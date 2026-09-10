"""Netmiko SSH configuration service."""

import logging
from typing import Dict, List, Optional
from netmiko import ConnectHandler
from netmiko.ssh_exception import NetmikoTimeoutException, NetmikoAuthenticationException
from app.config import settings

logger = logging.getLogger(__name__)


class NetmikoService:
    """Service for SSH configuration of network devices via Netmiko."""

    def __init__(self):
        self.connection_cache: Dict[str, ConnectHandler] = {}

    def get_device_params(self, name: str, management_ip: str, username: str = "admin", password: str = "admin") -> Dict:
        """Build Netmiko device parameters from device info."""
        return {
            "device_type": "linux",  # Default for QEMU-based devices
            "host": management_ip,
            "username": username,
            "password": password,
            "timeout": 30,
        }

    def connect(self, name: str, management_ip: str, username: str = "admin", password: str = "admin") -> ConnectHandler:
        """Establish SSH connection to a device."""
        cache_key = f"{name}:{management_ip}"
        if cache_key in self.connection_cache:
            return self.connection_cache[cache_key]

        device_params = self.get_device_params(name, management_ip, username, password)
        try:
            connection = ConnectHandler(**device_params)
            self.connection_cache[cache_key] = connection
            logger.info(f"Connected to device '{name}' at {management_ip}")
            return connection
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            logger.error(f"Failed to connect to '{name}' at {management_ip}: {e}")
            raise

    def disconnect(self, name: str, management_ip: str):
        """Disconnect from a device."""
        cache_key = f"{name}:{management_ip}"
        if cache_key in self.connection_cache:
            self.connection_cache[cache_key].disconnect()
            del self.connection_cache[cache_key]
            logger.info(f"Disconnected from device '{name}'")

    def send_config(self, name: str, management_ip: str, commands: List[str], username: str = "admin", password: str = "admin") -> Dict:
        """Send configuration commands to a device."""
        conn = self.connect(name, management_ip, username, password)
        try:
            output = conn.send_config_set(commands)
            logger.info(f"Configuration applied to '{name}': {commands}")
            return {"device": name, "status": "success", "output": output}
        except Exception as e:
            logger.error(f"Configuration failed on '{name}': {e}")
            return {"device": name, "status": "failed", "error": str(e)}

    def send_command(self, name: str, management_ip: str, command: str, username: str = "admin", password: str = "admin") -> str:
        """Send a single command and return output."""
        conn = self.connect(name, management_ip, username, password)
        try:
            output = conn.send_command(command, timeout=30)
            return output
        except Exception as e:
            logger.error(f"Command failed on '{name}': {e}")
            raise

    def configure_ip_address(self, name: str, management_ip: str, interface: str, ip_address: str, subnet_mask: str, username: str = "admin", password: str = "admin") -> Dict:
        """Configure IP address on a device interface."""
        commands = [
            f"interface {interface}",
            f"ip address {ip_address} {subnet_mask}",
            "no shutdown",
            "exit",
        ]
        return self.send_config(name, management_ip, commands, username, password)

    def configure_static_route(self, name: str, management_ip: str, destination: str, mask: str, next_hop: str, username: str = "admin", password: str = "admin") -> Dict:
        """Configure a static route."""
        commands = [
            f"ip route {destination} {mask} {next_hop}",
        ]
        return self.send_config(name, management_ip, commands, username, password)

    def configure_ospf(self, name: str, management_ip: str, router_id: str, networks: List[str], username: str = "admin", password: str = "admin") -> Dict:
        """Configure OSPF routing."""
        commands = [
            f"router ospf 1",
            f"router-id {router_id}",
        ]
        for network in networks:
            commands.append(f"network {network}")
        commands.append("exit")
        return self.send_config(name, management_ip, commands, username, password)

    def configure_vlan(self, name: str, management_ip: str, vlans: List[Dict], username: str = "admin", password: str = "admin") -> Dict:
        """Configure VLANs on a switch."""
        commands = []
        for vlan in vlans:
            vlan_id = vlan["id"]
            vlan_name = vlan["name"]
            commands.extend([
                f"vlan {vlan_id}",
                f"name {vlan_name}",
                "exit",
            ])
        return self.send_config(name, management_ip, commands, username, password)

    def configure_dhcp(self, name: str, management_ip: str, pool_name: str, subnet: str, gateway: str, dns: str, username: str = "admin", password: str = "admin") -> Dict:
        """Configure DHCP server."""
        commands = [
            f"ip dhcp pool {pool_name}",
            f"network {subnet}",
            f"default-router {gateway}",
            f"dns-server {dns}",
            "exit",
        ]
        return self.send_config(name, management_ip, commands, username, password)

    def get_interfaces(self, name: str, management_ip: str, username: str = "admin", password: str = "admin") -> str:
        """Get interface status."""
        return self.send_command(name, management_ip, "show ip interface brief", username, password)

    def get_routing_table(self, name: str, management_ip: str, username: str = "admin", password: str = "admin") -> str:
        """Get routing table."""
        return self.send_command(name, management_ip, "show ip route", username, password)

    def test_connectivity(self, name: str, management_ip: str, target: str, username: str = "admin", password: str = "admin") -> str:
        """Test connectivity via ping."""
        return self.send_command(name, management_ip, f"ping {target}", username, password)

    def close_all(self):
        """Close all cached connections."""
        for key in list(self.connection_cache.keys()):
            self.disconnect(key.split(":")[0], key.split(":")[1])