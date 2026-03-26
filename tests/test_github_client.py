"""
test_github_client.py — unit tests for src/github_client.py.

All network calls are mocked using pytest-mock / unittest.mock so these
tests run without a real GITHUB_TOKEN.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# We patch `github_client._client` to return a fully-mocked Github instance
# so every test stays isolated from the network.


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
# get_repo
# ---------------------------------------------------------------------------


class TestGetRepo:
    def test_returns_expected_fields(self, monkeypatch):
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

    def test_missing_description_defaults_to_empty_string(self, monkeypatch):
        mock_repo = _mock_repo(description=None)
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_repo("owner", "repo")

        assert result["description"] == ""

    def test_missing_language_defaults_to_unknown(self, monkeypatch):
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
        file2 = MagicMock(filename="tests/test_auth.py", additions=20, deletions=20, status="added")
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
    def _make_issue(self, number: int, state: str = "open", is_pr: bool = False) -> MagicMock:
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

    def test_search_with_repo_restriction(self):
        mock_g = MagicMock()
        mock_g.search_code.return_value = iter([])

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            gh.search_code("token", repo="owner/repo")

        call_args = mock_g.search_code.call_args[0][0]
        assert "repo:owner/repo" in call_args

    def test_search_raises_runtime_error_on_github_exception(self):
        from github import GithubException

        mock_g = MagicMock()
        mock_g.search_code.side_effect = GithubException(403, {"message": "Forbidden"})

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            with pytest.raises(RuntimeError, match="GitHub code search failed"):
                gh.search_code("secret")


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

        assert result[0]["login"] == "bob"
        assert result[0]["total_commits"] == 200
        assert result[-1]["login"] == "carol"

    def test_returns_empty_list_when_stats_none(self):
        mock_repo = _mock_repo()
        mock_repo.get_stats_contributors.return_value = None
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_contributor_stats("owner", "repo")

        assert result == []


# ---------------------------------------------------------------------------
# get_weekly_digest
# ---------------------------------------------------------------------------


class TestGetWeeklyDigest:
    def _make_merged_pr(self, number: int, days_ago: int = 2) -> MagicMock:
        from datetime import timedelta

        pr = MagicMock()
        pr.number = number
        pr.title = f"PR {number}"
        pr.user.login = "alice"
        pr.merged_at = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
        pr.updated_at = pr.merged_at
        pr.html_url = f"https://github.com/owner/repo/pull/{number}"
        pr.pull_request = MagicMock()
        return pr

    def _make_old_pr(self, number: int) -> MagicMock:
        from datetime import timedelta

        pr = MagicMock()
        pr.number = number
        pr.title = f"Old PR {number}"
        pr.user.login = "bob"
        pr.merged_at = None
        pr.updated_at = datetime.now(tz=timezone.utc) - timedelta(days=30)
        pr.html_url = f"https://github.com/owner/repo/pull/{number}"
        return pr

    def _make_issue(self, number: int, state: str = "open", days_ago: int = 2) -> MagicMock:
        from datetime import timedelta

        issue = MagicMock()
        issue.number = number
        issue.title = f"Issue {number}"
        issue.user.login = "carol"
        issue.created_at = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
        issue.closed_at = None
        issue.state = state
        issue.html_url = f"https://github.com/owner/repo/issues/{number}"
        issue.pull_request = None
        return issue

    def test_digest_structure(self):
        mock_repo = _mock_repo()
        mock_repo.get_pulls.return_value = iter(
            [self._make_merged_pr(1), self._make_old_pr(2)]
        )
        issue = self._make_issue(10)
        mock_repo.get_issues.return_value = iter([issue])
        mock_repo.get_stats_contributors.return_value = []
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_weekly_digest("owner", "repo")

        assert "period" in result
        assert "from" in result["period"]
        assert "to" in result["period"]
        assert "merged_prs" in result
        assert "opened_issues" in result
        assert "top_contributors" in result
        assert "stats" in result

    def test_old_prs_excluded_from_digest(self):
        mock_repo = _mock_repo()
        mock_repo.get_pulls.return_value = iter([self._make_old_pr(99)])
        mock_repo.get_issues.return_value = iter([])
        mock_repo.get_stats_contributors.return_value = []
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_weekly_digest("owner", "repo")

        assert result["stats"]["merged_pr_count"] == 0

    def test_recent_merged_pr_included(self):
        mock_repo = _mock_repo()
        mock_repo.get_pulls.return_value = iter([self._make_merged_pr(7, days_ago=1)])
        mock_repo.get_issues.return_value = iter([])
        mock_repo.get_stats_contributors.return_value = []
        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo

        with patch("src.github_client._client", return_value=mock_g):
            from src import github_client as gh

            result = gh.get_weekly_digest("owner", "repo")

        assert result["stats"]["merged_pr_count"] == 1
        assert result["merged_prs"][0]["number"] == 7
