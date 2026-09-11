"""Deployment endpoints."""

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.topology import Topology
from app.schemas.deployment import DeploymentRequest
from app.services.deployment_service import deploy_topology

router = APIRouter(prefix="/api/deploy", tags=["deployment"])


@router.post("/{topology_id}/run")
def run_deployment(topology_id: int, request: DeploymentRequest, db: Session = Depends(get_db)):
    """Trigger end-to-end deployment."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topology with ID {topology_id} not found",
        )

    try:
        # CORRECTION : On extrait proprement auto_start au lieu d'appeler request.deploy
        auto_start = getattr(request, "auto_start", True)

        # Si votre fonction deploy_topology prend 2 paramètres booléens (ex: deploy et configure)
        # passez-lui True et auto_start :
        results = deploy_topology(topology_id, True, auto_start)
        
        return {
            "message": "Deployment completed",
            "topology_id": topology_id,
            "results": results,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deployment failed: {e}",
        )


@router.get("/{topology_id}/status")
def get_deployment_status(topology_id: int, db: Session = Depends(get_db)):
    """Get deployment status for a topology."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topology with ID {topology_id} not found",
        )
    return {
        "topology_id": topology_id,
        "status": topology.status,
        "updated_at": str(topology.updated_at) if topology.updated_at else None,
    }