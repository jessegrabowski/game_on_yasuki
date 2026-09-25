from dataclasses import dataclass, replace

from yasuki_core.engine import ops
from yasuki_core.engine.rules.battle.presence import place_unit
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.table import Location, location_of
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary.decisions import (
    AssignUnits,
    ChooseBattlefield,
    DecisionResponse,
    assignment,
    assignment_token,
)
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.stats.province_strength import effective_province_strength
from yasuki_core.engine.rules.effects import (
    Destroy,
    DestroyProvince,
    Discard,
    Effect,
    GainHonor,
    Rehonor,
)
from yasuki_core.engine.rules.board.queries import terrains_at, units_at
from yasuki_core.engine.rules.units.composition import unit_force
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.board.queries import province_zones
from yasuki_core.engine.rules.abilities.registry import may_attack
from yasuki_core.engine.rules.vocabulary.game_events import Assigned, BattleResolved, Destroyed
from yasuki_core.engine.rules.battle.records import (
    AttackPhase,
    BattleOutcome,
    BattlefieldInfo,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import (
    ActionRound,
    BATTLE_SEGMENT_TIMINGS,
    Boundary,
    Moment,
    RoundKind,
    END_OF_BATTLE,
)
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment, Segment
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint

# The single maneuvers window the current rules run. Gold through Emperor Edition ran two, Infantry
# Maneuvers then Cavalry Maneuvers, and cards still ask which of them a unit assigned in; this is
# the name there is to record while there is one.
MANEUVERS_WINDOW = "maneuvers"


def _declared_attack(game: GameState) -> AttackPhase:
    """The attack in progress. Raise ``ValueError`` outside one, since every caller here is a step
    of the Attack Phase and has nothing to do without it."""
    if game.attack is None:
        raise ValueError("no attack is declared")
    return game.attack


def defender_of(game: GameState, attacker: PlayerId) -> PlayerId:
    """The seat ``attacker`` attacks: the one other seat at the table.

    Raise ``ValueError`` at a table not holding exactly two seats: the Defender is a single seat in
    every rule written about a battle.
    """
    opponents = [seat for seat in game.table.seats if seat is not attacker]
    if len(opponents) != 1:
        raise ValueError(f"{attacker.name} has {len(opponents)} opponents, not one")
    return opponents[0]


def declare_attack(game: GameState, attacker: PlayerId | None = None) -> None:
    """Declare an attack, creating a battlefield at each Defender Province, in Province order.

    Parameters
    ----------
    game : GameState
        The game to declare in.
    attacker : PlayerId, optional
        The seat attacking. Defaults to the active player, which is who the Attack Phase's
        Declaration Segment offers the choice to. An attack a card creates names its own
        attacker, and need not be the seat whose turn it is.
    """
    attacker = game.active if attacker is None else attacker
    defender = defender_of(game, attacker)
    # By Province index rather than by the order the zones were created in: a destroyed Province is
    # replaced at the lowest free index, and the CR makes battlefields at adjacent Provinces
    # adjacent to each other.
    provinces = sorted(
        (key for key, _ in province_zones(game, defender)),
        key=lambda province: province.idx,
    )
    game.attack = AttackPhase(
        attacker=attacker,
        defender=defender,
        battlefields=tuple(BattlefieldInfo(province=province) for province in provinces),
    )


def assignable_units(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Personalities ``seat`` may assign from home to a battlefield, in play order.

    Both clauses sit on the Personality rather than on the unit he leads: he must be unbowed
    (*"A unit led by a bowed Personality may not be assigned"*) and at home, since assigning moves
    a unit out of home rather than between battlefields. A bowed Follower blocks nothing, since it
    only stops contributing Force once a battle resolves. The Attacker also leaves behind a
    Personality whose text says he cannot attack.
    """
    attacking = game.attack is not None and seat is game.attack.attacker
    return [
        card
        for card in game.table.battlefield.cards
        if card.owner is seat
        and isinstance(card.printed, PersonalityPrint)
        and not card.bowed
        and location_of(game.table, card).is_home
        and (not attacking or may_attack(card))
    ]


def assignment_candidates(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """Every place ``seat`` could send a unit: each assignable Personality paired with each
    battlefield the attack created. Empty outside a declared attack."""
    attack = game.attack
    if attack is None:
        return ()
    return tuple(
        assignment_token(card.id, battlefield)
        for card in assignable_units(game, seat)
        for battlefield in range(len(attack.battlefields))
    )


def open_maneuvers(game: GameState) -> None:
    """Begin the Maneuvers Segment by asking the Attacker where its units go.

    The Attacker assigns first and the Defender answers next, which is the CR's order. Each seat
    assigns simultaneously within its own answer.
    """
    attack = _declared_attack(game)
    attack.segment = Segment.MANEUVERS
    _ask_to_assign(game, attack.attacker)


def _ask_to_assign(game: GameState, seat: PlayerId) -> None:
    """Put the assignment question to ``seat``."""
    attack = _declared_attack(game)
    game.pending = AssignUnits(
        seat=seat,
        candidates=assignment_candidates(game, seat),
        battlefields=len(attack.battlefields),
    )


def apply_assignment(game: GameState, request: AssignUnits, response: DecisionResponse) -> None:
    """Send each Personality the answer names to its battlefield, raise ``Assigned`` for each, then
    ask the other seat.

    The next step of the segment is queued behind the events, so a trigger that pauses for a
    decision is answered before the Defender is asked or the Fight Segment opens.
    """
    attack = _declared_attack(game)
    assigned: list[Assigned] = []
    for token in response.choices:
        card_id, battlefield = assignment(token)
        place_unit(game, game.table.cards_by_id[card_id], Location.at_battlefield(battlefield))
        attack.assigned_in[card_id] = MANEUVERS_WINDOW
        assigned.append(Assigned(card_id, battlefield, request.seat))
    game.stack.append(AfterAssignment(request.seat))
    if assigned:
        triggers.fire_all(game, assigned)


@dataclass(frozen=True, slots=True)
class AfterAssignment:
    """Continue the Maneuvers Segment once ``seat``'s assignment and whatever it triggered have
    settled: the Defender is asked after the Attacker, and the Defender answering ends the
    segment."""

    seat: PlayerId

    def resume(self, game: GameState) -> None:
        attack = _declared_attack(game)
        if self.seat is attack.attacker:
            _ask_to_assign(game, attack.defender)
            return
        begin_fight(game)


def army_force(game: GameState, battlefield: int, seat: PlayerId) -> int:
    """``seat``'s army Force at ``battlefield`` (CR, Army Force).

    The total of every unbowed Personality and Follower in it. An Item modifies its Personality's
    Force whether the Item is bowed or not. A side with no units has zero Force, which is what makes
    an empty side comparable rather than absent.
    """
    return sum(
        unit_force(game, personality, in_battle_resolution=True)
        for personality in units_at(game, battlefield, seat)
    )


def _cards_in(game: GameState, army: list[L5RCard]) -> int:
    """How many cards ``army`` is made of: each Personality plus everything attached to him. What
    the honor gain counts, which is cards rather than units."""
    return sum(1 + len(attachments_of(game, personality)) for personality in army)


def _destroy_army(army: list[L5RCard]) -> list[Effect]:
    """Destroy every unit in ``army``. Each Personality takes his whole unit with him."""
    return [Destroy(personality.id, Rulebook.BATTLE_RESOLUTION) for personality in army]


def resolution_effects(game: GameState, battlefield: int) -> list[Effect]:
    """What resolving the battle at ``battlefield`` does (CR, Battle Resolution).

    The higher Force wins and destroys the enemy army. An Attacker whose Force also cleared the
    Province Strength destroys the Province too. A tie with units on both sides destroys both. A tie
    on zero Force where either side is empty has no outcome, which is not the same as a tie that
    destroys nothing. The winner gains twice the cards it destroyed, and on a tie both do, except
    that an army holding a dishonorable Personality rehonors him in place of its gain (CR,
    Rehonoring 0.3), in a tie before it is destroyed.
    """
    attack = _declared_attack(game)
    attacking = units_at(game, battlefield, attack.attacker)
    defending = units_at(game, battlefield, attack.defender)
    attacking_force = army_force(game, battlefield, attack.attacker)
    defending_force = army_force(game, battlefield, attack.defender)

    if attacking_force > defending_force:
        effects = [
            *_destroy_army(defending),
            *_rehonored(attacking),
            *_spoils(game, attack.attacker, attacking, defending),
        ]
        province = attack.battlefields[battlefield].province
        if attacking_force > defending_force + effective_province_strength(game, province):
            effects.append(DestroyProvince(attack.attacker, province))
        return effects
    if defending_force > attacking_force:
        return [
            *_destroy_army(attacking),
            *_rehonored(defending),
            *_spoils(game, attack.defender, defending, attacking),
        ]
    if not (attacking and defending):
        return []  # tied on zero Force with a side empty: no outcome
    return [
        *_rehonored(attacking),
        *_rehonored(defending),
        *_destroy_army(defending),
        *_destroy_army(attacking),
        *_spoils(game, attack.attacker, attacking, defending),
        *_spoils(game, attack.defender, defending, attacking),
    ]


def _rehonored(army: list[L5RCard]) -> list[Effect]:
    return [Rehonor(personality.id) for personality in army if personality.dishonorable]


def _spoils(
    game: GameState, winner: PlayerId, army: list[L5RCard], destroyed: list[L5RCard]
) -> list[Effect]:
    """The Honor ``winner`` gains for destroying ``destroyed``, twice the cards, unless a
    dishonorable Personality in its ``army`` was rehonored in its place (CR, Rehonoring 0.3)."""
    if any(personality.dishonorable for personality in army):
        return []
    return [GainHonor(winner, 2 * _cards_in(game, destroyed))]


def after_resolution(game: GameState, battlefield: int, *, last_battle: bool) -> None:
    """Send the survivors home (CR, After Resolution).

    Attacking units at this battlefield bow and then return home, both as effects of the
    resolution and neither as movement. Every card in the unit bows, and a Conqueror Personality
    exempts his whole unit from the bow but not from the trip home, as does a card that says the
    resolution does not bow its player's units. Once the Attack Phase's last
    battle is over, defending units return home without bowing. Every one of them, at every
    battlefield, holds the ground they defended until then. Last, every Terrain at this battlefield
    is discarded, announced like any discard.
    """
    attack = _declared_attack(game)
    exempt = attack.battlefields[battlefield].bow_exempt
    for personality in units_at(game, battlefield, attack.attacker):
        conqueror = keywords.CONQUEROR in effective_keywords(game, personality)
        if personality.owner not in exempt and not conqueror:
            personality.bow()
            for attached in attachments_of(game, personality):
                attached.bow()
        ops.return_home(game.table, personality)
    if last_battle:
        # Not scoped to this battlefield, unlike the attackers above: the CR qualifies 0.1 with "at
        # that battlefield" and pointedly leaves 0.2 unqualified, so the last battle sends home
        # every defending unit still standing at any of them.
        for index in range(len(attack.battlefields)):
            for personality in units_at(game, index, attack.defender):
                ops.return_home(game.table, personality)
    discards: list[Effect] = [
        Discard(terrain.id, Rulebook.AFTER_RESOLUTION) for terrain in terrains_at(game, battlefield)
    ]
    if discards:
        triggers.resolve_effects(game, discards)


@dataclass(frozen=True, slots=True)
class FightNextBattle:
    """Fight the next battlefield the Attacker has not fought at yet, or end the Attack Phase's
    Fight Segment once every one has been.

    A work item, since choosing where to fight is a decision the procedure must pause for and
    pick up again once answered.
    """

    def resume(self, game: GameState) -> None:
        fight_next_battle(game)


def begin_fight(game: GameState) -> None:
    """Open the Fight Segment, where the Attacker picks a battlefield and a battle is fought there
    until every battlefield has had exactly one."""
    _declared_attack(game).segment = Segment.FIGHT
    game.stack.append(FightNextBattle())


def fight_next_battle(game: GameState) -> None:
    """Ask the Attacker where the next battle is fought, or do nothing once every battlefield has
    been fought at and the segment is over."""
    attack = _declared_attack(game)
    remaining = [index for index in range(len(attack.battlefields)) if index not in attack.fought]
    if not remaining:
        return
    game.pending = ChooseBattlefield(
        seat=attack.attacker, candidates=tuple(str(index) for index in remaining)
    )


# What Action Round follows each of the two that are one, or None when resolution follows instead
# (CR, Battle Sequence). Spelled out rather than taken from the enum's order, so a round added to
# :class:`~yasuki_core.engine.rules.vocabulary.segments.BattleSegment` has to say where it belongs.
_AFTER_BATTLE_SEGMENT: dict[BattleSegment, BattleSegment | None] = {
    BattleSegment.ENGAGE: BattleSegment.COMBAT,
    BattleSegment.COMBAT: None,
}


def fight_battle(game: GameState, battlefield: int) -> None:
    """Begin the battle at ``battlefield`` by opening its first segment.

    A battle is an Action Round per segment and then resolution, so the Attacker's choice of where
    only starts it: what happens next is whatever the seats do in the segments.
    """
    attack = _declared_attack(game)
    attack.current = battlefield
    attack.fought |= {battlefield}
    _open_battle_segment(game, BattleSegment.ENGAGE)


def _open_battle_segment(game: GameState, segment: BattleSegment) -> None:
    """Open ``segment``'s Action Round over the round it suspends, starting with the Defender.

    Both battle segments begin with the Defender rather than the active player (CR, Battle
    Sequence), which is the one way they differ from a phase's round.
    """
    attack = _declared_attack(game)
    attack.battle_segment = segment
    game.round_stack.append(game.round)
    game.round = ActionRound(
        timings=BATTLE_SEGMENT_TIMINGS[segment],
        priority=attack.defender,
        kind=RoundKind.BATTLE_SEGMENT,
    )
    # After the round exists, so an effect held for this moment lands on the round it was held for.
    triggers.resolve_delayed(game, Moment(segment, Boundary.BEGINNING))


def close_battle_segment(game: GameState) -> None:
    """Close the open battle segment, resuming the round it suspended and moving the battle on.

    The Combat Segment follows the Engage Segment, and resolution follows the Combat Segment (CR,
    Battle Sequence), so closing the last one is what fights the battle.
    """
    attack = _declared_attack(game)
    closed = attack.battle_segment
    if closed is None:
        raise ValueError("no battle segment is open")
    game.round = game.round_stack.pop()
    attack.battle_segment = None
    following = _AFTER_BATTLE_SEGMENT[closed]
    if following is not None:
        _open_battle_segment(game, following)
        return
    _resolve_battle(game)


def _resolve_battle(game: GameState) -> None:
    """Resolve the battle at the current battlefield, clear up after it, and queue the next.

    Raise ``ValueError`` when no battle is being fought, since resolution has nothing to resolve.
    """
    attack = _declared_attack(game)
    battlefield = attack.current
    if battlefield is None:
        raise ValueError("no battle is being fought")
    last_battle = len(attack.fought) == len(attack.battlefields)
    # All three read before anything is applied: resolution destroys the armies the effects and the
    # winner are read off, and moves the honor the outcome reports the movement of.
    effects = resolution_effects(game, battlefield)
    winner = _winner(game, battlefield)
    honor_before = _honor(game)
    # Where this battle's events start. Every battle of an Attack Phase runs inside one action, so
    # an outcome reading the action's events rather than its own would collect its predecessors'.
    events_before = len(game.action_events)

    attack.battle_segment = BattleSegment.RESOLUTION
    triggers.resolve_effects(game, effects)
    destructions = _resolution_destructions(game, events_before)
    outcome = _outcome(
        game,
        battlefield,
        winner=winner,
        honor_before=honor_before,
        destructions=destructions,
    )
    attack.amend(battlefield, outcome=outcome)
    # Queued before the announcement, so a trait that pauses on it stashes its cascade above the
    # work and resumes first.
    game.stack.append(AfterResolution(battlefield, last_battle=last_battle))
    triggers.fire(game, _battle_resolved(attack, battlefield, outcome, destructions))


@dataclass(frozen=True, slots=True)
class AfterResolution:
    """Open the Response Step a battle's resolution leaves for Reactions, then run After
    Resolution once it closes (CR, Battle Sequence).

    A work item, since the step is an Action Round the seats pass out of. It is queued twice: once
    to open the step, and again beneath it to run the After Resolution clauses when the step
    closes, with :class:`~.EndBattle` queued beneath those. A card that reads "after a battle's Resolution Segment" acts in the step, while the
    battle segment still reads Resolution.

    Attributes
    ----------
    battlefield : int
        The battlefield whose battle resolved.
    last_battle : bool
        Whether it was the Attack Phase's last, which sends every defending unit home.
    responded : bool, optional
        Whether the Response Step has already been offered. Default False.
    """

    battlefield: int
    last_battle: bool
    responded: bool = False

    def resume(self, game: GameState) -> None:
        # The Response Step is the turn machine's, which imports this module.
        from yasuki_core.engine.rules.turn.sequence import open_response_window

        if not self.responded and open_response_window(game):
            game.stack.append(replace(self, responded=True))
            return
        _declared_attack(game).battle_segment = BattleSegment.AFTER_RESOLUTION
        # Queued first, so a question the Terrain discard asks stashes its cascade above it and is
        # answered before the battle ends.
        game.stack.append(EndBattle())
        after_resolution(game, self.battlefield, last_battle=self.last_battle)


@dataclass(frozen=True, slots=True)
class EndBattle:
    """End the battle After Resolution closes: resolve what was delayed to the end of the battle,
    then move on to the next battlefield."""

    def resume(self, game: GameState) -> None:
        triggers.resolve_delayed(game, END_OF_BATTLE)
        attack = _declared_attack(game)
        attack.battle_segment = None
        attack.current = None
        game.stack.append(FightNextBattle())


def _winner(game: GameState, battlefield: int) -> PlayerId | None:
    """Which side took ``battlefield``, or None if the battle was tied.

    Decided before resolution runs, because resolution destroys the armies whose Force decides it.
    """
    attack = _declared_attack(game)
    attacking = army_force(game, battlefield, attack.attacker)
    defending = army_force(game, battlefield, attack.defender)
    if attacking == defending:
        return None
    return attack.attacker if attacking > defending else attack.defender


def _honor(game: GameState) -> dict[PlayerId, int]:
    """Each seat's Family Honor as it stands."""
    return {seat: info.honor for seat, info in game.table.seats.items()}


def _resolution_destructions(game: GameState, events_before: int) -> list[Destroyed]:
    """The destructions the resolution announced, in the order they went."""
    return [
        event
        for event in game.action_events[events_before:]
        if isinstance(event, Destroyed) and event.cause is Rulebook.BATTLE_RESOLUTION
    ]


def _outcome(
    game: GameState,
    battlefield: int,
    *,
    winner: PlayerId | None,
    honor_before: dict[PlayerId, int],
    destructions: list[Destroyed],
) -> BattleOutcome:
    """What the battle at ``battlefield`` turned out to have done.

    Destruction and the Province's fate are read off the board rather than off the effects
    resolution set out to apply, so a card that prevents one leaves an outcome that still matches
    the board. Honor is the difference across resolution, which is exact while nothing can act
    inside a resolution and will over-report once something can. There is no honor event to
    attribute a movement to a cause with.
    """
    province = _declared_attack(game).battlefields[battlefield].province
    return BattleOutcome(
        winner=winner,
        destroyed=tuple(event.card_id for event in destructions),
        province_destroyed=province not in game.table.zones,
        honor={
            seat: honor - honor_before[seat]
            for seat, honor in _honor(game).items()
            if honor != honor_before[seat]
        },
    )


def _battle_resolved(
    attack: AttackPhase, battlefield: int, outcome: BattleOutcome, destructions: list[Destroyed]
) -> BattleResolved:
    info = attack.battlefields[battlefield]
    return BattleResolved(
        battlefield=battlefield,
        province=info.province,
        attacker=attack.attacker,
        defender=attack.defender,
        winner=outcome.winner,
        province_destroyed=outcome.province_destroyed,
        destroyed=outcome.destroyed,
        ever_present=info.ever_present,
        destroyed_controllers=frozenset(
            event.controller for event in destructions if event.controller is not None
        ),
        terrains_played=info.terrains_played,
        terrains_destroyed=info.terrains_destroyed,
    )


def end_attack_phase(game: GameState) -> None:
    """Send every assigned unit home, then clear the attack and the battlefields it created, which
    the CR has cease to exist immediately before the Attack Phase ends.

    Units come home unbowed. Bowing an attacking army is an effect of battle resolution, and no
    battle is fought yet.
    """
    if game.attack is None:
        return
    for card in game.table.battlefield.cards:
        if not location_of(game.table, card).is_home:
            ops.return_home(game.table, card)
    game.attack = None
