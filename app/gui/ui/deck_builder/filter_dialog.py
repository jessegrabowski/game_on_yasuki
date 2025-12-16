import tkinter as tk
from tkinter import messagebox
from dataclasses import dataclass, field
from typing import Any
from app.database import (
    query_all_formats,
    query_all_sets,
    query_sets_by_format,
    query_all_decks,
    query_all_clans,
    query_all_types,
    query_all_rarities,
    query_types_by_deck,
    query_cards_filtered,
    query_stat_ranges,
    query_all_stat_type_mappings,
)


@dataclass
class FilterOptions:
    """
    Extensible filter options for card queries.

    Stores arbitrary property filters as key-value pairs.
    Each filter is a constraint on a specific card property.
    """

    filters: dict[str, Any] = field(default_factory=dict)

    def add_filter(self, property_name: str, value: Any) -> None:
        """Add or update a filter constraint for a card property."""
        self.filters[property_name] = value

    def remove_filter(self, property_name: str) -> None:
        """Remove a filter constraint."""
        self.filters.pop(property_name, None)

    def get_filter(self, property_name: str) -> Any:
        """Get the value for a specific filter, or None if not set."""
        return self.filters.get(property_name)

    def has_filters(self) -> bool:
        """Check if any filters are active."""
        return bool(self.filters)

    def clear(self) -> None:
        """Remove all filters."""
        self.filters.clear()


class FilterDialog:
    """
    Dialog for configuring card list filters.

    Extensible design allows adding new filter types by implementing new UI sections.
    Currently supports format legality filtering.
    """

    def __init__(self, parent: tk.Misc, current_options: FilterOptions | None = None):
        self.parent = parent
        self.result: FilterOptions | None = None
        self.current_options = current_options or FilterOptions()
        self._updating_filters = False  # Flag to batch updates
        self._update_card_count_after_id = None  # For debouncing card count updates

        # Cache stat-to-types mapping for performance (single batch query)
        self._stat_types_cache = query_all_stat_type_mappings()

        # Track which stats are currently active (to detect enable/disable boundaries)
        self._active_stats = set()

        self.win = tk.Toplevel(parent)
        self.win.title("Filter Cards")
        self.win.geometry("1200x750")
        self.win.transient(parent)
        self.win.grab_set()

        self._setup_ui()

        # Center on parent
        self.win.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (self.win.winfo_width() // 2)
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (self.win.winfo_height() // 2)
        self.win.geometry(f"+{x}+{y}")

    def _setup_ui(self) -> None:
        """Create filter UI elements."""
        main_frame = tk.Frame(self.win, padx=16, pady=16)
        main_frame.pack(fill="both", expand=True)

        columns_frame = tk.Frame(main_frame)
        columns_frame.pack(fill="both", expand=True)

        # Left column: Format and Legality
        left_column = tk.Frame(columns_frame)
        left_column.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self._setup_legality_filter(left_column)

        # Second column: Card Properties (Deck, Type, Clan)
        second_column = tk.Frame(columns_frame)
        second_column.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self._setup_card_properties_filter(second_column)

        # Third column: Print Properties (Sets, Rarity)
        third_column = tk.Frame(columns_frame)
        third_column.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self._setup_print_properties_filter(third_column)

        # Fourth column: Statistics (Force, Chi, etc.)
        fourth_column = tk.Frame(columns_frame)
        fourth_column.pack(side="left", fill="both", expand=True)
        self._setup_statistics_filter(fourth_column)

        # Buttons at the bottom
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(16, 0))

        tk.Button(button_frame, text="Clear Filters", command=self._clear_filters).pack(side="left")

        # Card count label in the center
        self.card_count_label = tk.Label(
            button_frame, text="Current filters will return: ... cards", fg="gray"
        )
        self.card_count_label.pack(side="left", expand=True)

        tk.Button(button_frame, text="Cancel", command=self._cancel).pack(side="right", padx=(4, 0))
        tk.Button(button_frame, text="Apply", command=self._apply).pack(side="right")

        self._update_stat_availability()
        self._update_card_count()

    def _setup_legality_filter(self, parent: tk.Frame) -> None:
        """Create format filter UI section."""
        # Format selection section
        format_frame = tk.LabelFrame(parent, text="Format", padx=8, pady=8)
        format_frame.pack(fill="both", expand=True)

        # Create scrollable canvas to hold all three boxes
        canvas_frame = tk.Frame(format_frame)
        canvas_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.format_canvas = canvas
        self.format_scrollable_frame = scrollable_frame

        self.legal_var = tk.BooleanVar(value=True)
        self.not_legal_var = tk.BooleanVar(value=False)

        self._create_arc_box(scrollable_frame)
        self._create_formats_box(scrollable_frame)
        self._create_misc_box(scrollable_frame)

        self._load_formats()

        legality_frame = tk.LabelFrame(parent, text="Legality", padx=8, pady=8)
        legality_frame.pack(fill="x", pady=(8, 0))

        tk.Checkbutton(
            legality_frame, text="Legal", variable=self.legal_var, command=self._update_card_count
        ).pack(anchor="w")
        tk.Checkbutton(
            legality_frame,
            text="Not Legal",
            variable=self.not_legal_var,
            command=self._update_card_count,
        ).pack(anchor="w")

    def _create_arc_box(self, parent: tk.Frame) -> None:
        """Create the Arc formats box."""
        self.arc_frame = tk.LabelFrame(
            parent, text="Arc", padx=4, pady=4, relief=tk.GROOVE, borderwidth=2
        )
        self.arc_frame.pack(fill="x", pady=(0, 8))

        self.arc_listbox = tk.Listbox(
            self.arc_frame, selectmode="single", height=11, width=30, exportselection=False
        )
        self.arc_listbox.pack(fill="x", padx=4)

        # Bind click to handle deselection on re-click
        self.arc_listbox.bind("<Button-1>", self._make_format_click_handler(self.arc_listbox))
        # Bind arrow keys for navigation
        self.arc_listbox.bind("<Up>", lambda e: self._on_format_arrow_key(e, self.arc_listbox))
        self.arc_listbox.bind("<Down>", lambda e: self._on_format_arrow_key(e, self.arc_listbox))

    def _create_formats_box(self, parent: tk.Frame) -> None:
        """Create the standard Formats box."""
        self.formats_frame = tk.LabelFrame(
            parent, text="Formats", padx=4, pady=4, relief=tk.GROOVE, borderwidth=2
        )
        self.formats_frame.pack(fill="x", pady=(0, 8))

        self.formats_listbox = tk.Listbox(
            self.formats_frame, selectmode="single", height=2, width=30, exportselection=False
        )
        self.formats_listbox.pack(fill="x", padx=4)

        # Bind click to handle deselection on re-click
        self.formats_listbox.bind(
            "<Button-1>", self._make_format_click_handler(self.formats_listbox)
        )
        # Bind arrow keys for navigation
        self.formats_listbox.bind(
            "<Up>", lambda e: self._on_format_arrow_key(e, self.formats_listbox)
        )
        self.formats_listbox.bind(
            "<Down>", lambda e: self._on_format_arrow_key(e, self.formats_listbox)
        )

    def _create_misc_box(self, parent: tk.Frame) -> None:
        """Create the Misc formats box."""
        self.misc_frame = tk.LabelFrame(
            parent, text="Misc", padx=4, pady=4, relief=tk.GROOVE, borderwidth=2
        )
        self.misc_frame.pack(fill="x", pady=(0, 8))

        self.misc_listbox = tk.Listbox(
            self.misc_frame, selectmode="single", height=2, width=30, exportselection=False
        )
        self.misc_listbox.pack(fill="x", padx=4)

        # Bind click to handle deselection on re-click
        self.misc_listbox.bind("<Button-1>", self._make_format_click_handler(self.misc_listbox))
        # Bind arrow keys for navigation
        self.misc_listbox.bind("<Up>", lambda e: self._on_format_arrow_key(e, self.misc_listbox))
        self.misc_listbox.bind("<Down>", lambda e: self._on_format_arrow_key(e, self.misc_listbox))

    def _setup_card_properties_filter(self, parent: tk.Frame) -> None:
        """Create card properties filter UI section (Deck, Type, Clan)."""
        # Deck filter
        deck_frame = tk.LabelFrame(parent, text="Deck", padx=8, pady=8)
        deck_frame.pack(fill="x", pady=(0, 8))  # Changed from fill="both", expand=True

        self.deck_listbox = tk.Listbox(
            deck_frame,
            selectmode="extended",
            width=25,
            height=4,  # Small fixed height since there are only ~4 deck types
            exportselection=False,
        )
        self.deck_listbox.pack(fill="x", padx=4)

        # Bind spreadsheet-style selection handlers
        self.deck_listbox.bind("<Button-1>", self._make_deck_click_handler(self.deck_listbox))
        self.deck_listbox.bind(
            "<Control-Button-1>", self._make_deck_ctrl_click_handler(self.deck_listbox)
        )
        self.deck_listbox.bind(
            "<Shift-Button-1>", self._make_deck_shift_click_handler(self.deck_listbox)
        )
        # Bind arrow keys for navigation
        self.deck_listbox.bind("<Up>", lambda e: self._on_deck_arrow_key(e, self.deck_listbox))
        self.deck_listbox.bind("<Down>", lambda e: self._on_deck_arrow_key(e, self.deck_listbox))
        self.deck_listbox.bind(
            "<Shift-Up>", lambda e: self._on_deck_arrow_key(e, self.deck_listbox)
        )
        self.deck_listbox.bind(
            "<Shift-Down>", lambda e: self._on_deck_arrow_key(e, self.deck_listbox)
        )

        # Type filter
        type_frame = tk.LabelFrame(parent, text="Type", padx=8, pady=8)
        type_frame.pack(fill="both", expand=True, pady=(0, 8))

        list_frame = tk.Frame(type_frame)
        list_frame.pack(fill="both", expand=True, padx=4)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self.type_listbox = tk.Listbox(
            list_frame,
            selectmode="extended",
            width=25,
            yscrollcommand=scrollbar.set,
            exportselection=False,
        )
        scrollbar.config(command=self.type_listbox.yview)
        self.type_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind spreadsheet-style selection handlers
        self.type_listbox.bind(
            "<Button-1>", self._make_generic_click_handler(self.type_listbox, "type")
        )
        self.type_listbox.bind(
            "<Control-Button-1>", self._make_generic_ctrl_click_handler(self.type_listbox, "type")
        )
        self.type_listbox.bind(
            "<Shift-Button-1>", self._make_generic_shift_click_handler(self.type_listbox, "type")
        )
        # Bind arrow keys for navigation
        self.type_listbox.bind("<Up>", lambda e: self._on_type_arrow_key(e, self.type_listbox))
        self.type_listbox.bind("<Down>", lambda e: self._on_type_arrow_key(e, self.type_listbox))
        self.type_listbox.bind(
            "<Shift-Up>", lambda e: self._on_type_arrow_key(e, self.type_listbox)
        )
        self.type_listbox.bind(
            "<Shift-Down>", lambda e: self._on_type_arrow_key(e, self.type_listbox)
        )

        # Clan filter
        clan_frame = tk.LabelFrame(parent, text="Clan", padx=8, pady=8)
        clan_frame.pack(fill="both", expand=True)

        list_frame = tk.Frame(clan_frame)
        list_frame.pack(fill="both", expand=True, padx=4)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self.clan_listbox = tk.Listbox(
            list_frame,
            selectmode="extended",
            width=25,
            yscrollcommand=scrollbar.set,
            exportselection=False,
        )
        scrollbar.config(command=self.clan_listbox.yview)
        self.clan_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind spreadsheet-style selection handlers
        self.clan_listbox.bind(
            "<Button-1>", self._make_generic_click_handler(self.clan_listbox, "clan")
        )
        self.clan_listbox.bind(
            "<Control-Button-1>", self._make_generic_ctrl_click_handler(self.clan_listbox, "clan")
        )
        self.clan_listbox.bind(
            "<Shift-Button-1>", self._make_generic_shift_click_handler(self.clan_listbox, "clan")
        )
        # Bind arrow keys for navigation
        self.clan_listbox.bind(
            "<Up>", lambda e: self._on_arrow_key_with_update(e, self.clan_listbox)
        )
        self.clan_listbox.bind(
            "<Down>", lambda e: self._on_arrow_key_with_update(e, self.clan_listbox)
        )
        self.clan_listbox.bind(
            "<Shift-Up>", lambda e: self._on_arrow_key_with_update(e, self.clan_listbox)
        )
        self.clan_listbox.bind(
            "<Shift-Down>", lambda e: self._on_arrow_key_with_update(e, self.clan_listbox)
        )

        self._load_card_properties()

    def _setup_print_properties_filter(self, parent: tk.Frame) -> None:
        """Create print properties filter UI section (Sets, Rarity)."""
        set_frame = tk.LabelFrame(parent, text="Sets", padx=8, pady=8)
        set_frame.pack(fill="both", expand=True, pady=(0, 8))

        list_frame = tk.Frame(set_frame)
        list_frame.pack(fill="both", expand=True, padx=4)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self.set_listbox = tk.Listbox(
            list_frame,
            selectmode="extended",
            width=25,
            yscrollcommand=scrollbar.set,
            exportselection=False,
        )
        scrollbar.config(command=self.set_listbox.yview)
        self.set_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind spreadsheet-style selection handlers
        self.set_listbox.bind(
            "<Button-1>", self._make_generic_click_handler(self.set_listbox, "set")
        )
        self.set_listbox.bind(
            "<Control-Button-1>", self._make_generic_ctrl_click_handler(self.set_listbox, "set")
        )
        self.set_listbox.bind(
            "<Shift-Button-1>", self._make_generic_shift_click_handler(self.set_listbox, "set")
        )
        # Bind arrow keys for navigation
        self.set_listbox.bind("<Up>", lambda e: self._on_arrow_key_with_update(e, self.set_listbox))
        self.set_listbox.bind(
            "<Down>", lambda e: self._on_arrow_key_with_update(e, self.set_listbox)
        )
        self.set_listbox.bind(
            "<Shift-Up>", lambda e: self._on_arrow_key_with_update(e, self.set_listbox)
        )
        self.set_listbox.bind(
            "<Shift-Down>", lambda e: self._on_arrow_key_with_update(e, self.set_listbox)
        )

        # Rarity filter
        rarity_frame = tk.LabelFrame(parent, text="Rarity", padx=8, pady=8)
        rarity_frame.pack(fill="x")  # Changed from fill="both", expand=True

        self.rarity_listbox = tk.Listbox(
            rarity_frame,
            selectmode="extended",
            width=25,
            height=7,  # Increased to 7 to show all rarity options without scrollbar
            exportselection=False,
        )
        self.rarity_listbox.pack(fill="x", padx=4)

        # Bind spreadsheet-style selection handlers
        self.rarity_listbox.bind(
            "<Button-1>", self._make_generic_click_handler(self.rarity_listbox, "rarity")
        )
        self.rarity_listbox.bind(
            "<Control-Button-1>",
            self._make_generic_ctrl_click_handler(self.rarity_listbox, "rarity"),
        )
        self.rarity_listbox.bind(
            "<Shift-Button-1>",
            self._make_generic_shift_click_handler(self.rarity_listbox, "rarity"),
        )
        # Bind arrow keys for navigation
        self.rarity_listbox.bind(
            "<Up>", lambda e: self._on_arrow_key_with_update(e, self.rarity_listbox)
        )
        self.rarity_listbox.bind(
            "<Down>", lambda e: self._on_arrow_key_with_update(e, self.rarity_listbox)
        )
        self.rarity_listbox.bind(
            "<Shift-Up>", lambda e: self._on_arrow_key_with_update(e, self.rarity_listbox)
        )
        self.rarity_listbox.bind(
            "<Shift-Down>", lambda e: self._on_arrow_key_with_update(e, self.rarity_listbox)
        )

        self._load_print_properties()

    def _setup_statistics_filter(self, parent: tk.Frame) -> None:
        """Create statistics filter UI section (Force, Chi, Cost, etc.)."""
        canvas_frame = tk.Frame(parent)
        canvas_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Dictionary to store stat filter widgets
        self.stat_filters = {}

        # Define statistics with their display names and ranges
        # Ranges queried from actual database values
        stats_config = self._get_stats_config()

        for display_name, db_name, min_val, max_val in stats_config:
            self._create_stat_filter(scrollable_frame, display_name, db_name, min_val, max_val)

        # Restore statistics filter values from current_options
        for stat_name, stat_data in self.stat_filters.items():
            stat_filter = self.current_options.get_filter(stat_name)
            if stat_filter:
                min_val, max_val = stat_filter
                if min_val is not None:
                    stat_data["min_var"].set(str(min_val))
                if max_val is not None:
                    stat_data["max_var"].set(str(max_val))

    def _get_stats_config(self) -> list[tuple[str, str, int, int]]:
        """
        Get statistics configuration with min/max ranges from database.

        Queries actual database values to determine ranges for each statistic.

        Returns
        -------
        config : list of tuple
            Each tuple is (display_name, db_name, min_val, max_val)
        """
        ranges = query_stat_ranges()

        return [
            ("Force", "force", *ranges["force"]),
            ("Chi", "chi", *ranges["chi"]),
            ("Honor Req", "honor_requirement", *ranges["honor_requirement"]),
            ("Gold Cost", "gold_cost", *ranges["gold_cost"]),
            ("Personal Honor", "personal_honor", *ranges["personal_honor"]),
            ("Province Str", "province_strength", *ranges["province_strength"]),
            ("Gold Prod", "gold_production", *ranges["gold_production"]),
            ("Starting Honor", "starting_honor", *ranges["starting_honor"]),
            ("Focus", "focus", *ranges["focus"]),
        ]

    def _create_stat_filter(
        self, parent: tk.Frame, display_name: str, db_name: str, min_val: int, max_val: int
    ) -> None:
        """Create a single statistic filter with min/max spinboxes."""
        frame = tk.LabelFrame(parent, text=display_name, padx=6, pady=6)
        frame.pack(fill="x", pady=(0, 8))

        control_frame = tk.Frame(frame)
        control_frame.pack(fill="x")

        min_frame = tk.Frame(control_frame)
        min_frame.pack(side="left", expand=True, fill="x")
        tk.Label(min_frame, text="Min:", width=4, anchor="w").pack(side="left")
        min_var = tk.StringVar(value=str(min_val))
        min_spinbox = tk.Spinbox(
            min_frame,
            from_=min_val,
            to=max_val,
            textvariable=min_var,
            width=5,
            command=self._update_card_count,
        )
        min_spinbox.pack(side="left", padx=2)

        max_frame = tk.Frame(control_frame)
        max_frame.pack(side="left", expand=True, fill="x")
        tk.Label(max_frame, text="Max:", width=4, anchor="w").pack(side="left")
        max_var = tk.StringVar(value=str(max_val))
        max_spinbox = tk.Spinbox(
            max_frame,
            from_=min_val,
            to=max_val,
            textvariable=max_var,
            width=5,
            command=self._update_card_count,
        )
        max_spinbox.pack(side="left", padx=2)

        # Bind variable changes to update card count and available types/decks
        min_var.trace_add("write", lambda *args: self._on_stat_filter_change())
        max_var.trace_add("write", lambda *args: self._on_stat_filter_change())

        # Store references
        self.stat_filters[db_name] = {
            "min_var": min_var,
            "max_var": max_var,
            "min_spinbox": min_spinbox,
            "max_spinbox": max_spinbox,
            "frame": frame,
            "range": (min_val, max_val),
        }

    def _load_card_properties(self) -> None:
        """Load deck, type, and clan values from database."""
        try:
            decks = query_all_decks()
            for deck in decks:
                if deck == "PRE_GAME":
                    self.deck_listbox.insert(tk.END, "Setup Cards")
                else:
                    self.deck_listbox.insert(tk.END, deck.title())

            types = query_all_types()
            for card_type in types:
                self.type_listbox.insert(tk.END, card_type)

            clans = query_all_clans()
            clan_set = set()
            for clan in clans:
                for c in clan.split(","):
                    clan_set.add(c.strip())

            for clan in sorted(clan_set):
                self.clan_listbox.insert(tk.END, clan)

            # Restore deck selections
            deck_filter = self.current_options.get_filter("decks")
            if deck_filter:
                all_decks = self.deck_listbox.get(0, tk.END)
                for i, deck_display in enumerate(all_decks):
                    # Convert display name to internal name for comparison
                    if deck_display == "Setup Cards":
                        internal_name = "PRE_GAME"
                    else:
                        internal_name = deck_display.upper()
                    if internal_name in deck_filter:
                        self.deck_listbox.selection_set(i)

            # Restore type selections
            type_filter = self.current_options.get_filter("types")
            if type_filter:
                all_types = self.type_listbox.get(0, tk.END)
                for i, card_type in enumerate(all_types):
                    if card_type in type_filter:
                        self.type_listbox.selection_set(i)

            # Restore clan selections
            clan_filter = self.current_options.get_filter("clans")
            if clan_filter:
                all_clans = self.clan_listbox.get(0, tk.END)
                for i, clan in enumerate(all_clans):
                    if clan in clan_filter:
                        self.clan_listbox.selection_set(i)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load card properties: {e}", parent=self.win)

    def _load_print_properties(self) -> None:
        """Load sets and rarities from database."""
        try:
            sets = query_all_sets()
            for set_name in sets:
                self.set_listbox.insert(tk.END, set_name)

            rarities = query_all_rarities()
            rarity_set = set()
            for rarity in rarities:
                for r in rarity.split(","):
                    rarity_set.add(r.strip())

            rarity_order = ["Common", "Uncommon", "Rare", "Fixed", "Promo", "Premium", "Other"]
            sorted_rarities = []
            for rarity in rarity_order:
                if rarity in rarity_set:
                    sorted_rarities.append(rarity)

            for rarity in sorted(rarity_set):
                if rarity not in rarity_order:
                    sorted_rarities.append(rarity)

            for rarity in sorted_rarities:
                self.rarity_listbox.insert(tk.END, rarity)

            # Restore rarity selections
            rarity_filter = self.current_options.get_filter("rarities")
            if rarity_filter:
                all_rarities = self.rarity_listbox.get(0, tk.END)
                for i, rarity in enumerate(all_rarities):
                    if rarity in rarity_filter:
                        self.rarity_listbox.selection_set(i)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load print properties: {e}", parent=self.win)

    def _make_format_click_handler(self, listbox: tk.Listbox):
        """Create a click handler for the given format listbox."""

        def handler(event):
            return self._on_format_listbox_click(event, listbox)

        return handler

    def _make_deck_click_handler(self, listbox: tk.Listbox):
        """Create a click handler for deck listbox that updates types."""

        def handler(event):
            result = self._on_generic_listbox_click(event, listbox, "deck")
            self._update_types_for_selected_decks()
            self._update_stat_availability()
            self._update_card_count()
            return result

        return handler

    def _make_deck_ctrl_click_handler(self, listbox: tk.Listbox):
        """Create a Ctrl+click handler for deck listbox that updates types."""

        def handler(event):
            result = self._on_generic_listbox_ctrl_click(event, listbox, "deck")
            self._update_types_for_selected_decks()
            self._update_stat_availability()
            self._update_card_count()
            return result

        return handler

    def _make_deck_shift_click_handler(self, listbox: tk.Listbox):
        """Create a Shift+click handler for deck listbox that updates types."""

        def handler(event):
            result = self._on_generic_listbox_shift_click(event, listbox, "deck")
            self._update_types_for_selected_decks()
            self._update_stat_availability()
            self._update_card_count()
            return result

        return handler

    def _update_types_for_selected_decks(self) -> None:
        """Update type and deck listboxes based on selected decks and active stat filters."""
        current_type_selections = [
            self.type_listbox.get(i) for i in self.type_listbox.curselection()
        ]
        current_deck_selections = [
            self.deck_listbox.get(i) for i in self.deck_listbox.curselection()
        ]

        active_stat_filters = self._get_active_stat_filters()

        selected_decks = []
        for i in self.deck_listbox.curselection():
            deck_display = self.deck_listbox.get(i)
            if deck_display == "Setup Cards":
                selected_decks.append("PRE_GAME")
            else:
                selected_decks.append(deck_display.upper())

        valid_types = None
        valid_decks = None

        if active_stat_filters:
            for stat_name in active_stat_filters:
                stat_types, stat_decks = self._stat_types_cache.get(stat_name, (set(), set()))

                if valid_types is None:
                    valid_types = stat_types.copy()
                    valid_decks = stat_decks.copy()
                else:
                    valid_types &= stat_types
                    valid_decks &= stat_decks

        self.type_listbox.delete(0, tk.END)

        if selected_decks:
            # Load types for selected decks
            types = query_types_by_deck(selected_decks)
        else:
            # No deck selected, show all types
            types = query_all_types()

        # Filter by valid types if we have stat filters active
        if valid_types is not None:
            types = [t for t in types if t in valid_types]

        # Populate type listbox
        for card_type in types:
            self.type_listbox.insert(tk.END, card_type)

        # Try to restore type selections if they still exist
        if current_type_selections:
            all_types = self.type_listbox.get(0, tk.END)
            for i, card_type in enumerate(all_types):
                if card_type in current_type_selections:
                    self.type_listbox.selection_set(i)

        # Update deck listbox
        self.deck_listbox.delete(0, tk.END)

        # Get all decks
        all_decks = query_all_decks()

        # Filter by valid decks if we have stat filters active
        if valid_decks is not None:
            all_decks = [d for d in all_decks if d in valid_decks]

        # Populate deck listbox (with display names)
        for deck in all_decks:
            if deck == "PRE_GAME":
                self.deck_listbox.insert(tk.END, "Setup Cards")
            else:
                self.deck_listbox.insert(tk.END, deck.title())

        # Try to restore deck selections if they still exist
        if current_deck_selections:
            all_decks_display = self.deck_listbox.get(0, tk.END)
            for i, deck_display in enumerate(all_decks_display):
                if deck_display in current_deck_selections:
                    self.deck_listbox.selection_set(i)

    def _get_active_stat_filters(self) -> list[str]:
        """Get list of statistics that have non-default filter values."""
        active_stats = []
        for stat_name, stat_data in self.stat_filters.items():
            min_val_str = stat_data["min_var"].get().strip()
            max_val_str = stat_data["max_var"].get().strip()

            if min_val_str and max_val_str:
                try:
                    min_val = int(min_val_str)
                    max_val = int(max_val_str)
                    range_min, range_max = stat_data["range"]

                    # If values differ from full range, this stat is active
                    if min_val != range_min or max_val != range_max:
                        active_stats.append(stat_name)
                except ValueError:
                    pass  # Skip invalid values

        return active_stats

    def _get_available_stats_for_selection(self) -> set[str]:
        """
        Get which stats are available based on current type/deck selections.

        Returns
        -------
        available : set of str
            Stat names that can be used with the selected types/decks
        """
        # Get selected types
        selected_types = [self.type_listbox.get(i) for i in self.type_listbox.curselection()]

        # Get selected decks (convert from display names)
        selected_decks = []
        for i in self.deck_listbox.curselection():
            deck_display = self.deck_listbox.get(i)
            if deck_display == "Setup Cards":
                selected_decks.append("PRE_GAME")
            else:
                selected_decks.append(deck_display.upper())

        # If nothing selected, all stats are available
        if not selected_types and not selected_decks:
            return set(self._stat_types_cache.keys())

        # Find stats that are valid for the selected types/decks
        available_stats = set()

        for stat_name, (stat_types, stat_decks) in self._stat_types_cache.items():
            # Check if any selected type can have this stat
            if selected_types:
                if any(t in stat_types for t in selected_types):
                    available_stats.add(stat_name)
                    continue

            # Check if any selected deck can have this stat
            if selected_decks:
                if any(d in stat_decks for d in selected_decks):
                    available_stats.add(stat_name)

        return available_stats

    def _update_stat_availability(self) -> None:
        """Update visual state of stat filters based on type/deck selections."""
        available_stats = self._get_available_stats_for_selection()

        for stat_name, stat_data in self.stat_filters.items():
            is_available = stat_name in available_stats

            # Update visual state
            frame = stat_data["frame"]
            min_spinbox = stat_data["min_spinbox"]
            max_spinbox = stat_data["max_spinbox"]

            if is_available:
                # Enable - normal appearance
                frame.config(fg="black")
                min_spinbox.config(state="normal")
                max_spinbox.config(state="normal")
            else:
                # Disable - grayed out appearance
                frame.config(fg="gray")
                min_spinbox.config(state="disabled")
                max_spinbox.config(state="disabled")

    def _make_generic_click_handler(self, listbox: tk.Listbox, filter_name: str):
        """Create a click handler for the given listbox."""

        def handler(event):
            result = self._on_generic_listbox_click(event, listbox, filter_name)
            if filter_name == "type":
                self._update_stat_availability()
            self._update_card_count()
            return result

        return handler

    def _make_generic_ctrl_click_handler(self, listbox: tk.Listbox, filter_name: str):
        """Create a Ctrl+click handler for the given listbox."""

        def handler(event):
            result = self._on_generic_listbox_ctrl_click(event, listbox, filter_name)
            if filter_name == "type":
                self._update_stat_availability()
            self._update_card_count()
            return result

        return handler

    def _make_generic_shift_click_handler(self, listbox: tk.Listbox, filter_name: str):
        """Create a Shift+click handler for the given listbox."""

        def handler(event):
            result = self._on_generic_listbox_shift_click(event, listbox, filter_name)
            if filter_name == "type":
                self._update_stat_availability()
            self._update_card_count()
            return result

        return handler

    def _on_arrow_key(self, event, listbox: tk.Listbox) -> str:
        """Handle arrow key navigation in listboxes."""
        current_selection = listbox.curselection()
        selectmode = listbox.cget("selectmode")

        if not current_selection:
            # No selection, select first item
            if listbox.size() > 0:
                listbox.selection_set(0)
                listbox.activate(0)
                listbox.see(0)
            return "break"

        # Get the active index (where keyboard focus is)
        active_index = listbox.index("active")
        if active_index < 0:
            active_index = current_selection[0]

        if event.keysym == "Up":
            new_index = max(0, active_index - 1)
        elif event.keysym == "Down":
            new_index = min(listbox.size() - 1, active_index + 1)
        else:
            return "break"

        # Check if Shift key is held
        shift_held = getattr(event, "state", 0) & 0x0001  # Shift modifier bit

        if selectmode == "extended" and shift_held:
            # Shift+arrow: expand selection in multi-select listboxes
            listbox.selection_set(new_index)
            listbox.activate(new_index)
            listbox.see(new_index)
        else:
            # Plain arrow: move selection (clear previous)
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(new_index)
            listbox.activate(new_index)
            listbox.see(new_index)

        return "break"

    def _on_arrow_key_with_update(self, event, listbox: tk.Listbox) -> str:
        """Handle arrow key navigation and update card count."""
        result = self._on_arrow_key(event, listbox)
        self._update_card_count()
        return result

    def _on_format_arrow_key(self, event, listbox: tk.Listbox) -> str:
        """Handle arrow key navigation in format listboxes with set list update."""
        # First handle the arrow key navigation
        result = self._on_arrow_key(event, listbox)

        # Then clear selections in other format listboxes and update set list
        for lb in self.all_listboxes:
            if lb != listbox:
                lb.selection_clear(0, tk.END)

        # Update set list based on new selection
        self._update_sets_for_selected_format()

        # Update card count
        self._update_card_count()

        return result

    def _on_deck_arrow_key(self, event, listbox: tk.Listbox) -> str:
        """Handle arrow key navigation in deck listbox with type list update."""
        # First handle the arrow key navigation
        result = self._on_arrow_key(event, listbox)

        # Then update type list based on new deck selection
        self._update_types_for_selected_decks()

        # Update card count
        self._update_card_count()

        return result

    def _on_type_arrow_key(self, event, listbox: tk.Listbox) -> str:
        """Handle arrow key navigation in type listbox with stat availability update."""
        # First handle the arrow key navigation
        result = self._on_arrow_key(event, listbox)

        # Update stat availability based on new type selection
        self._update_stat_availability()

        # Update card count
        self._update_card_count()

        return result

    def _on_generic_listbox_click(self, event, listbox: tk.Listbox, filter_name: str) -> str:
        """Handle plain click on generic listbox - select only the clicked item."""
        # Give focus to the listbox so keyboard events work
        listbox.focus_set()

        clicked_index = listbox.nearest(event.y)

        # Clear all selections and select only the clicked item
        listbox.selection_clear(0, tk.END)
        listbox.selection_set(clicked_index)
        listbox.activate(clicked_index)

        # Remember this index for shift-click
        setattr(self, f"last_{filter_name}_click_index", clicked_index)

        return "break"

    def _on_generic_listbox_ctrl_click(self, event, listbox: tk.Listbox, filter_name: str) -> str:
        """Handle Ctrl+click on generic listbox - toggle selection of clicked item."""
        clicked_index = listbox.nearest(event.y)

        # Toggle selection
        if clicked_index in listbox.curselection():
            listbox.selection_clear(clicked_index)
        else:
            listbox.selection_set(clicked_index)

        listbox.activate(clicked_index)

        # Remember this index for shift-click
        setattr(self, f"last_{filter_name}_click_index", clicked_index)

        return "break"

    def _on_generic_listbox_shift_click(self, event, listbox: tk.Listbox, filter_name: str) -> str:
        """Handle Shift+click on generic listbox - select range from last click to this click."""
        clicked_index = listbox.nearest(event.y)

        last_index = getattr(self, f"last_{filter_name}_click_index", None)
        if last_index is not None:
            # Select range from last click to current click
            start = min(last_index, clicked_index)
            end = max(last_index, clicked_index)

            # Clear existing selection and select the range
            listbox.selection_clear(0, tk.END)
            for i in range(start, end + 1):
                listbox.selection_set(i)

            listbox.activate(clicked_index)
        else:
            # No previous click, just select this item
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(clicked_index)
            listbox.activate(clicked_index)
            setattr(self, f"last_{filter_name}_click_index", clicked_index)

        return "break"

    def _load_formats(self) -> None:
        """Load format names from database and populate category boxes."""
        try:
            formats = query_all_formats()

            # Categorize and sort formats
            arc_formats = self._get_arc_formats(formats)
            format_formats = self._get_format_formats(formats)
            misc_formats = self._get_misc_formats(formats)

            # Track all listboxes (only three now)
            self.all_listboxes = [self.arc_listbox, self.formats_listbox, self.misc_listbox]

            # Populate Arc listbox
            for fmt in arc_formats:
                self.arc_listbox.insert(tk.END, fmt)

            # Populate Formats listbox
            for fmt in format_formats:
                self.formats_listbox.insert(tk.END, fmt)

            # Populate Misc listbox
            for fmt in misc_formats:
                self.misc_listbox.insert(tk.END, fmt)

            # Restore current selection if set
            legality_filter = self.current_options.get_filter("legality")
            if legality_filter:
                format_name, statuses = legality_filter

                # Find which listbox contains this format
                # Check arc listbox
                arc_items = self.arc_listbox.get(0, tk.END)
                if format_name in arc_items:
                    idx = arc_items.index(format_name)
                    self.arc_listbox.selection_set(idx)
                else:
                    # Check formats listbox
                    format_items = self.formats_listbox.get(0, tk.END)
                    if format_name in format_items:
                        idx = format_items.index(format_name)
                        self.formats_listbox.selection_set(idx)
                    else:
                        # Check misc listbox
                        misc_items = self.misc_listbox.get(0, tk.END)
                        if format_name in misc_items:
                            idx = misc_items.index(format_name)
                            self.misc_listbox.selection_set(idx)

                # Restore checkbox states
                self.legal_var.set("legal" in statuses)
                self.not_legal_var.set("not_legal" in statuses)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load formats: {e}", parent=self.win)

    def _on_format_listbox_click(self, event, listbox: tk.Listbox) -> str:
        """
        Handle click on format listbox with deselection support.

        If clicking on already selected item, deselect it.
        Otherwise, select the clicked item and clear others.
        """
        # Give focus to the listbox so keyboard events work
        listbox.focus_set()

        # Get the index under the click
        clicked_index = listbox.nearest(event.y)

        # Check if this index is already selected BEFORE any selection changes
        was_selected = clicked_index in listbox.curselection()

        # Handle selection immediately (not with after_idle)
        if was_selected:
            # Item was already selected, so deselect it
            listbox.selection_clear(0, tk.END)
            # Update set list to show all sets (no format filter)
            self._update_sets_for_selected_format()
        else:
            # Clear selection in all other format listboxes
            for lb in self.all_listboxes:
                if lb != listbox:
                    lb.selection_clear(0, tk.END)

            # Select the clicked item
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(clicked_index)
            listbox.activate(clicked_index)

            # Update set list based on new selection
            self._update_sets_for_selected_format()

        # Update card count
        self._update_card_count()

        return "break"  # Prevent default Tkinter selection behavior

    def _load_sets(self) -> None:
        """Load sets from database, optionally filtered by selected format."""
        try:
            # Check if a format is selected
            format_name = self._get_selected_format()

            if format_name:
                # Get sets for the selected format with selected statuses
                statuses = self._get_selected_statuses()
                sets = query_sets_by_format(format_name, statuses if statuses else None)
            else:
                # No format selected, show all sets
                sets = query_all_sets()

            # Clear and repopulate listbox
            self.set_listbox.delete(0, tk.END)
            for set_name in sets:
                self.set_listbox.insert(tk.END, set_name)

            # Restore set selections if they exist
            set_filter = self.current_options.get_filter("sets")
            if set_filter:
                all_sets = self.set_listbox.get(0, tk.END)
                for i, set_name in enumerate(all_sets):
                    if set_name in set_filter:
                        self.set_listbox.selection_set(i)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load sets: {e}", parent=self.win)

    def _update_sets_for_selected_format(self) -> None:
        """Update the set listbox based on currently selected format."""
        # Store currently selected sets
        current_selections = [self.set_listbox.get(i) for i in self.set_listbox.curselection()]

        # Reload sets
        self._load_sets()

        # Try to restore selections if those sets still exist
        if current_selections:
            all_sets = self.set_listbox.get(0, tk.END)
            for i, set_name in enumerate(all_sets):
                if set_name in current_selections:
                    self.set_listbox.selection_set(i)

    def _get_selected_format(self) -> str | None:
        """Get the currently selected format name, or None if no format selected."""
        if self.arc_listbox.curselection():
            idx = self.arc_listbox.curselection()[0]
            return self.arc_listbox.get(idx)
        elif self.formats_listbox.curselection():
            idx = self.formats_listbox.curselection()[0]
            return self.formats_listbox.get(idx)
        elif self.misc_listbox.curselection():
            idx = self.misc_listbox.curselection()[0]
            return self.misc_listbox.get(idx)
        return None

    def _get_arc_formats(self, all_formats: list[str]) -> list[str]:
        """Get arc formats sorted by release date."""
        # Define arc order by release date
        arc_order = [
            "Clan Wars (Imperial)",
            "Hidden Emperor (Jade)",
            "Four Winds (Gold)",
            "Rain of Blood (Diamond)",
            "Age of Enlightenment (Lotus)",
            "Race for the Throne (Samurai)",
            "Destroyer War (Celestial)",
            "Age of Conquest (Emperor)",
            "A Brother's Destiny (Twenty Festivals)",
            "War of the Seals (Onyx Edition)",
            "Shattered Empire",
        ]

        # Return only formats that exist in database, in the specified order
        return [fmt for fmt in arc_order if fmt in all_formats]

    def _get_format_formats(self, all_formats: list[str]) -> list[str]:
        """Get standard formats."""
        format_order = ["Modern", "Legacy"]
        return [fmt for fmt in format_order if fmt in all_formats]

    def _get_misc_formats(self, all_formats: list[str]) -> list[str]:
        """Get miscellaneous formats."""
        misc_order = ["Not Legal (Proxy)", "Unreleased"]
        return [fmt for fmt in misc_order if fmt in all_formats]

    def _get_selected_statuses(self) -> list[str]:
        """Get list of selected legality statuses."""
        statuses = []
        if self.legal_var.get():
            statuses.append("legal")
        if self.not_legal_var.get():
            statuses.append("not_legal")
        return statuses

    def _apply(self) -> None:
        """Apply filter settings and close dialog."""
        new_options = FilterOptions()

        # Get selected format from any listbox
        format_name = None

        # Check each listbox for selection
        if self.arc_listbox.curselection():
            idx = self.arc_listbox.curselection()[0]
            format_name = self.arc_listbox.get(idx)
        elif self.formats_listbox.curselection():
            idx = self.formats_listbox.curselection()[0]
            format_name = self.formats_listbox.get(idx)
        elif self.misc_listbox.curselection():
            idx = self.misc_listbox.curselection()[0]
            format_name = self.misc_listbox.get(idx)

        # Get selected legality statuses
        statuses = self._get_selected_statuses()

        # Special handling for "Not Legal (Proxy)" format
        # This format specifically contains not_legal cards, so we should always include that status
        if format_name == "Not Legal (Proxy)" and "not_legal" not in statuses:
            statuses.append("not_legal")

        # Check if user wants non-default legality filtering
        # Default is: Legal=True, Not Legal=False
        is_default_legality = self.legal_var.get() and not self.not_legal_var.get()

        # Apply legality filter if:
        # 1. A format is selected, OR
        # 2. Legality is non-default (user wants specific legality filtering)
        if format_name or not is_default_legality:
            if not statuses:
                messagebox.showwarning(
                    "No Status Selected",
                    "Please select at least one legality status (Legal, Not Legal).",
                    parent=self.win,
                )
                return
            new_options.add_filter("legality", (format_name, statuses))

        # Collect set filter selections (multi-select)
        selected_sets = [self.set_listbox.get(i) for i in self.set_listbox.curselection()]
        if selected_sets:
            new_options.add_filter("sets", selected_sets)

        # Collect deck filter selections (multi-select)
        selected_decks = [self.deck_listbox.get(i) for i in self.deck_listbox.curselection()]
        if selected_decks:
            # Convert back from display names to database values
            deck_values = []
            for deck in selected_decks:
                if deck == "Setup Cards":
                    deck_values.append("PRE_GAME")
                else:
                    deck_values.append(deck.upper())
            new_options.add_filter("decks", deck_values)

        # Collect type filter selections (multi-select)
        selected_types = [self.type_listbox.get(i) for i in self.type_listbox.curselection()]
        if selected_types:
            new_options.add_filter("types", selected_types)

        # Collect clan filter selections (multi-select)
        selected_clans = [self.clan_listbox.get(i) for i in self.clan_listbox.curselection()]
        if selected_clans:
            new_options.add_filter("clans", selected_clans)

        # Collect rarity filter selections (multi-select)
        selected_rarities = [self.rarity_listbox.get(i) for i in self.rarity_listbox.curselection()]
        if selected_rarities:
            new_options.add_filter("rarities", selected_rarities)

        # Collect statistics filters
        for stat_name, stat_data in self.stat_filters.items():
            min_val_str = stat_data["min_var"].get().strip()
            max_val_str = stat_data["max_var"].get().strip()

            # Only add filter if at least one value is specified
            if min_val_str or max_val_str:
                try:
                    min_val = int(min_val_str) if min_val_str else None
                    max_val = int(max_val_str) if max_val_str else None

                    # Get the full range for this stat
                    range_min, range_max = stat_data["range"]

                    # Apply filter unless both values equal the full range
                    # (if user changes either min or max, the filter should apply)
                    if min_val != range_min or max_val != range_max:
                        new_options.add_filter(stat_name, (min_val, max_val))
                except ValueError:
                    messagebox.showwarning(
                        "Invalid Value",
                        f"Invalid value for {stat_name}. Please enter valid integers.",
                        parent=self.win,
                    )
                    return

        self.result = new_options
        self.win.destroy()

    def _on_stat_filter_change(self) -> None:
        """Handle changes to statistic filters - only triggers on enable/disable boundaries."""
        # Skip updates during bulk operations
        if self._updating_filters:
            return

        # Get currently active stats
        current_active_stats = set(self._get_active_stat_filters())

        # Check if the set of active stats has changed (boundary crossing)
        if current_active_stats != self._active_stats:
            # Stat was enabled or disabled - update UI
            self._active_stats = current_active_stats

            # Update available types and decks based on active stat filters
            self._update_types_for_selected_decks()

            # Update card count
            self._update_card_count()
        else:
            # Just value change within already-active filter - only update count
            self._update_card_count()

    def _update_card_count(self) -> None:
        """Update the card count label based on current filter selections."""
        # Skip updates during bulk operations to avoid performance issues
        if self._updating_filters:
            return

        if self._update_card_count_after_id is not None:
            self.win.after_cancel(self._update_card_count_after_id)
            self._update_card_count_after_id = None

        # Schedule update after a short delay (debouncing)
        self._update_card_count_after_id = self.win.after(100, self._do_update_card_count)

    def _do_update_card_count(self) -> None:
        """Actually perform the card count update (called after debounce delay)."""
        self._update_card_count_after_id = None

        try:
            # Build filter options from current UI state
            filter_options = {}

            # Get format and legality
            format_name = self._get_selected_format()
            statuses = self._get_selected_statuses()

            # Special handling for "Not Legal (Proxy)" format
            if format_name == "Not Legal (Proxy)" and "not_legal" not in statuses:
                statuses.append("not_legal")

            # Only add legality filter if format is selected or legality is non-default
            is_default_legality = self.legal_var.get() and not self.not_legal_var.get()
            if format_name or not is_default_legality:
                if statuses:
                    filter_options["legality"] = (format_name, statuses)

            # Get set selections
            selected_sets = [self.set_listbox.get(i) for i in self.set_listbox.curselection()]
            if selected_sets:
                filter_options["sets"] = selected_sets

            # Get deck selections
            selected_decks = [self.deck_listbox.get(i) for i in self.deck_listbox.curselection()]
            if selected_decks:
                deck_values = []
                for deck in selected_decks:
                    if deck == "Setup Cards":
                        deck_values.append("PRE_GAME")
                    else:
                        deck_values.append(deck.upper())
                filter_options["decks"] = deck_values

            # Get type selections
            selected_types = [self.type_listbox.get(i) for i in self.type_listbox.curselection()]
            if selected_types:
                filter_options["types"] = selected_types

            # Get clan selections
            selected_clans = [self.clan_listbox.get(i) for i in self.clan_listbox.curselection()]
            if selected_clans:
                filter_options["clans"] = selected_clans

            # Get rarity selections
            selected_rarities = [
                self.rarity_listbox.get(i) for i in self.rarity_listbox.curselection()
            ]
            if selected_rarities:
                filter_options["rarities"] = selected_rarities

            # Get statistics filters
            for stat_name, stat_data in self.stat_filters.items():
                min_val_str = stat_data["min_var"].get().strip()
                max_val_str = stat_data["max_var"].get().strip()

                # Only add filter if at least one value is specified
                if min_val_str or max_val_str:
                    try:
                        min_val = int(min_val_str) if min_val_str else None
                        max_val = int(max_val_str) if max_val_str else None

                        # Get the full range for this stat
                        range_min, range_max = stat_data["range"]

                        # Only apply filter if values differ from full range
                        if min_val != range_min or max_val != range_max:
                            filter_options[stat_name] = (min_val, max_val)
                    except ValueError:
                        # Skip invalid values
                        pass

            # Query database with current filters
            cards = query_cards_filtered(filter_options=filter_options)
            count = len(cards)

            # Update label
            self.card_count_label.config(text=f"Current filters will return: {count} cards")

        except Exception:
            # On error, show a generic message
            self.card_count_label.config(text="Current filters will return: ??? cards")

    def _clear_filters(self) -> None:
        """Clear all filter selections without closing the dialog."""
        # Set flag to batch updates and prevent multiple card count queries
        self._updating_filters = True

        try:
            # Clear all listbox selections
            for listbox in self.all_listboxes:
                listbox.selection_clear(0, tk.END)

            # Clear card property selections
            self.deck_listbox.selection_clear(0, tk.END)
            self.type_listbox.selection_clear(0, tk.END)
            self.clan_listbox.selection_clear(0, tk.END)

            # Clear print property selections
            self.set_listbox.selection_clear(0, tk.END)
            self.rarity_listbox.selection_clear(0, tk.END)

            # Clear statistics filters - reset to default ranges
            for stat_data in self.stat_filters.values():
                range_min, range_max = stat_data["range"]
                stat_data["min_var"].set(str(range_min))
                stat_data["max_var"].set(str(range_max))

            # Reset checkboxes to default
            self.legal_var.set(True)
            self.not_legal_var.set(False)

            # Reload sets to show all sets (no format filter)
            self._load_sets()

            # Update type list to show all types (no deck filter)
            self._update_types_for_selected_decks()

            # Reset stat availability (remove grayed-out state)
            self._update_stat_availability()
        finally:
            # Re-enable updates and do a single card count update
            self._updating_filters = False
            self._update_card_count()

    def _cancel(self) -> None:
        """Cancel and close dialog without changes."""
        self.result = None
        self.win.destroy()

    def show(self) -> FilterOptions | None:
        """
        Show dialog and wait for result.

        Returns
        -------
        options : FilterOptions or None
            Selected filter options, or None if cancelled
        """
        self.win.wait_window()
        return self.result
