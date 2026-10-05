"""End-to-end smoke test against a running `uvicorn examples.transport:app`.

    python tests/e2e/smoke.py [http://localhost:8000] [screenshot-dir]
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    # PW_CHROMIUM: use an existing Chromium instead of `playwright install chromium`
    b = p.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
    page = b.new_page(viewport={"width": 1100, "height": 720})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(URL)
    expect(page.get_by_text("Transportation Service").first).to_be_visible(timeout=10000)
    expect(page.get_by_text("3 of 3 cars shown")).to_be_visible()
    page.screenshot(path=str(OUT / "1-cars.png"))
    print("1. initial render OK")

    # typing: every keystroke goes to Python; local echo must keep the input stable
    box = page.get_by_placeholder("filter cars…")
    box.click()
    page.keyboard.type("toyota", delay=15)
    expect(box).to_have_value("toyota")
    expect(page.get_by_text("1 of 3 cars shown")).to_be_visible()
    st = page.evaluate("() => window.__pihanga.store.getState().remote")
    print("2. typing OK, remote state:", st)
    box.fill("")
    expect(page.get_by_text("3 of 3 cars shown")).to_be_visible()

    page.get_by_role("switch").click()
    expect(page.get_by_text("1 of 3 cars shown")).to_be_visible()
    page.get_by_role("switch").click()
    print("3. switch OK")

    page.get_by_role("button", name="Add car").click()
    expect(page.get_by_text("4 of 4 cars shown")).to_be_visible()
    expect(page.get_by_text("Added car #", exact=False).first).to_be_visible()
    page.screenshot(path=str(OUT / "2-added.png"))
    print("4. add + toast OK")

    page.get_by_text("Mazda").click()
    expect(page.get_by_text("status: service")).to_be_visible()
    print("5. row click → toast OK")

    page.get_by_text("Trucks", exact=True).first.click()
    expect(page.get_by_text("2 of 2 trucks shown")).to_be_visible()
    assert page.url.endswith("/trucks"), page.url
    page.screenshot(path=str(OUT / "3-trucks.png"))
    print("6. navigation OK:", page.url)

    page.go_back()
    expect(page.get_by_text("4 of 4 cars shown")).to_be_visible()
    print("7. back button OK:", page.url)

    page.goto(URL + "/trucks")
    expect(page.get_by_text("2 of 2 trucks shown")).to_be_visible()
    print("8. deep link OK")

    c1 = page.get_by_text("connected for").inner_text()
    page.wait_for_timeout(10_500)  # the demo clock ticks every 10 s
    c2 = page.get_by_text("connected for").inner_text()
    assert c1 != c2, (c1, c2)
    print("9. server push OK:", c1, "→", c2)

    probs = page.locator("[data-pihanga-problem]").all_inner_texts()
    print("render problems:", probs)
    print("console errors:", errors)
    b.close()
