"""GNS3 REST API integration service."""

import logging
import time
from typing import Dict, List, Optional, Any

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


class GNS3Service:
    """Service for interacting with GNS3 REST API."""

    def __init__(self):
        self.base_url = f"http://{settings.GNS3_HOST}:{settings.GNS3_PORT}"
        self.username = settings.GNS3_USERNAME
        self.password = settings.GNS3_PASSWORD
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client with auth."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                auth=(self.username, self.password),
                timeout=30.0,
            )
        return self._client

    def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make a request to GNS3 API."""
        try:
            response = self.client.request(
                method,
                path,
                **kwargs,
            )

            try:
                response.raise_for_status()

            except httpx.HTTPStatusError:
                # Afficher le détail exact retourné par GNS3
                print(f"GNS3 STATUS: {response.status_code}")
                print(f"GNS3 RESPONSE: {response.text}")

                logger.error(
                    f"GNS3 API error: {method} {path} "
                    f"- status={response.status_code} "
                    f"- response={response.text}"
                )

                raise

            if response.status_code == 204:
                return {}

            return response.json() if response.content else {}

        except httpx.HTTPError as e:
            logger.error(
                f"GNS3 API error: {method} {path} - {e}"
            )
            raise

    def get_version(self) -> Dict[str, Any]:
        """Get GNS3 server version."""
        return self._request(
            "GET",
            "/v2/version",
        )

    def list_projects(self) -> List[Dict[str, Any]]:
        """List all GNS3 projects."""
        return self._request(
            "GET",
            "/v2/projects",
        )

    def create_project(
        self,
        name: str,
        path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new GNS3 project."""
        data = {
            "name": name,
        }

        if path:
            data["path"] = path

        return self._request(
            "POST",
            "/v2/projects",
            json=data,
        )

    def delete_project(
        self,
        project_id: str,
    ) -> None:
        """Delete a GNS3 project."""
        self._request(
            "DELETE",
            f"/v2/projects/{project_id}",
        )

    def open_project(
        self,
        project_id: str,
    ) -> Dict[str, Any]:
        """Open a project for editing."""
        return self._request(
            "POST",
            f"/v2/projects/{project_id}/open",
        )

    def close_project(
        self,
        project_id: str,
    ) -> None:
        """Close a project."""
        self._request(
            "POST",
            f"/v2/projects/{project_id}/close",
        )

    def get_project(
        self,
        project_id: str,
    ) -> Dict[str, Any]:
        """Get project details."""
        return self._request(
            "GET",
            f"/v2/projects/{project_id}",
        )

    def list_templates(self) -> List[Dict[str, Any]]:
        """List available node templates."""
        return self._request(
            "GET",
            "/v2/templates",
        )

    def list_nodes(
        self,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """List nodes in a project."""
        return self._request(
            "GET",
            f"/v2/projects/{project_id}/nodes",
        )

    def create_node(
        self,
        project_id: str,
        node_type: str,
        name: str,
        template: str = "",
        x: int = 0,
        y: int = 0,
        compute_id: str = "local",
        properties: Optional[Dict[str, Any]] = None,
        **kwargs,
) -> Dict[str, Any]:
        data = {
        "name": name,
        "node_type": node_type,
        "compute_id": compute_id,
        "x": x,
        "y": y,
    }

        if properties:
            data["properties"] = properties

        data.update(kwargs)

        return self._request(
            "POST",
            f"/v2/projects/{project_id}/nodes",
            json=data,
        )

    def delete_node(
        self,
        project_id: str,
        node_id: str,
    ) -> None:
        """Delete a node from a project."""
        self._request(
            "DELETE",
            f"/v2/projects/{project_id}/nodes/{node_id}",
        )

    def start_node(
        self,
        project_id: str,
        node_id: str,
    ) -> None:
        """Start a node."""
        self._request(
            "POST",
            f"/v2/projects/{project_id}/nodes/{node_id}/start",
        )

    def stop_node(
        self,
        project_id: str,
        node_id: str,
    ) -> None:
        """Stop a node."""
        self._request(
            "POST",
            f"/v2/projects/{project_id}/nodes/{node_id}/stop",
        )

    def start_all_nodes(
        self,
        project_id: str,
    ) -> None:
        """Start all nodes in a project."""
        self._request(
            "POST",
            f"/v2/projects/{project_id}/nodes/start",
        )

    def stop_all_nodes(
        self,
        project_id: str,
    ) -> None:
        """Stop all nodes in a project."""
        self._request(
            "POST",
            f"/v2/projects/{project_id}/nodes/stop",
        )

    def get_node_status(
        self,
        project_id: str,
        node_id: str,
    ) -> Dict[str, Any]:
        """Get node status."""
        return self._request(
            "GET",
            f"/v2/projects/{project_id}/nodes/{node_id}/status",
        )

    def list_links(
        self,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """List links in a project."""
        return self._request(
            "GET",
            f"/v2/projects/{project_id}/links",
        )

    def create_link(
    self,
    project_id: str,
    source_node_id: str,
    source_port: str,
    target_node_id: str,
    target_port: str,
) -> Dict[str, Any]:
        """
        Create a GNS3 link.

        GNS3 REST API expects:
            {
                "nodes": [
                    {
                        "adapter_number": 0,
                        "node_id": "...",
                        "port_number": 0
                    },
                    {
                        "adapter_number": 0,
                        "node_id": "...",
                        "port_number": 0
                    }
                ]
            }
        """

        def interface_to_port(interface: str) -> Dict[str, int]:
            """
            Convert an interface name to GNS3 adapter_number/port_number.
            """

            interface = str(interface).strip()

            # --------------------------------------------------------------
            # VPCS
            # --------------------------------------------------------------

            # --------------------------------------------------------------
            # Ethernet / VPCS / Ethernet switch / NAT
            # --------------------------------------------------------------
            if interface.startswith("Ethernet"):
                try:
                    port_number = int(
                        interface.replace("Ethernet", "")
                    )
                    return {
                        "adapter_number": 0,
                        "port_number": port_number,
                    }
                except ValueError:
                    pass

            if interface in {
                "eth0",
                "e0",
                "nat0",
            }:
                return {
                    "adapter_number": 0,
                    "port_number": 0,
                }

            # --------------------------------------------------------------
            # C3745 FastEthernet
            #
            # FastEthernet0/0 -> adapter 0, port 0
            # FastEthernet0/1 -> adapter 0, port 1
            # FastEthernet1/0 -> adapter 1, port 0
            # --------------------------------------------------------------

            fast_map = {
                "FastEthernet0/0": {
                    "adapter_number": 0,
                    "port_number": 0,
                },
                "FastEthernet0/1": {
                    "adapter_number": 0,
                    "port_number": 1,
                },
                "FastEthernet1/0": {
                    "adapter_number": 1,
                    "port_number": 0,
                },
            }

            if interface in fast_map:
                return fast_map[interface]

            # Short Cisco names
            short_fast_map = {
                "Fa0/0": {
                    "adapter_number": 0,
                    "port_number": 0,
                },
                "Fa0/1": {
                    "adapter_number": 0,
                    "port_number": 1,
                },
                "Fa1/0": {
                    "adapter_number": 1,
                    "port_number": 0,
                },
            }

            if interface in short_fast_map:
                return short_fast_map[interface]

            # --------------------------------------------------------------
            # GigabitEthernet
            #
            # Useful if the topology uses GigabitEthernet names.
            # --------------------------------------------------------------

            gigabit_map = {
                "GigabitEthernet0/0": {
                    "adapter_number": 1,
                    "port_number": 0,
                },
                "GigabitEthernet0/1": {
                    "adapter_number": 1,
                    "port_number": 1,
                },
                "GigabitEthernet1/0": {
                    "adapter_number": 2,
                    "port_number": 0,
                },
            }

            if interface in gigabit_map:
                return gigabit_map[interface]

            short_gigabit_map = {
                "Gi0/0": {
                    "adapter_number": 1,
                    "port_number": 0,
                },
                "Gi0/1": {
                    "adapter_number": 1,
                    "port_number": 1,
                },
                "Gi1/0": {
                    "adapter_number": 2,
                    "port_number": 0,
                },
            }

            if interface in short_gigabit_map:
                return short_gigabit_map[interface]

            raise ValueError(
                f"Unsupported GNS3 interface: {interface}"
            )

        source = interface_to_port(source_port)
        target = interface_to_port(target_port)

        data = {
            "nodes": [
                {
                    "adapter_number": source["adapter_number"],
                    "node_id": source_node_id,
                    "port_number": source["port_number"],
                },
                {
                    "adapter_number": target["adapter_number"],
                    "node_id": target_node_id,
                    "port_number": target["port_number"],
                },
            ]
        }

        return self._request(
            "POST",
            f"/v2/projects/{project_id}/links",
            json=data,
        )

    def delete_link(
        self,
        project_id: str,
        link_id: str,
    ) -> None:
        """Delete a link."""
        self._request(
            "DELETE",
            f"/v2/projects/{project_id}/links/{link_id}",
        )

    def wait_for_node_state(
        self,
        project_id: str,
        node_id: str,
        target_state: str,
        timeout: int = 60,
    ) -> bool:
        """Wait for a node to reach a specific state."""

        start_time = time.time()

        while time.time() - start_time < timeout:

            try:
                status = self.get_node_status(
                    project_id,
                    node_id,
                )

                if status.get("status") == target_state:
                    return True

            except httpx.HTTPError:
                pass

            time.sleep(2)

        return False

    def close(self):
        """Close the HTTP client."""

        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()