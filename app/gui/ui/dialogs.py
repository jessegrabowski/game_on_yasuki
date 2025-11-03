import tkinter as tk
from tkinter import filedialog
from collections.abc import Callable

from app.gui.ui.images import ImageProvider
from app.gui.visuals import DeckVisual
from app.gui.constants import CARD_W, CARD_H


class Dialogs:
    def __init__(self, toplevel: tk.Misc, image_provider: ImageProvider):
        self.toplevel = toplevel
        self.images = image_provider

    def deck_inspect(self, dv: DeckVisual) -> None:
        win = tk.Toplevel(self.toplevel)
        win.title(f"Inspect - {dv.label}")
        canvas = tk.Canvas(win, width=800, height=260, bg="#1e1e1e")
        hscroll = tk.Scrollbar(win, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=hscroll.set)
        frame = tk.Frame(canvas, bg="#1e1e1e")
        canvas.create_window((0, 0), window=frame, anchor="nw")
        keep: list[object] = []
        pad = 10
        for idx, card in enumerate(dv.deck.cards):
            bowed = card.bowed
            face_up = card.face_up
            photo = (
                self.images.front(card.image_front, bowed, card.inverted)
                if face_up
                else self.images.back(card.side, bowed, card.inverted, card.image_back)
            )
            holder = tk.Frame(frame, bg="#1e1e1e")
            holder.grid(row=0, column=idx, padx=pad, pady=pad)
            if photo is not None:
                lbl = tk.Label(holder, image=photo, bg="#1e1e1e")
                lbl.pack()
                keep.append(photo)
            else:
                w, h = (CARD_H, CARD_W) if card.bowed else (CARD_W, CARD_H)
                c = tk.Canvas(holder, width=w, height=h, bg="#6b6b6b", highlightthickness=0)
                c.pack()
                c.create_text(w // 2, h // 2, text=card.name, fill="#222")

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
        dv: DeckVisual,
        draw_cb: Callable[[int], None],
        n: int | None = None,
    ) -> None:
        win = tk.Toplevel(self.toplevel)
        title = f"Search Top {n} - {dv.label}" if n else f"Search - {dv.label}"
        win.title(title)
        list_frame = tk.Frame(win, bg="#1e1e1e")
        list_frame.pack(fill="both", expand=True)
        keep: list[object] = []
        # Determine slice of deck to show
        cards = dv.deck.cards[-n:] if n else dv.deck.cards[:]
        if not cards:
            return

        def draw_card_at_index(idx_in_deck: int) -> None:
            try:
                draw_cb(idx_in_deck)
            finally:
                try:
                    win.destroy()
                except Exception:
                    pass

        for col, card in enumerate(cards):
            # Map displayed index to actual deck index
            idx_in_deck = (len(dv.deck.cards) - len(cards)) + col if n else col
            bowed = card.bowed
            face_up = card.face_up
            photo = (
                self.images.front(card.image_front, bowed, card.inverted)
                if face_up
                else self.images.back(card.side, bowed, card.inverted, card.image_back)
            )
            cell = tk.Frame(list_frame, bg="#1e1e1e")
            cell.grid(row=0, column=col, padx=6, pady=6)
            if photo is not None:
                lbl = tk.Label(cell, image=photo, bg="#1e1e1e")
                lbl.pack()
                keep.append(photo)
            else:
                w, h = (CARD_H, CARD_W) if card.bowed else (CARD_W, CARD_H)
                c = tk.Canvas(cell, width=w, height=h, bg="#6b6b6b", highlightthickness=0)
                c.pack()
                c.create_text(w // 2, h // 2, text=card.name, fill="#222")
            btn = tk.Button(cell, text="Draw", command=lambda i=idx_in_deck: draw_card_at_index(i))
            btn.pack(pady=4)
        win._images = keep  # type: ignore[attr-defined]

    def deck_reveal_top(self, dv: DeckVisual) -> None:
        # Minimal stub for future reveal logic
        win = tk.Toplevel(self.toplevel)
        win.title(f"Reveal Top (TODO) - {dv.label}")
        tk.Label(win, text="TODO: Reveal to opponent", bg="#1e1e1e", fg="#eaeaea").pack(
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
