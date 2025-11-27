# Spotify MCP Server

A standalone MCP server for Spotify integration, deployable to Google Cloud Run.

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
4. Add redirect URI: `http://localhost:8888/callback`

### 2. Get Refresh Token

Run the one-time OAuth flow (see `docs/spotify-mcp-server-guide.md` for details).

### 3. Local Development

```bash
# Create venv
python -m venv .venv
source .venv/bin/activate

# Install
uv pip install -e ".[dev]"

# Set env vars
export SPOTIFY_CLIENT_ID="your_client_id"
export SPOTIFY_CLIENT_SECRET="your_client_secret"
export SPOTIFY_REFRESH_TOKEN="your_refresh_token"

# Run (stdio mode)
python -m spotify_mcp.server
```

### 4. Deploy to Cloud Run

```bash
gcloud run deploy spotify-mcp \
    --source . \
    --region us-central1 \
    --allow-unauthenticated \
    --set-env-vars="MCP_TRANSPORT=sse" \
    --set-secrets="SPOTIFY_CLIENT_ID=SPOTIFY_CLIENT_ID:latest,SPOTIFY_CLIENT_SECRET=SPOTIFY_CLIENT_SECRET:latest,SPOTIFY_REFRESH_TOKEN=SPOTIFY_REFRESH_TOKEN:latest"
```

### 5. Connect MCP Client

```json
{
  "mcpServers": {
    "spotify": {
      "transport": "sse",
      "url": "https://spotify-mcp-xxxxx-uc.a.run.app/sse"
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

## Project Structure

```
├── pyproject.toml
├── Dockerfile
├── .env.example
└── src/spotify_mcp/
    ├── __init__.py
    ├── server.py      # FastMCP tools
    ├── auth.py        # OAuth token management
    └── client.py      # Spotify API wrapper
```

## License

MIT
