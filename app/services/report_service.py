"""Report generation service."""

import logging
from typing import List, Dict
from datetime import datetime
from pathlib import Path
from app.models.database import get_db
from app.models.topology import Topology

logger = logging.getLogger(__name__)


def generate_markdown_report(topology_id: int, db) -> str:
    """Generate a comprehensive markdown report for a topology."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise ValueError(f"Topology with ID {topology_id} not found")

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    report_path = Path("reports") / f"rapport_{topology_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# Network Topology Validation Report")
    lines.append("")
    lines.append(f"**Generated:** {timestamp}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Topology Summary
    lines.append("## 1. Topology Summary")
    lines.append("")
    lines.append(f"- **Topology Name:** {topology.name}")
    lines.append(f"- **Topology ID:** {topology.id}")
    lines.append(f"- **Status:** {topology.status}")
    lines.append(f"- **Created At:** {topology.created_at}")
    lines.append(f"- **Updated At:** {topology.updated_at}")
    lines.append("")

    # Parse YAML for devices and connections
    import json
    try:
        topo_data = json.loads(topology.yaml_content)
    except json.JSONDecodeError:
        topo_data = {}

    # Devices
    lines.append("## 2. Equipment List")
    lines.append("")
    lines.append("| Device Name | Type | Management IP | RAM |")
    lines.append("|---|---|---|---|")

    all_devices = []
    for section in ["management_network", "lan_a", "lan_b"]:
        section_data = topo_data.get(section, {})
        for device in section_data.get("devices", []):
            all_devices.append(device)
            lines.append(f"| {device['name']} | {device['device_type']} | {device.get('management_ip', 'N/A')} | {device.get('ram', 'N/A')} |")

    lines.append("")

    # Connections
    lines.append("## 3. Connections")
    lines.append("")
    lines.append("| Source | Target | Source Interface | Target Interface |")
    lines.append("|---|---|---|---|")
    connections = topo_data.get("connections", [])
    for conn in connections:
        lines.append(f"| {conn['source']} | {conn['target']} | {conn.get('source_interface', '-')} | {conn.get('target_interface', '-')} |")
    lines.append("")

    # Subnets
    lines.append("## 4. Network Subnets")
    lines.append("")
    for section in ["management_network", "lan_a", "lan_b"]:
        section_data = topo_data.get(section, {})
        if section_data:
            lines.append(f"- **{section_data.get('name', section)}:** {section_data.get('subnet', 'N/A')}")
    lines.append("")

    # Validation Results
    lines.append("## 5. Validation Results")
    lines.append("")
    lines.append("### Test Results")
    lines.append("")
    # Try to load validation results from a cache/DB
    try:
        from app.services.validation_service import run_all_validations
        validation_results = run_all_validations(topology)
        for test in validation_results:
            status_icon = "✅" if test["status"] == "success" else "❌"
            lines.append(f"- **{test['check']}:** {status_icon} {test['status']}")
            lines.append(f"  - {test['details']}")
    except Exception as e:
        lines.append(f"- Validation not yet run: {e}")
    lines.append("")

    # Final Status
    lines.append("## 6. Final Status")
    lines.append("")
    final_status = topology.status.upper()
    if final_status in ("DEPLOYED", "VALIDATED"):
        lines.append("### 🟢 **SUCCÈS**")
    else:
        lines.append("### 🔴 **ÉCHEC**")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Report generated automatically by DevNet2 Framework*")

    # Write the report
    content = "\n".join(lines)
    report_path.write_text(content, encoding="utf-8")
    logger.info(f"Report generated at: {report_path}")

    return str(report_path)