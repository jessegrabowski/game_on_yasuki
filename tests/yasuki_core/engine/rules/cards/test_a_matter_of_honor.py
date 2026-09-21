from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility, DeclareAttack, Pass
from yasuki_core.engine.rules.vocabulary.decisions import ChooseBattlefield, DecisionResponse
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import StrongholdPrint

from tests.yasuki_core.engine.builders import end_phase, personality, province_card, put_in_play

P1, P2 = PlayerId.P1, PlayerId.P2
HONORABLE_GARRISON = "the_honorable_garrison_of_the_lion"
IMPREGNABLE_FORTRESS = "the_impregnable_fortress_of_the_crab"


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


def test_the_garrison_gives_an_opposed_lion_samurai_force_equal_to_his_personal_honor():
    lion = personality("lion", force=1, personal_honor=2, keywords=("Samurai",), clans=("Lion",))
    crane = personality("crane", personal_honor=2, keywords=("Samurai",), clans=("Crane",))
    ashigaru = personality("ashigaru", personal_honor=2, clans=("Lion",))
    session = _combat(
        _flip_stronghold(HONORABLE_GARRISON),
        [lion, crane, ashigaru],
        [personality("guard", owner=P2)],
    )

    session.act(P1, ActivateAbility("sh"))
    assert session.game.pending.candidates == ("lion",)
    session.submit(P1, DecisionResponse(("lion",)))

    assert effective_force(session.game, session.game.table.cards_by_id["lion"]) == 3


def test_the_garrison_back_prints_the_same_ability():
    lion = personality("lion", force=1, personal_honor=2, keywords=("Samurai",), clans=("Lion",))
    session = _combat(
        _flip_stronghold(HONORABLE_GARRISON, flipped=True), [lion], [personality("guard", owner=P2)]
    )

    session.act(P1, ActivateAbility("sh"))
    session.submit(P1, DecisionResponse(("lion",)))

    assert effective_force(session.game, session.game.table.cards_by_id["lion"]) == 3


def test_the_fortress_gives_crab_personalities_a_force_while_opposed():
    crab = personality("crab", force=2, clans=("Crab",))
    crane = personality("crane", force=2, clans=("Crane",))
    reserve = personality("reserve", force=2, clans=("Crab",))
    session = _combat(
        _flip_stronghold(IMPREGNABLE_FORTRESS), [crab, crane], [personality("guard", owner=P2)]
    )
    game = session.game
    put_in_play(game, reserve)

    assert effective_force(game, game.table.cards_by_id["crab"]) == 3
    assert effective_force(game, game.table.cards_by_id["crane"]) == 2
    assert effective_force(game, game.table.cards_by_id["reserve"]) == 2
