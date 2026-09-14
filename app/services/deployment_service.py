"""
End-to-end deployment orchestration service.

Responsibilities:
- Load a topology from the database
- Parse topology YAML
- Create a GNS3 project
- Create GNS3 nodes
- Create GNS3 links
- Start nodes
- Configure devices through Netmiko when possible
- Run validations
- Generate deployment report
- Update topology status
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.topology import Topology
from app.services.gns3_service import GNS3Service
from app.services.netmiko_service import NetmikoService
from app.services.validation_service import run_all_validations
from app.services.report_service import generate_markdown_report
from app.utils.yaml import parse_topology_yaml


logger = logging.getLogger(__name__)

netmiko = NetmikoService()


# ============================================================================
# CONSTANTES GNS3
# ============================================================================

C3745_IMAGE = "c3745-adventerprisek9-mz.124-15.T14.image"

C3745_PROPERTIES: Dict[str, Any] = {
    "platform": "c3745",
    "image": C3745_IMAGE,
    "ram": 256,
    "nvram": 256,
    "iomem": 5,
    "slot0": "GT96100-FE",
    "slot1": "NM-1FE-TX",
    "slot2": None,
    "slot3": None,
    "slot4": None,
    "idlepc": "0x602701e4",
    "idlemax": 500,
    "idlesleep": 30,
    "exec_area": 64,
    "mmap": True,
    "sparsemem": True,
    "auto_delete_disks": True,
}


# ============================================================================
# LECTURE DE LA TOPOLOGIE
# ============================================================================

def _get_topology_data(topology: Topology) -> Dict[str, Any]:
    """
    Parse the topology YAML and return a dictionary.
    """
    if not topology.yaml_content:
        raise ValueError(
            f"Topology {topology.id} does not contain YAML data"
        )

    try:
        data = parse_topology_yaml(topology.yaml_content)

        if not isinstance(data, dict):
            raise ValueError(
                "Parsed topology data is not a dictionary"
            )

        return data

    except Exception as exc:
        logger.exception(
            "Failed to parse topology %s",
            topology.id,
        )
        raise ValueError(
            f"Unable to parse topology YAML: {exc}"
        ) from exc


def _get_topology_devices(
    topology: Topology,
) -> List[Dict[str, Any]]:
    """
    Return all devices defined in:
    - management_network
    - lan_a
    - lan_b
    """
    data = _get_topology_data(topology)

    devices: List[Dict[str, Any]] = []

    for section_name in (
        "management_network",
        "lan_a",
        "lan_b",
    ):
        section = data.get(section_name, {})

        if not isinstance(section, dict):
            continue

        section_devices = section.get("devices", [])

        if not isinstance(section_devices, list):
            continue

        for device in section_devices:
            if isinstance(device, dict):
                devices.append(device)

    return devices


def _get_topology_connections(
    topology: Topology,
) -> List[Dict[str, Any]]:
    """
    Return all topology connections.
    """
    data = _get_topology_data(topology)

    connections = data.get("connections", [])

    if not isinstance(connections, list):
        return []

    return [
        connection
        for connection in connections
        if isinstance(connection, dict)
    ]


# ============================================================================
# NORMALISATION DES TYPES
# ============================================================================

def _normalize_device_type(
    device: Dict[str, Any],
) -> str:
    """
    Normalize device type from topology YAML.

    Examples:
        dynamips
        router
        c3745
        vpcs
        pc
        host
    """
    raw_type = str(
        device.get("device_type", "vpcs")
    ).strip().lower()

    aliases = {
        "router": "dynamips",
        "c3745": "dynamips",
        "ios": "dynamips",
        "dynamips": "dynamips",

        "pc": "vpcs",
        "host": "vpcs",
        "vpc": "vpcs",
        "vpcs": "vpcs",

        # GNS3 built-in Ethernet switch
        "switch": "ethernet_switch",
        "ethernet_switch": "ethernet_switch",
        "ethernet-switch": "ethernet_switch",
        "ethernet switch": "ethernet_switch",

        # GNS3 built-in NAT
        "nat": "nat",
    }

    return aliases.get(raw_type, raw_type)


# ============================================================================
# MAPPING DES INTERFACES
# ============================================================================

def _map_gns3_interface(
    device: Dict[str, Any],
    interface: str,
) -> str:
    """
    Convert logical topology interface names to the actual GNS3
    interface names.

    The topology may use:

        GigabitEthernet0/0
        GigabitEthernet0/1

    while the C3745 Dynamips router exposes:

        FastEthernet0/0
        FastEthernet0/1
        FastEthernet1/0

    Therefore we translate the logical interface to the real
    GNS3 interface.
    """

    if not interface:
        return "Ethernet0"

    interface = str(interface).strip()

    device_type = _normalize_device_type(device)

    if device_type == "dynamips":
        mapping = {
            "GigabitEthernet0/0": "FastEthernet0/0",
            "GigabitEthernet0/1": "FastEthernet0/1",
            "GigabitEthernet1/0": "FastEthernet1/0",

            "Gi0/0": "FastEthernet0/0",
            "Gi0/1": "FastEthernet0/1",
            "Gi1/0": "FastEthernet1/0",

            "Fa0/0": "FastEthernet0/0",
            "Fa0/1": "FastEthernet0/1",
            "Fa1/0": "FastEthernet1/0",
        }

        return mapping.get(interface, interface)

    if device_type == "vpcs":
        mapping = {
            "GigabitEthernet0/0": "Ethernet0",
            "GigabitEthernet0/1": "Ethernet0",
            "FastEthernet0/0": "Ethernet0",
            "FastEthernet0/1": "Ethernet0",
            "Ethernet0": "Ethernet0",
            "eth0": "Ethernet0",
        }

        return mapping.get(interface, interface)

    return interface


# ============================================================================
# CREATION DES NŒUDS GNS3
# ============================================================================

def _create_dynamips_router(
    gns3: GNS3Service,
    project_id: str,
    name: str,
    x: int,
    y: int,
) -> Dict[str, Any]:
    """
    Create a Cisco C3745 Dynamips router.

    Important:
    GNS3 expects Dynamips-specific parameters inside "properties".
    """

    properties = dict(C3745_PROPERTIES)

    return gns3.create_node(
        project_id=project_id,
        node_type="dynamips",
        name=name,
        compute_id="vm",
        properties=properties,
        x=x,
        y=y,
    )


def _create_vpcs(
    gns3: GNS3Service,
    project_id: str,
    name: str,
    x: int,
    y: int,
) -> Dict[str, Any]:
    """Create a GNS3 VPCS node."""

    return gns3.create_node(
        project_id=project_id,
        node_type="vpcs",
        name=name,
        compute_id="local",
        x=x,
        y=y,
    )


def _create_ethernet_switch(
    gns3: GNS3Service,
    project_id: str,
    name: str,
    x: int,
    y: int,
) -> Dict[str, Any]:
    """Create the GNS3 built-in Ethernet switch.

    The built-in switch must use compute_id=local.
    """

    return gns3.create_node(
        project_id=project_id,
        node_type="ethernet_switch",
        name=name,
        compute_id="local",
        x=x,
        y=y,
    )


def _create_nat(
    gns3: GNS3Service,
    project_id: str,
    name: str,
    x: int,
    y: int,
) -> Dict[str, Any]:
    """Create the GNS3 built-in NAT node."""

    return gns3.create_node(
        project_id=project_id,
        node_type="nat",
        name=name,
        compute_id="local",
        x=x,
        y=y,
    )


def _node_position(name: str, index: int) -> tuple[int, int]:
    """Return a stable graphical position for the requested topology.

    This prevents the previous index-based layout from putting every device
    on a diagonal line.  Unknown devices keep a deterministic fallback.
    """

    positions = {
        "PC1": (-650, 0),
        "SW1": (-450, 0),
        "R1": (-180, 0),
        "R2": (180, 0),
        "SW2": (450, 0),
        "PC2": (650, 0),
        "SWMGT": (0, 220),
        "NAT1": (0, 430),
    }

    if name in positions:
        return positions[name]

    return (index * 180, 600)


def _create_gns3_node(
    gns3: GNS3Service,
    project_id: str,
    device: Dict[str, Any],
    index: int,
) -> Dict[str, Any]:
    """
    Create one GNS3 node from a topology device.
    """

    name = device.get(
        "name",
        f"node_{index}",
    )

    device_type = _normalize_device_type(device)

    # Use explicit positions so the GNS3 project reflects the intended
    # topology instead of the old diagonal index-based layout.
    x, y = _node_position(name, index)

    if device_type == "dynamips":
        return _create_dynamips_router(
            gns3=gns3,
            project_id=project_id,
            name=name,
            x=x,
            y=y,
        )

    if device_type == "vpcs":
        return _create_vpcs(
            gns3=gns3,
            project_id=project_id,
            name=name,
            x=x,
            y=y,
        )

    if device_type == "ethernet_switch":
        return _create_ethernet_switch(
            gns3=gns3,
            project_id=project_id,
            name=name,
            x=x,
            y=y,
        )

    if device_type == "nat":
        return _create_nat(
            gns3=gns3,
            project_id=project_id,
            name=name,
            x=x,
            y=y,
        )

    raise ValueError(
        f"Unsupported GNS3 device type "
        f"'{device_type}' for device '{name}'"
    )


# ============================================================================
# RECHERCHE D'UN DEVICE PAR SON NOM
# ============================================================================

def _find_device(
    devices: List[Dict[str, Any]],
    name: str,
) -> Optional[Dict[str, Any]]:
    """
    Find a device by name.
    """

    for device in devices:
        if device.get("name") == name:
            return device

    return None


# ============================================================================
# DEPLOIEMENT PRINCIPAL
# ============================================================================

def deploy_topology(
    topology_id: int,
    deploy: bool = True,
    configure: bool = True,
    db: Session = None,
) -> Dict[str, Any]:
    """
    Deploy a topology to GNS3.

    Parameters:
        topology_id:
            Database topology ID.

        deploy:
            If True, start all GNS3 nodes.

        configure:
            If True, attempt device configuration through Netmiko.

        db:
            SQLAlchemy database session.

    Returns:
        Deployment result dictionary.
    """

    # ========================================================================
    # 0. VERIFICATION SESSION DATABASE
    # ========================================================================

    if db is None:
        raise ValueError(
            "Database session is required"
        )

    # ========================================================================
    # 1. RECUPERATION TOPOLOGIE
    # ========================================================================

    topology = (
        db.query(Topology)
        .filter(Topology.id == topology_id)
        .first()
    )

    if not topology:
        raise ValueError(
            f"Topology with ID {topology_id} not found"
        )

    # ========================================================================
    # INITIALISATION
    # ========================================================================

    topology.status = "deploying"
    db.commit()

    gns3: Optional[GNS3Service] = None

    results: Dict[str, Any] = {
        "nodes": [],
        "links": [],
        "errors": [],
        "configurations": [],
        "validation": [],
        "report": None,
        "nodes_started": False,
    }

    try:

        # ====================================================================
        # 2. PARSE TOPOLOGIE
        # ====================================================================

        devices = _get_topology_devices(topology)
        connections = _get_topology_connections(topology)

        if not devices:
            raise ValueError(
                f"No devices found in topology {topology_id}"
            )

        logger.info(
            "Topology %s contains %d devices and %d connections",
            topology_id,
            len(devices),
            len(connections),
        )

        # ====================================================================
        # 3. CREATION SERVICE GNS3
        # ====================================================================

        gns3 = GNS3Service()

        # ====================================================================
        # 4. CREATION PROJET GNS3
        # ====================================================================

        project_name = (
            f"DevNet2_{topology.id}_"
            f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        )

        logger.info(
            "Creating GNS3 project: %s",
            project_name,
        )

        project = gns3.create_project(
            project_name
        )

        # GNS3Service.create_project() retourne project_id
        project_id = project.get("project_id")

        # Compatibilité éventuelle avec une réponse GNS3 contenant id
        if not project_id:
            project_id = project.get("id")

        if not project_id:
            raise RuntimeError(
                "GNS3 did not return a project ID"
            )

        results["project"] = {
            "name": project_name,
            "id": project_id,
        }

        logger.info(
            "GNS3 project created: %s",
            project_id,
        )

        # ====================================================================
        # 5. CREATION DES NŒUDS
        # ====================================================================

        node_ids: Dict[str, str] = {}

        for index, device in enumerate(devices):

            name = device.get(
                "name",
                f"node_{index}",
            )

            try:

                node = _create_gns3_node(
                    gns3=gns3,
                    project_id=project_id,
                    device=device,
                    index=index,
                )

                node_id = (
                    node.get("node_id")
                    or node.get("id")
                )

                if not node_id:
                    raise RuntimeError(
                        f"GNS3 did not return a node ID "
                        f"for {name}"
                    )

                node_ids[name] = node_id

                results["nodes"].append({
                    "name": name,
                    "id": node_id,
                    "node_id": node_id,
                    "status": "created",
                    "node_type": _normalize_device_type(
                        device
                    ),
                })

                logger.info(
                    "Created GNS3 node %s (%s)",
                    name,
                    node_id,
                )

            except Exception as exc:

                error_message = (
                    f"Failed to create node {name}: {exc}"
                )

                logger.exception(
                    error_message
                )

                results["errors"].append(
                    error_message
                )

        # ====================================================================
        # 6. VERIFICATION NŒUDS
        # ====================================================================

        if not node_ids:

            raise RuntimeError(
                "No GNS3 nodes were created"
            )

        # ====================================================================
        # 7. CREATION DES LIENS
        # ====================================================================

        for connection in connections:

            source_name = connection.get(
                "source"
            )

            target_name = connection.get(
                "target"
            )

            if not source_name or not target_name:

                results["errors"].append(
                    "Invalid connection: "
                    f"{connection}"
                )

                continue

            source_node_id = node_ids.get(
                source_name
            )

            target_node_id = node_ids.get(
                target_name
            )

            if not source_node_id:

                error_message = (
                    f"Source node '{source_name}' "
                    "was not created"
                )

                logger.warning(
                    error_message
                )

                results["errors"].append(
                    error_message
                )

                continue

            if not target_node_id:

                error_message = (
                    f"Target node '{target_name}' "
                    "was not created"
                )

                logger.warning(
                    error_message
                )

                results["errors"].append(
                    error_message
                )

                continue

            source_device = _find_device(
                devices,
                source_name,
            )

            target_device = _find_device(
                devices,
                target_name,
            )

            if source_device is None:
                source_device = {}

            if target_device is None:
                target_device = {}

            # ---------------------------------------------------------------
            # Interfaces logiques
            # ---------------------------------------------------------------

            source_interface = connection.get(
                "source_interface",
                "Ethernet0",
            )

            target_interface = connection.get(
                "target_interface",
                "Ethernet0",
            )

            # ---------------------------------------------------------------
            # Mapping vers les vraies interfaces GNS3
            # ---------------------------------------------------------------

            source_port = _map_gns3_interface(
                source_device,
                source_interface,
            )

            target_port = _map_gns3_interface(
                target_device,
                target_interface,
            )

            logger.info(
                "Creating link: %s:%s -> %s:%s",
                source_name,
                source_port,
                target_name,
                target_port,
            )

            try:

                link = gns3.create_link(
                    project_id=project_id,
                    source_node_id=source_node_id,
                    source_port=source_port,
                    target_node_id=target_node_id,
                    target_port=target_port,
                )

                link_id = (
                    link.get("link_id")
                    or link.get("id")
                )

                results["links"].append({
                    "source": source_name,
                    "target": target_name,
                    "source_interface": source_port,
                    "target_interface": target_port,
                    "id": link_id,
                    "status": "created",
                })

                logger.info(
                    "Link created successfully: "
                    "%s -> %s",
                    source_name,
                    target_name,
                )

            except Exception as exc:

                error_message = (
                    f"Failed to create link "
                    f"{source_name} ({source_port}) -> "
                    f"{target_name} ({target_port}): "
                    f"{exc}"
                )

                logger.exception(
                    error_message
                )

                results["errors"].append(
                    error_message
                )

        # ====================================================================
        # 8. DEMARRAGE DES NŒUDS
        # ====================================================================

        if deploy:

            try:

                logger.info(
                    "Starting all nodes in project %s",
                    project_id,
                )

                gns3.start_all_nodes(
                    project_id
                )

                results["nodes_started"] = True

                logger.info(
                    "All GNS3 nodes started"
                )

                # Les routeurs Dynamips peuvent nécessiter plusieurs secondes
                # avant de terminer leur démarrage et d'afficher le prompt Cisco.
                # Attendre avant Netmiko/validation évite de capturer le dialogue
                # initial de configuration comme s'il s'agissait d'une erreur.
                startup_wait = 20
                logger.info(
                    "Waiting %s seconds for GNS3/Cisco nodes to finish booting",
                    startup_wait,
                )
                import time
                time.sleep(startup_wait)

            except Exception as exc:

                error_message = (
                    f"Failed to start GNS3 nodes: {exc}"
                )

                logger.exception(
                    error_message
                )

                results["errors"].append(
                    error_message
                )

        # ====================================================================
        # 9. CONFIGURATION NETMIKO
        # ====================================================================

        if configure:

            for device in devices:

                device_name = device.get(
                    "name",
                    "unknown",
                )

                management_ip = device.get(
                    "management_ip"
                )

                device_type = _normalize_device_type(
                    device
                )

                # ------------------------------------------------------------
                # VPCS
                # ------------------------------------------------------------

                if device_type == "vpcs":

                    results["configurations"].append({
                        "device": device_name,
                        "status": "skipped",
                        "reason": (
                            "VPCS configuration is not performed "
                            "through Netmiko"
                        ),
                    })

                    continue

                # ------------------------------------------------------------
                # Pas d'adresse de management
                # ------------------------------------------------------------

                if not management_ip:

                    results["configurations"].append({
                        "device": device_name,
                        "status": "skipped",
                        "reason": (
                            "No management_ip configured"
                        ),
                    })

                    continue

                # ------------------------------------------------------------
                # Configuration du routeur
                # ------------------------------------------------------------

                configuration_ok = True

                interfaces = device.get(
                    "interfaces",
                    [],
                )

                if not isinstance(
                    interfaces,
                    list,
                ):
                    interfaces = []

                for interface in interfaces:

                    if not isinstance(
                        interface,
                        dict,
                    ):
                        continue

                    ip_address = interface.get(
                        "ip_address"
                    )

                    if not ip_address:
                        continue

                    interface_name = interface.get(
                        "name"
                    )

                    subnet_mask = interface.get(
                        "subnet_mask"
                    )

                    if not interface_name:
                        continue

                    try:

                        # Mapping de l'interface topology
                        # vers l'interface réelle C3745
                        real_interface = (
                            _map_gns3_interface(
                                device,
                                interface_name,
                            )
                        )

                        netmiko.configure_ip_address(
                            name=device_name,
                            management_ip=management_ip,
                            interface=real_interface,
                            ip_address=ip_address,
                            subnet_mask=subnet_mask,
                        )

                        logger.info(
                            "Configured %s %s with %s",
                            device_name,
                            real_interface,
                            ip_address,
                        )

                    except Exception as exc:

                        configuration_ok = False

                        error_message = (
                            f"Failed to configure "
                            f"{device_name} "
                            f"interface "
                            f"{interface_name}: "
                            f"{exc}"
                        )

                        logger.error(
                            error_message
                        )

                        results["errors"].append(
                            error_message
                        )

                # ------------------------------------------------------------
                # Route statique
                # ------------------------------------------------------------

                if device_type == "dynamips":

                    try:

                        # Si une route est explicitement définie
                        # dans le YAML, on l'utilise.
                        static_routes = device.get(
                            "static_routes",
                            [],
                        )

                        if isinstance(
                            static_routes,
                            list,
                        ) and static_routes:

                            for route in static_routes:

                                if not isinstance(
                                    route,
                                    dict,
                                ):
                                    continue

                                destination = route.get(
                                    "destination",
                                    "0.0.0.0",
                                )

                                mask = route.get(
                                    "mask",
                                    "0.0.0.0",
                                )

                                next_hop = route.get(
                                    "next_hop"
                                )

                                if not next_hop:
                                    continue

                                netmiko.configure_static_route(
                                    name=device_name,
                                    management_ip=management_ip,
                                    destination=destination,
                                    mask=mask,
                                    next_hop=next_hop,
                                )

                        # ----------------------------------------------------
                        # Aucun route statique explicite
                        # ----------------------------------------------------

                        else:

                            logger.info(
                                "No explicit static route "
                                "defined for %s; skipping",
                                device_name,
                            )

                    except Exception as exc:

                        configuration_ok = False

                        error_message = (
                            f"Failed to configure "
                            f"static route for "
                            f"{device_name}: {exc}"
                        )

                        logger.error(
                            error_message
                        )

                        results["errors"].append(
                            error_message
                        )

                # ------------------------------------------------------------
                # Résultat configuration
                # ------------------------------------------------------------

                results["configurations"].append({
                    "device": device_name,
                    "status": (
                        "configured"
                        if configuration_ok
                        else "failed"
                    ),
                })

        # ====================================================================
        # 10. VALIDATION
        # ====================================================================

        try:

            validation_results = (
                run_all_validations(
                    topology
                )
            )

            results["validation"] = (
                validation_results
            )

        except Exception as exc:

            error_message = (
                f"Validation failed: {exc}"
            )

            logger.exception(
                error_message
            )

            results["validation"] = {
                "status": "FAILED",
                "details": str(exc),
            }

            results["errors"].append(
                error_message
            )

        # ====================================================================
        # 11. GENERATION RAPPORT
        # ====================================================================

        try:

            report_path = (
                generate_markdown_report(
                    topology_id,
                    db,
                )
            )

            results["report"] = (
                report_path
            )

        except Exception as exc:

            error_message = (
                f"Report generation failed: {exc}"
            )

            logger.exception(
                error_message
            )

            results["report"] = None

            results["errors"].append(
                error_message
            )

        # ====================================================================
        # 12. STATUT FINAL
        # ====================================================================

        if results["errors"]:

            topology.status = "failed"

            logger.warning(
                "Deployment of topology %s completed "
                "with %d error(s)",
                topology_id,
                len(results["errors"]),
            )

        else:

            topology.status = "deployed"

            logger.info(
                "Deployment of topology %s completed successfully",
                topology_id,
            )

        db.commit()

    # =========================================================================
    # ERREUR GENERALE
    # =========================================================================

    except Exception as exc:

        logger.exception(
            "Deployment failed for topology %s",
            topology_id,
        )

        topology.status = "failed"

        try:
            db.commit()
        except Exception:
            db.rollback()

        results["errors"].append(
            f"Deployment failed: {exc}"
        )

        results["report"] = None

    # =========================================================================
    # NETTOYAGE
    # =========================================================================

    finally:

        if gns3 is not None:

            try:
                gns3.close()

            except Exception as exc:

                logger.warning(
                    "Error while closing GNS3 service: %s",
                    exc,
                )

        try:

            netmiko.close_all()

        except Exception as exc:

            logger.warning(
                "Error while closing Netmiko connections: %s",
                exc,
            )

    return results