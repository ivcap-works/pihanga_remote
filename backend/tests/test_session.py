import asyncio

import jsonpatch
import pytest

from pihanga_remote import GenericCard, Session
from pihanga_remote.cards.shadcn import Button, PageWithNavbar, SdFramework, Stack, TextField, Typography


def run(coro):
    return asyncio.run(coro)


class Wire:
    """Collects sent messages and mirrors the browser's view of the cards."""

    def __init__(self):
        self.msgs = []
        self.cards = None
        self.version = None

    async def send(self, m):
        self.msgs.append(m)
        if m["t"] == "snapshot":
            self.cards, self.version = m["cards"], m["version"]
        elif m["t"] == "patch":
            assert m["base"] == self.version
            self.cards = jsonpatch.apply_patch(self.cards, m["ops"])
            self.version = m["version"]


def make():
    w = Wire()
    s = Session(w.send)
    count = Typography(text="0", level="h2")

    def inc(_ev):
        count.text = str(int(count.text) + 1)

    s.window(SdFramework(page=PageWithNavbar(title="T", main=Stack(content=[count, Button(label="+", on_clicked=inc)]))))
    return w, s, count


def test_flatten_names_and_wire_format():
    w, s, _ = make()
    run(s.handle({"t": "hello", "route": {"path": [], "query": {}}}))
    c = w.cards
    assert c["_window"] == {"cardType": "shad/framework", "page": "_window/page"}
    assert c["_window/page"]["main"] == "_window/page/main"
    assert c["_window/page/main"]["content"] == ["_window/page/main/content/0", "_window/page/main/content/1"]
    assert c["_window/page/main/content/0"] == {"cardType": "shad/typography", "text": "0", "level": "h2"}
    btn = c["_window/page/main/content/1"]
    assert btn == {"cardType": "pi/button", "label": "+"}  # handler not serialised


def test_event_runs_handler_and_sends_patch_with_ack():
    w, s, _ = make()
    run(s.handle({"t": "hello", "route": {"path": [], "query": {}}}))
    run(s.handle({"t": "event", "seq": 7, "card": "_window/page/main/content/1", "event": "onClicked",
                  "type": "pi/button/clicked", "payload": {}}))
    last = w.msgs[-1]
    assert last["t"] == "patch" and last["ack"] == 7
    assert last["ops"] == [{"op": "replace", "path": "/_window~1page~1main~1content~10/text", "value": "1"}]
    assert w.cards["_window/page/main/content/0"]["text"] == "1"


def test_explicit_names_and_echo_policy():
    w = Wire()
    s = Session(w.send)
    tf = s.add("name", TextField(value=""))
    got = []
    tf.on_changed = lambda ev, ctx: got.append((ev.value, ctx.card_name))
    s.window(SdFramework(page=Stack(content=[tf])))
    run(s.handle({"t": "hello", "route": {"path": [], "query": {}}}))
    assert w.cards["_window/page"]["content"] == ["name"]
    assert w.cards["name"]["$events"] == {"onChanged": {"echo": {"value": "value"}}}
    run(s.handle({"t": "event", "seq": 1, "card": "name", "event": "onChanged", "type": "pi/text-field/changed",
                  "payload": {"value": "ab"}}))
    assert got == [("ab", "name")]
    # handler did not change the model → patch only carries the ack
    assert w.msgs[-1] == {"t": "patch", "base": 1, "version": 2, "ops": [], "ack": 1}


def test_structure_change_and_resync():
    w, s, count = make()
    run(s.handle({"t": "hello", "route": {"path": [], "query": {}}}))
    main = s.cards["_window"].page.main
    main.content = [Typography(text="new"), *main.content]
    run(s.flush())
    assert w.cards["_window/page/main/content/0"]["text"] == "new"
    assert w.cards["_window/page/main/content/1"]["text"] == "0"  # count card renamed by position
    run(s.handle({"t": "resync", "reason": "test"}))
    assert w.msgs[-1]["t"] == "snapshot"


def test_generic_card_and_async_handler():
    w = Wire()
    s = Session(w.send)
    hits = []

    async def h(ev, ctx):
        await asyncio.sleep(0)
        hits.append(ev)

    s.window(GenericCard(card_type_="acme/gauge", value=3, handlers={"onChanged": h}))
    run(s.handle({"t": "hello", "route": {"path": [], "query": {}}}))
    assert w.cards["_window"] == {"cardType": "acme/gauge", "value": 3}
    run(s.handle({"t": "event", "seq": 1, "card": "_window", "event": "onChanged", "type": "x", "payload": {"v": 1}}))
    assert hits == [{"v": 1}]


def test_functions_are_rejected():
    w = Wire()
    s = Session(w.send)
    s.window(GenericCard(card_type_="x", fmt=lambda v: v))
    with pytest.raises(TypeError, match="functions cannot be sent"):
        run(s.handle({"t": "hello", "route": {"path": [], "query": {}}}))
