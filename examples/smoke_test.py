"""Programmatic smoke test: directly call MCP tool functions (no MCP transport)."""
import asyncio
import json
import sys
import time

from camoufox_mcp.server import (
    camoufox_open,
    camoufox_navigate,
    camoufox_get_url,
    camoufox_get_text,
    camoufox_screenshot,
    camoufox_list_sessions,
    camoufox_close,
)


def show(label, result):
    print(f"\n=== {label} ===")
    print(result if isinstance(result, str) else json.dumps(result, indent=2, default=str))


async def main():
    show("OPEN", await camoufox_open(name="smoke", headless=True, url="https://example.com"))
    show("URL", await camoufox_get_url(name="smoke"))
    show("TEXT", await camoufox_get_text(name="smoke", max_chars=200))
    show("LIST", await camoufox_list_sessions())
    show("NAV", await camoufox_navigate(name="smoke", url="https://httpbin.org/headers"))
    show("TEXT2", await camoufox_get_text(name="smoke", max_chars=400))
    show("SHOT", await camoufox_screenshot(name="smoke", path=f"/tmp/camoufox-mcp-smoke-{int(time.time())}.png"))
    show("CLOSE", await camoufox_close(name="smoke"))


if __name__ == "__main__":
    asyncio.run(main())
