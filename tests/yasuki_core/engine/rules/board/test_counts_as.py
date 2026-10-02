import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.counts_as import (
    COUNTS_AS,
    RULEBOOK,
    AskedBy,
    Asking,
    CountsAs,
    anywhere,
    counts_as,
    register_counts_as,
    while_in_play,
)
from yasuki_core.game_pieces.prints import FatePrint, PersonalityPrint, RingPrint

from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    put_in_play,
    stronghold,
    two_seat_game,
)


def test_a_card_counting_as_a_ring_while_in_play_is_one_only_there():
    game = two_seat_game()
    heart = holding("P1-heart", owner=PlayerId.P1, printed_id="ring_in_play_probe")
    register_counts_as(
        "ring_in_play_probe", CountsAs(RingPrint, frozenset({AskedBy.ACTION}), while_in_play)
    )

    try:
        assert not counts_as(game, heart, RingPrint, Asking.action(heart))
        put_in_play(game, heart)
        assert counts_as(game, heart, RingPrint, Asking.action(heart))
    finally:
        COUNTS_AS.pop("ring_in_play_probe")


@pytest.mark.parametrize(
    ("asking_for", "counts"),
    [(Asking.action, True), (Asking.trait, False), (lambda card: RULEBOOK, False)],
    ids=["action", "trait", "rule"],
)
def test_a_card_counting_as_a_ring_for_actions_answers_only_an_action(asking_for, counts):
    game = two_seat_game()
    strategy = fate_card("ring_anywhere_probe", PlayerId.P1)
    register_counts_as(
        "ring_anywhere_probe", CountsAs(RingPrint, frozenset({AskedBy.ACTION}), anywhere)
    )

    try:
        assert counts_as(game, strategy, RingPrint, asking_for(strategy)) is counts
    finally:
        COUNTS_AS.pop("ring_anywhere_probe")


@pytest.mark.parametrize(("kind", "counts"), [(FatePrint, True), (PersonalityPrint, False)])
def test_a_card_counting_as_a_ring_counts_as_what_a_printed_ring_is(kind, counts):
    game = two_seat_game()
    heart = put_in_play(game, holding("P1-heart", owner=PlayerId.P1, printed_id="ring_kind_probe"))
    register_counts_as(
        "ring_kind_probe", CountsAs(RingPrint, frozenset({AskedBy.ACTION}), while_in_play)
    )

    try:
        assert counts_as(game, heart, kind, Asking.action(heart)) is counts
    finally:
        COUNTS_AS.pop("ring_kind_probe")


def test_the_condition_sees_the_asking_card():
    game = two_seat_game()
    counted = fate_card("ring_asker_probe", PlayerId.P1)
    own_stronghold = put_in_play(game, stronghold(PlayerId.P1, gold_production=5))
    plain = put_in_play(game, holding("P1-plain", owner=PlayerId.P1))

    def _not_for_a_stronghold(game, card, asking):
        return asking.card is not own_stronghold

    register_counts_as(
        "ring_asker_probe",
        CountsAs(RingPrint, frozenset({AskedBy.ACTION}), _not_for_a_stronghold),
    )

    try:
        assert counts_as(game, counted, RingPrint, Asking.action(plain))
        assert not counts_as(game, counted, RingPrint, Asking.action(own_stronghold))
    finally:
        COUNTS_AS.pop("ring_asker_probe")


@pytest.mark.parametrize(
    ("asked_by", "with_card"),
    [(AskedBy.ACTION, False), (AskedBy.TRAIT, False), (AskedBy.RULE, True)],
)
def test_an_asking_must_name_a_card_exactly_when_card_text_asks(asked_by, with_card):
    card = fate_card("P1-way", PlayerId.P1) if with_card else None

    with pytest.raises(ValueError, match=asked_by.value):
        Asking(asked_by, card)
