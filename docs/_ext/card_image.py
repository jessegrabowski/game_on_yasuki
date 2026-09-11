import functools
from collections.abc import Callable
from typing import Any, ClassVar

import yaml
from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.application import Sphinx
from sphinx.util.docutils import SphinxDirective

from yasuki_core import DATABASE_DIR
from yasuki_core.install.card_index import read_index
from yasuki_core.install.yaml_to_sql import card_slug

IMAGES_DIR = DATABASE_DIR / "images"


@functools.cache
def front_images(printing: str) -> dict[str, str]:
    """Map card id to front-image filename for one printing, from its committed manifest."""
    manifest = IMAGES_DIR / f"{printing}.yaml"
    if not manifest.exists():
        return {}
    entries = yaml.safe_load(manifest.read_text(encoding="utf-8")).get("images", [])
    return {
        entry["card_id"]: spec["file"]
        for entry in entries
        for spec in entry.get("files", [])
        if spec.get("role") == "front"
    }


def printings_with_art(card_id: str) -> list[str]:
    """Every printing with a front image of ``card_id``."""
    return sorted(
        manifest.stem
        for manifest in IMAGES_DIR.glob("*.yaml")
        if card_id in front_images(manifest.stem)
    )


class CardImage(SphinxDirective):
    """Show a printed card face, hotlinked, and link it to that card's page."""

    # The printing is required rather than defaulted: most cards have art in several sets, and
    # which face illustrates a point is the page author's call.

    required_arguments = 1
    final_argument_whitespace = True
    option_spec: ClassVar[dict[str, Callable[[str], Any]] | None] = {
        "printing": directives.unchanged_required,
        "width": directives.length_or_percentage_or_unitless,
        "align": lambda argument: directives.choice(argument, ("left", "center", "right")),
        "alt": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        title = self.arguments[0].strip()
        card_id = card_slug(title)
        if card_id not in read_index():
            return [self.warn(f"no card has the id {card_id!r}, derived from {title!r}")]

        printing = self.options.get("printing")
        if not printing:
            return [
                self.warn(f"{title!r} needs a :printing:, one of {printings_with_art(card_id)}")
            ]

        filename = front_images(printing).get(card_id)
        if filename is None:
            known = printings_with_art(card_id)
            detail = f"one of {known}" if known else "and no printing has art for it"
            return [self.warn(f"{printing!r} has no art for {title!r}; {detail}")]

        config = self.env.config
        image = nodes.image(
            uri=f"{config.card_image_base_url}/sets/{printing}/{filename}",
            alt=self.options.get("alt", title),
        )
        if "width" in self.options:
            image["width"] = self.options["width"]
        link = nodes.reference("", "", image, refuri=f"{config.card_base_url}/{card_id}")
        return [nodes.figure("", link, align=self.options.get("align", "center"))]

    def warn(self, message: str) -> nodes.system_message:
        return self.state_machine.reporter.warning(message, line=self.lineno)


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_config_value("card_image_base_url", "", "env", types=frozenset({str}))
    app.add_directive("card-image", CardImage)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
