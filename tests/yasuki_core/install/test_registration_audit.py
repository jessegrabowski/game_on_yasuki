import pathlib
import subprocess
import sys


from yasuki_core.engine.rules import cards
from yasuki_core.install import registration_audit
from yasuki_core.install.card_index import read_index
from yasuki_core.install.registration_audit import (
    unprinted_registrations,
    mislabeled_abilities,
    unvalidated_registries,
    card_keyed_data,
    duplicate_registrations,
    main,
    registered_card_ids,
    unregistered_back_faces,
    unregistered_card_ids,
)
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.rulebook.proxies import RULEBOOK_PROXY_PRINTS
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.triggers import Registration
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
# lands. "no enlightenment" waits on the Dark Rings and Legacy of Fudo, the Rings that do not
# count toward Enlightenment. "focus effect" waits on the first card with an "As a Focus Effect"
# trait.
KNOWINGLY_EMPTY: set[str] = {"focus effect", "no enlightenment"}


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


def test_a_rulebook_proxy_is_known_without_a_catalog_record():
    assert not RULEBOOK_PROXY_PRINTS.keys() & read_index()
    assert unregistered_card_ids({"abilities": frozenset(RULEBOOK_PROXY_PRINTS)}) == []


def test_a_misspelled_id_is_reported_with_its_registry_and_a_suggestion():
    problems = unregistered_card_ids({"abilities": frozenset({"milet_farm"})})

    assert problems == ["abilities: no card has the id 'milet_farm'. Did you mean millet_farm?"]


def test_an_implemented_front_with_an_unregistered_back_is_reported():
    known = frozenset({"kyuden", "kyuden__back", "farm"})
    registries = {"abilities": frozenset({"kyuden", "farm"})}

    problems = unregistered_back_faces(registries, known)

    assert problems == ["kyuden is implemented but its back face kyuden__back is not"]


def test_a_back_registered_in_any_registry_satisfies_the_check():
    known = frozenset({"kyuden", "kyuden__back"})
    registries = {"abilities": frozenset({"kyuden"}), "stat grants": frozenset({"kyuden__back"})}

    assert unregistered_back_faces(registries, known) == []


def test_a_back_the_engine_cannot_model_yet_is_not_reported():
    known = frozenset(
        {"the_palatial_estate_of_the_crane", "the_palatial_estate_of_the_crane__back"}
    )
    registries = {"abilities": frozenset({"the_palatial_estate_of_the_crane"})}

    assert unregistered_back_faces(registries, known) == []


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


def _registered(trigger) -> Registration:
    return Registration(trigger, None)


def test_a_trigger_registered_twice_for_one_card_is_reported():
    # _TRIGGERS appends rather than overwrites, so the duplicate does not shadow the original and
    # both fire, and the card's effect happens twice.
    registry = {
        EnteredPlay: {CardLocation.BATTLEFIELD: {"millet_farm": [_registered(a_trigger)] * 2}}
    }

    assert duplicate_registrations(registry) == [
        "triggers: millet_farm registers a_trigger for EnteredPlay 2 times in the battlefield",
    ]


def test_the_same_trigger_under_two_rulesets_is_legitimate():
    # A card whose text differs between arcs registers once per ruleset, and no ruleset reads both.
    scoped = [Registration(a_trigger, "onyx"), Registration(a_trigger, "shattered_empire")]
    registry = {EnteredPlay: {CardLocation.BATTLEFIELD: {"millet_farm": scoped}}}

    assert duplicate_registrations(registry) == []


def test_a_trigger_for_every_arc_and_again_under_one_is_reported():
    twice_under_onyx = [Registration(a_trigger, None), Registration(a_trigger, "onyx")]
    registry = {EnteredPlay: {CardLocation.BATTLEFIELD: {"millet_farm": twice_under_onyx}}}

    assert duplicate_registrations(registry) == [
        "triggers: millet_farm registers a_trigger for EnteredPlay 2 times in the battlefield",
    ]


def test_two_different_triggers_on_one_card_are_legitimate():
    # A card may react to the same event in two ways; only the *same* handler twice is the defect.
    registry = {
        EnteredPlay: {
            CardLocation.BATTLEFIELD: {
                "millet_farm": [_registered(a_trigger), _registered(another_trigger)]
            }
        }
    }

    assert duplicate_registrations(registry) == []


def test_the_same_trigger_on_two_cards_is_legitimate():
    # Shared helpers are registered for many cards on purpose.
    in_play = {
        "millet_farm": [_registered(a_trigger)],
        "modest_farm": [_registered(another_trigger)],
    }
    registry = {EnteredPlay: {CardLocation.BATTLEFIELD: in_play}}

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
    trigger_registry = {
        EnteredPlay: {CardLocation.BATTLEFIELD: {"millet_farm": [_registered(a_trigger)] * 2}}
    }
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


def _unlabeled(
    *,
    timings: tuple[ActionTiming, ...] = (ActionTiming.LIMITED,),
    printed_index: int = 0,
) -> Ability:
    return Ability(
        timings=timings,
        cost=no_cost,
        targets=lambda game, source: [],
        effects=lambda game, source, target: [],
        printed_index=printed_index,
    )


def _unprinted(**abilities) -> list[str]:
    return unprinted_registrations(abilities=abilities, interrupts={})


def test_an_index_on_a_printed_ability_of_the_right_designator_passes():
    # Banish All Shadows prints one Kiho Limited ability.
    assert _unprinted(banish_all_shadows=[_unlabeled()]) == []


def test_an_index_past_what_the_card_prints_is_reported():
    assert _unprinted(banish_all_shadows=[_unlabeled(printed_index=1)]) == [
        "abilities: banish_all_shadows names printed ability 1, and its text prints 1"
    ]


def test_an_index_on_an_ability_of_another_designator_is_reported():
    assert _unprinted(banish_all_shadows=[_unlabeled(timings=(ActionTiming.BATTLE,))]) == [
        "abilities: banish_all_shadows names printed ability 0, which is Limited where the "
        "registration is Battle"
    ]


def test_a_labeled_registration_names_no_printed_ability_and_is_not_judged():
    labeled = Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Put this Event into play",
        cost=no_cost,
        targets=lambda game, source: [],
        effects=lambda game, source, target: [],
        printed_index=7,
    )

    assert _unprinted(banish_all_shadows=[labeled]) == []


def test_every_shipped_registration_names_an_ability_its_card_prints():
    assert unprinted_registrations() == []


def _battle_ability(
    *,
    timings: tuple[ActionTiming, ...] = (ActionTiming.BATTLE,),
    keywords: frozenset[str] = frozenset(),
) -> Ability:
    return Ability(
        timings=timings,
        label="",
        cost=no_cost,
        targets=lambda game, source: [],
        effects=lambda game, source, target: [],
        keywords=keywords,
    )


def test_an_ability_registered_without_its_printed_keyword_is_reported():
    # Inexplicable Challenge prints "Political Battle:". A registration that leaves Political off
    # would make "if the action was Political" silently false for it.
    problems = mislabeled_abilities(abilities={"inexplicable_challenge": [_battle_ability()]})

    assert problems == [
        "abilities: inexplicable_challenge registers keywords none on its Battle ability, "
        "whose text prints Political"
    ]


def test_an_ability_registered_as_its_card_prints_passes():
    labeled = _battle_ability(keywords=frozenset({keywords.POLITICAL}))

    assert mislabeled_abilities(abilities={"inexplicable_challenge": [labeled]}) == []


def test_an_ability_the_text_does_not_print_is_not_judged():
    # Rout prints one Battle ability and nothing under Open, so an Open registration has no printed
    # ability to disagree with.
    unprinted = _battle_ability(timings=(ActionTiming.OPEN,))

    assert mislabeled_abilities(abilities={"rout": [unprinted]}) == []


def test_half_of_a_printed_battle_open_is_judged_against_the_whole():
    # Heart of Honor prints "Bushido Virtue Battle/Open". A registration of its Open half alone
    # still has to carry the keyword.
    half = _battle_ability(timings=(ActionTiming.OPEN,))

    assert mislabeled_abilities(abilities={"heart_of_honor": [half]}) == [
        "abilities: heart_of_honor registers keywords none on its Open ability, "
        "whose text prints Bushido Virtue"
    ]


def test_an_in_play_ability_registered_repeatable_against_its_text_is_reported():
    # Inexplicable Challenge prints no Repeatable, and a Strategy from hand is never rationed, so
    # the check reads only an ability registered as acting from play.
    in_play = _battle_ability(keywords=frozenset({keywords.POLITICAL}))
    repeating = Ability(
        timings=in_play.timings,
        label="",
        cost=no_cost,
        targets=in_play.targets,
        effects=in_play.effects,
        keywords=in_play.keywords,
        repeatable=True,
    )

    assert mislabeled_abilities(abilities={"inexplicable_challenge": [repeating]}) == [
        "abilities: inexplicable_challenge registers its Battle ability as Repeatable, "
        "and its text does not print it"
    ]
