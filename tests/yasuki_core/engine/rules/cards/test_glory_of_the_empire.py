from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    DeclareAttack,
    Pass,
    PlayStrategy,
)
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.gold.production import effective_gold_production
from yasuki_core.engine.rules.gold.producers import reachable_gold
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    fate_card,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
)

P1 = PlayerId.P1


def _peddler_game(*, other_production: int = 0, cards_in_deck: int = 1) -> EngineSession:
    """The Peddler in play, with an ordinary Holding beside it making ``other_production``."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("peddler", owner=P1, printed_id="traveling_peddler"))
    if other_production:
        put_in_play(state, holding("farm", owner=P1, gold_production=other_production))
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(state, fate_card(f"fd{i}", P1)) for i in range(cards_in_deck)
    ]
    return EngineSession.start(state, P1)


def _hand(session: EngineSession) -> list[str]:
    return [card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards]


def test_the_peddler_produces_two_gold_from_its_text():
    """ "Produce 2 Gold" is printed as text, not as a Gold Production stat, so only the handler
    delivers it. The stat on the card is blank."""
    session = _peddler_game()

    assert effective_gold_production(session.game, session.game.table.cards_by_id["peddler"]) == 2


def test_the_peddler_bows_and_pays_three_gold_to_draw():
    session = _peddler_game(other_production=3)

    session.act(P1, ActivateAbility("peddler"))
    session.submit(P1, DecisionResponse(("farm",)))  # bow the farm for its 3 gold

    assert _hand(session) == ["fd0"]
    assert session.game.table.cards_by_id["peddler"].bowed


def test_the_peddler_cannot_fund_its_own_cost_by_bowing_itself():
    """The cost bows the Peddler, so the 2 Gold it could otherwise produce is already spent. Its
    production and the farm's reach 3 between them, but only the farm's is really available."""
    session = _peddler_game(other_production=1)

    assert reachable_gold(session.game, P1, session.game.table.cards_by_id["peddler"]) == 3

    assert ActivateAbility("peddler") not in session.legal_actions(P1)


def test_a_producer_the_cost_leaves_alone_still_pays_for_it():
    """The exclusion is the bowed card alone. Every other producer counts as it always did."""
    session = _peddler_game(other_production=3)

    assert ActivateAbility("peddler") in session.legal_actions(P1)


def test_gold_already_in_the_pool_pays_for_the_peddler():
    """The exclusion takes the Peddler out of the producers it could bow, not out of the gold the
    seat is already holding. A pool that covers the cost needs no producer at all."""
    session = _peddler_game()
    session.game.add_gold(P1, 3)

    assert ActivateAbility("peddler") in session.legal_actions(P1)

    session.act(P1, ActivateAbility("peddler"))
    session.submit(P1, DecisionResponse(()))  # no producer to bow; the pool covers it

    assert _hand(session) == ["fd0"]
    assert session.game.gold[P1] == 0


ATTACKER, DEFENDER = PlayerId.P1, PlayerId.P2


def _challenge_battle() -> EngineSession:
    """The Combat Segment of P1's attack, with Inexplicable Challenge in the Attacker's hand.

    The Attacker sends a bushi and keeps a Courtier at home. The Defender sends a plain Personality
    and one carrying a Follower, and keeps a Holding at home.
    """
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("bushi", owner=ATTACKER, force=3))
    put_in_play(state, personality("courtier", owner=ATTACKER, force=0, keywords=("Courtier",)))
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    put_in_play(state, personality("escort", owner=DEFENDER, force=1))
    attached(
        state,
        attachment("yari", owner=DEFENDER, attachment_type=AttachmentType.FOLLOWER, force=1),
        "escort",
    )
    put_in_play(state, holding("mine", owner=DEFENDER, gold_production=1))
    state.zones[ZoneKey(ATTACKER, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="challenge",
                name="Inexplicable Challenge",
                printed_id="inexplicable_challenge",
                side=Side.FATE,
                owner=ATTACKER,
            ),
        )
    )
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("bushi@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0", "escort@0")))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())
    session.act(DEFENDER, Pass())
    return session


def _announce_challenge(session: EngineSession) -> tuple[str, ...]:
    """Play the Strategy for its Gold Cost of zero and return the Courtiers it offers."""
    session.act(ATTACKER, PlayStrategy("challenge"))
    session.submit(ATTACKER, DecisionResponse())
    return session.game.pending.candidates


def test_the_challenge_is_targeted_at_a_courtier_standing_at_home():
    session = _challenge_battle()

    assert _announce_challenge(session) == ("courtier",)


def test_it_reaches_every_enemy_card_with_nothing_attached():
    """A Follower has nothing attached to it and a Holding stands outside the Rules of Location, so
    both are enemy cards without attachments beside the plain Personality."""
    session = _challenge_battle()
    _announce_challenge(session)

    session.submit(ATTACKER, DecisionResponse(("courtier",)))

    assert set(session.game.pending.candidates) == {"guard", "yari", "mine"}


def test_it_bows_the_named_card_and_costs_a_target_player_two_honor():
    session = _challenge_battle()
    _announce_challenge(session)
    session.submit(ATTACKER, DecisionResponse(("courtier",)))

    session.submit(ATTACKER, DecisionResponse(("guard",)))
    session.submit(ATTACKER, DecisionResponse(("P2",)))
    session.submit(ATTACKER, DecisionResponse(("Lose 2 Honor",)))

    game = session.game
    assert game.table.cards_by_id["guard"].bowed is True
    assert game.table.seats[DEFENDER].honor == -2
    assert game.table.cards_by_id["courtier"].bowed is False


def test_the_honor_may_be_sent_the_challengers_way():
    session = _challenge_battle()
    _announce_challenge(session)
    session.submit(ATTACKER, DecisionResponse(("courtier",)))
    session.submit(ATTACKER, DecisionResponse(("yari",)))

    session.submit(ATTACKER, DecisionResponse(("P1",)))
    session.submit(ATTACKER, DecisionResponse(("Gain 2 Honor",)))

    assert session.game.table.seats[ATTACKER].honor == 2


def test_it_is_withheld_when_no_enemy_card_is_left_to_bow():
    """None of the three targets is optional, and an already-bowed card is nothing to bow."""
    session = _challenge_battle()
    for card_id in ("guard", "yari", "mine"):
        session.game.table.cards_by_id[card_id].bow()

    assert PlayStrategy("challenge") not in session.legal_actions(ATTACKER)
