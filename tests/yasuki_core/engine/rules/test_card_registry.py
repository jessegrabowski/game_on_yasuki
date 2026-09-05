import pathlib
import subprocess
import sys

from yasuki_core.engine.rules import (
    abilities,
    attachments,
    cards,
    economy,
    equip,
    policies,
    state_rules,
    triggers,
)
from yasuki_core.engine.rules import card_registry
from yasuki_core.engine.rules.card_registry import (
    card_keyed_data,
    duplicate_registrations,
    main,
    registered_card_ids,
    unregistered_card_ids,
)
from yasuki_core.engine.rules.events import EnteredPlay

# Registry modules, and the per-card registries in them that card_registry validates. CHOICE_RESOLVERS
# and CHOICE_PROMPTS are deliberately left out: both key on the kind of a pending choice rather than
# on a card. CHOICE_PROMPTS lives in decisions and is visible here only because triggers imports it
# to register into. POLICIES is the policy registry, keyed by policy name rather than by card.
REGISTRY_MODULES = (abilities, attachments, economy, equip, policies, state_rules, triggers)
VALIDATED_REGISTRIES = {
    "_ABILITIES",
    "MAY_REMAIN_BOWED",
    "BOW_WAIVERS",
    "LOBBY_BARS",
    "MAY_NOT_LOBBY",
    "FAVOR_PAYERS",
    "_INVEST",
    "_ENTERS_UNBOWED",
    "GOLD_HANDLERS",
    "LOBBY_BONUSES",
    "GOLD_SELF_GRANT",
    "RECRUIT_DISCOUNTS",
    "INVEST_DISCOUNTS",
    "KEYWORD_GRANTS",
    "PROVINCE_STRENGTH_GRANTS",
    "ABILITY_HEURISTICS",
    "CHI_DEATH_EXEMPT",
    "ATTACHMENT_GRANTS",
    "ATTACH_RESTRICTIONS",
    "_TRIGGERS",
}
NOT_KEYED_BY_CARD = {"CHOICE_RESOLVERS", "CHOICE_PROMPTS", "POLICIES"}


def module_level_registries() -> set[str]:
    """Every per-card registry the registry modules hold. Any collection counts, not only dicts: a
    registry recording a card's permission rather than its handler is still a place a misspelled id
    can hide, and a frozenset hides one as well as a set does."""
    return {
        name
        for module in REGISTRY_MODULES
        for name, value in vars(module).items()
        if isinstance(value, dict | set | frozenset) and not name.startswith("__")
    }


def test_every_registered_handler_names_a_real_card():
    # A handler keyed on a misspelled id registers, never fires, and raises nothing. This is the only
    # thing standing between that and a silently dead card.
    #
    # Run out of process, and via the same entry point the pre-commit hook uses: the registries are
    # module-global and several test modules register handlers on invented ids as they import, so an
    # in-process check would see their leavings rather than the shipped registrations.
    finished = subprocess.run(
        [sys.executable, "-m", "yasuki_core.engine.rules.card_registry"],
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0, finished.stderr


def test_no_per_card_registry_escapes_validation():
    # The failure this guards is a registry added to the engine and never wired into the check: it
    # would be validated by nothing, and every other test here would still pass. Discovering the
    # registries rather than listing them is what makes the new one visible.
    discovered = module_level_registries()

    assert discovered - VALIDATED_REGISTRIES == NOT_KEYED_BY_CARD
    assert VALIDATED_REGISTRIES - discovered == set()
    assert len(registered_card_ids()) + len(card_keyed_data()) == len(VALIDATED_REGISTRIES)


def test_card_keyed_data_is_validated_but_kept_out_of_the_layout_scan():
    # These ids name cards but no set module registers them — a card excepted from a rulebook rule
    # is listed beside the rule. Folded into registered_card_ids() they would read as registrations
    # the source scan cannot find, and that guard would fail for a card that is behaving correctly.
    assert card_keyed_data().keys().isdisjoint(registered_card_ids())
    assert unregistered_card_ids(card_keyed_data()) == []


# Registries that exist before the first card that registers into one. Listing them keeps the
# emptiness guard below meaningful for every other registry; drop an entry when its first card
# lands. "lobby bars" waits on the cards that forbid a player to Lobby.
KNOWINGLY_EMPTY: set[str] = set()


def test_no_registry_reports_as_empty():
    # An empty frozenset here means card_registry read an attribute that is no longer the registry,
    # which looks exactly like a clean bill of health. The data lists answer to it too — one emptied
    # by a rename would report every card in it as validated.
    populated = {
        name: ids for name, ids in registered_card_ids().items() if name not in KNOWINGLY_EMPTY
    }
    assert all(populated.values())
    assert all(card_keyed_data().values())
    assert KNOWINGLY_EMPTY <= registered_card_ids().keys(), "a listed registry no longer exists"


def test_a_misspelled_id_is_reported_with_its_registry_and_a_suggestion():
    problems = unregistered_card_ids({"abilities": frozenset({"milet_farm"})})

    assert problems == ["abilities: no card has the id 'milet_farm' — did you mean millet_farm?"]


def test_an_id_with_no_near_match_is_still_reported():
    # get_close_matches returns nothing below its similarity cutoff; the id must still be named.
    assert unregistered_card_ids({"triggers": frozenset({"zzzzzzzzzz"})}) == [
        "triggers: no card has the id 'zzzzzzzzzz'"
    ]


def a_trigger(ctx):
    return []


def another_trigger(ctx):
    return []


def test_a_trigger_registered_twice_for_one_card_is_reported():
    # _TRIGGERS appends rather than overwrites, so the duplicate does not shadow the original — both
    # fire, and the card's effect happens twice.
    problems = duplicate_registrations({EnteredPlay: {"millet_farm": [a_trigger, a_trigger]}})

    assert problems == [
        "triggers: millet_farm registers a_trigger for EnteredPlay 2 times",
    ]


def test_two_different_triggers_on_one_card_are_legitimate():
    # A card may react to the same event in two ways; only the *same* handler twice is the defect.
    assert (
        duplicate_registrations({EnteredPlay: {"millet_farm": [a_trigger, another_trigger]}}) == []
    )


def test_the_same_trigger_on_two_cards_is_legitimate():
    # Shared helpers are registered for many cards on purpose.
    registry = {EnteredPlay: {"millet_farm": [a_trigger], "modest_farm": [a_trigger]}}

    assert duplicate_registrations(registry) == []


def test_no_registries_checks_nothing_rather_than_falling_back():
    # An empty mapping is a caller saying "check these", not "check the defaults". The two answers
    # coincide while the engine's own registries are clean, which is what makes the confusion durable.
    assert unregistered_card_ids({}) == []
    assert unregistered_card_ids({"abilities": frozenset({"milet_farm"})}) != []


def test_the_cli_is_silent_and_succeeds_when_every_id_is_real():
    assert main({"abilities": frozenset({"millet_farm"})}) == 0


def test_the_cli_writes_each_problem_to_stderr_and_fails(capsys):
    # pre-commit shows the developer whatever the hook writes, so the text is the contract, not just
    # the exit code. Reporting only the first would send someone back for a second round trip.
    #
    # Both kinds of problem, because the CLI is where they are joined and a dropped half would
    # otherwise go unnoticed while the engine happens to be clean.
    registries = {"abilities": frozenset({"milet_farm"}), "triggers": frozenset({"rice_frm"})}
    trigger_registry = {EnteredPlay: {"millet_farm": [a_trigger, a_trigger]}}
    expected = unregistered_card_ids(registries) + duplicate_registrations(trigger_registry)

    assert main(registries, trigger_registry) == 1
    assert capsys.readouterr().err.splitlines() == expected
    assert len(expected) == 3


def test_every_card_module_is_imported_by_the_package():
    # cards/__init__.py lists its modules by hand rather than walking the directory, so a new set
    # module added without its import line registers nothing. That failure is otherwise only visible
    # if the new cards happen to have tests.
    package = pathlib.Path(cards.__file__).parent
    on_disk = {path.stem for path in package.glob("*.py")} - {"__init__"}
    imported = {name for name in vars(cards) if not name.startswith("__")}

    assert on_disk - imported == set(), "add these to cards/__init__.py"


def test_printed_ability_count_reads_the_designators_a_card_spells_out():
    """Two abilities in one text run, split by the sentence between them — the shape Outer Walls
    prints and the one a `<br>`-only split would miss."""
    text = (
        "<b>Battle:</b> Even if you control no units at the current battlefield: Give its province "
        "+3 strength. <b>Reaction:</b> After a Ranged Attack is targeted: Give it -2 strength."
    )

    assert card_registry.printed_ability_count(text) == 2


def test_a_colon_inside_an_abilitys_prose_does_not_head_a_second_one():
    """Moto Ikarichi prints "if your Wind is The Kanpeki Dynasty:" mid-sentence. A designator only
    counts where an ability could start."""
    text = (
        "Invest :g2:, or :g0: if your Wind is The Kanpeki Dynasty: Create and attach a 2F "
        "Nonhuman Follower to Ikarichi."
    )

    assert card_registry.printed_ability_count(text) == 0


def test_a_qualified_designator_still_heads_an_ability():
    """ "Absent Battle", "Tireless Response", "Economic Open" — the qualifiers stack ahead of the
    designator and the ability is still an ability."""
    text = "<b>Tireless Response:</b> Straighten a unit.<br><b>Absent Battle:</b> Bow a Follower."

    assert card_registry.printed_ability_count(text) == 2


# The cards shipping with fewer abilities registered than they print. Each behaves correctly in the
# half that is registered, which is why nothing else catches them. Shrinking this list is the fix;
# growing it means a card was implemented incompletely.
KNOWN_SHORT = {"man_the_walls", "outer_walls", "verdant_wilds"}


def test_no_card_beyond_the_known_three_registers_less_than_it_prints():
    reported = {line.split()[1] for line in card_registry.short_ability_registrations()}

    assert reported == KNOWN_SHORT
