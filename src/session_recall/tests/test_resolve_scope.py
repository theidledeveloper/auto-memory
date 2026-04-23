"""Direct tests for repo/path scope resolution helpers."""
from unittest.mock import patch

from session_recall.util.detect_repo import _parse_remote_url, detect_repo
from session_recall.util.resolve_scope import Scope, resolve_scope, time_filter_sql


def test_resolve_scope_prefers_detected_repo():
    with patch("session_recall.util.resolve_scope.detect_repo", return_value="owner/repo"), \
         patch("session_recall.util.resolve_scope._git_toplevel", return_value="/workspace/project"):
        scope = resolve_scope(cwd="/workspace/project")

    assert scope == Scope("repo", "owner/repo", "owner/repo")


def test_resolve_scope_falls_back_to_git_toplevel_path():
    with patch("session_recall.util.resolve_scope.detect_repo", return_value=None), \
         patch("session_recall.util.resolve_scope._git_toplevel", return_value="/workspace/project"):
        scope = resolve_scope(cwd="/workspace/project/subdir")

    assert scope == Scope("path", "/workspace/project", "/workspace/project")


def test_resolve_scope_falls_back_to_current_directory_path():
    with patch("session_recall.util.resolve_scope.detect_repo", return_value=None), \
         patch("session_recall.util.resolve_scope._git_toplevel", return_value=None):
        scope = resolve_scope(cwd="/workspace/project/subdir")

    assert scope == Scope("path", "/workspace/project/subdir", "/workspace/project/subdir")


def test_resolve_scope_treats_dot_relative_path_as_path():
    scope = resolve_scope("./subproject", cwd="/workspace/project")

    assert scope == Scope("path", "/workspace/project/subproject", "/workspace/project/subproject")


def test_resolve_scope_preserves_repo_slug_argument():
    scope = resolve_scope("owner/repo", cwd="/workspace/project")

    assert scope == Scope("repo", "owner/repo", "owner/repo")


def test_parse_remote_url_supports_ssh_and_https():
    assert _parse_remote_url("git@github.com:owner/repo.git") == "owner/repo"
    assert _parse_remote_url("https://github.com/owner/repo.git") == "owner/repo"
    assert _parse_remote_url("https://github.com/owner/repo") == "owner/repo"


def test_detect_repo_prefers_origin_then_other_remotes():
    outputs = {
        ("remote", "get-url", "origin"): "",
        ("remote",): "upstream\nmirror",
        ("remote", "get-url", "upstream"): "git@github.com:owner/repo.git",
    }

    def fake_git_output(args, cwd=None):
        return outputs.get(tuple(args), "")

    with patch("session_recall.util.detect_repo._git_output", side_effect=fake_git_output):
        assert detect_repo(cwd="/workspace/project") == "owner/repo"


def test_time_filter_sql_zero_days_means_today():
    clause, params = time_filter_sql("created_at", 0)

    assert clause == "date(created_at) >= date('now')"
    assert params == ()
