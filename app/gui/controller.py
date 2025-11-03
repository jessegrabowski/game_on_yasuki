import tkinter as tk
from typing import Protocol, Any
from collections.abc import Mapping

from app.game_pieces.cards import L5RCard
from app.engine.zones import HandZone
from app.gui.constants import CARD_W, CARD_H
from app.gui.services.drag import DragKind, Drag
from app.gui.services.hittest import (
    resolve_drop_target as hittest_resolve_drop_target,
    bounds_contains as hittest_bounds_contains,
)
from app.gui.services.permissions import tag_owner, can_interact
from app.gui.visuals import MarqueeBoxVisual
from app.gui.config import Hotkeys, DEFAULT_HOTKEYS
import app.gui.config as gui_config
from app.gui.ui.images import load_image as _li, load_back_image as _lbi
from app.gui.services.actions import (
    build_menu as build_actions_menu,
    REGISTRY as ACTIONS,
    ActionContext,
    HasView,
    FieldActions,
)
from app.engine.players import PlayerId


def _card_in_any_province(view, card) -> bool:
    from app.engine.zones import ProvinceZone

    for _, zv in view.zones.items():
        try:
            if isinstance(zv.zone, ProvinceZone) and card in zv.zone.cards:
                return True
        except Exception:
            pass
    return False


class FieldView(HasView, Protocol):
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

    # Apply redraws from actions
    def apply_redraw(self, rd): ...

    # Exposed collections
    @property
    def decks(self) -> Mapping[str, Any]: ...  # {tag: DeckVisual}

    @property
    def zones(self) -> Mapping[str, Any]: ...  # {tag: ZoneVisual}

    @property
    def hands(self) -> Mapping[str, Any]: ...  # {tag: HandVisual}

    @property
    def sprites(self) -> Mapping[str, Any]: ...  # {tag: CardSpriteVisual}

    # Selection helpers kept in the view (draw-only updates)
    def _set_selection(self, tags: set[str]) -> None: ...
    def _clear_selection(self) -> None: ...

    # Drop helpers (still implemented in the view for now)
    def _drop_sprite_into_zone(self, tag: str, ztag: str) -> None: ...
    def _drop_sprite_into_deck(self, tag: str, dtag: str) -> None: ...

    # Zone helpers used by actions via controller shortcuts
    def _zone_flip_up(self, ztag: str) -> None: ...
    def _zone_flip_down(self, ztag: str) -> None: ...
    def _zone_fill(self, ztag: str) -> None: ...
    def _zone_destroy(self, ztag: str) -> None: ...


class FieldController:
    def __init__(self, view: FieldView) -> None:
        self.view = view
        self.actions = FieldActions(view)
        self.drag: Drag = Drag()
        self._hotkeys: Hotkeys = DEFAULT_HOTKEYS
        # Hover state owned here
        self._hover_card_tag: str | None = None
        self._hover_zone_tag: str | None = None
        self._hover_deck_tag: str | None = None
        # Context menu owned here
        self._context_menu = tk.Menu(None, tearoff=0)
        self._context_tag: str | None = None
        # Marquee state (rectangle drawn by view)
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_rect: int | None = None
        # Visible hand-drag ghost (now rendered as full card image)
        self._hand_ghost_id: int | None = None
        self._hand_ghost_photo: object | None = None
        # Group-drag state: initial positions of selected sprites and mouse
        self._group_drag_init: dict[str, tuple[int, int]] = {}
        self._group_mouse_start: tuple[int, int] | None = None

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
        # Bind Ctrl+T always; handler will check debug flag
        v.bind_all("<Control-t>", self.on_toggle_player)

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

    def _clear_hand_ghost(self) -> None:
        if self._hand_ghost_id is not None:
            try:
                self.view.delete(self._hand_ghost_id)
            except Exception:
                pass
            self._hand_ghost_id = None
        # drop reference to image so Tk can GC
        self._hand_ghost_photo = None

    def _draw_hand_ghost(self, card: L5RCard, x: int, y: int) -> None:
        """Draw the full card art while dragging within the hand.
        Opponent viewing: show back unless card.revealed is True.
        """
        # Remove previous
        self._clear_hand_ghost()
        viewer = getattr(self.view, "local_player", None)
        owner = getattr(card, "owner", None)
        show_front = True
        if (
            owner is not None
            and viewer is not None
            and owner != viewer
            and not getattr(card, "revealed", False)
        ):
            show_front = False
        # Load image
        photo = (
            _li(card.image_front, card.bowed, card.inverted, master=self.view)
            if show_front
            else _lbi(card.side, card.bowed, card.inverted, card.image_back, master=self.view)
        )
        if photo is None:
            # Fallback rectangle with simple outline if image not available
            w, h = (CARD_H, CARD_W) if getattr(card, "bowed", False) else (CARD_W, CARD_H)
            self._hand_ghost_id = self.view.create_rectangle(
                x - w // 2,
                y - h // 2,
                x + w // 2,
                y + h // 2,
                outline="#66ccff",
                dash=(3, 3),
                width=2,
                tags=("hand-ghost",),
            )
            self._hand_ghost_photo = None
            return
        # Keep strong ref to prevent GC
        self._hand_ghost_photo = photo
        self._hand_ghost_id = self.view.create_image(x, y, image=photo, tags=("hand-ghost",))

    def on_press(self, e: tk.Event) -> None:
        self.view.focus_set()
        tag = self.view.resolve_tag_at(e)

        if not tag:
            # background: start marquee and clear selection
            self.view._clear_selection()
            self._start_marquee(e.x, e.y)
            self.drag = Drag()  # no drag yet
            return

        # Determine owner from tag or underlying model
        owner = tag_owner(tag)
        if owner is None:
            if tag.startswith("card:"):
                sp = self.view.sprites.get(tag)
                owner = getattr(sp.card, "owner", None) if sp else None
            elif tag.startswith("deck:"):
                dv = self.view.decks.get(tag)
                owner = getattr(dv, "owner", None) if dv else None
            elif tag.startswith("zone:"):
                zv = self.view.zones.get(tag)
                if zv is not None:
                    owner = getattr(zv.zone, "owner", None)
                else:
                    hv = self.view.hands.get(tag)
                    owner = getattr(hv.zone, "owner", None) if hv else None

        if tag.startswith(("card:", "p1:card", "p2:card")):
            if not can_interact(self.view, owner):
                self.drag = Drag()
                return
            # ensure single selection on press of a new card
            sel = getattr(self.view, "_selected", set())
            if tag not in sel:
                self.view._set_selection({tag})
                sel = {tag}
            # If dragging a selected card and multiple are selected, prepare group-drag
            if sel and tag in sel and len(sel) > 1:
                self._group_drag_init = {}
                for t in sel:
                    sp_sel = self.view.sprites.get(t)
                    if not sp_sel:
                        continue
                    # Only include sprites the local player may interact with
                    if not can_interact(self.view, getattr(sp_sel.card, "owner", None)):
                        continue
                    self._group_drag_init[t] = (sp_sel.x, sp_sel.y)
                self._group_mouse_start = (e.x, e.y)
            else:
                self._group_drag_init = {}
                self._group_mouse_start = None
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
        if tag.startswith(("deck:", "p1:deck", "p2:deck")):
            if not can_interact(self.view, owner):
                self.drag = Drag()
                return
            # arm a deck drag; draw happens when cursor leaves deck bbox
            dv = self.view.decks[tag]
            self.drag = Drag(
                kind=DragKind.DECK_ARMED,
                src_tag=tag,
                src_bbox=dv.bbox,
                offset=(0, 0),
            )
            return
        if tag.startswith(("zone:", "p1:zone", "p2:zone")):
            if not can_interact(self.view, owner):
                self.drag = Drag()
                return

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
                # Draw a simple ghost so the user sees what's being dragged within the hand
                self._draw_hand_ghost(card, e.x, e.y)
                return
            # Other zones: no-op on press for now
            self.drag = Drag()
            return

    def on_motion(self, e: tk.Event) -> None:
        d = self.drag
        if self._marquee_start is not None:
            self._update_marquee(e.x, e.y)
        # Group-drag handling: move all prepared sprites together
        if d.kind is DragKind.CARD and self._group_mouse_start and self._group_drag_init:
            dx = e.x - self._group_mouse_start[0]
            dy = e.y - self._group_mouse_start[1]
            for t, (x0, y0) in self._group_drag_init.items():
                sp = self.view.sprites.get(t)
                if not sp:
                    continue
                sp.move_to(self.view, x0 + dx, y0 + dy)
            return
        # Update hand ghost while dragging within the hand bbox
        if d.kind is DragKind.HAND and d.src_tag and not d.left_source(e.x, e.y) and d.card:
            self._draw_hand_ghost(d.card, e.x, e.y)
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
            # Clear hand ghost and convert to sprite
            self._clear_hand_ghost()
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
        # Group drag support for on_move as well
        if self.drag.kind is DragKind.CARD and self._group_mouse_start and self._group_drag_init:
            dx = e.x - self._group_mouse_start[0]
            dy = e.y - self._group_mouse_start[1]
            for t, (x0, y0) in self._group_drag_init.items():
                sp = self.view.sprites.get(t)
                if not sp:
                    continue
                sp.move_to(self.view, x0 + dx, y0 + dy)
            # No hover/marquee updates while group dragging
            return
        # If dragging from hand and we leave the hand bbox, convert to sprite (some tests use on_move)
        if (
            self.drag.kind is DragKind.HAND
            and self.drag.src_tag
            and self.drag.left_source(e.x, e.y)
            and self.drag.card
        ):
            self._clear_hand_ghost()
            tag = self.view.add_card(self.drag.card, e.x, e.y)
            self.drag = Drag(
                kind=DragKind.CARD,
                src_tag=self.drag.src_tag,
                sprite_tag=tag,
                card=self.drag.card,
                offset=(0, 0),
            )
            return
        if self.drag.kind is DragKind.HAND and self.drag.card and self.drag.src_tag:
            self._draw_hand_ghost(self.drag.card, e.x, e.y)
        # hover and marquee updates when not actively dragging
        self._update_hover(e)
        dragging = self.drag.kind is not DragKind.NONE
        if self._marquee_start is not None and not dragging:
            self._update_marquee(e.x, e.y)
        if self.drag.kind is DragKind.CARD and self.drag.sprite_tag and not self._group_drag_init:
            sp = self.view.sprites.get(self.drag.sprite_tag)
            if sp:
                sp.move_to(self.view, e.x - self.drag.offset[0], e.y - self.drag.offset[1])

    def on_release(self, e: tk.Event) -> None:
        # finish marquee if active
        if self._marquee_start is not None:
            self._end_marquee()
        d = self.drag
        self.drag = Drag()
        # Always clear any hand ghost
        self._clear_hand_ghost()
        # Clear group-drag state
        self._group_drag_init = {}
        self._group_mouse_start = None
        # Hand reinsert
        if d.kind is DragKind.HAND and d.src_tag and d.card:
            hv = self.view.hands.get(d.src_tag)
            if hv and hittest_bounds_contains(hv.bbox, e.x, e.y):
                idx = hv.index_at(e.x) or len(hv.zone.cards)
                hv.zone.cards.insert(idx, d.card)
                self.view.redraw_zone(d.src_tag)
            return
        # Card drop handling (primary sprite)
        if d.kind is DragKind.CARD and d.sprite_tag and d.card:
            sp = self.view.sprites.get(d.sprite_tag)
            if not sp:
                return
            drop = hittest_resolve_drop_target(self.view, sp.x, sp.y)
            if drop and drop.startswith("zone:"):
                rd = self.actions.drop_sprite_into_zone(d.sprite_tag, drop)
                self.view.apply_redraw(rd)
                return
            if drop and drop.startswith("deck:"):
                rd = self.actions.drop_sprite_into_deck(d.sprite_tag, drop)
                self.view.apply_redraw(rd)
                return
            # else leave on battlefield

    def on_double_click(self, e: tk.Event) -> None:
        tag = self.view.resolve_tag_at(e)
        if not tag:
            return

        # deck: draw
        if tag.startswith("deck:"):
            dv = self.view.decks.get(tag)
            owner = getattr(dv, "owner", None) if dv else None
            ctx = ActionContext(deck_tag=tag, event=e, owner=owner)
            act = ACTIONS["deck.draw"]
            if act.when(self.view, ctx):
                rd = FieldActions(self.view).deck_draw(tag)
                self.view.apply_redraw(rd)
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

        # card: toggle bow
        if tag.startswith("card:"):
            sp = self.view.sprites.get(tag)
            if not sp:
                return
            if _card_in_any_province(self.view, sp.card):
                return
            owner = getattr(sp.card, "owner", None)
            ctx = ActionContext(card_tag=tag, event=e, owner=owner)
            act = ACTIONS["card.toggle_bow"]
            if act.when(self.view, ctx):
                act.run(self.view, ctx)
            return

    def on_context(self, e: tk.Event) -> None:
        self.view.focus_set()
        tag = self.view.resolve_tag_at(e)
        if not tag:
            return
        self._context_menu.delete(0, "end")
        self._context_tag = tag
        # derive owner from model object when available
        owner = None
        if tag.startswith("card:"):
            sp = self.view.sprites.get(tag)
            owner = getattr(sp.card, "owner", None) if sp else None
        elif tag.startswith("zone:"):
            zv = self.view.zones.get(tag)
            owner = getattr(zv.zone, "owner", None) if zv else None
        elif tag.startswith("deck:"):
            dv = self.view.decks.get(tag)
            owner = getattr(dv, "owner", None) if dv else None
        ctx = ActionContext(
            card_tag=tag if tag.startswith("card:") else None,
            zone_tag=tag if tag.startswith("zone:") else None,
            deck_tag=tag if tag.startswith("deck:") else None,
            event=e,
            owner=owner,
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
                    state="normal"
                    if ACTIONS["card.toggle_bow"].when(self.view, ctx)
                    else "disabled",
                )
            else:
                self._context_menu.add_command(
                    label=f"Bow ({b})",
                    command=lambda: ACTIONS["card.toggle_bow"].run(self.view, ctx),
                    state="normal"
                    if ACTIONS["card.toggle_bow"].when(self.view, ctx)
                    else "disabled",
                )
            if sp.card.inverted:
                self._context_menu.add_command(
                    label=f"Uninvert ({d})",
                    command=lambda: ACTIONS["card.toggle_invert"].run(self.view, ctx),
                    state="normal"
                    if ACTIONS["card.toggle_invert"].when(self.view, ctx)
                    else "disabled",
                )
            else:
                self._context_menu.add_command(
                    label=f"Invert ({d})",
                    command=lambda: ACTIONS["card.toggle_invert"].run(self.view, ctx),
                    state="normal"
                    if ACTIONS["card.toggle_invert"].when(self.view, ctx)
                    else "disabled",
                )
            if sp.card.face_up:
                self._context_menu.add_command(
                    label=f"Flip Down ({f})",
                    command=lambda: ACTIONS["card.toggle_flip"].run(self.view, ctx),
                    state="normal"
                    if ACTIONS["card.toggle_flip"].when(self.view, ctx)
                    else "disabled",
                )
            else:
                self._context_menu.add_command(
                    label=f"Flip Up ({f})",
                    command=lambda: ACTIONS["card.toggle_flip"].run(self.view, ctx),
                    state="normal"
                    if ACTIONS["card.toggle_flip"].when(self.view, ctx)
                    else "disabled",
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
            # owner derivation should support hand zones as well
            zv = self.view.zones.get(tag)
            if zv is None:
                hv = self.view.hands.get(tag)
                owner = getattr(hv.zone, "owner", None) if hv else None
            else:
                owner = getattr(zv.zone, "owner", None)
            ctx = ActionContext(zone_tag=tag, event=e, owner=owner)
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
                ACTIONS["deck.create_province"],
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
        fa = self.actions

        if keysym == self._hotkeys.flip:
            zv = self.view.zones.get(ztag)
            if zv and zv.zone.cards:
                if zv.zone.cards[-1].face_up:
                    rd = fa.zone_flip_down(ztag)
                else:
                    rd = fa.zone_flip_up(ztag)
                self.view.apply_redraw(rd)

        elif keysym == self._hotkeys.fill:
            rd = fa.zone_fill(ztag)
            self.view.apply_redraw(rd)

        elif keysym == self._hotkeys.destroy:
            rd = fa.zone_destroy(ztag)
            self.view.apply_redraw(rd)

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
            dv = self.view.decks.get(self._hover_deck_tag)
            ctx = ActionContext(
                deck_tag=self._hover_deck_tag,
                event=e,
                owner=(getattr(dv, "owner", None) if dv else None),
            )
            if key == self._hotkeys.draw:
                act = ACTIONS["deck.draw"]
                if act.when(self.view, ctx):
                    act.run(self.view, ctx)
            elif key == self._hotkeys.shuffle:
                act = ACTIONS["deck.shuffle"]
                if act.when(self.view, ctx):
                    act.run(self.view, ctx)
            elif key == self._hotkeys.flip:
                act = ACTIONS["deck.flip_top"]
                if act.when(self.view, ctx):
                    act.run(self.view, ctx)
            elif key == self._hotkeys.inspect:
                act = ACTIONS["deck.inspect"]
                if act.when(self.view, ctx):
                    act.run(self.view, ctx)
            return

        # Zone hotkeys via actions
        if self._hover_zone_tag and key in {
            self._hotkeys.flip,
            self._hotkeys.fill,
            self._hotkeys.destroy,
            self._hotkeys.invert,
        }:
            zv = self.view.zones.get(self._hover_zone_tag)
            ctx = ActionContext(
                zone_tag=self._hover_zone_tag,
                event=e,
                owner=(getattr(zv.zone, "owner", None) if zv else None),
            )
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
        sel = getattr(self.view, "_selected", set())
        target_tag = next(iter(sel)) if sel else self._hover_card_tag
        if not target_tag:
            return
        sp = self.view.sprites.get(target_tag)
        ctx = ActionContext(
            card_tag=target_tag, event=e, owner=(getattr(sp.card, "owner", None) if sp else None)
        )
        if key == self._hotkeys.bow:
            act = ACTIONS["card.toggle_bow"]
            if act.when(self.view, ctx):
                act.run(self.view, ctx)
        elif key == self._hotkeys.flip:
            act = ACTIONS["card.toggle_flip"]
            if act.when(self.view, ctx):
                act.run(self.view, ctx)
        elif key == self._hotkeys.invert:
            act = ACTIONS["card.toggle_invert"]
            if act.when(self.view, ctx):
                act.run(self.view, ctx)

    def on_toggle_player(self, e: tk.Event) -> None:
        """Toggle the active local player between P1 and P2 (debug only)."""
        if not getattr(gui_config, "DEBUG_MODE", False):
            return
        cur = getattr(self.view, "local_player", None)
        if cur == PlayerId.P1:
            self.view.local_player = PlayerId.P2
            # rotate so P2 appears on bottom
            if hasattr(self.view, "flip_orientation"):
                self.view.flip_orientation()
        else:
            self.view.local_player = PlayerId.P1
            # rotate back so P1 appears on bottom
            if hasattr(self.view, "flip_orientation"):
                self.view.flip_orientation()
        # Inform UI about local player change (restack panels, update gating)
        cb = getattr(self.view, "on_local_player_changed", None)
        if callable(cb):
            try:
                cb()
                # Force idle update so panel re-pack happens immediately
                try:
                    self.view.winfo_toplevel().update_idletasks()
                except Exception:
                    pass
            except Exception:
                pass
        # After switching perspective, redraw everything to update private views
        if hasattr(self.view, "redraw_all"):
            try:
                self.view.redraw_all()
            except Exception:
                for z in list(self.view.zones.keys()):
                    self.view.redraw_zone(z)
                for h in list(self.view.hands.keys()):
                    self.view.redraw_zone(h)
                for d in list(self.view.decks.keys()):
                    self.view.redraw_deck(d)
