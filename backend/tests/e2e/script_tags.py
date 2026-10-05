"""Checks specific to the script-tag / import-map deployment.

    uvicorn examples.script_tags:app --port 8010      (from backend/)
    python tests/e2e/script_tags.py http://localhost:8010
"""
import os
import sys
from collections import Counter

from playwright.sync_api import expect, sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010"

with sync_playwright() as p:
    # PW_CHROMIUM: use an existing Chromium instead of `playwright install chromium`
    b = p.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
    ctx = b.new_context()
    page = ctx.new_page()
    errors, requests = [], []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: requests.append(r.url.replace(URL, "")))

    page.goto(URL)
    expect(page.get_by_text("Fleet size")).to_be_visible(timeout=10000)

    # 1. one registry: card types from both libraries are known to the runtime
    m = page.evaluate("() => window.__pihanga.manifest()")
    types = {c["name"] for c in m["cardTypes"]}
    assert {"acme/gauge", "pi/button", "shad/badge", "shad/framework"} <= types, types
    print(f"1. one registry: {len(types)} card types incl. acme/gauge + shadcn")

    # 2. cross-library composition: the acme card renders a shadcn badge via <Card>
    gauge = page.locator('[data-pihanga="fleet-gauge"]')
    expect(gauge.get_by_text("cars", exact=True)).to_be_visible()
    print("2. acme/gauge embeds shad/badge OK")

    # 3. same React: useState in the no-build library works (hover changes the bar colour)
    bar = gauge.locator("[data-acme-gauge-bar]")
    before = bar.evaluate("e => getComputedStyle(e).backgroundColor")
    gauge.hover()
    page.wait_for_timeout(100)
    after = bar.evaluate("e => getComputedStyle(e).backgroundColor")
    assert before != after, (before, after)
    print(f"3. hooks in third-party card OK ({before} → {after})")

    # 4. third-party event → Python handler → patch
    gauge.get_by_role("button", name="reset").click()
    expect(gauge.get_by_text("0/10")).to_be_visible()
    expect(gauge.get_by_text("reset from", exact=False)).to_be_visible()
    print("4. acme onReset → python → patch OK")

    # 5. every shared module fetched exactly once
    js = Counter(r for r in requests if r.endswith(".js"))
    dupes = {k: v for k, v in js.items() if v > 1}
    assert not dupes, dupes
    react_like = sorted(k for k in js if "react" in k)
    print(f"5. {len(js)} JS modules, none twice; React files: {react_like}")

    # 6. revisit: versioned /pkg files come from the browser cache
    page2 = ctx.new_page()
    page2.goto(URL)
    expect(page2.get_by_text("Fleet size")).to_be_visible(timeout=10000)
    res = page2.evaluate(
        "() => performance.getEntriesByType('resource').filter(e => e.name.includes('/pkg/'))"
        ".map(e => [new URL(e.name).pathname, e.transferSize])"
    )
    network = [r for r in res if r[1] > 0]
    print(f"6. revisit: {len(res)} /pkg resources, {len(network)} transferred over the network {network}")
    assert not network

    print("console errors:", errors)
    assert not errors
    b.close()
