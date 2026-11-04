"""
Tests for ``eaves.cli``, the argument parser and the read-only commands.

They parse the flags of the pipeline and the info and mcp commands, and run
``info`` in the process and through ``python -m eaves``. They do NOT run the
pipeline, which is the job of the regression test.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from eaves import cli
from eaves.agent import mcp_server

from .conftest import REPO_ROOT, TEST_SETTINGS


def test_pipeline_flags_parse_without_a_command() -> None:
    args = cli.build_parser().parse_args([
        "--settings", "s.json", "--only", "id_010001", "id_120000", "--plot-only", "--rerun",
        "--output-dir", "out", "--srtm-dir", "srtm", "--rebuild-domain", "--panels",
    ])
    assert args.command is None
    assert (args.settings, args.only, args.output_dir, args.srtm_dir) == ("s.json", ["id_010001", "id_120000"], "out", "srtm")
    assert args.plot_only and args.rerun and args.rebuild_domain and args.panels
    assert not args.panels_only


def test_flags_after_the_dam_ids_and_comma_separated_ids_parse() -> None:
    args = cli.build_parser().parse_args(["--only", "id_010001,id_120000", "--panels-only", "--settings", "s.json"])
    assert (args.command, args.only, args.panels_only, args.settings) == (None, ["id_010001,id_120000"], True, "s.json")


def test_no_arguments_parse_to_a_pipeline_run() -> None:
    args = cli.build_parser().parse_args([])
    assert (args.command, args.settings, args.only) == (None, None, None)
    assert not (args.plot_only or args.rerun or args.rebuild_domain or args.panels or args.panels_only)


def test_info_and_mcp_parse() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["info", "s.json"])
    assert (args.command, args.settings) == ("info", "s.json")
    assert parser.parse_args(["mcp"]).command == "mcp"


@pytest.mark.parametrize("argv", [["info"], ["simulate"], ["mcp", "s.json"]], ids=["info_without_settings", "unknown_command", "mcp_with_argument"])
def test_malformed_commands_are_refused(argv) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(argv)


def test_info_prints_the_resolved_configuration(capsys) -> None:
    assert cli.main(["info", str(TEST_SETTINGS)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["settings_file"] == str(TEST_SETTINGS.resolve())
    assert payload["output_layout"]["1_results_csv"] == str(TEST_SETTINGS.parent / "output" / "1_results_csv")


def test_info_on_a_missing_settings_file_exits_1(tmp_path, capsys) -> None:
    assert cli.main(["info", str(tmp_path / "absent.json")]) == 1
    assert "not found" in capsys.readouterr().err


def test_info_on_an_invalid_settings_file_exits_1(tmp_path, capsys) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text('{"bogus": 1}')
    assert cli.main(["info", str(settings)]) == 1
    assert "unknown setting key" in capsys.readouterr().err


def test_mcp_without_sdk_exits_1(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mcp_server, "MCPServer", None)
    assert cli.main(["mcp"]) == 1
    assert "mcp" in capsys.readouterr().out


def test_module_entry_point_passes_the_exit_code(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "eaves", "info", str(tmp_path / "absent.json")],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "not found" in result.stderr
