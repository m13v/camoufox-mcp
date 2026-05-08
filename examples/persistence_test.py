"""End-to-end credential persistence test.

1. Open session 'persist-demo', navigate to a page that sets a cookie.
2. Inject custom cookies + localStorage to simulate "logged in".
3. Close (auto-save fires).
4. Wipe profile dir to force restore-from-JSON path.
5. Reopen and verify cookies + localStorage came back.
"""
import asyncio
import json
import shutil
from pathlib import Path

from camoufox_mcp.server import (
    DEFAULT_PROFILE_ROOT,
    DEFAULT_STORAGE_DIR,
    camoufox_open,
    camoufox_close,
    camoufox_navigate,
    camoufox_evaluate,
    camoufox_get_cookies,
    camoufox_list_saved,
)

NAME = "persist-demo"


def show(label, result):
    print(f"\n=== {label} ===")
    print(result if isinstance(result, str) else json.dumps(result, indent=2, default=str))


async def main():
    # Clean slate
    pd = DEFAULT_PROFILE_ROOT / NAME
    sj = DEFAULT_STORAGE_DIR / f"{NAME}.storage.json"
    if pd.exists():
        shutil.rmtree(pd)
    if sj.exists():
        sj.unlink()

    # PHASE 1: open fresh, plant cookies + localStorage, close
    show("OPEN-1 (fresh)", await camoufox_open(name=NAME, headless=True, url="https://example.com"))
    # Set a cookie via JS
    await camoufox_evaluate(name=NAME, js_code='document.cookie = "demo=hello123; max-age=86400; path=/"')
    # Set localStorage
    await camoufox_evaluate(name=NAME, js_code='localStorage.setItem("demo_key", "demo_value_planted")')
    show("COOKIES (after plant)", await camoufox_get_cookies(name=NAME, domain="example.com"))
    show("CLOSE-1 (auto-save fires)", await camoufox_close(name=NAME))

    # Verify storage JSON was written
    assert sj.exists(), f"Auto-save failed; no JSON at {sj}"
    j = json.loads(sj.read_text())
    print(f"\n[disk] {sj} -> {len(j.get('cookies', []))} cookies, "
          f"{sum(len(o.get('localStorage', [])) for o in j.get('origins', []))} localStorage entries")

    # PHASE 2: wipe profile dir to force the restore-from-JSON path
    print(f"\n[wipe] removing profile dir {pd} to force JSON restore path")
    if pd.exists():
        shutil.rmtree(pd)

    # PHASE 3: reopen, expect auto-restore from JSON
    show("OPEN-2 (profile wiped)", await camoufox_open(name=NAME, headless=True))
    await camoufox_navigate(name=NAME, url="https://example.com")
    cookies_after = json.loads(await camoufox_get_cookies(name=NAME, domain="example.com"))
    ls_after = json.loads(await camoufox_evaluate(name=NAME, js_code='localStorage.getItem("demo_key")'))
    show("COOKIES (after restore)", cookies_after)
    show("LOCALSTORAGE demo_key", ls_after)

    # Asserts
    cookie_ok = any(c.get("name") == "demo" and c.get("value") == "hello123" for c in cookies_after.get("cookies", []))
    ls_ok = ls_after.get("result") == "demo_value_planted"
    print()
    print("=" * 50)
    print(f"Cookie restored: {cookie_ok}")
    print(f"LocalStorage restored: {ls_ok}")
    print(f"OVERALL: {'PASS' if (cookie_ok and ls_ok) else 'FAIL'}")
    print("=" * 50)

    show("LIST SAVED", await camoufox_list_saved())
    await camoufox_close(name=NAME)


if __name__ == "__main__":
    asyncio.run(main())
