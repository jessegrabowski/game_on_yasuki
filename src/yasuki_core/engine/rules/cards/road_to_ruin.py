from yasuki_core.engine.rules.abilities import ProductionBoost, register_production_boost
from yasuki_core.engine.rules.effects import Destroy, Effect
from yasuki_core.game_pieces.cards import L5RCard


# --- Outlying Farms ---


def _destroy_for_boosting(card: L5RCard) -> list[Effect]:
    """ "...if you did, destroy it after it bows." The destruction is this card's price for the
    boost; Jade Mine and Slave Pits pay different ones."""
    return [Destroy(card.id)]


register_production_boost("outlying_farms", ProductionBoost(2, _destroy_for_boosting))
