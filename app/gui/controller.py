import tkinter as tk
from typing import Protocol, Any

from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.engine.zones import HandZone
from app.gui.constants import CARD_W, CARD_H, DRAW_OFFSET
from app.gui.move_objects import DragKind, Drag
from app.gui.visuals import MarqueeBoxVisual
from app.gui.config import Hotkeys, DEFAULT_HOTKEYS
from app.gui.actions import build_menu as build_actions_menu, REGISTRY as ACTIONS, ActionContext


class FieldView(Protocol):
    # Event binding and focus
    def bind(self, sequence: str, func): ...
    def bind_all(self, sequence: str, func): ...
    def unbind_all(self, sequence: str): ...
    def focus_set(self) -> None: ...

    # Hit resolution
    def resolve_tag_at(self, event: tk.Event) -> str | None: ...

    # Drawing primitives (for marquee)
    def create_rectangle(self, *args, **kwargs): ...
    def coords(self, *args, **kwargs): ...
    def itemconfig(self, *args, **kwargs): ...
    def tag_raise(self, *args, **kwargs): ...
    def delete(self, *args, **kwargs): ...

    # Geometry helpers
    def bbox_for_deck(self, dtag: str) -> tuple[int, int, int, int]: ...
    def bbox_for_zone(self, ztag: str) -> tuple[int, int, int, int]: ...

    # Visual/model APIs
    def add_card(self, card: L5RCard, x: int, y: int) -> str: ...
    def redraw_deck(self, dtag: str) -> None: ...
    def redraw_zone(self, ztag: str) -> None: ...

    # Exposed collections
    @property
    def decks(self) -> dict[str, Any]: ...  # {tag: DeckVisual}

    @property
    def zones(self) -> dict[str, Any]: ...  # {tag: ZoneVisual}

    @property
    def hands(self) -> dict[str, Any]: ...  # {tag: HandVisual}

    @property
    def sprites(self) -> dict[str, Any]: ...  # {tag: CardSpriteVisual}

    # Selection helpers kept in the view (draw-only updates)
    def _set_selection(self, tags: set[str]) -> None: ...
    def _clear_selection(self) -> None: ...

    # Drop helpers (still implemented in the view for now)
    def _drop_sprite_into_zone(self, tag: str, ztag: str) -> None: ...
    def _drop_sprite_into_deck(self, tag: str, dtag: str) -> None: ...


class FieldController:
    def __init__(self, view: FieldView) -> None:
        self.view = view
        self.drag: Drag = Drag()
        self._hotkeys: Hotkeys = DEFAULT_HOTKEYS
        # Hover state owned here
        self._hover_card_tag: str | None = None
        self._hover_zone_tag: str | None = None
        self._hover_deck_tag: str | None = None
        # Context menu owned here
        self._context_menu = tk.Menu(self.view, tearoff=0)
        self._context_tag: str | None = None
        # Marquee state (rectangle drawn by view)
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_rect: int | None = None

        # Bind events to controller
        v = self.view
        v.bind("<Button-1>", self.on_press)
        v.bind("<B1-Motion>", self.on_motion)
        v.bind("<Motion>", self.on_move)
        v.bind("<ButtonRelease-1>", self.on_release)
        v.bind("<Double-Button-1>", self.on_double_click)
        v.bind("<Button-2>", self.on_context)
        v.bind("<Button-3>", self.on_context)
        v.bind("<Control-Button-1>", self.on_context)
        v.bind("<KeyPress-Escape>", self.on_escape)

    # Public: allow view to pass through hotkey configuration
    def configure_hotkeys(self, hotkeys: Hotkeys) -> None:
        # Unbind previous
        for key in {
            self._hotkeys.bow,
            self._hotkeys.flip,
            self._hotkeys.invert,
            self._hotkeys.fill,
            self._hotkeys.destroy,
            self._hotkeys.draw,
            self._hotkeys.shuffle,
            self._hotkeys.inspect,
        }:
            if key:
                try:
                    self.view.unbind_all(f"<KeyPress-{key}>")
                except Exception:
                    pass
        self._hotkeys = hotkeys
        # Bind new
        keys = {
            hotkeys.bow,
            hotkeys.flip,
            hotkeys.invert,
            hotkeys.fill,
            hotkeys.destroy,
            hotkeys.draw,
            hotkeys.shuffle,
            hotkeys.inspect,
        }
        for k in {k for k in keys if k}:
            self.view.bind_all(f"<KeyPress-{k}>", self.on_key)

    # Internal helpers -----------------------------------------------------
    @staticmethod
    def _contains(bbox: tuple[int, int, int, int], x: int, y: int) -> bool:
        x0, y0, x1, y1 = bbox
        return x0 <= x <= x1 and y0 <= y <= y1

    def _resolve_drop_target(self, x: int, y: int) -> str | None:
        # prefer zones/hands, then decks
        for ztag, zv in {**self.view.hands, **self.view.zones}.items():
            if self._contains(zv.bbox, x, y):
                return ztag
        for dtag, dv in self.view.decks.items():
            if self._contains(dv.bbox, x, y):
                return dtag
        return None

    def _update_hover(self, e: tk.Event) -> None:
        tag = self.view.resolve_tag_at(e)
        self._hover_card_tag = tag if tag and tag.startswith("card:") else None
        self._hover_zone_tag = tag if tag and tag.startswith("zone:") else None
        self._hover_deck_tag = tag if tag and tag.startswith("deck:") else None

    def _start_marquee(self, x: int, y: int) -> None:
        self._marquee_start = (x, y)
        if self._marquee_rect is None:
            self._marquee_rect = self.view.create_rectangle(
                x, y, x, y, outline="#66ccff", width=2, dash=(4, 2), tags=("marquee",)
            )
        else:
            self.view.coords(self._marquee_rect, x, y, x, y)
            self.view.itemconfig(self._marquee_rect, outline="#66ccff", width=2, dash=(4, 2))
        self.view.tag_raise(self._marquee_rect)

    def _update_marquee(self, x: int, y: int) -> None:
        if self._marquee_start is None or self._marquee_rect is None:
            return
        x0, y0 = self._marquee_start
        self.view.coords(self._marquee_rect, x0, y0, x, y)
        self.view.tag_raise(self._marquee_rect)
        sel_rect = (min(x0, x), min(y0, y), max(x0, x), max(y0, y))
        rect_visual = MarqueeBoxVisual(sel_rect)
        new_sel: set[str] = set()
        for tag, sprite in self.view.sprites.items():
            if sprite.intersects(rect_visual):
                new_sel.add(tag)
        self.view._set_selection(new_sel)

    def _end_marquee(self) -> None:
        self._marquee_start = None
        if self._marquee_rect is not None:
            try:
                self.view.delete(self._marquee_rect)
            except Exception:
                pass
            self._marquee_rect = None

    # Event handlers -------------------------------------------------------
    def on_press(self, e: tk.Event) -> None:
        self.view.focus_set()
        tag = self.view.resolve_tag_at(e)
        if not tag:
            # background: start marquee and clear selection
            self.view._clear_selection()
            self._start_marquee(e.x, e.y)
            self.drag = Drag()  # no drag yet
            return
        if tag.startswith("card:"):
            # ensure single selection on press of a new card
            sel = getattr(self.view, "_selected", set())
            if tag not in sel:
                self.view._set_selection({tag})
            sp = self.view.sprites.get(tag)
            if sp:
                self.drag = Drag(
                    kind=DragKind.CARD,
                    src_tag=tag,
                    sprite_tag=tag,
                    card=sp.card,
                    offset=(e.x - sp.x, e.y - sp.y),
                )
            return
        if tag.startswith("deck:"):
            # arm a deck drag; draw happens when cursor leaves deck bbox
            dv = self.view.decks[tag]
            self.drag = Drag(
                kind=DragKind.DECK_ARMED,
                src_tag=tag,
                src_bbox=dv.bbox,
                offset=(0, 0),
            )
            return
        if tag.startswith("zone:"):
            # If hand zone: prepare for reordering/drag-out
            hv = self.view.hands.get(tag)
            if hv is not None and isinstance(hv.zone, HandZone):
                idx = hv.index_at(e.x)
                if idx is None or idx >= len(hv.zone.cards):
                    return
                card = hv.zone.cards.pop(idx)
                self.view.redraw_zone(tag)
                self.drag = Drag(
                    kind=DragKind.HAND,
                    src_tag=tag,
                    card=card,
                    src_bbox=hv.bbox,
                    hand_origin_index=idx,
                    offset=(CARD_W // 2, CARD_H // 2),  # center offset for ghost/sprite
                )
                return
            # Other zones: no-op on press for now
            self.drag = Drag()
            return

    def on_motion(self, e: tk.Event) -> None:
        d = self.drag
        # Deck: convert to sprite once cursor leaves deck bbox
        if d.kind is DragKind.DECK_ARMED and d.src_tag and d.left_source(e.x, e.y):
            dv = self.view.decks[d.src_tag]
            card = dv.deck.draw_one()
            if card is None:
                self.drag = Drag()
                return
            card.turn_face_down()
            # start a card sprite at current location
            tag = self.view.add_card(card, e.x, e.y)
            self.view.redraw_deck(d.src_tag)
            self.drag = Drag(
                kind=DragKind.CARD,
                src_tag=d.src_tag,
                sprite_tag=tag,
                card=card,
                offset=(0, 0),
            )
            return
        # Hand drag: if leaves hand bbox, convert to battlefield sprite
        if d.kind is DragKind.HAND and d.src_tag and d.left_source(e.x, e.y) and d.card:
            tag = self.view.add_card(d.card, e.x, e.y)
            self.drag = Drag(
                kind=DragKind.CARD,
                src_tag=d.src_tag,
                sprite_tag=tag,
                card=d.card,
                offset=(0, 0),
            )
            return
        # Move sprite visually
        if d.kind in (DragKind.CARD,) and d.sprite_tag:
            sp = self.view.sprites.get(d.sprite_tag)
            if sp:
                sp.move_to(self.view, e.x - d.offset[0], e.y - d.offset[1])

    def on_move(self, e: tk.Event) -> None:
        # If dragging from hand and we leave the hand bbox, convert to sprite (some tests use on_move)
        if (
            self.drag.kind is DragKind.HAND
            and self.drag.src_tag
            and self.drag.left_source(e.x, e.y)
            and self.drag.card
        ):
            tag = self.view.add_card(self.drag.card, e.x, e.y)
            self.drag = Drag(
                kind=DragKind.CARD,
                src_tag=self.drag.src_tag,
                sprite_tag=tag,
                card=self.drag.card,
                offset=(0, 0),
            )
            return
        # hover and marquee updates when not actively dragging
        self._update_hover(e)
        dragging = self.drag.kind is not DragKind.NONE
        if self._marquee_start is not None and not dragging:
            self._update_marquee(e.x, e.y)
        # in tests some drags use move instead of motion to update visuals
        if self.drag.kind is DragKind.CARD and self.drag.sprite_tag:
            sp = self.view.sprites.get(self.drag.sprite_tag)
            if sp:
                sp.move_to(self.view, e.x - self.drag.offset[0], e.y - self.drag.offset[1])

    def on_release(self, e: tk.Event) -> None:
        # finish marquee if active
        if self._marquee_start is not None:
            self._end_marquee()
        d = self.drag
        self.drag = Drag()
        # Hand reinsert
        if d.kind is DragKind.HAND and d.src_tag and d.card:
            hv = self.view.hands.get(d.src_tag)
            if hv and self._contains(hv.bbox, e.x, e.y):
                idx = hv.index_at(e.x) or len(hv.zone.cards)
                hv.zone.cards.insert(idx, d.card)
                self.view.redraw_zone(d.src_tag)
            return
        # Card drop handling
        if d.kind is DragKind.CARD and d.sprite_tag and d.card:
            sp = self.view.sprites.get(d.sprite_tag)
            if not sp:
                return
            drop = self._resolve_drop_target(sp.x, sp.y)
            if drop and drop.startswith("zone:"):
                self.view._drop_sprite_into_zone(d.sprite_tag, drop)
                return
            if drop and drop.startswith("deck:"):
                self.view._drop_sprite_into_deck(d.sprite_tag, drop)
                return
            # else leave on battlefield

    def on_double_click(self, e: tk.Event) -> None:
        tag = self.view.resolve_tag_at(e)
        if not tag:
            return
        # deck: draw
        if tag.startswith("deck:"):
            dv = self.view.decks[tag]
            card = dv.deck.draw_one()
            if card is None:
                return
            if card.side is Side.FATE:
                # fate -> hand if present, face up
                for htag, hv in self.view.hands.items():
                    if isinstance(hv.zone, HandZone):
                        card.turn_face_up()
                        hv.zone.add(card)
                        self.view.redraw_zone(htag)
                        self.view.redraw_deck(tag)
                        return
            # else to battlefield near deck, face down
            card.turn_face_down()
            offset = CARD_W + DRAW_OFFSET
            draw_x = dv.x - offset if card.side is Side.FATE else dv.x + offset
            draw_y = dv.y
            self.view.add_card(card, draw_x, draw_y)
            self.view.redraw_deck(tag)
            return
        # zone: move top card to battlefield (except hand)
        if tag.startswith("zone:"):
            zv = self.view.zones.get(tag)
            if zv is None or isinstance(zv.zone, HandZone) or not zv.zone.cards:
                return
            card = zv.zone.cards.pop()
            self.view.add_card(card, zv.x, zv.y)
            self.view.redraw_zone(tag)
            return
        # card: toggle bow on selected-or-self
        if tag.startswith("card:"):
            sel = getattr(self.view, "_selected", set())
            targets = sel if (sel and tag in sel) else {tag}
            for t in targets:
                sp = self.view.sprites.get(t)
                if not sp:
                    continue
                if sp.card.bowed:
                    sp.card.unbow()
                else:
                    sp.card.bow()
                sp.refresh_face_state(self.view)

    def on_context(self, e: tk.Event) -> None:
        self.view.focus_set()
        tag = self.view.resolve_tag_at(e)
        if not tag:
            return
        self._context_menu.delete(0, "end")
        self._context_tag = tag
        ctx = ActionContext(
            card_tag=tag if tag.startswith("card:") else None,
            zone_tag=tag if tag.startswith("zone:") else None,
            deck_tag=tag if tag.startswith("deck:") else None,
            event=e,
        )
        if tag.startswith("card:"):
            # ensure single selection on right-click if not part of selection
            sel = getattr(self.view, "_selected", set())
            if tag not in sel:
                self.view._set_selection({tag})
            sp = self.view.sprites[tag]
            # Dynamic labels with hotkeys
            b = self._hotkeys.bow
            f = self._hotkeys.flip
            d = self._hotkeys.invert
            if sp.card.bowed:
                self._context_menu.add_command(
                    label=f"Unbow ({b})",
                    command=lambda: ACTIONS["card.toggle_bow"].run(self.view, ctx),
                )
            else:
                self._context_menu.add_command(
                    label=f"Bow ({b})",
                    command=lambda: ACTIONS["card.toggle_bow"].run(self.view, ctx),
                )
            if sp.card.inverted:
                self._context_menu.add_command(
                    label=f"Uninvert ({d})",
                    command=lambda: ACTIONS["card.toggle_invert"].run(self.view, ctx),
                )
            else:
                self._context_menu.add_command(
                    label=f"Invert ({d})",
                    command=lambda: ACTIONS["card.toggle_invert"].run(self.view, ctx),
                )
            if sp.card.face_up:
                self._context_menu.add_command(
                    label=f"Flip Down ({f})",
                    command=lambda: ACTIONS["card.toggle_flip"].run(self.view, ctx),
                )
            else:
                self._context_menu.add_command(
                    label=f"Flip Up ({f})",
                    command=lambda: ACTIONS["card.toggle_flip"].run(self.view, ctx),
                )
            # Send to submenu using actions
            send_menu = tk.Menu(self._context_menu, tearoff=0)
            send_actions = [
                ACTIONS["card.send_hand"],
                ACTIONS["card.send_fate_disc"],
                ACTIONS["card.send_dynasty_disc"],
                ACTIONS["card.send_deck_top"],
                ACTIONS["card.send_deck_bottom"],
            ]
            build_actions_menu(send_menu, self.view, ctx, send_actions)
            self._context_menu.add_cascade(label="Send to", menu=send_menu)
        elif tag.startswith("zone:"):
            actions = [
                ACTIONS["zone.toggle_flip"],
                ACTIONS["zone.fill"],
                ACTIONS["zone.destroy"],
                ACTIONS["zone.discard"],
            ]
            build_actions_menu(self._context_menu, self.view, ctx, actions)
        elif tag.startswith("deck:"):
            actions = [
                ACTIONS["deck.draw"],
                ACTIONS["deck.shuffle"],
                ACTIONS["deck.flip_top"],
                ACTIONS["deck.inspect"],
            ]
            build_actions_menu(self._context_menu, self.view, ctx, actions)
        try:
            self._context_menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._context_menu.grab_release()
            self._context_tag = None

    def _shortcut_card(self, keysym: str) -> None:
        # Simulate key press for card actions on context
        self.on_key(type("E", (), {"keysym": keysym})())  # simple event-like

    def _zone_shortcut(self, ztag: str, keysym: str) -> None:
        if keysym == self._hotkeys.flip:
            zv = self.view.zones.get(ztag)
            if zv and zv.zone.cards:
                if zv.zone.cards[-1].face_up:
                    self.view._zone_flip_down(ztag)
                else:
                    self.view._zone_flip_up(ztag)
        elif keysym == self._hotkeys.fill:
            self.view._zone_fill(ztag)
        elif keysym == self._hotkeys.destroy:
            self.view._zone_destroy(ztag)

    def on_escape(self, e: tk.Event) -> None:
        self.view._clear_selection()

    def on_key(self, e: tk.Event) -> None:
        key = getattr(e, "keysym", "").lower()
        # Deck hotkeys via actions
        if self._hover_deck_tag and key in {
            self._hotkeys.draw,
            self._hotkeys.shuffle,
            self._hotkeys.flip,
            self._hotkeys.inspect,
        }:
            ctx = ActionContext(deck_tag=self._hover_deck_tag, event=e)
            if key == self._hotkeys.draw:
                ACTIONS["deck.draw"].run(self.view, ctx)
            elif key == self._hotkeys.shuffle:
                ACTIONS["deck.shuffle"].run(self.view, ctx)
            elif key == self._hotkeys.flip:
                ACTIONS["deck.flip_top"].run(self.view, ctx)
            elif key == self._hotkeys.inspect:
                ACTIONS["deck.inspect"].run(self.view, ctx)
            return
        # Zone hotkeys via actions
        if self._hover_zone_tag and key in {
            self._hotkeys.flip,
            self._hotkeys.fill,
            self._hotkeys.destroy,
            self._hotkeys.invert,
        }:
            ctx = ActionContext(zone_tag=self._hover_zone_tag, event=e)
            if key == self._hotkeys.flip:
                act = ACTIONS["zone.toggle_flip"]
                if act.when(self.view, ctx):
                    act.run(self.view, ctx)
            elif key == self._hotkeys.fill:
                act = ACTIONS["zone.fill"]
                if act.when(self.view, ctx):
                    act.run(self.view, ctx)
            elif key == self._hotkeys.destroy:
                act = ACTIONS["zone.destroy"]
                if act.when(self.view, ctx):
                    act.run(self.view, ctx)
            elif key == self._hotkeys.invert:
                act = ACTIONS["zone.discard"]
                if act.when(self.view, ctx):
                    act.run(self.view, ctx)
            return

        # Card hotkeys (selection or hovered)
        def _apply_to_targets(fn):
            sel = getattr(self.view, "_selected", set())
            targets = sel if sel else ({self._hover_card_tag} if self._hover_card_tag else set())
            for t in list(targets):
                ctx = ActionContext(card_tag=t, event=e)
                fn(ctx)

        if key == self._hotkeys.bow:
            _apply_to_targets(lambda ctx: ACTIONS["card.toggle_bow"].run(self.view, ctx))
        elif key == self._hotkeys.flip:
            _apply_to_targets(lambda ctx: ACTIONS["card.toggle_flip"].run(self.view, ctx))
        elif key == self._hotkeys.invert:
            _apply_to_targets(lambda ctx: ACTIONS["card.toggle_invert"].run(self.view, ctx))
