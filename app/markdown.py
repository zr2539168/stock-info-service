from __future__ import annotations

from markupsafe import Markup
from markdown_it import MarkdownIt


_renderer = MarkdownIt("gfm-like", {"breaks": True, "linkify": False})


def render_markdown(value: str | None) -> Markup:
    if not value:
        return Markup("")
    return Markup(_renderer.render(value))
