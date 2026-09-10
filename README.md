# DevNet2 - Network Automation and Validation Framework

## Description

DevNet2 is a complete network automation and validation framework developed for the Master 1 Réseaux Informatiques - ISI KM project, supervised by M. TOP.

This project allows you to:
- Define a network topology in a declarative YAML file
- Validate the topology with Pydantic schemas
- Persist the topology in a MySQL database using SQLAlchemy
- Deploy the topology automatically to GNS3 via its REST API
- Configure network devices via SSH using Netmiko
- Run automated validation tests (SSH, interfaces, routing, ping)
- Generate an automatic markdown report (SUCCÈS / ÉCHEC)
- Extend functionality with VLAN, OSPF, DHCP, dynamic router addition, and inconsistency detection

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   YAML      │────▶│   FastAPI   │────▶│   MySQL     │
│  Topology   │     │    API      │     │  Database   │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                           ├──────────────▶ GNS3 API
                           │
                           ├──────────────▶ Netmiko (SSH)
                           │
                           └──────────────▶ Reports (Markdown)
```

## Project Structure

```
devnet2/
├── app/
│   ├── main.py                 # FastAPI application entry point
│   ├── config.py               # Environment configuration
│   ├── models/
│   │   ├── database.py         # SQLAlchemy engine and session
│   │   └── topology.py         # SQLAlchemy models
│   ├── schemas/
│   │   ├── topology.py         # Pydantic schemas
│   │   └── deployment.py       # Deployment schemas
│   ├── routers/
│   │   ├── topology.py         # Topology CRUD endpoints
│   │   ├── yaml.py             # YAML loading endpoints
│   │   ├── deployment.py       # Deployment endpoints
│   │   ├── validation.py       # Validation endpoints
│   │   └── advanced.py         # Advanced features endpoints
│   ├── services/
│   │   ├── gns3_service.py     # GNS3 REST API client
│   │   ├── netmiko_service.py  # Netmiko SSH client
│   │   ├── validation_service.py # Validation tests
│   │   ├── report_service.py   # Report generation
│   │   ├── deployment_service.py # End-to-end deployment
│   │   └── advanced_features.py # VLAN, OSPF, DHCP, etc.
│   ├── utils/
│   │   ├── logger.py           # Logging configuration
│   │   └── reporter.py         # Report utilities
│   └── tests/
│       └── test_api.py         # API tests
├── topology.yml                # Reference topology definition
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker image definition
├── docker-compose.yml          # Docker Compose configuration
├── rapport.md                  # Report template
└── .github/workflows/
    └── docker.yml              # GitHub Actions CI/CD
```

## Installation

### Prerequisites

- Python 3.11+
- MySQL 8.0+
- GNS3 server running on port 3080
- Docker and Docker Compose (optional)

### Local Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd devnet2
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create the MySQL database:
```sql
CREATE DATABASE devnet2;
CREATE USER 'devnet'@'localhost' IDENTIFIED BY 'devnetpassword';
GRANT ALL PRIVILEGES ON devnet2.* TO 'devnet'@'localhost';
FLUSH PRIVILEGES;
```

5. Configure environment variables:
```bash
cp .env.example .env
```

Edit `.env` with your settings:
```
DATABASE_URL=mysql+pymysql://devnet:devnetpassword@localhost:3306/devnet2
GNS3_HOST=127.0.0.1
GNS3_PORT=3080
GNS3_USERNAME=admin
GNS3_PASSWORD=admin
LOG_LEVEL=INFO
```

6. Start the application:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

7. Open Swagger UI:
```
http://localhost:8000/docs
```

### Docker Installation

1. Start all services:
```bash
docker compose up -d
```

2. Check the logs:
```bash
docker compose logs -f devnet-api
```

3. Open Swagger UI:
```
http://localhost:8000/docs
```

## API Endpoints

### Topology Management

- `GET /api/topology/` - List all topologies
- `POST /api/topology/` - Create a topology from schema
- `GET /api/topology/{topology_id}` - Get a topology
- `DELETE /api/topology/{topology_id}` - Delete a topology
- `POST /api/topology/{topology_id}/devices` - Add a device to a topology
- `POST /api/topology/{topology_id}/deploy` - Trigger topology deployment

### YAML Loading

- `POST /api/yaml/load` - Upload and validate a YAML topology file
- `GET /api/yaml/load/file` - Load the default topology.yml file

### Deployment

- `POST /api/deploy/{topology_id}/run` - Deploy a topology to GNS3
- `GET /api/deploy/{topology_id}/status` - Get deployment status

### Validation

- `POST /api/validation/{topology_id}/run` - Run validation tests
- `GET /api/validation/{topology_id}/results` - Get validation results
- `POST /api/validation/{topology_id}/report` - Generate a markdown report

### Advanced Features

- `POST /api/advanced/{topology_id}/vlans` - Configure VLANs
- `POST /api/advanced/{topology_id}/ospf` - Configure OSPF routing
- `POST /api/advanced/{topology_id}/dhcp` - Configure DHCP server
- `POST /api/advanced/{topology_id}/router` - Add a router dynamically
- `POST /api/advanced/{topology_id}/connection` - Add a connection dynamically
- `GET /api/advanced/{topology_id}/inconsistencies` - Detect YAML/GNS3 inconsistencies
- `GET /api/advanced/{topology_id}/diagram` - Generate a Mermaid diagram

## Usage

### 1. Load the Reference Topology

Upload the `topology.yml` file via the API:

```bash
curl -X POST "http://localhost:8000/api/yaml/load" \
  -F "file=@topology.yml"
```

Or load the default file:

```bash
curl -X GET "http://localhost:8000/api/yaml/load/file"
```

### 2. Deploy the Topology

```bash
curl -X POST "http://localhost:8000/api/deploy/{topology_id}/run" \
  -H "Content-Type: application/json" \
  -d '{"deploy": true, "configure": true}'
```

### 3. Run Validation

```bash
curl -X POST "http://localhost:8000/api/validation/{topology_id}/run"
```

### 4. Generate a Report

```bash
curl -X POST "http://localhost:8000/api/validation/{topology_id}/report"
```

The report will be generated at `reports/rapport_{topology_id}.md`.

## Advanced Features

### VLAN Configuration

```json
{
  "vlans": [
    {
      "device": "SW1",
      "vlans": [
        {"id": 10, "name": "VLAN_10"},
        {"id": 20, "name": "VLAN_20"}
      ]
    }
  ]
}
```

### OSPF Configuration

```json
{
  "router_id": "10.0.0.1",
  "networks": [
    "192.168.1.0 0.0.0.255 area 0",
    "10.0.0.0 0.0.0.3 area 0"
  ]
}
```

### DHCP Configuration

```json
{
  "pool_name": "LAN_A_POOL",
  "subnet": "192.168.1.0 255.255.255.0",
  "gateway": "192.168.1.1",
  "dns": "8.8.8.8"
}
```

## Testing

Run the test suite:

```bash
pytest
```

## Logs

Application logs are stored in the `logs/` directory. Each run creates a timestamped log file.

## Report

The `rapport.md` file contains:
- Topology summary
- Equipment list
- Connections
- Network subnets
- Validation results
- Final status (SUCCÈS / ÉCHEC)

## CI/CD

The GitHub Actions workflow automatically builds and pushes the Docker image to Docker Hub on every git push.

## Troubleshooting

### GNS3 Connection Issues

- Verify that the GNS3 server is running on port 3080
- Check the `GNS3_HOST` and `GNS3_PORT` environment variables
- Ensure the GNS3 API is accessible from the container network

### Database Connection Issues

- Verify that MySQL is running
- Check the `DATABASE_URL` environment variable
- Ensure the database user has the necessary permissions

### SSH Connection Issues

- Verify that devices are reachable from the management network
- Check the management IP addresses in the YAML file
- Ensure SSH is enabled on the target devices

## Security Notes

- Change default passwords before production use
- Do not commit `.env` files containing sensitive information
- Use TLS for GNS3 API communication in production
- Restrict API access with authentication in production

## License

This project is developed for educational purposes.