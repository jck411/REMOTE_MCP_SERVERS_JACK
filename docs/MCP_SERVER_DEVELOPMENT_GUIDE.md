# MCP Server Development Guide

> Lessons learned from deploying Spotify MCP Server to Google Cloud Run

## Table of Contents

1. [Overview](#overview)
2. [Project Structure](#project-structure)
3. [Dependencies](#dependencies)
4. [FastMCP Configuration](#fastmcp-configuration)
5. [Transport Types](#transport-types)
6. [Cloud Run Deployment](#cloud-run-deployment)
7. [Secret Management](#secret-management)
8. [Common Pitfalls](#common-pitfalls)
9. [Testing](#testing)
10. [Quick Start Template](#quick-start-template)

---

## Overview

MCP (Model Context Protocol) servers expose tools, resources, and prompts to LLM clients like Claude, ChatGPT, and others. This guide documents best practices for building MCP servers that can be deployed both locally (stdio) and remotely (HTTP via Cloud Run).

### Key Technologies

- **MCP SDK**: `mcp[cli]>=1.22.0` (Python implementation)
- **FastMCP**: High-level API for building MCP servers
- **Streamable HTTP**: Recommended transport for production/cloud deployments
- **Google Cloud Run**: Serverless container deployment
- **Google Secret Manager**: Secure credential storage

---

## Project Structure

```
my-mcp-server/
├── src/
│   └── my_mcp/
│       ├── __init__.py
│       ├── server.py      # FastMCP server with tools
│       ├── client.py      # API client (e.g., Spotify, Weather)
│       └── auth.py        # Authentication logic
├── scripts/
│   └── get_token.py       # OAuth helper scripts
├── tests/
│   └── test_server.py
├── docs/
│   └── guide.md
├── .env                   # Local secrets (NEVER commit)
├── .env.example           # Template for required env vars
├── .gitignore
├── Dockerfile
├── pyproject.toml
└── README.md
```

---

## Dependencies

### pyproject.toml

```toml
[project]
name = "my-mcp-server"
version = "0.1.0"
description = "MCP server for [service] integration"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.22.0",      # MCP SDK with CLI tools
    "httpx>=0.27.0",          # Async HTTP client
    "uvicorn>=0.30.0",        # ASGI server
    "starlette>=0.37.0",      # ASGI framework
    # Add service-specific dependencies
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
]
gcp = [
    "google-cloud-secret-manager>=2.20.0",
]

[project.scripts]
my-mcp = "my_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/my_mcp"]
```

### Key Points

- Use `mcp[cli]>=1.22.0` - includes CLI tools and all transport dependencies
- Version 1.22.0 is current as of Nov 2025
- The `[cli]` extra brings in `typer`, `rich`, `uvicorn`, etc.

---

## FastMCP Configuration

### For Cloud Run / Production

```python
from mcp.server.fastmcp import FastMCP

# Stateless + JSON response = optimal for cloud deployments
mcp = FastMCP(
    "my-server",
    stateless_http=True,   # No session state between requests
    json_response=True,    # JSON instead of SSE streams
)
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `stateless_http` | `False` | Each request creates new ephemeral connection |
| `json_response` | `False` | Return JSON instead of SSE streams |
| `host` | `"127.0.0.1"` | Server bind address |
| `port` | `8000` | Server port |
| `streamable_http_path` | `"/mcp"` | MCP endpoint path |

### Why Stateless + JSON?

1. **Scalability**: Cloud Run can scale to multiple instances
2. **Simplicity**: No session management needed
3. **Compatibility**: Works with all MCP clients
4. **Cost**: Faster cold starts, lower memory

---

## Transport Types

### 1. stdio (Local Development)

```python
# Default transport - used for local Claude Desktop, etc.
mcp.run()  # or mcp.run(transport="stdio")
```

**Use for:**
- Claude Desktop integration
- Local development/testing
- Direct process execution

### 2. Streamable HTTP (Cloud/Remote)

```python
# For cloud deployment
mcp.settings.host = "0.0.0.0"
mcp.settings.port = int(os.environ.get("PORT", "8080"))
mcp.run(transport="streamable-http")
```

**Use for:**
- Google Cloud Run
- Any HTTP-based deployment
- Remote MCP clients

### Server Entry Point Pattern

```python
def main():
    """Run the MCP server."""
    transport = os.environ.get("MCP_TRANSPORT", "stdio")

    if transport == "http":
        # Cloud Run / HTTP deployment
        port = int(os.environ.get("PORT", "8080"))
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        # Local stdio transport
        mcp.run()
```

---

## Cloud Run Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml .
COPY README.md .
COPY src/ src/

# Install dependencies
RUN uv pip install --system -e .

# Cloud Run uses PORT env var (default 8080)
ENV PORT=8080
ENV MCP_TRANSPORT=http
EXPOSE 8080

# Run the MCP server
CMD ["python", "-m", "my_mcp.server"]
```

### Deploy Command

```bash
gcloud run deploy my-mcp-server \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-secrets="API_KEY=API_KEY:latest,OTHER_SECRET=OTHER_SECRET:latest" \
  --memory 512Mi \
  --timeout 300
```

### Key Deployment Options

| Option | Description |
|--------|-------------|
| `--source .` | Build from current directory |
| `--region` | Cloud Run region |
| `--allow-unauthenticated` | Public access (for MCP clients) |
| `--set-secrets` | Mount secrets as env vars |
| `--memory` | Container memory (512Mi minimum recommended) |
| `--timeout` | Request timeout (300s for long operations) |

---

## Secret Management

### Local Development

Use `.env` file (never commit!):

```bash
# .env
API_KEY=your_api_key_here
API_SECRET=your_secret_here
```

### Google Cloud Secret Manager

#### 1. Create Secrets

```bash
# Create secret
echo -n "your-secret-value" | gcloud secrets create SECRET_NAME --data-file=-

# Or from file
gcloud secrets create SECRET_NAME --data-file=secret.txt
```

#### 2. Grant Access to Cloud Run

```bash
# Get the compute service account
gcloud iam service-accounts list

# Grant access (usually automatic, but if needed):
gcloud secrets add-iam-policy-binding SECRET_NAME \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

#### 3. Use in Cloud Run

```bash
--set-secrets="ENV_VAR_NAME=SECRET_NAME:latest"
```

### Reading Secrets in Code

```python
import os

def get_secret(name: str) -> str:
    """Get secret from environment (works for both local and Cloud Run)."""
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing required secret: {name}")
    return value
```

---

## Common Pitfalls

### ❌ Problem 1: Using Wrong MCP Package

```python
# WRONG - old/different package
from fastmcp import FastMCP

# CORRECT - official MCP SDK
from mcp.server.fastmcp import FastMCP
```

### ❌ Problem 2: Missing `http_app()` Method

```python
# WRONG - http_app() doesn't exist
app = mcp.http_app()

# CORRECT - use streamable_http_app() or run()
app = mcp.streamable_http_app()
# OR
mcp.run(transport="streamable-http")
```

### ❌ Problem 3: Manual Uvicorn with streamable_http_app

```python
# WORKS but not recommended
import uvicorn
app = mcp.streamable_http_app()
uvicorn.run(app, host="0.0.0.0", port=8080)

# BETTER - let FastMCP handle it
mcp.settings.host = "0.0.0.0"
mcp.settings.port = 8080
mcp.run(transport="streamable-http")
```

### ❌ Problem 4: Forgetting README.md in Docker

```dockerfile
# Build fails if README.md is referenced in pyproject.toml but not copied
COPY pyproject.toml .
COPY README.md .        # Don't forget this!
COPY src/ src/
```

### ❌ Problem 5: JSON Parsing Empty Responses

Some APIs return empty bodies on success (HTTP 200/204):

```python
async def _request(self, method: str, endpoint: str, **kwargs) -> dict | None:
    response = await self._client.request(method, url, **kwargs)
    response.raise_for_status()
    
    # Handle empty responses
    if response.status_code == 204 or not response.content:
        return None
    
    try:
        return response.json()
    except Exception:
        # Some endpoints return plain text on success
        return None
```

### ❌ Problem 6: OAuth Redirect URI Mismatch

Spotify and other OAuth providers are picky about redirect URIs:

```python
# Must match EXACTLY what's registered in the app dashboard
REDIRECT_URI = "http://127.0.0.1:8888/callback"  # NOT "localhost"
```

---

## Testing

### Local HTTP Testing

```bash
# Start server
MCP_TRANSPORT=http PORT=8080 python -m my_mcp.server

# Test initialize
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}, "id": 1}'

# Test tools/list
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 2}'

# Test tool call
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "my_tool", "arguments": {"arg1": "value"}}, "id": 3}'
```

### MCP Inspector

```bash
# Install MCP Inspector
npx -y @modelcontextprotocol/inspector

# Connect to your server
# In the UI, connect to http://localhost:8080/mcp
```

### Python Test Client

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def test_server():
    async with streamablehttp_client("http://localhost:8080/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Tools: {[t.name for t in tools.tools]}")

asyncio.run(test_server())
```

---

## Quick Start Template

### 1. Create Project

```bash
mkdir my-mcp-server && cd my-mcp-server
uv init
uv add "mcp[cli]>=1.22.0" httpx uvicorn starlette
```

### 2. Create Server (src/my_mcp/server.py)

```python
"""My MCP Server."""

from __future__ import annotations
import os
from mcp.server.fastmcp import FastMCP

# Configure for cloud deployment
mcp = FastMCP(
    "my-server",
    stateless_http=True,
    json_response=True,
)

@mcp.tool("my_tool")
async def my_tool(query: str) -> str:
    """Description of what this tool does."""
    # Implementation here
    return f"Result for: {query}"

def main():
    """Run the MCP server."""
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    
    if transport == "http":
        port = int(os.environ.get("PORT", "8080"))
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()

if __name__ == "__main__":
    main()
```

### 3. Deploy

```bash
# Setup GCP
gcloud auth login
gcloud config set project YOUR_PROJECT

# Enable APIs
gcloud services enable run.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com

# Create secrets
echo -n "secret-value" | gcloud secrets create MY_SECRET --data-file=-

# Deploy
gcloud run deploy my-mcp-server \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-secrets="MY_SECRET=MY_SECRET:latest" \
  --memory 512Mi
```

---

## Reference Links

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Specification - Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [Google Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Google Secret Manager](https://cloud.google.com/secret-manager/docs)

---

## Checklist for New MCP Servers

- [ ] Use `mcp[cli]>=1.22.0` dependency
- [ ] Import from `mcp.server.fastmcp` (not `fastmcp`)
- [ ] Configure `stateless_http=True` and `json_response=True` for cloud
- [ ] Use `mcp.run(transport="streamable-http")` for HTTP
- [ ] Handle empty API responses gracefully
- [ ] Include README.md in Dockerfile COPY
- [ ] Create secrets in Secret Manager before deployment
- [ ] Test with curl before deploying
- [ ] Set appropriate memory (512Mi+) and timeout (300s)
