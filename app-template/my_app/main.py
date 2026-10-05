"""A minimal Pihanga app.

    poetry install
    poetry run python -m uvicorn my_app.main:app --reload     → http://localhost:8000
"""

from pathlib import Path  # noqa: F401  (for the icon option below)

from pihanga_remote import AppOptions, Session, create_app
from pihanga_remote.cards.shadcn import Button, PageWithNavbar, SdFramework, Stack, TextField, Typography


def build(s: Session) -> None:
    """Called once per browser tab: declare the cards and wire the handlers."""
    greeting = Typography(level="h2", text="Hello!")
    name = TextField(placeholder="your name", value="")
    count = Typography(level="muted", text="clicked 0 times")
    clicks = 0

    def on_name(ev):  # ev is the generated pydantic payload model
        name.value = ev.value
        greeting.text = f"Hello {ev.value}!" if ev.value else "Hello!"

    def on_click(_ev):
        nonlocal clicks
        clicks += 1
        count.text = f"clicked {clicks} times"

    name.on_changed = on_name
    s.window(
        SdFramework(
            theme="light",
            page=PageWithNavbar(
                title="My App",
                main=Stack(
                    direction="column",
                    spacing=3,
                    content=[greeting, name, Button(label="Click me", on_clicked=on_click), count],
                ),
            ),
        )
    )


app = create_app(
    build,
    AppOptions(
        title="My App",                      # browser tab title
        description="A Pihanga UI driven from Python",
        # icon=Path(__file__).parent / "icon.svg",   # file, http(s) URL or data: URL
        # theme_color="#2563eb",
    ),
)
