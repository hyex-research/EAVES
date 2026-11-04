"""Unit tests for the read-only MCP server module (eaves/agent/mcp_server.py)."""

from __future__ import annotations

import asyncio

import pytest

from eaves.agent import mcp_server

RUN_TOOLS = ["resolved_config", "run_status", "run_outputs", "domain_characterization", "dam_results"]


def test_main_without_sdk(monkeypatch, capsys):
    monkeypatch.setattr(mcp_server, "MCPServer", None)
    assert mcp_server.main() == 1
    assert "mcp" in capsys.readouterr().out
    with pytest.raises(RuntimeError):
        mcp_server.build_server()


@pytest.mark.skipif(mcp_server.MCPServer is None, reason="optional mcp SDK not installed")
def test_build_server_registers_tools():
    server = mcp_server.build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"agents_brief", "pipeline_steps", *RUN_TOOLS} <= names


@pytest.mark.skipif(mcp_server.MCPServer is None, reason="optional mcp SDK not installed")
def test_agents_brief_returns_the_brief():
    server = mcp_server.build_server()
    result = asyncio.run(server.call_tool("agents_brief", {}))
    assert "EAVES agent guide" in str(result)


@pytest.mark.skipif(mcp_server.MCPServer is None, reason="optional mcp SDK not installed")
@pytest.mark.parametrize("tool", RUN_TOOLS)
def test_run_tools_report_a_missing_settings_file(tool, tmp_path):
    server = mcp_server.build_server()
    arguments = {"settings_file": str(tmp_path / "absent.json")}
    if tool == "dam_results":
        arguments["query"] = "id_120000"
    result = asyncio.run(server.call_tool(tool, arguments))
    assert "error" in str(result) and "FileNotFoundError" in str(result)


@pytest.mark.parametrize("build", ["resolved_config", "run_status", "run_outputs", "characterization"])
def test_guarded_turns_an_invalid_settings_file_into_an_error(build, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"bogus": 1}')
    result = mcp_server._guarded(getattr(mcp_server.info, build), str(settings))
    assert result["error"].startswith("ValueError")


def test_guarded_turns_an_empty_dam_query_into_an_error(tmp_path):
    result = mcp_server._guarded(mcp_server.info.dam, " ", str(tmp_path / "absent.json"))
    assert result["error"].startswith("ValueError")
