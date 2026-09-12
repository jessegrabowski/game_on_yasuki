import pathlib
import subprocess
import sys


from yasuki_core.engine.rules import cards
from yasuki_core.install import registration_audit
from yasuki_core.install.registration_audit import (
    unvalidated_registries,
    card_keyed_data,
    duplicate_registrations,
    main,
    registered_card_ids,
    unregistered_card_ids,
)
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay


def test_every_registered_handler_names_a_real_card():
    # A handler keyed on a misspelled id registers, never fires, and raises nothing. This is the
    # only thing standing between that and a silently dead card.
    #
    # Run out of process, and via the same entry point the pre-commit hook uses: the registries are
    # module-global and several test modules register handlers on invented ids as they import, so an
    # in-process check would see their leavings rather than the shipped registrations.
    finished = subprocess.run(
        [sys.executable, "-m", "yasuki_core.install.registration_audit"],
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0, finished.stderr


def test_card_keyed_data_is_validated_but_kept_out_of_the_layout_scan():
    # These ids name cards, but no set module registers them, and a card excepted from a rulebook
    # rule is listed beside the rule. Folded into registered_card_ids() they would read as
    # registrations the source scan cannot find, and that guard would fail for a card that is
    # behaving correctly.
    assert card_keyed_data().keys().isdisjoint(registered_card_ids())
    assert unregistered_card_ids(card_keyed_data()) == []


# Registries that exist before the first card that registers into one. Listing them keeps the
# emptiness guard below meaningful for every other registry; drop an entry when its first card
# lands. "lobby bars" waits on the cards that forbid a player to Lobby.
KNOWINGLY_EMPTY: set[str] = set()


def test_no_registry_reports_as_empty():
    # An empty frozenset here means registration_audit read an attribute that is no longer the
    # registry, which looks exactly like a clean bill of health. The data lists answer to it too
    # and one emptied by a rename would report every card in it as validated.
    populated = {
        name: ids for name, ids in registered_card_ids().items() if name not in KNOWINGLY_EMPTY
    }
    assert all(populated.values())
    assert all(card_keyed_data().values())
    assert KNOWINGLY_EMPTY <= registered_card_ids().keys(), "a listed registry no longer exists"


def test_a_misspelled_id_is_reported_with_its_registry_and_a_suggestion():
    problems = unregistered_card_ids({"abilities": frozenset({"milet_farm"})})

    assert problems == ["abilities: no card has the id 'milet_farm'. Did you mean millet_farm?"]


def test_an_id_with_no_near_match_is_still_reported():
    # get_close_matches returns nothing below its similarity cutoff; the id must still be named.
    assert unregistered_card_ids({"triggers": frozenset({"zzzzzzzzzz"})}) == [
        "triggers: no card has the id 'zzzzzzzzzz'"
    ]


def test_the_attack_strength_registry_is_validated():
    # The named instance of the guard above, kept because this is the registry that was actually
    # missed: it lives in effects.py among the effect dataclasses rather than beside the read that
    # consults it, so nothing walking the registry modules ever reached it.
    assert registered_card_ids()["attack strength"]


def a_trigger(ctx):
    return []


def another_trigger(ctx):
    return []


def test_a_trigger_registered_twice_for_one_card_is_reported():
    # _TRIGGERS appends rather than overwrites, so the duplicate does not shadow the original and
    # both fire, and the card's effect happens twice.
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


def test_a_registry_no_check_reads_is_reported():
    # A plain dict keyed by card id is validated by nothing: unregistered_card_ids iterates the
    # registries it is handed, so one it has never heard of contributes no ids and reports no
    # problems. The card behind a misspelled key in it would be silently dead.
    problems = unvalidated_registries({"_SNEAKY_REGISTRY"})

    assert len(problems) == 1
    assert "_SNEAKY_REGISTRY" in problems[0]


def test_a_registry_already_classified_is_not_reported():
    # Both classifications count: one the audit validates by name, and one that keys on something
    # other than a card and is exempt on purpose.
    assert unvalidated_registries({"_ABILITIES", "CHOICE_RESOLVERS"}) == []


def test_no_registries_checks_nothing_rather_than_falling_back():
    # An empty mapping is a caller saying "check these", not "check the defaults". The two answers
    # coincide while the engine's own registries are clean, which is what makes the confusion
    # durable.
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
    """Two abilities in one text run, split by the sentence between them and the shape Outer Walls
    prints and the one a `<br>`-only split would miss."""
    text = (
        "<b>Battle:</b> Even if you control no units at the current battlefield: Give its province "
        "+3 strength. <b>Reaction:</b> After a Ranged Attack is targeted: Give it -2 strength."
    )

    assert registration_audit.printed_ability_count(text) == 2


def test_a_colon_inside_an_abilitys_prose_does_not_head_a_second_one():
    """Moto Ikarichi prints "if your Wind is The Kanpeki Dynasty:" mid-sentence. A designator only
    counts where an ability could start."""
    text = (
        "Invest :g2:, or :g0: if your Wind is The Kanpeki Dynasty: Create and attach a 2F "
        "Nonhuman Follower to Ikarichi."
    )

    assert registration_audit.printed_ability_count(text) == 0


def test_a_qualified_designator_still_heads_an_ability():
    """ "Absent Battle", "Tireless Response", "Economic Open" and the qualifiers stack ahead of the
    designator and the ability is still an ability."""
    text = "<b>Tireless Response:</b> Straighten a unit.<br><b>Absent Battle:</b> Bow a Follower."

    assert registration_audit.printed_ability_count(text) == 2


# The cards shipping with fewer abilities registered than they print. Each behaves correctly in the
# half that is registered, which is why nothing else catches them. Shrinking this list is the fix;
# growing it means a card was implemented incompletely.
KNOWN_SHORT = {"man_the_walls", "outer_walls", "verdant_wilds"}

# Cards the count cannot see whole, rather than cards implemented in half. Commanding Favor's
# Interrupt pays a Favor cost, which is registered as a Favor payer instead of as an activated
# ability, so the scan finds one ability where the card prints two.
COUNTED_SHORT = {"commanding_favor"}


def test_no_card_registers_less_than_it_prints_but_the_known_few():
    reported = {line.split()[1] for line in registration_audit.short_ability_registrations()}

    assert reported == KNOWN_SHORT | COUNTED_SHORT
