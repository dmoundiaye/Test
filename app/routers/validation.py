"""Validation endpoints."""

from typing import List
from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.topology import Topology
from app.schemas.deployment import ValidationResult

router = APIRouter(prefix="/api/validation", tags=["validation"])


@router.post("/{topology_id}/run", response_model=List[ValidationResult])
def run_validation(topology_id: int, db: Session = Depends(get_db)):
    """Run validation tests on a deployed topology."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topology with ID {topology_id} not found",
        )

    if topology.status != "deployed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Topology must be deployed before validation. Current status: {topology.status}",
        )

    from app.services.validation_service import run_all_validations

    results = run_all_validations(topology)
    return results


@router.get("/{topology_id}/results", response_model=List[ValidationResult])
def get_validation_results(topology_id: int, db: Session = Depends(get_db)):
    """Get validation results for a topology."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topology with ID {topology_id} not found",
        )

    from app.services.validation_service import get_cached_results

    return get_cached_results(topology_id)


@router.post("/{topology_id}/report")
def generate_report(topology_id: int, db: Session = Depends(get_db)):
    """Generate a markdown report for a topology."""
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topology with ID {topology_id} not found",
        )

    from app.services.report_service import generate_markdown_report

    report_path = generate_markdown_report(topology_id, db)
    return {"message": "Report generated", "path": report_path}