"""Topology management endpoints."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.topology import Topology, Device, Connection, Interface
from app.schemas.topology import (
    TopologyCreate,
    TopologyResponse,
    DeviceResponse,
    ConnectionResponse,
    DeviceSchema,
    InterfaceSchema,
)
from app.schemas.deployment import DeploymentRequest
from app.services.deployment_service import deploy_topology

router = APIRouter(prefix="/api/topology", tags=["topology"])


@router.post("/", response_model=TopologyResponse, status_code=status.HTTP_201_CREATED)
def create_topology(topology_data: TopologyCreate, db: Session = Depends(get_db)):
    """Create a new topology from validated schema."""
    db_topology = Topology(
        name=topology_data.name,
        description=topology_data.description,
        yaml_content=topology_data.topology.model_dump_json(indent=2),
    )
    db.add(db_topology)
    db.commit()
    db.refresh(db_topology)

    # Create devices and their interfaces
    for section in [
        topology_data.topology.management_network,
        topology_data.topology.lan_a,
        topology_data.topology.lan_b,
    ]:
        for device_data in section.devices:
            db_device = Device(
                name=device_data.name,
                device_type=device_data.device_type,
                image=device_data.image,
                management_ip=device_data.management_ip,
                ram=device_data.ram,
                console_type=device_data.console_type,
                console_port=device_data.console_port,
                topology_id=db_topology.id,
            )
            db.add(db_device)
            db.flush()  # Get device ID

            # Create interfaces
            for interface_data in device_data.interfaces:
                db_interface = Interface(
                    name=interface_data.name,
                    ip_address=interface_data.ip_address,
                    subnet_mask=interface_data.subnet_mask,
                    device_id=db_device.id,
                )
                db.add(db_interface)

    # Create connections
    for conn_data in topology_data.topology.connections:
        db_connection = Connection(
            source_device=conn_data.source,
            target_device=conn_data.target,
            source_interface=conn_data.source_interface,
            target_interface=conn_data.target_interface,
            topology_id=db_topology.id,
        )
        db.add(db_connection)

    db.commit()
    db.refresh(db_topology)

    return TopologyResponse(
        id=db_topology.id,
        name=db_topology.name,
        description=db_topology.description,
        status=db_topology.status,
        created_at=str(db_topology.created_at) if db_topology.created_at else None,
        updated_at=str(db_topology.updated_at) if db_topology.updated_at else None,
    )


@router.get("/", response_model=List[TopologyResponse])
def list_topologies(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all topologies."""
    topologies = db.query(Topology).offset(skip).limit(limit).all()
    return [
        TopologyResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            status=t.status,
            created_at=str(t.created_at) if t.created_at else None,
            updated_at=str(t.updated_at) if t.updated_at else None,
        )
        for t in topologies
    ]


@router.get("/{topology_id}", response_model=TopologyResponse)
def get_topology(topology_id: int, db: Session = Depends(get_db)):
    """Get a specific topology by ID."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topology with ID {topology_id} not found",
        )
    return TopologyResponse(
        id=topology.id,
        name=topology.name,
        description=topology.description,
        status=topology.status,
        created_at=str(topology.created_at) if topology.created_at else None,
        updated_at=str(topology.updated_at) if topology.updated_at else None,
    )


@router.delete("/{topology_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topology(topology_id: int, db: Session = Depends(get_db)):
    """Delete a topology by ID."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topology with ID {topology_id} not found",
        )
    db.delete(topology)
    db.commit()
    return None


@router.post("/{topology_id}/devices", response_model=DeviceResponse)
def add_device(topology_id: int, device: DeviceSchema, db: Session = Depends(get_db)):
    """Add a device to an existing topology."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topology with ID {topology_id} not found",
        )

    db_device = Device(
        name=device.name,
        device_type=device.device_type,
        image=device.image,
        management_ip=device.management_ip,
        ram=device.ram,
        console_type=device.console_type,
        console_port=device.console_port,
        topology_id=topology_id,
    )
    db.add(db_device)
    db.flush()

    # Add interfaces
    for interface_data in device.interfaces:
        db_interface = Interface(
            name=interface_data.name,
            ip_address=interface_data.ip_address,
            subnet_mask=interface_data.subnet_mask,
            device_id=db_device.id,
        )
        db.add(db_interface)

    db.commit()
    db.refresh(db_device)

    return DeviceResponse(
        id=db_device.id,
        name=db_device.name,
        device_type=db_device.device_type,
        image=db_device.image,
        management_ip=db_device.management_ip,
        ram=db_device.ram,
        console_type=db_device.console_type,
        console_port=db_device.console_port,
        interfaces=[InterfaceSchema(name=i.name, ip_address=i.ip_address, subnet_mask=i.subnet_mask) for i in db_device.interfaces],
    )


# Assurez-vous d'avoir cet import en haut du fichier topology.py :
# from app.services.deployment_service import deploy_topology

@router.post("/{topology_id}/deploy")
def deploy_topology_endpoint(
    topology_id: int, 
    request: DeploymentRequest, 
    db: Session = Depends(get_db)
):
    """Deploy topology to GNS3."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topology with ID {topology_id} not found",
        )

    if topology.status in ["deploying", "deployed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Topology is already deploying and cannot be redeployed",
        )

    try:
        # Extraire auto_start de manière sécurisée
        auto_start = getattr(request, "auto_start", True)

        # Mise à jour du statut avant traitement
        topology.status = "deploying"
        db.commit()

        # REMPLACEMENT DE deploy_service.deploy PAR deploy_topology :
        results = deploy_topology(topology_id, True, auto_start)

        topology.status = "deployed"
        db.commit()

        return {
            "message": "Deployment completed successfully",
            "topology_id": topology_id,
            "results": results,
        }
    except Exception as e:
        topology.status = "failed"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deployment failed: {str(e)}",
        )