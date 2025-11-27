# MCP Server Development & Deployment Guide

> A comprehensive guide for building and deploying MCP servers to Google Cloud Run
> **Last Updated:** November 2025 | **MCP SDK Version:** 1.22.0+

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Project Structure](#project-structure)
4. [Configuration Files](#configuration-files)
5. [Server Implementation](#server-implementation)
6. [Authentication Patterns](#authentication-patterns)
7. [API Client Patterns](#api-client-patterns)
8. [Local Development](#local-development)
9. [Cloud Run Deployment](#cloud-run-deployment)
10. [Secret Management](#secret-management)
11. [Testing](#testing)
12. [Common Pitfalls](#common-pitfalls)
13. [Security Considerations](#security-considerations)
14. [Troubleshooting](#troubleshooting)
15. [References](#references)

---

## Overview

MCP (Model Context Protocol) servers expose tools, resources, and prompts to LLM clients like Claude, ChatGPT, and others. This guide provides patterns for building MCP servers that work both locally (stdio) and remotely (HTTP via Cloud Run).

### Key Technologies

| Technology | Purpose |
|------------|---------|
| **MCP SDK** | `mcp[cli]>=1.22.0` - Python implementation |
| **FastMCP** | High-level API for building MCP servers |
| **Streamable HTTP** | Transport for production/cloud deployments |
| **Google Cloud Run** | Serverless container deployment |
| **Google Secret Manager** | Secure credential storage |
| **httpx** | Async HTTP client for external APIs |

### Architecture

```
┌──────────────────┐      Streamable HTTP       ┌─────────────────────────┐
│  Any MCP Client  │ ◄────────────────────────► │  Cloud Run Service      │
│  (Claude, GPT..) │      POST /mcp             │  your-mcp-server        │
└──────────────────┘                            └───────────┬─────────────┘
                                                            │
                                                            ▼
                                                ┌─────────────────────────┐
                                                │  External API           │
                                                │  (Spotify, Weather...)  │
                                                └─────────────────────────┘
```

---

## Quick Start

### 1. Create Project

```bash
mkdir my-mcp-server && cd my-mcp-server
python -m venv .venv
source .venv/bin/activate
pip install "mcp[cli]>=1.22.0" httpx uvicorn starlette
```

### 2. Create Server (`src/my_mcp/server.py`)

```python
"""My MCP Server."""
from __future__ import annotations
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "my-server",
    stateless_http=True,
    json_response=True,
)

@mcp.tool("hello")
async def hello(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"

def main():
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

### 3. Test Locally

```bash
# Stdio mode
python -m my_mcp.server

# HTTP mode
MCP_TRANSPORT=http PORT=8080 python -m my_mcp.server
# Then: curl -X POST http://localhost:8080/mcp -H "Content-Type: application/json" ...
```

### 4. Deploy to Cloud Run

```bash
gcloud run deploy my-mcp-server \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 512Mi
```

---

## Project Structure

```
my-mcp-server/
├── src/
│   └── my_mcp/
│       ├── __init__.py        # Package init with version
│       ├── server.py          # FastMCP server with @mcp.tool decorators
│       ├── client.py          # External API client (httpx)
│       └── auth.py            # Authentication/token management
├── scripts/
│   └── get_token.py           # OAuth helper scripts (if needed)
├── tests/
│   └── test_server.py
├── docs/
│   └── README.md
├── .env                       # Local secrets (NEVER commit)
├── .env.example               # Template for required env vars
├── .gitignore
├── Dockerfile
├── pyproject.toml
└── README.md
```

---

## Configuration Files

### pyproject.toml

```toml
[project]
name = "my-mcp-server"
version = "0.1.0"
description = "MCP server for [service] integration"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.22.0",          # MCP SDK with CLI tools
    "httpx>=0.27.0",              # Async HTTP client
    "uvicorn>=0.30.0",            # ASGI server
    "starlette>=0.37.0",          # ASGI framework
    # Add service-specific dependencies here
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

[tool.ruff]
line-length = 88
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

**Key Points:**
- Use `mcp[cli]>=1.22.0` - the `[cli]` extra includes uvicorn, typer, and transport dependencies
- Include `readme = "README.md"` - hatchling needs this
- Use Python 3.11+ for best async performance

---

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project files - README.md is REQUIRED for hatchling build
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

**Key Points:**
- Must include `COPY README.md .` if pyproject.toml references it
- Set `MCP_TRANSPORT=http` to enable HTTP mode in container
- Cloud Run provides PORT=8080 by default

---

### .gitignore

```gitignore
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
.env
*.egg-info/
dist/
build/
.pytest_cache/
.ruff_cache/
```

---

### .env.example

```bash
# API Credentials (get from service dashboard)
API_KEY=your_api_key_here
API_SECRET=your_secret_here

# OAuth tokens (if applicable)
REFRESH_TOKEN=your_refresh_token_here

# Optional: GCP project for Secret Manager
GCP_PROJECT_ID=your-gcp-project
```

---

## Server Implementation

### FastMCP Configuration

```python
from mcp.server.fastmcp import FastMCP

# For cloud deployment - stateless and JSON responses
mcp = FastMCP(
    "my-server",
    stateless_http=True,   # No session state between requests
    json_response=True,    # JSON responses instead of SSE streams
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

### Tool Definition Pattern

```python
@mcp.tool("tool_name")
async def tool_name(
    required_param: str,
    optional_param: int = 10,
) -> str:
    """Short description of what this tool does.

    This description is sent to the LLM to help it understand
    when and how to use this tool.

    Args:
        required_param: Description of this parameter
        optional_param: Description with default value

    Returns:
        Description of what's returned
    """
    try:
        client = get_client()
        result = await client.some_operation(required_param, optional_param)
        return format_result(result)
    except SomeAPIError as e:
        return f"Error: {e.message}"
    except Exception as e:
        return f"Unexpected error: {e}"
```

### Server Entry Point Pattern

```python
import os

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
        # Local stdio transport (Claude Desktop, etc.)
        mcp.run()

if __name__ == "__main__":
    main()
```

---

## Authentication Patterns

### OAuth Token Management

For services requiring OAuth (Spotify, Google, etc.):

```python
"""OAuth token management with auto-refresh."""

from __future__ import annotations
import os
import time
from dataclasses import dataclass
from typing import Optional
import httpx

TOKEN_URL = "https://api.example.com/oauth/token"

@dataclass
class TokenInfo:
    """Access token with expiration tracking."""
    access_token: str
    expires_at: float  # Unix timestamp
    refresh_token: str

    @property
    def is_expired(self) -> bool:
        # Add 60s buffer before actual expiration
        return time.time() >= (self.expires_at - 60)


class AuthError(Exception):
    """Raised when authentication fails."""
    pass


class AuthManager:
    """Manages OAuth tokens with automatic refresh."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("CLIENT_SECRET", "")
        self._refresh_token = refresh_token or os.environ.get("REFRESH_TOKEN", "")
        self._token_info: Optional[TokenInfo] = None

        if not self.client_id or not self.client_secret:
            raise AuthError("CLIENT_ID and CLIENT_SECRET are required")

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self._token_info and not self._token_info.is_expired:
            return self._token_info.access_token

        if not self._refresh_token:
            raise AuthError("No refresh token available. Complete OAuth flow first.")

        await self._refresh_access_token()
        return self._token_info.access_token

    async def _refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                auth=(self.client_id, self.client_secret),
            )

        if response.status_code != 200:
            raise AuthError(f"Token refresh failed: {response.status_code}")

        data = response.json()
        self._token_info = TokenInfo(
            access_token=data["access_token"],
            expires_at=time.time() + data.get("expires_in", 3600),
            refresh_token=data.get("refresh_token", self._refresh_token),
        )


# Global instance
_auth: Optional[AuthManager] = None

def get_auth() -> AuthManager:
    global _auth
    if _auth is None:
        _auth = AuthManager()
    return _auth

async def get_access_token() -> str:
    return await get_auth().get_access_token()
```

### API Key Authentication

For simpler API key auth:

```python
import os

def get_api_key() -> str:
    """Get API key from environment."""
    key = os.environ.get("API_KEY")
    if not key:
        raise ValueError("API_KEY environment variable is required")
    return key
```

---

## API Client Patterns

### Async HTTP Client

```python
"""External API client wrapper."""

from __future__ import annotations
from typing import Any, Optional
import httpx
from .auth import get_access_token

API_BASE = "https://api.example.com/v1"

class APIError(Exception):
    """Raised when an API call fails."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"API error {status_code}: {message}")


class APIClient:
    """Async client for external API."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make an authenticated request."""
        token = await get_access_token()
        url = f"{API_BASE}{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
            )

        # Handle empty responses (204 No Content)
        if response.status_code == 204:
            return {}

        # Handle errors
        if response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("error", {}).get("message", response.text)
            except Exception:
                message = response.text
            raise APIError(response.status_code, message)

        # Handle empty body
        if not response.content:
            return {}

        return response.json()

    async def get(self, endpoint: str, **kwargs) -> dict[str, Any]:
        return await self._request("GET", endpoint, **kwargs)

    async def post(self, endpoint: str, **kwargs) -> dict[str, Any]:
        return await self._request("POST", endpoint, **kwargs)

    async def put(self, endpoint: str, **kwargs) -> dict[str, Any]:
        return await self._request("PUT", endpoint, **kwargs)

    async def delete(self, endpoint: str, **kwargs) -> dict[str, Any]:
        return await self._request("DELETE", endpoint, **kwargs)


# Global instance
_client: Optional[APIClient] = None

def get_client() -> APIClient:
    global _client
    if _client is None:
        _client = APIClient()
    return _client
```

---

## Local Development

### Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Set environment variables
cp .env.example .env
# Edit .env with your credentials
```

### Running Locally

```bash
# Stdio mode (for MCP Inspector or Claude Desktop)
python -m my_mcp.server

# HTTP mode (for curl testing)
MCP_TRANSPORT=http PORT=8080 python -m my_mcp.server
```

### MCP Inspector

```bash
# Install and run MCP Inspector
npx -y @modelcontextprotocol/inspector

# Connect to your local server at http://localhost:8080/mcp
```

---

## Cloud Run Deployment

### Prerequisites

```bash
# Authenticate with GCP
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Enable required APIs
gcloud services enable \
    run.googleapis.com \
    secretmanager.googleapis.com \
    cloudbuild.googleapis.com
```

### Create Secrets

```bash
# Create secrets from values
echo -n "your_api_key" | gcloud secrets create API_KEY --data-file=-
echo -n "your_secret" | gcloud secrets create API_SECRET --data-file=-
echo -n "your_refresh_token" | gcloud secrets create REFRESH_TOKEN --data-file=-
```

### Grant Permissions (if needed)

```bash
# Get your project number
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')

# Grant Cloud Run service account access to secrets
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

### Deploy

```bash
gcloud run deploy my-mcp-server \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-secrets="API_KEY=API_KEY:latest,API_SECRET=API_SECRET:latest,REFRESH_TOKEN=REFRESH_TOKEN:latest" \
  --memory 512Mi \
  --timeout 300
```

### Deployment Options

| Option | Description |
|--------|-------------|
| `--source .` | Build from current directory |
| `--region` | Cloud Run region (us-central1, europe-west1, etc.) |
| `--allow-unauthenticated` | Public access for MCP clients |
| `--set-secrets` | Mount secrets as environment variables |
| `--memory` | Container memory (512Mi minimum recommended) |
| `--timeout` | Request timeout (up to 3600s) |
| `--min-instances` | Keep instances warm (costs more) |
| `--max-instances` | Limit scaling |

---

## Secret Management

### Local: `.env` File

```bash
# .env (NEVER commit this file)
API_KEY=abc123
API_SECRET=xyz789
REFRESH_TOKEN=...
```

### Cloud: Google Secret Manager

#### Creating Secrets

```bash
# From literal value
echo -n "secret-value" | gcloud secrets create SECRET_NAME --data-file=-

# From file
gcloud secrets create SECRET_NAME --data-file=secret.txt

# View secret
gcloud secrets versions access latest --secret=SECRET_NAME
```

#### Using Secrets in Code

```python
import os

def get_secret(name: str, required: bool = True) -> str:
    """Get secret from environment (works for both local and Cloud Run)."""
    value = os.environ.get(name)
    if required and not value:
        raise ValueError(f"Missing required secret: {name}")
    return value or ""
```

---

## Testing

### Curl Tests

```bash
# Initialize connection
curl -X POST https://YOUR-SERVICE-URL/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}, "id": 1}'

# List available tools
curl -X POST https://YOUR-SERVICE-URL/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 2}'

# Call a tool
curl -X POST https://YOUR-SERVICE-URL/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "my_tool", "arguments": {"param": "value"}}, "id": 3}'
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

            # Call a tool
            result = await session.call_tool("hello", {"name": "World"})
            print(f"Result: {result}")

asyncio.run(test_server())
```

### Unit Tests

```python
# tests/test_server.py
import pytest
from my_mcp.server import mcp

@pytest.mark.asyncio
async def test_hello_tool():
    # Get the tool function directly
    hello = mcp._tools["hello"].fn
    result = await hello("World")
    assert "Hello, World" in result
```

---

## Common Pitfalls

### ❌ Wrong Import

```python
# WRONG - old/different package
from fastmcp import FastMCP

# CORRECT - official MCP SDK
from mcp.server.fastmcp import FastMCP
```

### ❌ Non-existent `http_app()` Method

```python
# WRONG - http_app() doesn't exist
app = mcp.http_app()

# CORRECT - use run() with transport
mcp.run(transport="streamable-http")

# OR get the ASGI app directly
app = mcp.streamable_http_app()
```

### ❌ Using SSE Transport for HTTP

```python
# WRONG - SSE is not for HTTP deployment
mcp.run(transport="sse")

# CORRECT - Use streamable-http for cloud
mcp.run(transport="streamable-http")
```

### ❌ Missing README.md in Docker

```dockerfile
# Build fails if README.md is referenced but not copied
COPY pyproject.toml .
COPY README.md .        # ← Don't forget this!
COPY src/ src/
```

### ❌ Not Handling Empty API Responses

```python
# WRONG - crashes on 204 or empty body
return response.json()

# CORRECT - handle empty responses
if response.status_code == 204 or not response.content:
    return {}
return response.json()
```

### ❌ OAuth Redirect URI Mismatch

```python
# Use exactly what's registered in the app dashboard
# Often 127.0.0.1 works but localhost doesn't, or vice versa
REDIRECT_URI = "http://127.0.0.1:8888/callback"  # NOT "localhost"
```

---

## Security Considerations

| Concern | Recommendation |
|---------|----------------|
| **API Access** | Use Cloud Run IAM or add API key validation |
| **Token Storage** | Use Secret Manager (single user) or Firestore (multi-user) |
| **HTTPS** | Cloud Run provides this automatically |
| **Rate Limits** | Implement caching and respect API rate limits |
| **Secrets** | Never commit `.env` files; use Secret Manager |
| **Logging** | Don't log sensitive data (tokens, credentials) |

### Adding API Key Protection

```python
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        api_key = request.headers.get("X-API-Key")
        expected = os.environ.get("MCP_API_KEY")
        if expected and api_key != expected:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `401 Unauthorized` | Refresh token expired; re-run OAuth flow |
| `403 Forbidden` | Missing scopes or permissions |
| Container won't start | Check `MCP_TRANSPORT=http` is set |
| Permission denied for secrets | Grant `roles/secretmanager.secretAccessor` |
| Cold start timeout | Increase `--timeout` or use `--min-instances 1` |
| Import error for `mcp` | Install `mcp[cli]>=1.22.0` (with `[cli]` extra) |
| Empty response crashes | Handle 204 and empty body in client |

### Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Check Cloud Run Logs

```bash
gcloud run services logs read my-mcp-server --region us-central1
```

---

## Client Configuration

### HTTP-based Clients

```json
{
  "mcpServers": {
    "my-server": {
      "transport": "streamable-http",
      "url": "https://my-mcp-server-xxxxx-uc.a.run.app/mcp"
    }
  }
}
```

### Stdio-based Clients (Claude Desktop)

```json
{
  "mcpServers": {
    "my-server": {
      "command": "python",
      "args": ["-m", "my_mcp.server"],
      "env": {
        "API_KEY": "your_api_key",
        "API_SECRET": "your_secret"
      }
    }
  }
}
```

---

## Checklist for New MCP Servers

- [ ] Use `mcp[cli]>=1.22.0` dependency
- [ ] Import from `mcp.server.fastmcp` (not `fastmcp`)
- [ ] Configure `stateless_http=True` and `json_response=True`
- [ ] Use `mcp.run(transport="streamable-http")` for HTTP
- [ ] Handle empty API responses gracefully
- [ ] Include README.md in Dockerfile COPY
- [ ] Create `.env.example` template
- [ ] Add `.env` to `.gitignore`
- [ ] Create secrets in Secret Manager before deployment
- [ ] Test with curl before deploying
- [ ] Set appropriate memory (512Mi+) and timeout (300s)
- [ ] Write clear tool descriptions for LLM understanding

---

## References

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Specification](https://modelcontextprotocol.io/specification)
- [FastMCP Examples](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples/servers)
- [Google Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Google Secret Manager](https://cloud.google.com/secret-manager/docs)
- [httpx Documentation](https://www.python-httpx.org/)
