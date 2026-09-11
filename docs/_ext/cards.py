import functools
from typing import Any

from docutils import nodes
from docutils.parsers.rst.states import Inliner
from sphinx.application import Sphinx

from yasuki_core.install.card_index import read_index
from yasuki_core.install.yaml_to_sql import card_slug


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

    A title deriving to an id no card has renders as literal text and reports a warning naming both.
    """
    # Derived rather than written out, the same rule a card module follows, so a title spelled the
    # way the card prints it needs no second spelling here.
    slug = card_slug(text)
    if slug not in _known_ids():
        message = inliner.reporter.warning(
            f"no card has the id {slug!r}, derived from {text!r}", line=lineno
        )
        return [nodes.literal(rawtext, text)], [message]

    base = inliner.document.settings.env.config.card_base_url
    return [nodes.reference(rawtext, text, refuri=f"{base}/{slug}")], []


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_config_value("card_base_url", "", "env", types=frozenset({str}))
    app.add_role("card", card_reference)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
