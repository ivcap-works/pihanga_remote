"""App-level options: page metadata, icon, bundle choice, handler execution."""

from __future__ import annotations

import hashlib
import html
import mimetypes
import re
from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

PACKAGE_DIR = Path(__file__).parent
SINGLE_BUNDLE = PACKAGE_DIR / "static"
"""Single self-contained bundle (runtime + React + shadcn cards in one file)."""
CDN_BUNDLE = PACKAGE_DIR / "static_cdn"
"""Script-tag layout: generic index.html + import map + versioned /pkg/<name>@<version>/ folders."""


class AppOptions(BaseModel):
    """Everything about the page and the server that is not a card.

    ```python
    app = create_app(build, AppOptions(
        title="Fleet monitor",
        description="Live status of the vehicle fleet",
        icon="static/truck.svg",           # file path, http(s) URL or data: URL
        theme_color="#2563eb",
    ))
    ```
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    # ---- <head> of the served index.html ------------------------------------
    title: str = Field("Pihanga", description="Browser tab title (<title>).")
    description: Optional[str] = Field(None, description='<meta name="description">.')
    icon: Optional[Union[Path, str]] = Field(
        None,
        description="Favicon: a local file (served by the app; .svg/.png/.ico/…) or an http(s)/data: URL.",
    )
    lang: str = Field("en", description="<html lang>.")
    theme_color: Optional[str] = Field(None, description='<meta name="theme-color">, e.g. "#2563eb".')
    meta: dict[str, str] = Field(
        default_factory=dict,
        description='Extra <meta name=… content=…> tags, e.g. {"author": "…", "robots": "noindex"}.',
    )
    head_html: Optional[str] = Field(
        None, description="Trusted raw HTML appended to <head> (analytics, fonts, …). NOT escaped."
    )

    # ---- what the browser loads ------------------------------------------------
    bundle: Union[Literal["single", "script-tags"], Path] = Field(
        "single",
        description='"single" (one JS file), "script-tags" (import map + versioned packages) or a directory.',
    )

    # ---- how event handlers run ------------------------------------------------
    sync_handlers: Literal["thread", "loop"] = Field(
        "thread",
        description=(
            "Where plain `def` handlers run. 'thread' (default, like FastAPI's sync endpoints): in a worker "
            "thread, so blocking code does not stall other tabs. 'loop': directly on the event loop."
        ),
    )

    @field_validator("icon")
    @classmethod
    def _check_icon(cls, v: Optional[Union[Path, str]]) -> Optional[Union[Path, str]]:
        if v is None or (isinstance(v, str) and re.match(r"^(https?:|data:)", v)):
            return v
        p = Path(v)
        if not p.is_file():
            raise ValueError(f"icon file not found: {p}")
        return p.resolve()

    # ------------------------------------------------------------------ helpers
    def bundle_dir(self) -> Path:
        if self.bundle == "single":
            return SINGLE_BUNDLE
        if self.bundle == "script-tags":
            return CDN_BUNDLE
        return Path(self.bundle)

    def icon_file(self) -> Optional[Path]:
        return self.icon if isinstance(self.icon, Path) else None

    def icon_url(self) -> Optional[str]:
        if self.icon is None:
            return None
        if isinstance(self.icon, Path):
            digest = hashlib.sha256(self.icon.read_bytes()).hexdigest()[:10]
            return f"/_pihanga/icon-{digest}{self.icon.suffix}"  # content-addressed → cacheable forever
        return self.icon

    def icon_type(self) -> Optional[str]:
        f = self.icon_file()
        if f is None:
            return None
        if f.suffix == ".svg":
            return "image/svg+xml"
        if f.suffix == ".ico":
            return "image/x-icon"
        return mimetypes.guess_type(f.name)[0] or "application/octet-stream"

    def render_index(self, template: str) -> str:
        """Apply title/metadata/icon to the bundle's index.html."""
        e = html.escape
        out = re.sub(r"<html([^>]*)\blang=\"[^\"]*\"", lambda m: f'<html{m.group(1)}lang="{e(self.lang)}"', template, count=1)
        if "<title>" in out:
            out = re.sub(r"<title>.*?</title>", f"<title>{e(self.title)}</title>", out, count=1, flags=re.S)
        tags: list[str] = []
        if "<title>" not in out:
            tags.append(f"<title>{e(self.title)}</title>")
        if self.description:
            tags.append(f'<meta name="description" content="{e(self.description)}" />')
        if self.theme_color:
            tags.append(f'<meta name="theme-color" content="{e(self.theme_color)}" />')
        for k, v in self.meta.items():
            tags.append(f'<meta name="{e(k)}" content="{e(v)}" />')
        url = self.icon_url()
        if url:
            t = f' type="{self.icon_type()}"' if self.icon_type() else ""
            tags.append(f'<link rel="icon" href="{e(url)}"{t} />')
        if self.head_html:
            tags.append(self.head_html)
        if tags:
            out = re.sub(r"\s*</head>", lambda _m: "\n    " + "\n    ".join(tags) + "\n  </head>", out, count=1)
        return out
