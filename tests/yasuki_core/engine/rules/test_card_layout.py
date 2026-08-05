import json
import subprocess
import sys

import pytest

from yasuki_core.install.yaml_to_sql import card_slug

from tests.yasuki_core.engine.rules.card_modules import card_modules, headers, registered_ids


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
