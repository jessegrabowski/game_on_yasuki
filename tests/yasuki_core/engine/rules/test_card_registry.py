import subprocess
import sys

from yasuki_core.engine.rules import abilities, economy, triggers
from yasuki_core.engine.rules.card_registry import main, registered_card_ids, unregistered_card_ids

# Registry modules, and the per-card registries in them that card_registry validates. CHOICE_RESOLVERS
# is the one module-level registry deliberately left out: it keys on the kind of a pending choice
# rather than on a card.
REGISTRY_MODULES = (abilities, economy, triggers)
VALIDATED_REGISTRIES = {
    "_ABILITIES",
    "_INVEST",
    "_PRODUCTION_BOOST",
    "GOLD_HANDLERS",
    "RECRUIT_DISCOUNTS",
    "_TRIGGERS",
}
NOT_KEYED_BY_CARD = {"CHOICE_RESOLVERS"}


def module_level_registries() -> set[str]:
    return {
        name
        for module in REGISTRY_MODULES
        for name, value in vars(module).items()
        if isinstance(value, dict) and not name.startswith("__")
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
    assert len(registered_card_ids()) == len(VALIDATED_REGISTRIES)


def test_no_registry_reports_as_empty():
    # An empty frozenset here means card_registry read an attribute that is no longer the registry,
    # which looks exactly like a clean bill of health.
    assert all(registered_card_ids().values())


def test_a_misspelled_id_is_reported_with_its_registry_and_a_suggestion():
    problems = unregistered_card_ids({"abilities": frozenset({"milet_farm"})})

    assert problems == ["abilities: no card has the id 'milet_farm' — did you mean millet_farm?"]


def test_an_id_with_no_near_match_is_still_reported():
    # get_close_matches returns nothing below its similarity cutoff; the id must still be named.
    assert unregistered_card_ids({"triggers": frozenset({"zzzzzzzzzz"})}) == [
        "triggers: no card has the id 'zzzzzzzzzz'"
    ]


def test_no_registries_checks_nothing_rather_than_falling_back():
    # An empty mapping is a caller saying "check these", not "check the defaults". The two answers
    # coincide while the engine's own registries are clean, which is what makes the confusion durable.
    assert unregistered_card_ids({}) == []
    assert unregistered_card_ids({"abilities": frozenset({"milet_farm"})}) != []


def test_the_cli_is_silent_and_succeeds_when_every_id_is_real():
    assert main({"abilities": frozenset({"millet_farm"})}) == 0


def test_the_cli_writes_each_problem_to_stderr_and_fails(capsys):
    # pre-commit shows the developer whatever the hook writes, so the text is the contract, not just
    # the exit code. Two bad ids, because reporting only the first would send someone back for a
    # second round trip.
    registries = {"abilities": frozenset({"milet_farm"}), "triggers": frozenset({"rice_frm"})}

    assert main(registries) == 1
    assert capsys.readouterr().err.splitlines() == unregistered_card_ids(registries)
    assert len(unregistered_card_ids(registries)) == 2
