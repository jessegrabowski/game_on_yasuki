from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import location_of
from yasuki_core.engine.rules.decisions import (
    AssignUnits,
    DecisionResponse,
    assignment,
    assignment_token,
)
from yasuki_core.engine.rules.legality import province_zones
from yasuki_core.engine.rules.state import AttackPhase, BattlefieldInfo, GameState, Segment
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint


def _declared_attack(game: GameState) -> AttackPhase:
    """The attack in progress. Raise ``ValueError`` outside one, since every caller here is a step
    of the Attack Phase and has nothing to do without it."""
    if game.attack is None:
        raise ValueError("no attack is declared")
    return game.attack


def defender_of(game: GameState, attacker: PlayerId) -> PlayerId:
    """The seat ``attacker`` attacks — the one other seat at the table.

    Raise ``ValueError`` at a table not holding exactly two seats: the Defender is a single seat in
    every rule written about a battle.
    """
    opponents = [seat for seat in game.table.seats if seat is not attacker]
    if len(opponents) != 1:
        raise ValueError(f"{attacker.name} has {len(opponents)} opponents, not one")
    return opponents[0]


def declare_attack(game: GameState) -> None:
    """Declare the active player's attack, creating a battlefield at each Defender Province, in
    Province order."""
    attacker = game.active
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

    Both clauses sit on the Personality rather than on the unit he leads: he must be unbowed — *"A
    unit led by a bowed Personality may not be assigned"* — and at home, since assigning moves a unit
    out of home rather than between battlefields. A bowed Follower blocks nothing; it only stops
    contributing Force once a battle resolves.
    """
    return [
        card
        for card in game.table.battlefield.cards
        if card.owner is seat
        and isinstance(card.printed, PersonalityPrint)
        and not card.bowed
        and location_of(game.table, card).is_home
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

    The Attacker assigns first and the Defender answers next, which is the CR's order; each seat
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
    """Send each Personality the answer names to its battlefield, then ask the other seat.

    The Defender answering ends the segment.
    """
    attack = _declared_attack(game)
    for token in response.choices:
        card_id, battlefield = assignment(token)
        ops.assign(game.table, game.table.cards_by_id[card_id], battlefield)
    game.pending = None
    if request.seat is attack.attacker:
        _ask_to_assign(game, attack.defender)


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
