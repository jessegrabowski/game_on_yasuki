from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility, DeclareAttack, Pass
from yasuki_core.engine.rules.vocabulary.decisions import ChooseBattlefield, DecisionResponse
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import StrongholdPrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    personality,
    province_card,
    put_in_play,
)

P1, P2 = PlayerId.P1, PlayerId.P2
GRAND_HALLS = "the_grand_halls_of_the_lion"
UNASSAILABLE_FORTRESS = "the_unassailable_fortress_of_the_crab"


def _flip_stronghold(printed_id: str, *, flipped: bool = False) -> L5RCard:
    return L5RCard.of(
        StrongholdPrint,
        id="sh",
        name=printed_id,
        printed_id=printed_id,
        side=Side.STRONGHOLD,
        owner=P1,
        back_card_id=f"{printed_id}__back",
        back_printed=StrongholdPrint(
            name=printed_id, side=Side.STRONGHOLD, printed_id=f"{printed_id}__back"
        ),
        showing_back=flipped,
    )


def _combat(
    stronghold: L5RCard, attackers: list[L5RCard], defenders: list[L5RCard]
) -> EngineSession:
    """The Combat Segment of P1's attack, every listed Personality at battlefield 0 and P2 passed,
    so P1 holds priority."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, stronghold)
    for card in (*attackers, *defenders):
        put_in_play(state, card)
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(tuple(f"{card.id}@0" for card in attackers)))
    session.submit(P2, DecisionResponse(tuple(f"{card.id}@0" for card in defenders)))
    choice = session.game.pending
    assert isinstance(choice, ChooseBattlefield)
    session.submit(choice.seat, DecisionResponse(("0",)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    session.act(P2, Pass())
    return session


def _offered(session: EngineSession) -> bool:
    return ActivateAbility("sh") in session.legal_actions(P1)


def test_the_halls_give_an_opposed_samurai_force_equal_to_his_personal_honor():
    samurai = personality("samurai", force=2, personal_honor=3, keywords=("Samurai",))
    session = _combat(_flip_stronghold(GRAND_HALLS), [samurai], [personality("guard", owner=P2)])

    session.act(P1, ActivateAbility("sh"))
    session.submit(P1, DecisionResponse(("samurai",)))

    game = session.game
    assert effective_force(game, game.table.cards_by_id["samurai"]) == 5
    assert not game.table.cards_by_id["sh"].bowed


def test_the_halls_target_only_samurai():
    peasant = personality("peasant", personal_honor=3)
    session = _combat(_flip_stronghold(GRAND_HALLS), [peasant], [personality("guard", owner=P2)])

    assert not _offered(session)


def test_the_halls_back_is_tireless_where_the_front_is_not():
    samurai = personality("samurai", force=2, personal_honor=3, keywords=("Samurai",))
    guard = personality("guard", owner=P2)
    front = _combat(_flip_stronghold(GRAND_HALLS), [samurai], [guard])
    front.game.table.cards_by_id["sh"].bow()
    assert not _offered(front)

    back = _combat(_flip_stronghold(GRAND_HALLS, flipped=True), [samurai], [guard])
    back.game.table.cards_by_id["sh"].bow()
    assert _offered(back)
    back.act(P1, ActivateAbility("sh"))
    back.submit(P1, DecisionResponse(("samurai",)))

    assert effective_force(back.game, back.game.table.cards_by_id["samurai"]) == 5


def _fortress_battle(*, guards: int) -> EngineSession:
    """P1's bowed hero, carrying a bowed Follower, opposed by ``guards`` enemy Personalities."""
    hero = personality("hero", force=3)
    session = _combat(
        _flip_stronghold(UNASSAILABLE_FORTRESS),
        [hero],
        [personality(f"guard{index}", owner=P2) for index in range(guards)],
    )
    game = session.game
    banner = attached(
        game, attachment("banner", attachment_type=AttachmentType.FOLLOWER, force=1), "hero"
    )
    game.table.cards_by_id["hero"].bow()
    banner.bow()
    return session


def test_the_fortress_straightens_the_personality_and_his_attachments_when_outnumbered():
    session = _fortress_battle(guards=2)

    session.act(P1, ActivateAbility("sh"))
    session.submit(P1, DecisionResponse(("hero",)))

    cards = session.game.table.cards_by_id
    assert not cards["hero"].bowed
    assert not cards["banner"].bowed


def test_the_fortress_leaves_the_attachments_bowed_against_an_army_no_larger():
    session = _fortress_battle(guards=1)

    session.act(P1, ActivateAbility("sh"))
    session.submit(P1, DecisionResponse(("hero",)))

    cards = session.game.table.cards_by_id
    assert not cards["hero"].bowed
    assert cards["banner"].bowed
