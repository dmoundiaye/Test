"""YAML loading endpoint."""

import yaml
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.topology import Topology
from app.schemas.topology import TopologySchema

router = APIRouter(prefix="/api/yaml", tags=["yaml"])


@router.post("/load", status_code=status.HTTP_201_CREATED)
async def load_yaml(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load and validate a topology from a YAML file."""
    try:
        content = await file.read()
        topology_data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid YAML file: {e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error reading file: {e}",
        )

    try:
        # Validate with Pydantic
        schema = TopologySchema(**topology_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation error: {e}",
        )

    # Create topology in database
    topology = Topology(
        name=schema.management_network.name + " - " + schema.lan_a.name,
        description=f"Auto-loaded from YAML: {schema.lan_a.name} and {schema.lan_b.name}",
        yaml_content=content.decode("utf-8"),
    )
    db.add(topology)
    db.commit()
    db.refresh(topology)

    return {
        "message": "YAML topology loaded and validated",
        "topology_id": topology.id,
        "name": topology.name,
        "status": topology.status,
    }


@router.get("/load/file")
async def load_yaml_from_path(filename: str = "topology.yml", db: Session = Depends(get_db)):
    """Load a YAML file from the project directory."""
    from pathlib import Path
    import os

    file_path = Path(os.getcwd()) / "topology.yml"
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="topology.yml not found in project directory",
        )

    try:
        with open(file_path) as f:
            content = f.read()
        topology_data = yaml.safe_load(content)
        schema = TopologySchema(**topology_data)
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid YAML: {e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Check if already loaded
    existing = db.query(Topology).filter(Topology.name == "DevNet2 Topology").first()
    if existing:
        return {
            "message": "Topology already loaded",
            "topology_id": existing.id,
            "name": existing.name,
            "status": existing.status,
        }

    topology = Topology(
        name="DevNet2 Topology",
        description="Network topology for DevNet2 project",
        yaml_content=content,
    )
    db.add(topology)
    db.commit()
    db.refresh(topology)

    return {
        "message": "topology.yml loaded successfully",
        "topology_id": topology.id,
        "name": topology.name,
        "status": topology.status,
    }