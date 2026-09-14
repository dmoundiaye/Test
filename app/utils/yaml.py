"""YAML/JSON parsing utilities for topology content.

The ``yaml_content`` column stores either a raw YAML string (loaded via
``/api/yaml/load``) or a JSON dump produced by a Pydantic model
(``/api/topology/``).  This module provides a single entry point that
returns a Python dict regardless of the stored format, so the rest of the
code base never has to care about which one it is dealing with.
"""

import json
import logging
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)


def parse_topology_yaml(content: str) -> Dict[str, Any]:
    """Parse a topology document that may be stored as YAML or JSON.

    Tries JSON first (fast path for Pydantic-generated content), then falls
    back to YAML.  Raises ``ValueError`` if the content cannot be parsed.
    """
    if not content:
        raise ValueError("Empty topology content")

    # JSON is a strict subset of YAML, but YAML parsers are more permissive
    # and would happily swallow malformed JSON, so try JSON first explicitly.
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        pass

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid topology content: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Topology content did not parse to a mapping")

    return data