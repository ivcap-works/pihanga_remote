"""Card models ("proxies") and the flattening of a card tree into the wire format.

A card in Python is a pydantic model. Assigning to its fields is all an app
does; the session later dumps the tree, diffs it against what the browser has
and sends JSON-Patch ops.

Child cards can be referenced *by name* (a ``str``) or *by instance*. Instances
nested anywhere inside another card are given a deterministic name
(``parent/prop`` or ``parent/prop/<i>``, the same scheme @pihanga2/core uses
for inline card declarations) and sent as separate top-level entries. This is
how "anonymous" cards are resolved in the backend: the browser only ever sees a
flat ``{cardName: declaration}`` map.
"""

from __future__ import annotations

import datetime as _dt
import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover
    from .session import Session


class PropModel(BaseModel):
    """Base for nested prop structures and event payloads generated from the
    card library's JSON Schema. Unknown keys are kept (``extra="allow"``) so a
    newer bundle never breaks an older backend."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        protected_namespaces=(),
    )


@dataclass
class EventContext:
    """Second (optional) argument passed to event handlers."""

    session: "Session"
    card: "CardModel"
    card_name: str
    event: str  # "onClicked"
    action_type: str  # "pi/button/clicked"
    seq: int
    card_key: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


Handler = Callable[..., Any]
"""``fn(event)`` or ``fn(event, ctx: EventContext)``; may be ``async``."""


class CardModel(PropModel):
    """Base class of all card proxies.

    Class-level metadata (filled in by the code generator):

    * ``__card_type__`` – the card type registered in the browser bundle
    * ``__events__`` – python handler attribute → ``onXxx`` event name
    * ``__event_payloads__`` – ``onXxx`` → payload model class
    * ``__default_events_policy__`` – default ``$events`` (echo/debounce hints)
    """

    __card_type__: ClassVar[str] = ""
    __events__: ClassVar[dict[str, str]] = {}
    __event_payloads__: ClassVar[dict[str, type[BaseModel]]] = {}
    __default_events_policy__: ClassVar[dict[str, dict[str, Any]]] = {}

    events_policy: Optional[dict[str, dict[str, Any]]] = Field(
        default=None,
        alias="$events",
        description="Per-event policy overriding the card type's default (echo, debounceMs, send).",
    )

    def card_type(self) -> str:
        return self.__card_type__

    def handler_for(self, event: str) -> Optional[Handler]:
        for attr, ev in type(self).__events__.items():
            if ev == event:
                return getattr(self, attr, None)
        return None

    def __hash__(self) -> int:  # identity semantics: cards are mutable proxies
        return id(self)

    def __eq__(self, other: object) -> bool:
        return self is other


class GenericCard(CardModel):
    """Escape hatch for card types without a generated proxy::

    GenericCard(card_type_="acme/gauge", value=3, handlers={"onChanged": fn})
    """

    card_type_: str = Field(exclude=True)
    handlers: dict[str, Handler] = Field(default_factory=dict, exclude=True)

    def card_type(self) -> str:
        return self.card_type_

    def handler_for(self, event: str) -> Optional[Handler]:
        return self.handlers.get(event)


CardRef = Union[str, CardModel]
"""A child card: its name, or the card proxy itself."""


# --------------------------------------------------------------------------- flattening

class Flattener:
    """Turns named root cards (and every card instance reachable from them)
    into the flat ``{name: declaration}`` map sent to the browser."""

    def __init__(self, roots: dict[str, CardModel]):
        self.roots = roots
        self.decls: dict[str, dict[str, Any]] = {}
        self.by_name: dict[str, CardModel] = {}
        self._names: dict[int, str] = {}

    def run(self) -> tuple[dict[str, dict[str, Any]], dict[str, CardModel]]:
        for name, card in self.roots.items():  # explicit names win over derived ones
            self._names.setdefault(id(card), name)
        for name, card in self.roots.items():
            self._card(card, name)
        return self.decls, self.by_name

    def _card(self, card: CardModel, suggested: str) -> str:
        name = self._names.setdefault(id(card), suggested)
        if name in self.by_name:
            if self.by_name[name] is not card:
                raise ValueError(f"two different cards would both be named '{name}'")
            return name  # already emitted (shared or cyclic reference)
        self.by_name[name] = card
        self.decls[name] = {}  # reserve (cycles)
        decl: dict[str, Any] = {"cardType": card.card_type()}
        policy = dict(type(card).__default_events_policy__)
        policy.update(card.events_policy or {})
        if policy:
            decl["$events"] = policy
        decl.update(self._fields(card, name, skip={"events_policy"}))
        self.decls[name] = decl
        return name

    def _fields(self, m: BaseModel, path: str, skip: set[str] = frozenset()) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for fname, finfo in type(m).model_fields.items():
            if fname in skip or finfo.exclude:
                continue
            v = getattr(m, fname)
            if v is None:
                continue
            key = finfo.alias or fname
            out[key] = self._value(v, f"{path}/{key}")
        for k, v in (m.__pydantic_extra__ or {}).items():
            if v is not None:
                out[k] = self._value(v, f"{path}/{k}")
        return out

    def _value(self, v: Any, path: str) -> Any:
        if isinstance(v, CardModel):
            return self._card(v, path)
        if isinstance(v, BaseModel):
            return self._fields(v, path)
        if isinstance(v, enum.Enum):
            return v.value
        if isinstance(v, (list, tuple)):
            return [self._value(x, f"{path}/{i}") for i, x in enumerate(v)]
        if isinstance(v, dict):
            return {str(k): self._value(x, f"{path}/{k}") for k, x in v.items()}
        if isinstance(v, (_dt.datetime, _dt.date)):
            return v.isoformat()
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        if callable(v):
            raise TypeError(f"'{path}': functions cannot be sent to the browser (use an on_* handler)")
        raise TypeError(f"'{path}': value of type {type(v).__name__} is not JSON serialisable")
