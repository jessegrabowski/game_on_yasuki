import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

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
    "M",
    "N",
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
