import pytest
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
    Recruit,
)
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary.decisions import ChooseOption, DecisionResponse
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.effects import Destroy, Discard
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.idioms import PITCH, ask_who_loses_honor
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import _ABILITIES, register_ability
from yasuki_core.engine.rules.effects import GainHonor, TakeFavor
from yasuki_core.engine.rules.vocabulary.game_events import ConditionFulfilled
from yasuki_core.engine.rules.legality import recruit_cost
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.vocabulary.game_events import Dishonored, EnteredPlay
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.cards.shattered_empire import FINE_SWORD, SANJIROS_ARMOR
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded, FavorDiscarded
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.turn import action_sequence, sequence
from yasuki_core.engine.players import Trait
from yasuki_core.engine.rules.rulebook import proxies
from yasuki_core.engine.rules.rulebook.lobby import is_lobby, lobby_bonus
from yasuki_core.engine.rules.board.queries import province_zones
from yasuki_core.engine import ops
from yasuki_core.engine.table import DeckKey
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, AttachmentType, Side

from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.rulebook.recruit import finish_recruit
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseDiscard,
    ChoosePayment,
    Confirm,
)
from yasuki_core.engine.rules.vocabulary.actions import PlayInterrupt
from yasuki_core.engine.rules.effects import Move
from yasuki_core.engine.table import Location, location_of
from yasuki_core.engine.rules.board.queries import personalities_in_play
from tests.yasuki_core.engine.rules.conftest import probe_ability
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from tests.yasuki_core.engine.builders import (
    datasheet_favor_ability,
    attached,
    attachment,
    end_phase,
    fate_card,
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

    session.act(P1, Recruit("sanjiro", invest=True))
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

    session.act(P1, Recruit("sanjiro"))
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
        printed_id=printed_id,
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


# --- Doji Yasuko, Soul of Doji Takeji ---


def _yasuko_waiting(state: TableState) -> L5RCard:
    return register(
        state, personality("yasuko", printed_id="doji_yasuko_soul_of_doji_takeji", gold_cost=6)
    )


def _courtier_of(clan: str) -> L5RCard:
    return L5RCard.of(
        PersonalityPrint,
        id="courtier",
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
            register(state, L5RCard.of(ActionPrint, id="top", name="Top", side=Side.FATE, owner=P1))
        ]
        session = EngineSession.start(state, P1)

        session.act(P1, PlayStrategy("probe"))
        session.submit(P1, DecisionResponse())
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

    finish_recruit(game, meiji.id, None, proclaim=True)

    assert isinstance(game.pending, Confirm)
    assert game.pending.prompt() == "Gain 5 Honor from Proclaiming instead of 2?"
    submit(game, DecisionResponse(game.pending.candidates))
    assert game.table.seats[P1].honor == 5


def _wind_named(owner: PlayerId, printed_id: str) -> L5RCard:
    return L5RCard.of(
        WindPrint,
        id=f"{owner.name}-wind",
        name=printed_id,
        printed_id=printed_id,
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

    session.act(P1, Recruit("gonshiro"))
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

    session.act(P1, Recruit("gonshiro"))
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

    session.act(P1, Recruit("gonshiro"))
    pay(session, P1)

    game = session.game
    assert game.pending is None
    assert game.table.cards_by_id["gonshiro"].dishonorable
    assert effective_force(game, game.table.cards_by_id["gihei"]) == 3


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
        RingPrint, id=card_id, name=printed_id, printed_id=printed_id, side=Side.FATE, owner=owner
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


def test_ring_of_air_straightens_two_bowed_cards_of_one_unit():
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    put_in_play(state, personality("samurai"))
    attached(state, attachment("guard", attachment_type=AttachmentType.FOLLOWER), "samurai")
    put_in_play(state, register(state, _ring("air", "ring_of_air")))
    session = EngineSession.start(state, P1)
    for card_id in ("samurai", "guard"):
        session.game.table.cards_by_id[card_id].bow()

    session.act(P1, ActivateAbility("air", "air"))
    _answer_until_settled(session, "samurai", "guard")

    cards = session.game.table.cards_by_id
    assert not cards["samurai"].bowed and not cards["guard"].bowed
    assert cards["air"].bowed


def test_ring_of_air_offers_a_second_card_only_from_the_targets_unit():
    session = _ring_game(personality("samurai"), personality("other"), _ring("air", "ring_of_air"))
    for card_id in ("samurai", "other"):
        session.game.table.cards_by_id[card_id].bow()

    session.act(P1, ActivateAbility("air", "air"))
    _answer_until_settled(session, "samurai")

    cards = session.game.table.cards_by_id
    assert not cards["samurai"].bowed
    assert cards["other"].bowed


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
    in_play: tuple[L5RCard, ...] = (),
    held: tuple[L5RCard, ...] = (),
) -> EngineSession:
    """P1 attacks P2's Province with a raider; P2 defends with a guard. Left in the Combat Segment
    with P1 holding the opportunity."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, personality("raider", force=2, printed_id=raider_printed_id))
    put_in_play(state, personality("guard", owner=P2, force=guard_force))
    for card in in_play:
        put_in_play(state, register(state, card))
    for card in held:
        state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
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
    pay(session, P1)
    session.submit(P1, DecisionResponse(("bearer",)))
    return session


def _void_offered(session: EngineSession, ring_id: str = "void") -> bool:
    pending = session.game.pending
    return isinstance(pending, Confirm) and pending.seat is P1 and ring_id in pending.candidates


def _void_game(*held: L5RCard, in_play: int) -> EngineSession:
    """P1's "bearer" carrying ``in_play`` Followers, "follower0" upward, and Ring of the Void in
    P1's hand beside ``held``, started with no action taken."""
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
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


@pytest.mark.parametrize(
    ("announced", "action"),
    [
        (attachment("played", attachment_type=AttachmentType.FOLLOWER), Equip("played")),
        (
            L5RCard.of(
                ActionPrint,
                id="played",
                name="Played",
                printed_id="probe_gain_honor",
                side=Side.FATE,
                owner=P1,
            ),
            PlayStrategy("played"),
        ),
    ],
    ids=["equip", "strategy"],
)
def test_ring_of_the_void_is_offered_when_an_announcement_takes_the_hand_down_to_match(
    announced, action
):
    # The card leaves the hand for its entering-play or resolution area when it is announced, so
    # none in play and none in hand match before anything is paid (CR, Resolution Area).
    session = _void_game(announced, in_play=0)

    with probe_ability("probe_gain_honor", _GAIN_HONOR):
        session.act(P1, action)

        assert _void_offered(session)
        session.submit(P1, DecisionResponse(()))
        assert isinstance(session.game.pending, ChoosePayment)


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
