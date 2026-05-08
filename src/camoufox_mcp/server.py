"""
Camoufox MCP server.

Exposes a Camoufox (anti-fingerprint Firefox) browser as MCP tools.
Each `camoufox_open` call creates a long-lived session keyed by name; subsequent
tool calls operate against that session until `camoufox_close` is called.

Stdio transport. Run with: python -m camoufox_mcp
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from camoufox.async_api import AsyncCamoufox
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PROFILE_ROOT = Path(
    os.environ.get("CAMOUFOX_MCP_PROFILE_ROOT", str(Path.home() / ".camoufox-mcp" / "profiles"))
)
DEFAULT_SHOTS_DIR = Path(
    os.environ.get("CAMOUFOX_MCP_SCREENSHOTS_DIR", str(Path.home() / ".camoufox-mcp" / "screenshots"))
)
DEFAULT_PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
DEFAULT_SHOTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Session:
    name: str
    profile_dir: Path
    cm: Any  # AsyncCamoufox context manager (NOT yet exited)
    browser: Any  # Camoufox browser context returned by __aenter__
    page: Any  # active page
    headless: bool
    created_at: float = field(default_factory=time.time)


SESSIONS: dict[str, Session] = {}

mcp = FastMCP("camoufox")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require(name: str) -> Session:
    sess = SESSIONS.get(name)
    if sess is None:
        raise ValueError(f"No active session named {name!r}. Open one with camoufox_open(name={name!r}) first.")
    return sess


def _safe_name(name: str) -> str:
    """Sanitize profile name to a directory-safe slug."""
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    return "".join(c if c in keep else "_" for c in name)[:80] or "default"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def camoufox_open(
    name: str = "default",
    headless: bool = False,
    geoip: bool = True,
    humanize: bool = True,
    block_webrtc: bool = True,
    url: Optional[str] = None,
    fingerprint_seed: Optional[int] = None,
    proxy: Optional[str] = None,
) -> str:
    """Open (or reopen) a Camoufox browser session with a persistent profile.

    The session is keyed by `name`; reusing the same name reuses cookies,
    localStorage, and history from the last run. A second call with the same
    name while a session is still open returns the existing session.

    Args:
        name: Session name. Reuses persistent profile dir on disk.
        headless: Run without a visible window. Default False (visible).
        geoip: Auto-match timezone/locale/geolocation to proxy IP.
        humanize: Add human-like cursor movement.
        block_webrtc: Block WebRTC at the protocol level (prevents IP leak).
        url: If provided, navigate to this URL after opening.
        fingerprint_seed: Integer seed for deterministic fingerprint across launches.
            Required for sites that fingerprint-bind sessions (Google, banks).
        proxy: Optional proxy URL, e.g. 'http://user:pass@host:port'.

    Returns:
        JSON status with session name, profile dir, and current URL (if any).
    """
    if name in SESSIONS:
        sess = SESSIONS[name]
        info = {
            "status": "already_open",
            "name": name,
            "profile_dir": str(sess.profile_dir),
            "url": sess.page.url,
        }
        if url:
            await sess.page.goto(url, wait_until="domcontentloaded")
            info["url"] = sess.page.url
        return json.dumps(info, indent=2)

    profile_dir = DEFAULT_PROFILE_ROOT / _safe_name(name)
    profile_dir.mkdir(parents=True, exist_ok=True)

    kwargs: dict[str, Any] = {
        "persistent_context": True,
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "geoip": geoip,
        "humanize": humanize,
        "block_webrtc": block_webrtc,
    }
    if fingerprint_seed is not None:
        # Camoufox 0.4.x supports `fingerprint_seed` once PR #606 lands; safe to pass.
        kwargs["fingerprint_seed"] = fingerprint_seed
    if proxy:
        kwargs["proxy"] = {"server": proxy}

    cm = AsyncCamoufox(**kwargs)
    browser = await cm.__aenter__()
    page = await browser.new_page()

    sess = Session(name=name, profile_dir=profile_dir, cm=cm, browser=browser, page=page, headless=headless)
    SESSIONS[name] = sess

    if url:
        await page.goto(url, wait_until="domcontentloaded")

    return json.dumps({
        "status": "opened",
        "name": name,
        "profile_dir": str(profile_dir),
        "headless": headless,
        "url": page.url,
    }, indent=2)


@mcp.tool()
async def camoufox_close(name: str = "default") -> str:
    """Close a Camoufox session and release the browser process.

    Args:
        name: Session name. Use `*` to close all open sessions.
    """
    if name == "*":
        closed = []
        for n in list(SESSIONS.keys()):
            await _close_one(n)
            closed.append(n)
        return json.dumps({"status": "closed_all", "sessions": closed}, indent=2)
    await _close_one(name)
    return json.dumps({"status": "closed", "name": name}, indent=2)


async def _close_one(name: str) -> None:
    sess = SESSIONS.pop(name, None)
    if sess is None:
        return
    try:
        await sess.cm.__aexit__(None, None, None)
    except Exception:
        pass


@mcp.tool()
async def camoufox_list_sessions() -> str:
    """List active Camoufox sessions: name, profile dir, current URL, headless flag."""
    out = []
    for name, sess in SESSIONS.items():
        try:
            url = sess.page.url
            title = await sess.page.title()
        except Exception:
            url = "<unknown>"
            title = "<unknown>"
        out.append({
            "name": name,
            "profile_dir": str(sess.profile_dir),
            "url": url,
            "title": title,
            "headless": sess.headless,
            "uptime_sec": int(time.time() - sess.created_at),
        })
    return json.dumps({"sessions": out}, indent=2)


@mcp.tool()
async def camoufox_navigate(name: str, url: str, wait_until: str = "domcontentloaded", timeout_ms: int = 30000) -> str:
    """Navigate to a URL in the named session.

    Args:
        name: Session name.
        url: Target URL.
        wait_until: One of 'load', 'domcontentloaded', 'networkidle', 'commit'.
        timeout_ms: Navigation timeout in milliseconds.
    """
    sess = _require(name)
    await sess.page.goto(url, wait_until=wait_until, timeout=timeout_ms)
    return json.dumps({
        "status": "navigated",
        "url": sess.page.url,
        "title": await sess.page.title(),
    }, indent=2)


@mcp.tool()
async def camoufox_snapshot(name: str, max_elements: int = 80) -> str:
    """Return a compact snapshot of interactable elements on the current page.

    Each element gets a stable selector you can pass to `camoufox_click` or
    `camoufox_type`. Includes inputs, buttons, links, and main text.

    Args:
        name: Session name.
        max_elements: Cap on number of elements returned (default 80).
    """
    sess = _require(name)
    page = sess.page

    js = """
    () => {
      const result = { url: location.href, title: document.title, elements: [] };
      const sel = (el) => {
        if (el.id) return `#${CSS.escape(el.id)}`;
        if (el.name) return `${el.tagName.toLowerCase()}[name="${el.name}"]`;
        if (el.getAttribute('data-testid')) return `[data-testid="${el.getAttribute('data-testid')}"]`;
        // fallback: nth-of-type within tag
        const parent = el.parentElement;
        if (!parent) return el.tagName.toLowerCase();
        const same = Array.from(parent.children).filter(c => c.tagName === el.tagName);
        const idx = same.indexOf(el) + 1;
        return `${el.tagName.toLowerCase()}:nth-of-type(${idx})`;
      };
      const targets = document.querySelectorAll('input, textarea, button, a[href], select, [role="button"], [role="link"]');
      let i = 0;
      for (const el of targets) {
        if (i >= __MAX__) break;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const tag = el.tagName.toLowerCase();
        const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 80);
        const type = el.getAttribute('type') || '';
        result.elements.push({
          ref: sel(el),
          tag,
          type,
          text,
          href: el.href || undefined,
        });
        i++;
      }
      return result;
    }
    """.replace("__MAX__", str(max_elements))

    snap = await page.evaluate(js)
    return json.dumps(snap, indent=2)


@mcp.tool()
async def camoufox_click(name: str, selector: str, timeout_ms: int = 8000) -> str:
    """Click an element by CSS selector or text (use `text=Foo` syntax).

    Args:
        name: Session name.
        selector: CSS selector OR Playwright text selector (e.g. 'text=Login').
        timeout_ms: Wait for element to be visible, in milliseconds.
    """
    sess = _require(name)
    loc = sess.page.locator(selector).first
    await loc.wait_for(state="visible", timeout=timeout_ms)
    await loc.click()
    return json.dumps({"status": "clicked", "selector": selector, "url": sess.page.url}, indent=2)


@mcp.tool()
async def camoufox_type(
    name: str,
    selector: str,
    text: str,
    submit: bool = False,
    clear_first: bool = True,
    timeout_ms: int = 8000,
) -> str:
    """Type text into an input/textarea.

    Args:
        name: Session name.
        selector: CSS selector for the field.
        text: Text to type. The MCP layer strips trailing newlines.
        submit: If True, press Enter after typing.
        clear_first: If True, clear the field before typing.
        timeout_ms: Wait for element to be visible.
    """
    sess = _require(name)
    text = text.rstrip("\n")
    loc = sess.page.locator(selector).first
    await loc.wait_for(state="visible", timeout=timeout_ms)
    if clear_first:
        await loc.fill("")
    await loc.fill(text)
    if submit:
        await loc.press("Enter")
    return json.dumps({"status": "typed", "selector": selector, "submitted": submit}, indent=2)


@mcp.tool()
async def camoufox_screenshot(name: str, path: Optional[str] = None, full_page: bool = False) -> str:
    """Take a screenshot of the current page.

    Args:
        name: Session name.
        path: Output file path. If omitted, saves to ~/.camoufox-mcp/screenshots/<name>-<ts>.png
        full_page: Capture full page (not just viewport).

    Returns:
        JSON with the absolute path written.
    """
    sess = _require(name)
    if not path:
        ts = int(time.time())
        path = str(DEFAULT_SHOTS_DIR / f"{_safe_name(name)}-{ts}.png")
    await sess.page.screenshot(path=path, full_page=full_page)
    return json.dumps({"status": "saved", "path": path}, indent=2)


@mcp.tool()
async def camoufox_evaluate(name: str, js_code: str) -> str:
    """Run arbitrary JavaScript in the page context and return the result.

    Args:
        name: Session name.
        js_code: A JavaScript expression OR a function body. Will be wrapped as
                 `() => { return (<code>); }` if it doesn't already start with 'function' or '('.
    """
    sess = _require(name)
    code = js_code.strip()
    if not (code.startswith("(") or code.startswith("function") or code.startswith("async")):
        code = f"() => {{ return ({code}); }}"
    result = await sess.page.evaluate(code)
    return json.dumps({"result": result}, indent=2, default=str)


@mcp.tool()
async def camoufox_get_cookies(name: str, domain: Optional[str] = None) -> str:
    """Get cookies from the current browsing context.

    Args:
        name: Session name.
        domain: If provided, only return cookies whose domain contains this string.
    """
    sess = _require(name)
    cookies = await sess.page.context.cookies()
    if domain:
        cookies = [c for c in cookies if domain in c.get("domain", "")]
    return json.dumps({"count": len(cookies), "cookies": cookies}, indent=2, default=str)


@mcp.tool()
async def camoufox_save_storage(name: str, path: str) -> str:
    """Save the full storage_state (cookies + localStorage) to a JSON file.

    Args:
        name: Session name.
        path: Output JSON file path.
    """
    sess = _require(name)
    state = await sess.page.context.storage_state()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(state, indent=2, default=str))
    n_cookies = len(state.get("cookies", []))
    n_origins = len(state.get("origins", []))
    n_localstorage = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    return json.dumps({
        "status": "saved",
        "path": path,
        "cookies": n_cookies,
        "origins": n_origins,
        "localStorage_entries": n_localstorage,
    }, indent=2)


@mcp.tool()
async def camoufox_wait(name: str, ms: int) -> str:
    """Sleep for `ms` milliseconds within the page (useful between actions)."""
    sess = _require(name)
    await sess.page.wait_for_timeout(ms)
    return json.dumps({"waited_ms": ms}, indent=2)


@mcp.tool()
async def camoufox_get_url(name: str) -> str:
    """Return current URL and title of the active page in the session."""
    sess = _require(name)
    return json.dumps({"url": sess.page.url, "title": await sess.page.title()}, indent=2)


@mcp.tool()
async def camoufox_get_text(name: str, max_chars: int = 4000) -> str:
    """Return visible page text (body innerText), truncated to `max_chars`."""
    sess = _require(name)
    text = await sess.page.locator("body").inner_text()
    truncated = len(text) > max_chars
    return json.dumps({"text": text[:max_chars], "truncated": truncated, "total_length": len(text)}, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
