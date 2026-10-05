"""Where does "normal" backend processing go?  A worked example.

    poetry run python -m uvicorn examples.background:app --port 8000

Four kinds of work, all in one app:

1. Per-tab UI logic         → event handlers, wired in build()          (the "Count" button)
2. Slow / blocking work     → a plain `def` handler runs in a worker thread;
                              an `async def` handler can show progress with
                              `await ctx.session.flush()` and offload with
                              `await asyncio.to_thread(...)`             (the two "report" buttons)
3. App-wide background work → create_app(..., workers=[fn]); fn(hub) runs for
                              the lifetime of the server and pushes changes to
                              every open tab with hub.broadcast(...)       (the "sensor" line)
4. Other entry points       → ordinary FastAPI routes on the same app; they
                              reach the tabs through get_hub(app)          (POST /api/announce)
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from pathlib import Path

from pydantic import BaseModel

from pihanga_remote import AppOptions, Hub, Session, create_app, get_hub
from pihanga_remote.cards.shadcn import Button, PageWithNavbar, SdFramework, Stack, Toast, Typography

SENSOR_INTERVAL_S = float(os.environ.get("SENSOR_INTERVAL_S", "5"))
SENSOR = {"load": 0.0, "updated": "never"}  # app-wide state (per server process)


def build(s: Session) -> None:
    """Per tab: declare the cards, wire the handlers, register what workers may update."""
    banner = Typography(level="lead", text="")
    sensor = Typography(level="muted", text=f"sensor load: {SENSOR['load']:.1f} (updated {SENSOR['updated']})")
    count, clicks = Typography(text="0 clicks"), [0]
    result = Typography(level="muted", text="no report yet")

    # 1. per-tab UI logic
    def on_count(_ev):
        clicks[0] += 1
        count.text = f"{clicks[0]} clicks"

    # 2a. blocking work in a plain `def` handler → runs in a worker thread,
    #     other tabs (and the sensor broadcast) keep running meanwhile
    def on_blocking_report(_ev):
        time.sleep(3)  # e.g. a slow library call
        result.text = f"blocking report done at {time.strftime('%H:%M:%S')}"

    # 2b. async handler with visible progress
    async def on_async_report(_ev, ctx):
        async_btn.loading = True
        result.text = "working…"
        await ctx.session.flush()  # send the intermediate state now
        value = await asyncio.to_thread(lambda: (time.sleep(3), random.randint(1, 100))[1])
        async_btn.loading = False
        result.text = f"async report: {value}"

    async_btn = Button(label="Report (async + progress)", on_clicked=on_async_report)

    # What workers and endpoints may change in this tab (see sensor_worker / announce).
    s.state["sensor"] = sensor
    s.state["banner"] = banner

    s.window(
        SdFramework(
            theme="light",
            page=PageWithNavbar(
                title="Background processing",
                main=Stack(
                    direction="column",
                    spacing=3,
                    content=[
                        banner,
                        sensor,
                        Stack(direction="row", spacing=2, content=[Button(label="Count", on_clicked=on_count), count]),
                        Stack(
                            direction="row",
                            spacing=2,
                            content=[Button(label="Report (blocking def)", on_clicked=on_blocking_report), async_btn],
                        ),
                        result,
                    ],
                ),
                footer=Toast(),
            ),
        )
    )


# 3. app-wide background processing: started with the server, cancelled on shutdown
async def sensor_worker(hub: Hub) -> None:
    while True:
        await asyncio.sleep(SENSOR_INTERVAL_S)
        SENSOR["load"] = random.uniform(0, 100)
        SENSOR["updated"] = time.strftime("%H:%M:%S")
        text = f"sensor load: {SENSOR['load']:.1f} (updated {SENSOR['updated']})"

        def show(s: Session) -> None:
            s.state["sensor"].text = text

        await hub.broadcast(show)


app = create_app(
    build,
    AppOptions(
        title="Fleet monitor",
        description="Pihanga example: background workers, broadcasts and REST endpoints",
        icon=Path(__file__).parent / "truck.svg",
        theme_color="#2563eb",
        meta={"robots": "noindex"},
    ),
    workers=[sensor_worker],
)


# 4. other entry points: normal FastAPI routes on the same app
class Announcement(BaseModel):
    text: str


@app.post("/api/announce")
async def announce(a: Announcement) -> dict[str, int]:
    async def show(s: Session) -> None:
        s.state["banner"].text = a.text
        await s.toast(a.text, variant="info")

    return {"tabs": await get_hub(app).broadcast(show)}


@app.get("/api/status")
async def status() -> dict[str, object]:
    return {"tabs": len(get_hub(app).sessions), "sensor": SENSOR}
