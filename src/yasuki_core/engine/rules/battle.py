from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.table import location_of
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.decisions import (
    AssignUnits,
    ChooseBattlefield,
    DecisionResponse,
    assignment,
    assignment_token,
)
from yasuki_core.engine.rules.economy import effective_province_strength
from yasuki_core.engine.rules.effects import Destroy, DestroyProvince, Effect, GainHonor
from yasuki_core.engine.rules.units import unit_force
from yasuki_core.engine.rules.work import FightNextBattle
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.legality import province_zones
from yasuki_core.engine.rules.state import AttackPhase, BattlefieldInfo, GameState, Segment
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
    """The seat ``attacker`` attacks — the one other seat at the table.

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
        Declaration Segment offers the choice to; an attack a card creates names its own attacker,
        and need not be the seat whose turn it is.
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
        attack.assigned_in[card_id] = MANEUVERS_WINDOW
    game.pending = None
    if request.seat is attack.attacker:
        _ask_to_assign(game, attack.defender)
        return
    begin_fight(game)


def units_at(game: GameState, battlefield: int, seat: PlayerId) -> list[L5RCard]:
    """The Personalities ``seat`` has standing at ``battlefield``, in play order. One side of the
    army there, since a seat's units at a battlefield are all on the same side of it."""
    return [
        card
        for card in game.table.battlefield.cards
        if card.owner is seat
        and isinstance(card.printed, PersonalityPrint)
        and location_of(game.table, card).battlefield == battlefield
    ]


def army_force(game: GameState, battlefield: int, seat: PlayerId) -> int:
    """``seat``'s army Force at ``battlefield`` (CR, Army Force).

    The total of every unbowed Personality and Follower in it; an Item modifies its Personality's
    Force whether the Item is bowed or not. A side with no units has zero Force, which is what makes
    an empty side comparable rather than absent.
    """
    return sum(
        unit_force(game, personality, in_battle_resolution=True)
        for personality in units_at(game, battlefield, seat)
    )


def _cards_in(game: GameState, army: list[L5RCard]) -> int:
    """How many cards ``army`` is made of — each Personality plus everything attached to him. What
    the honor gain counts, which is cards rather than units."""
    return sum(1 + len(attachments_of(game, personality)) for personality in army)


def _destroy_army(army: list[L5RCard]) -> list[Effect]:
    """Destroy every unit in ``army``. Each Personality takes his whole unit with him."""
    return [Destroy(personality.id, Rulebook.BATTLE_RESOLUTION) for personality in army]


def resolution_effects(game: GameState, battlefield: int) -> list[Effect]:
    """What resolving the battle at ``battlefield`` does (CR, Battle Resolution).

    The higher Force wins and destroys the enemy army; an Attacker whose Force also cleared the
    Province Strength destroys the Province too. A tie with units on both sides destroys both. A tie
    on zero Force where either side is empty has no outcome, which is not the same as a tie that
    destroys nothing. The winner gains twice the cards it destroyed, and on a tie both do.
    """
    attack = _declared_attack(game)
    attacking = units_at(game, battlefield, attack.attacker)
    defending = units_at(game, battlefield, attack.defender)
    attacking_force = army_force(game, battlefield, attack.attacker)
    defending_force = army_force(game, battlefield, attack.defender)

    if attacking_force > defending_force:
        effects = _destroy_army(defending) + [
            GainHonor(attack.attacker, 2 * _cards_in(game, defending))
        ]
        province = attack.battlefields[battlefield].province
        if attacking_force > defending_force + effective_province_strength(game, province):
            effects.append(DestroyProvince(attack.attacker, province))
        return effects
    if defending_force > attacking_force:
        return _destroy_army(attacking) + [
            GainHonor(attack.defender, 2 * _cards_in(game, attacking))
        ]
    if not (attacking and defending):
        return []  # tied on zero Force with a side empty: no outcome
    return [
        *_destroy_army(defending),
        *_destroy_army(attacking),
        GainHonor(attack.attacker, 2 * _cards_in(game, defending)),
        GainHonor(attack.defender, 2 * _cards_in(game, attacking)),
    ]


def after_resolution(game: GameState, battlefield: int, *, last_battle: bool) -> None:
    """Send the survivors home (CR, After Resolution).

    Attacking units at this battlefield bow and then return home, both as effects of the
    resolution and neither as movement, and every card in the unit bows. Once the Attack Phase's last
    battle is over, defending units return home without bowing — every one of them, at every
    battlefield, since until then they hold the ground they defended.
    """
    attack = _declared_attack(game)
    for personality in units_at(game, battlefield, attack.attacker):
        # Every card in the unit bows, not just its leader: Conqueror's exemption is worded as
        # "cards in a Conqueror Personality's unit do not bow", so that is what it exempts them from.
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


def fight_battle(game: GameState, battlefield: int) -> None:
    """Fight the battle at ``battlefield``: resolve it, clear up after it, and queue the next.

    Nothing may be done inside a battle yet, so the whole thing runs from the Attacker's choice of
    where — resolution is arithmetic over the armies that maneuvers left standing.
    """
    attack = _declared_attack(game)
    attack.current = battlefield
    attack.fought |= {battlefield}
    last_battle = len(attack.fought) == len(attack.battlefields)
    # Read before anything is applied: the honor gain counts the cards in the enemy army, and once
    # resolution has run there is no army left to count.
    effects = resolution_effects(game, battlefield)
    triggers.resolve_effects(game, effects)
    after_resolution(game, battlefield, last_battle=last_battle)
    attack.current = None
    game.stack.append(FightNextBattle())


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
