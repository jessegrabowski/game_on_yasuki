import pytest

from dataclasses import FrozenInstanceError
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import HoldingPrint
from yasuki_core.game_pieces.prints import CardPrint
from yasuki_core.engine.players import PlayerId


def test_l5rcard_normalizes_keywords_and_traits_to_tuples():
    c = L5RCard.of(
        CardPrint,
        id="c1",
        name="Card",
        side=Side.FATE,
        keywords=["Samurai"],  # type: ignore[list-item]
        traits=["Unique"],
        owner=PlayerId.P1,  # type: ignore[list-item]
    )
    assert isinstance(c.keywords, tuple)
    assert isinstance(c.traits, tuple)
    assert c.keywords == ("Samurai",)
    assert c.traits == ("Unique",)


def test_of_builds_the_card_its_print_describes():
    card = L5RCard.of(
        HoldingPrint, id="c1", name="Farm", side=Side.DYNASTY, gold_production=2, owner=PlayerId.P1
    )

    assert isinstance(card.printed, HoldingPrint)
    assert (card.id, card.gold_production) == ("c1", 2)


def test_of_rejects_a_field_neither_half_declares():
    with pytest.raises(TypeError):
        L5RCard.of(
            HoldingPrint, id="c1", name="Farm", side=Side.DYNASTY, force=3, owner=PlayerId.P1
        )


def test_l5rcard_is_frozen():
    c = L5RCard.of(CardPrint, id="c1", name="Card", side=Side.FATE, owner=PlayerId.P1)
    with pytest.raises(FrozenInstanceError):
        c.name = "New Name"  # type: ignore[assignment]
