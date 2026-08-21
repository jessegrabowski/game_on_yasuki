import json
import subprocess
import sys

import pytest

from yasuki_core.install.yaml_to_sql import card_slug

from tests.yasuki_core.engine.rules.card_modules import (
    CardFunction,
    card_functions,
    card_modules,
    headers,
    registered_ids,
)


@pytest.mark.parametrize("module", card_modules(), ids=lambda path: path.stem)
def test_cards_appear_in_id_order(module):
    # A set module grows to hundreds of lines of independent blocks; alphabetical order is what keeps
    # it navigable, and what stops two people appending the same card in two places.
    ids = list(dict.fromkeys(registered_ids(module)))

    assert ids == sorted(ids)


@pytest.mark.parametrize("module", card_modules(), ids=lambda path: path.stem)
def test_no_card_is_split_across_two_headers(module):
    # The point of the phase: everything a card does sits in one contiguous block. Registrations
    # split across two headers is the scattering this package was built to remove, reappearing
    # inside a single file.
    titles = headers(module)

    assert titles == tuple(dict.fromkeys(titles))


@pytest.mark.parametrize("module", card_modules(), ids=lambda path: path.stem)
def test_every_card_has_a_header(module):
    assert len(headers(module)) == len(set(registered_ids(module)))


@pytest.mark.parametrize("module", card_modules(), ids=lambda path: path.stem)
def test_each_header_names_the_card_beneath_it(module):
    # Counts and ordering all pass with a header that names a different card than the block registers,
    # which is what a copy-pasted block with a half-edited header looks like.
    titled = [card_slug(title) for title in headers(module)]

    assert titled == list(dict.fromkeys(registered_ids(module)))


@pytest.mark.parametrize("module", card_modules(), ids=lambda path: path.stem)
def test_a_cards_registrations_are_contiguous(module):
    # Interleaving two cards' registrations would satisfy the header count while still forcing a
    # reader to hunt: the ids must appear in runs, not alternating.
    ids = registered_ids(module)
    runs = [card_id for index, card_id in enumerate(ids) if index == 0 or ids[index - 1] != card_id]

    assert len(runs) == len(set(runs))


def test_the_source_scan_sees_every_registration_the_engine_holds():
    # The scan matches registration forms from a hand-written list, so a new one — an attachment or
    # combat registry — would leave its cards exempt from every check in this file, silently. The
    # registries are the truth; a card in them the scan cannot find means the list is stale.
    #
    # Read from a fresh interpreter: the registries are module-global, and several test modules
    # register handlers on invented ids as they import.
    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json;"
            "from yasuki_core.engine.rules.card_registry import registered_card_ids;"
            "print(json.dumps(sorted(set().union(*registered_card_ids().values()))))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    at_runtime = set(json.loads(finished.stdout))
    from_source = {card_id for module in card_modules() for card_id in registered_ids(module)}

    assert at_runtime - from_source == set(), "add the new registration form to card_modules.py"


# The jobs a card's handler can hold, spelled the way its name has to end. A handler's name is its
# card's id and one of these, so a card's whole implementation answers a grep for its id and every
# function of a kind answers a grep for its role.
ROLES = frozenset(
    {
        # the three parts of an activated ability
        "cost",
        "targets",
        "effects",
        # the per-registry hooks
        "invest",
        "gold",
        "recruit_discount",
        "invest_discount",
        "keywords",
        "attachment_grant",
        "attach_restriction",
        "production_boost",
        # triggers, named for the event they answer
        "entered_play",
        "destroyed",
        "straightened",
        "turn_started",
        "counter_gained",
        "card_discarded",
        "entered_play_or_destroyed",
    }
)


@pytest.mark.parametrize("module", card_modules(), ids=lambda path: path.stem)
def test_every_handler_is_named_for_its_card_and_its_job(module):
    # One shape, so a card's whole implementation answers a grep for its id and a reader can tell a
    # gold handler from a trigger without opening the registration. Names that read as prose
    # instead — _sasada_calls_her_orochi — say neither which card nor which of the roles they fill.
    offenders = [
        f"{function.card_id}: {function.name}"
        for function in card_functions(module)
        if not _named_conventionally(function)
    ]

    assert offenders == []


def test_the_function_scan_finds_handlers_to_check():
    # Guards the check above twice over. A scan that read no functions passes it without reading a
    # name; so does one that classifies every function as an unregistered helper, since a helper is
    # only asked to carry its card's id and a prose name like _sasada_calls_her_orochi already does.
    scanned = [function for module in card_modules() for function in card_functions(module)]

    assert len(scanned) > 50
    assert sum(function.registered for function in scanned) > 25
    assert any(function.resolves is not None for function in scanned)


def _named_conventionally(function: CardFunction) -> bool:
    """A resolver is named for the choice it resolves, a handler for its card and its role, and a
    helper only has to carry its card's id."""
    if function.resolves is not None:
        return function.name == f"_resolve_{function.resolves}"
    prefix = f"_{function.card_id}_"
    if not function.name.startswith(prefix):
        return False
    return not function.registered or function.name.removeprefix(prefix) in ROLES
