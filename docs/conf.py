import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent / "_ext"))

project = "Game on, Yasuki!"
author = "Jesse Grabowski"
copyright = "%Y, Jesse Grabowski"


def _resolve_release() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("game-on-yasuki")
    except PackageNotFoundError:
        return "0.0.0"


release = _resolve_release()
version = release.split("+")[0]

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.mathjax",
    "sphinx.ext.viewcode",
    "numpydoc",
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
    "cards",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# -- Markdown (MyST) ---------------------------------------------------------
source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "substitution",
    "tasklist",
]
myst_heading_anchors = 3

# -- the {card} role ---------------------------------------------------------
# Where a card title links to. The role derives the id and checks it against the committed
# card-id index, so a title naming no card fails the -W build rather than linking to a 404.
card_base_url = "https://gameonyasuki.com/card"

# -- autodoc / autosummary ---------------------------------------------------
autosummary_generate = True
autodoc_typehints = "none"
autoclass_content = "class"
add_module_names = False

# -- numpydoc ----------------------------------------------------------------
# show_class_members=False: members are listed by the autosummary class
# template, so let numpydoc skip its own (duplicated) member table.
numpydoc_show_class_members = False
numpydoc_xref_param_type = True
numpydoc_xref_ignore = {
    "of",
    "or",
    "optional",
    "default",
    "type",
    "scalar",
    "instance",
    "sequence",
    "mapping",
    "path",
    "subclass",
    "to",
    "M",
    "N",
}

# numpydoc_xref_param_type turns every word of a type field into a reference, so a class named by
# its bare name resolves nowhere. These are the ones our docstrings name that way.
numpydoc_xref_aliases = {
    "Action": "yasuki_gui.services.actions.Action",
    "Agent": "yasuki_core.bots.agents.Agent",
    "EngineSession": "yasuki_core.engine.session.EngineSession",
    "GameRunner": "yasuki_gui.services.game_runner.GameRunner",
    "GameState": "yasuki_core.engine.rules.state.GameState",
    "GameView": "yasuki_core.engine.rules.projection.GameView",
    "L5RCard": "yasuki_core.game_pieces.cards.L5RCard",
    "Metric": "yasuki_core.sim.metrics.Metric",
    "PayingAgent": "yasuki_core.bots.agents.PayingAgent",
    "PlayerId": "yasuki_core.engine.players.PlayerId",
    "Policy": "yasuki_core.bots.policies.Policy",
}

# -- HTML output (pydata-sphinx-theme) ---------------------------------------
html_theme = "pydata_sphinx_theme"
html_title = "Game on, Yasuki!"
html_static_path = ["_static"]
html_theme_options = {
    "secondary_sidebar_items": ["page-toc", "sourcelink"],
    "show_prev_next": True,
    "header_links_before_dropdown": 5,
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/jessegrabowski/game-on-yasuki",
            "icon": "fa-brands fa-github",
        }
    ],
}
html_sidebars = {"**": ["sidebar-nav-bs", "searchbox"]}
html_context = {
    "github_url": "https://github.com",
    "github_user": "jessegrabowski",
    "github_repo": "game-on-yasuki",
    "github_version": "main",
    "doc_path": "docs/",
    "default_mode": "auto",
}

# -- Intersphinx -------------------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest", None),
}

# What nitpicky may not complain about. Every entry is a target no docstring can make resolve.
nitpick_ignore_regex = [
    # Third-party and stdlib types. Each would need another inventory fetched on every build to
    # resolve ten-odd references, which is not worth the build time or the network dependency.
    # `pathlib._local` is a 3.13 quirk: `pathlib.Path` resolves to the private module it now lives
    # in, which the python inventory does not carry.
    ("py:.*", r"pathlib\._local\..*"),
    ("py:.*", r"psycopg\..*"),
    ("py:.*", r"numpy\..*"),
    ("py:.*", r"tk\..*"),
    ("py:.*", r"PIL(\..*)?"),
    ("py:.*", r"PhotoImage"),
    # A TypeVar rendered into Deck's generic signature. It is a parameter, not a documented class.
    ("py:class", r"CardT"),
    # autodoc renders a dataclass annotation such as `clans: tuple[str, ...]` verbatim, and
    # numpydoc_xref_param_type splits it on the comma, so the target is the unclosed fragment
    # `tuple[str`.
    ("py:class", r"[^\]]*\[[^\]]*"),
]
