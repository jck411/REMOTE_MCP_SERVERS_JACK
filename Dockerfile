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

# Run the MCP server with streamable HTTP transport
CMD ["python", "-m", "spotify_mcp.server"]
