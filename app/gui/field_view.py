from collections.abc import Callable
from typing import Literal

import tkinter as tk
from types import MappingProxyType

from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.game_pieces.deck import Deck
from app.gui.constants import (
    CARD_W,
    CARD_H,
    DRAW_OFFSET,
    CANVAS_BG,
)
from app.gui.config import Hotkeys, DEFAULT_HOTKEYS
from app.engine.zones import Zone, HandZone, FateDiscardZone, DynastyDiscardZone, ProvinceZone
from app.gui.images import load_image, load_back_image
from app.gui.visuals import DeckVisual, ZoneVisual, CardSpriteVisual, HandVisual
from app.gui.controller import FieldController


class GameField(tk.Canvas):
    def __init__(self, master: tk.Misc, width: int = 800, height: int = 600):
        super().__init__(master, width=width, height=height, bg=CANVAS_BG, highlightthickness=0)
        self._sprites: dict[str, CardSpriteVisual] = {}
        self._decks: dict[str, DeckVisual] = {}
        self._zones: dict[str, ZoneVisual] = {}
        self._hands: dict[str, HandVisual] = {}
        self._battlefield_zone: Zone | None = None
        self._next_id = 1
        # Draw-only state
        self._hotkeys: Hotkeys = DEFAULT_HOTKEYS
        # Selection (visual only)
        self._selected: set[str] = set()
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_rect: int | None = None

        self._img_cache: dict[str, object] = {}

        self._controller = FieldController(self)
        # Keep focus behavior
        self.bind("<Enter>", lambda e: self.focus_set())

    # Provide selection helpers for controller to call
    def _clear_selection(self) -> None:
        if not self._selected:
            return
        tags = list(self._selected)
        self._selected.clear()
        for t in tags:
            sprite = self._sprites.get(t)
            if sprite:
                sprite.update_selection(self, False)

    def _set_selection(self, tags: set[str]) -> None:
        if tags == self._selected:
            return
        old = self._selected.copy()
        self._selected = set(tags)
        for t in old - self._selected:
            sp = self._sprites.get(t)
            if sp:
                sp.update_selection(self, False)
        for t in self._selected - old:
            sp = self._sprites.get(t)
            if sp:
                sp.update_selection(self, True)

    def _tk_state(self, enabled: bool) -> Literal["normal", "disabled"]:
        return "normal" if enabled else "disabled"

    # Public API for controller ------------------------------------------------
    def resolve_tag_at(self, event: tk.Event) -> str | None:
        return self._resolve_tag_at(event)

    def bbox_for_deck(self, dtag: str) -> tuple[int, int, int, int]:
        dv = self._decks.get(dtag)
        return dv.bbox if dv else (0, 0, -1, -1)

    def bbox_for_zone(self, ztag: str) -> tuple[int, int, int, int]:
        zv = self._zones.get(ztag)
        if zv is not None:
            return zv.bbox
        hv = self._hands.get(ztag)
        return hv.bbox if hv else (0, 0, -1, -1)

    def redraw_deck(self, tag: str) -> None:
        self._redraw_deck(tag)

    def redraw_zone(self, tag: str) -> None:
        self._redraw_zone(tag)

    @property
    def decks(self):
        return MappingProxyType(self._decks)

    @property
    def zones(self):
        return MappingProxyType(self._zones)

    @property
    def hands(self):
        return MappingProxyType(self._hands)

    @property
    def sprites(self):
        return MappingProxyType(self._sprites)

    def remove_card_sprite(self, tag: str) -> None:
        self._remove_card_sprite(tag)

    # -------------------------------------------------------------------------

    def configure_hotkeys(self, hotkeys: Hotkeys) -> None:
        # Delegate to controller so hotkeys are global
        self._hotkeys = hotkeys
        if hasattr(self, "_controller"):
            self._controller.configure_hotkeys(hotkeys)

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
        if isinstance(zone, HandZone):
            hv = HandVisual(zone, x, y, w, h, tag)
            self._hands[tag] = hv
            hv.draw(self)
        else:
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
        if tag in self._zones:
            self._zones[tag].draw(self)
        elif tag in self._hands:
            self._hands[tag].draw(self)

    # Hit-testing helpers
    @staticmethod
    def _bounds_contains(bbox: tuple[int, int, int, int], x: int, y: int) -> bool:
        x0, y0, x1, y1 = bbox
        return x0 <= x <= x1 and y0 <= y <= y1

    def _resolve_drop_target(self, x: int, y: int) -> str | None:
        for tag, hv in self._hands.items():
            if self._bounds_contains(hv.bbox, x, y):
                return tag
        for tag, zv in self._zones.items():
            if self._bounds_contains(zv.bbox, x, y):
                return tag
        for tag, dv in self._decks.items():
            if self._bounds_contains(dv.bbox, x, y):
                return tag
        return None

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

    # Event helpers (hit test)
    def _resolve_tag_at(self, event: tk.Event) -> str | None:
        item = self.find_withtag("current")
        if not item:
            return None
        tags = self.gettags(item[0])
        for t in tags:
            if t.startswith("card:") or t.startswith("deck:") or t.startswith("zone:"):
                return t
        return None

    # Apply helpers for single or selection
    def _apply_to_targets(self, tag: str, apply_fn: Callable[[CardSpriteVisual], None]) -> None:
        targets = self._selected if (self._selected and tag in self._selected) else {tag}
        for t in targets:
            sprite = self._sprites.get(t)
            if not sprite:
                continue
            apply_fn(sprite)
            # Only refresh art/border; selection is updated separately
            sprite.refresh_face_state(self)

    def _apply_to_selection(self, apply_fn: Callable[[CardSpriteVisual], None]) -> None:
        if not self._selected:
            return
        for t in list(self._selected):
            sprite = self._sprites.get(t)
            if not sprite:
                continue
            apply_fn(sprite)
            sprite.refresh_face_state(self)

    # Helpers to find zones/decks
    def _find_zone_tag_by_type(self, zone_type: type[Zone]) -> str | None:
        for tag, zv in self._zones.items():
            if isinstance(zv.zone, zone_type):
                return tag
        for tag, hv in self._hands.items():
            if isinstance(hv.zone, zone_type):
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
        for hv in self._hands.values():
            hv.zone.remove(card)

    def _remove_card_sprite(self, tag: str) -> None:
        sprite = self._sprites.pop(tag, None)
        # Always clean up canvas and state for this tag
        try:
            self.delete(tag)
        except Exception:
            pass
        # Remove from selection
        self._selected.discard(tag)
        if sprite is None:
            return
        self.delete(tag)

    # Send-to commands ------------------------------------------------------
    def _send_card_to_hand(self, tag: str) -> None:
        sprite = self._sprites.get(tag)
        if not sprite:
            return
        zone_tag = self._find_zone_tag_by_type(HandZone)
        if not zone_tag:
            return
        hv = self._hands.get(zone_tag)
        if not hv:
            return
        target_zone = hv.zone
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

    # Context menu commands for cards (kept)
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

    # Zone actions ---------------------------------------------------------
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

    # Drop helpers ---------------------------------------------------------
    def _drop_sprite_into_zone(self, tag: str, zone_tag: str) -> None:
        sprite = self._sprites.get(tag)
        if not sprite:
            return
        # Support both regular zones and hand zones
        zv = self._zones.get(zone_tag)
        hv = self._hands.get(zone_tag)
        target_zone = None
        if zv is not None:
            target_zone = zv.zone
        elif hv is not None:
            target_zone = hv.zone
        if target_zone is None:
            return
        allowed = getattr(target_zone, "allowed_side", None)
        if allowed is not None and sprite.card.side is not allowed:
            return
        if not target_zone.has_capacity():
            return
        self._remove_from_all_zones(sprite.card)
        # Special handling for hand: insert at index and flip face down
        if hv is not None:
            sprite.card.turn_face_down()
            idx = hv.index_at(sprite.x) or len(hv.zone.cards)
            hv.zone.cards.insert(idx, sprite.card)
            self._remove_card_sprite(tag)
            self._redraw_zone(zone_tag)
            return
        # Regular zones
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

    # Deck helpers ---------------------------------------------------------
    def _deck_draw(self, dtag: str) -> None:
        dv = self._decks[dtag]
        card = dv.deck.draw_one()
        if card is None:
            return
        # Fate draws go to hand if present (face up)
        if card.side is Side.FATE:
            hand_tag = self._find_zone_tag_by_type(HandZone)
            if hand_tag:
                card.turn_face_up()
                # HandVisual stored in _hands
                target_zone = self._hands[hand_tag].zone
                target_zone.add(card)
                self._redraw_zone(hand_tag)
                self._redraw_deck(dtag)
                return
        # Otherwise to battlefield near deck, face down
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
        win = tk.Toplevel(self.winfo_toplevel())
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
        win = tk.Toplevel(self.winfo_toplevel())
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
        win = tk.Toplevel(self.winfo_toplevel())
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

    # Context menu commands for cards (kept)
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

    # Zone actions ---------------------------------------------------------
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

    # Drop helpers ---------------------------------------------------------
    def _drop_sprite_into_zone(self, tag: str, zone_tag: str) -> None:
        sprite = self._sprites.get(tag)
        if not sprite:
            return
        # Support both regular zones and hand zones
        zv = self._zones.get(zone_tag)
        hv = self._hands.get(zone_tag)
        target_zone = None
        if zv is not None:
            target_zone = zv.zone
        elif hv is not None:
            target_zone = hv.zone
        if target_zone is None:
            return
        allowed = getattr(target_zone, "allowed_side", None)
        if allowed is not None and sprite.card.side is not allowed:
            return
        if not target_zone.has_capacity():
            return
        self._remove_from_all_zones(sprite.card)
        # Special handling for hand: insert at index and flip face down
        if hv is not None:
            sprite.card.turn_face_down()
            idx = hv.index_at(sprite.x) or len(hv.zone.cards)
            hv.zone.cards.insert(idx, sprite.card)
            self._remove_card_sprite(tag)
            self._redraw_zone(zone_tag)
            return
        # Regular zones
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

    # Deck helpers ---------------------------------------------------------
    def _deck_draw(self, dtag: str) -> None:
        dv = self._decks[dtag]
        card = dv.deck.draw_one()
        if card is None:
            return
        # Fate draws go to hand if present (face up)
        if card.side is Side.FATE:
            hand_tag = self._find_zone_tag_by_type(HandZone)
            if hand_tag:
                card.turn_face_up()
                # HandVisual stored in _hands
                target_zone = self._hands[hand_tag].zone
                target_zone.add(card)
                self._redraw_zone(hand_tag)
                self._redraw_deck(dtag)
                return
        # Otherwise to battlefield near deck, face down
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
        win = tk.Toplevel(self.winfo_toplevel())
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
        win = tk.Toplevel(self.winfo_toplevel())
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
        win = tk.Toplevel(self.winfo_toplevel())
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
