"""Same demo as transport.py, but served with the *script-tag* deployment:

    uvicorn examples.script_tags:app --port 8000

The browser gets a generic index.html with an import map and loads, as
separate cacheable ES modules,
  - /pkg/@pihanga2/runtime@0.1.0/…   React, ReactDOM, lean runtime (one copy)
  - /pkg/@pihanga2/shadcn@…/…        the shadcn card library (+ precompiled CSS)
  - /pkg/acme-cards@0.1.0/…          a third-party card library written without a build step

It adds one `acme/gauge` card that embeds a shadcn badge – two card libraries,
one React, one card registry.
"""

from __future__ import annotations

from pihanga_remote import AppOptions, Session, create_app
from pihanga_remote.cards.acme import Gauge
from pihanga_remote.cards.shadcn import ShadBadge

from examples import transport


def build(s: Session) -> None:
    transport.build(s)
    badge = ShadBadge(label="cars", variant="secondary")
    gauge = Gauge(label="Fleet size", value=len(transport.FLEET["cars"]), max=10, badge_card=badge)

    async def reset(ev, ctx):
        gauge.value = 0
        badge.label = f"reset from {ev.value:g}"
        await ctx.session.toast("gauge reset", variant="info")

    gauge.on_reset = reset
    s.add("fleet-gauge", gauge)
    s.cards["_window"].page.footer.content.insert(0, gauge)


app = create_app(build, AppOptions(title="Transportation Service (script tags)", bundle="script-tags"))
