"""Pydantic schemas for topology validation."""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
import ipaddress


class InterfaceSchema(BaseModel):
    name: str
    ip_address: Optional[str] = None
    subnet_mask: Optional[str] = None

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v):
        if v:
            try:
                ipaddress.ip_address(v)
            except ValueError as e:
                raise ValueError("Invalid IP address") from e
        return v

    @field_validator("subnet_mask")
    @classmethod
    def validate_mask(cls, v):
        if v:
            try:
                ipaddress.ip_network(f"0.0.0.0/{v}", strict=False)
            except ValueError as e:
                raise ValueError("Invalid subnet mask") from e
        return v


class DeviceSchema(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    device_type: str = Field(min_length=1, max_length=100)
    image: Optional[str] = None
    management_ip: Optional[str] = None
    ram: Optional[int] = Field(default=None, ge=64, le=8192)
    console_type: Optional[str] = None
    console_port: Optional[int] = Field(default=None, ge=1024, le=65535)
    interfaces: List[InterfaceSchema] = Field(default_factory=list)


class ConnectionSchema(BaseModel):
    source: str
    target: str
    source_interface: Optional[str] = None
    target_interface: Optional[str] = None


class LANSchema(BaseModel):
    name: str
    subnet: str
    devices: List[DeviceSchema] = Field(default_factory=list)

    @field_validator("subnet")
    @classmethod
    def validate_subnet(cls, v):
        try:
            ipaddress.ip_network(v, strict=False)
        except ValueError as e:
            raise ValueError("Invalid subnet") from e
        return v


class ManagementNetworkSchema(BaseModel):
    name: str
    subnet: str
    gateway: str
    devices: List[DeviceSchema] = Field(default_factory=list)

    @field_validator("subnet")
    @classmethod
    def validate_subnet(cls, v):
        try:
            ipaddress.ip_network(v, strict=False)
        except ValueError as e:
            raise ValueError("Invalid subnet") from e
        return v


class TopologySchema(BaseModel):
    management_network: ManagementNetworkSchema
    lan_a: LANSchema
    lan_b: LANSchema
    connections: List[ConnectionSchema]

    @model_validator(mode="after")
    def validate_connections(self):
        """Validate that all connection endpoints exist in the topology."""
        all_names = set()
        for section in [self.management_network, self.lan_a, self.lan_b]:
            all_names.update(d.name for d in section.devices)
        for conn in self.connections:
            if conn.source not in all_names:
                raise ValueError(f"Connection source '{conn.source}' does not exist")
            if conn.target not in all_names:
                raise ValueError(f"Connection target '{conn.target}' does not exist")
        return self


class TopologyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    topology: TopologySchema


class TopologyResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    status: str
    created_at: Optional[str]
    updated_at: Optional[str]


class DeviceResponse(BaseModel):
    id: int
    name: str
    device_type: str
    image: Optional[str]
    management_ip: Optional[str]
    ram: Optional[int]
    console_type: Optional[str]
    console_port: Optional[int]
    interfaces: List[InterfaceSchema]


class ConnectionResponse(BaseModel):
    id: int
    source: str
    target: str
    source_interface: Optional[str]
    target_interface: Optional[str]


class DeploymentRequest(BaseModel):
    topology_id: int
    deploy: bool = True
    configure: bool = True


class ValidationResult(BaseModel):
    check: str
    status: str  # success, failed, warning
    details: str