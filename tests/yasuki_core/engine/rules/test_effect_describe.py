import inspect

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import (
    RefillProvince,
    AdjustCounter,
    AttachCard,
    BanishTopFate,
    Bow,
    Ask,
    Unpayable,
    Choose,
    Discard,
    Destroy,
    DestroyProvince,
    DrawCard,
    Effect,
    InterruptingEffect,
    GainGold,
    GainHonor,
    MoveToHand,
    GrantModifier,
    IgnoreHonorRequirements,
    MoveToDeck,
    PlaceInProvince,
    RecruitCard,
    RevealProvinces,
    Show,
    ShuffleDeck,
    Straighten,
    Then,
)
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH

EFFECTS = [
    (AdjustCounter("rural_market_1", WEALTH, 2), "+2 Wealth on rural_market_1"),
    (AdjustCounter("rural_market_1", WEALTH, -1), "-1 Wealth on rural_market_1"),
    (DrawCard(PlayerId.P1), "P1 draws a card"),
    (Destroy("farm_1", PlayerId.P1), "destroy farm_1"),
    (Bow("farm_1"), "bow farm_1"),
    (Straighten("farm_1"), "straighten farm_1"),
    (BanishTopFate(PlayerId.P2), "banish the top of P2's fate deck"),
    (GainGold(PlayerId.P2, 3), "P2 gains 3 gold"),
    (GainHonor(PlayerId.P1, 2), "P1 gains 2 honor"),
    (GainHonor(PlayerId.P2, -4), "P2 loses 4 honor"),
    (
        DestroyProvince(PlayerId.P1, ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 2)),
        "destroy P1's province 2",
    ),
    (Show("a"), "show a"),
    (MoveToHand("a", PlayerId.P1), "a to P1's hand"),
    (IgnoreHonorRequirements(PlayerId.P1), "P1 ignores honor requirements"),
    (
        GrantModifier("millet", "farm_1", Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN),
        "millet grants farm_1 +2 GOLD_PRODUCTION (UNTIL_END_OF_TURN)",
    ),
    (
        MoveToDeck("farm_1", DeckKey(PlayerId.P1, Side.DYNASTY), from_bottom=0),
        "move farm_1 into P1's dynasty deck, 0 from bottom",
    ),
    (
        MoveToDeck("farm_1", DeckKey(PlayerId.P2, Side.FATE), from_top=3),
        "move farm_1 into P2's fate deck, 3 from top",
    ),
    (RecruitCard("holding_1"), "recruit holding_1 out of sequence"),
    (
        RecruitCard("holding_1", renew=True),
        "recruit holding_1 out of sequence, renewing the province",
    ),
    (RefillProvince(ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 2)), "refill P1 province 2"),
    (
        RefillProvince(ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0), face_up=True),
        "refill P2 province 0 face-up",
    ),
    (Discard("farm_1", PlayerId.P1), "P1 discards farm_1"),
    (AttachCard("katana", "hero"), "attach katana to hero"),
    (
        Unpayable("katana is attached to no Personality"),
        "unpayable: katana is attached to no Personality",
    ),
    (
        PlaceInProvince("farm_1", ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 1)),
        "place farm_1 in P2 province 1",
    ),
    (ShuffleDeck(DeckKey(PlayerId.P1, Side.DYNASTY)), "shuffle P1's dynasty deck"),
    (RevealProvinces(PlayerId.P1), "reveal P1's provinces"),
    (Then((Bow("a"), Destroy("b", PlayerId.P1))), "then: 2 deferred"),
    (
        Choose(PlayerId.P1, ("a", "b", "c"), 0, 2, "wheat_farm", "wheat_1"),
        "P1 chooses 0-2 of 3 for wheat_farm",
    ),
    (
        Ask(PlayerId.P1, "Destroy Rice Farm to straighten Kobune?", "rice_farm", ("rice_1",)),
        "P1 is asked: Destroy Rice Farm to straighten Kobune?",
    ),
]


@pytest.mark.parametrize("effect, expected", EFFECTS, ids=[text for _, text in EFFECTS])
def test_an_effect_describes_itself_in_one_line(effect, expected):
    assert effect.describe() == expected


def test_every_effect_has_a_description_here():
    # EFFECTS is hand-written, so effect number thirteen would ship with a describe the ABC forced
    # but wording nobody reviewed.
    described = {type(effect).__name__ for effect, _ in EFFECTS}
    concrete = {
        subclass.__name__
        for base in (Effect, InterruptingEffect)
        for subclass in base.__subclasses__()
        if subclass.__module__ == Effect.__module__ and not inspect.isabstract(subclass)
    }

    assert concrete - described == set()


def test_nesting_deferrals_does_not_grow_the_line():
    # Then is the deferral primitive, so it is the effect most likely to nest — and a cascade that
    # fails to converge is where nesting runs deepest. Inlining children would put the longest line
    # exactly where the trace matters most; the renderer nests them by depth instead.
    inner = Then((Bow("a"), Destroy("b", PlayerId.P1), AdjustCounter("c", WEALTH, 1)))

    assert Then((inner, inner, inner)).describe() == "then: 3 deferred"


def test_an_effect_without_a_description_cannot_be_instantiated():
    # describe is abstract, so a new effect that forgets it fails at construction rather than
    # rendering as an unreadable dataclass dump inside a trace.
    class Wordless(Effect):
        __slots__ = ()

        def perform(self, game):
            return []

    with pytest.raises(TypeError, match="describe"):
        Wordless()
