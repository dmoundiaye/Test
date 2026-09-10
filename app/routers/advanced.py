"""Advanced features endpoints."""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any
from pydantic import BaseModel

from app.models.database import get_db
from app.models.topology import Topology
from app.schemas.topology import DeviceSchema, ConnectionSchema
from app.services.advanced_features import (
    configure_vlans,
    configure_ospf,
    configure_dhcp,
    add_router,
    add_connection,
    detect_inconsistencies,
    generate_schema_diagram,
    apply_advanced_features,
)

router = APIRouter(prefix="/api/advanced", tags=["advanced"])


class VLANConfig(BaseModel):
    device: str
    vlans: list[Dict[str, Any]]


class OSPFConfig(BaseModel):
    router_id: str
    networks: list[str]


class DHCPConfig(BaseModel):
    pool_name: str
    subnet: str
    gateway: str
    dns: str


class AdvancedFeaturesRequest(BaseModel):
    vlans: list[VLANConfig] = []
    ospf: OSPFConfig | None = None
    dhcp: DHCPConfig | None = None
    add_router: DeviceSchema | None = None
    add_connection: ConnectionSchema | None = None
    detect_inconsistencies: bool = False
    generate_diagram: bool = False


@router.post("/{topology_id}/vlans")
def config_vlans(topology_id: int, config: list[VLANConfig], db: Session = Depends(get_db)):
    """Configure VLANs on switches."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")
    return configure_vlans(topology_id, [v.model_dump() for v in config], db)


@router.post("/{topology_id}/ospf")
def config_ospf(topology_id: int, config: OSPFConfig, db: Session = Depends(get_db)):
    """Configure OSPF routing."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")
    return configure_ospf(topology_id, config.router_id, config.networks, db)


@router.post("/{topology_id}/dhcp")
def config_dhcp(topology_id: int, config: DHCPConfig, db: Session = Depends(get_db)):
    """Configure DHCP server."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")
    return configure_dhcp(topology_id, config.pool_name, config.subnet, config.gateway, config.dns, db)


@router.post("/{topology_id}/router")
def add_new_router(topology_id: int, router: DeviceSchema, db: Session = Depends(get_db)):
    """Add a new router dynamically."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")
    return add_router(topology_id, router, db)


@router.post("/{topology_id}/connection")
def add_new_connection(topology_id: int, connection: ConnectionSchema, db: Session = Depends(get_db)):
    """Add a new connection dynamically."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")
    return add_connection(topology_id, connection, db)


@router.get("/{topology_id}/inconsistencies")
def check_inconsistencies(topology_id: int, db: Session = Depends(get_db)):
    """Detect inconsistencies between YAML and database."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")
    return detect_inconsistencies(topology_id, db)


@router.get("/{topology_id}/diagram")
def get_diagram(topology_id: int, db: Session = Depends(get_db)):
    """Generate Mermaid diagram for topology."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")
    return generate_schema_diagram(topology_id, db)


@router.post("/{topology_id}/apply")
def apply_features(topology_id: int, request: AdvancedFeaturesRequest, db: Session = Depends(get_db)):
    """Apply multiple advanced features at once."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")
    return apply_advanced_features(topology_id, request.model_dump(), db)