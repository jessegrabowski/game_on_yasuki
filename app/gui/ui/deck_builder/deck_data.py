from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from app.database import query_all_cards, get_prints_by_card_id, query_cards_filtered

if TYPE_CHECKING:
    from app.gui.ui.deck_builder.filter_dialog import FilterOptions

_CARDS_CACHE: list[dict] | None = None


def _extract_experience_sort_key(card: dict) -> tuple[int, str]:
    """
    Extract experience level for sorting.

    Returns a tuple of (priority, experience_string) where:
    - priority is a numeric value for sorting (lower = earlier)
    - experience_string is the experience level for secondary sorting

    Experience level priority:
    - Inexperienced: -1
    - Base version (no experience): 0
    - Experienced: 1
    - Experienced 2: 2
    - Experienced 3: 3
    - etc.

    Parameters
    ----------
    card : dict
        Card record from database

    Returns
    -------
    sort_key : tuple of (int, str)
        Priority and experience string for sorting
    """
    card_id = card.get("id", "")

    if "_inexp" in card_id:
        return (-1, "inexp")

    if "_exp" in card_id:
        parts = card_id.split("_exp")
        if len(parts) > 1:
            exp_suffix = parts[-1]

            if not exp_suffix or exp_suffix == "":
                return (1, "exp")

            if exp_suffix.startswith("_") and exp_suffix[1:].isdigit():
                level = int(exp_suffix[1:])
                return (level, f"exp{level}")

            if exp_suffix.isdigit():
                level = int(exp_suffix)
                return (level, f"exp{level}")

            if "_" in exp_suffix:
                parts = exp_suffix.split("_")
                if parts[0].isdigit():
                    level = int(parts[0])
                    return (level, exp_suffix)
                return (1, exp_suffix)

            return (1, exp_suffix)

    return (0, "")


def _card_sort_key(card: dict) -> tuple[str, int, str]:
    """
    Generate sort key for cards.

    Sorts by:
    1. Base name without subtitle (alphabetically)
    2. Experience level (numerically)
    3. Experience string (alphabetically for variants)

    Parameters
    ----------
    card : dict
        Card record from database

    Returns
    -------
    sort_key : tuple of (str, int, str)
        Sort key for ordering cards
    """
    full_name = card.get("name", "")
    card_type = card.get("type", "")

    if card_type == "personality":
        base_name = full_name.split(", ")[0].lower() if ", " in full_name else full_name.lower()
    else:
        base_name = full_name.lower()

    exp_priority, exp_string = _extract_experience_sort_key(card)

    return base_name, exp_priority, exp_string


def clear_cards_cache() -> None:
    """Clear the cards cache to force reload from database."""
    global _CARDS_CACHE
    _CARDS_CACHE = None


def load_cards_from_db() -> list[dict]:
    """
    Load all cards from PostgreSQL database.

    Returns
    -------
    cards : list of dict
        Card records from database
    """
    global _CARDS_CACHE
    if _CARDS_CACHE is not None:
        return _CARDS_CACHE

    _CARDS_CACHE = query_all_cards()
    return _CARDS_CACHE


@dataclass(frozen=True)
class DeckState:
    """
    Immutable state tracking deck composition.

    Tracks card_id -> list of (print_id, count) tuples.
    """

    cards: dict[str, list[tuple[int, int]]] = field(default_factory=dict)

    def add_card(self, card_id: str, print_id: int) -> "DeckState":
        """
        Add one copy of a card with specific print to deck.

        Parameters
        ----------
        card_id : str
            Card identifier
        print_id : int
            Print identifier

        Returns
        -------
        new_state : DeckState
            Updated deck state
        """
        new_cards = dict(self.cards)

        if card_id not in new_cards:
            new_cards[card_id] = [(print_id, 1)]
        else:
            print_list = list(new_cards[card_id])
            found = False
            for i, (pid, count) in enumerate(print_list):
                if pid == print_id:
                    print_list[i] = (pid, count + 1)
                    found = True
                    break
            if not found:
                print_list.append((print_id, 1))
            new_cards[card_id] = print_list

        return replace(self, cards=new_cards)

    def remove_card(self, card_id: str, print_id: int | None = None) -> "DeckState":
        """
        Remove one copy of a card from deck.

        Parameters
        ----------
        card_id : str
            Card identifier
        print_id : int or None
            Specific print to remove, or None to remove any print

        Returns
        -------
        new_state : DeckState
            Updated deck state
        """
        if card_id not in self.cards:
            return self

        new_cards = dict(self.cards)
        print_list = list(new_cards[card_id])

        if print_id is None:
            # Remove first available print
            if print_list:
                pid, count = print_list[0]
                if count > 1:
                    print_list[0] = (pid, count - 1)
                else:
                    print_list.pop(0)
        else:
            # Remove specific print
            for i, (pid, count) in enumerate(print_list):
                if pid == print_id:
                    if count > 1:
                        print_list[i] = (pid, count - 1)
                    else:
                        print_list.pop(i)
                    break

        if print_list:
            new_cards[card_id] = print_list
        else:
            del new_cards[card_id]

        return replace(self, cards=new_cards)

    def clear(self) -> "DeckState":
        """
        Clear all cards from deck.

        Returns
        -------
        new_state : DeckState
            Empty deck state
        """
        return DeckState()

    def get_card_count(self, side: str, cards_by_id: dict[str, dict]) -> int:
        """
        Count total cards for a specific side (FATE, DYNASTY, or SETUP).

        Parameters
        ----------
        side : str
            Side identifier (FATE, DYNASTY, or SETUP)
        cards_by_id : dict of str to dict
            Card data lookup by ID

        Returns
        -------
        count : int
            Total card count for the side
        """
        total = 0
        for card_id, print_list in self.cards.items():
            card = cards_by_id.get(card_id)
            if not card:
                continue

            card_side = card.get("side")

            # Check if card matches the requested side
            if side == "SETUP":
                # Setup cards are anything that's not FATE or DYNASTY
                if card_side not in ("FATE", "DYNASTY"):
                    total += sum(count for _, count in print_list)
            else:
                # Regular FATE or DYNASTY side
                if card_side == side:
                    total += sum(count for _, count in print_list)
        return total


class DeckBuilderRepository:
    """Repository for deck builder data operations."""

    def __init__(self):
        self._all_cards = load_cards_from_db()
        self._cards_by_id = {c["id"]: c for c in self._all_cards}

    @property
    def all_cards(self) -> list[dict]:
        return self._all_cards

    @property
    def cards_by_id(self) -> dict[str, dict]:
        return self._cards_by_id

    def get_card(self, card_id: str) -> dict | None:
        """
        Get card data by ID.

        Parameters
        ----------
        card_id : str
            Card identifier

        Returns
        -------
        card : dict or None
            Card data or None if not found
        """
        return self._cards_by_id.get(card_id)

    def get_prints(self, card_id: str) -> list[dict]:
        """
        Get all prints for a card.

        Parameters
        ----------
        card_id : str
            Card identifier

        Returns
        -------
        prints : list of dict
            Print records from database
        """
        return get_prints_by_card_id(card_id)

    def filter_cards(
        self,
        query: str,
        filter_options: "FilterOptions | dict | None" = None,
    ) -> list[dict]:
        """
        Filter cards by search query and optional property filters.

        Uses SQL-based filtering for optimal performance.
        Sorts results by name, then by experience level within each name group.

        Parameters
        ----------
        query : str
            Search query (case-insensitive)
        filter_options : FilterOptions, dict, or None
            Filter options containing property constraints.
            Can be FilterOptions object or dict of filters.

        Returns
        -------
        filtered : list of dict
            Cards matching the query and filters, sorted by name and experience level
        """
        # Convert FilterOptions to dict for database query
        filter_dict = None
        if filter_options:
            if isinstance(filter_options, dict):
                filter_dict = filter_options
            elif hasattr(filter_options, "has_filters") and filter_options.has_filters():
                filter_dict = filter_options.filters

        # Performance optimization: use cached cards when no query and no filters
        # This avoids expensive database query when showing all cards
        if not query and not filter_dict:
            # Return cached cards sorted by name and experience
            return sorted(self._all_cards, key=_card_sort_key)

        cards = query_cards_filtered(text_query=query, filter_options=filter_dict)

        # Sort by name and experience level (SQL sorts by name, we refine with experience)
        return sorted(cards, key=_card_sort_key)
