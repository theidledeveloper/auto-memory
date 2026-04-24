"""Parser introspection tests — every subcommand has a TIER_MAP entry."""
import pytest

from session_recall.__main__ import TIER_MAP, build_parser


def test_tier_map_covers_all_subcommands():
    """Every registered subcommand must have a TIER_MAP entry."""
    known_commands = {
        "list",
        "schema-check",
        "init",
        "doctor",
        "files",
        "checkpoints",
        "context",
        "show",
        "export",
        "diff",
        "search",
        "stats",
        "calibrate",
        "health",
    }
    missing = known_commands - set(TIER_MAP.keys())
    assert not missing, f"Subcommands missing from TIER_MAP: {missing}"


def test_help_text_says_10_dimensions():
    """Regression guard against stale docstring."""
    from session_recall.commands import health
    assert "10 dimension" in health.__doc__.lower() or "10-dimension" in health.__doc__.lower()


def test_health_includes_file_freshness_dimension():
    from session_recall.commands.health import DIMS

    assert any(dim.__name__.endswith("dim_file_freshness") for dim in DIMS)


def test_parser_uses_session_recall_prog_name():
    parser = build_parser()
    assert parser.prog == "session-recall"


def test_parser_help_mentions_version_and_all_time_days_policy():
    parser = build_parser()
    main_help = parser.format_help()
    list_parser = parser._subparsers._group_actions[0].choices["list"]
    context_parser = parser._subparsers._group_actions[0].choices["context"]
    export_parser = parser._subparsers._group_actions[0].choices["export"]
    diff_parser = parser._subparsers._group_actions[0].choices["diff"]
    stats_parser = parser._subparsers._group_actions[0].choices["stats"]
    calibrate_parser = parser._subparsers._group_actions[0].choices["calibrate"]
    list_help = " ".join(list_parser.format_help().split())
    show_help = " ".join(parser._subparsers._group_actions[0].choices["show"].format_help().split())
    export_help = " ".join(export_parser.format_help().split())
    diff_help = " ".join(diff_parser.format_help().split())

    assert "--version" in main_help
    assert "--debug" in main_help
    assert "Health check (10 dimensions)" in main_help
    assert "export" in main_help
    assert "diff" in main_help
    assert "stats" in main_help
    assert "calibrate" in main_help
    assert "context" in main_help
    assert "all time by default" in list_help
    assert "--source {copilot,claude}" in list_help
    assert "--budget" in context_parser.format_help()
    assert "Approximate recall bundle" in context_parser.format_help()
    assert "--format {md}" in export_parser.format_help()
    assert "--source {copilot,claude}" in export_help
    assert "Compare two sessions" in diff_parser.format_help()
    assert "--source {copilot,claude}" in diff_help
    assert "--source {copilot,claude}" in show_help
    assert "defaults to all" in stats_parser.format_help()
    assert "--analyze" in calibrate_parser.format_help()


def test_version_flag_uses_session_recall_prefix(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("session-recall ")


def test_main_prints_help_to_stderr_when_no_command(monkeypatch, capsys):
    from session_recall import __main__ as cli

    monkeypatch.setattr(cli.sys, "argv", ["session-recall"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage: session-recall" in captured.err
