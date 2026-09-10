"""Report utility functions."""

from datetime import datetime
from pathlib import Path


def format_timestamp(dt: datetime) -> str:
    """Format a datetime as a string."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def ensure_report_dir(report_dir: str = "reports") -> Path:
    """Ensure the report directory exists."""
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path