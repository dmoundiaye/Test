"""End-to-end deployment orchestration service."""

import logging
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from app.models.database import get_db
from app.models.topology import Topology, Device, Connection, Interface
from app.services.gns3_service import GNS3Service
from app.services.netmiko_service import NetmikoService
from app.services.validation_service import run_all_validations
from app.services.report_service import generate_markdown_report
from app.utils.logger import setup_logging

logger = logging.getLogger(__name__)
netmiko = NetmikoService()


def _get_topology_devices(topology: Topology) -> List[Dict[str, Any]]:
    """Get device configuration from topology YAML."""
    try:
        data = json.loads(topology.yaml_content)
        devices = []
        for section in ["management_network", "lan_a", "lan_b"]:
            for device in data.get(section, {}).get("devices", []):
                devices.append(device)
        return devices
    except Exception as e:
        logger.error(f"Could not parse topology YAML: {e}")
        return []


def _get_topology_connections(topology: Topology) -> List[Dict[str, Any]]:
    """Get connections from topology YAML."""
    try:
        data = json.loads(topology.yaml_content)
        return data.get("connections", [])
    except Exception as e:
        logger.error(f"Could not parse connections: {e}")
        return []


def deploy_topology(topology_id: int, deploy: bool = True, configure: bool = True) -> Dict[str, Any]:
    """Deploy a topology to GNS3, configure devices via Netmiko, and run validation."""
    db = get_db()
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise ValueError(f"Topology with ID {topology_id} not found")

    topology.status = "deploying"
    db.commit()

    gns3 = GNS3Service()
    results: Dict[str, Any] = {"nodes": [], "links": [], "errors": []}

    try:
        # 1. Create GNS3 project
        project_name = f"DevNet2_{topology.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        project = gns3.create_project(project_name)
        project_id = project.get("id")
        results["project"] = {"name": project_name, "id": project_id}

        # 2. Create nodes
        devices = _get_topology_devices(topology)
        for idx, device in enumerate(devices):
            node_type = device.get("device_type", "qemu")
            template = device.get("image", "qemu")
            name = device.get("name", f"node_{idx}")
            try:
                node = gns3.create_node(
                    project_id=project_id,
                    node_type=node_type,
                    name=name,
                    template=template,
                    x=idx * 200,
                    y=idx * 100,
                )
                results["nodes"].append({"name": name, "id": node.get("id"), "status": "created"})
            except Exception as e:
                logger.error(f"Failed to create node {name}: {e}")
                results["errors"].append(f"Failed to create node {name}: {e}")

        # 3. Create links
        connections = _get_topology_connections(topology)
        node_ids = {n["name"]: n["id"] for n in results["nodes"] if n.get("status") == "created"}
        for conn in connections:
            try:
                source = node_ids.get(conn.get("source"))
                target = node_ids.get(conn.get("target"))
                if not source or not target:
                    logger.warning(f"Skipping link {conn.get('source')}->{conn.get('target')}: missing node")
                    continue
                link = gns3.create_link(
                    project_id=project_id,
                    source_node_id=source["id"],
                    source_port=conn.get("source_interface", "eth0"),
                    target_node_id=target["id"],
                    target_port=conn.get("target_interface", "eth0"),
                )
                results["links"].append({"source": conn.get("source"), "target": conn.get("target"), "id": link.get("id")})
            except Exception as e:
                logger.error(f"Failed to create link {conn.get('source')}->{conn.get('target')}: {e}")
                results["errors"].append(f"Failed to create link {conn.get('source')}->{conn.get('target')}: {e}")

        # 4. Start all nodes
        gns3.start_all_nodes(project_id)
        results["nodes_started"] = True

        # 5. Configure devices via Netmiko
        if configure:
            for device in devices:
                if device.get("management_ip") and device.get("device_type") != "nat":
                    interface_configs = []
                    for interface in device.get("interfaces", []):
                        if interface.get("ip_address"):
                            interface_configs.append(netmiko.configure_ip_address(
                                name=device["name"],
                                management_ip=device["management_ip"],
                                interface=interface["name"],
                                ip_address=interface["ip_address"],
                                subnet_mask=interface["subnet_mask"],
                            ))
                    # Add static routes for routers
                    if device.get("name").startswith("R"):
                        netmiko.configure_static_route(
                            name=device["name"],
                            management_ip=device["management_ip"],
                            destination="0.0.0.0",
                            mask="0.0.0.0",
                            next_hop="10.0.0.2" if device["name"] == "R1" else "10.0.0.1",
                        )
                    results["configurations"].append({"device": device["name"], "status": "configured"})
        else:
            results["configurations"] = []

        # 6. Run validation
        results["validation"] = run_all_validations(topology)

        # 7. Generate report
        report_path = generate_markdown_report(topology_id, db)
        results["report"] = report_path

        topology.status = "deployed"
        db.commit()

    except Exception as e:
        logger.exception(f"Deployment failed for topology {topology_id}: {e}")
        topology.status = "failed"
        db.commit()
        results["errors"].append(str(e))
        results["report"] = None

    finally:
        gns3.close()
        netmiko.close_all()
        db.close()

    return results