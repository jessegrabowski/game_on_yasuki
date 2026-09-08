from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.gold.production import (
    effective_gold_production,
    reads_its_targets,
)
from yasuki_core.engine.rules.gold.self_grants import maximum_gold_production
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import SenseiPrint


def gold_producers(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The unbowed gold producers ``seat`` controls in play — its Stronghold and gold Holdings —
    each a source it may bow for gold (KD6, stat-derived).

    A Sensei is never one of them. Its printed Gold Production is a delta the Stronghold receives,
    not gold the Sensei makes, so counting it would pay the seat twice for the same characteristic.
    """
    return [
        card
        for card in game.table.battlefield.cards
        if card.owner is seat
        and not card.bowed
        and not isinstance(card.printed, SenseiPrint)
        and effective_gold_production(game, card) > 0
    ]


def gold_reach(game: GameState, seat: PlayerId) -> tuple[int, tuple[L5RCard, ...]]:
    """What ``seat`` can raise before knowing what it is paying for, split from the producers that
    still need to know.

    Only a producer with a registered gold handler can read the cards being paid for; everything
    else yields its printed Gold Production plus its modifiers whatever the target.

    Returns
    -------
    fixed : int
        The seat's pool, every target-independent producer's yield, and every bow-time boost a
        producer could add if the seat opts in.
    variable : tuple of L5RCard
        The unbowed producers whose yield may still depend on what they pay for.
    """
    fixed = game.gold[seat]
    variable: list[L5RCard] = []
    for producer in gold_producers(game, seat):
        if reads_its_targets(producer):
            variable.append(producer)
        else:
            fixed += maximum_gold_production(game, producer)
    return fixed, tuple(variable)


def reachable_gold(game: GameState, seat: PlayerId, card: L5RCard | None = None) -> int:
    """The gold ``seat`` could muster: its pool plus the yield of every unbowed producer, plus any
    bow-time boost a producer could add if the seat opts in.

    Parameters
    ----------
    card : L5RCard, optional
        The card being paid for, since a producer's yield can depend on what it pays for. Omit for a
        rulebook cost, which prices no card. Default None.
    """
    targets = () if card is None else (card,)
    fixed, variable = gold_reach(game, seat)
    return fixed + sum(
        maximum_gold_production(game, producer, targets=targets) for producer in variable
    )
