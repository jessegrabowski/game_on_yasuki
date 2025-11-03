import pytest

from dataclasses import FrozenInstanceError
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side


def test_l5rcard_normalizes_keywords_and_traits_to_tuples():
    c = L5RCard(
        id="c1",
        name="Card",
        side=Side.FATE,
        keywords=["Samurai"],  # type: ignore[list-item]
        traits=["Unique"],  # type: ignore[list-item]
    )
    assert isinstance(c.keywords, tuple)
    assert isinstance(c.traits, tuple)
    assert c.keywords == ("Samurai",)
    assert c.traits == ("Unique",)


def test_l5rcard_is_frozen():
    c = L5RCard(id="c1", name="Card", side=Side.FATE)
    with pytest.raises(FrozenInstanceError):
        c.name = "New Name"  # type: ignore[assignment]
