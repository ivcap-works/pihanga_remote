"""Generate pydantic card proxies from a card catalogue (JSON Schema).

    python -m pihanga_remote.codegen SCHEMA.json [--hints HINTS.json] -o OUT.py

Input is produced by ``runtime/tools/extract-card-schemas.mjs`` (or, ideally,
published by the card library itself). For every card type it emits a
``CardModel`` subclass with

* one field per prop (snake_case, with the camelCase wire name as alias),
* one ``on_<event>`` handler field per event, typed with the payload model,
* class metadata (``__card_type__``, ``__events__``, ``__event_payloads__``,
  ``__default_events_policy__`` from the hints file).

Props typed ``PiCardRef`` become ``CardRef`` (card name *or* card instance).
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
from pathlib import Path
from typing import Any

RESERVED = {
    "model_config", "model_fields", "model_dump", "model_validate", "copy", "dict", "json",
    "schema", "construct", "validate", "fields", "events_policy", "card_type", "handler_for",
    "card_type_", "handlers",
}
SPECIAL_REFS = {"PiCardRef": "CardRef", "PiCardName": "str", "ReactValue": "Any"}


def snake(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z_]", "_", name)
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s).lower()
    if not s or s[0].isdigit():
        s = "f_" + s
    if keyword.iskeyword(s) or s in RESERVED or s.startswith("model_"):
        s += "_"
    return s


# Names the generated module itself uses; generated classes must not shadow them.
MODULE_NAMES = {"Any", "Callable", "ClassVar", "Literal", "Optional", "Union", "CardModel", "CardRef",
                "EventContext", "PropModel", "CARDS", "LIBRARY", "LIBRARY_VERSION"}


def class_name(name: str) -> str:
    n = re.sub(r"[^0-9a-zA-Z_]", "_", name)
    n = n if n and not n[0].isdigit() else "T_" + n
    return n + "_" if n in MODULE_NAMES else n


def ref_name(ref: str) -> str:
    from urllib.parse import unquote

    return unquote(ref.split("/")[-1])


class Gen:
    def __init__(self, catalogue: dict[str, Any], hints: dict[str, Any]):
        self.cat = catalogue
        self.defs: dict[str, Any] = catalogue.get("definitions", {})
        self.hints = hints.get("cards", {})
        self.aliases: list[str] = []  # "Name = <type>" lines
        self.classes: list[str] = []  # class source blocks
        self.emitted: set[str] = set()
        self.class_names: set[str] = set()

    # ------------------------------------------------------------ types
    def ty(self, s: Any, ctx: str) -> str:
        if s is True or s == {} or s is None:
            return "Any"
        if not isinstance(s, dict):
            return "Any"
        if "$ref" in s:
            n = ref_name(s["$ref"])
            if n in SPECIAL_REFS:
                return SPECIAL_REFS[n]
            self.definition(n)
            return class_name(n)
        if "const" in s:
            return f"Literal[{s['const']!r}]"
        if "enum" in s:
            vals = [v for v in s["enum"] if v is not None]
            lit = f"Literal[{', '.join(repr(v) for v in vals)}]" if vals else "None"
            return f"Optional[{lit}]" if None in s["enum"] and vals else lit
        for key in ("anyOf", "oneOf"):
            if key in s:
                return self.union([self.ty(x, ctx) for x in s[key]])
        if "allOf" in s:
            return "Any"  # not used by the shadcn catalogue; keep permissive
        if "not" in s:
            return "None"
        t = s.get("type")
        if isinstance(t, list):
            return self.union([self.ty({**s, "type": x}, ctx) for x in t])
        if t == "string":
            return "str"
        if t == "integer":
            return "int"
        if t == "number":
            return "float"
        if t == "boolean":
            return "bool"
        if t == "null":
            return "None"
        if t == "array":
            it = s.get("items")
            if isinstance(it, list):
                return "list[Any]"
            return f"list[{self.ty(it, ctx + '_item')}]"
        if t == "object" or "properties" in s:
            if s.get("properties"):
                n = class_name(f"{ctx}")
                base_n, i = n, 2
                while n in self.class_names or n in self.defs:
                    n, i = f"{base_n}_{i}", i + 1
                self.model_class(n, s, base="PropModel")
                return n
            ap = s.get("additionalProperties")
            if isinstance(ap, dict) and ap:
                return f"dict[str, {self.ty(ap, ctx + '_value')}]"
            return "dict[str, Any]"
        return "Any"

    @staticmethod
    def union(parts: list[str]) -> str:
        seen: list[str] = []
        for p in parts:
            if p not in seen:
                seen.append(p)
        if "Any" in seen:
            return "Any"
        non_none = [p for p in seen if p != "None"]
        if not non_none:
            return "None"
        u = non_none[0] if len(non_none) == 1 else f"Union[{', '.join(non_none)}]"
        return f"Optional[{u}]" if "None" in seen else u

    # ------------------------------------------------------------ definitions
    def definition(self, name: str) -> None:
        if name in self.emitted:
            return
        self.emitted.add(name)
        s = self.defs.get(name)
        cn = class_name(name)
        if s is None:
            self.aliases.append(f"{cn} = Any  # missing definition")
            return
        if s.get("properties") and s.get("type", "object") == "object":
            self.model_class(cn, s, base="PropModel")
        else:
            self.aliases.append(f"{cn} = {self.ty(s, cn)}" + self.doc_comment(s))

    @staticmethod
    def doc_comment(s: dict[str, Any]) -> str:
        d = s.get("description")
        return f"  # {d.splitlines()[0][:100]}" if d else ""

    def fields(self, s: dict[str, Any], owner: str) -> list[str]:
        lines = []
        req = set(s.get("required", []))
        used: set[str] = set()
        for prop, ps in (s.get("properties") or {}).items():
            py = snake(prop)
            while py in used:
                py += "_"
            used.add(py)
            t = self.ty(ps, f"{owner}_{class_name(prop)}")
            args = []
            if prop not in req:
                t = t if t.startswith("Optional[") or t in ("Any", "None") else f"Optional[{t}]"
                args.append("default=None")
            if py != prop:
                args.append(f"alias={prop!r}")
            desc = ps.get("description") if isinstance(ps, dict) else None
            if desc:
                args.append(f"description={desc.strip()!r}")
            lines.append(f"    {py}: {t} = _Field({', '.join(args)})" if args else f"    {py}: {t}")
        return lines

    def model_class(self, cn: str, s: dict[str, Any], base: str, extra_body: list[str] | None = None,
                    doc: str | None = None) -> None:
        body = []
        d = doc or s.get("description")
        if d:
            body.append(f'    """{d.strip()}"""'.replace('\\', '\\\\'))
        body += extra_body or []
        body += self.fields(s, cn)
        if not body:
            body = ["    pass"]
        self.class_names.add(cn)
        self.classes.append(f"class {cn}({base}):\n" + "\n".join(body) + "\n")

    # ------------------------------------------------------------ cards
    def card(self, card_type: str, c: dict[str, Any]) -> tuple[str, list[str]]:
        cn = class_name(c["declaration"])
        props = c.get("props") or {}
        ps = props
        if "$ref" in props:
            n = ref_name(props["$ref"])
            ps = self.defs.get(n, {})
        if ps.get("type") != "object":
            ps = {"type": "object", "properties": {}}
        events = c.get("events", {})
        ev_map, payloads, handler_lines = {}, {}, []
        for ev, info in events.items():
            attr = snake(ev)  # onClicked → on_clicked
            payload_t = self.ty(info.get("payload") or {}, f"{cn}_{ev}_payload")
            ev_map[attr] = ev
            if payload_t not in ("Any", "None") and not payload_t.startswith(("dict[", "list[")):
                payloads[ev] = payload_t
            et = payload_t if payload_t not in ("None",) else "Any"
            handler_lines.append(
                f"    {attr}: Optional[Union[Callable[[{et}], Any], Callable[[{et}, EventContext], Any]]] = "
                f"_Field(default=None, exclude=True, description={('Handler for ' + ev + ' (' + info['actionType'] + ')')!r})"
            )
        policy = self.hints.get(card_type, {}).get("events", {})
        meta = [
            f"    __card_type__: ClassVar[str] = {card_type!r}",
            f"    __events__: ClassVar[dict[str, str]] = {ev_map!r}",
            f"    __default_events_policy__: ClassVar[dict[str, dict[str, Any]]] = {policy!r}",
        ]
        doc = f"Card `{card_type}` ({self.cat.get('library')} {self.cat.get('version')}, module {c.get('module')})."
        pd = ps.get("description")
        if pd:
            doc += "\n\n    " + pd.strip()
        if c.get("metaCard"):
            doc += "\n\n    NOTE: this is a metacard – it cannot be rendered by the remote runtime."
        self.model_class(cn, ps, base="CardModel", extra_body=meta + handler_lines, doc=doc)
        payload_line = f"{cn}.__event_payloads__ = {{{', '.join(f'{k!r}: {v}' for k, v in payloads.items())}}}"
        alias_lines = [f"{class_name(a)} = {cn}" for a in c.get("aliases", [])]
        return cn, [payload_line] + alias_lines

    def module(self) -> str:
        card_names, post = [], []
        for ct, c in self.cat["cards"].items():
            cn, extra = self.card(ct, c)
            card_names.append(cn)
            post += extra
            post += [ln.split(" = ")[0] for ln in extra[1:]] and []
        exported = card_names + [ln.split(" = ")[0] for ln in post if " = " in ln and not ln.startswith(tuple(card_names))]
        head = f'''"""Card proxies for {self.cat.get('library')} {self.cat.get('version')}.

GENERATED by pihanga_remote.codegen from {self.cat.get('generatedBy', 'a card catalogue')} – do not edit.
"""
# ruff: noqa
from __future__ import annotations

from typing import Any, Callable, ClassVar, Literal, Optional, Union

from pydantic import Field as _Field

from pihanga_remote.card import CardModel, CardRef, EventContext, PropModel

LIBRARY = {self.cat.get('library')!r}
LIBRARY_VERSION = {self.cat.get('version')!r}
'''
        rebuild = "\n".join(
            f"{n}.model_rebuild()" for n in [re.match(r"class (\w+)\(", c).group(1) for c in self.classes]
        )
        all_names = sorted(set(card_names) | {ln.split(" = ")[0] for ln in post if " = " in ln and "__event_payloads__" not in ln})
        return (
            head
            + "\n# --- models (annotations are resolved lazily by model_rebuild below)\n\n" + "\n\n".join(self.classes) + "\n"
            + "# --- type aliases\n" + "\n".join(self.aliases) + "\n\n"
            + "# --- card metadata\n" + "\n".join(post) + "\n\n"
            + rebuild + "\n\n"
            + "CARDS: dict[str, type[CardModel]] = {c.__card_type__: c for c in [" + ", ".join(card_names) + "]}\n\n"
            + "__all__ = " + repr(all_names + ["CARDS", "LIBRARY", "LIBRARY_VERSION"]) + "\n"
        )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("schema")
    ap.add_argument("--hints")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    cat = json.loads(Path(a.schema).read_text())
    hints = json.loads(Path(a.hints).read_text()) if a.hints else {}
    src = Gen(cat, hints).module()
    Path(a.out).write_text(src)
    print(f"wrote {a.out} ({len(cat['cards'])} cards)", file=sys.stderr)


if __name__ == "__main__":
    main()
