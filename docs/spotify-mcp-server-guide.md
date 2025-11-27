# Complete Guide: Self-Contained Spotify MCP Server on Google Cloud

## Overview

You're building a **standalone MCP server** that exposes Spotify tools over HTTP, deployable to **Google Cloud Run**, usable by **any MCP-compatible chatbot**.

**⚠️ NOTE:** This guide has been updated based on real deployment experience. See `MCP_SERVER_DEVELOPMENT_GUIDE.md` for general MCP server development best practices.

---

## Architecture

```
┌──────────────────┐      Streamable HTTP       ┌─────────────────────────┐
│  Any MCP Client  │ ◄────────────────────────► │  Cloud Run Service      │
│  (Claude, etc.)  │      POST /mcp             │  spotify-mcp-server     │
└──────────────────┘                             └───────────┬─────────────┘
                                                             │
                                                             ▼
                                                 ┌─────────────────────────┐
                                                 │  Spotify Web API        │
                                                 │  api.spotify.com        │
                                                 └─────────────────────────┘
```

---

## Project Structure

```
spotify-mcp-server/
├── pyproject.toml          # Dependencies & project config
├── Dockerfile              # Cloud Run container
├── README.md               # Required for hatchling build
├── .gitignore
├── .env.example            # Template for local dev
├── scripts/
│   └── get_spotify_token.py  # OAuth token retrieval
└── src/
    └── spotify_mcp/
        ├── __init__.py
        ├── server.py       # FastMCP server with @mcp.tool decorators
        ├── auth.py         # Spotify OAuth token management
        └── client.py       # Spotify Web API wrapper (httpx)
```

---

## File Contents

### 1. pyproject.toml

```toml
[project]
name = "spotify-mcp-server"
version = "0.1.0"
description = "MCP server for Spotify integration, deployable to Cloud Run"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.22.0",      # IMPORTANT: Use mcp[cli] not just mcp
    "httpx>=0.27.0",
    "google-cloud-secret-manager>=2.20.0",
    "uvicorn>=0.30.0",
    "starlette>=0.37.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
]

[project.scripts]
spotify-mcp = "spotify_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/spotify_mcp"]

[tool.ruff]
line-length = 88
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

**Key Points:**
- Use `mcp[cli]>=1.22.0` - the `[cli]` extra includes uvicorn, typer, and other required dependencies
- Include `readme = "README.md"` - hatchling needs this

---

### 2. `Dockerfile`

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

# Run the MCP server with streamable HTTP transport
CMD ["python", "-m", "spotify_mcp.server"]
```

**Key Points:**
- Must include `COPY README.md .` if pyproject.toml references it
- Set `MCP_TRANSPORT=http` to enable HTTP mode
- Cloud Run provides PORT=8080 by default

---

### 3. .gitignore

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

### 4. `.env.example`

```bash
# Spotify App Credentials (from developer.spotify.com)
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here

# For single-user: store refresh token directly
# For multi-user: use Firestore/database instead
SPOTIFY_REFRESH_TOKEN=your_refresh_token_here

# Optional: GCP project for Secret Manager
GCP_PROJECT_ID=your-gcp-project
```

---

### 5. `src/spotify_mcp/__init__.py`

```python
"""Spotify MCP Server - A standalone MCP server for Spotify integration."""

__version__ = "0.1.0"
```

---

### 6. `src/spotify_mcp/auth.py`

```python
"""Spotify OAuth token management.

Handles token refresh and storage. For Cloud Run deployment, tokens are
stored in Google Secret Manager. For local dev, uses environment variables.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


@dataclass
class TokenInfo:
    """Spotify access token with expiration tracking."""

    access_token: str
    expires_at: float  # Unix timestamp
    refresh_token: str
    scope: str = ""

    @property
    def is_expired(self) -> bool:
        # Add 60s buffer before actual expiration
        return time.time() >= (self.expires_at - 60)


class SpotifyAuthError(Exception):
    """Raised when authentication fails."""

    pass


class SpotifyAuth:
    """Manages Spotify OAuth tokens with automatic refresh."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("SPOTIFY_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("SPOTIFY_CLIENT_SECRET", "")
        self._refresh_token = refresh_token or os.environ.get("SPOTIFY_REFRESH_TOKEN", "")
        self._token_info: Optional[TokenInfo] = None

        if not self.client_id or not self.client_secret:
            raise SpotifyAuthError(
                "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are required"
            )

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self._token_info and not self._token_info.is_expired:
            return self._token_info.access_token

        if not self._refresh_token:
            raise SpotifyAuthError(
                "No refresh token available. Complete OAuth flow first."
            )

        await self._refresh_access_token()
        return self._token_info.access_token  # type: ignore

    async def _refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                auth=(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            raise SpotifyAuthError(
                f"Token refresh failed: {response.status_code} - {response.text}"
            )

        data = response.json()
        self._token_info = TokenInfo(
            access_token=data["access_token"],
            expires_at=time.time() + data.get("expires_in", 3600),
            refresh_token=data.get("refresh_token", self._refresh_token),
            scope=data.get("scope", ""),
        )

        # If Spotify returned a new refresh token, update it
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]
            # TODO: Persist new refresh token to Secret Manager/DB


# Global auth instance (initialized on first use)
_auth: Optional[SpotifyAuth] = None


def get_auth() -> SpotifyAuth:
    """Get or create the global SpotifyAuth instance."""
    global _auth
    if _auth is None:
        _auth = SpotifyAuth()
    return _auth


async def get_access_token() -> str:
    """Convenience function to get a valid access token."""
    return await get_auth().get_access_token()
```

---

### 7. `src/spotify_mcp/client.py`

```python
"""Spotify Web API client.

Thin async wrapper around the Spotify Web API using httpx.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from .auth import get_access_token, SpotifyAuthError

SPOTIFY_API_BASE = "https://api.spotify.com/v1"


class SpotifyAPIError(Exception):
    """Raised when a Spotify API call fails."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Spotify API error {status_code}: {message}")


class SpotifyClient:
    """Async client for Spotify Web API."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to Spotify API."""
        token = await get_access_token()
        url = f"{SPOTIFY_API_BASE}{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
            )

        if response.status_code == 204:
            return {}

        if response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("error", {}).get("message", response.text)
            except Exception:
                message = response.text
            raise SpotifyAPIError(response.status_code, message)

        if not response.content:
            return {}

        return response.json()

    async def get(
        self, endpoint: str, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        return await self._request("GET", endpoint, params=params)

    async def post(
        self,
        endpoint: str,
        json_body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return await self._request("POST", endpoint, params=params, json_body=json_body)

    async def put(
        self,
        endpoint: str,
        json_body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return await self._request("PUT", endpoint, params=params, json_body=json_body)

    async def delete(
        self, endpoint: str, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        return await self._request("DELETE", endpoint, params=params)

    # ─────────────────────────────────────────────────────────────────
    # Player / Playback
    # ─────────────────────────────────────────────────────────────────

    async def get_current_playback(self) -> dict[str, Any]:
        """Get the current playback state."""
        return await self.get("/me/player")

    async def get_currently_playing(self) -> dict[str, Any]:
        """Get the currently playing track."""
        return await self.get("/me/player/currently-playing")

    async def play(
        self,
        device_id: Optional[str] = None,
        context_uri: Optional[str] = None,
        uris: Optional[list[str]] = None,
        offset: Optional[dict[str, Any]] = None,
        position_ms: Optional[int] = None,
    ) -> dict[str, Any]:
        """Start or resume playback."""
        params = {"device_id": device_id} if device_id else None
        body: dict[str, Any] = {}
        if context_uri:
            body["context_uri"] = context_uri
        if uris:
            body["uris"] = uris
        if offset:
            body["offset"] = offset
        if position_ms is not None:
            body["position_ms"] = position_ms
        return await self.put("/me/player/play", json_body=body or None, params=params)

    async def pause(self, device_id: Optional[str] = None) -> dict[str, Any]:
        """Pause playback."""
        params = {"device_id": device_id} if device_id else None
        return await self.put("/me/player/pause", params=params)

    async def skip_to_next(self, device_id: Optional[str] = None) -> dict[str, Any]:
        """Skip to next track."""
        params = {"device_id": device_id} if device_id else None
        return await self.post("/me/player/next", params=params)

    async def skip_to_previous(self, device_id: Optional[str] = None) -> dict[str, Any]:
        """Skip to previous track."""
        params = {"device_id": device_id} if device_id else None
        return await self.post("/me/player/previous", params=params)

    async def seek(
        self, position_ms: int, device_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Seek to position in current track."""
        params: dict[str, Any] = {"position_ms": position_ms}
        if device_id:
            params["device_id"] = device_id
        return await self.put("/me/player/seek", params=params)

    async def set_volume(
        self, volume_percent: int, device_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Set playback volume (0-100)."""
        params: dict[str, Any] = {"volume_percent": max(0, min(100, volume_percent))}
        if device_id:
            params["device_id"] = device_id
        return await self.put("/me/player/volume", params=params)

    async def set_shuffle(
        self, state: bool, device_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Set shuffle mode."""
        params: dict[str, Any] = {"state": str(state).lower()}
        if device_id:
            params["device_id"] = device_id
        return await self.put("/me/player/shuffle", params=params)

    async def set_repeat(
        self, state: str, device_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Set repeat mode: 'track', 'context', or 'off'."""
        params: dict[str, Any] = {"state": state}
        if device_id:
            params["device_id"] = device_id
        return await self.put("/me/player/repeat", params=params)

    async def get_devices(self) -> dict[str, Any]:
        """Get available playback devices."""
        return await self.get("/me/player/devices")

    async def transfer_playback(
        self, device_id: str, play: bool = False
    ) -> dict[str, Any]:
        """Transfer playback to another device."""
        return await self.put(
            "/me/player", json_body={"device_ids": [device_id], "play": play}
        )

    async def add_to_queue(
        self, uri: str, device_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Add a track to the playback queue."""
        params: dict[str, Any] = {"uri": uri}
        if device_id:
            params["device_id"] = device_id
        return await self.post("/me/player/queue", params=params)

    async def get_queue(self) -> dict[str, Any]:
        """Get the user's playback queue."""
        return await self.get("/me/player/queue")

    # ─────────────────────────────────────────────────────────────────
    # Search
    # ─────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        types: list[str] = ["track"],
        limit: int = 20,
        offset: int = 0,
        market: Optional[str] = None,
    ) -> dict[str, Any]:
        """Search for tracks, albums, artists, playlists, etc."""
        params: dict[str, Any] = {
            "q": query,
            "type": ",".join(types),
            "limit": min(50, max(1, limit)),
            "offset": offset,
        }
        if market:
            params["market"] = market
        return await self.get("/search", params=params)

    # ─────────────────────────────────────────────────────────────────
    # Tracks & Albums
    # ─────────────────────────────────────────────────────────────────

    async def get_track(self, track_id: str) -> dict[str, Any]:
        """Get track details."""
        return await self.get(f"/tracks/{track_id}")

    async def get_album(self, album_id: str) -> dict[str, Any]:
        """Get album details."""
        return await self.get(f"/albums/{album_id}")

    async def get_album_tracks(
        self, album_id: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get album tracks."""
        return await self.get(
            f"/albums/{album_id}/tracks", params={"limit": limit, "offset": offset}
        )

    # ─────────────────────────────────────────────────────────────────
    # Artists
    # ─────────────────────────────────────────────────────────────────

    async def get_artist(self, artist_id: str) -> dict[str, Any]:
        """Get artist details."""
        return await self.get(f"/artists/{artist_id}")

    async def get_artist_top_tracks(
        self, artist_id: str, market: str = "US"
    ) -> dict[str, Any]:
        """Get artist's top tracks."""
        return await self.get(
            f"/artists/{artist_id}/top-tracks", params={"market": market}
        )

    async def get_artist_albums(
        self,
        artist_id: str,
        include_groups: str = "album,single",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get artist's albums."""
        return await self.get(
            f"/artists/{artist_id}/albums",
            params={"include_groups": include_groups, "limit": limit},
        )

    # ─────────────────────────────────────────────────────────────────
    # Playlists
    # ─────────────────────────────────────────────────────────────────

    async def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Get playlist details."""
        return await self.get(f"/playlists/{playlist_id}")

    async def get_playlist_tracks(
        self, playlist_id: str, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        """Get playlist tracks."""
        return await self.get(
            f"/playlists/{playlist_id}/tracks",
            params={"limit": limit, "offset": offset},
        )

    async def get_my_playlists(
        self, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get current user's playlists."""
        return await self.get("/me/playlists", params={"limit": limit, "offset": offset})

    async def create_playlist(
        self,
        user_id: str,
        name: str,
        public: bool = False,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new playlist."""
        return await self.post(
            f"/users/{user_id}/playlists",
            json_body={"name": name, "public": public, "description": description},
        )

    async def add_tracks_to_playlist(
        self, playlist_id: str, uris: list[str], position: Optional[int] = None
    ) -> dict[str, Any]:
        """Add tracks to a playlist."""
        body: dict[str, Any] = {"uris": uris}
        if position is not None:
            body["position"] = position
        return await self.post(f"/playlists/{playlist_id}/tracks", json_body=body)

    # ─────────────────────────────────────────────────────────────────
    # User Profile & Library
    # ─────────────────────────────────────────────────────────────────

    async def get_me(self) -> dict[str, Any]:
        """Get current user's profile."""
        return await self.get("/me")

    async def get_saved_tracks(
        self, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get user's saved/liked tracks."""
        return await self.get("/me/tracks", params={"limit": limit, "offset": offset})

    async def save_tracks(self, track_ids: list[str]) -> dict[str, Any]:
        """Save tracks to user's library."""
        return await self.put("/me/tracks", json_body={"ids": track_ids})

    async def remove_saved_tracks(self, track_ids: list[str]) -> dict[str, Any]:
        """Remove tracks from user's library."""
        return await self.delete("/me/tracks", params={"ids": ",".join(track_ids)})

    async def get_recently_played(self, limit: int = 50) -> dict[str, Any]:
        """Get recently played tracks."""
        return await self.get("/me/player/recently-played", params={"limit": limit})


# Global client instance
_client: Optional[SpotifyClient] = None


def get_client() -> SpotifyClient:
    """Get or create the global SpotifyClient instance."""
    global _client
    if _client is None:
        _client = SpotifyClient()
    return _client
```

---

### 8. `src/spotify_mcp/server.py`

```python
"""Spotify MCP Server.

FastMCP server exposing Spotify tools via MCP protocol.
Supports Streamable HTTP transport for Cloud Run deployment.
"""

from __future__ import annotations

import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .client import get_client, SpotifyAPIError
from .auth import SpotifyAuthError

# Create MCP server instance
# IMPORTANT: stateless_http=True and json_response=True are recommended for Cloud Run
# as they allow better scalability in multi-node environments
mcp = FastMCP(
    "spotify",
    stateless_http=True,   # No session state between requests
    json_response=True,    # JSON responses instead of SSE streams
)


def _format_track(track: dict) -> str:
    """Format a track for display."""
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    album = track.get("album", {}).get("name", "Unknown Album")
    duration_ms = track.get("duration_ms", 0)
    duration = f"{duration_ms // 60000}:{(duration_ms % 60000) // 1000:02d}"
    return f'"{track.get("name")}" by {artists} ({album}) [{duration}]'


def _format_error(e: Exception) -> str:
    """Format an error for the LLM."""
    if isinstance(e, SpotifyAuthError):
        return f"Authentication error: {e}. The Spotify token may need to be refreshed."
    if isinstance(e, SpotifyAPIError):
        return f"Spotify API error ({e.status_code}): {e.message}"
    return f"Error: {e}"


# ... (tool definitions remain the same) ...


# ─────────────────────────────────────────────────────────────────────────────
# Server Entry Point
# ─────────────────────────────────────────────────────────────────────────────


def main():
    """Run the MCP server."""
    transport = os.environ.get("MCP_TRANSPORT", "stdio")

    if transport == "http":
        # For Cloud Run: run with streamable HTTP transport
        # The server listens on host:port/mcp by default
        port = int(os.environ.get("PORT", "8080"))
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        # For local development: use stdio
        mcp.run()


if __name__ == "__main__":
    main()
```

**Key Changes from Original:**
1. Use `stateless_http=True` and `json_response=True` for cloud scalability
2. Use `transport="streamable-http"` NOT `transport="sse"` 
3. Configure `mcp.settings.host` and `mcp.settings.port` before calling `run()`
4. Don't manually create uvicorn - let `mcp.run()` handle it

---

## Deployment Steps

### 1. Create Spotify App

1. Go to https://developer.spotify.com/dashboard
2. Create a new app
3. Note your **Client ID** and **Client Secret**
4. Add redirect URI: `http://127.0.0.1:8888/callback` (**IMPORTANT**: Use `127.0.0.1`, NOT `localhost`)
5. Required scopes:
   ```
   user-read-playback-state
   user-modify-playback-state
   user-read-currently-playing
   user-read-recently-played
   user-library-read
   user-library-modify
   playlist-read-private
   playlist-modify-public
   playlist-modify-private
   ```

### 2. Get Initial Refresh Token

Use the script in `scripts/get_spotify_token.py`:

```bash
export SPOTIFY_CLIENT_ID="your_client_id"
export SPOTIFY_CLIENT_SECRET="your_client_secret"
python scripts/get_spotify_token.py
```

### 3. Set Up Google Cloud

```bash
# Authenticate
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Enable APIs
gcloud services enable \
    run.googleapis.com \
    secretmanager.googleapis.com \
    cloudbuild.googleapis.com

# Store secrets
echo -n "your_client_id" | gcloud secrets create SPOTIFY_CLIENT_ID --data-file=-
echo -n "your_client_secret" | gcloud secrets create SPOTIFY_CLIENT_SECRET --data-file=-
echo -n "your_refresh_token" | gcloud secrets create SPOTIFY_REFRESH_TOKEN --data-file=-

# Grant Cloud Run access to secrets (if needed)
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

### 4. Deploy to Cloud Run

```bash
gcloud run deploy spotify-mcp \
    --source . \
    --region us-central1 \
    --allow-unauthenticated \
    --set-secrets="SPOTIFY_CLIENT_ID=SPOTIFY_CLIENT_ID:latest,SPOTIFY_CLIENT_SECRET=SPOTIFY_CLIENT_SECRET:latest,SPOTIFY_REFRESH_TOKEN=SPOTIFY_REFRESH_TOKEN:latest" \
    --memory 512Mi \
    --timeout 300
```

**Note:** No need for `--set-env-vars="MCP_TRANSPORT=..."` since it's set in the Dockerfile.

### 5. Test the Deployment

```bash
# Initialize connection
curl -X POST https://YOUR-SERVICE-URL/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}, "id": 1}'

# List tools
curl -X POST https://YOUR-SERVICE-URL/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 2}'

# Call a tool
curl -X POST https://YOUR-SERVICE-URL/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "spotify_get_playback", "arguments": {}}, "id": 3}'
```

### 6. Connect from Any MCP Client

For HTTP-based clients:

```json
{
  "mcpServers": {
    "spotify": {
      "transport": "streamable-http",
      "url": "https://spotify-mcp-xxxxx-uc.a.run.app/mcp"
    }
  }
}
```

For stdio-based clients (like Claude Desktop, running locally):

```json
{
  "mcpServers": {
    "spotify": {
      "command": "python",
      "args": ["-m", "spotify_mcp.server"],
      "env": {
        "SPOTIFY_CLIENT_ID": "your_client_id",
        "SPOTIFY_CLIENT_SECRET": "your_client_secret",
        "SPOTIFY_REFRESH_TOKEN": "your_refresh_token"
      }
    }
  }
}
```

---

## Local Development

```bash
# Create venv
python -m venv .venv
source .venv/bin/activate

# Install
pip install -e ".[dev]"

# Set env vars (or use .env file)
export SPOTIFY_CLIENT_ID="xxx"
export SPOTIFY_CLIENT_SECRET="xxx"
export SPOTIFY_REFRESH_TOKEN="xxx"

# Run in stdio mode (for MCP Inspector or Claude Desktop)
python -m spotify_mcp.server

# Or run in HTTP mode for local testing with curl
MCP_TRANSPORT=http python -m spotify_mcp.server
# Then test at http://localhost:8080/mcp
```

---

## Security Considerations

| Concern | Recommendation |
|---------|----------------|
| **API Access** | Use Cloud Run IAM or add API key validation |
| **Token Storage** | Use Secret Manager (single user) or Firestore (multi-user) |
| **HTTPS** | Cloud Run provides this automatically |
| **Rate Limits** | Spotify has rate limits; add caching if needed |

---

## Additional Tools You May Want to Add

```python
# Ideas for additional tools:

@mcp.tool("spotify_play_album")
async def play_album(album_name: str, artist: str = "") -> str:
    """Play a specific album."""
    ...

@mcp.tool("spotify_play_playlist")
async def play_playlist(playlist_name: str) -> str:
    """Play one of the user's playlists by name."""
    ...

@mcp.tool("spotify_create_playlist")
async def create_playlist(name: str, description: str = "") -> str:
    """Create a new playlist."""
    ...

@mcp.tool("spotify_add_to_playlist")
async def add_to_playlist(playlist_id: str, track_uri: str) -> str:
    """Add a track to a playlist."""
    ...

@mcp.tool("spotify_get_recommendations")
async def get_recommendations(seed_tracks: str, limit: int = 20) -> str:
    """Get track recommendations based on seed tracks."""
    ...
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `401 Unauthorized` | Refresh token expired; re-run OAuth flow |
| `403 Forbidden` | Missing scopes; check app settings in Spotify Dashboard |
| `No active device` | Open Spotify app on a device first |
| `Rate limited` | Add exponential backoff or caching |
| `Cloud Run timeout` | Increase `--timeout` setting |
| Container won't start | Check `MCP_TRANSPORT=http` is set in Dockerfile |
| Permission denied for secrets | Grant `roles/secretmanager.secretAccessor` to compute SA |
| OAuth redirect fails | Use `127.0.0.1` NOT `localhost` in redirect URI |

### Common SDK Pitfalls

1. **Don't use `mcp.http_app()`** - This method doesn't exist. Use `mcp.run(transport="streamable-http")` instead.

2. **Don't use `transport="sse"`** - The SSE transport is for local stdio-like usage. For HTTP servers, use `transport="streamable-http"`.

3. **Don't manually create uvicorn** - Let `mcp.run()` handle server creation.

4. **JSON responses for empty content** - Some Spotify endpoints return empty responses (204). Handle with try/except.

---

## References

- [Spotify Web API Docs](https://developer.spotify.com/documentation/web-api)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [FastMCP Examples](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples/servers/simple-streamablehttp)
- [Cloud Run Docs](https://cloud.google.com/run/docs)
- [MCP Server Development Guide](./MCP_SERVER_DEVELOPMENT_GUIDE.md) - Comprehensive guide with lessons learned
