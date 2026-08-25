from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.legality import province_zones
from yasuki_core.engine.rules.state import AttackPhase, BattlefieldInfo, GameState


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
