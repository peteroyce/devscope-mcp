"""
test_github_client.py — unit tests for src/github_client.py.

All network calls are mocked using unittest.mock so these tests run without
a real GITHUB_TOKEN.

Fixed datetime: 2025-10-15T00:00:00+00:00 — avoids time-dependent failures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from github import GithubException, RateLimitExceededException

# Fixed "now" used throughout the test suite so assertions are deterministic.
FIXED_NOW = datetime(2025, 10, 15, tzinfo=timezone.utc)
FIXED_SINCE = FIXED_NOW - timedelta(days=7)  # 2025-10-08


# ---------------------------------------------------------------------------
# Helpers to build mock PyGithub objects
# ---------------------------------------------------------------------------


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _mock_repo(**kwargs) -> MagicMock:
    defaults = dict(
        full_name="owner/repo",
        description="A test repo",
        language="Python",
        stargazers_count=42,
        forks_count=7,
        open_issues_count=3,
        default_branch="main",
        private=False,
        created_at=_dt(2023, 1, 1),
        updated_at=_dt(2024, 6, 1),
        pushed_at=_dt(2024, 6, 15),
        html_url="https://github.com/owner/repo",
    )
    defaults.update(kwargs)
    repo = MagicMock(**defaults)
    repo.get_topics.return_value = ["python", "mcp"]
    return repo


# ---------------------------------------------------------------------------
# _client / token validation
# ---------------------------------------------------------------------------


class TestClientTokenValidation:
    def test_empty_token_raises_value_error(self):
        from src.github_client import _client

        with pytest.raises(ValueError, match="non-empty GITHUB_TOKEN"):
            _client(token="")

    def test_whitespace_only_token_raises_value_error(self):
        from src.github_client import _client

        with pytest.raises(ValueError, match="non-empty GITHUB_TOKEN"):
            _client(token="   ")

    def test_none_token_with_no_env_raises_value_error(self):
        from src.github_client import _client

        with patch("src.github_client.os.getenv", return_value=None):
            with pytest.raises(ValueError, match="non-empty GITHUB_TOKEN"):
                _client()

    def test_valid_token_returns_github_instance(self):
        from github import Github

        from src.github_client import _client

        with patch("src.github_client.Github") as MockGithub:
            MockGithub.return_value = MagicMock(spec=Github)
            result = _client(token="valid_token_abc")

        MockGithub.assert_called_once_with("valid_token_abc")
        assert result is not None


# ---------------------------------------------------------------------------
# _sanitise_query
# ---------------------------------------------------------------------------


class TestSanitiseQuery:
    def test_strips_AND_operator(self):
        from src.github_client import _sanitise_query

        result = _sanitise_query("foo AND bar")
        assert "AND" not in result
        assert "foo" in result
        assert "bar" in result

    def test_strips_OR_operator(self):
        from src.github_client import _sanitise_query

        result = _sanitise_query("foo OR bar")
        assert "OR" not in result

    def test_strips_NOT_operator(self):
        from src.github_client import _sanitise_query

        result = _sanitise_query("foo NOT bar")
        assert "NOT" not in result

    def test_strips_repo_qualifier(self):
        from src.github_client import _sanitise_query

        result = _sanitise_query("inject repo:evil/repo")
        assert "repo:" not in result

    def test_strips_language_qualifier(self):
        from src.github_client import _sanitise_query

        result = _sanitise_query("token language:python")
        assert "language:" not in result

    def test_strips_org_qualifier(self):
        from src.github_client import _sanitise_query

        result = _sanitise_query("secret org:target-org")
        assert "org:" not in result

    def test_plain_query_unchanged(self):
        from src.github_client import _sanitise_query

        result = _sanitise_query("authenticate user")
        assert result == "authenticate user"

    def test_multiple_operators_all_stripped(self):
        from src.github_client import _sanitise_query

        result = _sanitise_query("foo AND bar OR baz NOT qux repo:x/y language:go")
        for bad in ("AND", "OR", "NOT", "repo:", "language:"):
            assert bad not in result


# ---------------------------------------------------------------------------
# get_repo
# ---------------------------------------------------------------------------


class TestGetRepo:
    def test_returns_expected_fields(self):
        mock_repo = _mock_repo()
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_repo("owner", "repo")

        assert result["full_name"] == "owner/repo"
        assert result["language"] == "Python"
        assert result["stars"] == 42
        assert result["forks"] == 7
        assert result["open_issues"] == 3
        assert result["default_branch"] == "main"
        assert result["is_private"] is False
        assert "python" in result["topics"]
        assert result["html_url"] == "https://github.com/owner/repo"

    def test_missing_description_defaults_to_empty_string(self):
        mock_repo = _mock_repo(description=None)
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_repo("owner", "repo")

        assert result["description"] == ""

    def test_missing_language_defaults_to_unknown(self):
        mock_repo = _mock_repo(language=None)
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_repo("owner", "repo")

        assert result["language"] == "unknown"


# ---------------------------------------------------------------------------
# list_repos
# ---------------------------------------------------------------------------


class TestListRepos:
    def _make_repos(self, n: int) -> list[MagicMock]:
        repos = []
        for i in range(n):
            r = _mock_repo(
                full_name=f"myorg/repo-{i}",
                description=f"Repo {i}",
                language="TypeScript",
                stargazers_count=i * 10,
                open_issues_count=i,
                private=False,
                pushed_at=_dt(2024, 1, i + 1),
                html_url=f"https://github.com/myorg/repo-{i}",
            )
            repos.append(r)
        return repos

    def test_list_repos_for_org(self):
        repos = self._make_repos(5)
        mock_org = MagicMock()
        mock_org.get_repos.return_value = iter(repos)

        mock_g = MagicMock()
        mock_g.get_organization.return_value = mock_org

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.list_repos(org="myorg", limit=5)

        assert len(result) == 5
        assert result[0]["full_name"] == "myorg/repo-0"

    def test_limit_is_respected(self):
        repos = self._make_repos(10)
        mock_org = MagicMock()
        mock_org.get_repos.return_value = iter(repos)

        mock_g = MagicMock()
        mock_g.get_organization.return_value = mock_org

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.list_repos(org="myorg", limit=3)

        assert len(result) == 3

    def test_list_repos_for_authenticated_user_when_no_org(self):
        repos = self._make_repos(2)
        mock_user = MagicMock()
        mock_user.get_repos.return_value = iter(repos)

        mock_g = MagicMock()
        mock_g.get_user.return_value = mock_user

        with (
            patch("src.github_client._client", return_value=mock_g),
            patch("src.github_client._default_org", return_value=None),
        ):
            from src import github_client as gh

            result = gh.list_repos(org=None, limit=20)

        mock_g.get_user.assert_called_once()
        assert len(result) == 2


# ---------------------------------------------------------------------------
# get_pr_summary
# ---------------------------------------------------------------------------


class TestGetPrSummary:
    def _build_pr(self):
        pr = MagicMock()
        pr.number = 42
        pr.title = "Add authentication"
        pr.state = "closed"
        pr.user.login = "alice"
        pr.body = "Implements JWT auth."
        pr.created_at = _dt(2024, 5, 1)
        pr.updated_at = _dt(2024, 5, 10)
        pr.merged_at = _dt(2024, 5, 10)
        pr.base.ref = "main"
        pr.head.ref = "feature/auth"
        pr.review_comments = 2
        pr.commits = 3
        pr.additions = 120
        pr.deletions = 30
        pr.html_url = "https://github.com/owner/repo/pull/42"

        file1 = MagicMock(filename="auth.py", additions=100, deletions=10, status="modified")
        file2 = MagicMock(
            filename="tests/test_auth.py", additions=20, deletions=20, status="added"
        )
        pr.get_files.return_value = [file1, file2]

        comment = MagicMock()
        comment.user.login = "bob"
        comment.body = "LGTM"
        comment.created_at = _dt(2024, 5, 9)
        pr.get_issue_comments.return_value = [comment]

        return pr

    def test_pr_summary_structure(self):
        mock_pr = self._build_pr()
        mock_repo = _mock_repo()
        mock_repo.get_pull.return_value = mock_pr
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_pr_summary("owner", "repo", 42)

        assert result["number"] == 42
        assert result["title"] == "Add authentication"
        assert result["author"] == "alice"
        assert len(result["files_changed"]) == 2
        assert result["files_changed"][0]["filename"] == "auth.py"
        assert len(result["comments"]) == 1
        assert result["comments"][0]["author"] == "bob"
        assert result["additions"] == 120
        assert result["deletions"] == 30

    def test_pr_summary_null_merged_at(self):
        mock_pr = self._build_pr()
        mock_pr.merged_at = None
        mock_repo = _mock_repo()
        mock_repo.get_pull.return_value = mock_pr
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_pr_summary("owner", "repo", 42)

        assert result["merged_at"] is None


# ---------------------------------------------------------------------------
# get_issues
# ---------------------------------------------------------------------------


class TestGetIssues:
    def _make_issue(
        self, number: int, state: str = "open", is_pr: bool = False
    ) -> MagicMock:
        issue = MagicMock()
        issue.number = number
        issue.title = f"Issue {number}"
        issue.state = state
        issue.user.login = "user1"
        issue.labels = []
        issue.assignees = []
        issue.comments = 0
        issue.created_at = _dt(2024, 3, number)
        issue.updated_at = _dt(2024, 3, number)
        issue.body = f"Body of issue {number}"
        issue.html_url = f"https://github.com/owner/repo/issues/{number}"
        issue.pull_request = MagicMock() if is_pr else None
        return issue

    def test_returns_only_issues_not_prs(self):
        issues = [
            self._make_issue(1),
            self._make_issue(2, is_pr=True),  # should be filtered out
            self._make_issue(3),
        ]
        mock_repo = _mock_repo()
        mock_repo.get_issues.return_value = iter(issues)
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_issues("owner", "repo", state="open", limit=10)

        assert len(result) == 2
        numbers = [r["number"] for r in result]
        assert 2 not in numbers

    def test_limit_is_respected(self):
        issues = [self._make_issue(i) for i in range(1, 11)]
        mock_repo = _mock_repo()
        mock_repo.get_issues.return_value = iter(issues)
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_issues("owner", "repo", limit=4)

        assert len(result) == 4

    def test_body_is_truncated(self):
        issue = self._make_issue(1)
        issue.body = "x" * 1000
        mock_repo = _mock_repo()
        mock_repo.get_issues.return_value = iter([issue])
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_issues("owner", "repo")

        assert len(result[0]["body"]) == 500


# ---------------------------------------------------------------------------
# search_code
# ---------------------------------------------------------------------------


class TestSearchCode:
    def _make_code_result(self, name: str, path: str) -> MagicMock:
        item = MagicMock()
        item.name = name
        item.path = path
        item.repository.full_name = "owner/repo"
        item.html_url = f"https://github.com/owner/repo/blob/main/{path}"
        item.sha = "abc123"
        return item

    def test_search_returns_results(self):
        items = [
            self._make_code_result("auth.py", "src/auth.py"),
            self._make_code_result("middleware.py", "src/middleware.py"),
        ]
        mock_g = MagicMock()
        mock_g.search_code.return_value = iter(items)

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.search_code("authenticate")

        assert len(result) == 2
        assert result[0]["name"] == "auth.py"
        assert result[0]["path"] == "src/auth.py"

    def test_search_strips_injected_operators_before_sending(self):
        """Verify that dangerous operators in the query are stripped."""
        mock_g = MagicMock()
        mock_g.search_code.return_value = iter([])

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            gh.search_code("authenticate AND evil repo:hacker/repo language:python")

        sent_query = mock_g.search_code.call_args[0][0]
        assert "AND" not in sent_query
        assert "repo:hacker/repo" not in sent_query
        assert "language:python" not in sent_query
        # The plain keyword should survive
        assert "authenticate" in sent_query

    def test_search_with_repo_restriction_adds_trusted_qualifier(self):
        """The repo= parameter (trusted) must still appear in the final query."""
        mock_g = MagicMock()
        mock_g.search_code.return_value = iter([])

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            gh.search_code("token", repo="owner/repo")

        call_args = mock_g.search_code.call_args[0][0]
        assert "repo:owner/repo" in call_args

    def test_search_raises_runtime_error_on_github_exception(self):
        mock_g = MagicMock()
        exc = GithubException(403, {"message": "Forbidden"})
        mock_g.search_code.side_effect = exc

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            with pytest.raises(RuntimeError, match="GitHub code search failed"):
                gh.search_code("secret")

    def test_exc_data_missing_falls_back_to_str(self):
        """GithubException with data=None should not cause AttributeError.

        PyGithub's GithubException.data is a @property with no deleter, so
        we cannot ``del exc.data``.  Instead we construct an exception whose
        data property returns None (getattr fallback path) by passing None as
        the data argument — which is the real GitHub-202 / no-body situation.
        """
        mock_g = MagicMock()
        exc = GithubException(500, None)
        mock_g.search_code.side_effect = exc

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            with pytest.raises(RuntimeError, match="GitHub code search failed"):
                gh.search_code("oops")

    def test_rate_limit_exception_raises_runtime_with_reset_info(self):
        """RateLimitExceededException should surface reset time in the error."""
        mock_g = MagicMock()
        exc = RateLimitExceededException(403, {"message": "rate limit exceeded"}, headers={"x-ratelimit-reset": "1700000000"})
        mock_g.search_code.side_effect = exc

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            with pytest.raises(RuntimeError, match="rate limit"):
                gh.search_code("test")

    def test_repo_param_injection_raises_value_error(self):
        """A repo value containing injection payload must raise ValueError, not reach GitHub."""
        mock_g = MagicMock()
        mock_g.search_code.return_value = iter([])

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            with pytest.raises(ValueError, match="Invalid repo format"):
                gh.search_code("foo", repo="owner/repo repo:evil/bad")

        # The malicious string must never have been forwarded to the GitHub API
        mock_g.search_code.assert_not_called()

    def test_valid_repo_param_accepted(self):
        """A well-formed owner/repo string must pass validation without error."""
        mock_g = MagicMock()
        mock_g.search_code.return_value = iter([])

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            # Should not raise
            gh.search_code("foo", repo="valid-owner/valid.repo_name")

        mock_g.search_code.assert_called_once()
        sent_query = mock_g.search_code.call_args[0][0]
        assert "repo:valid-owner/valid.repo_name" in sent_query


# ---------------------------------------------------------------------------
# get_contributor_stats
# ---------------------------------------------------------------------------


class TestGetContributorStats:
    def _make_stat(self, login: str, total: int) -> MagicMock:
        stat = MagicMock()
        stat.author.login = login
        stat.total = total
        week = MagicMock(c=5, a=100, d=20)
        stat.weeks = [week, week, week]
        return stat

    def test_returns_sorted_by_commits_desc(self):
        stats = [
            self._make_stat("alice", 50),
            self._make_stat("bob", 200),
            self._make_stat("carol", 10),
        ]
        mock_repo = _mock_repo()
        mock_repo.get_stats_contributors.return_value = stats
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_contributor_stats("owner", "repo")

        assert isinstance(result, list)
        assert result[0]["login"] == "bob"
        assert result[0]["total_commits"] == 200
        assert result[-1]["login"] == "carol"

    def test_returns_unavailable_sentinel_when_stats_none(self):
        """GitHub HTTP 202 causes PyGithub to return None — we return a sentinel dict."""
        mock_repo = _mock_repo()
        mock_repo.get_stats_contributors.return_value = None
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_contributor_stats("owner", "repo")

        assert isinstance(result, dict)
        assert result["available"] is False
        assert "retry" in result["reason"].lower() or "computed" in result["reason"].lower()


# ---------------------------------------------------------------------------
# get_weekly_digest
# ---------------------------------------------------------------------------


def _make_merged_pr(number: int, merged_days_ago: int = 2) -> MagicMock:
    pr = MagicMock()
    pr.number = number
    pr.title = f"PR {number}"
    pr.user.login = "alice"
    pr.merged_at = FIXED_NOW - timedelta(days=merged_days_ago)
    pr.updated_at = pr.merged_at
    pr.html_url = f"https://github.com/owner/repo/pull/{number}"
    return pr


def _make_unmerged_closed_pr(number: int, updated_days_ago: int = 2) -> MagicMock:
    """A closed (not merged) PR — should never appear in merged_prs."""
    pr = MagicMock()
    pr.number = number
    pr.title = f"Closed PR {number}"
    pr.user.login = "bob"
    pr.merged_at = None
    pr.updated_at = FIXED_NOW - timedelta(days=updated_days_ago)
    pr.html_url = f"https://github.com/owner/repo/pull/{number}"
    return pr


def _make_old_pr(number: int) -> MagicMock:
    """A merged PR that is older than the 7-day window."""
    pr = MagicMock()
    pr.number = number
    pr.title = f"Old PR {number}"
    pr.user.login = "bob"
    pr.merged_at = FIXED_NOW - timedelta(days=30)
    pr.updated_at = FIXED_NOW - timedelta(days=30)
    pr.html_url = f"https://github.com/owner/repo/pull/{number}"
    return pr


def _make_digest_issue(
    number: int, state: str = "open", created_days_ago: int = 2
) -> MagicMock:
    issue = MagicMock()
    issue.number = number
    issue.title = f"Issue {number}"
    issue.user.login = "carol"
    issue.created_at = FIXED_NOW - timedelta(days=created_days_ago)
    issue.closed_at = None
    issue.state = state
    issue.html_url = f"https://github.com/owner/repo/issues/{number}"
    issue.pull_request = None
    return issue


class TestGetWeeklyDigest:
    def _run_digest(self, prs, issues, stats=None):
        mock_repo = _mock_repo()
        mock_repo.get_pulls.return_value = iter(prs)
        mock_repo.get_issues.return_value = iter(issues)
        mock_repo.get_stats_contributors.return_value = stats or []
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with (
            patch("src.github_client._client", return_value=mock_g),
            patch("src.github_client.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src import github_client as gh

            return gh.get_weekly_digest("owner", "repo")

    def test_digest_structure_keys_present(self):
        result = self._run_digest(
            prs=[_make_merged_pr(1)],
            issues=[_make_digest_issue(10)],
        )
        assert "period" in result
        assert "from" in result["period"]
        assert "to" in result["period"]
        assert "merged_prs" in result
        assert "opened_issues" in result
        assert "top_contributors" in result
        assert "stats" in result

    def test_old_pr_excluded_from_digest(self):
        result = self._run_digest(prs=[_make_old_pr(99)], issues=[])
        assert result["stats"]["merged_pr_count"] == 0

    def test_recent_merged_pr_included(self):
        result = self._run_digest(
            prs=[_make_merged_pr(7, merged_days_ago=1)],
            issues=[],
        )
        assert result["stats"]["merged_pr_count"] == 1
        assert result["merged_prs"][0]["number"] == 7

    def test_unmerged_closed_pr_not_in_merged_list(self):
        """A PR that was closed without merging must never appear in merged_prs."""
        result = self._run_digest(
            prs=[
                _make_merged_pr(1, merged_days_ago=2),
                _make_unmerged_closed_pr(2, updated_days_ago=1),
            ],
            issues=[],
        )
        numbers = [pr["number"] for pr in result["merged_prs"]]
        assert 2 not in numbers
        assert 1 in numbers

    def test_mixed_merged_and_unmerged_prs_correct_count(self):
        """Only genuinely merged PRs within the window should be counted."""
        result = self._run_digest(
            prs=[
                _make_merged_pr(1, merged_days_ago=1),
                _make_unmerged_closed_pr(2, updated_days_ago=1),
                _make_merged_pr(3, merged_days_ago=3),
                _make_old_pr(4),               # outside window
            ],
            issues=[],
        )
        assert result["stats"]["merged_pr_count"] == 2

    def test_issues_opened_and_closed_counted(self):
        closed_issue = _make_digest_issue(5, state="closed", created_days_ago=3)
        closed_issue.closed_at = FIXED_NOW - timedelta(days=1)

        result = self._run_digest(
            prs=[],
            issues=[
                _make_digest_issue(1, state="open", created_days_ago=2),
                closed_issue,
            ],
        )
        assert result["stats"]["opened_issue_count"] == 2
        assert result["stats"]["closed_issue_count"] == 1


MAX_3 = 115


MAX_9 = 145
