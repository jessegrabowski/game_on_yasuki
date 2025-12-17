import tkinter as tk
from collections.abc import Callable

from app.gui.ui.deck_builder.components import CardStatsPanel, PrintSelector
from app.gui.ui.deck_builder.card_preview import CardPreviewController
from app.gui.ui.deck_builder.deck_data import DeckBuilderRepository, DeckState
from app.gui.ui.deck_builder.deck_components import FilteredCardList, DeckCardList
from app.gui.ui.deck_builder.filter_dialog import FilterDialog, FilterOptions
from app.gui.ui.deck_builder.search_help import show_search_help
import logging

logger = logging.getLogger(__name__)


class DeckBuilderWindow:
    """
    Deck builder UI with three-column layout.

    Columns
    -------
    Left: Search box and filtered card list
    Middle: Deck composition (Fate and Dynasty decks)
    Right: Card preview with image, stats, and rules text
    """

    def __init__(self, master: tk.Misc, on_close: Callable | None = None):
        self.master = master
        self.on_close = on_close
        self.win = tk.Toplevel(master)
        self.win.title("Deck Builder")
        self.win.geometry("1600x900")
        self.win.protocol("WM_DELETE_WINDOW", self._close)

        logger.info("Initializing Deck Builder window")

        self._repository = DeckBuilderRepository()
        self._deck_state = DeckState()
        self._updating_lists = False  # Flag to prevent event handlers during refresh
        self._filter_options = FilterOptions()
        self._search_debounce_id = None  # For debouncing search input

        self._setup_layout()
        self._setup_event_bindings()

        logger.info(f"Loaded {len(self._repository.all_cards)} cards from database")
        self.card_list.refresh()

    def _setup_layout(self) -> None:
        """Create the three-column layout with all UI components."""
        # Use grid for better control over column widths
        self.win.grid_columnconfigure(0, weight=1, minsize=300)  # Left: card list
        self.win.grid_columnconfigure(1, weight=2, minsize=400)  # Middle: deck (wider)
        self.win.grid_columnconfigure(2, weight=1, minsize=300)  # Right: preview (narrower)
        self.win.grid_rowconfigure(0, weight=1)

        col1 = self._create_card_list_column(self.win)
        col2 = self._create_deck_composition_column(self.win)
        col3 = self._create_preview_column(self.win)

        col1.grid(row=0, column=0, sticky="nsew")
        col2.grid(row=0, column=1, sticky="nsew")
        col3.grid(row=0, column=2, sticky="nsew")

    def _create_card_list_column(self, parent: tk.Widget) -> tk.Frame:
        """Create left column with search and filtered card list."""
        col = tk.Frame(parent, padx=8, pady=8)

        search_frame = tk.Frame(col)
        search_frame.pack(fill="x")
        tk.Label(search_frame, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=(6, 4))
        search_entry.bind("<KeyRelease>", lambda e: self._on_search_changed())

        tk.Button(search_frame, text="?", width=2, command=self._show_search_help).pack(side="left")

        self.card_list = FilteredCardList(col, self._repository)
        self.card_list.pack(fill="both", expand=True, pady=(8, 0))

        btn_frame = tk.Frame(col)
        btn_frame.pack(fill="x", pady=(8, 0))
        tk.Button(btn_frame, text="Filters", command=self._open_filter_dialog).pack(side="left")
        tk.Button(btn_frame, text="Clear Filters", command=self._clear_filters).pack(
            side="left", padx=(4, 0)
        )

        return col

    def _create_deck_composition_column(self, parent: tk.Widget) -> tk.Frame:
        """Create middle column with Fate, Dynasty, and Setup deck lists."""
        col = tk.Frame(parent, padx=8, pady=8)

        self.fate_label = tk.Label(col, text="Fate Deck (0)", font=("TkDefaultFont", 11, "bold"))
        self.fate_label.pack(anchor="w")
        self.fate_list = DeckCardList(col, self._repository, "FATE")
        self.fate_list.pack(fill="both", expand=True, pady=(4, 0))

        self.dynasty_label = tk.Label(
            col, text="Dynasty Deck (0)", font=("TkDefaultFont", 11, "bold")
        )
        self.dynasty_label.pack(anchor="w", pady=(12, 0))
        self.dynasty_list = DeckCardList(col, self._repository, "DYNASTY")
        self.dynasty_list.pack(fill="both", expand=True, pady=(4, 0))

        tk.Label(col, text="Setup Cards", font=("TkDefaultFont", 11, "bold")).pack(
            anchor="w", pady=(12, 0)
        )
        self.setup_list = DeckCardList(col, self._repository, "SETUP")
        self.setup_list.frame.configure(height=150)
        self.setup_list.pack(fill="x", pady=(4, 0))

        actions = tk.Frame(col)
        actions.pack(fill="x", pady=(12, 0))
        tk.Button(actions, text="Clear Deck", command=self._clear_deck).pack(side="left")

        return col

    def _create_preview_column(self, parent: tk.Widget) -> tk.Frame:
        """Create right column with card preview."""
        col = tk.Frame(parent, padx=8, pady=8)

        tk.Label(col, text="Card Preview", font=("TkDefaultFont", 11, "bold")).pack(anchor="w")

        preview_img_lbl = tk.Label(col)
        preview_img_lbl.pack(anchor="n", pady=(4, 0), expand=True, fill="both")
        preview_img_lbl.bind("<Double-Button-1>", lambda e: self._add_from_preview())

        print_selector = PrintSelector(col, self._on_prev_print, self._on_next_print)
        print_selector.pack(fill="x", pady=(4, 0))

        stats_panel = CardStatsPanel(col)
        stats_panel.pack(fill="x", pady=(4, 0))

        tk.Label(col, text="Flavor Text", font=("TkDefaultFont", 9, "bold")).pack(
            anchor="w", pady=(4, 2)
        )

        flavor_holder = tk.Frame(col)
        flavor_holder.pack(fill="x", pady=(0, 4))
        flavor_text = tk.Text(flavor_holder, wrap="word", height=3, font=("TkDefaultFont", 9))
        flavor_text.pack(side="left", fill="x", expand=True)
        flavor_scroll = tk.Scrollbar(flavor_holder, orient="vertical", command=flavor_text.yview)
        flavor_text.configure(yscrollcommand=flavor_scroll.set, state="disabled")
        flavor_scroll.pack(side="left", fill="y")

        tk.Label(col, text="Rules Text", font=("TkDefaultFont", 9, "bold")).pack(
            anchor="w", pady=(4, 2)
        )

        text_holder = tk.Frame(col)
        text_holder.pack(fill="x", pady=(0, 8))
        preview_text = tk.Text(text_holder, wrap="word", height=6, font=("TkDefaultFont", 9))
        preview_text.pack(side="left", fill="x", expand=True)
        tscroll = tk.Scrollbar(text_holder, orient="vertical", command=preview_text.yview)
        preview_text.configure(yscrollcommand=tscroll.set, state="disabled")
        tscroll.pack(side="left", fill="y")

        close_frame = tk.Frame(col)
        close_frame.pack(side="bottom", fill="x")
        tk.Button(close_frame, text="Close", command=self._close).pack(side="right")

        self.preview_controller = CardPreviewController(
            preview_img_lbl,
            stats_panel,
            preview_text,
            flavor_text,
            print_selector,
            self.win,
            self._repository,
        )

        # Store flavor text widget for later use
        self.flavor_text = flavor_text

        return col

    def _setup_event_bindings(self) -> None:
        """Bind event handlers for user interactions."""
        self.card_list.bind("<Double-Button-1>", lambda e: self._add_selected())
        self.card_list.bind("<<ListboxSelect>>", lambda e: self._on_card_list_select())

        self.fate_list.bind("<Double-Button-1>", lambda e: self._remove_from_fate())
        self.fate_list.bind(
            "<<ListboxSelect>>", lambda e: self._on_deck_list_select(self.fate_list)
        )

        self.dynasty_list.bind("<Double-Button-1>", lambda e: self._remove_from_dynasty())
        self.dynasty_list.bind(
            "<<ListboxSelect>>", lambda e: self._on_deck_list_select(self.dynasty_list)
        )

        self.setup_list.bind("<Double-Button-1>", lambda e: self._remove_from_setup())
        self.setup_list.bind(
            "<<ListboxSelect>>", lambda e: self._on_deck_list_select(self.setup_list)
        )

    def _close(self) -> None:
        if callable(self.on_close):
            try:
                self.on_close()
            except Exception:
                pass
        try:
            self.win.destroy()
        except Exception:
            pass

    def _on_search_changed(self) -> None:
        """Handle search box changes with debouncing to improve performance."""
        # Cancel any pending search
        if self._search_debounce_id is not None:
            self.win.after_cancel(self._search_debounce_id)

        # Schedule new search after delay (150ms is responsive but reduces queries)
        self._search_debounce_id = self.win.after(150, self._execute_search)

    def _execute_search(self) -> None:
        """Execute the actual search (called after debounce delay)."""
        self._search_debounce_id = None
        query = self.search_var.get()
        self.card_list.set_filter(query)

    def _show_search_help(self) -> None:
        """Show search syntax help dialog."""
        show_search_help(self.win)

    def _open_filter_dialog(self) -> None:
        """Open the filter dialog and apply selected filters."""
        dialog = FilterDialog(self.win, self._filter_options)
        result = dialog.show()

        if result is not None:
            self._filter_options = result
            self.card_list.set_filter_options(self._filter_options)

    def _clear_filters(self) -> None:
        """Clear all filters and search text."""
        self._filter_options = FilterOptions()
        self.search_var.set("")
        self.card_list.set_filter("")
        self.card_list.set_filter_options(self._filter_options)

    def _clear_deck(self) -> None:
        self._deck_state = self._deck_state.clear()
        self._refresh_deck_lists()

    def _add_selected(self) -> None:
        card_id = self.card_list.get_selected_card_id()
        if not card_id:
            return

        print_id = self._get_print_id_for_card(card_id)
        if print_id is None:
            logger.warning(f"No prints found for card {card_id}")
            return

        self._deck_state = self._deck_state.add_card(card_id, print_id)
        self._refresh_deck_lists()

    def _get_print_id_for_card(self, card_id: str) -> int | None:
        """Get print ID for card, preferring currently viewed print."""
        if (
            self.preview_controller.get_current_card_id() == card_id
            and self.preview_controller.get_current_print_id()
        ):
            return self.preview_controller.get_current_print_id()

        prints = self._repository.get_prints(card_id)
        return prints[0]["print_id"] if prints else None

    def _add_from_preview(self) -> None:
        card_id = self.preview_controller.get_current_card_id()
        print_id = self.preview_controller.get_current_print_id()

        if not card_id or not print_id:
            return

        self._deck_state = self._deck_state.add_card(card_id, print_id)
        self._refresh_deck_lists()

    def _remove_from_fate(self) -> None:
        ids = self.fate_list.get_selected_ids()
        if not ids:
            return
        print_id, card_id = ids
        self._deck_state = self._deck_state.remove_card(card_id, print_id)
        self._refresh_deck_lists()

    def _remove_from_dynasty(self) -> None:
        ids = self.dynasty_list.get_selected_ids()
        if not ids:
            return
        print_id, card_id = ids
        self._deck_state = self._deck_state.remove_card(card_id, print_id)
        self._refresh_deck_lists()

    def _remove_from_setup(self) -> None:
        ids = self.setup_list.get_selected_ids()
        if not ids:
            return
        print_id, card_id = ids
        self._deck_state = self._deck_state.remove_card(card_id, print_id)
        self._refresh_deck_lists()

    def _refresh_deck_lists(self) -> None:
        self._updating_lists = True
        try:
            self.fate_list.refresh(self._deck_state)
            self.dynasty_list.refresh(self._deck_state)
            self.setup_list.refresh(self._deck_state)

            fate_count = self._deck_state.get_card_count("FATE", self._repository.cards_by_id)
            dynasty_count = self._deck_state.get_card_count("DYNASTY", self._repository.cards_by_id)
            setup_count = self._deck_state.get_card_count("SETUP", self._repository.cards_by_id)

            self.fate_label.config(text=f"Fate Deck ({fate_count})")
            self.dynasty_label.config(text=f"Dynasty Deck ({dynasty_count})")

            self.win.title(
                f"Deck Builder - Fate:{fate_count} Dynasty:{dynasty_count} Setup:{setup_count}"
            )
        finally:
            self._updating_lists = False

    def _on_card_list_select(self) -> None:
        if self._updating_lists:
            return

        card_id = self.card_list.get_selected_card_id()
        if card_id:
            self.preview_controller.load_card(card_id)
        # Don't clear if no card selected - might be mid-click

    def _on_deck_list_select(self, deck_list: DeckCardList) -> None:
        if self._updating_lists:
            return

        ids = deck_list.get_selected_ids()
        if ids:
            print_id, card_id = ids
            self.preview_controller.load_card(card_id, print_id)
        # Don't clear if no selection - might be clicking on type header or mid-transition

    def _on_prev_print(self) -> None:
        self.preview_controller.prev_print()

    def _on_next_print(self) -> None:
        self.preview_controller.next_print()


def open_deck_builder(master: tk.Misc) -> DeckBuilderWindow:
    """
    Open the deck builder window.

    Parameters
    ----------
    master : tk.Misc
        Parent Tkinter widget

    Returns
    -------
    window : DeckBuilderWindow
        The deck builder window instance
    """
    return DeckBuilderWindow(master)
