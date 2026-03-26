"""
github_client.py — thin wrapper around PyGithub for devscope-mcp.

All public functions accept plain Python types and return plain dicts / lists
so that the MCP server layer stays free of PyGithub objects.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv
from github import Github, GithubException
from github.Repository import Repository

load_dotenv()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _client() -> Github:
    """Return an authenticated Github client, reading the token from the env."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise EnvironmentError(
            "GITHUB_TOKEN is not set. Add it to your .env file or environment."
        )
    return Github(token)


def _default_org() -> str | None:
    return os.getenv("GITHUB_DEFAULT_ORG") or None


def _repo(g: Github, owner: str, repo: str) -> Repository:
    return g.get_repo(f"{owner}/{repo}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_repo(owner: str, repo: str) -> dict[str, Any]:
    """
    Return basic metadata for a single repository.

    Returns:
        {
            full_name, description, language, stars, forks, open_issues,
            default_branch, topics, is_private, created_at, updated_at, html_url
        }
    """
    g = _client()
    r = _repo(g, owner, repo)

    return {
        "full_name": r.full_name,
        "description": r.description or "",
        "language": r.language or "unknown",
        "stars": r.stargazers_count,
        "forks": r.forks_count,
        "open_issues": r.open_issues_count,
        "default_branch": r.default_branch,
        "topics": r.get_topics(),
        "is_private": r.private,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "html_url": r.html_url,
    }


def list_repos(org: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """
    List repositories for an org (or the authenticated user if org is None).

    Returns a list of lightweight repo dicts sorted by most recently pushed.
    """
    g = _client()
    target_org = org or _default_org()

    if target_org:
        gh_org = g.get_organization(target_org)
        repos_iter = gh_org.get_repos(sort="pushed", direction="desc")
    else:
        user = g.get_user()
        repos_iter = user.get_repos(sort="pushed", direction="desc")

    results: list[dict[str, Any]] = []
    for r in repos_iter:
        results.append(
            {
                "full_name": r.full_name,
                "description": r.description or "",
                "language": r.language or "unknown",
                "stars": r.stargazers_count,
                "open_issues": r.open_issues_count,
                "is_private": r.private,
                "pushed_at": r.pushed_at.isoformat() if r.pushed_at else None,
                "html_url": r.html_url,
            }
        )
        if len(results) >= limit:
            break

    return results


def get_pr_summary(owner: str, repo: str, pr_number: int) -> dict[str, Any]:
    """
    Return a rich summary for a pull request.

    Returns:
        {
            number, title, state, author, body, created_at, updated_at,
            merged_at, base_branch, head_branch,
            files_changed: [{filename, additions, deletions, status}],
            comments: [{author, body, created_at}],
            review_comments_count, commits_count, additions, deletions,
            html_url
        }
    """
    g = _client()
    r = _repo(g, owner, repo)
    pr = r.get_pull(pr_number)

    # Files changed
    files_changed = [
        {
            "filename": f.filename,
            "additions": f.additions,
            "deletions": f.deletions,
            "status": f.status,
        }
        for f in pr.get_files()
    ]

    # Issue comments (general conversation thread)
    comments = [
        {
            "author": c.user.login if c.user else "ghost",
            "body": c.body,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in pr.get_issue_comments()
    ]

    return {
        "number": pr.number,
        "title": pr.title,
        "state": pr.state,
        "author": pr.user.login if pr.user else "ghost",
        "body": pr.body or "",
        "created_at": pr.created_at.isoformat() if pr.created_at else None,
        "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
        "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
        "base_branch": pr.base.ref,
        "head_branch": pr.head.ref,
        "files_changed": files_changed,
        "comments": comments,
        "review_comments_count": pr.review_comments,
        "commits_count": pr.commits,
        "additions": pr.additions,
        "deletions": pr.deletions,
        "html_url": pr.html_url,
    }


def get_issues(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    List issues for a repository.

    Args:
        state: "open", "closed", or "all"
        limit: maximum number of issues to return

    Returns a list of issue dicts.
    """
    g = _client()
    r = _repo(g, owner, repo)
    issues_iter = r.get_issues(state=state, sort="updated", direction="desc")

    results: list[dict[str, Any]] = []
    for issue in issues_iter:
        # PyGithub returns PRs via get_issues too; filter them out
        if issue.pull_request:
            continue
        results.append(
            {
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "author": issue.user.login if issue.user else "ghost",
                "labels": [lbl.name for lbl in issue.labels],
                "assignees": [a.login for a in issue.assignees],
                "comments": issue.comments,
                "created_at": issue.created_at.isoformat() if issue.created_at else None,
                "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
                "body": (issue.body or "")[:500],  # truncate long bodies
                "html_url": issue.html_url,
            }
        )
        if len(results) >= limit:
            break

    return results


def search_code(query: str, repo: str | None = None) -> list[dict[str, Any]]:
    """
    Search code on GitHub.

    Args:
        query: GitHub code-search query string (e.g. "auth token")
        repo:  optional "owner/repo" to restrict the search

    Returns a list of result dicts.
    """
    g = _client()
    full_query = f"{query} repo:{repo}" if repo else query

    results: list[dict[str, Any]] = []
    try:
        for item in g.search_code(full_query):
            results.append(
                {
                    "name": item.name,
                    "path": item.path,
                    "repository": item.repository.full_name,
                    "html_url": item.html_url,
                    "sha": item.sha,
                }
            )
            if len(results) >= 20:
                break
    except GithubException as exc:
        # Code search requires authentication and can be rate-limited
        raise RuntimeError(f"GitHub code search failed: {exc.data}") from exc

    return results


def get_contributor_stats(owner: str, repo: str) -> list[dict[str, Any]]:
    """
    Return contribution statistics per contributor.

    Returns a list sorted by total commits descending:
        [{login, total_commits, additions, deletions, weeks_active}]
    """
    g = _client()
    r = _repo(g, owner, repo)
    stats = r.get_stats_contributors()

    if stats is None:
        return []

    results = []
    for stat in stats:
        weeks_active = sum(1 for w in stat.weeks if w.c > 0)
        total_additions = sum(w.a for w in stat.weeks)
        total_deletions = sum(w.d for w in stat.weeks)
        results.append(
            {
                "login": stat.author.login if stat.author else "ghost",
                "total_commits": stat.total,
                "additions": total_additions,
                "deletions": total_deletions,
                "weeks_active": weeks_active,
            }
        )

    results.sort(key=lambda x: x["total_commits"], reverse=True)
    return results


def get_weekly_digest(owner: str, repo: str) -> dict[str, Any]:
    """
    Return a digest of repository activity for the past 7 days.

    Returns:
        {
            period: {from, to},
            merged_prs: [{number, title, author, merged_at, html_url}],
            opened_issues: [{number, title, author, created_at, html_url}],
            top_contributors: [{login, commits}],
            stats: {merged_pr_count, opened_issue_count, closed_issue_count}
        }
    """
    g = _client()
    r = _repo(g, owner, repo)

    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(days=7)

    # Merged PRs in the last 7 days
    merged_prs = []
    for pr in r.get_pulls(state="closed", sort="updated", direction="desc"):
        if pr.merged_at and pr.merged_at >= since:
            merged_prs.append(
                {
                    "number": pr.number,
                    "title": pr.title,
                    "author": pr.user.login if pr.user else "ghost",
                    "merged_at": pr.merged_at.isoformat(),
                    "html_url": pr.html_url,
                }
            )
        elif pr.updated_at < since:
            break  # list is sorted by updated_at; no point going further

    # Issues opened in the last 7 days
    opened_issues = []
    closed_issues_count = 0
    for issue in r.get_issues(state="all", sort="created", direction="desc", since=since):
        if issue.pull_request:
            continue
        if issue.created_at >= since:
            opened_issues.append(
                {
                    "number": issue.number,
                    "title": issue.title,
                    "author": issue.user.login if issue.user else "ghost",
                    "created_at": issue.created_at.isoformat(),
                    "html_url": issue.html_url,
                }
            )
        if issue.state == "closed" and issue.closed_at and issue.closed_at >= since:
            closed_issues_count += 1

    # Top contributors via commit activity (last week bucket)
    top_contributors: list[dict[str, Any]] = []
    try:
        stats = r.get_stats_contributors()
        if stats:
            weekly: list[tuple[str, int]] = []
            for stat in stats:
                # The last week in the stats list is the most recent
                if stat.weeks:
                    last_week = stat.weeks[-1]
                    if last_week.c > 0:
                        weekly.append(
                            (stat.author.login if stat.author else "ghost", last_week.c)
                        )
            weekly.sort(key=lambda x: x[1], reverse=True)
            top_contributors = [
                {"login": login, "commits": commits} for login, commits in weekly[:5]
            ]
    except GithubException:
        pass  # stats may not be ready on newly created repos

    return {
        "period": {"from": since.isoformat(), "to": now.isoformat()},
        "merged_prs": merged_prs,
        "opened_issues": opened_issues,
        "top_contributors": top_contributors,
        "stats": {
            "merged_pr_count": len(merged_prs),
            "opened_issue_count": len(opened_issues),
            "closed_issue_count": closed_issues_count,
        },
    }
# weekly digest aggregates 7 days of activity
# github api rate limit handled with graceful error message
