# camoufox-mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**MCP server for [Camoufox](https://camoufox.com/)** — an anti-fingerprint Firefox fork. Drives a real, persistent browser session through Model Context Protocol tool calls. Cookies, localStorage, and history persist across opens.

Built for Claude Desktop, Claude Code, Fazm, Cursor, and any other MCP client.

## Why this exists

Camoufox ships as a Python library; you have to write scripts to use it. This MCP wraps it so an agent can drive the browser tool-by-tool from chat:

```
camoufox_open(name="bluesky")
camoufox_navigate(name="bluesky", url="https://bsky.app/login")
camoufox_type(name="bluesky", selector='input[name="username"]', text="me.bsky.social")
camoufox_type(name="bluesky", selector='input[type="password"]', text="...", submit=True)
camoufox_screenshot(name="bluesky")
camoufox_close(name="bluesky")
```

Persistent profiles live under `~/.camoufox-mcp/profiles/<name>/`. Reopen the same `name` later and you're still logged in (assuming the site doesn't fingerprint-bind the session).

## Installation

```bash
git clone https://github.com/m13v/camoufox-mcp.git
cd camoufox-mcp
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .

# Download the patched Firefox binary (one-time, ~300MB)
python -m camoufox fetch
```

## Usage in Claude Desktop / Code / Fazm

Add to your MCP config (e.g. `~/.claude.json` `mcpServers` block, or `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "camoufox": {
      "type": "stdio",
      "command": "/absolute/path/to/camoufox-mcp/.venv/bin/python",
      "args": ["-m", "camoufox_mcp"],
      "env": {}
    }
  }
}
```

Restart the client. The tools `camoufox_open`, `camoufox_navigate`, etc. will appear.

## Tools

| Tool | What it does |
|---|---|
| `camoufox_open` | Launch (or attach to) a named persistent session. Auto-restores cookies/localStorage if a saved JSON exists. |
| `camoufox_close` | Close a session and auto-save credentials (`name="*"` closes all). |
| `camoufox_list_sessions` | List active sessions with URL, title, uptime. |
| `camoufox_list_saved` | List all saved sessions on disk (storage JSONs + profile dirs). |
| `camoufox_navigate` | Go to URL. |
| `camoufox_snapshot` | Compact list of interactable elements (inputs, buttons, links) with selectors. |
| `camoufox_click` | Click by CSS selector or `text=Foo`. |
| `camoufox_type` | Fill an input. Optional `submit=True` presses Enter. |
| `camoufox_screenshot` | PNG to disk. Returns absolute path. |
| `camoufox_evaluate` | Run arbitrary JS in the page, return result. |
| `camoufox_get_cookies` | Dump cookies, optionally filtered by domain. |
| `camoufox_save_storage` | Manually snapshot `storage_state` (cookies + localStorage) to JSON. |
| `camoufox_load_storage` | Manually load a saved storage JSON into the open session. |
| `camoufox_wait` | Sleep N ms (useful between actions). |
| `camoufox_get_url` | Current URL + title. |
| `camoufox_get_text` | Visible body text (truncated). |

## Credential persistence (default ON)

By default the MCP saves your session credentials in **two places** every time you close (or every 30 seconds while open):

1. **Firefox profile dir** (`~/.camoufox-mcp/profiles/<name>/`) — Firefox's native on-disk format
2. **Portable JSON** (`~/.camoufox-mcp/storage/<name>.storage.json`) — `storage_state()` snapshot

When you `camoufox_open` a session whose profile dir is missing or empty, the MCP automatically restores cookies + localStorage from the JSON before navigating. This means:

- Move the JSON to another machine and you're still logged in there
- Delete the entire profile dir; your credentials still come back from the JSON
- No manual `save_storage` / `load_storage` calls needed for normal use

To disable: set env var `CAMOUFOX_MCP_AUTO_PERSIST=0`. To change the autosave interval: `CAMOUFOX_MCP_AUTO_PERSIST_INTERVAL=<seconds>` (set 0 to only save on close).

## Camoufox-specific knobs (on `camoufox_open`)

- `geoip=True` — auto-match timezone/locale/geolocation to proxy IP
- `humanize=True` — human-like cursor movement
- `block_webrtc=True` — block WebRTC at the protocol level (no IP leak)
- `fingerprint_seed=<int>` — deterministic fingerprint across launches (needed for sites that fingerprint-bind sessions)
- `proxy="http://user:pass@host:port"` — route traffic through proxy
- `headless=True` — no window

## Environment variables

- `CAMOUFOX_MCP_PROFILE_ROOT` — where persistent profiles live (default `~/.camoufox-mcp/profiles`)
- `CAMOUFOX_MCP_STORAGE_DIR` — where portable storage JSONs live (default `~/.camoufox-mcp/storage`)
- `CAMOUFOX_MCP_SCREENSHOTS_DIR` — where screenshots land (default `~/.camoufox-mcp/screenshots`)
- `CAMOUFOX_MCP_AUTO_PERSIST` — `0` to disable auto-save/restore of credentials (default `1`)
- `CAMOUFOX_MCP_AUTO_PERSIST_INTERVAL` — seconds between background autosaves (default `30`, `0` = save only on close)

## What persists across `camoufox_close` → `camoufox_open`

| Storage | Persists? |
|---|---|
| Cookies (incl. `sessionid`, `remember-me`) | Yes |
| localStorage | Yes |
| sessionStorage | No (by spec) |
| Hardware/screen/canvas fingerprint | **Rotates each launch** unless you set `fingerprint_seed` |

Verified end-to-end against Bluesky (localStorage JWT) and PostHog (Django session cookies).

## Limitations

- One page per session in v0.1 (multi-tab support TBD).
- No file upload, drag/drop, or multi-modal inputs yet.
- No automatic 2FA / captcha solving — that's on the agent.
- Camoufox `fingerprint_seed` is fully deterministic only after upstream PR #606 lands; until then, hardware values rotate.

## License

MIT. Camoufox itself is MPL-2.0 (Firefox-derived).
