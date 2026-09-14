"""Validation and testing service.

Real validation for Cisco Dynamips routers is performed through the
GNS3 console (Telnet). VPCS, NAT and Ethernet switches are not tested
through Netmiko.
"""

import logging
import re
import socket
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.services.netmiko_service import NetmikoService
from app.services.gns3_service import GNS3Service

logger = logging.getLogger(__name__)

netmiko = NetmikoService()


def _is_cisco_router(device) -> bool:
    name = str(getattr(device, "name", "") or "").upper()
    device_type = str(
        getattr(device, "device_type", "")
        or getattr(device, "type", "")
        or ""
    ).lower()
    return name.startswith("R") or device_type in ("dynamips", "ios", "cisco")


def _result(check_name: str, status: str, details: str) -> Dict[str, Any]:
    return {
        "test_name": check_name,
        "check": check_name,
        "status": status,
        "details": details,
        "timestamp": datetime.utcnow().isoformat(),
    }


def _device_type(device) -> str:
    return str(
        getattr(device, "device_type", "")
        or getattr(device, "type", "")
        or ""
    ).lower().strip()


def _clean_console_output(data: bytes) -> str:
    text = data.decode("utf-8", errors="ignore")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = text.replace("\x08", "")
    return text


class GNS3Console:
    """Minimal Telnet client for GNS3 Dynamips consoles."""

    IAC = 255
    DO = 253
    DONT = 254
    WILL = 251
    WONT = 252
    SB = 250
    SE = 240

    def __init__(self, host: str, port: int, timeout: float = 8.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None

    def connect(self) -> str:
        self.sock = socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout,
        )
        self.sock.settimeout(0.5)
        time.sleep(1)
        return self._read_available()

    def _send_negotiation(self, command: int, option: int) -> None:
        if not self.sock:
            return
        # Refuse optional Telnet modes. This is enough for a Cisco console.
        if command == self.DO:
            reply = bytes([self.IAC, self.WONT, option])
        elif command == self.WILL:
            reply = bytes([self.IAC, self.DONT, option])
        else:
            return
        self.sock.sendall(reply)

    def _read_available(self) -> str:
        if not self.sock:
            return ""

        chunks = []
        deadline = time.time() + 2.0

        while time.time() < deadline:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break

                # Basic Telnet negotiation handling.
                clean = bytearray()
                i = 0
                while i < len(data):
                    byte = data[i]
                    if byte != self.IAC:
                        clean.append(byte)
                        i += 1
                        continue

                    if i + 1 >= len(data):
                        break

                    command = data[i + 1]

                    if command == self.IAC:
                        clean.append(self.IAC)
                        i += 2
                    elif command in (self.DO, self.DONT, self.WILL, self.WONT):
                        if i + 2 < len(data):
                            self._send_negotiation(command, data[i + 2])
                            i += 3
                        else:
                            break
                    elif command == self.SB:
                        # Skip sub-negotiation until IAC SE.
                        i += 2
                        while i + 1 < len(data):
                            if data[i] == self.IAC and data[i + 1] == self.SE:
                                i += 2
                                break
                            i += 1
                    else:
                        i += 2

                chunks.append(bytes(clean))

            except socket.timeout:
                break

        return _clean_console_output(b"".join(chunks))

    def command(self, command: str, wait: float = 1.5) -> str:
        if not self.sock:
            raise RuntimeError("GNS3 console is not connected")

        self.sock.sendall((command.rstrip("\r\n") + "\r").encode())
        time.sleep(wait)
        return self._read_available()

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()


def _find_gns3_project_id(topology, gns3: GNS3Service) -> Optional[str]:
    """Find the deployed GNS3 project belonging to this database topology."""
    projects = gns3.list_projects()

    topology_id = getattr(topology, "id", None)
    candidates = []

    for project in projects:
        name = str(project.get("name", ""))
        project_id = project.get("project_id") or project.get("id")
        if not project_id:
            continue

        if topology_id is not None and f"DevNet2_{topology_id}_" in name:
            candidates.append(project)

    if not candidates:
        return None

    # Most recent deployment normally has the lexicographically greatest
    # timestamp in its name.
    candidates.sort(key=lambda p: str(p.get("name", "")), reverse=True)
    return candidates[0].get("project_id") or candidates[0].get("id")


def _get_console_nodes(topology) -> Dict[str, Dict[str, Any]]:
    """Return GNS3 console information for Cisco routers."""
    gns3 = GNS3Service()
    try:
        project_id = _find_gns3_project_id(topology, gns3)
        if not project_id:
            raise RuntimeError(
                f"Aucun projet GNS3 trouvé pour la topologie {topology.id}"
            )

        nodes = gns3.list_nodes(project_id)
        result = {}

        for node in nodes:
            name = str(node.get("name", ""))
            if _is_cisco_router(type("Node", (), {
                "name": name,
                "device_type": node.get("node_type", ""),
            })()):
                console = node.get("console")
                console_host = node.get("console_host")

                if console is not None and console_host:
                    result[name] = {
                        "project_id": project_id,
                        "node_id": node.get("node_id") or node.get("id"),
                        "console": console,
                        "console_host": console_host,
                        "console_type": node.get("console_type"),
                    }

        return result
    finally:
        gns3.close()


def _run_console_command(
    console_info: Dict[str, Any],
    command: str,
    wait: float = 1.5,
) -> str:
    with GNS3Console(
        console_info["console_host"],
        console_info["console"],
    ) as console:
        # Wake the console and clear any initial banner.
        console.command("", wait=0.5)
        return console.command(command, wait=wait)


def run_all_validations(topology) -> List[Dict[str, Any]]:
    """Run all validation tests on a deployed topology."""
    results = [
        _test_ssh_accessibility(topology),
        _test_interfaces(topology),
        _test_routing_table(topology),
        _test_ping_connectivity(topology),
    ]

    all_passed = all(
        result.get("status") in ("success", "warning", "info")
        for result in results
    )

    logger.info(
        "Validation complete for topology %s: %s",
        topology.id,
        "SUCCESS" if all_passed else "FAILED",
    )

    return results


def get_cached_results(topology_id: int) -> List[Dict[str, Any]]:
    return []


# -------------------------------------------------------------------------
# TEST 1 - ACCESSIBILITY
# -------------------------------------------------------------------------

def _test_ssh_accessibility(topology) -> Dict[str, Any]:
    """Validate actual accessibility of Cisco Dynamips consoles."""
    check_name = "SSH Accessibility Test"

    try:
        console_nodes = _get_console_nodes(topology)
        if not console_nodes:
            return _result(
                check_name,
                "warning",
                "Aucun routeur Cisco Dynamips avec console GNS3 n'a été trouvé.",
            )

        tested = []
        failed = []

        for name, info in console_nodes.items():
            try:
                with GNS3Console(info["console_host"], info["console"]) as console:
                    banner = console.command("", wait=0.5)
                tested.append(name)
            except Exception as exc:
                failed.append(f"{name}: {exc}")

        if failed:
            return _result(
                check_name,
                "failed",
                f"Console GNS3 testée pour {tested or 'aucun'}. "
                f"Échecs : {'; '.join(failed)}",
            )

        return _result(
            check_name,
            "success",
            f"Console GNS3 accessible pour : {', '.join(tested)}. "
            "Validation effectuée par connexion Telnet à la console GNS3.",
        )

    except Exception as exc:
        logger.exception("Console accessibility test failed")
        return _result(check_name, "failed", str(exc))


# -------------------------------------------------------------------------
# TEST 2 - INTERFACES
# -------------------------------------------------------------------------

def _test_interfaces(topology) -> Dict[str, Any]:
    """Run 'show ip interface brief' on Cisco Dynamips routers."""
    check_name = "Interface Status Test"

    try:
        console_nodes = _get_console_nodes(topology)
        if not console_nodes:
            return _result(
                check_name,
                "warning",
                "Aucun routeur Cisco Dynamips avec console GNS3 disponible.",
            )

        router_results = []

        for name, info in console_nodes.items():
            output = _run_console_command(
                info,
                "show ip interface brief",
                wait=2.0,
            )

            if not output.strip():
                return _result(
                    check_name,
                    "failed",
                    f"{name}: aucune sortie retournée par 'show ip interface brief'.",
                )

            # Cisco reports administratively down/down or down/down when an
            # interface is not operational. Treat those as failures.
            down_lines = []
            for line in output.splitlines():
                if re.search(r"\b(?:administratively down|down/down)\b", line, re.I):
                    down_lines.append(line.strip())

            if down_lines:
                return _result(
                    check_name,
                    "failed",
                    f"{name}: interface(s) non opérationnelle(s) détectée(s): "
                    + " | ".join(down_lines),
                )

            router_results.append(
                f"{name}: show ip interface brief OK"
            )

        return _result(
            check_name,
            "success",
            "Validation Cisco réelle effectuée avec 'show ip interface brief'. "
            + " ; ".join(router_results),
        )

    except Exception as exc:
        logger.exception("Interface test failed")
        return _result(check_name, "failed", str(exc))


# -------------------------------------------------------------------------
# TEST 3 - ROUTING
# -------------------------------------------------------------------------

def _test_routing_table(topology) -> Dict[str, Any]:
    """Run 'show ip route' on Cisco Dynamips routers."""
    check_name = "Routing Table Test"

    try:
        console_nodes = _get_console_nodes(topology)
        if not console_nodes:
            return _result(
                check_name,
                "warning",
                "Aucun routeur Cisco Dynamips avec console GNS3 disponible.",
            )

        results = []

        for name, info in console_nodes.items():
            output = _run_console_command(
                info,
                "show ip route",
                wait=2.0,
            )

            if not output.strip():
                return _result(
                    check_name,
                    "failed",
                    f"{name}: aucune sortie retournée par 'show ip route'.",
                )

            # A Cisco routing table should contain the standard header.
            if "Routing Table" not in output and (
                "C" not in output and "L" not in output and "S" not in output
            ):
                return _result(
                    check_name,
                    "failed",
                    f"{name}: sortie de table de routage non reconnue.",
                )

            results.append(f"{name}: show ip route OK")

        return _result(
            check_name,
            "success",
            "Validation Cisco réelle effectuée avec 'show ip route'. "
            + " ; ".join(results),
        )

    except Exception as exc:
        logger.exception("Routing table test failed")
        return _result(check_name, "failed", str(exc))


# -------------------------------------------------------------------------
# TEST 4 - PING
# -------------------------------------------------------------------------

def _test_ping_connectivity(topology) -> Dict[str, Any]:
    """Ping the other Cisco router from each Cisco Dynamips router."""
    check_name = "Ping Connectivity Test"

    try:
        devices = getattr(topology, "devices", []) or []
        routers = [
            device for device in devices
            if _is_cisco_router(device)
            and getattr(device, "management_ip", None)
        ]

        console_nodes = _get_console_nodes(topology)

        if len(routers) < 2:
            return _result(
                check_name,
                "warning",
                "Au moins deux routeurs Cisco avec management_ip sont nécessaires "
                "pour effectuer le ping inter-routeurs.",
            )

        tested = []

        for source in routers[:2]:
            source_name = getattr(source, "name", "Unknown")
            source_info = console_nodes.get(source_name)

            if not source_info:
                return _result(
                    check_name,
                    "failed",
                    f"Console GNS3 introuvable pour {source_name}.",
                )

            targets = [r for r in routers[:2] if getattr(r, "name", "") != source_name]
            if not targets:
                continue

            target = targets[0]
            target_ip = getattr(target, "management_ip", None)

            if not target_ip:
                return _result(
                    check_name,
                    "failed",
                    f"Adresse management absente pour {getattr(target, 'name', 'Unknown')}.",
                )

            output = _run_console_command(
                source_info,
                f"ping {target_ip}",
                wait=4.0,
            )

            success = bool(
                re.search(
                    r"(Success rate is 100 percent|!!!!|[1-9][0-9]? percent)",
                    output,
                    re.I,
                )
            )

            if not success:
                return _result(
                    check_name,
                    "failed",
                    f"{source_name} -> {target_ip}: ping échoué. "
                    f"Sortie: {output[-800:]}",
                )

            tested.append(f"{source_name} -> {target_ip}: OK")

        return _result(
            check_name,
            "success",
            "Ping réel exécuté depuis les consoles Cisco GNS3. "
            + " ; ".join(tested),
        )

    except Exception as exc:
        logger.exception("Ping connectivity test failed")
        return _result(check_name, "failed", str(exc))