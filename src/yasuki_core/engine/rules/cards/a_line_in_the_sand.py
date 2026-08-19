from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import InvestAbility, register_invest
from yasuki_core.engine.rules.effects import Choose, Effect, MoveToHand, Show, ShuffleDeck
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


# --- Stockpiled Weapon ---


@choice_resolver("stockpiled_weapon", prompt="Search your Fate deck for a Stockpiled Weapon")
def _resolve_stockpiled_weapon_search(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [
        Show(chosen[0]),
        MoveToHand(chosen[0], seat),
        ShuffleDeck(DeckKey(seat, Side.FATE)),
    ]


def _stockpiled_weapon_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """Fetch another copy out of the Fate deck, or nothing when the deck holds none — the Invest is
    then a pure surcharge, which the card does not forbid paying."""
    seat = source.owner
    deck = game.table.decks[DeckKey(seat, Side.FATE)].cards
    copies = tuple(card.id for card in deck if card.printed_id == "stockpiled_weapon")
    if not copies:
        return []
    return [Choose(seat, copies, 1, 1, "stockpiled_weapon", source.id)]


register_invest("stockpiled_weapon", InvestAbility(1, 1, _stockpiled_weapon_invest))
