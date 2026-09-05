from yasuki_core import ruleset
from yasuki_core.engine.rules import flow, legality
from yasuki_core.engine.rules.actions import PlayStrategy
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import ActionPrint
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility, Recruit
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import effective_force
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.cards.shattered_empire import FINE_SWORD, SANJIROS_ARMOR
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    holding,
    pay,
    personality,
    put_in_play,
    register,
    stronghold,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


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
    """One Weapon per Personality, so the sword has nowhere to go on the one already carrying — the
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


def _edict_game(*, clan: str | None = ruleset.CRANE, in_play: tuple[str, ...] = ()) -> GameState:
    """Way of the Crane in P1's hand, with ``clan`` on their stronghold and ``in_play`` already out
    as Edicts of theirs."""
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1, clan=clan)))
    for card_id in in_play:
        already = (
            "way_of_the_crane_experienced" if card_id == "first" else "way_of_the_lion_experienced"
        )
        put_in_play(state, register(state, _edict(card_id, already)))
    crane = register(state, _edict("crane", "way_of_the_crane_experienced"))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(crane)
    return GameState.start(state, P1, seed=0)


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


def _play_the_edict(game: GameState) -> None:
    flow.perform(game, PlayStrategy("crane"))
    while game.pending is not None:
        flow.submit(game, DecisionResponse(()))


def test_an_edict_puts_itself_into_play_rather_than_being_discarded():
    """ShE: "Open: If you are a Crane Clan player, put this Edict into play." Step F discards a
    played Strategy "unless it is now in play", and this is the clause that exception exists for."""
    game = _edict_game()

    _play_the_edict(game)

    assert "crane" in {card.id for card in game.table.battlefield.cards}
    discard = game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    assert "crane" not in {card.id for card in discard.cards}


def test_an_edict_discards_the_one_already_out():
    """A player holds one Edict at a time (ShE datasheet, Edicts), which every Edict restates as
    "Discard your other Edicts in play"."""
    game = _edict_game(in_play=("lion",))

    _play_the_edict(game)

    in_play = {card.id for card in game.table.battlefield.cards}
    assert "crane" in in_play and "lion" not in in_play


def test_an_edict_naming_a_clan_is_not_offered_to_another():
    """ "If you are a Crane Clan player" — the condition gates the action, so a Lion player holding
    it has nothing to take."""
    game = _edict_game(clan=ruleset.LION)

    assert PlayStrategy("crane") not in legality.legal_actions(game, P1)


def test_a_second_copy_of_an_edict_discards_the_first():
    """Way of the Crane says "Discard your other Edicts in play" with no carve-out, so a second copy
    of itself is one of them. Only Be Prepared to Dig Two Graves exempts copies, and it says so.

    Worth pinning because the two copies are indistinguishable on the board, which makes the swap
    read as the played card vanishing."""
    game = _edict_game(in_play=("first",))

    _play_the_edict(game)

    in_play = {card.id for card in game.table.battlefield.cards}
    assert "crane" in in_play, "the copy just played is the one that stays"
    assert "first" not in in_play
    discard = game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    assert "first" in {card.id for card in discard.cards}
