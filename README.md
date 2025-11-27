# Spotify MCP Server

A standalone MCP server for Spotify integration, deployable to Google Cloud Run.

**Live Deployment:** `https://spotify-mcp-421545226088.us-central1.run.app/mcp`

## Features

- **Playback control**: play, pause, skip, volume, shuffle, repeat
- **Search**: find tracks, albums, artists, playlists
- **Queue management**: view and add to queue
- **Library**: view playlists, recently played, like tracks
- **Device control**: list devices, transfer playback

## Quick Start

### 1. Set up Spotify App

1. Go to https://developer.spotify.com/dashboard
2. Create a new app
3. Note your **Client ID** and **Client Secret**
4. Add redirect URI: `http://127.0.0.1:8888/callback` (use 127.0.0.1, NOT localhost)

### 2. Get Refresh Token

```bash
# Set credentials
export SPOTIFY_CLIENT_ID="your_client_id"
export SPOTIFY_CLIENT_SECRET="your_client_secret"

# Run OAuth flow
python scripts/get_spotify_token.py
```

### 3. Local Development

```bash
# Create venv
python -m venv .venv
source .venv/bin/activate

# Install
uv pip install -e ".[dev]"

# Set env vars (or use .env file)
export SPOTIFY_CLIENT_ID="your_client_id"
export SPOTIFY_CLIENT_SECRET="your_client_secret"
export SPOTIFY_REFRESH_TOKEN="your_refresh_token"

# Run (stdio mode for local clients like Claude Desktop)
python -m spotify_mcp.server

# Run (HTTP mode for testing)
MCP_TRANSPORT=http PORT=8080 python -m spotify_mcp.server
```

### 4. Deploy to Cloud Run

```bash
# First time: Create secrets in Google Secret Manager
echo -n "your_client_id" | gcloud secrets create SPOTIFY_CLIENT_ID --data-file=-
echo -n "your_client_secret" | gcloud secrets create SPOTIFY_CLIENT_SECRET --data-file=-
echo -n "your_refresh_token" | gcloud secrets create SPOTIFY_REFRESH_TOKEN --data-file=-

# Deploy
gcloud run deploy spotify-mcp \
    --source . \
    --region us-central1 \
    --allow-unauthenticated \
    --set-secrets="SPOTIFY_CLIENT_ID=SPOTIFY_CLIENT_ID:latest,SPOTIFY_CLIENT_SECRET=SPOTIFY_CLIENT_SECRET:latest,SPOTIFY_REFRESH_TOKEN=SPOTIFY_REFRESH_TOKEN:latest" \
    --memory 512Mi \
    --timeout 300
```

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

### 6. Connect MCP Client

For HTTP-based MCP clients (like remote chatbots):

```json
{
  "mcpServers": {
    "spotify": {
      "transport": "streamable-http",
      "url": "https://spotify-mcp-421545226088.us-central1.run.app/mcp"
    }
  }
}
```

For stdio-based MCP clients (like Claude Desktop):

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

## Available Tools

| Tool | Description |
|------|-------------|
| `spotify_get_playback` | Get current playback state |
| `spotify_play` | Play track by search query or URI |
| `spotify_pause` | Pause playback |
| `spotify_next` | Skip to next track |
| `spotify_previous` | Skip to previous track |
| `spotify_volume` | Set volume (0-100) |
| `spotify_shuffle` | Toggle shuffle mode |
| `spotify_repeat` | Set repeat mode |
| `spotify_queue` | View playback queue |
| `spotify_queue_add` | Add track to queue |
| `spotify_devices` | List available devices |
| `spotify_transfer` | Transfer playback to device |
| `spotify_search` | Search for tracks/albums/artists |
| `spotify_my_playlists` | Get user's playlists |
| `spotify_recently_played` | Get recently played tracks |
| `spotify_like_track` | Save track to library |

## Architecture

### Transport Modes

| Mode | Use Case | Endpoint |
|------|----------|----------|
| `stdio` | Local clients (Claude Desktop) | N/A (stdin/stdout) |
| `streamable-http` | Remote clients, Cloud Run | `/mcp` |

### Configuration

The server uses `FastMCP` with these settings for cloud deployment:

```python
mcp = FastMCP(
    "spotify",
    stateless_http=True,   # No session state (scalable)
    json_response=True,    # JSON responses (not SSE streams)
)
```

## Project Structure

```
├── pyproject.toml
├── Dockerfile
├── .env.example
├── docs/
│   ├── spotify-mcp-server-guide.md
│   └── MCP_SERVER_DEVELOPMENT_GUIDE.md
├── scripts/
│   └── get_spotify_token.py
└── src/spotify_mcp/
    ├── __init__.py
    ├── server.py      # FastMCP tools
    ├── auth.py        # OAuth token management
    └── client.py      # Spotify API wrapper
```

## Development Guide

See [docs/MCP_SERVER_DEVELOPMENT_GUIDE.md](docs/MCP_SERVER_DEVELOPMENT_GUIDE.md) for comprehensive documentation on:

- FastMCP configuration options
- Transport types (stdio vs streamable-http)
- Cloud Run deployment best practices
- Secret management
- Common pitfalls and solutions
- Testing strategies

## License

MIT
