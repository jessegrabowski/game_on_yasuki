from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.turn import sequence
from yasuki_core.engine.rules.vocabulary.actions import DeclareAttack, Pass
from yasuki_core.engine.rules.vocabulary.decisions import ChooseBattlefield, DecisionResponse
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.bots.agents import PayingAgent
from yasuki_core.engine.rules.gold.self_grants import is_production_window
from yasuki_core.engine.rules.vocabulary.decisions import ChoosePayment, Confirm
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import (
    AttachTarget,
    DeckKey,
    Location,
    TableState,
    ZoneKey,
    ZoneRole,
)
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.factory import build_print
from yasuki_core.game_pieces.prints import (
    ActionPrint,
    AttachmentPrint,
    CardPrint,
    FatePrint,
    HoldingPrint,
    PersonalityPrint,
    SenseiPrint,
    StrongholdPrint,
    WindPrint,
)

# Only shapes duplicated across two or more test modules belong here; one that would have to contort
# to serve a single caller belongs in that caller's module.


def register(state: TableState, card):
    """Index ``card`` in the table's id map and return it. Cards built directly rather than dealt
    are not otherwise reachable by id, and most engine reads go through ``cards_by_id``."""
    state.cards_by_id[card.id] = card
    return card


def put_in_play(target: GameState | TableState, card):
    """Register ``card`` and add it to the battlefield. Accepts a game or a bare table."""
    state = target.table if isinstance(target, GameState) else target
    register(state, card)
    state.battlefield.add(card)
    return card


def personality(
    card_id: str,
    *,
    owner: PlayerId = PlayerId.P1,
    name: str | None = None,
    printed_id: str | None = None,
    force: int = 2,
    chi: int = 3,
    personal_honor: int = 0,
    gold_cost: int | None = None,
    keywords: tuple[str, ...] = (),
    clans: tuple[str, ...] = (),
) -> L5RCard:
    """A Personality. ``chi`` defaults live because a Personality at zero Chi is destroyed on sight
    (CR, Chi Death Rule), which would otherwise remove the card a test just built."""
    return L5RCard.of(
        PersonalityPrint,
        id=card_id,
        name=name or card_id,
        side=Side.DYNASTY,
        owner=owner,
        printed_id=printed_id,
        force=force,
        chi=chi,
        personal_honor=personal_honor,
        gold_cost=gold_cost,
        keywords=keywords,
        clans=clans,
    )


def attachment(
    card_id: str,
    *,
    owner: PlayerId = PlayerId.P1,
    name: str | None = None,
    printed_id: str | None = None,
    attachment_type: AttachmentType = AttachmentType.ITEM,
    force: int = 0,
    chi: int = 0,
    force_modifier: int = 0,
    chi_modifier: int = 0,
    gold_cost: int = 0,
    keywords: tuple[str, ...] = (),
) -> L5RCard:
    """An Item, Follower or Spell. ``force``/``chi`` are the card's own stats, which it brings to a
    unit. The ``_modifier`` pair is what it hands to the Personality it attaches to."""
    return L5RCard.of(
        AttachmentPrint,
        id=card_id,
        name=name or card_id,
        side=Side.FATE,
        owner=owner,
        printed_id=printed_id,
        attachment_type=attachment_type,
        force=force,
        chi=chi,
        force_modifier=force_modifier,
        chi_modifier=chi_modifier,
        gold_cost=gold_cost,
        keywords=keywords,
    )


def token_template(
    target: GameState | TableState,
    card_id: str,
    *,
    name: str,
    card_type: str,
    keywords: tuple[str, ...] = (),
    force: int | None = None,
    chi: int | None = None,
) -> CardPrint:
    """Load a creatable-token template onto the table and return it.

    Built from a card record through the same factory a deck load uses, so a test's token splits its
    printed Force and Chi between its own stats and the ones it hands its Personality exactly as the
    database-loaded one does.
    """
    state = target.table if isinstance(target, GameState) else target
    printed = build_print(
        {
            "card_id": card_id,
            "name": name,
            "types": [card_type, "Proxy"],
            "keywords": list(keywords),
            "force": force,
            "chi": chi,
            "gold_cost": 0,
        }
    )
    state.creatable_tokens[card_id] = printed
    return printed


def attached(target: GameState | TableState, card: L5RCard, parent: AttachTarget) -> L5RCard:
    """Put ``card`` into play attached to ``parent`` (a Personality's card id, or a Province
    ``ZoneKey`` for a Region or Fortification) through the same ops the rules layer uses, so a test
    never hand-builds the relation."""
    state = target.table if isinstance(target, GameState) else target
    put_in_play(state, card)
    if isinstance(parent, ZoneKey):
        ops.attach_to_province(state, card, parent)
    else:
        ops.attach_to_personality(state, card, state.cards_by_id[parent])
    return card


def holding(
    card_id: str,
    *,
    printed_id: str | None = None,
    owner: PlayerId = PlayerId.P1,
    name: str | None = None,
    keywords: tuple[str, ...] = (),
    gold_production: int = 0,
    gold_cost: int | None = None,
    clan: str | None = None,
    counters: dict[str, int] | None = None,
) -> L5RCard:
    """A Dynasty Holding. ``name`` defaults to ``card_id``, which keeps failure output readable."""
    return L5RCard.of(
        HoldingPrint,
        id=card_id,
        name=name or card_id,
        side=Side.DYNASTY,
        owner=owner,
        printed_id=printed_id,
        keywords=keywords,
        gold_production=gold_production,
        gold_cost=gold_cost,
        clan=clan,
        counters=dict(counters or {}),
    )


def stronghold(
    owner: PlayerId = PlayerId.P1,
    *,
    gold_production: int = 0,
    province_strength: int = 0,
    clan: str | None = None,
    clans: tuple[str, ...] = (),
    starting_honor: int = 0,
) -> L5RCard:
    return L5RCard.of(
        StrongholdPrint,
        id=f"{owner.name}-SH",
        name="SH",
        side=Side.STRONGHOLD,
        owner=owner,
        gold_production=gold_production,
        province_strength=province_strength,
        clan=clan,
        clans=clans,
        starting_honor=starting_honor,
    )


def flip_stronghold(
    printed_id: str,
    *,
    card_id: str = "sh",
    owner: PlayerId = PlayerId.P1,
    flipped: bool = False,
    **printed,
) -> L5RCard:
    """A double-faced Stronghold whose back print carries ``<printed_id>__back``, showing its back
    when ``flipped``. ``printed`` are further front characteristics."""
    return L5RCard.of(
        StrongholdPrint,
        id=card_id,
        name=printed_id,
        printed_id=printed_id,
        side=Side.STRONGHOLD,
        owner=owner,
        back_card_id=f"{printed_id}__back",
        back_printed=StrongholdPrint(
            name=printed_id, side=Side.STRONGHOLD, printed_id=f"{printed_id}__back"
        ),
        showing_back=flipped,
        **printed,
    )


def combat_segment(
    cards: list[L5RCard],
    attackers: dict[str, int],
    defenders: dict[str, int],
    *,
    attacker: PlayerId = PlayerId.P1,
) -> EngineSession:
    """The Combat Segment at battlefield 0 of ``attacker``'s attack, with ``cards`` in play and each
    seat's Personalities assigned by id to the battlefield index given, the defender passed, so the
    attacker holds priority. A Province is created for every battlefield index named."""
    defender = PlayerId.P2 if attacker is PlayerId.P1 else PlayerId.P1
    state = TableState.empty_two_seat()
    for index in sorted({*attackers.values(), *defenders.values(), 0}):
        province_card(state, f"atk-prov{index}", seat=attacker, index=index)
        province_card(state, f"def-prov{index}", seat=defender, index=index)
    for card in cards:
        put_in_play(state, card)
    session = EngineSession.start(state, attacker)
    end_phase(session)
    session.act(attacker, DeclareAttack())
    assigned = {
        seat: tuple(f"{card_id}@{battlefield}" for card_id, battlefield in army.items())
        for seat, army in ((attacker, attackers), (defender, defenders))
    }
    session.submit(attacker, DecisionResponse(assigned[attacker]))
    session.submit(defender, DecisionResponse(assigned[defender]))
    choice = session.game.pending
    assert isinstance(choice, ChooseBattlefield)
    session.submit(choice.seat, DecisionResponse(("0",)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    session.act(defender, Pass())
    return session


def sensei(
    owner: PlayerId = PlayerId.P1,
    *,
    printed_id: str | None = None,
    keywords: tuple[str, ...] = (),
) -> L5RCard:
    """A Sensei. Like a Stronghold and a Wind it starts in play, so tests put it there directly."""
    return L5RCard.of(
        SenseiPrint,
        id=f"{owner.name}-sensei",
        name="Sensei",
        side=Side.FATE,
        owner=owner,
        printed_id=printed_id,
        keywords=keywords,
    )


def wind(owner: PlayerId = PlayerId.P1, *, name: str = "Wind") -> L5RCard:
    """A Wind. A deck holds at most one and it starts in play, so tests put it there directly."""
    return L5RCard.of(
        WindPrint,
        id=f"{owner.name}-wind",
        name=name,
        side=Side.FATE,
        owner=owner,
    )


def fate_card(card_id: str, owner: PlayerId, *, name: str = "F") -> L5RCard:
    return L5RCard.of(FatePrint, id=card_id, name=name, side=Side.FATE, owner=owner)


def terrain(card_id: str, *, owner: PlayerId = PlayerId.P1) -> L5RCard:
    return L5RCard.of(
        ActionPrint, id=card_id, name="Terrain", side=Side.FATE, owner=owner, keywords=("Terrain",)
    )


def terrain_at(
    target: GameState | TableState, card_id: str, battlefield: int, *, owner: PlayerId = PlayerId.P1
) -> L5RCard:
    """A Terrain in play at ``battlefield``, in no unit, as one that put itself into play stands."""
    state = target.table if isinstance(target, GameState) else target
    card = put_in_play(state, terrain(card_id, owner=owner))
    ops.set_location(state, card, Location.at_battlefield(battlefield))
    return card


def two_seat_game(first_player: PlayerId = PlayerId.P1) -> GameState:
    """An empty two-seat game, the starting point for tests that build their own board."""
    return GameState.start(TableState.empty_two_seat(), first_player)


def dealt_table(*, fate_deck: int = 1, hand: int | None = None) -> TableState:
    """A two-seat table with ``fate_deck`` cards in each seat's fate deck and ``hand`` cards in P1's
    hand. The hand defaults to the maximum, so P1's turns end in a discard while P2's do not."""
    hand = sequence.MAX_HAND_SIZE if hand is None else hand
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(state, fate_card(f"{seat.name}-fd{i}", seat)) for i in range(fate_deck)
        ]
    p1_hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(hand):
        p1_hand.add(register(state, fate_card(f"P1-h{i}", PlayerId.P1, name="H")))
    return state


def province_card(
    target: GameState | TableState,
    card_id: str,
    *,
    seat: PlayerId = PlayerId.P1,
    printed_id: str | None = None,
    name: str | None = None,
    keywords: tuple[str, ...] = (),
    gold_cost: int | None = None,
    gold_production: int = 0,
    counters: dict[str, int] | None = None,
    face_up: bool = True,
    index: int = 0,
) -> L5RCard:
    """Put a Holding into ``seat``'s province at ``index``, replacing whatever zone was there."""
    state = target.table if isinstance(target, GameState) else target
    card = register(
        state,
        holding(
            card_id,
            printed_id=printed_id,
            name=name,
            owner=seat,
            keywords=keywords,
            gold_cost=gold_cost,
            gold_production=gold_production,
            counters=counters,
        ),
    )
    if face_up:
        card.turn_face_up()
    else:
        card.turn_face_down()
    zone = state.zones.get(ZoneKey(seat, ZoneRole.PROVINCE, index)) or ProvinceZone(owner=seat)
    zone.add(card)
    state.zones[ZoneKey(seat, ZoneRole.PROVINCE, index)] = zone
    return card


def pay(session: EngineSession, seat: PlayerId) -> None:
    """Cover the gold cost ``seat`` owes, however many answers that takes.

    Bows producers the way :class:`PayingAgent` does, smallest first, and answers the window each
    one opens as it bows, taking a producer's own grant only when nothing else reaches the cost. A
    test that cares *which* producers bow, or how a window was answered, answers the decision
    itself.

    Raise ``AssertionError`` unless ``seat`` owes a payment right now, so a test that has drifted
    past the one it meant to answer fails here rather than somewhere downstream.
    """
    pending = session.game.pending
    assert isinstance(pending, ChoosePayment), (
        f"no payment pending for {seat.name}, found {type(pending).__name__}"
    )
    assert pending.seat is seat, f"the pending payment is {pending.seat.name}'s, not {seat.name}'s"
    agent = PayingAgent()
    while pending is not None and pending.seat is seat:
        view = session.project(seat)
        part_of_the_payment = isinstance(pending, ChoosePayment) or (
            isinstance(pending, Confirm) and is_production_window(pending, view.table.battlefield)
        )
        if not part_of_the_payment:
            return
        session.submit(seat, agent.decide(pending, view))
        pending = session.game.pending


def end_phase(session: EngineSession) -> None:
    """Pass for whoever holds the opportunity until the round closes and the phase moves on.

    A round ends when every seat entitled to act in it has passed consecutively, so how many passes
    that takes depends on the phase: two in the Action phase, where the inactive seat may take Open
    actions, one everywhere else. Tests that want the next phase should say so rather than counting.
    Stops early if the engine pauses for a decision, such as the end-of-turn discard.
    """
    started = (session.game.phase, session.game.turn)
    while (
        (session.game.phase, session.game.turn) == started
        and not session.game.game_over
        and not session.game.awaiting_decision
    ):
        session.act(session.game.round.priority, Pass())


def end_turn(session: EngineSession) -> None:
    """Pass through the rest of the active player's turn, until the next one begins.

    Stops early if the engine pauses for a decision or the game ends, so a test that wanted the turn
    over asserts on a board that says why it is not.
    """
    turn = session.game.turn
    while (
        session.game.turn == turn
        and not session.game.game_over
        and not session.game.awaiting_decision
    ):
        end_phase(session)
