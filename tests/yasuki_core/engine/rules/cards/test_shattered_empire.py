from yasuki_core import ruleset
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import ActionPrint, PersonalityPrint, WindPrint
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    DeclareAttack,
    Lobby,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary.decisions import ChooseOption, DecisionResponse
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import _ABILITIES, register_ability
from yasuki_core.engine.rules.effects import GainHonor
from yasuki_core.engine.rules.legality import recruit_cost
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.cards.shattered_empire import FINE_SWORD, SANJIROS_ARMOR
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import AttachmentType, Side

from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.rulebook.recruit import finish_recruit
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.vocabulary.decisions import Confirm
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    stronghold,
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
    session.act(P1, PlayStrategy("crane"))
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

    assert PlayStrategy("crane") not in session.legal_actions(P1)


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
    return game


def test_an_unbowed_meiji_stops_a_seat_without_his_controllers_wind_lobbying():
    game = _p2_ready_to_lobby()

    assert Lobby() not in legality.legal_actions(game, PlayerId.P2)


def test_a_seat_sharing_meijis_controllers_wind_may_lobby():
    game = _p2_ready_to_lobby(p2_wind="kanos_alliance")

    assert Lobby() in legality.legal_actions(game, PlayerId.P2)


def test_a_bowed_meiji_stops_nobody():
    game = _p2_ready_to_lobby(meiji_bowed=True)

    assert Lobby() in legality.legal_actions(game, PlayerId.P2)


def test_meiji_stops_nobody_while_his_controller_has_no_wind():
    # "Your Wind" names a Wind his controller has. Without one the clause has no referent, and
    # the ruling here is that it does nothing.
    game = _p2_ready_to_lobby(p1_wind=None)

    assert Lobby() in legality.legal_actions(game, PlayerId.P2)


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


def test_the_dishonoring_is_reacted_to_while_gonshiro_still_stands_in_his_province():
    session = _gonshiro_in_a_province()
    put_in_play(session.game, personality("gihei", printed_id="bayushi_gihei", force=3))

    session.act(P1, Recruit("gonshiro"))
    pay(session, P1)

    game = session.game
    assert isinstance(game.pending, ChooseOption)
    assert game.table.cards_by_id["gonshiro"] not in game.table.battlefield.cards
    session.submit(P1, DecisionResponse(("P2",)))
    assert game.table.cards_by_id["gonshiro"] in game.table.battlefield.cards
    assert game.table.cards_by_id["gonshiro"].dishonorable


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
