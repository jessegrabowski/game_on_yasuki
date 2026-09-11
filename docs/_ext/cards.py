import functools
from typing import Any

from docutils import nodes
from docutils.parsers.rst.states import Inliner
from sphinx.application import Sphinx

from yasuki_core.install.card_index import read_index
from yasuki_core.install.yaml_to_sql import card_slug

CARD_BASE_URL = "https://gameonyasuki.com/card"


@functools.cache
def _known_ids() -> frozenset[str]:
    return read_index()


def card_reference(
    name: str,
    rawtext: str,
    text: str,
    lineno: int,
    inliner: Inliner,
    options: dict[str, Any] | None = None,
    content: list[str] | None = None,
) -> tuple[list[nodes.Node], list[nodes.system_message]]:
    """Link a printed card title to its page on the live site, by derived card id.

    The id is derived rather than written, which is the same rule a card module follows, so a title
    spelled the way the card prints it needs no second spelling here. A title that derives to an id
    no card has is reported: the build runs under ``-W``, so it fails rather than shipping a link
    to a 404.
    """
    slug = card_slug(text)
    if slug not in _known_ids():
        message = inliner.reporter.warning(
            f"no card has the id {slug!r}, derived from {text!r}", line=lineno
        )
        return [nodes.literal(rawtext, text)], [message]

    link = nodes.reference(rawtext, text, refuri=f"{CARD_BASE_URL}/{slug}")
    return [link], []


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_role("card", card_reference)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
