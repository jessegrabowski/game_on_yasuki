from collections.abc import Callable
from typing import Literal

import tkinter as tk

from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.game_pieces.deck import Deck
from app.gui.constants import CARD_W, CARD_H, DRAW_OFFSET
from app.gui.config import Hotkeys, DEFAULT_HOTKEYS
from app.engine.zones import Zone, HandZone, FateDiscardZone, DynastyDiscardZone, ProvinceZone
from app.gui.images import load_image, load_back_image
from app.gui.visuals import MarqueeBoxVisual, DeckVisual, ZoneVisual, CardSpriteVisual


class GameField(tk.Canvas):
    def __init__(self, master: tk.Misc, width: int = 800, height: int = 600):
        super().__init__(master, width=width, height=height, bg="#2b2b2b", highlightthickness=0)
        self._sprites: dict[str, CardSpriteVisual] = {}
        self._decks: dict[str, DeckVisual] = {}
        self._zones: dict[str, ZoneVisual] = {}
        self._battlefield_zone: Zone | None = None
        self._next_id = 1
        self._drag_tag: str | None = None
        self._drag_off_x = 0
        self._drag_off_y = 0
        self._context_menu = tk.Menu(self, tearoff=0)
        self._context_tag: str | None = None
        self._hover_tag: str | None = None
        self._hover_zone_tag: str | None = None
        self._hover_deck_tag: str | None = None
        self._context_keys_bound = False
        self._deck_context_keys_bound = False
        self._hotkeys: Hotkeys = DEFAULT_HOTKEYS
        # Selection
        self._selected: set[str] = set()
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_rect: int | None = None
        # Image cache
        self._img_cache: dict[str, object] = {}

        # Pending deck drag state
        self._pending_deck_tag: str | None = None
        self._pending_deck_press: tuple[int, int] | None = None
        # Pending zone drag state (excluding Hand)
        self._pending_zone_tag: str | None = None
        self._pending_zone_press: tuple[int, int] | None = None
        # Track source deck when dragging a freshly drawn card
        self._drag_source_deck_tag: str | None = None

        # Event bindings
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Double-Button-1>", self._on_double_click)
        # Context menu (right-click)
        self.bind("<Button-2>", self._on_context)
        self.bind("<Button-3>", self._on_context)
        self.bind("<Control-Button-1>", self._on_context)
        # Hover and keyboard
        self.bind("<Motion>", self._on_move)
        self.bind("<Enter>", lambda e: self.focus_set())
        self.bind("<KeyPress-Escape>", self._on_escape)

    def _tk_state(self, enabled: bool) -> Literal["normal", "disabled"]:
        return "normal" if enabled else "disabled"

    def configure_hotkeys(self, hotkeys: Hotkeys) -> None:
        # Remove previous bindings if any
        for key in {
            self._hotkeys.bow,
            self._hotkeys.flip,
            self._hotkeys.invert,
            getattr(self._hotkeys, "fill", ""),
            getattr(self._hotkeys, "destroy", ""),
        }:
            if key:
                self.unbind(f"<KeyPress-{key}>")
        self._hotkeys = hotkeys
        # Add new bindings (canvas-level)
        self.bind(f"<KeyPress-{self._hotkeys.bow}>", self._on_key)
        self.bind(f"<KeyPress-{self._hotkeys.flip}>", self._on_key)
        self.bind(f"<KeyPress-{self._hotkeys.invert}>", self._on_key)
        self.bind(f"<KeyPress-{self._hotkeys.fill}>", self._on_key)
        self.bind(f"<KeyPress-{self._hotkeys.destroy}>", self._on_key)

    # Public API
    def set_battlefield_zone(self, zone: Zone | None) -> None:
        self._battlefield_zone = zone

    def add_card(self, card: L5RCard, x: int, y: int) -> str:
        tag = f"card:{self._next_id}"
        self._next_id += 1
        sprite = CardSpriteVisual(card, x, y, tag)
        self._sprites[tag] = sprite
        if self._battlefield_zone is not None:
            self._battlefield_zone.add(card)
        sprite.draw(self, selected=sprite.tag in self._selected)
        return tag

    def add_deck(self, deck: Deck[L5RCard], x: int, y: int, label: str = "Deck") -> str:
        tag = f"deck:{self._next_id}"
        self._next_id += 1
        deck = DeckVisual(deck, x, y, tag, label)
        self._decks[tag] = deck
        deck.draw(self)
        return tag

    def add_zone(self, zone: Zone, x: int, y: int, w: int, h: int) -> str:
        tag = f"zone:{self._next_id}"
        self._next_id += 1
        zv = ZoneVisual(zone, x, y, w, h, tag)
        self._zones[tag] = zv
        zv.draw(self)
        return tag

    def _redraw_sprite(self, tag: str) -> None:
        self.delete(tag)
        sprite = self._sprites.get(tag)
        if sprite is None:
            return
        sprite.draw(self, selected=tag in self._selected)

    def _redraw_deck(self, tag: str) -> None:
        self.delete(tag)
        deck = self._decks.get(tag)
        if deck is None:
            return
        deck.draw(self)

    def _redraw_zone(self, tag: str) -> None:
        self.delete(tag)
        zv = self._zones.get(tag)
        if zv is None:
            return
        zv.draw(self)

    def _deck_expected_side(self, dv: DeckVisual) -> Side | None:
        if "Fate" in dv.label:
            return Side.FATE
        if "Dynasty" in dv.label:
            return Side.DYNASTY
        top = dv.deck.peek(1)
        return top[0].side if top else None

    def _deck_hit_for_sprite(self, sprite: CardSpriteVisual) -> str | None:
        cx, cy = sprite.x, sprite.y
        for tag, dv in self._decks.items():
            x0, y0, x1, y1 = dv.bbox
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return tag
        for tag, dv in self._decks.items():
            if sprite.intersects(dv):
                return tag
        return None

    def _zone_hit_for_sprite(self, sprite: CardSpriteVisual) -> str | None:
        cx, cy = sprite.x, sprite.y
        for tag, zv in self._zones.items():
            x0, y0, x1, y1 = zv.bbox
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return tag
        for tag, zv in self._zones.items():
            if sprite.intersects(zv):
                return tag
        return None

    # Selection helpers
    def _clear_selection(self) -> None:
        if not self._selected:
            return
        tags = list(self._selected)
        self._selected.clear()
        for t in tags:
            self._redraw_sprite(t)

    def _set_selection(self, tags: set[str]) -> None:
        if tags == self._selected:
            return
        old = self._selected.copy()
        self._selected = set(tags)
        for t in old - self._selected:
            self._redraw_sprite(t)
        for t in self._selected - old:
            self._redraw_sprite(t)

    # Event helpers
    def _resolve_tag_at(self, event: tk.Event) -> str | None:
        item = self.find_withtag("current")
        if not item:
            return None
        tags = self.gettags(item[0])
        for t in tags:
            if t.startswith("card:") or t.startswith("deck:") or t.startswith("zone:"):
                return t
        return None

    def _update_hover_from_event(self, event: tk.Event) -> None:
        tag = self._resolve_tag_at(event)
        if tag and tag.startswith("card:"):
            self._hover_tag = tag
            self._hover_zone_tag = None
            self._hover_deck_tag = None
        elif tag and tag.startswith("zone:"):
            self._hover_zone_tag = tag
            self._hover_tag = None
            self._hover_deck_tag = None
        elif tag and tag.startswith("deck:"):
            self._hover_deck_tag = tag
            self._hover_tag = None
            self._hover_zone_tag = None
        else:
            self._hover_tag = None
            self._hover_zone_tag = None
            self._hover_deck_tag = None

    # Apply helpers for single or selection
    def _apply_to_targets(self, tag: str, apply_fn: Callable[[CardSpriteVisual], None]) -> None:
        targets = self._selected if (self._selected and tag in self._selected) else {tag}
        for t in targets:
            sprite = self._sprites.get(t)
            if not sprite:
                continue
            apply_fn(sprite)
            self._redraw_sprite(t)

    def _apply_to_selection(self, apply_fn: Callable[[CardSpriteVisual], None]) -> None:
        if not self._selected:
            return
        for t in list(self._selected):
            sprite = self._sprites.get(t)
            if not sprite:
                continue
            apply_fn(sprite)
            self._redraw_sprite(t)

    # Helpers to find zones/decks
    def _find_zone_tag_by_type(self, zone_type: type[Zone]) -> str | None:
        for tag, zv in self._zones.items():
            if isinstance(zv.zone, zone_type):
                return tag
        return None

    def _find_deck_tag_by_side(self, side: Side) -> str | None:
        # Prefer label heuristic, fallback to top card side
        for tag, dv in self._decks.items():
            if side is Side.FATE and "Fate" in dv.label:
                return tag
            if side is Side.DYNASTY and "Dynasty" in dv.label:
                return tag
        for tag, dv in self._decks.items():
            top = dv.deck.peek(1)
            if top and top[0].side is side:
                return tag
        return None

    def _remove_from_all_zones(self, card: L5RCard) -> None:
        if self._battlefield_zone is not None:
            self._battlefield_zone.remove(card)
        for zv in self._zones.values():
            zv.zone.remove(card)

    def _remove_card_sprite(self, tag: str) -> None:
        sprite = self._sprites.pop(tag, None)
        # Always clean up canvas and state for this tag
        try:
            self.delete(tag)
        except Exception:
            pass
        # Remove from selection/hover/context
        self._selected.discard(tag)
        if self._hover_tag == tag:
            self._hover_tag = None
        if self._context_tag == tag:
            self._context_tag = None
        if sprite is None:
            return
        self.delete(tag)

    # Send-to commands
    def _send_card_to_hand(self, tag: str) -> None:
        sprite = self._sprites.get(tag)
        if not sprite:
            return
        zone_tag = self._find_zone_tag_by_type(HandZone)
        if not zone_tag:
            return
        target_zone = self._zones[zone_tag].zone
        # Pre-check capacity
        if not target_zone.has_capacity():
            return
        # Update model: remove from zones, then flip and add
        self._remove_from_all_zones(sprite.card)
        sprite.card.turn_face_down()
        target_zone.add(sprite.card)
        # Remove from canvas and redraw zone
        self._remove_card_sprite(tag)
        self._redraw_zone(zone_tag)

    def _send_card_to_fate_discard(self, tag: str) -> None:
        sprite = self._sprites.get(tag)
        if not sprite:
            return
        zone_tag = self._find_zone_tag_by_type(FateDiscardZone)
        if not zone_tag:
            return
        target_zone = self._zones[zone_tag].zone
        if not target_zone.has_capacity():
            return
        self._remove_from_all_zones(sprite.card)
        target_zone.add(sprite.card)
        self._remove_card_sprite(tag)
        self._redraw_zone(zone_tag)

    def _send_card_to_dynasty_discard(self, tag: str) -> None:
        sprite = self._sprites.get(tag)
        if not sprite:
            return
        zone_tag = self._find_zone_tag_by_type(DynastyDiscardZone)
        if not zone_tag:
            return
        target_zone = self._zones[zone_tag].zone
        if not target_zone.has_capacity():
            return
        self._remove_from_all_zones(sprite.card)
        target_zone.add(sprite.card)
        self._remove_card_sprite(tag)
        self._redraw_zone(zone_tag)

    def _send_card_to_deck_top(self, tag: str, side: Side) -> None:
        sprite = self._sprites.get(tag)
        if not sprite:
            return
        deck_tag = self._find_deck_tag_by_side(side)
        if not deck_tag:
            return
        dv = self._decks[deck_tag]
        # Update model
        self._remove_from_all_zones(sprite.card)
        sprite.card.turn_face_down()
        dv.deck.add_to_top([sprite.card])
        # Remove from canvas and redraw deck
        self._remove_card_sprite(tag)
        self._redraw_deck(deck_tag)

    def _send_card_to_deck_bottom(self, tag: str, side: Side) -> None:
        sprite = self._sprites.get(tag)
        if not sprite:
            return
        deck_tag = self._find_deck_tag_by_side(side)
        if not deck_tag:
            return
        dv = self._decks[deck_tag]
        # Update model
        self._remove_from_all_zones(sprite.card)
        sprite.card.turn_face_down()
        dv.deck.add_to_bottom([sprite.card])
        # Remove from canvas and redraw deck
        self._remove_card_sprite(tag)
        self._redraw_deck(deck_tag)

    # Context menu helpers
    def _build_context_menu_for(self, tag: str) -> None:
        sprite = self._sprites[tag]
        self._context_menu.delete(0, "end")

        b = self._hotkeys.bow
        f = self._hotkeys.flip
        d = self._hotkeys.invert

        if sprite.card.bowed:
            self._context_menu.add_command(
                label=f"Unbow ({b})", command=lambda: self._invoke_menu_action(self._cmd_unbow, tag)
            )
        else:
            self._context_menu.add_command(
                label=f"Bow ({b})", command=lambda: self._invoke_menu_action(self._cmd_bow, tag)
            )

        if sprite.card.inverted:
            self._context_menu.add_command(
                label=f"Uninvert ({d})",
                command=lambda: self._invoke_menu_action(self._cmd_uninvert, tag),
            )
        else:
            self._context_menu.add_command(
                label=f"Invert ({d})",
                command=lambda: self._invoke_menu_action(self._cmd_invert, tag),
            )

        if sprite.card.face_up:
            self._context_menu.add_command(
                label=f"Flip Down ({f})",
                command=lambda: self._invoke_menu_action(self._cmd_flip_down, tag),
            )
        else:
            self._context_menu.add_command(
                label=f"Flip Up ({f})",
                command=lambda: self._invoke_menu_action(self._cmd_flip_up, tag),
            )

        # Send to submenu
        send_to = tk.Menu(self._context_menu, tearoff=0)
        if sprite.card.side is Side.FATE:
            # Hand
            hand_tag = self._find_zone_tag_by_type(HandZone)
            send_to.add_command(
                label="Hand",
                state=self._tk_state(bool(hand_tag)),
                command=lambda: self._send_card_to_hand(tag),
            )
            # Fate discard
            fate_disc_tag = self._find_zone_tag_by_type(FateDiscardZone)
            send_to.add_command(
                label="Fate Discard",
                state=self._tk_state(bool(fate_disc_tag)),
                command=lambda: self._send_card_to_fate_discard(tag),
            )
            # Deck top/bottom
            fate_deck_tag = self._find_deck_tag_by_side(Side.FATE)
            send_to.add_command(
                label="Fate Top",
                state=self._tk_state(bool(fate_deck_tag)),
                command=lambda: self._send_card_to_deck_top(tag, Side.FATE),
            )
            send_to.add_command(
                label="Fate Bottom",
                state=self._tk_state(bool(fate_deck_tag)),
                command=lambda: self._send_card_to_deck_bottom(tag, Side.FATE),
            )
        else:
            # Dynasty discard
            dyn_disc_tag = self._find_zone_tag_by_type(DynastyDiscardZone)
            send_to.add_command(
                label="Dynasty Discard",
                state=self._tk_state(bool(dyn_disc_tag)),
                command=lambda: self._send_card_to_dynasty_discard(tag),
            )
            # Deck top/bottom
            dyn_deck_tag = self._find_deck_tag_by_side(Side.DYNASTY)
            send_to.add_command(
                label="Dynasty Top",
                state=self._tk_state(bool(dyn_deck_tag)),
                command=lambda: self._send_card_to_deck_top(tag, Side.DYNASTY),
            )
            send_to.add_command(
                label="Dynasty Bottom",
                state=self._tk_state(bool(dyn_deck_tag)),
                command=lambda: self._send_card_to_deck_bottom(tag, Side.DYNASTY),
            )

        self._context_menu.add_cascade(label="Send to", menu=send_to)

    def _build_context_menu_for_zone(self, ztag: str) -> None:
        zv = self._zones[ztag]
        zone = zv.zone
        self._context_menu.delete(0, "end")
        f = self._hotkeys.flip
        lkey = self._hotkeys.fill
        ckey = self._hotkeys.destroy
        # Flip
        if zone.cards and zone.cards[-1].face_up:
            self._context_menu.add_command(
                label=f"Flip Down ({f})",
                command=lambda: self._invoke_menu_action(
                    lambda _: self._zone_flip_down(ztag), ztag
                ),
            )
        else:
            self._context_menu.add_command(
                label=f"Flip Up ({f})",
                command=lambda: self._invoke_menu_action(lambda _: self._zone_flip_up(ztag), ztag),
            )
        # Fill
        self._context_menu.add_command(
            label=f"Fill ({lkey})",
            state=self._tk_state(zone.has_capacity()),
            command=lambda: self._invoke_menu_action(lambda _: self._zone_fill(ztag), ztag),
        )
        # Destroy for provinces only
        if isinstance(zone, ProvinceZone):
            self._context_menu.add_separator()
            self._context_menu.add_command(
                label=f"Destroy ({ckey})",
                command=lambda: self._invoke_menu_action(lambda _: self._zone_destroy(ztag), ztag),
            )

    def _build_context_menu_for_deck(self, dtag: str) -> None:
        dv = self._decks[dtag]
        self._context_menu.delete(0, "end")
        rkey = "r"
        skey = "s"
        fkey = self._hotkeys.flip
        ikey = "i"

        self._context_menu.add_command(
            label=f"Draw ({rkey})",
            state=self._tk_state(len(dv.deck.cards) > 0),
            command=lambda: self._invoke_menu_action(lambda _: self._deck_draw(dtag), dtag),
        )
        self._context_menu.add_command(
            label=f"Shuffle ({skey})",
            command=lambda: self._invoke_menu_action(lambda _: self._deck_shuffle(dtag), dtag),
        )
        self._context_menu.add_command(
            label=f"Flip Top ({fkey})",
            state=self._tk_state(len(dv.deck.cards) > 0),
            command=lambda: self._invoke_menu_action(lambda _: self._deck_flip_top(dtag), dtag),
        )
        self._context_menu.add_command(
            label=f"Inspect ({ikey})",
            command=lambda: self._invoke_menu_action(lambda _: self._deck_inspect(dtag), dtag),
        )
        self._context_menu.add_command(
            label="Search",
            command=lambda: self._invoke_menu_action(lambda _: self._deck_search(dtag), dtag),
        )

        top_menu = tk.Menu(self._context_menu, tearoff=0)
        for n in range(1, 11):
            top_menu.add_command(label=str(n), command=lambda n=n: self._deck_search(dtag, n=n))
        self._context_menu.add_cascade(label="Search Top", menu=top_menu)
        # Reveal Top (TODO)
        self._context_menu.add_command(
            label="Reveal Top (TODO)",
            command=lambda: self._invoke_menu_action(lambda _: self._deck_reveal_top(dtag), dtag),
        )

        if "Dynasty" in dv.label:
            self._context_menu.add_separator()
            self._context_menu.add_command(
                label="Add Province",
                command=lambda: self._invoke_menu_action(
                    lambda _: self._deck_add_province(dtag), dtag
                ),
            )

    def _bind_deck_context_keys(self) -> None:
        if self._deck_context_keys_bound:
            return
        rkey, skey, fkey, ikey = "r", "s", self._hotkeys.flip, "i"
        self.bind_all(f"<KeyPress-{rkey}>", lambda e: self._invoke_context_shortcut_deck(rkey))
        self.bind_all(f"<KeyPress-{skey}>", lambda e: self._invoke_context_shortcut_deck(skey))
        self.bind_all(f"<KeyPress-{fkey}>", lambda e: self._invoke_context_shortcut_deck(fkey))
        self.bind_all(f"<KeyPress-{ikey}>", lambda e: self._invoke_context_shortcut_deck(ikey))
        self._deck_context_keys_bound = True

    def _unbind_deck_context_keys(self) -> None:
        if not self._deck_context_keys_bound:
            return
        for key in {"r", "s", self._hotkeys.flip, "i"}:
            self.unbind_all(f"<KeyPress-{key}>")
        self._deck_context_keys_bound = False

    def _invoke_context_shortcut_deck(self, keysym: str) -> None:
        tag = self._context_tag
        if not tag or not tag.startswith("deck:"):
            return
        if keysym == "r":
            self._deck_draw(tag)
        elif keysym == "s":
            self._deck_shuffle(tag)
        elif keysym == self._hotkeys.flip:
            self._deck_flip_top(tag)
        elif keysym == "i":
            self._deck_inspect(tag)
        try:
            self._context_menu.unpost()
        except Exception:
            pass
        self._context_tag = None
        self._unbind_deck_context_keys()

    def _deck_draw(self, dtag: str) -> None:
        dv = self._decks[dtag]
        card = dv.deck.draw_one()
        if card is None:
            return
        card.turn_face_down()
        offset = CARD_W + DRAW_OFFSET
        draw_x = dv.x - offset if card.side is Side.FATE else dv.x + offset
        draw_y = dv.y
        self.add_card(card, draw_x, draw_y)
        self._redraw_deck(dtag)

    def _deck_shuffle(self, dtag: str) -> None:
        dv = self._decks[dtag]
        dv.deck.shuffle()
        self._redraw_deck(dtag)

    def _deck_flip_top(self, dtag: str) -> None:
        dv = self._decks[dtag]
        top = dv.deck.peek(1)
        if not top:
            return
        top[0].turn_face_up()
        self._redraw_deck(dtag)

    def _deck_inspect(self, dtag: str) -> None:
        dv = self._decks[dtag]
        win = tk.Toplevel(self)
        win.title(f"Inspect - {dv.label}")
        canvas = tk.Canvas(win, width=800, height=260, bg="#1e1e1e")
        hscroll = tk.Scrollbar(win, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=hscroll.set)
        frame = tk.Frame(canvas, bg="#1e1e1e")
        canvas.create_window((0, 0), window=frame, anchor="nw")
        images: list[object] = []
        pad = 10
        for idx, card in enumerate(dv.deck.cards):
            bowed = card.bowed
            face_up = card.face_up
            photo = (
                load_image(card.image_front, bowed, master=win)
                if face_up
                else load_back_image(card.side, bowed, card.image_back, master=win)
            )
            holder = tk.Frame(frame, bg="#1e1e1e")
            holder.grid(row=0, column=idx, padx=pad, pady=pad)
            if photo is not None:
                lbl = tk.Label(holder, image=photo, bg="#1e1e1e")
                lbl.pack()
                images.append(photo)
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
        # prevent GC
        win._images = images  # type: ignore[attr-defined]

    def _deck_search(self, dtag: str, n: int | None = None) -> None:
        dv = self._decks[dtag]
        cards = dv.deck.cards[-n:] if n else dv.deck.cards[:]
        if not cards:
            return
        win = tk.Toplevel(self)
        title = f"Search Top {n} - {dv.label}" if n else f"Search - {dv.label}"
        win.title(title)
        list_frame = tk.Frame(win, bg="#1e1e1e")
        list_frame.pack(fill="both", expand=True)
        images: list[object] = []

        def draw_card_at_index(idx_in_deck: int) -> None:
            # Map from displayed index to actual index in deck.cards
            actual_card = dv.deck.cards[idx_in_deck]
            dv.deck.cards.pop(idx_in_deck)
            actual_card.turn_face_down()
            offset = CARD_W + DRAW_OFFSET
            draw_x = dv.x - offset if actual_card.side is Side.FATE else dv.x + offset
            draw_y = dv.y
            self.add_card(actual_card, draw_x, draw_y)
            self._redraw_deck(dtag)
            try:
                win.destroy()
            except Exception:
                pass

        # Build grid
        for col, card in enumerate(cards):
            idx_in_deck = (len(dv.deck.cards) - len(cards)) + col if n else col
            bowed = card.bowed
            face_up = card.face_up
            photo = (
                load_image(card.image_front, bowed, master=win)
                if face_up
                else load_back_image(card.side, bowed, card.image_back, master=win)
            )
            cell = tk.Frame(list_frame, bg="#1e1e1e")
            cell.grid(row=0, column=col, padx=6, pady=6)
            if photo is not None:
                lbl = tk.Label(cell, image=photo, bg="#1e1e1e")
                lbl.pack()
                images.append(photo)
            else:
                w, h = (CARD_H, CARD_W) if card.bowed else (CARD_W, CARD_H)
                c = tk.Canvas(cell, width=w, height=h, bg="#6b6b6b", highlightthickness=0)
                c.pack()
                c.create_text(w // 2, h // 2, text=card.name, fill="#222")
            btn = tk.Button(cell, text="Draw", command=lambda i=idx_in_deck: draw_card_at_index(i))
            btn.pack(pady=4)
        win._images = images  # type: ignore[attr-defined]

    def _deck_reveal_top(self, dtag: str) -> None:
        # TODO: reveal to opponent when multi-player UI is present
        dv = self._decks[dtag]
        win = tk.Toplevel(self)
        win.title(f"Reveal Top (TODO) - {dv.label}")
        tk.Label(win, text="TODO: Reveal to opponent", bg="#1e1e1e", fg="#eaeaea").pack(
            padx=12, pady=12
        )

    def _deck_add_province(self, dtag: str) -> None:
        # Only meaningful for Dynasty decks
        dv = self._decks[dtag]
        if "Dynasty" not in dv.label:
            return
        # Create new province zone
        new_zone = ProvinceZone()
        # Determine spacing and center
        provinces: list[tuple[str, ZoneVisual]] = [
            (tag, zv) for tag, zv in self._zones.items() if isinstance(zv.zone, ProvinceZone)
        ]
        spacing = CARD_W
        center_x: int
        if provinces:
            # Keep prior visual center
            center_x = int(sum(zv.x for _, zv in provinces) / len(provinces))
        else:
            # Use midpoint between decks if both present, else deck x
            fate_tags = [t for t, d in self._decks.items() if "Fate" in d.label]
            if fate_tags:
                fate_x = self._decks[fate_tags[0]].x
                center_x = (dv.x + fate_x) // 2
            else:
                center_x = dv.x + CARD_W * 2
        # Add to model and visuals
        self.add_zone(new_zone, x=center_x, y=dv.y, w=CARD_W, h=CARD_H)
        # Recompute provinces including new one, and re-center in a row with spacing
        provinces = [
            (tag, zv) for tag, zv in self._zones.items() if isinstance(zv.zone, ProvinceZone)
        ]
        provinces.sort(key=lambda item: item[1].x)
        n = len(provinces)
        start_x = int(center_x - ((n - 1) * spacing) / 2)
        for i, (ptag, pv) in enumerate(provinces):
            pv.x = start_x + i * spacing
            self._redraw_zone(ptag)

    def _invoke_menu_action(self, action: Callable[[str], None], tag: str) -> None:
        # Execute the action as if the menu item was clicked
        action(tag)
        # Close the menu and clear context
        try:
            self._context_menu.unpost()
        except Exception:
            pass
        self._context_tag = None
        self._unbind_context_keys()

    def _bind_context_keys(self) -> None:
        if self._context_keys_bound:
            return
        b = self._hotkeys.bow
        f = self._hotkeys.flip
        d = self._hotkeys.invert
        self.bind_all(f"<KeyPress-{b}>", lambda e: self._invoke_context_shortcut(b))
        self.bind_all(f"<KeyPress-{f}>", lambda e: self._invoke_context_shortcut(f))
        self.bind_all(f"<KeyPress-{d}>", lambda e: self._invoke_context_shortcut(d))
        self._context_keys_bound = True

    def _unbind_context_keys(self) -> None:
        if not self._context_keys_bound:
            return
        for key in {self._hotkeys.bow, self._hotkeys.flip, self._hotkeys.invert}:
            self.unbind_all(f"<KeyPress-{key}>")
        self._context_keys_bound = False

    def _invoke_context_shortcut(self, keysym: str) -> None:
        tag = self._context_tag
        if not tag or not tag.startswith("card:"):
            return
        if keysym == self._hotkeys.bow:
            # Toggle bow on selection or single
            def _toggle_bow(sprite: CardSpriteVisual) -> None:
                if sprite.card.bowed:
                    sprite.card.unbow()
                else:
                    sprite.card.bow()

            self._apply_to_targets(tag, _toggle_bow)
        elif keysym == self._hotkeys.flip:

            def _flip(sprite: CardSpriteVisual) -> None:
                if sprite.card.face_up:
                    sprite.card.turn_face_down()
                else:
                    sprite.card.turn_face_up()

            self._apply_to_targets(tag, _flip)
        elif keysym == self._hotkeys.invert:

            def _toggle_invert(sprite: CardSpriteVisual) -> None:
                if sprite.card.inverted:
                    sprite.card.uninvert()
                else:
                    sprite.card.invert()

            self._apply_to_targets(tag, _toggle_invert)
        # Close and clear context after shortcut selection
        try:
            self._context_menu.unpost()
        except Exception:
            pass
        self._context_tag = None
        self._unbind_context_keys()

    # Event handlers
    def _on_press(self, event: tk.Event) -> None:
        self.focus_set()
        tag = self._resolve_tag_at(event)
        if not tag:
            # Background press: clear selection and start marquee
            self._clear_selection()
            self._marquee_start = (event.x, event.y)
            if self._marquee_rect is None:
                self._marquee_rect = self.create_rectangle(
                    event.x,
                    event.y,
                    event.x,
                    event.y,
                    outline="#66ccff",
                    width=2,
                    dash=(4, 2),
                    tags=("marquee",),
                )
            else:
                self.coords(self._marquee_rect, event.x, event.y, event.x, event.y)
                self.itemconfig(self._marquee_rect, outline="#66ccff", width=2, dash=(4, 2))
            self.tag_raise(self._marquee_rect)
            return
        if tag.startswith("deck:"):
            # Arm a pending deck drag; do not draw yet
            self._pending_deck_tag = tag
            self._pending_deck_press = (event.x, event.y)
            return
        if tag.startswith("zone:"):
            # Arm a pending zone drag (excluding Hand)
            zv = self._zones.get(tag)
            if zv is not None and not isinstance(zv.zone, HandZone):
                self._pending_zone_tag = tag
                self._pending_zone_press = (event.x, event.y)
                return
        if tag.startswith("card:"):
            # If the clicked card is not selected, collapse to single selection
            if tag not in self._selected:
                self._set_selection({tag})
            sprite = self._sprites[tag]
            self._drag_tag = tag
            self._drag_off_x = event.x - sprite.x
            self._drag_off_y = event.y - sprite.y
            # Bring to front
            self.tag_raise(tag)

    def _on_move(self, event: tk.Event) -> None:
        self._update_hover_from_event(event)
        # Update marquee selection live
        if self._marquee_start is not None and self._drag_tag is None:
            x0, y0 = self._marquee_start
            x1, y1 = event.x, event.y
            if self._marquee_rect is not None:
                self.coords(self._marquee_rect, x0, y0, x1, y1)
                self.tag_raise(self._marquee_rect)
            sel_rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            rect_visual = MarqueeBoxVisual(sel_rect)
            new_sel: set[str] = set()
            for tag, sprite in self._sprites.items():
                if sprite.intersects(rect_visual):
                    new_sel.add(tag)
            self._set_selection(new_sel)

    def _on_motion(self, event: tk.Event) -> None:
        # If marquee is active, mirror updates here during B1-Motion as well
        if self._marquee_start is not None and self._drag_tag is None:
            x0, y0 = self._marquee_start
            x1, y1 = event.x, event.y
            if self._marquee_rect is not None:
                self.coords(self._marquee_rect, x0, y0, x1, y1)
                self.tag_raise(self._marquee_rect)
            sel_rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            rect_visual = MarqueeBoxVisual(sel_rect)
            new_sel: set[str] = set()
            for tag, sprite in self._sprites.items():
                if sprite.intersects(rect_visual):
                    new_sel.add(tag)
            self._set_selection(new_sel)
            return
        # If we have a pending deck drag and no active drag, start it when cursor leaves deck bounds
        if self._pending_deck_tag and self._drag_tag is None:
            visual = self._decks.get(self._pending_deck_tag)
            if visual is not None:
                x0, y0, x1, y1 = visual.bbox
                if not (x0 <= event.x <= x1 and y0 <= event.y <= y1):
                    card = visual.deck.draw_one()
                    if card is not None:
                        card.turn_face_down()
                        new_tag = self.add_card(card, event.x, event.y)
                        self._drag_tag = new_tag
                        self._drag_off_x = 0
                        self._drag_off_y = 0
                        self._redraw_deck(self._pending_deck_tag)
                        # Remember which deck this drag came from
                        self._drag_source_deck_tag = self._pending_deck_tag
                    # Clear pending regardless
                    self._pending_deck_tag = None
                    self._pending_deck_press = None
        # If we have a pending zone drag and no active drag, start it when cursor leaves zone bounds
        if self._pending_zone_tag and self._drag_tag is None:
            zv = self._zones.get(self._pending_zone_tag)
            if zv is not None:
                x0, y0, x1, y1 = zv.bbox
                if not (x0 <= event.x <= x1 and y0 <= event.y <= y1):
                    # Take top card from zone and start dragging it to battlefield
                    if zv.zone.cards:
                        card = zv.zone.cards.pop()
                        new_tag = self.add_card(card, event.x, event.y)
                        self._drag_tag = new_tag
                        self._drag_off_x = 0
                        self._drag_off_y = 0
                        self._redraw_zone(self._pending_zone_tag)
                    # Clear pending regardless
                    self._pending_zone_tag = None
                    self._pending_zone_press = None
        if not self._drag_tag:
            return
        sprite = self._sprites[self._drag_tag]
        new_x = event.x - self._drag_off_x
        new_y = event.y - self._drag_off_y
        dx = new_x - sprite.x
        dy = new_y - sprite.y
        if dx or dy:
            self.move(self._drag_tag, dx, dy)
            sprite.x = new_x
            sprite.y = new_y

    def _on_release(self, event: tk.Event) -> None:
        # End marquee
        if self._marquee_start is not None:
            self._marquee_start = None
            if self._marquee_rect is not None:
                self.delete(self._marquee_rect)
                self._marquee_rect = None
        # If we were dragging a card, check drop target zone or deck
        if self._drag_tag:
            sprite = self._sprites.get(self._drag_tag)
            if sprite is not None:
                ztag = self._zone_hit_for_sprite(sprite)
                if ztag is not None:
                    self._drop_sprite_into_zone(self._drag_tag, ztag)
                else:
                    dtag = self._deck_hit_for_sprite(sprite)
                    if dtag is not None:
                        # Avoid dropping back onto the same deck immediately after draw
                        if self._drag_source_deck_tag and dtag == self._drag_source_deck_tag:
                            pass
                        else:
                            self._drop_sprite_into_deck(self._drag_tag, dtag)
        self._drag_tag = None
        # Clear any pending deck/zone drag if mouse released without leaving bounds
        self._pending_deck_tag = None
        self._pending_deck_press = None
        self._pending_zone_tag = None
        self._pending_zone_press = None
        self._drag_source_deck_tag = None

    def _on_double_click(self, event: tk.Event) -> None:
        tag = self._resolve_tag_at(event)
        if not tag:
            return
        if tag.startswith("deck:"):
            visual = self._decks[tag]
            card = visual.deck.draw_one()
            if card is None:
                return
            card.turn_face_down()
            # Place drawn card toward the center relative to the deck side
            offset = CARD_W + DRAW_OFFSET
            draw_x = visual.x - offset if card.side is Side.FATE else visual.x + offset
            draw_y = visual.y
            # add_card handles battlefield tracking
            self.add_card(card, draw_x, draw_y)
            self._redraw_deck(tag)
            return
        if tag.startswith("zone:"):
            zv = self._zones.get(tag)
            if zv is None or isinstance(zv.zone, HandZone):
                return
            if not zv.zone.cards:
                return
            card = zv.zone.cards.pop()
            # Place card at zone center on battlefield, keeping its current state
            self.add_card(card, zv.x, zv.y)
            self._redraw_zone(tag)
            return
        if tag.startswith("card:"):
            # Toggle bow on targets
            def _toggle_bow(sprite: CardSpriteVisual) -> None:
                if sprite.card.bowed:
                    sprite.card.unbow()
                else:
                    sprite.card.bow()

            self._apply_to_targets(tag, _toggle_bow)

    def _on_context(self, event: tk.Event) -> None:
        self.focus_set()
        tag = self._resolve_tag_at(event)
        if not tag:
            return
        if tag.startswith("card:"):
            # If clicked card is not already selected, select only it
            if tag not in self._selected:
                self._set_selection({tag})
            self._context_tag = tag
            self._build_context_menu_for(tag)
            self._bind_context_keys()
            try:
                self._context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._context_menu.grab_release()
                self._unbind_context_keys()
            return
        if tag.startswith("zone:"):
            self._context_tag = tag
            self._build_context_menu_for_zone(tag)
            # Bind flip/fill/destroy hotkeys while menu open
            f = self._hotkeys.flip
            lkey = self._hotkeys.fill
            ckey = self._hotkeys.destroy
            self.bind_all(f"<KeyPress-{f}>", lambda e: self._invoke_context_shortcut_zone(f))
            self.bind_all(f"<KeyPress-{lkey}>", lambda e: self._invoke_context_shortcut_zone(lkey))
            self.bind_all(f"<KeyPress-{ckey}>", lambda e: self._invoke_context_shortcut_zone(ckey))
            try:
                self._context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._context_menu.grab_release()
                self.unbind_all(f"<KeyPress-{f}>")
                self.unbind_all(f"<KeyPress-{lkey}>")
                self.unbind_all(f"<KeyPress-{ckey}>")
            return
        if tag.startswith("deck:"):
            self._context_tag = tag
            self._build_context_menu_for_deck(tag)
            self._bind_deck_context_keys()
            try:
                self._context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._context_menu.grab_release()
                self._unbind_deck_context_keys()
            return

    def _invoke_context_shortcut_zone(self, keysym: str) -> None:
        tag = self._context_tag
        if not tag or not tag.startswith("zone:"):
            return
        if keysym == self._hotkeys.flip:
            zv = self._zones.get(tag)
            if not zv:
                return
            if zv.zone.cards and zv.zone.cards[-1].face_up:
                self._zone_flip_down(tag)
            else:
                self._zone_flip_up(tag)
        elif keysym == self._hotkeys.fill:
            self._zone_fill(tag)
        elif keysym == self._hotkeys.destroy:
            self._zone_destroy(tag)
        try:
            self._context_menu.unpost()
        except Exception:
            pass
        self._context_tag = None

    def _on_key(self, event: tk.Event) -> None:
        targets_present = bool(
            self._selected or self._hover_tag or self._hover_zone_tag or self._hover_deck_tag
        )
        if not targets_present:
            return
        key = getattr(event, "keysym", "").lower()
        # Deck hover hotkeys
        if self._hover_deck_tag and key in {"r", "s", self._hotkeys.flip, "i"}:
            if key == "r":
                self._deck_draw(self._hover_deck_tag)
            elif key == "s":
                self._deck_shuffle(self._hover_deck_tag)
            elif key == self._hotkeys.flip:
                self._deck_flip_top(self._hover_deck_tag)
            elif key == "i":
                self._deck_inspect(self._hover_deck_tag)
            return
        # Zone hover hotkeys
        if self._hover_zone_tag and key in {
            self._hotkeys.flip,
            self._hotkeys.fill,
            self._hotkeys.destroy,
        }:
            if key == self._hotkeys.flip:
                zv = self._zones.get(self._hover_zone_tag)
                if zv and zv.zone.cards:
                    if zv.zone.cards[-1].face_up:
                        self._zone_flip_down(self._hover_zone_tag)
                    else:
                        self._zone_flip_up(self._hover_zone_tag)
            elif key == self._hotkeys.fill:
                self._zone_fill(self._hover_zone_tag)
            elif key == self._hotkeys.destroy:
                self._zone_destroy(self._hover_zone_tag)
            return

        # Card hotkeys
        def _toggle_bow(s: CardSpriteVisual) -> None:
            if s.card.bowed:
                s.card.unbow()
            else:
                s.card.bow()

        def _toggle_flip(s: CardSpriteVisual) -> None:
            if s.card.face_up:
                s.card.turn_face_down()
            else:
                s.card.turn_face_up()

        def _toggle_invert(s: CardSpriteVisual) -> None:
            if s.card.inverted:
                s.card.uninvert()
            else:
                s.card.invert()

        if key == self._hotkeys.bow:
            fn = _toggle_bow
        elif key == self._hotkeys.flip:
            fn = _toggle_flip
        elif key == self._hotkeys.invert:
            fn = _toggle_invert
        else:
            return
        if self._selected:
            self._apply_to_selection(fn)
        else:
            self._apply_to_targets(self._hover_tag, fn)  # type: ignore[arg-type]

    def _on_escape(self, event: tk.Event) -> None:
        self._clear_selection()

    # Context menu commands
    def _cmd_bow(self, tag: str) -> None:
        self._apply_to_targets(tag, lambda s: s.card.bow())

    def _cmd_unbow(self, tag: str) -> None:
        self._apply_to_targets(tag, lambda s: s.card.unbow())

    def _cmd_invert(self, tag: str) -> None:
        self._apply_to_targets(tag, lambda s: s.card.invert())

    def _cmd_uninvert(self, tag: str) -> None:
        self._apply_to_targets(tag, lambda s: s.card.uninvert())

    def _cmd_flip_up(self, tag: str) -> None:
        self._apply_to_targets(tag, lambda s: s.card.turn_face_up())

    def _cmd_flip_down(self, tag: str) -> None:
        self._apply_to_targets(tag, lambda s: s.card.turn_face_down())

    # Zone actions
    def _zone_flip_up(self, ztag: str) -> None:
        zv = self._zones.get(ztag)
        if not zv or not zv.zone.cards:
            return
        top = zv.zone.cards[-1]
        top.turn_face_up()
        self._redraw_zone(ztag)

    def _zone_flip_down(self, ztag: str) -> None:
        zv = self._zones.get(ztag)
        if not zv or not zv.zone.cards:
            return
        top = zv.zone.cards[-1]
        top.turn_face_down()
        self._redraw_zone(ztag)

    def _zone_fill(self, ztag: str) -> None:
        zv = self._zones.get(ztag)
        if not zv:
            return
        zone = zv.zone
        if not getattr(zone, "has_capacity", lambda: True)():
            return
        allowed = getattr(zone, "allowed_side", None)
        if allowed is not None and allowed is not Side.DYNASTY:
            return
        deck_tag = self._find_deck_tag_by_side(Side.DYNASTY)
        if not deck_tag:
            return
        dv = self._decks[deck_tag]
        card = dv.deck.draw_one()
        if card is None:
            return
        card.turn_face_down()
        added_ok = True
        try:
            added = zone.add(card)
            if isinstance(added, bool):
                added_ok = added
        except Exception:
            added_ok = True
        if not added_ok:
            dv.deck.add_to_top([card])
            return
        self._redraw_zone(ztag)
        self._redraw_deck(deck_tag)

    def _zone_destroy(self, ztag: str) -> None:
        zv = self._zones.get(ztag)
        if not zv or not isinstance(zv.zone, ProvinceZone):
            return
        zone = zv.zone
        disc_tag = self._find_zone_tag_by_type(DynastyDiscardZone)
        if disc_tag:
            discard_zone = self._zones[disc_tag].zone
            while zone.cards:
                card = zone.cards.pop()
                if not card.face_up:
                    card.turn_face_up()
                discard_zone.add(card)
            self._redraw_zone(disc_tag)
        else:
            while zone.cards:
                card = zone.cards.pop()
                if not card.face_up:
                    card.turn_face_up()
                self.add_card(card, zv.x, zv.y)
        try:
            self.delete(ztag)
        except Exception:
            pass
        self._zones.pop(ztag, None)
        if self._hover_zone_tag == ztag:
            self._hover_zone_tag = None
        if self._context_tag == ztag:
            self._context_tag = None
        provinces: list[tuple[str, ZoneVisual]] = [
            (tag, zv2) for tag, zv2 in self._zones.items() if isinstance(zv2.zone, ProvinceZone)
        ]
        if not provinces:
            return
        provinces.sort(key=lambda item: item[1].x)
        leftmost_x = provinces[0][1].x
        spacing = provinces[0][1].w
        for idx, (ptag, pv) in enumerate(provinces):
            new_x = leftmost_x + idx * spacing
            if pv.x != new_x:
                pv.x = new_x
                self._redraw_zone(ptag)

    # Drop helpers
    def _drop_sprite_into_zone(self, tag: str, zone_tag: str) -> None:
        sprite = self._sprites.get(tag)
        if not sprite:
            return
        zv = self._zones.get(zone_tag)
        if not zv:
            return
        allowed = zv.zone.allowed_side
        if allowed is not None and sprite.card.side is not allowed:
            return
        target_zone = zv.zone
        if not target_zone.has_capacity():
            return
        self._remove_from_all_zones(sprite.card)
        if isinstance(target_zone, HandZone):
            sprite.card.turn_face_down()
        target_zone.add(sprite.card)
        self._remove_card_sprite(tag)
        self._redraw_zone(zone_tag)

    def _drop_sprite_into_deck(self, tag: str, deck_tag: str) -> None:
        sprite = self._sprites.get(tag)
        if not sprite:
            return
        dv = self._decks.get(deck_tag)
        if not dv:
            return
        expected = self._deck_expected_side(dv)
        if expected is not None and sprite.card.side is not expected:
            return
        self._remove_from_all_zones(sprite.card)
        sprite.card.turn_face_down()
        dv.deck.add_to_top([sprite.card])
        self._remove_card_sprite(tag)
        self._redraw_deck(deck_tag)
