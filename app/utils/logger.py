"""Logging configuration."""

import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logging(level: str = "INFO", log_dir: str = "logs"):
    """Configure application logging."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    log_file = log_path / f"devnet2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    return logging.getLogger(__name__)