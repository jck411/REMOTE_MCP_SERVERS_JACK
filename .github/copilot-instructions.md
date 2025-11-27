# GitHub Copilot Instructions

These guidelines help Copilot generate code consistent with this repo.

## Rule 0: Context7
- Always consult **Context7 documentation** (MCP server in VS Code) before code, dependencies, or architecture.

## Project Rules
- Code in `src/`, tests in `tests/`
- Use `uv` for deps + packaging
- `.venv/` at project root, VS Code uses `.venv/bin/python`
- Secrets in `.env` (never hardcode)
- Prefer **Pydantic AI** + **Model Context Protocol (MCP)** when possible

## Code Standards
- Python 3.11+
- PEP 8 + type hints
- `ruff` for format/lint/imports
- One responsibility per file
- Tests: `pytest`, files `test_*.py`

## Reliability & Async
- Fail fast with clear errors
- Catch broad exceptions only at boundaries
- Async/event-driven > polling
- Use async I/O for ops >10ms
- Always set timeouts
- Never swallow `CancelledError`

## Principles
- Prefer simple solutions
- Remove obsolete code
- No fake data outside tests
"""
