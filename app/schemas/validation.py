from pydantic import BaseModel
from typing import Optional

class ValidationTestResult(BaseModel):
    check: str  # Remplacez test_name par check
    status: str
    details: str
    timestamp: str

    class Config:
        from_attributes = True