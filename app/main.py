"""DevNet2 - Network Automation and Validation Framework.

FastAPI application that orchestrates network topology deployment via GNS3,
device configuration via Netmiko, and automated validation with reporting.
"""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.routers import topology, yaml as yaml_router, deployment, validation, advanced
from app.models.database import Base, engine, get_db
from sqlalchemy.orm import Session

# Create database tables at startup
Base.metadata.create_all(bind=engine)



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    from app.utils.logger import setup_logging
    setup_logging(settings.LOG_LEVEL)
    yield
    # Shutdown - nothing to clean up


app = FastAPI(
    title="DevNet2 API",
    description="Network Automation and Validation Framework",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(topology.router)
app.include_router(yaml_router.router)
app.include_router(deployment.router)
app.include_router(validation.router)
app.include_router(advanced.router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "DevNet2 API is running", "docs": "/docs"}


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint."""
    return {"status": "healthy", "service": "devnet2"}