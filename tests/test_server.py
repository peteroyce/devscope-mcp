"""
test_server.py — unit tests for src/server.py dispatcher and formatting helpers.

Tests focus on:
  - Unknown tool name → descriptive ValueError (surfaced as error response)
  - Valid tool dispatch routing
  - Integer conversion failure → error response (not crash)
  - _fmt_weekly_digest variable-name bug regression
  - _fmt_contributor_stats sentinel dict handling
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _dispatch: unknown tool
# ---------------------------------------------------------------------------


class TestDispatchUnknownTool:
    def test_unknown_tool_raises_value_error(self):
        from src.server import _dispatch

        with pytest.raises(ValueError, match="Unknown tool"):
            _dispatch("does_not_exist", {})

    def test_error_message_lists_known_tools(self):
        from src.server import _dispatch

        with pytest.raises(ValueError) as exc_info:
            _dispatch("does_not_exist", {})

        msg = str(exc_info.value)
        # At least a couple of real tool names should be in the error message
        assert "list_repos" in msg or "get_repo_info" in msg

    def test_empty_tool_name_raises_value_error(self):
        from src.server import _dispatch

        with pytest.raises(ValueError, match="Unknown tool"):
            _dispatch("", {})


# ---------------------------------------------------------------------------
# _dispatch: valid tool routing
# ---------------------------------------------------------------------------


class TestDispatchValidTools:
    def test_list_repos_routed_correctly(self):
        from src.server import _dispatch

        with patch("src.server.gh.list_repos", return_value=[]) as mock_fn:
            result = _dispatch("list_repos", {"org": "myorg", "limit": 5})

        mock_fn.assert_called_once_with(org="myorg", limit=5)
        assert isinstance(result, str)

    def test_get_repo_info_routed_correctly(self):
        from src.server import _dispatch

        fake_repo = {
            "full_name": "owner/repo",
            "description": "desc",
            "language": "Python",
            "stars": 1,
            "forks": 0,
            "open_issues": 0,
            "default_branch": "main",
            "topics": [],
            "is_private": False,
            "created_at": "2024-01-01",
            "updated_at": "2024-06-01",
            "html_url": "https://github.com/owner/repo",
        }
        with patch("src.server.gh.get_repo", return_value=fake_repo):
            result = _dispatch("get_repo_info", {"owner": "owner", "repo": "repo"})

        assert "owner/repo" in result

    def test_search_code_routed_correctly(self):
        from src.server import _dispatch

        with patch("src.server.gh.search_code", return_value=[]) as mock_fn:
            result = _dispatch("search_code", {"query": "auth"})

        mock_fn.assert_called_once_with(query="auth", repo=None)
        assert isinstance(result, str)

    def test_get_contributor_stats_routed_correctly(self):
        from src.server import _dispatch

        with patch("src.server.gh.get_contributor_stats", return_value=[]) as mock_fn:
            result = _dispatch("get_contributor_stats", {"owner": "o", "repo": "r"})

        mock_fn.assert_called_once_with(owner="o", repo="r")
        assert isinstance(result, str)

    def test_get_weekly_digest_routed_correctly(self):
        from src.server import _dispatch

        fake_digest = {
            "period": {"from": "2025-10-08T00:00:00+00:00", "to": "2025-10-15T00:00:00+00:00"},
            "merged_prs": [],
            "opened_issues": [],
            "top_contributors": [],
            "stats": {"merged_pr_count": 0, "opened_issue_count": 0, "closed_issue_count": 0},
        }
        with patch("src.server.gh.get_weekly_digest", return_value=fake_digest):
            result = _dispatch("get_weekly_digest", {"owner": "o", "repo": "r"})

        assert "Weekly Digest" in result


# ---------------------------------------------------------------------------
# _dispatch: integer argument safety
# ---------------------------------------------------------------------------


class TestDispatchIntegerSafety:
    def test_non_integer_pr_number_raises_value_error(self):
        from src.server import _dispatch

        with pytest.raises(ValueError, match="pr_number"):
            _dispatch("summarize_pr", {"owner": "o", "repo": "r", "pr_number": "not_a_number"})

    def test_non_integer_limit_for_list_repos_raises_value_error(self):
        from src.server import _dispatch

        with pytest.raises(ValueError, match="limit"):
            _dispatch("list_repos", {"limit": "oops"})

    def test_non_integer_limit_for_list_issues_raises_value_error(self):
        from src.server import _dispatch

        with pytest.raises(ValueError, match="limit"):
            _dispatch("list_issues", {"owner": "o", "repo": "r", "limit": "bad"})

    def test_string_integer_for_pr_number_is_accepted(self):
        """'42' (string digit) should coerce cleanly to int."""
        from src.server import _dispatch

        fake_pr = {
            "number": 42,
            "title": "Test PR",
            "state": "open",
            "author": "alice",
            "body": "",
            "created_at": "2024-01-01",
            "updated_at": "2024-01-02",
            "merged_at": None,
            "base_branch": "main",
            "head_branch": "feature",
            "files_changed": [],
            "comments": [],
            "review_comments_count": 0,
            "commits_count": 1,
            "additions": 5,
            "deletions": 0,
            "html_url": "https://github.com/o/r/pull/42",
        }
        with patch("src.server.gh.get_pr_summary", return_value=fake_pr) as mock_fn:
            result = _dispatch("summarize_pr", {"owner": "o", "repo": "r", "pr_number": "42"})

        mock_fn.assert_called_once_with(owner="o", repo="r", pr_number=42)
        assert "PR #42" in result


# ---------------------------------------------------------------------------
# handle_call_tool: async error surface
# ---------------------------------------------------------------------------


class TestHandleCallToolErrorSurface:
    """
    Verify that errors raised in _dispatch are caught and returned as
    TextContent error messages rather than propagating as exceptions.
    """

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_text_content(self):
        from src.server import handle_call_tool

        result = await handle_call_tool("nonexistent_tool", {})

        assert len(result) == 1
        assert "Unknown tool" in result[0].text or "Invalid request" in result[0].text

    @pytest.mark.asyncio
    async def test_bad_integer_returns_error_text_content(self):
        from src.server import handle_call_tool

        result = await handle_call_tool(
            "summarize_pr", {"owner": "o", "repo": "r", "pr_number": "xyz"}
        )

        assert len(result) == 1
        assert "Invalid request" in result[0].text or "pr_number" in result[0].text

    @pytest.mark.asyncio
    async def test_environment_error_returns_configuration_error(self):
        from src.server import handle_call_tool

        with patch("src.server.gh.list_repos", side_effect=EnvironmentError("No token")):
            result = await handle_call_tool("list_repos", {})

        assert len(result) == 1
        assert "Configuration error" in result[0].text

    @pytest.mark.asyncio
    async def test_runtime_error_returns_github_api_error(self):
        from src.server import handle_call_tool

        with patch("src.server.gh.list_repos", side_effect=RuntimeError("API error")):
            result = await handle_call_tool("list_repos", {})

        assert len(result) == 1
        assert "GitHub API error" in result[0].text


# ---------------------------------------------------------------------------
# _fmt_weekly_digest: regression for variable-shadowing bug
# ---------------------------------------------------------------------------


class TestFmtWeeklyDigest:
    def _make_digest(self, merged_prs=None, opened_issues=None, top_contributors=None):
        return {
            "period": {"from": "2025-10-08T00:00:00+00:00", "to": "2025-10-15T00:00:00+00:00"},
            "merged_prs": merged_prs or [],
            "opened_issues": opened_issues or [],
            "top_contributors": top_contributors or [],
            "stats": {
                "merged_pr_count": len(merged_prs or []),
                "opened_issue_count": len(opened_issues or []),
                "closed_issue_count": 0,
            },
        }

    def test_empty_digest_renders_without_error(self):
        from src.server import _fmt_weekly_digest

        result = _fmt_weekly_digest(self._make_digest())
        assert "Weekly Digest" in result
        assert "Merged PRs: none" in result
        assert "Opened Issues: none" in result

    def test_merged_prs_rendered_with_pr_fields_not_period_fields(self):
        """Regression: original code used `p` (the period dict) inside the PR loop."""
        from src.server import _fmt_weekly_digest

        digest = self._make_digest(
            merged_prs=[
                {
                    "number": 7,
                    "title": "Fix the bug",
                    "author": "alice",
                    "merged_at": "2025-10-14T10:00:00+00:00",
                    "html_url": "https://github.com/o/r/pull/7",
                }
            ]
        )
        result = _fmt_weekly_digest(digest)
        assert "#7" in result
        assert "Fix the bug" in result
        assert "alice" in result

    def test_opened_issues_rendered_correctly(self):
        from src.server import _fmt_weekly_digest

        digest = self._make_digest(
            opened_issues=[
                {
                    "number": 42,
                    "title": "Something broke",
                    "author": "bob",
                    "created_at": "2025-10-13T08:00:00+00:00",
                    "html_url": "https://github.com/o/r/issues/42",
                }
            ]
        )
        result = _fmt_weekly_digest(digest)
        assert "#42" in result
        assert "Something broke" in result

    def test_top_contributors_rendered(self):
        from src.server import _fmt_weekly_digest

        digest = self._make_digest(
            top_contributors=[{"login": "carol", "commits": 12}]
        )
        result = _fmt_weekly_digest(digest)
        assert "carol" in result
        assert "12" in result


# ---------------------------------------------------------------------------
# _fmt_contributor_stats: sentinel dict handling
# ---------------------------------------------------------------------------


class TestFmtContributorStats:
    def test_sentinel_dict_returns_unavailable_message(self):
        from src.server import _fmt_contributor_stats

        sentinel = {"available": False, "reason": "Stats are being computed, retry in a moment"}
        result = _fmt_contributor_stats(sentinel)
        assert "not yet available" in result
        assert "computed" in result.lower() or "retry" in result.lower()

    def test_empty_list_returns_fallback_message(self):
        from src.server import _fmt_contributor_stats

        result = _fmt_contributor_stats([])
        assert "No contributor stats" in result

    def test_valid_stats_list_rendered(self):
        from src.server import _fmt_contributor_stats

        stats = [
            {"login": "alice", "total_commits": 100, "additions": 500, "deletions": 200, "weeks_active": 10},
            {"login": "bob", "total_commits": 50, "additions": 300, "deletions": 100, "weeks_active": 5},
        ]
        result = _fmt_contributor_stats(stats)
        assert "alice" in result
        assert "100" in result
        assert "bob" in result


def process_4(items):
    """Process batch."""
    return [x for x in items if x]


def process_10(items):
    """Process batch."""
    return [x for x in items if x]
