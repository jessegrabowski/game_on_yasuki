import pytest
from yasuki_core.engine.rules.rulebook.recruit import RECRUIT, RECRUIT_WITH_INVEST
from yasuki_core import ruleset
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import (
    ActionPrint,
    PersonalityPrint,
    RingPrint,
    RulebookPrint,
    WindPrint,
)
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.projection import project
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    DeclareAttack,
    Equip,
    Pass,
)
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseAbilityTarget,
    ChooseOption,
    DecisionResponse,
)
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.stats.province_strength import effective_province_strength
from yasuki_core.engine.rules.effects import Bow, Destroy, Discard, DrawCard, PutIntoPlay
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.idioms import PITCH, ask_who_loses_honor
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import _ABILITIES, ability_for, register_ability
from yasuki_core.engine.rules.effects import GainHonor, GrantNegation, TakeFavor
from yasuki_core.engine.rules.vocabulary.game_events import ConditionFulfilled
from yasuki_core.engine.rules.legality import recruit_cost
from yasuki_core.engine.rules.triggers import pay_costs, resolve_effects
from yasuki_core.engine.rules.vocabulary.game_events import Dishonored, EnteredPlay
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.cards.shattered_empire import (
    ENLIGHTENED_PATH_COPY,
    FINE_SWORD,
    SANJIROS_ARMOR,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded, FavorDiscarded
from yasuki_core.engine.rules.turn.structure import END_OF_TURN, RoundKind
from yasuki_core.engine.rules.vocabulary.modifiers import (
    Duration,
    Modifier,
    Negation,
    SeatAbilityGrant,
    Stat,
)
from yasuki_core.engine.rules.turn import action_sequence, sequence
from yasuki_core.engine.players import Trait
from yasuki_core.engine.rules.rulebook import proxies
from yasuki_core.engine.rules.rulebook.lobby import is_lobby, lobby_bonus
from yasuki_core.engine.rules.board.counts_as import Asking, counts_as
from yasuki_core.engine.rules.board.queries import province_zones
from yasuki_core.engine import ops
from yasuki_core.engine.table import DeckKey
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, AttachmentType, Side

from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.effects import Recruit as RecruitEffect
from yasuki_core.engine.rules.interrupts import forecast
from yasuki_core.engine.rules.rulebook.recruit import proclaim_gain_effects, recruit_effects
from yasuki_core.engine.rules.triggers import resolve_action_effects
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.vocabulary.decisions import (
    STRIKE,
    ChooseDiscard,
    ChoosePayment,
    Confirm,
    FocusOrStrike,
    focus_token,
)
from yasuki_core.engine.rules.vocabulary.actions import PlayInterrupt
from yasuki_core.engine.rules.effects import Move, StartDuel, Straighten
from yasuki_core.engine.table import Location, location_of
from yasuki_core.engine.rules.board.queries import personalities_in_play
from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.rules.cards.test_anvil_of_despair import (
    _reach_the_combat_segment,
    _refugees_battle,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from tests.yasuki_core.engine.builders import (
    combat_segment,
    datasheet_favor_ability,
    attached,
    attachment,
    end_phase,
    end_turn,
    fate_card,
    focus_card,
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    stronghold,
    terrain_at,
    token_template,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


def _artist_game(*, carrying: tuple[str, ...] = (), free_handed: bool = False):
    """P1's Weapon Artist in play beside "hero", who is already carrying ``carrying`` Weapons, and
    with an empty-handed "rival" beside him when ``free_handed``."""
    game = two_seat_game()
    token_template(
        game,
        FINE_SWORD,
        name="Fine Sword",
        card_type="Item",
        keywords=("One-Handed", "Sword", "Weapon"),
        force=2,
        chi=1,
    )
    put_in_play(game, holding("artist", printed_id="weapon_artist", gold_production=6))
    put_in_play(game, personality("hero", force=3, chi=3))
    for index, keyword in enumerate(carrying):
        attached(
            game,
            attachment(f"held{index}", keywords=("Weapon", keyword), force_modifier=1),
            "hero",
        )
    if free_handed:
        put_in_play(game, personality("rival", force=3, chi=3))
    return game


def test_weapon_artist_bows_to_equip_a_created_sword():
    session = EngineSession.start(_artist_game().table, P1)

    session.act(P1, ActivateAbility("artist"))
    session.submit(P1, DecisionResponse(("hero",)))

    game = session.game
    hero = game.table.cards_by_id["hero"]
    sword = attachments_of(game, hero)[0]
    assert sword.name == "Fine Sword"
    assert sword.is_token is True
    assert game.table.cards_by_id["artist"].bowed is True  # the cost
    assert effective_force(game, hero) == 5  # 3 printed, +2 from the sword


def test_the_created_sword_is_a_one_handed_weapon():
    """The +1C half, and the keywords the next Weapon has to fit around, come off the token print
    rather than being spelled out at the creation site."""
    session = EngineSession.start(_artist_game().table, P1)

    session.act(P1, ActivateAbility("artist"))
    session.submit(P1, DecisionResponse(("hero",)))

    sword = attachments_of(session.game, session.game.table.cards_by_id["hero"])[0]
    assert sword.chi_modifier == 1
    assert set(sword.keywords) == {"One-Handed", "Sword", "Weapon"}


def test_weapon_artist_offers_only_the_personalities_with_a_hand_free():
    """One Weapon per Personality, so the sword has nowhere to go on the one already carrying. The
    Weapon rules judge it before it exists. The filter has to narrow the targets rather than
    withdraw the ability, which is what the empty-handed rival is here to show."""
    session = EngineSession.start(
        _artist_game(carrying=("One-Handed",), free_handed=True).table, P1
    )

    session.act(P1, ActivateAbility("artist"))

    assert session.game.pending.candidates == ("rival",)


def test_weapon_artist_is_withheld_when_every_personality_is_carrying():
    session = EngineSession.start(_artist_game(carrying=("One-Handed",)).table, P1)

    assert ActivateAbility("artist") not in session.legal_actions(P1)


def test_weapon_artist_is_withheld_while_bowed():
    """His bow is the cost, so a Weapon Artist who has already bowed for gold makes nothing."""
    session = EngineSession.start(_artist_game().table, P1)
    session.game.table.cards_by_id["artist"].bow()

    assert ActivateAbility("artist") not in session.legal_actions(P1)


def test_the_created_sword_leaves_the_game_with_its_personality():
    """A created card has no discard pile: it exists only in play, so a destroyed unit takes it off
    the table entirely rather than into the pile its Personality goes to."""
    session = EngineSession.start(_artist_game().table, P1)
    session.act(P1, ActivateAbility("artist"))
    session.submit(P1, DecisionResponse(("hero",)))
    game = session.game
    sword_id = attachments_of(game, game.table.cards_by_id["hero"])[0].id

    resolve_effects(game, [Destroy("hero", P1)])

    discard = game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert sword_id not in game.table.cards_by_id
    assert [card.id for card in discard.cards] == ["hero"]


def test_weapon_artist_replays_to_the_same_board():
    session = EngineSession.start(_artist_game().table, P1)
    session.act(P1, ActivateAbility("artist"))
    session.submit(P1, DecisionResponse(("hero",)))

    assert replay(session.log).table == session.game.table


# --- Hida Sanjiro ---


def _sanjiro_game():
    """A Dynasty phase with Sanjiro face-up in a Province and gold enough for his Invest."""
    state = TableState.empty_two_seat()
    token_template(
        state, SANJIROS_ARMOR, name="Armor", card_type="Item", keywords=("Armor",), force=2
    )
    put_in_play(state, stronghold(P1, gold_production=8))
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [register(state, holding("refill", owner=P1))]
    sanjiro = register(
        state, personality("sanjiro", force=4, chi=2, printed_id="hida_sanjiro", gold_cost=6)
    )
    sanjiro.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(sanjiro)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


def test_hida_sanjiro_invests_in_his_own_armour():
    """The Invest resolves as he arrives, so the Armor is on him the moment he is in play."""
    session = _sanjiro_game()

    session.act(P1, ActivateAbility("sanjiro", RECRUIT_WITH_INVEST))
    pay(session, P1)

    game = session.game
    sanjiro = game.table.cards_by_id["sanjiro"]
    armour = attachments_of(game, sanjiro)[0]
    assert armour.name == "Armor"
    assert armour.is_token is True
    assert effective_force(game, sanjiro) == 6  # 4 printed, +2 worn


def test_hida_sanjiro_recruited_plainly_wears_nothing():
    """The Armor is the Invest's payoff, not part of him arriving."""
    session = _sanjiro_game()

    session.act(P1, ActivateAbility("sanjiro", RECRUIT))
    pay(session, P1)

    assert attachments_of(session.game, session.game.table.cards_by_id["sanjiro"]) == ()


def _edict_game(
    *, clan: str | None = ruleset.CRANE, in_play: tuple[str, ...] = ()
) -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1, clan=clan)))
    for card_id in in_play:
        already = (
            "way_of_the_crane_experienced" if card_id == "first" else "way_of_the_lion_experienced"
        )
        put_in_play(state, register(state, _edict(card_id, already)))
    crane = register(state, _edict("crane", "way_of_the_crane_experienced"))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(crane)
    return EngineSession.start(state, P1)


def _edict(card_id: str, printed_id: str) -> L5RCard:
    return L5RCard.of(
        ActionPrint,
        id=card_id,
        name=printed_id,
        printed_id=card_id if printed_id is None else printed_id,
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
        keywords=(keywords.EDICT,),
    )


def _play_the_edict(session: EngineSession) -> None:
    session.act(P1, PlayStrategy("crane", "enter"))
    while session.game.pending is not None:
        session.submit(P1, DecisionResponse(()))


def test_an_edict_puts_itself_into_play_rather_than_being_discarded():
    """Step F discards a played Strategy "unless it is now in play", the exception an Edict is."""
    session = _edict_game()

    _play_the_edict(session)

    game = session.game
    assert "crane" in {card.id for card in game.table.battlefield.cards}
    discard = game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    assert "crane" not in {card.id for card in discard.cards}


def test_an_edict_discards_the_one_already_out():
    """One Edict at a time (ShE datasheet, Edicts)."""
    session = _edict_game(in_play=("lion",))

    _play_the_edict(session)

    in_play = {card.id for card in session.game.table.battlefield.cards}
    assert "crane" in in_play and "lion" not in in_play


def test_an_edict_naming_a_clan_is_not_offered_to_another():
    session = _edict_game(clan=ruleset.LION)

    assert PlayStrategy("crane", "enter") not in session.legal_actions(P1)


def test_a_second_copy_of_an_edict_discards_the_first():
    """A copy of itself is one of "your other Edicts in play". Only Be Prepared to Dig Two Graves
    exempts copies, and it says so."""
    session = _edict_game(in_play=("first",))

    _play_the_edict(session)

    game = session.game
    in_play = {card.id for card in game.table.battlefield.cards}
    assert "crane" in in_play, "the copy just played is the one that stays"
    assert "first" not in in_play
    discard = game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    assert "first" in {card.id for card in discard.cards}


def _crane_edict_in_play(
    *, hand: tuple[str, ...] = ("held",), deck: tuple[str, ...] = ("top",)
) -> GameState:
    """Way of the Crane in play for a Crane seat, with ``hand`` in hand and ``deck`` on top of the
    Fate deck, just after the seat's own action discarded the Favor."""
    state = TableState.empty_two_seat()
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    put_in_play(state, register(state, stronghold(P1, clan=ruleset.CRANE)))
    put_in_play(state, register(state, _edict("crane", "way_of_the_crane_experienced")))
    for index in range(3):
        province_card(state, f"p1-prov{index}", seat=P1, index=index)
    for card_id in hand:
        state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, fate_card(card_id, P1)))
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card(c, P1)) for c in deck]
    game = GameState.start(state, P1, seed=0)
    game.action_seat = P1
    game.action_events[:] = [FavorDiscarded(P1)]
    return game


CRANE_DRAW = ActivateAbility("crane", "draw_and_discard")


def _hand_ids(game: GameState) -> list[str]:
    return [card.id for card in game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards]


def test_way_of_the_crane_gives_one_lobby_bonus_per_province():
    game = _crane_edict_in_play()  # three Provinces
    assert lobby_bonus(game, P1) == 3

    first, _ = next(province_zones(game, P1))
    ops.destroy_province(game.table, P1, first)

    assert lobby_bonus(game, P1) == 2


def test_way_of_the_crane_is_offered_in_the_response_step_after_your_action_discards_the_favor():
    """A trait worded "after your action", offered where a Response is so the seat orders it among
    the other answers to the same action, or passes it."""
    game = _crane_edict_in_play()

    assert sequence.open_response_window(game) is True

    assert CRANE_DRAW in legality.legal_actions(game, P1)


def test_way_of_the_crane_draws_then_discards_as_a_trait(reacting):
    """The card just drawn is among the ones offered for the discard, and the discard is the
    trait's doing rather than an action's. A Response's doings stay off the action record, so the
    cause is read by a card reacting to the discard."""
    game = _crane_edict_in_play()
    put_in_play(game, holding("witness", printed_id="crane_discard_witness"))
    causes = []

    def witness(ctx):
        causes.append(ctx.event.cause)
        return []

    reacting(CardDiscarded, "crane_discard_witness", witness)
    sequence.open_response_window(game)

    action_sequence.perform(game, CRANE_DRAW)

    assert isinstance(game.pending, ChooseDiscard)
    assert set(game.pending.candidates) == {"held", "top"}
    assert _hand_ids(game) == ["held", "top"]
    submit(game, DecisionResponse(("top",)))

    assert _hand_ids(game) == ["held"]
    discard = game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    assert "top" in {card.id for card in discard.cards}
    assert causes == [Trait("crane")]


def test_way_of_the_crane_is_a_trait_and_escapes_a_negation_of_actions_from_strategies():
    game = _crane_edict_in_play()
    negation = Negation("ring", END_OF_TURN, source_kind=ActionPrint)
    resolve_effects(game, [GrantNegation(negation)])
    sequence.open_response_window(game)

    action_sequence.perform(game, CRANE_DRAW)

    assert _hand_ids(game) == ["held", "top"]


def test_way_of_the_crane_does_not_offer_the_imperial_favor_as_its_discard():
    game = _crane_edict_in_play()
    resolve_effects(game, [TakeFavor(P1)])
    sequence.open_response_window(game)

    action_sequence.perform(game, CRANE_DRAW)

    assert set(game.pending.candidates) == {"held", "top"}


def test_way_of_the_crane_draws_once_per_turn():
    game = _crane_edict_in_play(deck=("top", "second"))
    sequence.open_response_window(game)
    action_sequence.perform(game, CRANE_DRAW)
    submit(game, DecisionResponse(("held",)))
    game.action_events[:] = [FavorDiscarded(P1)]

    assert sequence.open_response_window(game) is False


def test_passing_on_way_of_the_crane_keeps_it_for_later_in_the_turn():
    game = _crane_edict_in_play()
    sequence.open_response_window(game)
    while game.round.kind is RoundKind.RESPONSE:
        action_sequence.perform(game, Pass())
    assert _hand_ids(game) == ["held"]
    game.action_events[:] = [FavorDiscarded(P1)]

    assert sequence.open_response_window(game) is True


def test_way_of_the_crane_counts_your_action_discarding_the_other_seats_favor():
    """Lies, Lies, Lies... (Experienced): "The player with :favor: discards it." Your action, so
    the trait answers it."""
    game = _crane_edict_in_play()
    game.action_events[:] = [FavorDiscarded(PlayerId.P2)]

    assert sequence.open_response_window(game) is True

    assert CRANE_DRAW in legality.legal_actions(game, P1)


def test_way_of_the_crane_ignores_a_favor_discarded_by_the_other_seats_action():
    game = _crane_edict_in_play()
    game.action_seat = PlayerId.P2

    assert sequence.open_response_window(game) is False


def test_the_rulebook_favor_ability_opens_way_of_the_cranes_window():
    state = TableState.empty_two_seat()
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    put_in_play(state, register(state, stronghold(P1, clan=ruleset.CRANE)))
    put_in_play(state, register(state, _edict("crane", "way_of_the_crane_experienced")))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, fate_card("spent", P1)))
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("top", P1))]
    session = EngineSession.start(state, P1)
    TakeFavor(P1).perform(session.game)

    session.act(P1, datasheet_favor_ability("discard_to_draw"))
    session.submit(P1, DecisionResponse(("spent",)))

    assert session.game.round.kind is RoundKind.RESPONSE
    assert CRANE_DRAW in session.legal_actions(P1)


# --- Way of the Crab (Experienced) ---


def _crab_edict_in_play() -> GameState:
    """Way of the Crab in play for P1, beside P1's Fortifications "wall" and "second_wall", P1's
    plain Holding "farm" and P2's Fortification "keep"."""
    game = two_seat_game()
    put_in_play(game, _edict("crab", "way_of_the_crab_experienced"))
    put_in_play(game, holding("wall", keywords=(keywords.FORTIFICATION,)))
    put_in_play(game, holding("second_wall", keywords=(keywords.FORTIFICATION,)))
    put_in_play(game, holding("farm"))
    put_in_play(game, holding("keep", owner=P2, keywords=(keywords.FORTIFICATION,)))
    return game


def _bowed(game: GameState, card_id: str) -> bool:
    return game.table.cards_by_id[card_id].bowed


def test_way_of_the_crab_straightens_your_fortification_and_negates_its_bowing_this_turn():
    game = _crab_edict_in_play()

    resolve_effects(game, [Bow("wall")])
    assert not _bowed(game, "wall")

    resolve_effects(game, [Bow("wall")])
    assert not _bowed(game, "wall")


def test_way_of_the_crab_straightens_once_per_turn():
    game = _crab_edict_in_play()
    resolve_effects(game, [Bow("wall")])

    resolve_effects(game, [Bow("second_wall")])

    assert _bowed(game, "second_wall")


@pytest.mark.parametrize("card_id", ["farm", "keep"])
def test_way_of_the_crab_leaves_any_other_card_bowed(card_id):
    game = _crab_edict_in_play()

    resolve_effects(game, [Bow(card_id)])

    assert _bowed(game, card_id)


def test_a_fortification_whose_bowing_way_of_the_crab_negates_still_bows_to_pay_a_cost():
    game = _crab_edict_in_play()
    resolve_effects(game, [Bow("wall")])

    pay_costs(game, [Bow("wall")])

    assert _bowed(game, "wall")


# --- Way of the Dragon (Experienced) ---


def _dragon_game() -> EngineSession:
    """Way of the Dragon in play for P1, with "under" then "top" on P1's Fate deck. Starting the
    session begins P1's turn, so the look is already waiting."""
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1, clan=ruleset.DRAGON)))
    put_in_play(state, register(state, _edict("dragon", "way_of_the_dragon_experienced")))
    for seat in (P1, P2):
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(state, fate_card(f"{seat.name}-{card_id}", seat))
            for card_id in ("bottom", "under", "top")
        ]
    return EngineSession.start(state, P1)


def _fate_deck_ids(session: EngineSession, seat: PlayerId) -> list[str]:
    return [card.id for card in session.game.table.decks[DeckKey(seat, Side.FATE)].cards]


@pytest.mark.parametrize(
    ("answer", "deck"),
    [
        ((), ["P1-bottom", "P1-under", "P1-top"]),
        (("P1-top",), ["P1-top", "P1-bottom", "P1-under"]),
    ],
    ids=["kept", "bottomed"],
)
def test_way_of_the_dragon_looks_at_the_top_card_after_your_turn_begins(answer, deck):
    session = _dragon_game()
    assert session.game.look.card_ids == ("P1-top",)

    session.submit(P1, DecisionResponse(answer))

    assert session.game.look is None
    assert _fate_deck_ids(session, P1) == deck


def test_way_of_the_dragon_looks_only_when_its_controllers_turn_begins():
    session = _dragon_game()
    session.submit(P1, DecisionResponse(()))

    end_turn(session)

    assert session.game.active is P2
    assert session.game.look is None
    assert session.game.pending is None


def _ring_card(card_id: str, owner: PlayerId) -> L5RCard:
    return L5RCard.of(
        RingPrint, id=card_id, printed_id=card_id, name=card_id, side=Side.FATE, owner=owner
    )


def test_way_of_the_dragon_lobby_bonus_counts_printed_rings_in_play_and_in_discard_piles():
    game = two_seat_game()
    put_in_play(game, _edict("dragon", "way_of_the_dragon_experienced"))
    put_in_play(game, _ring_card("mine", P1))
    put_in_play(game, _ring_card("theirs", P2))
    put_in_play(game, holding("heart", printed_id="shinseis_heart"))
    for seat, card in (
        (P1, _ring_card("discarded", P1)),
        (P2, _edict("other_dragon", "way_of_the_dragon_experienced")),
    ):
        game.table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)].add(register(game.table, card))

    assert lobby_bonus(game, P1) == 3


def test_way_of_the_dragon_in_hand_counts_as_a_ring_for_an_action_but_not_a_trait():
    game = two_seat_game()
    held = _edict("dragon", "way_of_the_dragon_experienced")
    game.table.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(game.table, held))
    asker = put_in_play(game, holding("asker"))

    assert counts_as(game, held, RingPrint, Asking.action(asker))
    assert not counts_as(game, held, RingPrint, Asking.trait(asker))


def test_way_of_the_dragon_looks_at_nothing_from_an_empty_fate_deck():
    session = _dragon_game()
    session.submit(P1, DecisionResponse(()))
    session.game.table.decks[DeckKey(P1, Side.FATE)].cards = []

    end_turn(session)
    end_turn(session)

    assert session.game.active is P1
    assert session.game.look is None


# --- Doji Yasuko, Soul of Doji Takeji ---


def _yasuko_waiting(state: TableState) -> L5RCard:
    return register(
        state, personality("yasuko", printed_id="doji_yasuko_soul_of_doji_takeji", gold_cost=6)
    )


def _courtier_of(clan: str) -> L5RCard:
    return L5RCard.of(
        PersonalityPrint,
        id="courtier",
        printed_id="courtier",
        name="Courtier",
        side=Side.DYNASTY,
        owner=P1,
        chi=3,
        keywords=("Courtier",),
        clans=(clan,),
    )


def test_doji_yasuko_costs_two_less_beside_a_crane_courtier():
    game = two_seat_game()
    put_in_play(game, _courtier_of("Crane Clan"))
    yasuko = _yasuko_waiting(game.table)

    assert recruit_cost(game, yasuko) == 4


def test_doji_yasuko_is_not_discounted_by_a_courtier_of_another_clan():
    game = two_seat_game()
    put_in_play(game, _courtier_of("Lion Clan"))
    yasuko = _yasuko_waiting(game.table)

    assert recruit_cost(game, yasuko) == 6


HONORABLE_STRATEGY = "probe_honorable_strategy"


def _honorable_strategy_registered():
    register_ability(
        HONORABLE_STRATEGY,
        Ability(
            timings=(ActionTiming.OPEN,),
            label="Open: gain 1 Honor",
            cost=no_cost,
            targets=itself,
            effects=lambda game, source, target: [GainHonor(source.owner, 1)],
            hits_every_target=True,
            located_at=(CardLocation.HAND,),
        ),
    )


def test_doji_yasuko_draws_after_a_strategy_gains_a_player_honor():
    _honorable_strategy_registered()
    try:
        state = TableState.empty_two_seat()
        put_in_play(state, personality("yasuko", printed_id="doji_yasuko_soul_of_doji_takeji"))
        state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
            register(
                state,
                L5RCard.of(
                    ActionPrint,
                    id="probe",
                    name="Probe",
                    printed_id=HONORABLE_STRATEGY,
                    side=Side.FATE,
                    owner=P1,
                    gold_cost=0,
                ),
            )
        )
        state.decks[DeckKey(P1, Side.FATE)].cards = [
            register(
                state,
                L5RCard.of(
                    ActionPrint, id="top", printed_id="top", name="Top", side=Side.FATE, owner=P1
                ),
            )
        ]
        session = EngineSession.start(state, P1)

        session.act(P1, PlayStrategy("probe"))
        assert ActivateAbility("yasuko") in session.legal_actions(P1)
        session.act(P1, ActivateAbility("yasuko"))

        hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
        assert [card.id for card in hand] == ["top"]
    finally:
        _ABILITIES.pop(HONORABLE_STRATEGY)


# --- Doji Meiji, Regent (Experienced) ---

MEIJI = "doji_meiji_regent_experienced"


def _meiji(**overrides) -> L5RCard:
    fields = dict(chi=5, personal_honor=2)
    fields.update(overrides)
    return personality("meiji", printed_id=MEIJI, **fields)


def test_proclaiming_meiji_asks_whether_to_gain_his_chi_instead():
    game = two_seat_game()
    meiji = put_in_play(game, _meiji())

    resolve_action_effects(game, proclaim_gain_effects(game, meiji))

    assert isinstance(game.pending, Confirm)
    assert game.pending.prompt() == "Gain 5 Honor from Proclaiming instead of 2?"
    submit(game, DecisionResponse(game.pending.candidates))
    assert game.table.seats[P1].honor == 5


def _wind_named(owner: PlayerId, printed_id: str) -> L5RCard:
    return L5RCard.of(
        WindPrint,
        id=f"{owner.name}-wind",
        name=printed_id,
        printed_id=f"{owner.name}-wind" if printed_id is None else printed_id,
        side=Side.FATE,
        owner=owner,
    )


def _p2_ready_to_lobby(
    *, meiji_bowed: bool = False, p1_wind: str | None = "kanos_alliance", p2_wind: str | None = None
) -> GameState:
    game = two_seat_game(first_player=PlayerId.P2)
    meiji = put_in_play(game, _meiji())
    if meiji_bowed:
        meiji.bow()
    if p1_wind is not None:
        put_in_play(game, _wind_named(P1, p1_wind))
    if p2_wind is not None:
        put_in_play(game, _wind_named(PlayerId.P2, p2_wind))
    game.table.seats[PlayerId.P2].honor = 10
    put_in_play(game, personality("P2-courtier", owner=PlayerId.P2, personal_honor=2))
    proxies.spawn_rulebook_proxies(game)
    return game


def _p2_may_lobby(game: GameState) -> bool:
    return any(is_lobby(action) for action in legality.legal_actions(game, PlayerId.P2))


def test_an_unbowed_meiji_stops_a_seat_without_his_controllers_wind_lobbying():
    game = _p2_ready_to_lobby()

    assert not _p2_may_lobby(game)


def test_a_seat_sharing_meijis_controllers_wind_may_lobby():
    game = _p2_ready_to_lobby(p2_wind="kanos_alliance")

    assert _p2_may_lobby(game)


def test_a_bowed_meiji_stops_nobody():
    game = _p2_ready_to_lobby(meiji_bowed=True)

    assert _p2_may_lobby(game)


def test_meiji_stops_nobody_while_his_controller_has_no_wind():
    # "Your Wind" names a Wind his controller has. Without one the clause has no referent, and
    # the ruling here is that it does nothing.
    game = _p2_ready_to_lobby(p1_wind=None)

    assert _p2_may_lobby(game)


# --- Matsu Gonshiro, Soul of Matsu Shimei ---

GONSHIRO = "matsu_gonshiro_soul_of_matsu_shimei"


def _gonshiro_in_a_province() -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1, gold_production=8))
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [register(state, holding("refill", owner=P1))]
    gonshiro = register(state, personality("gonshiro", printed_id=GONSHIRO, gold_cost=6))
    gonshiro.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(gonshiro)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)
    return session


def test_gonshiro_is_dishonored_before_he_enters_play(reacting):
    # A card reacting to his entry sees him already dishonorable (CR, Timing: "before").
    seen: list[bool] = []
    reacting(
        EnteredPlay,
        "entry_probe",
        lambda ctx: seen.append(ctx.game.table.cards_by_id[ctx.event.card_id].dishonorable) or [],
    )
    session = _gonshiro_in_a_province()
    put_in_play(session.game, personality("probe", printed_id="entry_probe"))

    session.act(P1, ActivateAbility("gonshiro", RECRUIT))
    pay(session, P1)

    assert seen == [True]
    assert session.game.table.cards_by_id["gonshiro"] in session.game.table.battlefield.cards


def test_the_dishonoring_is_reacted_to_while_gonshiro_still_stands_in_his_province(reacting):
    reacting(
        Dishonored,
        "dishonor_probe",
        lambda ctx: [ask_who_loses_honor(ctx.game, P1, 1, ctx.card.id)],
    )
    session = _gonshiro_in_a_province()
    put_in_play(session.game, personality("probe", printed_id="dishonor_probe"))

    session.act(P1, ActivateAbility("gonshiro", RECRUIT))
    pay(session, P1)

    game = session.game
    assert isinstance(game.pending, ChooseOption)
    assert game.table.cards_by_id["gonshiro"] not in game.table.battlefield.cards
    session.submit(P1, DecisionResponse(("P2",)))
    assert game.table.cards_by_id["gonshiro"] in game.table.battlefield.cards
    assert game.table.cards_by_id["gonshiro"].dishonorable
    assert [card.id for card in game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards] == [
        "refill"
    ]


def test_gonshiros_own_trait_is_not_his_controllers_action():
    # Gihei reacts to "your action" dishonoring a card at his location, and a trait is not an
    # action (CR, Traits).
    session = _gonshiro_in_a_province()
    put_in_play(session.game, personality("gihei", printed_id="bayushi_gihei", force=3))

    session.act(P1, ActivateAbility("gonshiro", RECRUIT))
    pay(session, P1)

    game = session.game
    assert game.pending is None
    assert game.table.cards_by_id["gonshiro"].dishonorable
    assert effective_force(game, game.table.cards_by_id["gihei"]) == 3


def test_gonshiros_dishonoring_is_not_offered_at_the_recruits_interrupt_step():
    session = _gonshiro_in_a_province()
    game = session.game
    arrival = RecruitEffect("gonshiro", from_province=ZoneKey(P1, ZoneRole.PROVINCE, 0))

    assert forecast(game, tuple(recruit_effects(game, arrival))) == (arrival,)


def _gonshiro_attacking(*, dishonored: bool = True) -> EngineSession:
    """Gonshiro attacks into a 9-Gold unit and a 10-Gold one, with the Combat Segment open and the
    Defender passed."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, personality("gonshiro", printed_id=GONSHIRO, force=4, personal_honor=2))
    put_in_play(state, personality("cheap", owner=P2, force=2, gold_cost=5))
    attached(state, attachment("blade", attachment_type=AttachmentType.ITEM, gold_cost=4), "cheap")
    put_in_play(state, personality("costly", owner=P2, force=2, gold_cost=10))
    session = EngineSession.start(state, P1)
    if dishonored:
        session.game.table.cards_by_id["gonshiro"].dishonor()
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("gonshiro@0",)))
    session.submit(P2, DecisionResponse(("cheap@0", "costly@0")))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    session.act(P2, Pass())
    return session


def test_gonshiro_reaches_only_a_unit_costing_nine_or_less():
    session = _gonshiro_attacking()

    session.act(P1, ActivateAbility("gonshiro"))

    assert session.game.pending.candidates == ("cheap",)


def test_gonshiro_rehonors_to_destroy_the_unit_and_commits_seppuku_after_the_battle():
    session = _gonshiro_attacking()

    session.act(P1, ActivateAbility("gonshiro"))
    session.submit(P1, DecisionResponse(("cheap",)))
    on_board = {card.id for card in session.game.table.battlefield.cards}
    assert not session.game.table.cards_by_id["gonshiro"].dishonorable
    assert "cheap" not in on_board and "blade" not in on_board
    assert "gonshiro" in on_board

    session.act(P2, Pass())
    session.act(P1, Pass())

    gonshiro = session.game.table.cards_by_id["gonshiro"]
    assert gonshiro in session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)].cards
    assert not gonshiro.dishonorable
    # The 2 is for destroying the 10-Gold unit in resolution. Seppuku rehonors him first, so his
    # own death costs nothing.
    assert session.game.table.seats[P1].honor == 2


def test_gonshiro_is_withheld_while_honorable():
    session = _gonshiro_attacking(dishonored=False)

    assert ActivateAbility("gonshiro") not in session.legal_actions(P1)


# --- Shinjo Mayuko, Soul of Shinjo Wei ---

MAYUKO = "shinjo_mayuko_soul_of_shinjo_wei"


def _mayuko_attacking(*, dishonored: bool = False) -> EngineSession:
    """Mayuko attacks alone into three defenders, one too strong for either of her attacks, and
    the Combat Segment is open with the Defender having passed."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, personality("mayuko", printed_id=MAYUKO, force=2))
    put_in_play(state, personality("weak", owner=P2, force=3))
    put_in_play(state, personality("weaker", owner=P2, force=2))
    put_in_play(state, personality("strong", owner=P2, force=5))
    session = EngineSession.start(state, P1)
    if dishonored:
        session.game.table.cards_by_id["mayuko"].dishonor()
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("mayuko@0",)))
    session.submit(P2, DecisionResponse(("weak@0", "weaker@0", "strong@0")))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    session.act(P2, Pass())
    return session


def test_mayuko_dishonors_herself_for_two_consecutive_melee_attacks():
    session = _mayuko_attacking()

    session.act(P1, ActivateAbility("mayuko"))
    session.submit(P1, DecisionResponse(("weak",)))
    asked = session.game.pending
    assert asked is not None and set(asked.candidates) == {"weaker", "strong"}
    session.submit(P1, DecisionResponse(("weaker",)))

    table = session.game.table
    assert table.cards_by_id["mayuko"].dishonorable
    assert "weak" not in {card.id for card in table.battlefield.cards}
    assert "weaker" not in {card.id for card in table.battlefield.cards}
    assert "strong" in {card.id for card in table.battlefield.cards}


def test_mayuko_cannot_pay_her_dishonoring_twice():
    session = _mayuko_attacking(dishonored=True)

    assert ActivateAbility("mayuko") not in session.legal_actions(P1)


# --- Togashi Toyonobu, Soul of Togashi Binya ---


@pytest.mark.parametrize(
    ("target_force", "penalty"),
    [(5, 0), (1, 0), (2, -3)],
    ids=["lowered", "raised", "raised_from_below_zero"],
)
def test_togashi_toyonobu_sets_a_target_personalitys_force_to_his_own(target_force, penalty):
    session = combat_segment(
        [
            personality("toyonobu", printed_id="togashi_toyonobu_soul_of_togashi_binya", force=2),
            personality("target", owner=P2, force=target_force),
        ],
        {"toyonobu": 0},
        {"target": 0},
    )
    if penalty:
        session.game.ongoing.append(
            Modifier("penalty", "target", Stat.FORCE, penalty, Duration.UNTIL_END_OF_TURN)
        )

    session.act(P1, ActivateAbility("toyonobu"))
    session.submit(P1, DecisionResponse(("target",)))

    target = session.game.table.cards_by_id["target"]
    assert effective_force(session.game, target) == 2


# --- Daidoji Tashiko ---


def _tashiko_defending(*, raider_force: int, courtier: bool = False) -> EngineSession:
    """P1 attacks P2's Province with a raider of ``raider_force``. P2 defends with Tashiko (Force
    3), beside a Courtier of Personal Honor 3 when asked, and the session is left in the Engage
    Segment with the Defender holding the opportunity."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, personality("raider", force=raider_force))
    put_in_play(state, personality("tashiko", owner=P2, printed_id="daidoji_tashiko", force=3))
    defenders = ["tashiko@0"]
    if courtier:
        put_in_play(
            state,
            personality(
                "courtier", owner=P2, personal_honor=3, keywords=(keywords.COURTIER,), force=1
            ),
        )
        defenders.append("courtier@0")
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(P2, DecisionResponse(tuple(defenders)))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    return session


def _resolve_the_battle(session: EngineSession) -> None:
    while session.game.attack.current is not None:
        session.act(session.game.round.priority, Pass())


def test_tashiko_gains_the_highest_courtier_honor_as_force_while_opposed():
    session = _tashiko_defending(raider_force=1, courtier=True)

    assert effective_force(session.game, session.game.table.cards_by_id["tashiko"]) == 3 + 3


def test_tashiko_gains_nothing_from_an_army_without_courtiers():
    session = _tashiko_defending(raider_force=1)

    assert effective_force(session.game, session.game.table.cards_by_id["tashiko"]) == 3


def test_tashiko_gains_honor_after_a_battle_that_leaves_her_province_standing():
    session = _tashiko_defending(raider_force=1)
    session.act(P2, ActivateAbility("tashiko"))
    honor_before_resolution = session.game.table.seats[P2].honor

    _resolve_the_battle(session)

    outcome = session.game.attack.battlefields[0].outcome
    assert outcome.province_destroyed is False
    assert session.game.table.seats[P2].honor == honor_before_resolution + outcome.honor[P2] + 2


def test_tashiko_gains_nothing_when_her_province_falls():
    session = _tashiko_defending(raider_force=9)
    session.act(P2, ActivateAbility("tashiko"))

    _resolve_the_battle(session)

    outcome = session.game.attack.battlefields[0].outcome
    assert outcome.province_destroyed is True
    assert session.game.table.seats[P2].honor == outcome.honor.get(P2, 0)


# --- The five Rings ---

MOVE_PROBE = "probe_battle_move_an_enemy_home"


def _ring(card_id: str, printed_id: str, owner: PlayerId = P1) -> L5RCard:
    return L5RCard.of(
        RingPrint,
        id=card_id,
        name=printed_id,
        printed_id=card_id if printed_id is None else printed_id,
        side=Side.FATE,
        owner=owner,
    )


def _ring_game(*in_play: L5RCard, held: tuple[L5RCard, ...] = ()) -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    for card in in_play:
        put_in_play(state, register(state, card))
    for card in held:
        state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
    return EngineSession.start(state, P1)


def _answer_until_settled(session: EngineSession, *answers: str) -> None:
    """Answer each decision the action raises: a named answer where one of ``answers`` is among
    the candidates, an empty answer to everything else, payments included."""
    pending = session.game.pending
    while pending is not None:
        named = [each for each in answers if each in getattr(pending, "candidates", ())]
        session.submit(pending.seat, DecisionResponse(tuple(named[:1])))
        pending = session.game.pending


def _in_play(session: EngineSession) -> set[str]:
    return {card.id for card in session.game.table.battlefield.cards}


def _fate_discard(session: EngineSession, seat: PlayerId) -> set[str]:
    pile = session.game.table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)]
    return {card.id for card in pile.cards}


def _ring_of_air_unit_game() -> EngineSession:
    """P1 holding the Ring, a bowed Personality carrying a bowed Follower, and a second bowed
    Personality in a unit of his own."""
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    put_in_play(state, personality("samurai"))
    attached(state, attachment("guard", attachment_type=AttachmentType.FOLLOWER), "samurai")
    put_in_play(state, personality("other"))
    put_in_play(state, register(state, _ring("air", "ring_of_air")))
    session = EngineSession.start(state, P1)
    for card_id in ("samurai", "guard", "other"):
        session.game.table.cards_by_id[card_id].bow()
    return session


def test_ring_of_air_straightens_two_bowed_cards_of_one_unit():
    session = _ring_of_air_unit_game()

    session.act(P1, ActivateAbility("air", "air"))
    session.submit(P1, DecisionResponse(("samurai", "guard")))

    cards = session.game.table.cards_by_id
    assert not cards["samurai"].bowed and not cards["guard"].bowed
    assert cards["air"].bowed


def test_ring_of_air_asks_for_both_cards_before_either_straightens():
    session = _ring_of_air_unit_game()

    session.act(P1, ActivateAbility("air", "air"))

    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget)
    assert (pending.minimum, pending.maximum) == (1, 2)
    assert session.game.table.cards_by_id["samurai"].bowed
    # Both cards of the unit stay on offer after the first is picked, and the other unit does not.
    assert set(pending.selectable(DecisionResponse(("samurai",)))) == {"samurai", "guard"}
    assert pending.accepts(DecisionResponse(("samurai", "other"))) is False


def test_ring_of_air_asks_for_its_targets_without_restating_the_count():
    # The prompt composes the count, so a targeting message that spells it out again reads "Target
    # 1 to 2 of one or two of your bowed cards".
    session = _ring_of_air_unit_game()

    session.act(P1, ActivateAbility("air", "air"))

    assert session.game.pending.prompt().endswith("target 1 or 2 of your bowed cards in one unit")


def test_ring_of_air_straightens_one_card_of_a_unit_of_one():
    session = _ring_of_air_unit_game()

    session.act(P1, ActivateAbility("air", "air"))
    session.submit(P1, DecisionResponse(("other",)))

    cards = session.game.table.cards_by_id
    assert not cards["other"].bowed
    assert cards["samurai"].bowed and cards["guard"].bowed


def test_ring_of_air_is_not_offered_with_nothing_bowed_to_straighten():
    session = _ring_game(personality("samurai"), _ring("air", "ring_of_air"))

    assert ActivateAbility("air", "air") not in session.legal_actions(P1)


def test_ring_of_air_pitched_from_hand_straightens_one_and_is_discarded():
    session = _ring_game(personality("samurai"), held=(_ring("air", "ring_of_air"),))
    session.game.table.cards_by_id["samurai"].bow()

    session.act(P1, PlayStrategy("air", PITCH))
    _answer_until_settled(session, "samurai")

    assert not session.game.table.cards_by_id["samurai"].bowed
    assert "air" in _fate_discard(session, P1)


def test_ring_of_the_void_has_no_action_entry_and_draws_as_an_open_action():
    session = _ring_game(
        _ring("void", "ring_of_the_void"), held=(_ring("held", "ring_of_the_void"),)
    )
    state = session.game.table
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("top", P1))]
    assert PlayStrategy("held", "enter") not in session.legal_actions(P1)

    session.act(P1, ActivateAbility("void", "void"))

    hand = [card.id for card in state.zones[ZoneKey(P1, ZoneRole.HAND)].cards]
    assert hand == ["held", "top"]
    # The draw fulfills the held Ring's "Play if", which is answered before the action's discard
    # (CR 20F, Timing).
    entry = session.game.pending
    assert isinstance(entry, Confirm) and entry.source_id == "held"
    session.submit(P1, DecisionResponse(()))
    assert isinstance(session.game.pending, ChooseDiscard)


def _enemy_personalities(game, source):
    return [card.id for card in personalities_in_play(game) if card.owner is not source.owner]


MOVE_ABILITY = Ability(
    timings=(ActionTiming.BATTLE,),
    label="Battle: move a target enemy Personality home",
    cost=no_cost,
    targets=_enemy_personalities,
    effects=lambda game, source, target: [Move(target.id, Location.home(target.owner))],
)


def _ring_battle(
    *,
    raider_printed_id: str | None = None,
    guard_force: int = 3,
    raider_chi: int = 3,
    in_play: tuple[L5RCard, ...] = (),
    held: tuple[L5RCard, ...] = (),
    discarded: tuple[L5RCard, ...] = (),
) -> EngineSession:
    """P1 attacks P2's Province with a raider; P2 defends with a guard. Left in the Combat Segment
    with P1 holding the opportunity."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, personality("raider", force=2, chi=raider_chi, printed_id=raider_printed_id))
    put_in_play(state, personality("guard", owner=P2, force=guard_force))
    for card in in_play:
        put_in_play(state, register(state, card))
    for card in held:
        state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
    for card in discarded:
        state.zones[ZoneKey(card.owner, ZoneRole.FATE_DISCARD)].add(register(state, card))
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(P2, DecisionResponse(("guard@0",)))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    if session.game.round.priority is not P1:
        session.act(P2, Pass())
    return session


def test_ring_of_fire_lowers_an_enemy_personalitys_force_for_the_turn():
    session = _ring_battle(guard_force=6, in_play=(_ring("fire", "ring_of_fire"),))

    session.act(P1, ActivateAbility("fire", "fire"))
    _answer_until_settled(session, "guard")

    assert effective_force(session.game, session.game.table.cards_by_id["guard"]) == 6 - 4


DUEL_PROBE = "probe_battle_challenge_to_a_duel"
DUEL_ABILITY = Ability(
    timings=(ActionTiming.OPEN, ActionTiming.BATTLE),
    label="Open or Battle: challenge a target enemy Personality to a duel",
    cost=no_cost,
    targets=_enemy_personalities,
    effects=lambda game, source, target: [StartDuel(source.id, target.id, source.id)],
)


def _focusers(p1_focus: int | None) -> tuple[L5RCard, ...]:
    """P2's Focus Value 1 card, and P1's of ``p1_focus`` when one is given."""
    cards = [focus_card("P2-fv", P2, 1)]
    if p1_focus is not None:
        cards.append(focus_card("P1-fv", P1, p1_focus))
    return tuple(cards)


def _duel(session: EngineSession) -> None:
    """P1's raider challenges P2's guard. Each seat focuses its one focusing card, if it holds one,
    the first time it is asked, and strikes after. P2 is asked first."""
    session.act(P1, ActivateAbility("raider"))
    session.submit(P1, DecisionResponse(("guard",)))
    while isinstance(session.game.pending, FocusOrStrike):
        pending = session.game.pending
        token = focus_token(f"{pending.seat.name}-fv")
        answer = token if token in pending.candidates else STRIKE
        session.submit(pending.seat, DecisionResponse((answer,)))


# --- the Edicts' Focus Effects ---


def _edict_duel(
    edict_id: str,
    *,
    holder: PlayerId = P1,
    p1_focus: int | None = 1,
    guard_force: int = 3,
    raider_chi: int = 3,
) -> EngineSession:
    """A duel inside a battle with the named Edict focused by ``holder``, beside P2's focusing card.

    The Edict is focused from hand rather than played, which is the only way its Focus Effect is
    reached: a card in hand is a focus source whatever else it could do. P1's raider is always the
    challenger, so ``holder`` is what tells a challenger's Edict from a challenged seat's.
    """
    edict = focus_card("edict", holder, 0, printed_id=edict_id)
    others = _focusers(p1_focus) if holder is P1 else ()
    session = _ring_battle(
        raider_printed_id=DUEL_PROBE,
        guard_force=guard_force,
        raider_chi=raider_chi,
        held=(*others, edict),
    )
    session.act(P1, ActivateAbility("raider"))
    session.submit(P1, DecisionResponse(("guard",)))
    while isinstance(session.game.pending, FocusOrStrike):
        pending = session.game.pending
        wanted = focus_token("edict") if pending.seat is holder else focus_token("P2-fv")
        answer = wanted if wanted in pending.candidates else STRIKE
        session.submit(pending.seat, DecisionResponse((answer,)))
    return session


def test_way_of_the_crab_makes_the_duel_compare_force():
    # The raider's Chi is 3 and its Force 2, and the guard is given 9 Force, so a duel on Chi goes
    # the other way.
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _edict_duel("way_of_the_crab_experienced", p1_focus=None, guard_force=9)

        outcome = session.game.duel.outcome
        assert outcome.totals == {P1: 2, P2: 9 + 1}
        assert outcome.winners == (P2,)


def test_way_of_the_crane_honors_you_and_strengthens_your_provinces_when_you_win():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _edict_duel("way_of_the_crane_experienced", raider_chi=5)

        assert session.game.duel.outcome.winners == (P1,)
        assert session.game.table.seats[P1].honor == 1
        # No Stronghold is in play, so a Province's printed base is nothing and the bonus is all
        # of its strength.
        province = ZoneKey(P1, ZoneRole.PROVINCE, 0)
        assert effective_province_strength(session.game, province) == 1


def test_way_of_the_crane_does_nothing_when_you_lose():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _edict_duel("way_of_the_crane_experienced", p1_focus=None)

        assert session.game.duel.outcome.winners == (P2,)
        assert session.game.table.seats[P1].honor == 0
        assert effective_province_strength(session.game, ZoneKey(P1, ZoneRole.PROVINCE, 0)) == 0


def test_way_of_the_scorpion_dishonors_the_winner_only_for_the_challenged_seat():
    # P1 created the duel, so P1 focusing the Edict is the challenger and nothing happens.
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _edict_duel("way_of_the_scorpion_experienced", raider_chi=5)

        assert session.game.duel.outcome.winners == (P1,)
        assert session.game.table.cards_by_id["raider"].dishonorable is False


def test_way_of_the_scorpion_dishonors_the_winner_for_the_seat_that_was_challenged():
    # P2 is the challenged seat, so its Edict dishonors whoever won, which here is P2's own guard.
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _edict_duel("way_of_the_scorpion_experienced", holder=P2, raider_chi=1)

        assert session.game.duel.outcome.winners == (P2,)
        assert session.game.table.cards_by_id["guard"].dishonorable is True


def _ring_of_fire_offered(session: EngineSession) -> bool:
    pending = session.game.pending
    return isinstance(pending, Confirm) and pending.candidates == ("fire",)


@pytest.mark.parametrize(
    ("raider_chi", "focus"),
    [(2, 3), (3, 2)],
    ids=["entered with the lower duel stat", "entered level"],
)
def test_ring_of_fire_is_offered_after_winning_a_battle_duel_entered_without_the_higher_stat(
    raider_chi, focus
):
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _ring_battle(
            raider_printed_id=DUEL_PROBE,
            raider_chi=raider_chi,
            held=(_ring("fire", "ring_of_fire"), *_focusers(focus)),
        )
        _duel(session)

        assert _ring_of_fire_offered(session)
        session.submit(P1, DecisionResponse(("fire",)))

    assert "fire" in _in_play(session)


@pytest.mark.parametrize(
    "raider_chi",
    [5, 2],
    ids=["won having entered with the higher duel stat", "lost"],
)
def test_ring_of_fire_is_not_offered_after_a_duel_won_on_the_higher_stat_or_lost(raider_chi):
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _ring_battle(
            raider_printed_id=DUEL_PROBE,
            raider_chi=raider_chi,
            held=(_ring("fire", "ring_of_fire"), *_focusers(None)),
        )
        _duel(session)

        assert not _ring_of_fire_offered(session)


def test_ring_of_fire_is_not_offered_after_winning_a_duel_outside_a_battle():
    state = TableState.empty_two_seat()
    put_in_play(state, personality("raider", chi=2, printed_id=DUEL_PROBE))
    put_in_play(state, personality("guard", owner=P2))
    for card in (_ring("fire", "ring_of_fire"), *_focusers(3)):
        state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = EngineSession.start(state, P1)
        _duel(session)

        assert not _ring_of_fire_offered(session)


def test_ring_of_water_moves_a_personality_to_the_battlefield_and_another_home():
    session = _ring_battle(in_play=(_ring("water", "ring_of_water"), personality("reserve")))

    session.act(P1, ActivateAbility("water", "water"))
    _answer_until_settled(session, "reserve")
    table = session.game.table
    assert location_of(table, table.cards_by_id["reserve"]).battlefield == 0

    session.act(P2, Pass())
    table.cards_by_id["water"].unbow()
    session.act(P1, ActivateAbility("water", "water"))
    _answer_until_settled(session, "raider")

    assert location_of(table, table.cards_by_id["raider"]).is_home


def test_ring_of_earth_negates_the_battle_actions_move():
    with probe_ability(MOVE_PROBE, MOVE_ABILITY):
        session = _ring_battle(
            raider_printed_id=MOVE_PROBE, in_play=(_ring("earth", "ring_of_earth", P2),)
        )
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("guard",)))

        session.act(P2, PlayInterrupt("earth"))
        _answer_until_settled(session)

        table = session.game.table
        assert location_of(table, table.cards_by_id["guard"]).battlefield == 0
        assert table.cards_by_id["earth"].bowed


def test_ring_of_earth_pitched_from_hand_negates_the_move_and_is_discarded():
    with probe_ability(MOVE_PROBE, MOVE_ABILITY):
        session = _ring_battle(
            raider_printed_id=MOVE_PROBE, held=(_ring("earth", "ring_of_earth", P2),)
        )
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("guard",)))

        session.act(P2, PlayInterrupt("earth"))
        _answer_until_settled(session)

        table = session.game.table
        assert location_of(table, table.cards_by_id["guard"]).battlefield == 0
        assert "earth" in _fate_discard(session, P2)


# --- The Enlightened Path of the Dragon ---

ENLIGHTENED_PATH = "the_enlightened_path_of_the_dragon"


def _fate_deck(session: EngineSession, seat: PlayerId) -> set[str]:
    return {card.id for card in session.game.table.decks[DeckKey(seat, Side.FATE)].cards}


def test_the_enlightened_path_takes_a_discarded_rings_battle_then_reshuffles_it():
    session = _ring_battle(
        guard_force=6,
        in_play=(stronghold(P1, printed_id=ENLIGHTENED_PATH),),
        discarded=(_ring("fire", "ring_of_fire"),),
    )

    session.act(P1, ActivateAbility("P1-SH"))
    _answer_until_settled(session, "fire")

    assert session.legal_actions(P1) == [Pass(), ActivateAbility("fire", ENLIGHTENED_PATH_COPY)]

    session.act(P1, ActivateAbility("fire", ENLIGHTENED_PATH_COPY))
    _answer_until_settled(session, "guard")

    assert effective_force(session.game, session.game.table.cards_by_id["guard"]) == 6 - 4
    assert "fire" in _fate_deck(session, P1)
    assert not any(isinstance(held, SeatAbilityGrant) for held in session.game.ongoing)


def test_the_enlightened_path_reshuffles_the_ring_when_the_additional_action_is_passed():
    session = _ring_battle(
        in_play=(stronghold(P1, printed_id=ENLIGHTENED_PATH),),
        discarded=(_ring("fire", "ring_of_fire"),),
    )
    session.act(P1, ActivateAbility("P1-SH"))
    _answer_until_settled(session, "fire")

    session.act(P1, Pass())

    assert "fire" in _fate_deck(session, P1)


def test_the_enlightened_path_takes_a_ring_in_play_ignoring_its_bow_cost():
    session = _ring_battle(
        guard_force=6,
        in_play=(stronghold(P1, printed_id=ENLIGHTENED_PATH), _ring("fire", "ring_of_fire")),
    )

    session.act(P1, ActivateAbility("P1-SH"))
    _answer_until_settled(session, "fire")
    session.act(P1, ActivateAbility("fire", ENLIGHTENED_PATH_COPY))
    _answer_until_settled(session, "guard")

    table = session.game.table
    assert effective_force(session.game, table.cards_by_id["guard"]) == 6 - 4
    assert not table.cards_by_id["fire"].bowed
    assert "fire" in _in_play(session)


def test_the_enlightened_path_skips_a_bowed_ring_in_play():
    session = _ring_battle(
        in_play=(stronghold(P1, printed_id=ENLIGHTENED_PATH), _ring("fire", "ring_of_fire"))
    )
    session.game.table.cards_by_id["fire"].bow()

    assert ActivateAbility("P1-SH") not in session.legal_actions(P1)


@pytest.mark.parametrize("used_as_a_battle", [False, True])
def test_the_enlightened_path_taken_as_a_battle_spends_its_interrupt(used_as_a_battle):
    with probe_ability(MOVE_PROBE, MOVE_ABILITY):
        session = _ring_battle(
            raider_printed_id=MOVE_PROBE,
            in_play=(stronghold(P1, printed_id=ENLIGHTENED_PATH),),
            discarded=(_ring("earth", "ring_of_earth"), _ring("fire", "ring_of_fire")),
        )
        if used_as_a_battle:
            session.act(P1, ActivateAbility("P1-SH"))
            _answer_until_settled(session, "fire")
            session.act(P1, ActivateAbility("fire", ENLIGHTENED_PATH_COPY))
            _answer_until_settled(session, "guard")
            session.act(P2, Pass())

        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("guard",)))

        offered = PlayInterrupt("P1-SH") in session.legal_actions(P1)
        assert offered is not used_as_a_battle


def test_the_enlightened_path_takes_a_discarded_rings_interrupt_then_spends_its_one_use():
    with probe_ability(MOVE_PROBE, MOVE_ABILITY):
        session = _ring_battle(
            raider_printed_id=MOVE_PROBE,
            in_play=(stronghold(P2, printed_id=ENLIGHTENED_PATH),),
            discarded=(_ring("earth", "ring_of_earth", P2), _ring("fire", "ring_of_fire", P2)),
        )
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("guard",)))

        session.act(P2, PlayInterrupt("P2-SH"))
        _answer_until_settled(session, "earth")
        session.act(P2, PlayInterrupt("earth", ENLIGHTENED_PATH_COPY))
        _answer_until_settled(session)

        table = session.game.table
        assert location_of(table, table.cards_by_id["guard"]).battlefield == 0
        assert "earth" in _fate_deck(session, P2)
        assert session.game.round.priority is P2
        assert ActivateAbility("P2-SH") not in session.legal_actions(P2)


def test_the_enlightened_path_takes_a_discarded_earths_interrupt_against_refugees():
    session = _refugees_battle()
    table = session.game.table
    put_in_play(table, register(table, stronghold(P1, printed_id=ENLIGHTENED_PATH)))
    table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].add(
        register(table, _ring("earth", "ring_of_earth"))
    )
    _reach_the_combat_segment(session, P2)
    session.act(P2, PlayStrategy("refugees"))
    session.submit(P2, DecisionResponse(("raider",)))

    session.act(P1, PlayInterrupt("P1-SH"))
    _answer_until_settled(session, "earth")
    session.act(P1, PlayInterrupt("earth", ENLIGHTENED_PATH_COPY))
    _answer_until_settled(session)

    raider = table.cards_by_id["raider"]
    assert location_of(table, raider).battlefield == 0
    assert not raider.bowed
    assert "earth" in _fate_deck(session, P1)


def test_the_enlightened_path_back_takes_an_open_from_the_discard_pile():
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1, printed_id=f"{ENLIGHTENED_PATH}__back")))
    state.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].add(
        register(state, _ring("void", "ring_of_the_void"))
    )
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("drawn", P1))]
    session = EngineSession.start(state, P1)

    session.act(P1, ActivateAbility("P1-SH"))
    _answer_until_settled(session, "void")
    session.act(P1, ActivateAbility("void", ENLIGHTENED_PATH_COPY))
    _answer_until_settled(session)

    assert _fate_deck(session, P1) == {"void"}
    assert "drawn" in _fate_discard(session, P1)


def test_the_enlightened_path_front_is_not_taken_as_an_open():
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1, printed_id=ENLIGHTENED_PATH)))
    state.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].add(
        register(state, _ring("void", "ring_of_the_void"))
    )
    session = EngineSession.start(state, P1)

    assert ActivateAbility("P1-SH") not in session.legal_actions(P1)


FAVOR_PROBE = "favor_probe_shattered"
register_ability(
    FAVOR_PROBE,
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Favor Open: nothing",
        cost=no_cost,
        targets=itself,
        effects=lambda game, source, target: [],
        hits_every_target=True,
        repeatable=True,
    ),
)


def _favor_twice(session: EngineSession) -> None:
    session.act(P1, ActivateAbility("favor"))
    session.act(P2, Pass())
    session.act(P1, ActivateAbility("favor"))


def _air_in_hand_game() -> EngineSession:
    return _ring_game(
        holding("favor", printed_id=FAVOR_PROBE, keywords=(keywords.FAVOR,)),
        held=(_ring("air", "ring_of_air"),),
    )


def test_ring_of_air_is_offered_after_the_second_favor_action_of_the_turn():
    session = _air_in_hand_game()

    session.act(P1, ActivateAbility("favor"))
    assert session.game.pending is None
    session.act(P2, Pass())
    session.act(P1, ActivateAbility("favor"))

    assert isinstance(session.game.pending, Confirm) and session.game.pending.seat is P1
    assert project(session.game, P2).pending is None


def test_ring_of_air_question_cannot_be_backed_out_of():
    # Backing out would unwind the Favor action that resolved, which the Ring only reacts to.
    session = _air_in_hand_game()
    _favor_twice(session)

    assert not session.can_cancel(P1)
    with pytest.raises(ValueError, match="a trigger asked"):
        session.cancel(P1)


def test_ring_of_air_enters_play_on_yes_and_is_offered_again_after_a_third():
    session = _air_in_hand_game()
    _favor_twice(session)
    session.submit(P1, DecisionResponse(()))
    assert "air" not in _in_play(session)

    session.act(P2, Pass())
    session.act(P1, ActivateAbility("favor"))
    session.submit(P1, DecisionResponse(("air",)))

    assert "air" in _in_play(session)


def test_ring_of_air_is_not_offered_by_the_opponents_favor_actions():
    session = _ring_game(
        holding("favor", owner=P2, printed_id=FAVOR_PROBE, keywords=(keywords.FAVOR,)),
        held=(_ring("air", "ring_of_air"),),
    )
    session.act(P1, Pass())
    session.act(P2, ActivateAbility("favor"))
    session.act(P1, Pass())
    session.act(P2, ActivateAbility("favor"))

    assert session.game.pending is None


def _earth_battle(
    *,
    attacker: PlayerId,
    raider_force: int = 1,
    assign_raider: bool = True,
) -> EngineSession:
    """``attacker`` attacks the other seat's first Province with a raider of ``raider_force``; the
    Defender holds a guard of Force 3 and a second Province, so a lost battle does not end the
    game. Ring of Earth waits in P1's hand. Left on the resolution's first question, or on the
    choice of the next battlefield when it asks none."""
    defender = P2 if attacker is P1 else P1
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=defender, index=0)
    province_card(state, "def-prov1", seat=defender, index=1)
    province_card(state, "atk-prov0", seat=attacker, index=0)
    put_in_play(state, personality("raider", owner=attacker, force=raider_force))
    put_in_play(state, personality("guard", owner=defender, force=3))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, _ring("earth", "ring_of_earth")))
    session = EngineSession.start(state, attacker)
    end_phase(session)
    session.act(attacker, DeclareAttack())
    session.submit(attacker, DecisionResponse(("raider@0",) if assign_raider else ()))
    session.submit(defender, DecisionResponse(("guard@0",)))
    session.submit(attacker, DecisionResponse(("0",)))
    while session.game.pending is None and session.game.attack.current is not None:
        session.act(session.game.round.priority, Pass())
    return session


def test_ring_of_earth_is_offered_after_defending_a_province_that_stood():
    session = _earth_battle(attacker=P2)

    assert isinstance(session.game.pending, Confirm) and session.game.pending.seat is P1
    session.submit(P1, DecisionResponse(("earth",)))

    assert "earth" in _in_play(session)


def test_ring_of_earth_is_not_offered_when_the_province_fell():
    session = _earth_battle(attacker=P2, raider_force=9)

    assert not isinstance(session.game.pending, Confirm)


def test_ring_of_earth_is_not_offered_to_the_attacker():
    session = _earth_battle(attacker=P1)

    assert not isinstance(session.game.pending, Confirm)


def test_ring_of_earth_is_not_offered_when_no_enemy_unit_was_ever_at_the_battlefield():
    session = _earth_battle(attacker=P2, assign_raider=False)

    assert not isinstance(session.game.pending, Confirm)


def _water_battle(*, raider_force: int, terrain_owner: PlayerId | None) -> EngineSession:
    """P1 attacks P2's first Province with a raider of ``raider_force`` against a guard of Force 3,
    with a Terrain owned by ``terrain_owner`` at the battlefield, or none. P2 keeps a second
    Province. Ring of Water waits in P1's hand. Left on the resolution's first question, or on the
    choice of the next battlefield when it asks none."""
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=P2, index=0)
    province_card(state, "def-prov1", seat=P2, index=1)
    province_card(state, "atk-prov0", seat=P1, index=0)
    put_in_play(state, personality("raider", owner=P1, force=raider_force))
    put_in_play(state, personality("guard", owner=P2, force=3))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, _ring("water", "ring_of_water")))
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(P2, DecisionResponse(("guard@0",)))
    session.submit(P1, DecisionResponse(("0",)))
    if terrain_owner is not None:
        terrain_at(session.game, "ground", battlefield=0, owner=terrain_owner)
    while session.game.pending is None and session.game.attack.current is not None:
        session.act(session.game.round.priority, Pass())
    return session


def test_ring_of_water_is_offered_after_destroying_a_province_where_you_control_a_terrain():
    session = _water_battle(raider_force=9, terrain_owner=P1)

    assert isinstance(session.game.pending, Confirm) and session.game.pending.seat is P1
    session.submit(P1, DecisionResponse(("water",)))

    assert "water" in _in_play(session)


@pytest.mark.parametrize(
    ("raider_force", "terrain_owner"),
    [(1, P1), (9, P2), (9, None)],
    ids=["province-stood", "enemy-terrain", "no-terrain"],
)
def test_ring_of_water_is_not_offered_otherwise(raider_force, terrain_owner):
    session = _water_battle(raider_force=raider_force, terrain_owner=terrain_owner)

    assert not isinstance(session.game.pending, Confirm)


def _void_equip_game(*also_held: L5RCard, holds_favor: bool = False) -> EngineSession:
    """P1's "bearer" in play and Ring of the Void and a Follower in P1's hand beside ``also_held``,
    with the Imperial Favor's proxy in hand too when ``holds_favor``. Left after P1 equips the
    Follower to "bearer", which puts one Fate card in play and takes one out of hand."""
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    put_in_play(state, personality("bearer", owner=P1))
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    hand = state.zones[ZoneKey(P1, ZoneRole.HAND)]
    hand.add(register(state, _ring("void", "ring_of_the_void")))
    hand.add(register(state, attachment("ashigaru", attachment_type=AttachmentType.FOLLOWER)))
    for card in also_held:
        hand.add(register(state, card))
    session = EngineSession.start(state, P1)
    if holds_favor:
        resolve_effects(session.game, [TakeFavor(P1)])
    session.act(P1, Equip("ashigaru"))
    session.submit(P1, DecisionResponse(("bearer",)))
    return session


def _void_offered(session: EngineSession, ring_id: str = "void") -> bool:
    pending = session.game.pending
    return isinstance(pending, Confirm) and pending.seat is P1 and ring_id in pending.candidates


def _void_game(*held: L5RCard, in_play: int) -> EngineSession:
    """P1's "bearer" carrying ``in_play`` Followers, "follower0" upward, and Ring of the Void in
    P1's hand beside ``held``, started with no action taken."""
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1, gold_production=1)))
    put_in_play(state, personality("bearer", owner=P1))
    for index in range(in_play):
        follower = attachment(f"follower{index}", attachment_type=AttachmentType.FOLLOWER)
        attached(state, register(state, follower), "bearer")
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    hand = state.zones[ZoneKey(P1, ZoneRole.HAND)]
    for card in (_ring("void", "ring_of_the_void"), *held):
        hand.add(register(state, card))
    return EngineSession.start(state, P1)


def test_ring_of_the_void_is_offered_when_fate_cards_in_play_come_to_match_the_hand():
    session = _void_equip_game(fate_card("spare", P1))

    assert _void_offered(session)
    session.submit(P1, DecisionResponse(("void",)))
    assert "void" in _in_play(session)
    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert [card.id for card in hand] == ["spare"]


def test_ring_of_the_void_is_offered_before_a_trigger_that_would_break_its_count(reacting):
    # A Ring may enter immediately after its condition is fulfilled (CR, Ring), so its offer comes
    # ahead of a draw the same entry set off, which would leave the hand one card larger.
    def _draw(ctx):
        return [DrawCard(P1)]

    reacting(EnteredPlay, "probe_drawer", _draw)
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    put_in_play(state, holding("drawer", owner=P1, printed_id="probe_drawer"))
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("drawn", P1))]
    hand = state.zones[ZoneKey(P1, ZoneRole.HAND)]
    for card in (
        _ring("void", "ring_of_the_void"),
        fate_card("entering", P1),
        fate_card("spare", P1),
    ):
        hand.add(register(state, card))
    session = EngineSession.start(state, P1)

    resolve_effects(session.game, [PutIntoPlay("entering")])

    assert _void_offered(session)
    assert "drawn" in _fate_deck(session, P1)


def test_a_second_ring_of_the_void_is_not_offered_once_the_first_breaks_its_count():
    session = _void_equip_game(_ring("void2", "ring_of_the_void"))

    assert _void_offered(session, "void")
    session.submit(P1, DecisionResponse(("void",)))

    assert "void" in _in_play(session)
    assert not _void_offered(session, "void2")


def test_declining_ring_of_the_void_is_not_offered_again_while_the_count_still_matches():
    session = _void_equip_game(fate_card("spare", P1))

    session.submit(P1, DecisionResponse(()))
    resolve_effects(session.game, [GainHonor(P1, 1)])

    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert any(card.id == "void" for card in hand)
    assert "void" not in _in_play(session)
    assert not _void_offered(session)


_GAIN_HONOR = Ability(
    timings=(ActionTiming.OPEN,),
    label="Open: gain 1 Honor",
    cost=no_cost,
    targets=itself,
    effects=lambda game, source, target: [GainHonor(source.owner, 1)],
    hits_every_target=True,
    located_at=(CardLocation.HAND,),
)


def test_ring_of_the_void_is_not_offered_while_an_equipped_card_waits_to_enter():
    # Announcing the Equip takes the Follower out of hand, so for a moment no Fate card is in play
    # and none is in hand. The card is in its entering-play area, and once it lands one is in play
    # against none in hand.
    session = _void_game(
        attachment("played", attachment_type=AttachmentType.FOLLOWER, gold_cost=1), in_play=0
    )

    session.act(P1, Equip("played"))
    assert isinstance(session.game.pending, ChoosePayment)
    pay(session, P1)
    session.submit(P1, DecisionResponse(("bearer",)))

    assert "played" in _in_play(session)
    assert not _void_offered(session)


def test_ring_of_the_void_is_not_offered_while_a_strategy_can_still_be_cancelled():
    # Announcing the Strategy takes it out of hand, leaving none in hand against none in play, but
    # the action can still be backed out of, so nothing is judged until it resolves.
    played = L5RCard.of(
        ActionPrint,
        id="played",
        name="Played",
        printed_id="probe_gain_honor",
        side=Side.FATE,
        owner=P1,
        gold_cost=1,
    )
    session = _void_game(played, in_play=0)

    with probe_ability("probe_gain_honor", _GAIN_HONOR):
        session.act(P1, PlayStrategy("played"))

        assert isinstance(session.game.pending, ChoosePayment)
        assert session.can_cancel(P1)

        session.cancel(P1)

    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert {card.id for card in hand} == {"void", "played"}
    assert session.game.pending is None


def test_ring_of_the_void_is_offered_once_a_strategy_has_left_the_resolution_area():
    played = L5RCard.of(
        ActionPrint,
        id="played",
        name="Played",
        printed_id="probe_gain_honor",
        side=Side.FATE,
        owner=P1,
        gold_cost=1,
    )
    session = _void_game(played, in_play=0)

    with probe_ability("probe_gain_honor", _GAIN_HONOR):
        session.act(P1, PlayStrategy("played"))
        assert isinstance(session.game.pending, ChoosePayment)
        pay(session, P1)

        assert _void_offered(session)


@pytest.mark.parametrize(
    ("in_play", "held", "effect"),
    [
        (1, 2, Discard("held1", P2)),
        (2, 1, Destroy("follower1", P2)),
    ],
    ids=["discarded-from-hand", "destroyed-in-play"],
)
def test_ring_of_the_void_is_offered_whoever_brings_the_counts_together(in_play, held, effect):
    session = _void_game(*(fate_card(f"held{index}", P1) for index in range(held)), in_play=in_play)

    resolve_effects(session.game, [effect])

    assert _void_offered(session)


def test_each_ring_of_the_void_in_hand_is_offered():
    session = _void_game(_ring("void2", "ring_of_the_void"), fate_card("held", P1), in_play=1)

    resolve_effects(session.game, [Discard("held", P1)])
    offered = session.game.pending.candidates
    session.submit(P1, DecisionResponse(()))

    assert {*offered, *session.game.pending.candidates} == {"void", "void2"}


def test_ring_of_the_void_does_not_count_itself_in_hand():
    # One Fate card in hand beside the Ring and two in play: equal only if the Ring were counted.
    session = _void_game(fate_card("held", P1), in_play=2)

    resolve_effects(session.game, [GainHonor(P1, 1)])

    assert not _void_offered(session)


def test_ring_of_the_void_does_not_count_the_imperial_favor_in_hand():
    # Equal only if the Favor's proxy, which waits in the holder's hand, were counted.
    session = _void_game(fate_card("held", P1), in_play=2)

    resolve_effects(session.game, [TakeFavor(P1)])

    assert any(
        card.printed_id == IMPERIAL_FAVOR_ID
        for card in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    )
    assert not _void_offered(session)


def test_ring_of_the_void_watches_only_under_the_shattered_empire_rules(monkeypatch):
    monkeypatch.setattr(ruleset, "ACTIVE", ruleset.ONYX)

    session = _void_equip_game(fate_card("spare", P1))

    assert not _void_offered(session)
    assert not any(isinstance(event, ConditionFulfilled) for event in session.game.turn_events)


# --- Binasa (Experienced) ---


def _binasa_battle():
    binasa = personality("binasa", printed_id="binasa_experienced", force=5, keywords=("Pearl",))
    units = [binasa, personality("enemy", owner=P2, force=2)]
    session = combat_segment(units, {"binasa": 0}, {"enemy": 0})
    token_template(
        session.game, "pearl_strategy", name="Pearl", card_type="Strategy", keywords=("Pearl",)
    )
    return session


def _pearl_strategy(card_id: str) -> L5RCard:
    return L5RCard.of(
        ActionPrint,
        id=card_id,
        printed_id="pearl_strategy",
        name="Pearl",
        side=Side.FATE,
        owner=P1,
        keywords=("Pearl",),
    )


def test_binasa_gives_an_enemy_personality_a_yu_letting_you_create_a_pearl_strategy():
    game = _binasa_battle().game

    resolve_effects(game, [Destroy("enemy", P1)])
    assert isinstance(game.pending, Confirm) and game.pending.seat is P1
    submit(game, DecisionResponse(game.pending.candidates))

    pearls = [card for card in game.table.battlefield.cards if card.name == "Pearl"]
    assert [card.owner for card in pearls] == [P1]
    assert location_of(game.table, pearls[0]).is_home


def test_binasa_ranged_counts_your_pearl_strategies_and_may_straighten_a_pearl_card():
    session = _binasa_battle()
    game = session.game
    put_in_play(game, _pearl_strategy("first"))
    put_in_play(game, _pearl_strategy("second"))
    resolve_effects(game, [Bow("binasa")])

    session.act(P1, ActivateAbility("binasa"))
    session.submit(P1, DecisionResponse(("enemy",)))
    session.submit(P1, DecisionResponse(()))
    session.submit(P1, DecisionResponse(("binasa",)))

    assert "enemy" not in {card.id for card in game.table.battlefield.cards}
    assert not game.table.cards_by_id["binasa"].bowed


def test_binasa_offers_no_pearl_card_his_ranged_destroyed():
    session = _binasa_battle()
    game = session.game
    put_in_play(game, personality("pearl", owner=P2, force=0, keywords=("Pearl",)))
    ops.set_location(game.table, game.table.cards_by_id["pearl"], Location.at_battlefield(0))
    resolve_effects(game, [Bow("pearl")])

    session.act(P1, ActivateAbility("binasa"))
    session.submit(P1, DecisionResponse(("pearl",)))
    session.submit(P1, DecisionResponse(()))

    assert "pearl" not in {card.id for card in game.table.battlefield.cards}
    assert game.pending is None


# --- Daigotsu Konishi ---


def test_konishi_gives_a_card_on_either_side_of_the_battle_minus_2_force():
    cards = [
        personality("konishi", printed_id="daigotsu_konishi", force=3),
        personality("guard", owner=P2, force=3),
        personality("reserve", owner=P2, force=3),
    ]
    session = combat_segment(cards, {"konishi": 0}, {"guard": 0})
    follower = attachment("ashigaru", owner=P2, attachment_type=AttachmentType.FOLLOWER, force=1)
    attached(session.game, follower, "guard")

    session.act(P1, ActivateAbility("konishi"))
    assert set(session.game.pending.candidates) == {"konishi", "guard", "ashigaru"}
    session.submit(P1, DecisionResponse(("guard",)))

    game = session.game
    assert effective_force(game, game.table.cards_by_id["guard"]) == 1


# --- Lane of Immorality ---


def test_recruiting_lane_of_immorality_loses_1_honor():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("mine", gold_production=2))
    province_card(state, "lane", printed_id="lane_of_immorality", gold_cost=1, gold_production=2)
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [register(state, holding("refill"))]
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)
    honor = session.game.table.seats[P1].honor

    session.act(P1, ActivateAbility("lane", RECRUIT))
    pay(session, P1)

    assert session.game.table.seats[P1].honor == honor - 1


def test_each_bow_of_lane_of_immorality_loses_1_honor():
    game = two_seat_game()
    put_in_play(game, holding("lane", printed_id="lane_of_immorality", gold_production=2))
    put_in_play(game, holding("other", printed_id="lane_of_immorality", gold_production=2))
    honor = game.table.seats[P1].honor

    resolve_effects(game, [Bow("lane"), Straighten("lane"), Bow("lane")])

    assert game.table.seats[P1].honor == honor - 2


# --- Seppun Blade ---


@pytest.mark.parametrize(
    ("defenders", "hand"),
    [({"guard": 0}, ["held", "top"]), ({}, ["top"])],
    ids=["opposed", "unopposed"],
)
def test_seppun_blade_discards_only_while_unopposed_and_always_draws(defenders, hand):
    cards = [personality("hero", force=3), personality("guard", owner=P2, force=3)]
    held = [fate_card("held", P1)]
    session = combat_segment(cards, {"hero": 0}, defenders, in_hand=held)
    game = session.game
    attached(game, attachment("blade", printed_id="seppun_blade", force_modifier=2), "hero")
    game.table.decks[DeckKey(P1, Side.FATE)].cards = [register(game.table, fate_card("top", P1))]

    session.act(P1, ActivateAbility("blade"))

    assert game.pending is None
    assert [card.id for card in game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards] == hand
    assert game.table.cards_by_id["blade"].bowed


def test_seppun_blade_reads_whether_its_personality_is_opposed_as_it_resolves():
    cards = [personality("hero", force=3), personality("guard", owner=P2, force=3)]
    session = combat_segment(cards, {"hero": 0}, {"guard": 0}, in_hand=[fate_card("held", P1)])
    game = session.game
    blade = attached(game, attachment("blade", printed_id="seppun_blade"), "hero")
    game.table.decks[DeckKey(P1, Side.FATE)].cards = [register(game.table, fate_card("top", P1))]
    effects = ability_for(game, blade).effects(game, blade, blade)

    resolve_effects(game, [Move("guard", Location.home(P2)), *effects])

    assert [card.id for card in game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards] == ["top"]
