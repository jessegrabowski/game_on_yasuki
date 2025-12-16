import tkinter as tk
from collections.abc import Callable


class ScrollableListBox:
    """Base class for listboxes with scrollbars."""

    def __init__(self, master: tk.Widget, selectmode: str = "browse"):
        self.frame = tk.Frame(master)
        self.listbox = tk.Listbox(self.frame, selectmode=selectmode)
        scrollbar = tk.Scrollbar(self.frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")

    def pack(self, **kwargs) -> None:
        self.frame.pack(**kwargs)

    def grid(self, **kwargs) -> None:
        self.frame.grid(**kwargs)

    def clear(self) -> None:
        self.listbox.delete(0, tk.END)

    def get_selection(self) -> tuple[int, ...]:
        return self.listbox.curselection()

    def get_item(self, index: int) -> str:
        return self.listbox.get(index)

    def bind(self, sequence: str, func: Callable) -> None:
        self.listbox.bind(sequence, func)

    def insert(self, index: int | str, item: str) -> None:
        self.listbox.insert(index, item)

    def refresh(self, *args, **kwargs) -> None:
        """Refresh the listbox contents."""
        pass


class CardStatsPanel:
    """Panel displaying card statistics in a compact two-row format."""

    def __init__(self, master: tk.Widget):
        self.frame = tk.LabelFrame(master, text="Card Stats", padx=6, pady=4)

        # Row 1: String data (Name, Type, Clan)
        self.row1_frame = tk.Frame(self.frame)
        self.row1_frame.pack(fill="x", pady=2)

        self.name_label = tk.Label(self.row1_frame, text="—", anchor="w", font=("TkDefaultFont", 9))
        self.name_label.pack(side="left", padx=(0, 8))

        self.type_label = tk.Label(self.row1_frame, text="—", anchor="w", font=("TkDefaultFont", 9))
        self.type_label.pack(side="left", padx=(0, 8))

        self.clan_label = tk.Label(self.row1_frame, text="—", anchor="w", font=("TkDefaultFont", 9))
        self.clan_label.pack(side="left")

        self.row2_frame = tk.Frame(self.frame)
        self.row2_frame.pack(fill="x", pady=2)

        self.stats = {}
        stat_abbrevs = [
            ("F", "force"),
            ("C", "chi"),
            ("PH", "personal_honor"),
            ("HR", "honor_requirement"),
            ("Foc", "focus"),
            ("GC", "gold_cost"),
            ("GP", "gold_production"),
            ("PS", "province_strength"),
            ("SH", "starting_honor"),
        ]

        for abbrev, field in stat_abbrevs:
            stat_frame = tk.Frame(self.row2_frame)
            stat_frame.pack(side="left", padx=(0, 8))

            label = tk.Label(stat_frame, text=f"{abbrev}:", font=("TkDefaultFont", 9, "bold"))
            label.pack(side="left")

            value_label = tk.Label(stat_frame, text="—", font=("TkDefaultFont", 9))
            value_label.pack(side="left", padx=(2, 0))

            self.stats[field] = (stat_frame, value_label)

    def pack(self, **kwargs) -> None:
        self.frame.pack(**kwargs)

    def update_stats(self, card: dict) -> None:
        """
        Update displayed statistics from card data.

        Parameters
        ----------
        card : dict
            Card record with stats fields
        """
        # Row 1: String data
        name = card.get("name", "—")
        card_type = card.get("type", "—")
        clan = card.get("clan", "—")

        self.name_label.configure(text=name)
        self.type_label.configure(text=card_type)
        self.clan_label.configure(text=clan if clan else "—")

        # Row 2: Numeric data - show/hide based on what's available
        for field, (frame, value_label) in self.stats.items():
            value = card.get(field)
            if value is not None:
                value_label.configure(text=str(value))
                frame.pack(side="left", padx=(0, 8))
            else:
                frame.pack_forget()

    def clear(self) -> None:
        """Clear all stats."""
        self.name_label.configure(text="—")
        self.type_label.configure(text="—")
        self.clan_label.configure(text="—")

        for field, (frame, value_label) in self.stats.items():
            value_label.configure(text="—")
            frame.pack_forget()


class PrintSelector:
    """Print selection controls with navigation buttons."""

    def __init__(self, master: tk.Widget, on_prev: Callable[[], None], on_next: Callable[[], None]):
        self.frame = tk.Frame(master)
        tk.Label(self.frame, text="Print:").pack(side="left")

        self.prev_btn = tk.Button(self.frame, text="◀", command=on_prev, width=3)
        self.prev_btn.pack(side="left", padx=(4, 2))

        self.info_lbl = tk.Label(self.frame, text="", anchor="center", width=30)
        self.info_lbl.pack(side="left", padx=2)

        self.next_btn = tk.Button(self.frame, text="▶", command=on_next, width=3)
        self.next_btn.pack(side="left", padx=(2, 0))

        self._disable_buttons()

    def pack(self, **kwargs) -> None:
        self.frame.pack(**kwargs)

    def update(self, set_name: str, current_index: int, total_prints: int) -> None:
        """
        Update print selector display.

        Parameters
        ----------
        set_name : str
            Name of the card set
        current_index : int
            Zero-based index of current print
        total_prints : int
            Total number of prints available
        """
        if total_prints > 1:
            self.info_lbl.configure(text=f"{set_name} ({current_index + 1}/{total_prints})")
            self._enable_buttons()
        else:
            self.info_lbl.configure(text=f"{set_name}")
            self._disable_buttons()

    def clear(self) -> None:
        self.info_lbl.configure(text="")
        self._disable_buttons()

    def _enable_buttons(self) -> None:
        self.prev_btn.configure(state="normal")
        self.next_btn.configure(state="normal")

    def _disable_buttons(self) -> None:
        self.prev_btn.configure(state="disabled")
        self.next_btn.configure(state="disabled")
