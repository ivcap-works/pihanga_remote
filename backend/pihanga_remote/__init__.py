"""pihanga-remote: drive a Pihanga card UI from Python.

The browser runs a prebuilt generic bundle (lean runtime + card library). The
UI is a flat map ``{cardName: declaration}`` owned by this backend; changes are
sent as JSON-Patch, events come back over the same WebSocket.
"""

from .card import CardModel, CardRef, EventContext, GenericCard, PropModel
from .options import CDN_BUNDLE, SINGLE_BUNDLE, AppOptions
from .server import DEFAULT_BUNDLE, Hub, create_app, get_hub
from .session import Session

__all__ = [
    "AppOptions", "CardModel", "CardRef", "EventContext", "GenericCard", "Hub", "PropModel", "Session",
    "create_app", "get_hub", "CDN_BUNDLE", "DEFAULT_BUNDLE", "SINGLE_BUNDLE",
]
