"""Demo: the "cars and trucks" example from the Pihanga README, driven from Python.

    uvicorn examples.transport:app --reload        (from the backend/ directory)
    open http://localhost:8000

Everything the browser shows is declared below with the generated
@pihanga2/shadcn proxies. There is no JavaScript in this app.
"""

from __future__ import annotations

import asyncio
import itertools

from pihanga_remote import AppOptions, Session, create_app
from pihanga_remote.cards.shadcn import (
    Button,
    DataTable,
    PageWithNavbar,
    SdFramework,
    Stack,
    Switch,
    TextField,
    Toast,
    Typography,
)

FLEET = {
    "cars": [
        {"id": 1, "make": "Toyota", "model": "Corolla", "seats": 5, "status": "available"},
        {"id": 2, "make": "Tesla", "model": "Model 3", "seats": 5, "status": "booked"},
        {"id": 3, "make": "Mazda", "model": "MX-5", "seats": 2, "status": "service"},
    ],
    "trucks": [
        {"id": 11, "make": "Isuzu", "model": "N-Series", "seats": 3, "status": "available"},
        {"id": 12, "make": "Volvo", "model": "FH16", "seats": 2, "status": "booked"},
    ],
}
COLUMNS = [
    {"key": "make", "title": "Make", "sortable": True},
    {"key": "model", "title": "Model", "sortable": True},
    {"key": "seats", "title": "Seats", "type": "number", "align": "right", "sortable": True},
    {"key": "status", "title": "Status", "type": "badge",
     "variants": {"available": "default", "booked": "secondary", "service": "destructive"}},
]
new_ids = itertools.count(100)
CLOCK_INTERVAL_S = 10


def build(s: Session) -> None:
    """Called once per browser tab."""

    # ---- per-kind page: title, filter, table -----------------------------
    def fleet_page(kind: str):
        title = Typography(text=kind.capitalize(), level="h2")
        summary = Typography(level="muted")
        table = DataTable(columns=COLUMNS, rows=[], hoverable=True, striped=True)
        only_available = Switch(label="available only", checked=False)
        query = TextField(placeholder=f"filter {kind}…", value="")

        def refresh() -> None:
            q = (query.value or "").lower()
            rows = [
                r for r in FLEET[kind]
                if (q in f"{r['make']} {r['model']}".lower()) and (not only_available.checked or r["status"] == "available")
            ]
            table.rows = [{"id": r["id"], "data": r} for r in rows]
            summary.text = f"{len(rows)} of {len(FLEET[kind])} {kind} shown"

        def on_query(ev):  # runs on every keystroke; the browser echoes locally
            query.value = ev.value
            refresh()

        def on_toggle(ev):
            only_available.checked = ev.checked
            refresh()

        async def add(_ev, ctx):
            n = next(new_ids)
            FLEET[kind].append({"id": n, "make": "New", "model": f"#{n}", "seats": 4, "status": "available"})
            refresh()
            await ctx.session.toast(f"Added {kind[:-1]} #{n}", variant="success")

        async def row_clicked(ev, ctx):
            d = ev.row.data
            await ctx.session.toast(f"{d['make']} {d['model']}", description=f"status: {d['status']}")

        query.on_changed = on_query
        only_available.on_changed = on_toggle
        table.on_row_clicked = row_clicked
        refresh()
        toolbar = Stack(direction="row", spacing=2, alignItems="center",
                        content=[query, only_available, Button(label=f"Add {kind[:-1]}", on_clicked=add)])
        return Stack(direction="column", spacing=3, content=[title, toolbar, table, summary])

    pages = {k: s.add(f"page/{k}", fleet_page(k)) for k in FLEET}

    # ---- a server-side clock, updated from a background task --------------
    # One patch every CLOCK_INTERVAL_S seconds (kept low-frequency so the
    # Redux/WebSocket traffic of real interactions stays easy to follow).
    clock = Typography(level="muted", text="")

    async def tick() -> None:
        for i in itertools.count():
            clock.text = f"connected for {i * CLOCK_INTERVAL_S}s"
            await s.flush()
            await asyncio.sleep(CLOCK_INTERVAL_S)

    # ---- shell --------------------------------------------------------------
    shell = PageWithNavbar(
        title="Transportation Service",
        nav_links=[{"id": k, "title": k.capitalize()} for k in FLEET],
        main="page/cars",
        footer=Stack(direction="column", content=[clock, Toast()]),
    )

    async def nav(ev, ctx):
        await ctx.session.navigate([ev.id])  # updates URL, then on_route below

    shell.on_navigate_to = nav

    @s.on_route
    def route(_s: Session, path: list[str], _q: dict[str, str]) -> None:
        shell.main = f"page/{path[0]}" if path and path[0] in pages else "page/cars"

    s.window(SdFramework(page=shell, theme="light"))
    task = asyncio.get_running_loop().create_task(tick())
    s.on_close(lambda _s: task.cancel())


app = create_app(build, AppOptions(title="Transportation Service", description="Pihanga demo: cars and trucks, driven from Python"))
