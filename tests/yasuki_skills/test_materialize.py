from pathlib import Path

import pytest

from yasuki_skills.materialize import DOCS_URL, MaterializeError, materialize

MODULE = '''from yasuki_core.engine import on


# --- Rural Market ---


@on(EnteredPlay, "rural_market")
def _rural_market_entered_play(ctx):
    """Give it a token."""
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


# --- Order ---


def _canonical_order(cards):
    ordered = sorted(cards)
    return ordered
'''


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    """A documentation tree with a source tree beside it, laid out as the repository is."""
    (tmp_path / "src" / "yasuki_core").mkdir(parents=True)
    (tmp_path / "src" / "yasuki_core" / "cards.py").write_text(MODULE, encoding="utf-8")

    root = tmp_path / "docs"
    (root / "contributing").mkdir(parents=True)
    (root / "design").mkdir()

    return root


def written(docs: Path, body: str, name: str = "contributing/page.md") -> Path:
    page = docs / name
    page.write_text(body, encoding="utf-8")

    return page


def render(page: Path, docs: Path, installed: set[str] | None = None) -> str:
    return materialize(
        page,
        docs_root=docs,
        source_root=docs.parent / "src",
        installed=set() if installed is None else installed,
    )


def test_a_whole_object_is_included_with_its_decorator(docs: Path):
    page = written(
        docs,
        "Before.\n\n```{literalinclude} ../../src/yasuki_core/cards.py\n"
        ":pyobject: _rural_market_entered_play\n:language: python\n```\n\nAfter.\n",
    )

    body = render(page, docs)

    assert '@on(EnteredPlay, "rural_market")' in body
    assert "def _rural_market_entered_play(ctx):" in body
    assert "_canonical_order" not in body
    assert body.startswith("Before.")
    assert body.rstrip().endswith("After.")


def test_the_included_text_is_fenced_in_the_declared_language(docs: Path):
    page = written(
        docs,
        "```{literalinclude} ../../src/yasuki_core/cards.py\n"
        ":pyobject: _canonical_order\n:language: python\n```\n",
    )

    assert render(page, docs).startswith("```python\n")


def test_a_line_range_is_taken_inclusively_at_both_markers(docs: Path):
    page = written(
        docs,
        "```{literalinclude} ../../src/yasuki_core/cards.py\n"
        ":start-at: ordered = sorted\n:end-at: return ordered\n```\n",
    )

    body = render(page, docs)

    assert "    ordered = sorted(cards)" in body
    assert "    return ordered" in body
    assert "def _canonical_order" not in body


def test_end_before_stops_short_of_its_marker(docs: Path):
    page = written(
        docs,
        "```{literalinclude} ../../src/yasuki_core/cards.py\n"
        ":start-at: def _canonical_order\n:end-before: return ordered\n```\n",
    )

    body = render(page, docs)

    assert "ordered = sorted(cards)" in body
    assert "return ordered" not in body


def test_a_quoted_marker_matches_the_text_inside_the_quotes(docs: Path):
    # A marker naming a card header holds a "#", which MyST would read as a comment unquoted.
    page = written(
        docs,
        "```{literalinclude} ../../src/yasuki_core/cards.py\n"
        ':start-at: "# --- Rural Market ---"\n:end-before: "# --- Order"\n```\n',
    )

    body = render(page, docs)

    assert "# --- Rural Market ---" in body
    assert "_rural_market_entered_play" in body
    assert "_canonical_order" not in body


def test_dedent_removes_exactly_the_width_asked_for(docs: Path):
    page = written(
        docs,
        "```{literalinclude} ../../src/yasuki_core/cards.py\n"
        ":start-at: ordered = sorted\n:end-at: return ordered\n:dedent: 4\n```\n",
    )

    body = render(page, docs)

    assert "\nordered = sorted(cards)\n" in body
    assert "    ordered" not in body


def test_an_object_that_moved_fails_the_render(docs: Path):
    page = written(
        docs,
        "```{literalinclude} ../../src/yasuki_core/cards.py\n:pyobject: _renamed_since\n```\n",
    )

    with pytest.raises(MaterializeError, match="_renamed_since"):
        render(page, docs)


def test_a_marker_that_no_longer_matches_fails_the_render(docs: Path):
    page = written(
        docs,
        "```{literalinclude} ../../src/yasuki_core/cards.py\n:start-at: gone from the source\n```\n",
    )

    with pytest.raises(MaterializeError, match="gone from the source"):
        render(page, docs)


def test_an_include_of_a_file_that_is_not_there_fails_the_render(docs: Path):
    page = written(docs, "```{literalinclude} ../../src/yasuki_core/absent.py\n```\n")

    with pytest.raises(MaterializeError, match="absent.py"):
        render(page, docs)


def test_an_option_the_renderer_cannot_honor_fails_rather_than_being_dropped(docs: Path):
    """Silently ignoring it would ship a sample that is not the one the page asked for."""
    page = written(
        docs,
        "```{literalinclude} ../../src/yasuki_core/cards.py\n:lines: 1-3\n```\n",
    )

    with pytest.raises(MaterializeError, match="lines"):
        render(page, docs)


def test_a_directive_with_no_rule_fails_the_render(docs: Path):
    page = written(docs, "```{mermaid}\ngraph TD;\n```\n")

    with pytest.raises(MaterializeError, match="mermaid"):
        render(page, docs)


def test_an_autosummary_becomes_the_names_it_lists(docs: Path):
    page = written(
        docs,
        "```{eval-rst}\n.. currentmodule:: yasuki_core.engine.rules.effects\n\n"
        ".. autosummary::\n\n   AdjustCounter\n   Ask\n```\n",
    )

    body = render(page, docs)

    assert "- ``yasuki_core.engine.rules.effects.AdjustCounter``" in body
    assert "- ``yasuki_core.engine.rules.effects.Ask``" in body


def test_a_card_image_becomes_the_card_it_shows(docs: Path):
    page = written(
        docs,
        "```{card-image} Culling Grounds\n:printing: rise_of_otosan_uchi\n:width: 220px\n```\n",
    )

    body = render(page, docs)

    assert "Culling Grounds" in body
    assert "rise_of_otosan_uchi" in body
    assert "220px" not in body


def test_a_toctree_disappears(docs: Path):
    page = written(docs, "Text.\n\n```{toctree}\n:hidden:\n\nadding_a_card\n```\n")

    assert render(page, docs).strip() == "Text."


def test_roles_become_the_text_sphinx_would_show(docs: Path):
    page = written(
        docs,
        "{class}`~.TableState`, {func}`~yasuki_core.engine.rules.triggers.at_cap`, "
        "{class}`.EngineSession` and {card}`Rice Farm`.\n",
    )

    assert render(page, docs).strip() == (
        "``TableState``, ``at_cap``, ``EngineSession`` and Rice Farm."
    )


def test_a_braced_name_inside_code_is_not_a_role(docs: Path):
    """The web API documents ``/api/cards/random/{count}``, which is a URL template."""
    page = written(docs, "| `GET` | `/api/cards/random/{count}` | Random cards |\n")

    assert "{count}" in render(page, docs)


def test_a_link_to_a_page_that_travels_too_stays_relative(docs: Path):
    page = written(docs, "See [the guide](../design/engine.md).\n")

    body = render(page, docs, installed={"design/engine.md", "contributing/page.md"})

    assert "](../design/engine.md)" in body


def test_a_link_to_a_page_left_behind_points_at_the_hosted_site(docs: Path):
    page = written(docs, "See [the guide](../design/engine.md).\n")

    body = render(page, docs, installed={"contributing/page.md"})

    assert f"]({DOCS_URL}design/engine.html)" in body


def test_a_link_anchor_survives_the_rewrite(docs: Path):
    page = written(docs, "See [the hooks](../design/engine.md#hooks).\n")

    body = render(page, docs, installed=set())

    assert f"]({DOCS_URL}design/engine.html#hooks)" in body


def test_an_installed_package_resolves_includes_without_a_src_directory(tmp_path: Path):
    """A wheel has no src/, so the include path has to be reachable from the package itself."""
    packaged = tmp_path / "site-packages"
    (packaged / "yasuki_core").mkdir(parents=True)
    (packaged / "yasuki_core" / "cards.py").write_text(MODULE, encoding="utf-8")

    docs = packaged / "yasuki_skills" / "docs"
    (docs / "contributing").mkdir(parents=True)
    page = docs / "contributing" / "page.md"
    page.write_text(
        "```{literalinclude} ../../src/yasuki_core/cards.py\n:pyobject: _canonical_order\n```\n",
        encoding="utf-8",
    )

    body = materialize(page, docs, packaged, set())

    assert "def _canonical_order(cards):" in body


def test_a_whole_file_is_included_when_no_bounds_are_given(docs: Path):
    page = written(docs, "```{literalinclude} ../../src/yasuki_core/cards.py\n```\n")

    body = render(page, docs)

    assert "_rural_market_entered_play" in body
    assert "_canonical_order" in body


def test_start_after_begins_below_its_marker(docs: Path):
    page = written(
        docs,
        "```{literalinclude} ../../src/yasuki_core/cards.py\n"
        ":start-after: def _canonical_order\n:end-at: return ordered\n```\n",
    )

    body = render(page, docs)

    assert "def _canonical_order" not in body
    assert "ordered = sorted(cards)" in body


def test_an_admonition_keeps_its_text(docs: Path):
    page = written(docs, "```{note}\nThe database is a cache.\n```\n")

    assert render(page, docs).strip() == "**Note:** The database is a cache."


def test_a_link_out_of_the_documentation_tree_is_left_as_written(docs: Path):
    """It names a repository file, which the hosted site does not serve either."""
    page = written(docs, "See [the licence](../../LICENSE.md).\n")

    assert render(page, docs).strip() == "See [the licence](../../LICENSE.md)."


def test_an_option_naming_no_text_fails_the_render(docs: Path):
    page = written(docs, "```{literalinclude} ../../src/yasuki_core/cards.py\n:start-at:\n```\n")

    with pytest.raises(MaterializeError, match="start-at"):
        render(page, docs)


def test_an_empty_end_marker_fails_the_render(docs: Path):
    page = written(
        docs,
        "```{literalinclude} ../../src/yasuki_core/cards.py\n"
        ":start-at: def _canonical_order\n:end-before:\n```\n",
    )

    with pytest.raises(MaterializeError, match="end-before"):
        render(page, docs)
