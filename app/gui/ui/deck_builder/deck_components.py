import tkinter as tk
from typing import TYPE_CHECKING
import logging

from app.gui.ui.deck_builder.components import ScrollableListBox
from app.gui.ui.deck_builder.card_preview import format_card_display_name
from app.gui.ui.deck_builder.parse_search import parse_and_build_query

if TYPE_CHECKING:
    from app.gui.ui.deck_builder.filter_dialog import FilterOptions

logger = logging.getLogger(__name__)


def pluralize(word: str) -> str:
    """
    Convert a card type to its plural form, preserving capitalization.

    Parameters
    ----------
    word : str
        Singular form of card type

    Returns
    -------
    plural : str
        Plural form with proper capitalization
    """
    word_lower = word.lower()
    match word_lower:
        case _ if word_lower.endswith("y"):
            # Most words ending in 'y' -> 'ies'
            result = word_lower[:-1] + "ies"
        case _ if word_lower.endswith(("s", "sh", "ch", "x", "z")):
            result = word_lower + "es"
        case _:
            result = word_lower + "s"

    # Capitalize if original was capitalized
    if word and word[0].isupper():
        return result.capitalize()

    return result


def extract_card_id(text: str) -> str | None:
    """
    Extract card_id from formatted list item text.

    Parameters
    ----------
    text : str
        List item text containing ⟨card_id⟩

    Returns
    -------
    card_id : str or None
        Extracted card ID or None if not found
    """
    if "⟨" in text and "⟩" in text:
        return text.split("⟨")[-1].rstrip("⟩")
    logger.warning(f"Could not extract card_id from: {text}")
    return None


def extract_print_and_card_id(text: str) -> tuple[int, str] | None:
    """
    Extract print_id and card_id from formatted deck list item.

    Parameters
    ----------
    text : str
        List item text containing ⟨print_id:card_id⟩

    Returns
    -------
    ids : tuple of (int, str) or None
        (print_id, card_id) or None if not found
    """
    if "⟨" in text and "⟩" in text:
        ids_part = text.split("⟨")[-1].rstrip("⟩")
        print_id_str, card_id = ids_part.split(":")
        return int(print_id_str), card_id
    logger.warning(f"Could not extract IDs from: {text}")
    return None


class FilteredCardList(ScrollableListBox):
    """Listbox showing filtered card search results."""

    def __init__(self, master: tk.Widget, repository):
        super().__init__(master, selectmode="browse")
        self._repository = repository
        self._filter_query = ""
        self._filter_options: "FilterOptions | None" = None
        self._card_ids: list[str] = []

    def set_filter(self, query: str) -> None:
        """
        Set filter query and refresh display.

        Uses Scryfall-style query language to parse search terms.

        Parameters
        ----------
        query : str
            Search query string (supports field:value, comparisons, etc.)
        """
        self._filter_query = query.strip()
        self.refresh()

    def set_filter_options(self, filter_options: "FilterOptions | None") -> None:
        """
        Set filter options and refresh display.

        Parameters
        ----------
        filter_options : FilterOptions or None
            Filter options containing property constraints
        """
        self._filter_options = filter_options
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        self._card_ids = []

        # Parse the search query using the query language
        text_query, parsed_filters = parse_and_build_query(self._filter_query)

        # Merge with dialog filters (dialog filters take precedence)
        combined_filters = dict(parsed_filters)
        if self._filter_options and self._filter_options.has_filters():
            combined_filters.update(self._filter_options.filters)

        # Convert combined filters back to FilterOptions-like dict, or None if empty
        filter_dict = combined_filters if combined_filters else None

        filtered = self._repository.filter_cards(text_query, filter_dict)
        for card in filtered:
            display_name = format_card_display_name(card)
            self.insert(tk.END, display_name)
            self._card_ids.append(card["id"])

    def get_selected_card_id(self) -> str | None:
        """
        Get card_id of currently selected item.

        Returns
        -------
        card_id : str or None
            Card ID or None if nothing selected
        """
        sel = self.get_selection()
        if not sel:
            return None
        index = sel[0]
        if 0 <= index < len(self._card_ids):
            return self._card_ids[index]
        return None


class DeckCardList(ScrollableListBox):
    """Listbox showing cards in a deck (Fate, Dynasty, or Setup)."""

    def __init__(self, master: tk.Widget, repository, side: str):
        super().__init__(master, selectmode="browse")
        self._repository = repository
        self._side = side
        self._item_data: list[tuple[int | None, str]] = []

    def refresh(self, deck_state) -> None:
        """
        Refresh display from deck state, grouped by card type.

        Parameters
        ----------
        deck_state : DeckState
            Current deck state
        """
        self.clear()
        self._item_data = []

        # Group cards by type
        cards_by_type: dict[str, list[tuple[str, list[tuple[int, int]]]]] = {}

        for card_id, print_list in deck_state.cards.items():
            card = self._repository.get_card(card_id)
            if not card:
                continue

            card_side = card.get("side")

            # Check if card matches this list's side
            if self._side == "SETUP":
                # Setup cards are anything that's not FATE or DYNASTY
                if card_side in ("FATE", "DYNASTY"):
                    continue
            else:
                # Regular FATE or DYNASTY list
                if card_side != self._side:
                    continue

            # Group by type
            card_type = card.get("type", "Unknown")
            if card_type not in cards_by_type:
                cards_by_type[card_type] = []
            cards_by_type[card_type].append((card_id, print_list))

        # Display cards grouped by type
        for card_type in sorted(cards_by_type.keys()):
            cards_in_type = cards_by_type[card_type]

            # Calculate total count for this type
            type_total = sum(
                sum(count for _, count in print_list) for _, print_list in cards_in_type
            )

            # Add type header with count first and proper plural
            plural_type = pluralize(card_type)
            type_header = f"{type_total}x {plural_type}"
            self.insert(tk.END, type_header)
            self._item_data.append((None, None))  # Type header has no card

            # Add cards under this type
            for card_id, print_list in sorted(cards_in_type):
                card = self._repository.get_card(card_id)
                if not card:
                    continue

                total_count = sum(count for _, count in print_list)
                display_name = format_card_display_name(card)

                # If only one print, show on one line (indented under type)
                if len(print_list) == 1:
                    print_id, count = print_list[0]
                    prints = self._repository.get_prints(card_id)
                    print_info = next((p for p in prints if p["print_id"] == print_id), None)
                    set_name = print_info.get("set_name") if print_info else None

                    if set_name:
                        entry = f"    {total_count}x {display_name} [{set_name}]"
                    else:
                        entry = f"    {total_count}x {display_name}"

                    self.insert(tk.END, entry)
                    self._item_data.append((print_id, card_id))
                else:
                    # Multiple prints - show hierarchical view (indented under type)
                    entry = f"    {total_count}x {display_name}"
                    self.insert(tk.END, entry)
                    self._item_data.append((None, card_id))

                    # Sub-entries for each print (double indented)
                    for print_id, count in sorted(print_list):
                        prints = self._repository.get_prints(card_id)
                        print_info = next((p for p in prints if p["print_id"] == print_id), None)
                        set_name = print_info.get("set_name") if print_info else "Unknown"

                        sub_entry = f"        {count}x {set_name}"
                        self.insert(tk.END, sub_entry)
                        self._item_data.append((print_id, card_id))

    def _add_deck_entry(self, card: dict, card_id: str, print_id: int, count: int) -> None:
        """DEPRECATED: No longer used, kept for compatibility."""
        pass

    def get_selected_ids(self) -> tuple[int, str] | None:
        """
        Get print_id and card_id of currently selected item.

        Returns
        -------
        ids : tuple of (int, str) or None
            (print_id, card_id) or None if nothing selected
        """
        sel = self.get_selection()
        if not sel:
            return None
        index = sel[0]
        if 0 <= index < len(self._item_data):
            print_id, card_id = self._item_data[index]

            # Type headers have (None, None) - can't be removed
            if card_id is None:
                return None

            # If print_id is None (card entry with multiple prints), use the first print
            if print_id is None:
                # Find the first sub-entry for this card
                for i in range(index + 1, len(self._item_data)):
                    pid, cid = self._item_data[i]
                    if cid == card_id and pid is not None:
                        return (pid, card_id)
            return (print_id, card_id) if print_id is not None else None
        return None

    def get_total_count(self, deck_state, cards_by_id: dict) -> int:
        """
        Get total card count for this side.

        Parameters
        ----------
        deck_state : DeckState
            Current deck state
        cards_by_id : dict of str to dict
            Card lookup by ID

        Returns
        -------
        count : int
            Total cards
        """
        return deck_state.get_card_count(self._side, cards_by_id)
