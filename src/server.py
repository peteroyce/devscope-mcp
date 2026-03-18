"""
server.py — devscope-mcp MCP server entry point.

Exposes GitHub tooling to Claude (or any MCP-compatible client) via the
Model Context Protocol over stdio.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from src import github_client as gh

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

server = Server("devscope-mcp")

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[types.Tool] = [
    types.Tool(
        name="list_repos",
        description=(
            "List repositories for a GitHub organisation or the authenticated user. "
            "Returns repo names, descriptions, primary language, star counts, and "
            "open issue counts sorted by most recently pushed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "org": {
                    "type": "string",
                    "description": (
                        "GitHub organisation login. "
                        "If omitted, lists repos for the authenticated user."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of repos to return (default 20, max 100).",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
    ),
    types.Tool(
        name="get_repo_info",
        description=(
            "Get detailed metadata for a specific GitHub repository: description, "
            "language, stars, forks, open issues, topics, default branch, visibility, "
            "and creation / last-update timestamps."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Repository owner (user or org login).",
                },
                "repo": {
                    "type": "string",
                    "description": "Repository name.",
                },
            },
            "required": ["owner", "repo"],
        },
    ),
    types.Tool(
        name="summarize_pr",
        description=(
            "Return a comprehensive summary of a pull request: title, description, "
            "state, author, base/head branches, list of changed files with line deltas, "
            "all conversation comments, and aggregate addition / deletion counts."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Repository owner.",
                },
                "repo": {
                    "type": "string",
                    "description": "Repository name.",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "Pull request number.",
                },
            },
            "required": ["owner", "repo", "pr_number"],
        },
    ),
    types.Tool(
        name="list_issues",
        description=(
            "List issues for a repository. Supports filtering by state "
            "(open / closed / all). Returns issue number, title, labels, assignees, "
            "author, comment count, and a truncated body."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Repository owner.",
                },
                "repo": {
                    "type": "string",
                    "description": "Repository name.",
                },
                "state": {
                    "type": "string",
                    "enum": ["open", "closed", "all"],
                    "description": "Filter issues by state (default: open).",
                    "default": "open",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of issues to return (default 10).",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["owner", "repo"],
        },
    ),
    types.Tool(
        name="search_code",
        description=(
            "Search code across GitHub using GitHub's code-search syntax. "
            "Optionally restrict the search to a specific repository. "
            "Returns file name, path, repository, and a link to each result."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "GitHub code-search query, e.g. 'authenticate user language:python'."
                    ),
                },
                "repo": {
                    "type": "string",
                    "description": (
                        "Optional 'owner/repo' string to restrict the search to one repo."
                    ),
                },
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="get_contributor_stats",
        description=(
            "Return per-contributor commit statistics for a repository: total commits, "
            "total lines added / deleted, and the number of weeks with at least one commit. "
            "Results are sorted by total commits descending."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Repository owner.",
                },
                "repo": {
                    "type": "string",
                    "description": "Repository name.",
                },
            },
            "required": ["owner", "repo"],
        },
    ),
    types.Tool(
        name="get_weekly_digest",
        description=(
            "Generate a 7-day activity digest for a repository. "
            "Returns: merged PRs, newly opened issues, closed issue count, and the "
            "top 5 contributors by commit count for the period. "
            "Great for weekly stand-ups or team summaries."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Repository owner.",
                },
                "repo": {
                    "type": "string",
                    "description": "Repository name.",
                },
            },
            "required": ["owner", "repo"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_list_repos(repos: list[dict[str, Any]]) -> str:
    if not repos:
        return "No repositories found."
    lines = []
    for r in repos:
        privacy = "private" if r["is_private"] else "public"
        pushed = r["pushed_at"] or "n/a"
        lines.append(
            f"• {r['full_name']} [{privacy}] — {r['language']} | "
            f"★ {r['stars']} | {r['open_issues']} open issues | last pushed: {pushed}\n"
            f"  {r['description']}\n  {r['html_url']}"
        )
    return "\n\n".join(lines)


def _fmt_repo_info(info: dict[str, Any]) -> str:
    topics = ", ".join(info["topics"]) or "none"
    privacy = "Private" if info["is_private"] else "Public"
    return (
        f"Repository: {info['full_name']}  [{privacy}]\n"
        f"Description: {info['description'] or 'No description'}\n"
        f"Language:    {info['language']}\n"
        f"Stars:       {info['stars']}  |  Forks: {info['forks']}\n"
        f"Open issues: {info['open_issues']}\n"
        f"Topics:      {topics}\n"
        f"Default branch: {info['default_branch']}\n"
        f"Created:  {info['created_at']}\n"
        f"Updated:  {info['updated_at']}\n"
        f"URL: {info['html_url']}"
    )


def _fmt_pr_summary(pr: dict[str, Any]) -> str:
    files_section = ""
    if pr["files_changed"]:
        file_lines = [
            f"  {f['filename']}  (+{f['additions']} / -{f['deletions']}) [{f['status']}]"
            for f in pr["files_changed"]
        ]
        files_section = "Files changed:\n" + "\n".join(file_lines)

    comments_section = ""
    if pr["comments"]:
        comment_lines = [
            f"  [{c['created_at']}] {c['author']}: {c['body'][:200]}"
            for c in pr["comments"]
        ]
        comments_section = "Comments:\n" + "\n".join(comment_lines)

    merged = pr["merged_at"] or "not merged"
    return (
        f"PR #{pr['number']}: {pr['title']}\n"
        f"State:  {pr['state']}  |  Author: {pr['author']}\n"
        f"Branch: {pr['head_branch']} → {pr['base_branch']}\n"
        f"Opened: {pr['created_at']}  |  Merged: {merged}\n"
        f"Changes: +{pr['additions']} / -{pr['deletions']}  "
        f"across {len(pr['files_changed'])} file(s)  |  {pr['commits_count']} commit(s)\n"
        f"URL: {pr['html_url']}\n\n"
        f"Description:\n{pr['body'] or '(no description)'}\n\n"
        f"{files_section}\n\n"
        f"{comments_section}"
    ).strip()


def _fmt_issues(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return "No issues found."
    lines = []
    for i in issues:
        labels = ", ".join(i["labels"]) or "no labels"
        assignees = ", ".join(i["assignees"]) or "unassigned"
        lines.append(
            f"#{i['number']}  [{i['state']}]  {i['title']}\n"
            f"  Author: {i['author']}  |  Assignees: {assignees}\n"
            f"  Labels: {labels}  |  Comments: {i['comments']}\n"
            f"  Opened: {i['created_at']}\n"
            f"  {i['html_url']}"
        )
    return "\n\n".join(lines)


def _fmt_search_code(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No code results found."
    lines = []
    for r in results:
        lines.append(
            f"• {r['repository']} — {r['path']}\n  {r['html_url']}"
        )
    return "\n\n".join(lines)


def _fmt_contributor_stats(stats: list[dict[str, Any]] | dict[str, Any]) -> str:
    # Handle the "stats not yet available" sentinel returned when GitHub
    # returns HTTP 202 (stats still being computed).
    if isinstance(stats, dict):
        reason = stats.get("reason", "Stats are unavailable.")
        return f"Contributor stats are not yet available: {reason}"
    if not stats:
        return "No contributor stats available (the repository may be empty or stats are still being computed by GitHub)."
    lines = ["Contributor Statistics (sorted by total commits):\n"]
    for rank, s in enumerate(stats, start=1):
        lines.append(
            f"{rank:>2}. {s['login']:<25} {s['total_commits']:>6} commits | "
            f"+{s['additions']:>7} / -{s['deletions']:>7} lines | "
            f"{s['weeks_active']} active weeks"
        )
    return "\n".join(lines)


def _fmt_weekly_digest(digest: dict[str, Any]) -> str:
    period = digest["period"]
    s = digest["stats"]

    # Merged PRs — note: iterate over digest["merged_prs"], not period
    if digest["merged_prs"]:
        pr_lines = [
            f"  • #{pr['number']}  {pr['title']}  by {pr['author']}  ({pr['merged_at']})\n    {pr['html_url']}"
            for pr in digest["merged_prs"]
        ]
        prs_section = "Merged PRs:\n" + "\n".join(pr_lines)
    else:
        prs_section = "Merged PRs: none"

    # Opened issues
    if digest["opened_issues"]:
        issue_lines = [
            f"  • #{i['number']}  {i['title']}  by {i['author']}  ({i['created_at']})\n    {i['html_url']}"
            for i in digest["opened_issues"]
        ]
        issues_section = "Opened Issues:\n" + "\n".join(issue_lines)
    else:
        issues_section = "Opened Issues: none"

    # Top contributors
    if digest["top_contributors"]:
        contrib_lines = [
            f"  {c['login']}: {c['commits']} commit(s)" for c in digest["top_contributors"]
        ]
        contrib_section = "Top Contributors (this week):\n" + "\n".join(contrib_lines)
    else:
        contrib_section = "Top Contributors: no commit activity this week"

    return (
        f"Weekly Digest — {period['from'][:10]} to {period['to'][:10]}\n"
        f"{'=' * 55}\n"
        f"Summary: {s['merged_pr_count']} PR(s) merged | "
        f"{s['opened_issue_count']} issue(s) opened | "
        f"{s['closed_issue_count']} issue(s) closed\n\n"
        f"{prs_section}\n\n"
        f"{issues_section}\n\n"
        f"{contrib_section}"
    )


# ---------------------------------------------------------------------------
# Tool call dispatcher (dict-based, with input validation)
# ---------------------------------------------------------------------------

def _safe_int(value: Any, field_name: str) -> int:
    """Convert *value* to int, returning a descriptive error string on failure.

    Raises:
        ValueError: with a human-readable message if conversion fails.
    """
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid value for '{field_name}': expected an integer, got {value!r}"
        ) from exc


def _handle_list_repos(args: dict[str, Any]) -> str:
    limit = _safe_int(args.get("limit", 20), "limit")
    data = gh.list_repos(org=args.get("org"), limit=limit)
    return _fmt_list_repos(data)


def _handle_get_repo_info(args: dict[str, Any]) -> str:
    data = gh.get_repo(owner=args["owner"], repo=args["repo"])
    return _fmt_repo_info(data)


def _handle_summarize_pr(args: dict[str, Any]) -> str:
    pr_number = _safe_int(args["pr_number"], "pr_number")
    data = gh.get_pr_summary(
        owner=args["owner"],
        repo=args["repo"],
        pr_number=pr_number,
    )
    return _fmt_pr_summary(data)


def _handle_list_issues(args: dict[str, Any]) -> str:
    limit = _safe_int(args.get("limit", 10), "limit")
    data = gh.get_issues(
        owner=args["owner"],
        repo=args["repo"],
        state=args.get("state", "open"),
        limit=limit,
    )
    return _fmt_issues(data)


def _handle_search_code(args: dict[str, Any]) -> str:
    data = gh.search_code(query=args["query"], repo=args.get("repo"))
    return _fmt_search_code(data)


def _handle_get_contributor_stats(args: dict[str, Any]) -> str:
    data = gh.get_contributor_stats(owner=args["owner"], repo=args["repo"])
    return _fmt_contributor_stats(data)


def _handle_get_weekly_digest(args: dict[str, Any]) -> str:
    data = gh.get_weekly_digest(owner=args["owner"], repo=args["repo"])
    return _fmt_weekly_digest(data)


# Registry mapping tool name → handler function
_TOOL_HANDLERS: dict[str, Any] = {
    "list_repos": _handle_list_repos,
    "get_repo_info": _handle_get_repo_info,
    "summarize_pr": _handle_summarize_pr,
    "list_issues": _handle_list_issues,
    "search_code": _handle_search_code,
    "get_contributor_stats": _handle_get_contributor_stats,
    "get_weekly_digest": _handle_get_weekly_digest,
}


def _dispatch(name: str, args: dict[str, Any]) -> str:
    """Synchronous dispatcher — called inside an executor."""
    logging.info(f"Tool called: {name}")
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        known = ", ".join(sorted(_TOOL_HANDLERS))
        raise ValueError(f"Unknown tool: '{name}'. Known tools: {known}")
    return handler(args)


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent]:
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, _dispatch, name, arguments
        )
        return [types.TextContent(type="text", text=result)]
    except ValueError as exc:
        # Covers unknown tool names and bad integer arguments
        error_text = f"Invalid request: {exc}"
    except EnvironmentError as exc:
        error_text = f"Configuration error: {exc}"
    except RuntimeError as exc:
        error_text = f"GitHub API error: {exc}"
    except Exception as exc:
        logging.exception("Unexpected error in tool dispatch")
        error_text = f"Error: {type(exc).__name__}: {exc}"

    return [types.TextContent(type="text", text=error_text)]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run() -> None:
    """Synchronous wrapper used as the console_scripts entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
