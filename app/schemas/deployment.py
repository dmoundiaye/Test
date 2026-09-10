
"""Schemas for deployment and validation results."""

from typing import List, Optional

from pydantic import BaseModel


class NodeStatus(BaseModel):
    name: str
    status: str  # started, stopped, error
    details: Optional[str] = None


class LinkStatus(BaseModel):
    source: str
    target: str
    status: str  # up, down, error
    details: Optional[str] = None


class ValidationResult(BaseModel):
    test_name: str
    status: str  # SUCCESS, FAILED
    details: Optional[str] = None


class ValidationReport(BaseModel):
    topology_name: str
    generated_at: str
    tests: List[ValidationResult]
    final_status: str  # SUCCESS, FAILED


class DeploymentRequest(BaseModel):
    topology_id: int
    project_name: Optional[str] = None
    auto_start: bool = True


class ReportGenerationRequest(BaseModel):
    topology_id: int
    output_path: Optional[str] = "reports/rapport.md"
