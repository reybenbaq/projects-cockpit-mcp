# Projects Cockpit MCP

[![CI](https://github.com/reybenbaq/projects-cockpit-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/reybenbaq/projects-cockpit-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![MCP protocol 2025-11-25](https://img.shields.io/badge/MCP-2025--11--25-green.svg)](https://modelcontextprotocol.io)

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server. It gives an AI host (Claude Code, Claude Desktop) live, structured awareness of a multi-project workspace: what projects exist, which subagents are defined, what plans are in flight, the git state of each repo, and a fast grep over memory files.

Built on the official Python MCP SDK with **FastMCP**, served over **streamable-HTTP**, and packaged to run in **Docker**. It ships zero data. Point `PROJECTS_ROOT` at any directory tree and it scans that.

- **Protocol revision:** `2025-11-25`
- **SDK:** `mcp[cli] >=1.25,<2.0` (official Python MCP SDK)
- **Transport:** streamable-HTTP, bound to loopback, bearer-token auth

> This is a portfolio sample. It exists to show that I can design, harden, and ship a real MCP server end to end: official SDK, streamable-HTTP transport, hardened container, bearer auth, supply-chain CI, and a live-client integration test. It is also a tool I actually use, published as a runnable reference so you can clone it, bring it up, and connect Claude yourself. It is not a hosted service and not a maintained dependency.

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `list_projects` | (none) | Each discovered project with `name` / `path` / `has_agent` / `has_git` / `plan_count` / `is_dirty` flags |
| `list_agents` | `project?` | Subagent definitions (name, description, model) parsed from `.claude/agents/*.md` frontmatter |
| `list_plans` | `status?`, `project?` | Plan documents and their `**Status:**` (DRAFT / APPROVED / IN PROGRESS / IMPLEMENTED / BLOCKED) |
| `project_status` | `project`, `recent=5` | Git branch, dirty state, ahead/behind vs upstream, recent commits |
| `memory_search` | `query`, `scope?` | Case-insensitive line matches across `MEMORY.md`, `feedback_*`, `reference_*`, `project_*`, `user_*`. `scope` narrows to files with that name prefix |

All tools are read-only. There is no write path.

### Relative-path tool inputs

The `project` argument on `project_status`, `list_agents`, and `list_plans` takes the project's **relative path from `PROJECTS_ROOT`**:

- Nested projects use their full relative path: `"GCP/Reviews Bot"`, `"Client/Acme Corp"`.
- Top-level (L1) projects use their bare directory name: `"Wordpress"`, `"Standards Agent"`.
- Bare leaf names are **not** resolved for nested projects — passing `"Reviews Bot"` when the project lives at `GCP/Reviews Bot` will not find it. Always pass the full relative path for nested projects.

```
project_status(project="GCP/Reviews Bot")    # nested — full relative path required
project_status(project="Wordpress")          # L1 — bare name is the full relative path
list_agents(project="GCP/Reviews Bot")
list_plans(project="Client/Acme Corp")
```

The path must be relative (no leading `/`) and must not escape `PROJECTS_ROOT` via `..`. Absolute paths and traversal attempts are rejected.

## Supported workspace layouts

The cockpit supports both **flat** and **nested** directory layouts, and handles mixed/irregular trees.

**Flat layout** (common for simple setups — all projects at the top level):
```
PROJECTS_ROOT/
  My Bot/
  My Website/
  Shared Lib/
```

**Nested layout** (real multi-category workspaces with sub-categories):
```
PROJECTS_ROOT/
  GCP/
    Reviews Bot/          <-- discovered as "GCP/Reviews Bot"
    Invoice Bot/          <-- discovered as "GCP/Invoice Bot"
  Client/
    Acme Corp/            <-- discovered as "Client/Acme Corp"
  Standards Agent/        <-- discovered as "Standards Agent"
  portfolio-samples/
    projects-cockpit-mcp/ <-- discovered at depth 2
```

Discovery is marker-based and recursive up to `MAX_DISCOVERY_DEPTH` (default 3). A directory qualifies as a project when it carries at least one marker:

- `.claude/agents/` with at least one `*.md` file
- A valid `.git` repository (`.git/HEAD` is a regular file)
- A `plans and validations/` or `implemented plans/` or `Plans/` subdirectory

Both a parent directory and a nested child qualify simultaneously — no suppression. If `GCP/` itself carries an agent definition, it surfaces alongside `GCP/Reviews Bot`.

## Architecture

```
src/cockpit/
  server.py       FastMCP instance, tool registration, ASGI app, main()
  config.py       env → frozen Config (load-once, fail-fast)
  scanner.py      project / agent / plan filesystem scans (marker-based, recursive)
  gitinfo.py      git via subprocess argument lists (no shell)
  search.py       pure-Python memory grep (no ripgrep dependency)
  security.py     path-containment guard (traversal defense)
  middleware.py   ASGI bearer-token enforcement
  models.py       dataclass output schemas
```

Tools are registered inside `build_server(config)` so they close over an injected config. Nothing reads the environment on import, which keeps the package testable without a populated environment.

### Design notes

- Discovery uses a single `_iter_project_dirs` function shared by `list_projects`, `list_agents`, and `list_plans`. No duplication of traversal logic.
- Tools that read the filesystem or run git are `async` and offload the blocking work with `anyio.to_thread.run_sync`. FastMCP runs sync tools directly on the event loop, so blocking there would stall every concurrent request.
- Each tool returns a dataclass. FastMCP derives the `outputSchema` from it and emits both `structuredContent` and a text mirror.
- The bearer middleware is raw ASGI, not Starlette's `BaseHTTPMiddleware`. That base class breaks streamed responses and swallows lifespan events, which the streamable-HTTP transport depends on.
- `project_status` validates that the target directory is a real git repo (`.git/HEAD` is a file) before invoking any git subprocess. An empty or corrupted `.git` directory returns a `ToolError` rather than an unhandled subprocess failure.
- `memory_search` uses `os.walk` with in-place directory pruning to skip excluded subtrees (`.venv/`, `node_modules/`, etc.) rather than an unbounded `rglob`. On NTFS-over-WSL2, this avoids traversing thousands of irrelevant files.

## Configuration

All configuration is loaded from environment variables at startup. Required variables are validated together and all problems are reported in a single error.

| Variable | Default | Description |
|---|---|---|
| `PROJECTS_ROOT` | *required* | Directory scanned for projects, agents, and plans |
| `COCKPIT_TOKEN` | *required* | Bearer token required on every HTTP request |
| `MEMORY_ROOT` | `PROJECTS_ROOT` | Directory searched by `memory_search`. Set this explicitly when your memory files live in a different tree from your project code. When unset, the cockpit searches `PROJECTS_ROOT` — correct for workspace roots that contain both, but a `memory_search` pointed at a large code tree will be slower. |
| `MAX_DISCOVERY_DEPTH` | `3` | How many directory levels below `PROJECTS_ROOT` to recurse. Covers L1/L2/L3 layouts; raising above 3 risks descending into vendored subdirectories. |
| `REQUIRE_MARKERS` | `true` | When `true`, only directories with at least one project marker (agent def, git repo, plans dir) are returned. Set to `false` to surface all non-excluded directories regardless of markers — useful for flat demo or CI environments with minimal fixture trees. |
| `PORT` | `8848` | Bind port (must be ≥ 1024 for non-root container operation) |
| `HOST` | `127.0.0.1` | Bind address |
| `ALLOWED_ORIGINS` | loopback origins | Comma-separated browser `Origin` values the transport accepts |
| `ALLOWED_HOSTS` | loopback hosts | Comma-separated `Host` header values the transport accepts |
| `MAX_SEARCH_HITS` | `50` | Hard ceiling on `memory_search` results |
| `LOG_LEVEL` | `INFO` | Root log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |

## Run in Docker

This repo holds the source. You run the container yourself. Nothing is hosted. Clone it, point it at your own workspace, and bring it up:

```bash
cp .env.example .env
# edit .env: set PROJECTS_ROOT_HOST to your workspace and COCKPIT_TOKEN to a random value
docker compose up --build
```

The server listens on `http://127.0.0.1:8848/mcp`. Compose mounts the workspace read-only. The container runs as a non-root user with `cap_drop: ALL`, a `read_only` root filesystem, and `no-new-privileges`.

Health probe (no token required): `GET http://127.0.0.1:8848/healthz`.

## Connect from Claude Code

Add to your project `.mcp.json` (or `~/.claude.json` for user scope):

```jsonc
{
  "mcpServers": {
    "projects-cockpit": {
      "type": "http",
      "url": "http://127.0.0.1:8848/mcp",
      "headers": { "Authorization": "Bearer <COCKPIT_TOKEN>" }
    }
  }
}
```

Then ask: *"Which plans are IN PROGRESS?"*, *"List my agents."*, *"Which repos are dirty?"*, *"Search memory for rate limits."*, *"What agents are in the GCP category?"*

## Local development

```bash
pip install -e ".[dev]"
pytest                       # unit + smoke tests
pytest --cov=cockpit         # with coverage
```

## Tests and supply-chain CI

The suite is 92 tests: the scanner (flat and nested discovery, marker gate, depth limit, exclusions, capital-P plans dir, parent+child surfacing, path-qualified names), search (excluded-dir pruning), git parsing, config boundaries (including `MAX_DISCOVERY_DEPTH` and `REQUIRE_MARKERS`), the transport-security 421 and 403 paths, the bearer middleware, path-traversal plus symlink containment (including multi-segment inputs), and invalid-git graceful handling. CI enforces a branch-coverage gate. One test pins the protocol revision by asserting the SDK's `LATEST_PROTOCOL_VERSION` equals the value the README advertises.

Every GitHub Actions step is pinned to a full commit SHA with a trailing version comment. The image-scan job builds the container and fails on any HIGH or CRITICAL vulnerability (Trivy). Dependabot keeps the SHA pins and the dependencies current.

The server is also validated end to end against a live MCP client. A real `ClientSession` over streamable-HTTP completes the initialize handshake (protocol `2025-11-25`) and calls all five tools. Every call returns correct structured data, with the container running non-root on a read-only root filesystem.

## Security model

This server runs **locally** (a container published on host loopback only), so it uses a static bearer token plus `Origin` validation. That is the MCP spec's baseline for local HTTP servers: validate `Origin`, bind loopback, require a token.

A **remote** deployment exposing anything beyond public data needs full OAuth 2.1 (PKCE, audience-bound tokens, Protected Resource Metadata). The official SDK supports this via `TokenVerifier` + `AuthSettings`. Swapping the static-token middleware for that path is the intended upgrade, out of scope for this local sample.

Notes:
- The FastMCP transport layer owns Host and Origin validation (the DNS-rebinding defense), configured explicitly in `build_server`. By default it accepts only loopback Host and Origin headers. A request with no `Origin` (a non-browser client like Claude Code) is allowed. A disallowed `Origin` returns 403 and a disallowed `Host` returns 421. Widen `ALLOWED_HOSTS` and `ALLOWED_ORIGINS` only to expose the server beyond loopback, and adopt the OAuth path below when you do.
- The ASGI middleware adds the one control the transport layer lacks: a bearer token, required on every request and compared in constant time (`hmac.compare_digest`).
- The server resolves every caller-supplied project or file name and checks containment before any read (`security.resolve_within`). Discovery skips symlinks so a planted link cannot redirect a scan outside the workspace. Multi-segment relative paths (e.g. `"GCP/Reviews Bot"`) are supported; absolute paths and `..` traversals are rejected.
- Git invocations use argument lists, never a shell string.

## License

MIT.
