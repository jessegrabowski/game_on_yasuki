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
# numpydoc_xref_param_type references every word of a type field. The first group is English
# our prose type fields use ("dict mapping (deck, era) to str"); the second is our own unions,
# type aliases and TypeVars, which autodoc documents nowhere.
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
    "a",
    "and",
    "deck",
    "era",
    "image",
    "Path",
    "event",
    "card",
    "triggers",
    "date",
    "Intent",
    "GameEvent",
    "WorkItem",
    "Cause",
    "Metric",
    "CardT",
}

# numpydoc_xref_param_type turns every word of a type field into a reference, so a class named by
# its bare name resolves nowhere. These are the ones our docstrings name that way.
numpydoc_xref_aliases = {
    "ACTION_TIMINGS": "yasuki_core.engine.rules.vocabulary.actions.ACTION_TIMINGS",
    "Act": "yasuki_core.engine.replay.game_log.Act",
    "Action": "yasuki_gui.services.actions.Action",
    "ActionRound": "yasuki_core.engine.rules.turn.structure.ActionRound",
    "ActionTiming": "yasuki_core.engine.rules.vocabulary.actions.ActionTiming",
    "Agent": "yasuki_core.bots.agents.Agent",
    "Answer": "yasuki_core.engine.replay.game_log.Answer",
    "AttackPhase": "yasuki_core.engine.rules.battle.records.AttackPhase",
    "AttackView": "yasuki_core.engine.rules.projection.AttackView",
    "BattleDesignator": "yasuki_core.engine.rules.vocabulary.actions.BattleDesignator",
    "BattleOutcome": "yasuki_core.engine.rules.battle.records.BattleOutcome",
    "BattleSegment": "yasuki_core.engine.rules.vocabulary.segments.BattleSegment",
    "BattleView": "yasuki_gui.ui.battle_view.BattleView",
    "BattlefieldCardView": "yasuki_core.engine.redaction.BattlefieldCardView",
    "BattlefieldZone": "yasuki_core.engine.zones.BattlefieldZone",
    "BoardPos": "yasuki_core.engine.table.BoardPos",
    "COLUMN_STEP": "yasuki_gui.layout.COLUMN_STEP",
    "CardPrint": "yasuki_core.game_pieces.prints.CardPrint",
    "ChooseAbilityTarget": "yasuki_core.engine.rules.vocabulary.decisions.ChooseAbilityTarget",
    "ChooseInvestAmount": "yasuki_core.engine.rules.vocabulary.decisions.ChooseInvestAmount",
    "Confirm": "yasuki_core.engine.rules.vocabulary.decisions.Confirm",
    "Controls": "yasuki_core.engine.driver.Controls",
    "Cost": "yasuki_core.engine.rules.abilities.costs.Cost",
    "DecisionRequest": "yasuki_core.engine.rules.vocabulary.decisions.DecisionRequest",
    "DecisionResponse": "yasuki_core.engine.rules.vocabulary.decisions.DecisionResponse",
    "Deck": "yasuki_core.game_pieces.deck.Deck",
    "DeckBuilderRepository": "yasuki_gui.ui.deck_builder.deck_data.DeckBuilderRepository",
    "DeckBuilderWindow": "yasuki_gui.ui.deck_builder.deck_builder.DeckBuilderWindow",
    "DeckCard": "yasuki_core.accounts.decks.DeckCard",
    "DeckKey": "yasuki_core.engine.table.DeckKey",
    "DeckState": "yasuki_gui.ui.deck_builder.deck_data.DeckState",
    "DeckSummary": "yasuki_core.accounts.decks.DeckSummary",
    "Effect": "yasuki_core.engine.rules.effects.Effect",
    "EngineSession": "yasuki_core.engine.session.EngineSession",
    "Event": "yasuki_core.engine.intents.Event",
    "FieldView": "yasuki_gui.field_view.FieldView",
    "FilterOptions": "yasuki_gui.ui.deck_builder.filter_dialog.FilterOptions",
    "GOLD_SELF_GRANT": "yasuki_core.engine.rules.gold.self_grants.GOLD_SELF_GRANT",
    "GameLog": "yasuki_core.engine.replay.game_log.GameLog",
    "GameRunner": "yasuki_gui.services.game_runner.GameRunner",
    "GameState": "yasuki_core.engine.rules.state.GameState",
    "GameView": "yasuki_core.engine.rules.projection.GameView",
    "HiddenCard": "yasuki_core.engine.redaction.HiddenCard",
    "HiddenFace": "yasuki_gui.visuals.cardface.HiddenFace",
    "InitialRecord": "yasuki_core.engine.replay.snapshot.InitialRecord",
    "KeywordGrant": "yasuki_core.engine.rules.vocabulary.modifiers.KeywordGrant",
    "L5RCard": "yasuki_core.game_pieces.cards.L5RCard",
    "LOCAL_DEBUG_OVERRIDE": "yasuki_gui.ui.game_window.LOCAL_DEBUG_OVERRIDE",
    "LobbyModifier": "yasuki_core.engine.rules.vocabulary.modifiers.LobbyModifier",
    "Location": "yasuki_core.engine.table.Location",
    "Minimum": "yasuki_core.engine.rules.vocabulary.modifiers.Minimum",
    "Modifier": "yasuki_core.engine.rules.vocabulary.modifiers.Modifier",
    "Moment": "yasuki_core.engine.rules.turn.structure.Moment",
    "Node": "yasuki_core.search.boolean_query.Node",
    "PayingAgent": "yasuki_core.bots.agents.PayingAgent",
    "Phase": "yasuki_core.engine.rules.turn.structure.Phase",
    "PhaseBar": "yasuki_gui.ui.phase_bar.PhaseBar",
    "PlayerId": "yasuki_core.engine.players.PlayerId",
    "PlayerInfoBox": "yasuki_gui.ui.info_box.PlayerInfoBox",
    "Policy": "yasuki_core.bots.policies.Policy",
    "PromptBox": "yasuki_gui.ui.prompt_box.PromptBox",
    "ProvinceModifier": "yasuki_core.engine.rules.vocabulary.modifiers.ProvinceModifier",
    "ResolvedDeck": "yasuki_core.game_pieces.factory.ResolvedDeck",
    "Rulebook": "yasuki_core.engine.players.Rulebook",
    "SearchTerm": "yasuki_core.search.parse_search.SearchTerm",
    "SeatInfo": "yasuki_core.engine.table.SeatInfo",
    "Segment": "yasuki_core.engine.rules.vocabulary.segments.Segment",
    "Side": "yasuki_core.game_pieces.constants.Side",
    "Stat": "yasuki_core.engine.rules.vocabulary.modifiers.Stat",
    "TableState": "yasuki_core.engine.table.TableState",
    "TriggerContext": "yasuki_core.engine.rules.triggers.TriggerContext",
    "UnitView": "yasuki_core.engine.rules.projection.UnitView",
    "VictoryRule": "yasuki_core.engine.rules.vocabulary.victory.VictoryRule",
    "ViewSnapshot": "yasuki_core.engine.redaction.ViewSnapshot",
    "Zone": "yasuki_core.engine.zones.Zone",
    "ZoneKey": "yasuki_core.engine.table.ZoneKey",
    "effective_gold_production": "yasuki_core.engine.rules.gold.production.effective_gold_production",
    "legacy_key": "yasuki_core.engine.rules.legality.legacy_key",
    "recruit_cost": "yasuki_core.engine.rules.legality.recruit_cost",
    "submit": "yasuki_core.engine.rules.turn.action_sequence.submit",
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
