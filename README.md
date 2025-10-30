# devscope-mcp

An MCP server that gives Claude live access to your GitHub workspace — PR reviews, issue triaging, repo search, and weekly digest reports through natural language.

Built on the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), devscope-mcp plugs directly into Claude Desktop (or any MCP-compatible client) and lets you work with GitHub without ever leaving the conversation.

---

## Features

- **PR Summaries** — full diff metadata, comments, and review stats for any pull request
- **Issue Triage** — list and filter open/closed issues across any repository
- **Repo Explorer** — browse repos for a user or org, with stats at a glance
- **Code Search** — GitHub code-search with optional repo scoping
- **Contributor Stats** — commit volume, lines changed, and active weeks per contributor
- **Weekly Digest** — merged PRs, opened issues, and top contributors for the past 7 days

---

## Tech Stack

| Layer | Technology |
|---|---|
| Protocol | [Model Context Protocol](https://modelcontextprotocol.io/) (`mcp >= 1.0`) |
| GitHub API | [PyGithub](https://pygithub.readthedocs.io/) `>= 2.3` |
| HTTP client | [httpx](https://www.python-httpx.org/) `>= 0.27` |
| Config | [python-dotenv](https://pypi.org/project/python-dotenv/) `>= 1.0` |
| Runtime | Python 3.11+ |
| Tests | pytest 8, pytest-asyncio, pytest-mock |
| Build | [Hatchling](https://hatch.pypa.io/) via `pyproject.toml` |

---

## Setup

### 1. Prerequisites

- Python 3.11 or later
- A [GitHub Personal Access Token](https://github.com/settings/tokens) with the following scopes:
  - `repo` (full repository access)
  - `read:org`
  - `read:user`

### 2. Clone and install

```bash
git clone https://github.com/your-user/devscope-mcp.git
cd devscope-mcp
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. Configure environment

```bash
cp .env.example .env
# edit .env and set GITHUB_TOKEN (and optionally GITHUB_DEFAULT_ORG)
```

### 4. Add to Claude Desktop

Open your Claude Desktop config file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add the devscope-mcp entry to `mcpServers`:

```json
{
  "mcpServers": {
    "devscope-mcp": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/absolute/path/to/devscope-mcp",
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here",
        "GITHUB_DEFAULT_ORG": "your-org-name"
      }
    }
  }
}
```

If you installed with `pip install -e .`, you can use the console script instead:

```json
{
  "mcpServers": {
    "devscope-mcp": {
      "command": "devscope-mcp",
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here",
        "GITHUB_DEFAULT_ORG": "your-org-name"
      }
    }
  }
}
```

Restart Claude Desktop. You should see the devscope-mcp tools available in the tools menu.

---

## Available Tools

| Tool | Description |
|---|---|
| `list_repos` | List repositories for a GitHub org or authenticated user, sorted by last push |
| `get_repo_info` | Detailed metadata for a single repo (language, stars, forks, topics, etc.) |
| `summarize_pr` | Full summary of a pull request including changed files, comments, and deltas |
| `list_issues` | List issues with state filter (open / closed / all) and configurable limit |
| `search_code` | GitHub code search with optional repo scope |
| `get_contributor_stats` | Per-contributor commit count, lines added/deleted, and active weeks |
| `get_weekly_digest` | 7-day activity digest: merged PRs, opened issues, top contributors |

---

## Example Prompts

> "Summarise the last 5 PRs in my repo"

> "List all open issues in peteroyce/devscope-mcp labelled 'bug'"

> "Show me the weekly digest for the myorg/backend repository"

> "Who are the top contributors to myorg/frontend this week?"

> "Search for usages of `authenticate_user` across the myorg/api repo"

> "Give me the full diff and comments for PR #47 in myorg/payments"

> "List all repos in the myorg organisation sorted by most recently active"

---

## Running Tests

```bash
pytest -v
```

Tests mock all PyGithub calls so no real GitHub token is required.

---

## Project Structure

```
devscope-mcp/
├── src/
│   ├── __init__.py
│   ├── github_client.py   # PyGithub wrapper — all GitHub logic lives here
│   └── server.py          # MCP server — tool definitions, dispatch, formatting
├── tests/
│   └── test_github_client.py
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## License

MIT
