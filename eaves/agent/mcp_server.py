"""
Read-only MCP server exposing EAVES to LLM agents.

Implements the Model Context Protocol (https://modelcontextprotocol.io) over
stdio, so that agent clients can query EAVES configurations, runs and results
as structured tools, with the payloads of ``eaves.agent.info``. The server
runs nothing. Every tool is read-only, and execution stays with the ``eaves``
CLI and ``run_all.sh``.

Requires the optional ``mcp`` package::

    pip install -e ".[mcp]"   # or: pip install mcp

Run over stdio (this is what MCP clients spawn)::

    eaves mcp
"""

from __future__ import annotations

import json
from pathlib import Path

from eaves.agent import info

# The server class is MCPServer in the mcp SDK 2 and FastMCP from version 1.3, and either serves the same decorated tools
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
    except ImportError:
        MCPServer = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_MISSING_SDK_MSG = (
    "The MCP server requires the optional 'mcp' package. "
    "Install it with: pip install -e \".[mcp]\" (or: pip install mcp)"
)


def _guarded(build, *args) -> dict:
    """Return the payload of build, or an error dict when the settings file or the table it reads is missing or invalid."""
    try:
        return build(*args)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def build_server():
    """Construct the MCP server with the read-only EAVES tool set."""
    if MCPServer is None:
        raise RuntimeError(_MISSING_SDK_MSG)

    server = MCPServer(
        "eaves",
        instructions=(
            "Read-only access to EAVES (Elevation-Area-Volume Estimation from SRTM) "
            "configurations, runs and results. Nothing here runs the pipeline, "
            "use the `eaves` CLI or run_all.sh for execution. Read the agents_brief "
            "tool first. The run tools take the settings JSON of a run."
        ),
    )

    @server.tool()
    def agents_brief() -> str:
        """Return AGENTS.md, the operational brief for working with this repository."""
        path = PROJECT_ROOT / "AGENTS.md"
        if not path.is_file():
            return "AGENTS.md not found in this installation."
        return path.read_text()

    @server.tool()
    def pipeline_steps() -> list[dict]:
        """List the five steps of an end-to-end run in order, with the module of each, what it makes, its compute cost class and its output files."""
        return info.steps()

    @server.tool()
    def resolved_config(settings_file: str) -> dict:
        """Load and validate a settings JSON, returning the resolved settings, the layout of the output tree and the defaults of eaves.config for the keys the file leaves out. Read-only."""
        return _guarded(info.resolved_config, settings_file)

    @server.tool()
    def run_status(settings_file: str) -> dict:
        """Return which outputs of a run exist: the tables, the EAV tables and check maps by count, the validation and uncertainty tables, the panels, the report and the domain characterization with its JSON twin, with the headline counts of the parameter, summary and failure tables. Read-only."""
        return _guarded(info.run_status, settings_file)

    @server.tool()
    def run_outputs(settings_file: str) -> dict:
        """Return the key tables and figures of a run, with what each shows, its path and whether it exists. Read-only."""
        return _guarded(info.run_outputs, settings_file)

    @server.tool()
    def domain_characterization(settings_file: str) -> dict:
        """Return the domain characterization of a run, every statistic by name with a typed value, as the report step writes it. Read-only."""
        return _guarded(info.characterization, settings_file)

    @server.tool()
    def dam_results(query: str, settings_file: str) -> dict:
        """Return the results of the dams whose identifier equals the query or whose name contains it, case-insensitive: the released parameters, the summary row with the fill, the fit, the grade and the flags, the failure row where one exists, and the paths of the EAV table and the check map. Read-only."""
        return _guarded(info.dam, query, settings_file)

    return server


def main() -> int:
    """Entry point behind `eaves mcp`, serves over stdio until the client disconnects."""
    if MCPServer is None:
        print(_MISSING_SDK_MSG)
        return 1
    build_server().run()
    return 0
