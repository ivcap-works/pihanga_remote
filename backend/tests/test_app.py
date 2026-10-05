import asyncio
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pihanga_remote import AppOptions, Session, create_app, get_hub
from pihanga_remote.cards.shadcn import Button, SdFramework, Typography

ICON = Path(__file__).parents[1] / "examples" / "truck.svg"


def build(s: Session) -> None:
    s.window(SdFramework(page=Typography(text="hi")))


def test_options_render_head_and_escape():
    html = AppOptions(title="A <b>&", description='x"y', theme_color="#123456", meta={"author": "me"},
                      lang="de", icon="https://example.org/i.png").render_index(
        '<!doctype html><html lang="en"><head><title>Pihanga</title></head><body></body></html>')
    assert '<html lang="de">' in html
    assert "<title>A &lt;b&gt;&amp;</title>" in html
    assert 'content="x&quot;y"' in html and 'name="theme-color"' in html and 'name="author"' in html
    assert '<link rel="icon" href="https://example.org/i.png"' in html


def test_options_icon_file_must_exist():
    with pytest.raises(ValueError, match="icon file not found"):
        AppOptions(icon="does/not/exist.svg")


def test_app_serves_title_icon_and_user_routes_win():
    app = create_app(build, AppOptions(title="My App", icon=ICON))

    @app.get("/api/ping")  # defined AFTER create_app: must not be shadowed by the UI
    def ping():
        return {"ok": True}

    c = TestClient(app)
    assert c.get("/api/ping").json() == {"ok": True}
    page = c.get("/some/client/route")
    assert page.status_code == 200 and "<title>My App</title>" in page.text
    href = page.text.split('rel="icon" href="')[1].split('"')[0]
    icon = c.get(href)
    assert icon.headers["content-type"] == "image/svg+xml" and "immutable" in icon.headers["cache-control"]
    assert c.get("/favicon.ico").headers["content-type"] == "image/svg+xml"
    assert c.post("/nope").status_code == 404  # non-GET stays a normal 404


def test_websocket_hello_snapshot_and_hub():
    app = create_app(build, AppOptions())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"t": "hello", "route": {"path": [], "query": {}}})
        snap = ws.receive_json()
        assert snap["t"] == "snapshot" and snap["cards"]["_window/page"]["text"] == "hi"
        assert len(get_hub(app).sessions) == 1


def test_workers_start_and_stop():
    seen = []

    async def worker(hub):
        seen.append("started")
        try:
            await asyncio.sleep(3600)
        finally:
            seen.append("stopped")

    app = create_app(build, workers=[worker])
    with TestClient(app):
        pass
    assert seen == ["started", "stopped"]


class Wire:
    def __init__(self):
        self.msgs = []

    async def send(self, m):
        self.msgs.append(m)


def test_sync_handler_runs_in_worker_thread_and_async_flush_is_reentrant():
    async def main():
        w = Wire()
        s = Session(w.send)
        out = Typography(text="")
        threads = []

        def blocking(_ev):
            threads.append(threading.get_ident())
            out.text = "sync"

        async def progressive(_ev, ctx):
            out.text = "working"
            await ctx.session.flush()  # must not deadlock on the session lock
            out.text = "done"

        s.window(SdFramework(page=out))
        s.add("b1", Button(label="1", on_clicked=blocking))
        s.add("b2", Button(label="2", on_clicked=progressive))
        await s.handle({"t": "hello", "route": {}})
        await s.handle({"t": "event", "seq": 1, "card": "b1", "event": "onClicked", "type": "x", "payload": {}})
        assert threads and threads[0] != threading.get_ident()
        await asyncio.wait_for(
            s.handle({"t": "event", "seq": 2, "card": "b2", "event": "onClicked", "type": "x", "payload": {}}), 2)
        texts = [op["value"] for m in w.msgs if m["t"] == "patch" for op in m["ops"]]
        assert texts == ["sync", "working", "done"]

        await s.update(lambda sess: setattr(out, "text", "from outside"))
        assert w.msgs[-1]["ops"][0]["value"] == "from outside"

    asyncio.run(main())
