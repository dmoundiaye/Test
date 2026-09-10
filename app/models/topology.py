"""SQLAlchemy models for topology persistence."""

from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.database import Base


class Topology(Base):
    """Represents a network topology."""

    __tablename__ = "topologies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    yaml_content = Column(Text, nullable=False)
    status = Column(String(50), default="draft")  # draft, deployed, validated, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    devices = relationship("Device", back_populates="topology", cascade="all, delete-orphan")
    connections = relationship("Connection", back_populates="topology", cascade="all, delete-orphan")


class Device(Base):
    """Represents a network device in a topology."""

    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    device_type = Column(String(100), nullable=False)  # qemu, ethernet_switch, nat, etc.
    image = Column(String(255), nullable=True)
    management_ip = Column(String(100), nullable=True)
    ram = Column(Integer, default=256)
    console_type = Column(String(50), nullable=True)
    console_port = Column(Integer, nullable=True)
    topology_id = Column(Integer, ForeignKey("topologies.id"), nullable=False)
    topology = relationship("Topology", back_populates="devices")
    interfaces = relationship("Interface", back_populates="device", cascade="all, delete-orphan")


class Interface(Base):
    """Represents a network interface on a device."""

    __tablename__ = "interfaces"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    ip_address = Column(String(100), nullable=True)
    subnet_mask = Column(String(50), nullable=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    device = relationship("Device", back_populates="interfaces")


class Connection(Base):
    """Represents a connection between two devices."""

    __tablename__ = "connections"

    id = Column(Integer, primary_key=True, index=True)
    source_device = Column(String(255), nullable=False)
    target_device = Column(String(255), nullable=False)
    source_interface = Column(String(100), nullable=True)
    target_interface = Column(String(100), nullable=True)
    topology_id = Column(Integer, ForeignKey("topologies.id"), nullable=False)
    topology = relationship("Topology", back_populates="connections")