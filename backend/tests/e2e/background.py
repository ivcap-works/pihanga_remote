"""Browser checks for examples/background.py (AppOptions, workers, broadcast, REST, threads).

    SENSOR_INTERVAL_S=1 poetry run python -m uvicorn examples.background:app --port 8030
    poetry run python tests/e2e/background.py http://localhost:8030
"""
import os
import sys
import time

from playwright.sync_api import expect, sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8030"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
    ctx = b.new_context()
    a, bb = ctx.new_page(), ctx.new_page()
    errors = []
    for pg in (a, bb):
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(URL)
        expect(pg.get_by_text("Background processing").first).to_be_visible(timeout=10000)

    # 1. AppOptions → <head>
    assert a.title() == "Fleet monitor", a.title()
    desc = a.locator('meta[name="description"]').get_attribute("content")
    assert desc.startswith("Pihanga example"), desc
    assert a.locator('meta[name="robots"]').get_attribute("content") == "noindex"
    assert a.locator('meta[name="theme-color"]').get_attribute("content") == "#2563eb"
    href = a.locator('link[rel="icon"]').get_attribute("href")
    r = ctx.request.get(URL + href)
    assert r.ok and r.headers["content-type"] == "image/svg+xml" and b"<svg" in r.body(), (href, r.headers)
    print(f"1. head: title/description/theme-color/robots/icon OK ({href})")

    # 2. app routes win over the UI catch-all, even when defined after create_app
    st = ctx.request.get(URL + "/api/status").json()
    assert st["tabs"] == 2, st
    spa = ctx.request.get(URL + "/some/client/route").text()
    assert "<title>Fleet monitor</title>" in spa
    print(f"2. GET /api/status → JSON {st}; unknown paths → index.html")

    # 3. background worker → broadcast to all tabs
    t0 = a.get_by_text("sensor load").inner_text()
    expect(a.get_by_text("sensor load")).not_to_have_text(t0, timeout=5000)
    expect(bb.get_by_text("sensor load")).not_to_have_text(t0, timeout=5000)
    print("3. worker broadcast reaches both tabs")

    # 4. REST endpoint → broadcast
    r = ctx.request.post(URL + "/api/announce", data={"text": "Maintenance at 5pm"})
    assert r.json() == {"tabs": 2}, r.json()
    expect(a.get_by_text("Maintenance at 5pm").first).to_be_visible()
    expect(bb.get_by_text("Maintenance at 5pm").first).to_be_visible()
    print("4. POST /api/announce updates both tabs")

    # 5. a blocking `def` handler in tab A does not stall tab B or the worker
    a.get_by_role("button", name="Report (blocking def)").click()
    t_start = time.time()
    bb.get_by_role("button", name="Count").click()
    expect(bb.get_by_text("1 clicks")).to_be_visible(timeout=1500)
    other_tab_latency = time.time() - t_start
    s1 = bb.get_by_text("sensor load").inner_text()
    expect(bb.get_by_text("sensor load")).not_to_have_text(s1, timeout=2500)  # worker still ticking
    expect(a.get_by_text("blocking report done")).to_be_visible(timeout=6000)
    print(f"5. while A blocked for 3 s, B answered in {other_tab_latency:.2f} s and the worker kept running")

    # 6. async handler shows intermediate state via flush()
    a.get_by_role("button", name="Report (async + progress)").click()
    expect(a.get_by_text("working…")).to_be_visible(timeout=1500)
    expect(a.get_by_text("async report:", exact=False)).to_be_visible(timeout=6000)
    print("6. async handler: 'working…' shown, then result")

    print("console errors:", errors)
    assert not errors
    b.close()
