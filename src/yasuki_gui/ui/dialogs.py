import tkinter as tk
from tkinter import filedialog
from collections.abc import Callable

from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_gui import theme
from yasuki_gui.ui.images import ImageProvider
from yasuki_gui.visuals import DeckVisual
from yasuki_gui.constants import CARD_W, CARD_H


class Dialogs:
    def __init__(self, toplevel: tk.Misc, image_provider: ImageProvider):
        self.toplevel = toplevel
        self.images = image_provider

    def deck_inspect(self, cards: list[L5RCard], label: str) -> None:
        win = tk.Toplevel(self.toplevel)
        win.title(f"Inspect - {label}")
        canvas = tk.Canvas(win, width=800, height=260, bg=theme.PANEL)
        hscroll = tk.Scrollbar(win, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=hscroll.set)
        frame = tk.Frame(canvas, bg=theme.PANEL)
        canvas.create_window((0, 0), window=frame, anchor="nw")
        keep: list[object] = []
        pad = 10
        for idx, card in enumerate(cards):
            bowed = card.bowed
            face_up = card.face_up
            photo = (
                self.images.front(card.image_front, bowed, card.inverted)
                if face_up
                else self.images.back(card.side, bowed, card.inverted, card.image_back)
            )
            holder = tk.Frame(frame, bg=theme.PANEL)
            holder.grid(row=0, column=idx, padx=pad, pady=pad)
            if photo is not None:
                lbl = tk.Label(holder, image=photo, bg=theme.PANEL)
                lbl.pack()
                keep.append(photo)
            else:
                w, h = (CARD_H, CARD_W) if card.bowed else (CARD_W, CARD_H)
                c = tk.Canvas(holder, width=w, height=h, bg=theme.CARD_FACE, highlightthickness=0)
                c.pack()
                c.create_text(w // 2, h // 2, text=card.name, fill=theme.INK)

        def _update_scrollregion():
            frame.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))

        _update_scrollregion()
        canvas.pack(fill="both", expand=True)
        hscroll.pack(fill="x")
        # prevent GC on PhotoImage objects
        win._images = keep  # type: ignore[attr-defined]

    def deck_search(
        self,
        cards: list[L5RCard],
        label: str,
        draw_cb: Callable[[int], None],
        n: int | None = None,
    ) -> None:
        win = tk.Toplevel(self.toplevel)
        title = f"Search Top {n} - {label}" if n else f"Search - {label}"
        win.title(title)
        list_frame = tk.Frame(win, bg=theme.PANEL)
        list_frame.pack(fill="both", expand=True)
        keep: list[object] = []
        # Determine slice of deck to show
        shown = cards[-n:] if n else cards[:]
        if not shown:
            return

        def draw_card_at_index(idx_in_deck: int) -> None:
            try:
                draw_cb(idx_in_deck)
            finally:
                try:
                    win.destroy()
                except Exception:
                    pass

        for col, card in enumerate(shown):
            # Map displayed index to actual deck index
            idx_in_deck = (len(cards) - len(shown)) + col if n else col
            bowed = card.bowed
            face_up = card.face_up
            photo = (
                self.images.front(card.image_front, bowed, card.inverted)
                if face_up
                else self.images.back(card.side, bowed, card.inverted, card.image_back)
            )
            cell = tk.Frame(list_frame, bg=theme.PANEL)
            cell.grid(row=0, column=col, padx=6, pady=6)
            if photo is not None:
                lbl = tk.Label(cell, image=photo, bg=theme.PANEL)
                lbl.pack()
                keep.append(photo)
            else:
                w, h = (CARD_H, CARD_W) if card.bowed else (CARD_W, CARD_H)
                c = tk.Canvas(cell, width=w, height=h, bg=theme.CARD_FACE, highlightthickness=0)
                c.pack()
                c.create_text(w // 2, h // 2, text=card.name, fill=theme.INK)
            btn = tk.Button(cell, text="Draw", command=lambda i=idx_in_deck: draw_card_at_index(i))
            btn.pack(pady=4)
        win._images = keep  # type: ignore[attr-defined]

    def card_search(
        self,
        cards: list[L5RCard],
        choosable: set[str],
        label: str,
        on_pick: Callable[[str], None],
    ) -> None:
        """Search a pile the way the web deck dialog does: the whole pile listed by title and
        filterable, with a live preview of the selection. ``cards`` is the pool shown; only cards in
        ``choosable`` can be taken (the others show but stay disabled), and taking one calls
        ``on_pick`` with its id. The window requires a pick — the search is a committed cost."""
        win = tk.Toplevel(self.toplevel)
        win.title(f"Search - {label}")
        win.transient(self.toplevel)
        win.grab_set()
        win.protocol("WM_DELETE_WINDOW", lambda: None)  # a pick is required; no dismiss

        query = tk.StringVar()
        header = tk.Frame(win, bg=theme.PANEL)
        header.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(header, text="Filter:", bg=theme.PANEL, fg=theme.INK).pack(side="left")
        filter_entry = tk.Entry(header, textvariable=query)
        filter_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))

        body = tk.Frame(win, bg=theme.PANEL)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        listbox = tk.Listbox(body, width=32, height=14, activestyle="dotbox")
        scroll = tk.Scrollbar(body, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scroll.set)
        listbox.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        preview = tk.Label(body, bg=theme.PANEL)
        preview.grid(row=0, column=2, padx=(10, 0))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        choose_btn = tk.Button(win, text="Choose")
        choose_btn.pack(pady=(4, 8))

        keep: list[object] = []
        shown: list[L5RCard] = []

        def selected() -> L5RCard | None:
            picked = listbox.curselection()
            return shown[picked[0]] if picked else None

        def refresh_preview(_event=None) -> None:
            card = selected()
            photo = self.images.front(card.image_front, False, card.inverted) if card else None
            keep.clear()
            if photo is not None:
                preview.configure(image=photo, text="")
                keep.append(photo)
            else:
                preview.configure(image="", text=card.name if card else "")
            takeable = card is not None and card.id in choosable
            choose_btn.configure(state="normal" if takeable else "disabled")

        def rebuild(*_args) -> None:
            needle = query.get().strip().lower()
            shown.clear()
            shown.extend(card for card in cards if needle in (card.name or "").lower())
            listbox.delete(0, "end")
            for card in shown:
                mark = "★ " if card.id in choosable else "   "
                listbox.insert("end", f"{mark}{card.name}")
            if shown:
                listbox.selection_set(0)
            refresh_preview()

        def pick() -> None:
            card = selected()
            if card is None or card.id not in choosable:
                return
            win.destroy()
            on_pick(card.id)

        listbox.bind("<<ListboxSelect>>", refresh_preview)
        query.trace_add("write", rebuild)
        choose_btn.configure(command=pick)
        rebuild()
        filter_entry.focus_set()
        win._images = keep  # type: ignore[attr-defined]

    def create_token(self, on_create: Callable[[str, Side], None]) -> None:
        """Prompt for a token name and side, then call ``on_create`` with them."""
        win = tk.Toplevel(self.toplevel)
        win.title("Create Token")
        win.transient(self.toplevel)
        win.grab_set()
        frm = tk.Frame(win, padx=12, pady=12)
        frm.pack(fill="both", expand=True)

        tk.Label(frm, text="Name:").grid(row=0, column=0, sticky="e", padx=(0, 8))
        name_var = tk.StringVar(value="Token")
        name_entry = tk.Entry(frm, textvariable=name_var, width=24)
        name_entry.grid(row=0, column=1, sticky="w")

        tk.Label(frm, text="Side:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=(8, 0))
        side_var = tk.StringVar(value=Side.DYNASTY.value)
        side_menu = tk.OptionMenu(frm, side_var, Side.DYNASTY.value, Side.FATE.value)
        side_menu.grid(row=1, column=1, sticky="w", pady=(8, 0))

        def create_close() -> None:
            try:
                on_create(name_var.get() or "Token", Side(side_var.get()))
            finally:
                win.destroy()

        btns = tk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, pady=(12, 0))
        tk.Button(btns, text="Cancel", command=win.destroy).pack(side="right", padx=(8, 0))
        tk.Button(btns, text="Create", command=create_close).pack(side="right")
        name_entry.focus_set()

    def deck_reveal_top(self, dv: DeckVisual) -> None:
        # Minimal stub for future reveal logic
        win = tk.Toplevel(self.toplevel)
        win.title(f"Reveal Top (TODO) - {dv.label}")
        tk.Label(win, text="TODO: Reveal to opponent", bg=theme.PANEL, fg=theme.INK).pack(
            padx=12, pady=12
        )

    def preferences(
        self,
        current_name: str,
        current_avatar: str | None,
        on_apply: Callable[[str, str | None], None],
    ) -> None:
        win = tk.Toplevel(self.toplevel)
        win.title("Preferences")
        win.transient(self.toplevel)
        win.grab_set()
        frm = tk.Frame(win, padx=12, pady=12)
        frm.pack(fill="both", expand=True)
        # Username
        tk.Label(frm, text="Username:").grid(row=0, column=0, sticky="e", padx=(0, 8))
        name_var = tk.StringVar(value=current_name)
        name_entry = tk.Entry(frm, textvariable=name_var, width=30)
        name_entry.grid(row=0, column=1, sticky="w")
        # Avatar
        tk.Label(frm, text="Avatar Image:").grid(
            row=1, column=0, sticky="e", padx=(0, 8), pady=(8, 0)
        )
        avatar_var = tk.StringVar(value=current_avatar or "")
        avatar_entry = tk.Entry(frm, textvariable=avatar_var, width=30)
        avatar_entry.grid(row=1, column=1, sticky="w", pady=(8, 0))

        def browse() -> None:
            path = filedialog.askopenfilename(
                parent=win,
                title="Choose Avatar Image",
                filetypes=[
                    ("Images", ".png .jpg .jpeg .gif .bmp"),
                    ("All files", "*"),
                ],
            )
            if path:
                avatar_var.set(path)

        tk.Button(frm, text="Browse…", command=browse).grid(
            row=1, column=2, sticky="w", pady=(8, 0), padx=(8, 0)
        )
        # Buttons
        btns = tk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=3, pady=(12, 0))

        def apply_close() -> None:
            try:
                on_apply(name_var.get(), (avatar_var.get() or None))
            finally:
                win.destroy()

        tk.Button(btns, text="Cancel", command=win.destroy).pack(side="right", padx=(8, 0))
        tk.Button(btns, text="OK", command=apply_close).pack(side="right")
        # Focus
        name_entry.focus_set()
