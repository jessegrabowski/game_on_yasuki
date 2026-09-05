import inspect

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import BEGINNING_OF_COMBAT, END_OF_TURN
from yasuki_core.engine.rules.effects import (
    RefillProvince,
    AdjustCounter,
    AskAmount,
    AskDistribution,
    AskOption,
    AttachCard,
    Banish,
    DelayedEffect,
    BanishTopFate,
    Bow,
    Ask,
    CounterOnAttachedProvince,
    Unpayable,
    Choose,
    CreateToken,
    DelayStraighten,
    Discard,
    Destroy,
    DestroyProvince,
    DiscardFavor,
    DrawCard,
    Effect,
    InterruptingEffect,
    GainGold,
    TakeFavor,
    GainHonor,
    LoseGame,
    WinGame,
    Move,
    MoveToHand,
    Fear,
    GrantPriority,
    RangedAttack,
    GrantKeyword,
    GrantMinimum,
    GrantLobbyBonus,
    GrantProvinceStrength,
    GrantModifier,
    PayFavorCost,
    PutIntoPlay,
    SpendOncePerTurn,
    PayGold,
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
from yasuki_core.engine.table import DeckKey, Location, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WALL, WEALTH

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
        LoseGame(PlayerId.P2, "no Provinces remaining", "Military Victory"),
        "P2 loses: no Provinces remaining",
    ),
    (
        WinGame(PlayerId.P1, "Honor Victory on 40 Family Honor"),
        "P1 wins: Honor Victory on 40 Family Honor",
    ),
    (
        DestroyProvince(PlayerId.P1, ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 2)),
        "destroy P1's province 2",
    ),
    (Show("a"), "show a"),
    (MoveToHand("a", PlayerId.P1), "a to P1's hand"),
    (Move("shiba", Location.home(PlayerId.P2)), "move shiba to P2's home"),
    (IgnoreHonorRequirements(PlayerId.P1), "P1 ignores honor requirements"),
    (
        GrantModifier("millet", "farm_1", Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN),
        "millet grants farm_1 +2 GOLD_PRODUCTION (UNTIL_END_OF_TURN)",
    ),
    (
        GrantMinimum("uncertainty", "shiba", Stat.CHI, 1, Duration.UNTIL_END_OF_TURN),
        "uncertainty gives shiba a minimum CHI of 1 (UNTIL_END_OF_TURN)",
    ),
    (
        PayFavorCost(),
        "the action pays a Favor cost",
    ),
    (
        PutIntoPlay("edict"),
        "put edict into play",
    ),
    (
        SpendOncePerTurn("miaka", "iweko_miaka_favor_payment"),
        "miaka spends its iweko_miaka_favor_payment for the turn",
    ),
    (
        GrantLobbyBonus("court", PlayerId.P1, 5, Duration.WHILE_SOURCE_IN_PLAY),
        "court gives P1 a +5 Lobby Bonus (WHILE_SOURCE_IN_PLAY)",
    ),
    (
        GrantProvinceStrength(
            "walls", ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0), 3, Duration.UNTIL_END_OF_TURN
        ),
        "walls gives P2:province:0 +3 province strength (UNTIL_END_OF_TURN)",
    ),
    (
        RangedAttack(3, "ashigaru", PlayerId.P1),
        "ranged 3 on ashigaru",
    ),
    (
        Fear(4, "hida", PlayerId.P1, compared=Stat.CHI),
        "fear 4 on hida vs CHI",
    ),
    (
        GrantPriority(PlayerId.P1),
        "P1 takes the opportunity to act",
    ),
    (
        DelayedEffect(GrantPriority(PlayerId.P1), BEGINNING_OF_COMBAT),
        "P1 takes the opportunity to act at the beginning of the Combat Segment",
    ),
    (
        GrantKeyword("fields", "shinjo_1", "Cavalry", Duration.UNTIL_END_OF_TURN),
        "fields gives shinjo_1 Cavalry (UNTIL_END_OF_TURN)",
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
    (CreateToken("ashigaru_2", PlayerId.P1, "farm_1"), "P1 creates ashigaru_2"),
    (
        CreateToken("ashigaru_2", PlayerId.P1, "farm_1", attach_to="hero"),
        "P1 creates ashigaru_2 on hero",
    ),
    (
        CreateToken("oni", PlayerId.P2, "mishime", stats=((Stat.FORCE, 4),)),
        "P2 creates oni with FORCE 4",
    ),
    (
        CreateToken("courtier", PlayerId.P1, "courts", clan="Lion"),
        "P1 creates courtier with Lion",
    ),
    (
        CreateToken("oni", PlayerId.P2, "mishime", clan="Crab", stats=((Stat.FORCE, 4),)),
        "P2 creates oni with Crab, FORCE 4",
    ),
    (Banish("oni"), "banish oni"),
    (
        DelayedEffect(Banish("oni"), END_OF_TURN),
        "banish oni at the end of the turn",
    ),
    (PayGold(PlayerId.P2, 3, "Colonial Farm"), "P2 pays 3 gold for Colonial Farm"),
    (CounterOnAttachedProvince("wall", WALL, 1), "+1 Wall on wall's province"),
    (
        Unpayable("katana is attached to no Personality"),
        "unpayable: katana is attached to no Personality",
    ),
    (
        PlaceInProvince("farm_1", ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 1)),
        "place farm_1 in P2 province 1",
    ),
    (ShuffleDeck(DeckKey(PlayerId.P1, Side.DYNASTY)), "shuffle P1's dynasty deck"),
    (DelayStraighten("jade_1"), "jade_1 may not straighten until after its next Action Phase"),
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
    (
        AskAmount(PlayerId.P1, (2, 4), "How much blood?", "bound_in_blood", "spell_1"),
        "P1 is asked: How much blood?",
    ),
    (
        AskOption(PlayerId.P1, ("P1 gains 1 Honor",), "Whose Honor moves?", "courts", "courts_1"),
        "P1 is asked: Whose Honor moves?",
    ),
    (
        AskDistribution(PlayerId.P1, ("hero", "rival"), 3, "suiteiru_no_oni", "oni_1"),
        "P1 divides 3 among 2 for suiteiru_no_oni",
    ),
    (TakeFavor(PlayerId.P1), "P1 takes the Imperial Favor"),
    (DiscardFavor(PlayerId.P2), "P2 discards the Imperial Favor"),
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
