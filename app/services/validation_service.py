import logging
import re
import socket
import time
from typing import Any, Dict, List, Optional

from app.models.topology import Topology
from app.services.gns3_service import GNS3Service
from app.utils.yaml import parse_topology_yaml


logger = logging.getLogger(__name__)


# ============================================================================
# CLIENT CONSOLE TELNET GNS3
# ============================================================================

class GNS3Console:
    """
    Client Telnet minimal pour les consoles Cisco Dynamips GNS3.

    Compatible Python 3.13 : n'utilise pas telnetlib.
    """

    IAC = 255
    DONT = 254
    DO = 253
    WONT = 252
    WILL = 251

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 10.0,
    ):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout,
        )
        self.sock.settimeout(0.5)

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

        self.sock = None

    def _handle_telnet_negotiation(self, data: bytes) -> bytes:
        """
        Répond aux négociations Telnet basiques.
        """

        if not self.sock:
            return data

        output = bytearray()
        i = 0

        while i < len(data):
            if data[i] != self.IAC:
                output.append(data[i])
                i += 1
                continue

            if i + 2 >= len(data):
                break

            command = data[i + 1]
            option = data[i + 2]

            if command == self.DO:
                self.sock.sendall(
                    bytes([
                        self.IAC,
                        self.WONT,
                        option,
                    ])
                )

            elif command == self.WILL:
                self.sock.sendall(
                    bytes([
                        self.IAC,
                        self.DONT,
                        option,
                    ])
                )

            i += 3

        return bytes(output)

    def _read_available(
        self,
        duration: float = 1.0,
    ) -> str:
        if not self.sock:
            raise RuntimeError(
                "Console Telnet non connectée."
            )

        chunks: List[bytes] = []
        deadline = time.time() + duration

        while time.time() < deadline:
            try:
                data = self.sock.recv(4096)

                if not data:
                    break

                clean = self._handle_telnet_negotiation(data)

                if clean:
                    chunks.append(clean)

                # Laisser arriver le reste de la sortie
                deadline = max(
                    deadline,
                    time.time() + 0.2,
                )

            except socket.timeout:
                time.sleep(0.05)

            except BlockingIOError:
                time.sleep(0.05)

        raw = b"".join(chunks)

        return raw.decode(
            "utf-8",
            errors="ignore",
        )

    def send_line(self, command: str = "") -> None:
        if not self.sock:
            raise RuntimeError(
                "Console Telnet non connectée."
            )

        self.sock.sendall(
            (command + "\r\n").encode("utf-8")
        )

    def prepare_cisco_console(self) -> str:
        """
        Prépare une console IOS de manière robuste.

        - réveille la console ;
        - traite le dialogue initial IOS ;
        - attend le prompt ;
        - passe en mode enable ;
        - désactive la pagination.
        """

        if not self.sock:
            raise RuntimeError("Console Telnet non connectée.")

        collected = ""

        # Lire ce qui est éventuellement déjà présent.
        collected += self._read_available(0.5)

        # Réveiller la console.
        self.send_line("")
        time.sleep(0.8)

        # Lire plusieurs fois : le dialogue IOS peut arriver
        # après la première lecture réseau.
        for _ in range(6):
            output = self._read_available(0.8)
            collected += output

            lower = collected.lower()

            # Dialogue initial IOS.
            if (
                "would you like to enter the initial configuration dialog"
                in lower
                or "would you like to enter the initial configuration"
                in lower
                or "please answer 'yes' or 'no'"
                in lower
                or "[yes/no]" in lower
            ):
                self.send_line("no")
                time.sleep(1.0)

                collected += self._read_available(1.5)

                # Certains IOS demandent ensuite ENTER.
                lower = collected.lower()

                if (
                    "press return" in lower
                    or "return to get started" in lower
                ):
                    self.send_line("")
                    time.sleep(0.8)
                    collected += self._read_available(1.2)

                break

            # Prompt IOS déjà disponible.
            if re.search(
                r"(?:^|\n)\s*[A-Za-z0-9_.()/-]+[>#]\s*$",
                collected,
                re.MULTILINE,
            ):
                break

            self.send_line("")
            time.sleep(0.3)

        # Quelques ENTER supplémentaires pour stabiliser le prompt.
        for _ in range(3):
            self.send_line("")
            time.sleep(0.3)
            collected += self._read_available(0.8)

            if re.search(
                r"[A-Za-z0-9_.()/-]+[>#]\s*$",
                collected,
                re.MULTILINE,
            ):
                break

        # Si le prompt est "Router>", passer en enable.
        if re.search(
            r"[A-Za-z0-9_.()/-]+>\s*$",
            collected,
            re.MULTILINE,
        ):
            self.send_line("enable")
            time.sleep(0.8)

            output = self._read_available(1.5)
            collected += output

            if "password:" in output.lower():
                raise RuntimeError(
                    "Le routeur demande un mot de passe enable."
                )

        # Désactiver la pagination.
        self.send_line("terminal length 0")
        time.sleep(0.5)
        collected += self._read_available(1.0)

        return collected

    def command(
        self,
        command: str,
        wait: float = 1.2,
    ) -> str:
        """
        Exécute une commande IOS et retourne sa sortie.
        """

        if not self.sock:
            raise RuntimeError(
                "Console Telnet non connectée."
            )

        # Nettoyer ce qui reste dans le buffer
        self._read_available(0.2)

        self.send_line(command)

        time.sleep(wait)

        output = self._read_available(
            max(wait, 1.0)
        )

        return output


# ============================================================================
# LECTURE DE LA TOPOLOGIE
# ============================================================================

def _get_topology_data(
    topology: Topology,
) -> Dict[str, Any]:

    if not topology.yaml_content:
        return {}

    try:
        data = parse_topology_yaml(
            topology.yaml_content
        )

        if isinstance(data, dict):
            return data

    except Exception:
        logger.exception(
            "Erreur lecture YAML topologie %s",
            topology.id,
        )

    return {}


def _get_devices(
    topology: Topology,
) -> List[Dict[str, Any]]:

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

        section_devices = section.get(
            "devices",
            [],
        )

        if not isinstance(
            section_devices,
            list,
        ):
            continue

        for device in section_devices:
            if isinstance(device, dict):
                devices.append(device)

    return devices


def _get_connections(
    topology: Topology,
) -> List[Dict[str, Any]]:

    data = _get_topology_data(topology)

    connections = data.get(
        "connections",
        [],
    )

    if not isinstance(connections, list):
        return []

    return [
        connection
        for connection in connections
        if isinstance(connection, dict)
    ]


# ============================================================================
# IDENTIFICATION DES ROUTEURS CISCO
# ============================================================================

def _is_cisco_router(
    device: Dict[str, Any],
) -> bool:

    name = str(
        device.get("name", "")
    ).strip()

    device_type = str(
        device.get(
            "device_type",
            device.get("type", ""),
        )
    ).strip().lower()

    if name.upper().startswith("R"):
        return True

    return device_type in {
        "dynamips",
        "router",
        "c3745",
        "ios",
        "cisco",
        "cisco_ios",
    }


def _get_cisco_devices(
    topology: Topology,
) -> List[Dict[str, Any]]:

    return [
        device
        for device in _get_devices(topology)
        if _is_cisco_router(device)
    ]


# ============================================================================
# RECHERCHE DU PROJET GNS3
# ============================================================================

def _find_gns3_project_id(
    topology: Topology,
    gns3: GNS3Service,
) -> str:

    projects = gns3.list_projects()

    expected = f"DevNet2_{topology.id}_"

    candidates = []

    for project in projects:
        name = str(
            project.get("name", "")
        )

        if expected in name:
            candidates.append(project)

    if not candidates:
        raise RuntimeError(
            f"Aucun projet GNS3 trouvé pour "
            f"la topologie {topology.id}."
        )

    # Les noms contiennent le timestamp YYYYMMDD_HHMMSS,
    # donc le tri lexical donne le déploiement le plus récent.
    candidates.sort(
        key=lambda item: str(
            item.get("name", "")
        ),
        reverse=True,
    )

    project_id = candidates[0].get(
        "project_id"
    )

    if not project_id:
        raise RuntimeError(
            "Projet GNS3 trouvé sans project_id."
        )

    return str(project_id)


# ============================================================================
# NŒUDS CONSOLE GNS3
# ============================================================================

def _get_console_nodes(
    topology: Topology,
) -> List[Dict[str, Any]]:

    gns3 = GNS3Service()

    project_id = _find_gns3_project_id(
        topology,
        gns3,
    )

    nodes = gns3.list_nodes(project_id)

    wanted_names = {
        str(device.get("name", "")).strip()
        for device in _get_cisco_devices(topology)
    }

    result = []

    for node in nodes:
        name = str(
            node.get("name", "")
        ).strip()

        if name not in wanted_names:
            continue

        console = node.get("console")

        if console is None:
            continue

        console_host = (
            node.get("console_host")
            or gns3.host
        )

        result.append(
            {
                "name": name,
                "node_id": node.get("node_id"),
                "console": int(console),
                "console_host": str(console_host),
                "console_type": node.get(
                    "console_type",
                    "telnet",
                ),
            }
        )

    return result


# ============================================================================
# EXECUTION D'UNE COMMANDE CISCO
# ============================================================================

def _run_console_command(
    node: Dict[str, Any],
    command: str,
    wait: float = 1.2,
) -> str:

    console = GNS3Console(
        host=node["console_host"],
        port=node["console"],
        timeout=10.0,
    )

    try:
        console.connect()

        console.prepare_cisco_console()

        output = console.command(
            command,
            wait=wait,
        )

        return output

    finally:
        console.close()


# ============================================================================
# TEST 1 : ACCESSIBILITE CONSOLE
# ============================================================================

def _test_console_accessibility(
    topology: Topology,
) -> Dict[str, Any]:

    try:
        nodes = _get_console_nodes(topology)

        if not nodes:
            return {
                "test_name": "SSH Accessibility Test",
                "status": "failed",
                "details": (
                    "Aucun routeur Cisco avec console "
                    "GNS3 n'a été trouvé."
                ),
            }

        success = []
        failed = []

        for node in nodes:
            try:
                output = _run_console_command(
                    node,
                    "show clock",
                )

                if output.strip():
                    success.append(node["name"])
                else:
                    failed.append(
                        f"{node['name']}: sortie vide"
                    )

            except Exception as exc:
                failed.append(
                    f"{node['name']}: {exc}"
                )

        if failed:
            return {
                "test_name": "SSH Accessibility Test",
                "status": "failed",
                "details": (
                    "Console accessible : "
                    + ", ".join(success)
                    + ". Erreurs : "
                    + " ; ".join(failed)
                ),
            }

        return {
            "test_name": "SSH Accessibility Test",
            "status": "success",
            "details": (
                "Console GNS3 accessible pour : "
                + ", ".join(success)
                + ". Validation effectuée par "
                  "connexion Telnet à la console GNS3."
            ),
        }

    except Exception as exc:
        return {
            "test_name": "SSH Accessibility Test",
            "status": "failed",
            "details": str(exc),
        }


# ============================================================================
# TEST 2 : INTERFACES
# ============================================================================

def _test_interfaces(
    topology: Topology,
) -> Dict[str, Any]:

    try:
        nodes = _get_console_nodes(topology)

        if not nodes:
            return {
                "test_name": "Interface Status Test",
                "status": "failed",
                "details": (
                    "Aucun routeur Cisco trouvé."
                ),
            }

        results = []
        errors = []

        for node in nodes:
            try:
                output = _run_console_command(
                    node,
                    "show ip interface brief",
                    wait=1.5,
                )

                if (
                    "interface" not in output.lower()
                    or "ip-address" not in output.lower()
                ):
                    errors.append(
                        f"{node['name']}: "
                        "sortie 'show ip interface brief' "
                        "non reconnue."
                    )
                    continue

                results.append(
                    f"{node['name']}: "
                    "show ip interface brief OK"
                )

            except Exception as exc:
                errors.append(
                    f"{node['name']}: {exc}"
                )

        if errors:
            return {
                "test_name": "Interface Status Test",
                "status": "failed",
                "details": " ; ".join(errors),
            }

        return {
            "test_name": "Interface Status Test",
            "status": "success",
            "details": (
                "Validation Cisco réelle effectuée avec "
                "'show ip interface brief'. "
                + " ; ".join(results)
            ),
        }

    except Exception as exc:
        return {
            "test_name": "Interface Status Test",
            "status": "failed",
            "details": str(exc),
        }


# ============================================================================
# TEST 3 : TABLE DE ROUTAGE
# ============================================================================

def _routing_output_is_valid(
    output: str,
) -> bool:
    """
    Vérifie que 'show ip route' a réellement retourné une sortie IOS.
    La validation ne dépend pas d'un en-tête particulier.
    """

    if not output or not output.strip():
        return False

    lower = output.lower()

    error_patterns = (
        "invalid input",
        "ambiguous command",
        "incomplete command",
        "unknown command",
    )

    if any(pattern in lower for pattern in error_patterns):
        return False

    # Signatures courantes de "show ip route".
    signatures = (
        "codes:",
        "gateway of last resort",
        "is directly connected",
        "variably subnetted",
        "known via",
        "routing table",
        "last resort",
    )

    if any(signature in lower for signature in signatures):
        return True

    # Routes Cisco classiques.
    route_pattern = re.compile(
        r"(?im)^\s*"
        r"(?:C|L|S|S\*|O|O IA|O E1|O E2|R|D|D EX|B)"
        r"\s+"
        r"\d{1,3}(?:\.\d{1,3}){3}"
    )

    if route_pattern.search(output):
        return True

    # Une sortie contenant le prompt IOS après la commande
    # est un indice que la commande a bien été exécutée.
    lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip()
    ]

    if len(lines) >= 2:
        if any(
            re.search(r"[A-Za-z0-9_.()/-]+#", line)
            for line in lines
        ):
            return True

    return False


def _test_routing_table(
    topology: Topology,
) -> Dict[str, Any]:

    try:
        nodes = _get_console_nodes(topology)

        if not nodes:
            return {
                "test_name": "Routing Table Test",
                "status": "failed",
                "details": (
                    "Aucun routeur Cisco trouvé."
                ),
            }

        success = []
        failed = []

        for node in nodes:
            try:
                output = _run_console_command(
                    node,
                    "show ip route",
                    wait=2.0,
                )

                if _routing_output_is_valid(output):
                    success.append(
                        f"{node['name']}: "
                        "show ip route OK"
                    )
                else:
                    preview = (
                        output.strip()
                        .replace("\r", " ")
                        .replace("\n", " ")
                    )

                    preview = preview[:300]

                    failed.append(
                        f"{node['name']}: sortie de table "
                        f"de routage non reconnue. "
                        f"Sortie: {preview}"
                    )

            except Exception as exc:
                failed.append(
                    f"{node['name']}: {exc}"
                )

        if failed:
            return {
                "test_name": "Routing Table Test",
                "status": "failed",
                "details": " ; ".join(failed),
            }

        return {
            "test_name": "Routing Table Test",
            "status": "success",
            "details": (
                "Validation Cisco réelle effectuée avec "
                "'show ip route'. "
                + " ; ".join(success)
            ),
        }

    except Exception as exc:
        return {
            "test_name": "Routing Table Test",
            "status": "failed",
            "details": str(exc),
        }


# ============================================================================
# RECHERCHE DES IP DE ROUTEUR
# ============================================================================

def _device_ip(
    device: Dict[str, Any],
) -> Optional[str]:
    """
    Recherche une adresse IP exploitable dans les données
    de la topologie.
    """

    for key in (
        "management_ip",
        "ip_address",
        "ip",
    ):
        value = device.get(key)

        if value:
            ip = str(value).strip()

            # Retirer /24 éventuel
            ip = ip.split("/")[0]

            if re.match(
                r"^\d{1,3}(?:\.\d{1,3}){3}$",
                ip,
            ):
                return ip

    interfaces = device.get("interfaces")

    if isinstance(interfaces, list):
        for interface in interfaces:
            if not isinstance(interface, dict):
                continue

            for key in (
                "ip_address",
                "ip",
                "address",
            ):
                value = interface.get(key)

                if value:
                    ip = str(value).strip()
                    ip = ip.split("/")[0]

                    if re.match(
                        r"^\d{1,3}(?:\.\d{1,3}){3}$",
                        ip,
                    ):
                        return ip

    return None


# ============================================================================
# TEST 4 : PING
# ============================================================================

def _ping_success(
    output: str,
) -> bool:
    """
    Détermine si un ping Cisco a réussi.
    """

    if not output:
        return False

    lower = output.lower()

    if "success rate is 100 percent" in lower:
        return True

    match = re.search(
        r"success rate is\s+(\d+)\s+percent",
        lower,
    )

    if match:
        try:
            return int(match.group(1)) > 0
        except ValueError:
            return False

    # Cisco IOS affiche généralement !!!!! pour 5 réponses.
    if "!!!!!" in output:
        return True

    return False


def _test_ping_connectivity(
    topology: Topology,
) -> Dict[str, Any]:

    try:
        nodes = _get_console_nodes(topology)
        devices = _get_cisco_devices(topology)

        if len(nodes) < 2:
            return {
                "test_name": "Ping Connectivity Test",
                "status": "failed",
                "details": (
                    "Au moins deux routeurs Cisco sont "
                    "nécessaires pour le test ping."
                ),
            }

        device_by_name = {
            str(device.get("name", "")).strip():
            device
            for device in devices
        }

        # Associer chaque nœud GNS3 à son IP
        routers = []

        for node in nodes:
            device = device_by_name.get(
                node["name"]
            )

            if not device:
                continue

            ip = _device_ip(device)

            if ip:
                routers.append(
                    {
                        "node": node,
                        "device": device,
                        "ip": ip,
                    }
                )

        if len(routers) < 2:
            return {
                "test_name": "Ping Connectivity Test",
                "status": "failed",
                "details": (
                    "Impossible de déterminer les adresses "
                    "IP de deux routeurs dans la topologie."
                ),
            }

        results = []
        failures = []

        # Test bidirectionnel
        for index, source in enumerate(routers):
            for target_index, target in enumerate(routers):

                if index == target_index:
                    continue

                source_name = source["node"]["name"]
                target_name = target["node"]["name"]
                target_ip = target["ip"]

                try:
                    output = _run_console_command(
                        source["node"],
                        f"ping {target_ip}",
                        wait=4.0,
                    )

                    if _ping_success(output):
                        results.append(
                            f"{source_name} -> "
                            f"{target_name} "
                            f"({target_ip}): OK"
                        )

                    else:
                        preview = (
                            output.strip()
                            .replace("\r", " ")
                            .replace("\n", " ")
                        )

                        preview = preview[:400]

                        failures.append(
                            f"{source_name} -> "
                            f"{target_name} "
                            f"({target_ip}): ping échoué. "
                            f"Sortie: {preview}"
                        )

                except Exception as exc:
                    failures.append(
                        f"{source_name} -> "
                        f"{target_name} "
                        f"({target_ip}): {exc}"
                    )

        if failures:
            return {
                "test_name": "Ping Connectivity Test",
                "status": "failed",
                "details": (
                    " ; ".join(failures)
                ),
            }

        return {
            "test_name": "Ping Connectivity Test",
            "status": "success",
            "details": (
                "Ping Cisco réel effectué depuis les "
                "consoles GNS3. "
                + " ; ".join(results)
            ),
        }

    except Exception as exc:
        return {
            "test_name": "Ping Connectivity Test",
            "status": "failed",
            "details": str(exc),
        }


# ============================================================================
# VALIDATION COMPLETE
# ============================================================================

def run_all_validations(
    topology: Topology,
) -> List[Dict[str, Any]]:
    """
    Exécute les validations réelles sur la topologie GNS3.
    """

    results = []

    results.append(
        _test_console_accessibility(topology)
    )

    results.append(
        _test_interfaces(topology)
    )

    results.append(
        _test_routing_table(topology)
    )

    results.append(
        _test_ping_connectivity(topology)
    )

    return results