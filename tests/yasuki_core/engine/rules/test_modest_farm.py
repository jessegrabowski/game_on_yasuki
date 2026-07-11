from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding
from yasuki_core.engine.rules.actions import ActivateAbility, Pass, Recruit
from yasuki_core.engine.rules.decisions import (
    ChooseAbilityTarget,
    ChooseCards,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession


def _register(state, card):
    state.cards_by_id[card.id] = card
    return card


def _modest_farm_game(*, target_keywords=(), target_cost=2, with_producer=True, producer_gp=8):
    """An Action-phase session: P1's Modest Farm and a face-up Holding in a province to recruit
    through Modest Farm's ability. With ``with_producer`` a gold Holding of ``producer_gp`` yield is
    also in play to pay the recruit; without it, only Modest Farm's own (forfeited) production
    remains."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        _register(
            state, DynastyHolding(id="refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1)
        )
    ]
    if with_producer:
        state.battlefield.add(
            _register(
                state,
                DynastyHolding(
                    id="SH",
                    name="SH",
                    side=Side.DYNASTY,
                    owner=PlayerId.P1,
                    gold_production=producer_gp,
                ),
            )
        )
    state.battlefield.add(
        _register(
            state,
            DynastyHolding(
                id="mf",
                name="Modest Farm",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                printed_id="modest_farm",
                keywords=("Farm",),
                gold_production=1,
            ),
        )
    )
    target = _register(
        state,
        DynastyHolding(
            id="target",
            name="Target",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            printed_id="plain_holding",
            keywords=target_keywords,
            gold_cost=target_cost,
            gold_production=2,
        ),
    )
    target.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(target)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province
    return EngineSession.start(state, PlayerId.P1)  # Action phase


def _drive_to_straighten_choice(session):
    session.act(PlayerId.P1, ActivateAbility("mf"))
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget) and pending.candidates == ("target",)
    session.submit(PlayerId.P1, DecisionResponse(("target",)))
    pending = session.game.pending
    assert isinstance(pending, ChoosePayment) and pending.amount == 2  # X = the target's cost
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))
    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ("mf",)  # may destroy MF


def test_modest_farm_is_activatable_with_a_province_holding():
    session = _modest_farm_game()
    assert ActivateAbility("mf") in session.legal_actions(PlayerId.P1)


def test_modest_farm_is_not_activatable_while_bowed():
    session = _modest_farm_game()
    session.game.table.cards_by_id["mf"].bow()
    assert ActivateAbility("mf") not in session.legal_actions(PlayerId.P1)


def test_modest_farm_is_not_offered_when_no_target_is_affordable():
    # Modest Farm's cost is paying the target's recruit cost; with no producer to cover it (Modest
    # Farm bows itself out of the pool), the ability must not be offered — else the recruit would
    # wedge at an unpayable payment.
    session = _modest_farm_game(target_cost=3, with_producer=False)
    assert ActivateAbility("mf") not in session.legal_actions(PlayerId.P1)


def test_modest_farm_does_not_count_its_own_forfeited_production_as_affordability():
    # Producer gp2 + Modest Farm gp1 covers a cost-3 target only if Modest Farm's own yield counts —
    # but Modest Farm bows itself as the cost, so it cannot. The ability must not be offered.
    session = _modest_farm_game(target_cost=3, producer_gp=2)
    assert ActivateAbility("mf") not in session.legal_actions(PlayerId.P1)


def test_modest_farm_destroys_itself_to_recruit_the_target_unbowed():
    session = _modest_farm_game(target_keywords=("Farm",))
    _drive_to_straighten_choice(session)
    session.submit(PlayerId.P1, DecisionResponse(("mf",)))  # sacrifice Modest Farm

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    assert not table.cards_by_id["target"].bowed  # straightened by the sacrifice
    discard = table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)]
    assert "mf" in {c.id for c in discard.cards}  # Modest Farm destroyed


def test_modest_farm_can_be_kept_leaving_the_recruit_bowed():
    session = _modest_farm_game()
    _drive_to_straighten_choice(session)
    session.submit(PlayerId.P1, DecisionResponse(()))  # decline the sacrifice

    table = session.game.table
    assert table.cards_by_id["target"].bowed  # recruits enter bowed
    assert table.cards_by_id["mf"] in table.battlefield.cards  # Modest Farm kept


def test_modest_farm_grants_a_farm_target_renew_refilling_its_province_face_up():
    session = _modest_farm_game(target_keywords=("Farm",))
    _drive_to_straighten_choice(session)
    session.submit(PlayerId.P1, DecisionResponse(()))

    refill = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert refill.face_up  # Renew granted to the Farm target


def test_modest_farm_does_not_grant_renew_to_a_non_farm_target():
    session = _modest_farm_game(target_keywords=("Market",))
    _drive_to_straighten_choice(session)
    session.submit(PlayerId.P1, DecisionResponse(()))

    refill = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert not refill.face_up  # no Renew for a non-Farm target


def test_modest_farm_activation_replays_to_the_same_state():
    session = _modest_farm_game(target_keywords=("Farm",))
    _drive_to_straighten_choice(session)
    session.submit(PlayerId.P1, DecisionResponse(("mf",)))
    assert replay(session.log) == session.game


def test_recruiting_a_renew_keyword_card_refills_its_province_face_up():
    # The general Renew rule: a normally-recruited card with the Renew keyword refills face-up.
    state = TableState.empty_two_seat()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        _register(
            state, DynastyHolding(id="refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1)
        )
    ]
    state.battlefield.add(
        _register(
            state,
            DynastyHolding(
                id="SH", name="SH", side=Side.DYNASTY, owner=PlayerId.P1, gold_production=8
            ),
        )
    )
    renewer = _register(
        state,
        DynastyHolding(
            id="warrens",
            name="W",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            keywords=("Renew",),
            gold_cost=1,
        ),
    )
    renewer.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(renewer)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, PlayerId.P1)
    session.act(PlayerId.P1, Pass())  # Action -> Attack
    session.act(PlayerId.P1, Pass())  # Attack -> Dynasty

    session.act(PlayerId.P1, Recruit("warrens"))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))
    refill = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert refill.face_up
