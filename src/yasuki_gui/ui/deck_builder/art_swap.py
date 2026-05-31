import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

from yasuki_core.card_art import classify
from yasuki_core.paths import resolve_set_image_path
from yasuki_gui.ui.deck_builder.components import PrintSelector
from yasuki_gui.ui.deck_builder.custom_art import composite_art

DIALOG_PREVIEW_W = 240


class BorrowArtDialog:
    """Pick a donor card + printing; auto-classifies both sides and previews the composite."""

    def __init__(self, parent: tk.Misc, repository, recipient_path: Path, recipient_key):
        self.repository = repository
        self.recipient_path = recipient_path
        self.recipient_key = recipient_key
        self.result: dict | None = None

        self._index = [
            ((c.get("extended_title") or c.get("name", "")).lower(), c)
            for c in repository.all_cards
        ]
        self._matches: list[dict] = []
        self._donor_card: dict | None = None
        self._donor_prints: list[dict] = []
        self._donor_index = 0
        self._donor_key: tuple[str, str] | None = None
        self._composite: Image.Image | None = None

        self.win = tk.Toplevel(parent)
        self.win.title("Borrow Art")
        self.win.geometry("640x520")
        self.win.transient(parent)
        self.win.grab_set()

        self.search_var = tk.StringVar()
        tk.Label(self.win, text="Borrow art from which card?").pack(anchor="w", padx=8, pady=(8, 2))
        entry = tk.Entry(self.win, textvariable=self.search_var)
        entry.pack(fill="x", padx=8)
        entry.focus_set()
        self.search_var.trace_add("write", lambda *_: self._search())

        body = tk.Frame(self.win)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        self.listbox = tk.Listbox(body, width=34, activestyle="dotbox")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _: self._select_donor())

        right = tk.Frame(body)
        right.pack(side="left", fill="y", padx=(8, 0))
        self.preview_label = tk.Label(right, width=DIALOG_PREVIEW_W, anchor="center")
        self.preview_label.pack()
        self.print_selector = PrintSelector(right, self._prev_print, self._next_print)
        self.print_selector.pack(pady=(4, 0))
        self.info_label = tk.Label(right, text="", justify="left", anchor="w", fg="#aaa")
        self.info_label.pack(anchor="w", pady=(4, 0))

        buttons = tk.Frame(self.win)
        buttons.pack(fill="x", padx=8, pady=8)
        tk.Button(buttons, text="Use Art", command=self._use).pack(side="right")
        tk.Button(buttons, text="Cancel", command=self.win.destroy).pack(side="right", padx=4)

        self.win.geometry(f"+{parent.winfo_rootx() + 50}+{parent.winfo_rooty() + 50}")
        self._show_all()

    def _show_all(self) -> None:
        """Populate the list with the full catalog so the dialog isn't empty before typing."""
        self._matches = [card for _, card in self._index]
        for card in self._matches:
            self.listbox.insert(tk.END, card.get("extended_title") or card.get("name", "?"))

    def _search(self) -> None:
        query = self.search_var.get().strip().lower()
        self.listbox.delete(0, tk.END)
        if not query:
            self._show_all()
            return
        self._matches = []
        for label, card in self._index:
            if query in label:
                self._matches.append(card)
                self.listbox.insert(tk.END, card.get("extended_title") or card.get("name", "?"))

    def _select_donor(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        self._donor_card = self._matches[selection[0]]
        self._donor_prints = [
            p
            for p in self.repository.get_prints(self._donor_card["card_id"])
            if p.get("image_path") and (resolve_set_image_path(p["image_path"]) or Path()).exists()
        ]
        self._donor_index = 0
        self._refresh_preview()

    def _prev_print(self) -> None:
        if self._donor_prints:
            self._donor_index = (self._donor_index - 1) % len(self._donor_prints)
            self._refresh_preview()

    def _next_print(self) -> None:
        if self._donor_prints:
            self._donor_index = (self._donor_index + 1) % len(self._donor_prints)
            self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not self._donor_prints:
            self.preview_label.configure(image="", text="(no art on this card)")
            self.preview_label.image = None  # type: ignore[attr-defined]
            self.print_selector.update("", 0, 0)
            self._composite = None
            return
        donor = self._donor_prints[self._donor_index]
        self._donor_key = classify(self._donor_card, donor.get("set_name", ""))
        self._composite = composite_art(
            self.recipient_path,
            resolve_set_image_path(donor["image_path"]),
            self.recipient_key,
            self._donor_key,
        )
        height = round(DIALOG_PREVIEW_W * self._composite.height / self._composite.width)
        photo = ImageTk.PhotoImage(
            self._composite.resize((DIALOG_PREVIEW_W, height), Image.LANCZOS), master=self.win
        )
        self.preview_label.configure(image=photo, text="")
        self.preview_label.image = photo  # type: ignore[attr-defined]
        self.print_selector.update(
            donor.get("set_name", "?"), self._donor_index, len(self._donor_prints)
        )
        rk, dk = self.recipient_key, self._donor_key
        self.info_label.configure(text=f"land {rk[0]}/{rk[1]}\ntake {dk[0]}/{dk[1]}")

    def _use(self) -> None:
        if not self._donor_prints or self._composite is None:
            return
        donor = self._donor_prints[self._donor_index]
        self.result = {
            "donor_card_id": self._donor_card["card_id"],
            "donor_print_id": donor["print_id"],
            "donor_key": self._donor_key,
        }
        self.win.destroy()

    def show(self) -> dict | None:
        self.win.wait_window()
        return self.result
