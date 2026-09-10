"""Schemas for deployment and validation results."""

from typing import List, Optional
from pydantic import BaseModel, Field


class NodeStatus(BaseModel):
    name: str
    status: str  # started, stopped, error
    details: Optional[str] = None


class LinkStatus(BaseModel):
    source: str
    target: str
    status: str  # up, down, error
    details: Optional[str] = None


class ValidationReport(BaseModel):
    topology_name: str
    generated_at: str
    tests: List[ValidationResult]
    final_status: str  # SUCCESS, FAILED


class ReportGenerationRequest(BaseModel):
    topology_id: int
    output_path: Optional[str] = "reports/rapport.md"