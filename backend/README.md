# pihanga-remote

Drive a [Pihanga](https://github.com/ivcap-works/pihanga-core) card UI from Python.

The package contains:
- a prebuilt browser bundle: the lean runtime plus the `@pihanga2/shadcn` cards;
- typed pydantic classes for every card (`pihanga_remote.cards.shadcn`);
- a FastAPI server that serves the bundle and keeps each browser tab in sync over a WebSocket, using JSON Patch.

You don't need any JavaScript tooling to use it.

```python
from pihanga_remote import create_app
from pihanga_remote.cards.shadcn import SdFramework, Stack, Typography, Button

def build(s):                                  # called once per browser tab
    count = Typography(text="0", level="h2")
    def inc(ev):
        count.text = str(int(count.text) + 1)  # mutate the card; the browser is patched
    s.window(SdFramework(page=Stack(direction="column",
                                    content=[count, Button(label="+", on_clicked=inc)])))

app = create_app(build)                        # python -m uvicorn mymodule:app
```

See the project README for the protocol, the design, and how to build an app.
