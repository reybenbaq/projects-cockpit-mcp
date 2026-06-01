# Projects Cockpit MCP

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server. It gives an AI host (Claude Code, Claude Desktop) live, structured awareness of a multi-project workspace: what projects exist, which subagents are defined, what plans are in flight, the git state of each repo, and a fast grep over memory files.

Built on the official Python MCP SDK with **FastMCP**, served over **streamable-HTTP**, and packaged to run in **Docker**. It ships zero data. Point `PROJECTS_ROOT` at any directory tree and it scans that.

- **Protocol revision:** `2025-11-25`
- **SDK:** `mcp[cli]` (1.x)
- **Transport:** streamable-HTTP, bound to loopback, bearer-token auth

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `list_projects` | (none) | Each top-level project with `has_agent` / `has_git` / `plan_count` / `is_dirty` flags |
| `list_agents` | `project?` | Subagent definitions (name, description, model) parsed from `.claude/agents/*.md` frontmatter |
| `list_plans` | `status?`, `project?` | Plan documents and their `**Status:**` (DRAFT / APPROVED / IN PROGRESS / IMPLEMENTED / BLOCKED) |
| `project_status` | `project`, `recent=5` | Git branch, dirty state, ahead/behind vs upstream, recent commits |
| `memory_search` | `query`, `scope?` | Case-insensitive line matches across `MEMORY.md`, `feedback_*`, `reference_*`, `project_*`, `user_*`. `scope` narrows to files with that name prefix |

All tools are read-only. There is no write path.

## Architecture

```
src/cockpit/
  server.py       FastMCP instance, tool registration, ASGI app, main()
  config.py       env → frozen Config (load-once, fail-fast)
  scanner.py      project / agent / plan filesystem scans
  gitinfo.py      git via subprocess argument lists (no shell)
  search.py       pure-Python memory grep (no ripgrep dependency)
  security.py     path-containment guard (traversal defense)
  middleware.py   ASGI bearer-token enforcement
  models.py       dataclass output schemas
```

Tools are registered inside `build_server(config)` so they close over an injected config. Nothing reads the environment on import, which keeps the package testable without a populated environment.

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

Then ask: *"Which plans are IN PROGRESS?"*, *"List my agents."*, *"Which repos are dirty?"*, *"Search memory for rate limits."*

## Local development

```bash
pip install -e ".[dev]"
pytest                       # unit + smoke tests
pytest --cov=cockpit         # with coverage
```

## Security model

This server runs **locally** (a container published on host loopback only), so it uses a static bearer token plus `Origin` validation. That is the MCP spec's baseline for local HTTP servers: validate `Origin`, bind loopback, require a token.

A **remote** deployment exposing anything beyond public data needs full OAuth 2.1 (PKCE, audience-bound tokens, Protected Resource Metadata). The official SDK supports this via `TokenVerifier` + `AuthSettings`. Swapping the static-token middleware for that path is the intended upgrade, out of scope for this local sample.

Notes:
- Host and Origin validation (DNS-rebinding defense) is owned by the FastMCP transport layer, configured explicitly in `build_server`. By default it accepts only loopback Host and Origin headers. A request with no `Origin` (a non-browser client like Claude Code) is allowed. A disallowed `Origin` returns 403 and a disallowed `Host` returns 421. Widen `ALLOWED_HOSTS` and `ALLOWED_ORIGINS` only to expose the server beyond loopback, and adopt the OAuth path below when you do.
- The ASGI middleware adds the one control the transport layer lacks: a bearer token, required on every request and compared in constant time (`hmac.compare_digest`).
- The server resolves every caller-supplied project or file name and checks containment before any read (`security.resolve_within`). Discovery skips symlinks so a planted link cannot redirect a scan outside the workspace.
- Git invocations use argument lists, never a shell string.

## License

MIT.
