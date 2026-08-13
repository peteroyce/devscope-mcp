# devscope-mcp

An MCP server that exposes a read-only view of GitHub to Claude and other
Model Context Protocol clients. Seven tools cover repository metadata, pull request
summaries, issue lists, code search, contributor statistics, and a seven-day activity
digest.

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

## Features

- Seven MCP tools registered over stdio, each with a full JSON input schema so the client
  can validate arguments before a call is made.
- Read-only by construction: every GitHub call goes through a small PyGithub wrapper that
  exposes no write operations.
- Search-query sanitisation — boolean operators and qualifier prefixes (`repo:`,
  `language:`, `org:`, `user:`, `path:`, and others) are stripped from model-supplied
  search text, so a query cannot silently widen its own scope.
- Results are rendered as compact plain text rather than raw JSON, which keeps tool
  output cheap to read for the model.
- Blocking PyGithub calls are dispatched to a thread executor, so the asyncio event loop
  running the MCP session is never stalled by network I/O.
- Errors are returned as tool text, classified into invalid-request, configuration, and
  GitHub-API categories, instead of tearing down the session.
- `get_contributor_stats` distinguishes "no contributors" from "GitHub is still computing
  the statistics" (GitHub answers HTTP 202 while the cache warms).
- Optional `GITHUB_DEFAULT_ORG` so tools that accept an `org` argument can be called
  without one.

## Architecture

```
MCP client (Claude Desktop, or any stdio MCP host)
        │  JSON-RPC over stdio
        ▼
src/server.py
   ├── TOOLS[]            tool names, descriptions, JSON input schemas
   ├── _TOOL_HANDLERS{}   name → handler; argument coercion and validation
   ├── run_in_executor    blocking GitHub work moved off the event loop
   ├── _fmt_*()           dict → human/model-readable text
   └── error mapping      ValueError → invalid request
                          EnvironmentError → configuration error
                          RuntimeError → GitHub API error
        │
        ▼
src/github_client.py      PyGithub wrapper. Returns plain dicts and lists only,
                          so no PyGithub object ever reaches the server layer.
        │
        ▼
GitHub REST API           authenticated with GITHUB_TOKEN
```

Keeping the client layer free of PyGithub types is what makes the server layer testable:
the test suite substitutes plain dictionaries and never touches the network.

## Quickstart

Requires Python 3.11+ and a GitHub personal access token. The token needs `repo`,
`read:org`, and `read:user` scopes for private repositories and organisation listings.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env               # set GITHUB_TOKEN, optionally GITHUB_DEFAULT_ORG
```

| Variable | Required | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | yes | Personal access token; a blank value raises at the first tool call |
| `GITHUB_DEFAULT_ORG` | no | Default organisation for tools that accept `org` |

Register the server with Claude Desktop by adding an entry to `mcpServers` in
`claude_desktop_config.json` (`~/Library/Application Support/Claude/` on macOS,
`%APPDATA%\Claude\` on Windows):

```json
{
  "mcpServers": {
    "devscope-mcp": {
      "command": "devscope-mcp",
      "env": { "GITHUB_TOKEN": "ghp_..." }
    }
  }
}
```

`devscope-mcp` is the console script declared in `pyproject.toml`. If you would rather not
install the package, use `"command": "python"`, `"args": ["-m", "src.server"]`, and set
`"cwd"` to the checkout directory. Restart the client after editing the config.

## Tools

| Tool | Required arguments | Returns |
|---|---|---|
| `list_repos` | — (`org`, `limit` optional; default 20, max 100) | Repos sorted by most recent push: name, visibility, language, stars, open issues, URL |
| `get_repo_info` | `owner`, `repo` | Description, language, stars, forks, open issues, topics, default branch, timestamps |
| `summarize_pr` | `owner`, `repo`, `pr_number` | Title, state, author, base/head branches, changed files with line deltas, conversation comments, commit count |
| `list_issues` | `owner`, `repo` (`state`, `limit` optional) | Issues only — pull requests are filtered out — with labels, assignees, comment counts |
| `search_code` | `query` (`repo` optional) | Up to 20 code results: repository, path, URL |
| `get_contributor_stats` | `owner`, `repo` | Per contributor: total commits, lines added and deleted, active weeks, sorted by commits |
| `get_weekly_digest` | `owner`, `repo` | Last 7 days: merged PRs, opened issues, closed issue count, top 5 contributors |

The `repo` argument to `search_code` is checked against `owner/repo` and then appended as
a trusted `repo:` qualifier — it is the only qualifier the server will add.

Example prompts once the server is connected:

> "Give me the changed files and review comments for PR #47 in myorg/payments"

> "List the open issues in peteroyce/devscope-mcp"

> "Show me the weekly digest for myorg/backend"

## Tech stack

Python 3.11+ · `mcp` (stdio server) · PyGithub · python-dotenv · Hatchling · pytest, pytest-asyncio, pytest-mock

## Testing

```bash
pytest -v
```

`tests/test_github_client.py` and `tests/test_server.py` mock every PyGithub call, so the
suite runs without a token or network access. `asyncio_mode = "auto"` is set in
`pyproject.toml`. GitHub Actions runs the same command on Python 3.11
(`.github/workflows/ci.yml`).

## License

MIT — see [LICENSE](LICENSE).
