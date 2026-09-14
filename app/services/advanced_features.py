"""Advanced features: VLAN, OSPF, DHCP, dynamic router management, and inconsistency detection."""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import ipaddress

from app.models.database import get_db
from app.models.topology import Topology, Device, Connection, Interface
from app.schemas.topology import TopologySchema, DeviceSchema, ConnectionSchema
from app.services.netmiko_service import NetmikoService
from app.utils.yaml import parse_topology_yaml

logger = logging.getLogger(__name__)
netmiko = NetmikoService()


def configure_vlans(topology_id: int, vlan_configs: List[Dict[str, Any]], db) -> Dict[str, Any]:
    """Configure VLANs on switches."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise ValueError(f"Topology with ID {topology_id} not found")

    results = []
    for vlan_config in vlan_configs:
        device_name = vlan_config.get("device")
        device = db.query(Device).filter(Device.name == device_name, Device.topology_id == topology_id).first()
        if not device:
            raise ValueError(f"Device '{device_name}' not found in topology {topology_id}")
        if device.device_type != "ethernet_switch":
            raise ValueError(f"Device '{device_name}' is not a switch")

        vlans = []
        for vlan in vlan_config.get("vlans", []):
            vlans.append({"id": vlan["id"], "name": vlan["name"]})

        result = netmiko.configure_vlan(device.name, device.management_ip, vlans)
        results.append(result)

    return {"topology_id": topology_id, "vlans_configured": results}


def configure_ospf(topology_id: int, router_id: str, networks: List[str], db) -> Dict[str, Any]:
    """Configure OSPF routing on routers."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise ValueError(f"Topology with ID {topology_id} not found")

    results = []
    routers = db.query(Device).filter(Device.topology_id == topology_id, Device.device_type == "qemu").all()
    for router in routers:
        if router.name.startswith("R"):
            result = netmiko.configure_ospf(router.name, router.management_ip, router_id, networks)
            results.append(result)

    return {"topology_id": topology_id, "ospf_configured": results}


def configure_dhcp(topology_id: int, pool_name: str, subnet: str, gateway: str, dns: str, db) -> Dict[str, Any]:
    """Configure DHCP server on a router."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise ValueError(f"Topology with ID {topology_id} not found")

    # Find a router that can serve DHCP
    routers = db.query(Device).filter(Device.topology_id == topology_id, Device.device_type == "qemu", Device.name.startswith("R")).all()
    if not routers:
        raise ValueError(f"No routers found in topology {topology_id}")

    router = routers[0]
    result = netmiko.configure_dhcp(router.name, router.management_ip, pool_name, subnet, gateway, dns)

    return {"topology_id": topology_id, "dhcp_configured": result}


def add_router(topology_id: int, router_data: DeviceSchema, db) -> Dict[str, Any]:
    """Add a new router to an existing topology dynamically."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise ValueError(f"Topology with ID {topology_id} not found")

    # Validate the router name doesn't already exist
    existing = db.query(Device).filter(Device.name == router_data.name, Device.topology_id == topology_id).first()
    if existing:
        raise ValueError(f"Device '{router_data.name}' already exists in topology {topology_id}")

    # Add the new router to the database
    new_router = Device(
        name=router_data.name,
        device_type="qemu",
        image=router_data.image or "gns3/qemu:latest",
        management_ip=router_data.management_ip,
        ram=router_data.ram or 512,
        console_type=router_data.console_type or "telnet",
        console_port=router_data.console_port or 5005,
        topology_id=topology_id,
    )
    db.add(new_router)
    db.flush()

    # Add interfaces
    for interface_data in router_data.interfaces:
        interface = Interface(
            name=interface_data.name,
            ip_address=interface_data.ip_address,
            subnet_mask=interface_data.subnet_mask,
            device_id=new_router.id,
        )
        db.add(interface)

    db.commit()
    db.refresh(new_router)

    return {"message": "Router added successfully", "router": new_router.name, "id": new_router.id}


def add_connection(topology_id: int, connection_data: ConnectionSchema, db) -> Dict[str, Any]:
    """Add a new connection to an existing topology."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise ValueError(f"Topology with ID {topology_id} not found")

    source = db.query(Device).filter(Device.name == connection_data.source, Device.topology_id == topology_id).first()
    target = db.query(Device).filter(Device.name == connection_data.target, Device.topology_id == topology_id).first()
    if not source or not target:
        raise ValueError(f"Connection endpoints not found in topology {topology_id}")

    connection = Connection(
        source_device=connection_data.source,
        target_device=connection_data.target,
        source_interface=connection_data.source_interface,
        target_interface=connection_data.target_interface,
        topology_id=topology_id,
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)

    return {"message": "Connection added successfully", "id": connection.id}


def detect_inconsistencies(topology_id: int, db) -> Dict[str, Any]:
    """Detect inconsistencies between YAML topology and GNS3 project."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise ValueError(f"Topology with ID {topology_id} not found")

    inconsistencies = []

    # Check for devices in DB but not in YAML
    try:
        data = parse_topology_yaml(topology.yaml_content)
        yaml_devices = set()
        for section in ["management_network", "lan_a", "lan_b"]:
            for device in data.get(section, {}).get("devices", []):
                yaml_devices.add(device["name"])

        db_devices = set(d.name for d in topology.devices)
        for device in sorted(db_devices - yaml_devices):
            inconsistencies.append({"type": "device_only_in_db", "device": device, "message": "Device exists in database but not in YAML"})
        for device in sorted(yaml_devices - db_devices):
            inconsistencies.append({"type": "device_only_in_yaml", "device": device, "message": "Device exists in YAML but not in database"})

        # Check connections
        yaml_connections = {(c["source"], c["target"]) for c in data.get("connections", [])}
        db_connections = {(c.source_device, c.target_device) for c in topology.connections}
        for conn in sorted(yaml_connections - db_connections):
            inconsistencies.append({"type": "connection_only_in_yaml", "connection": list(conn), "message": "Connection exists in YAML but not in database"})
        for conn in sorted(db_connections - yaml_connections):
            inconsistencies.append({"type": "connection_only_in_db", "connection": list(conn), "message": "Connection exists in database but not in YAML"})

        # Validate IP addresses
        for device in topology.devices:
            for interface in device.interfaces:
                if interface.ip_address:
                    try:
                        ipaddress.ip_address(interface.ip_address)
                    except ValueError:
                        inconsistencies.append({"type": "invalid_ip", "device": device.name, "interface": interface.name, "message": f"Invalid IP address: {interface.ip_address}"})

        # Validate subnet consistency
        for section in ["management_network", "lan_a", "lan_b"]:
            subnet = data.get(section, {}).get("subnet")
            if subnet:
                try:
                    network = ipaddress.ip_network(subnet, strict=False)
                    for device in data.get(section, {}).get("devices", []):
                        mgmt_ip = device.get("management_ip")
                        if mgmt_ip and ipaddress.ip_address(mgmt_ip) not in network:
                            inconsistencies.append({"type": "ip_outside_subnet", "device": device["name"], "ip": mgmt_ip, "subnet": subnet, "message": "Management IP is outside the subnet"})
                except ValueError as e:
                    inconsistencies.append({"type": "invalid_subnet", "section": section, "message": str(e)})

    except Exception as e:
        inconsistencies.append({"type": "parse_error", "message": str(e)})

    return {
        "topology_id": topology_id,
        "inconsistencies": inconsistencies,
        "status": "ok" if not inconsistencies else "inconsistent",
        "count": len(inconsistencies),
    }


def generate_schema_diagram(topology_id: int, db) -> Dict[str, Any]:
    """Generate a Mermaid diagram for the topology."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise ValueError(f"Topology with ID {topology_id} not found")

    try:
        data = parse_topology_yaml(topology.yaml_content)
    except Exception as e:
        raise ValueError(f"Could not parse topology YAML: {e}")

    nodes = []
    for section in ["management_network", "lan_a", "lan_b"]:
        for device in data.get(section, {}).get("devices", []):
            nodes.append(f"    {device['name']}[{device['name']} - {device['device_type']}]")

    links = []
    for conn in data.get("connections", []):
        links.append(f"    {conn['source']} --- {conn['target']}")

    mermaid = "graph TD\n" + "\n".join(nodes) + "\n" + "\n".join(links)

    return {
        "topology_id": topology_id,
        "mermaid": mermaid,
        "format": "mermaid",
    }


def apply_advanced_features(topology_id: int, features: Dict[str, Any], db) -> Dict[str, Any]:
    """Apply a set of advanced features to a topology."""
    results = {}

    if features.get("vlans"):
        results["vlans"] = configure_vlans(topology_id, features["vlans"], db)
    if features.get("ospf"):
        results["ospf"] = configure_ospf(topology_id, features["ospf"]["router_id"], features["ospf"]["networks"], db)
    if features.get("dhcp"):
        results["dhcp"] = configure_dhcp(topology_id, features["dhcp"]["pool_name"], features["dhcp"]["subnet"], features["dhcp"]["gateway"], features["dhcp"]["dns"], db)
    if features.get("add_router"):
        results["add_router"] = add_router(topology_id, features["add_router"], db)
    if features.get("add_connection"):
        results["add_connection"] = add_connection(topology_id, features["add_connection"], db)
    if features.get("detect_inconsistencies"):
        results["inconsistencies"] = detect_inconsistencies(topology_id, db)
    if features.get("generate_diagram"):
        results["diagram"] = generate_schema_diagram(topology_id, db)

    return results