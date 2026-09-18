from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey


@dataclass(frozen=True, slots=True)
class Look:
    """Cards one seat is looking at without their leaving the deck, as a card reading "look at the
    top four cards of your Fate deck" has it do.

    A look is a fact of the state rather than of any one decision, because the questions that
    follow it ("put one in your hand", "put the rest back in any order") are ordinary decisions of
    several kinds and every one of them has to know which cards are in view. It is also what makes
    backing out impossible: once a seat has read the cards, there is no taking that back.

    Attributes
    ----------
    seat : PlayerId
        The seat looking.
    deck : DeckKey
        The deck the cards are in.
    card_ids : tuple of str
        The cards in view, top of the deck first.
    """

    seat: PlayerId
    deck: DeckKey
    card_ids: tuple[str, ...]
