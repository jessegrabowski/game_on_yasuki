import tkinter as tk

import yasuki_gui.config as gui_config
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BATTLEFIELD, ZoneKey, ZoneRole
from yasuki_core.engine.intents import (
    Event,
    MoveCard,
    ReorderHand,
    SetCardPos,
    SetCardPositions,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_gui import theme
from yasuki_gui.config import DEFAULT_HOTKEYS, Hotkeys
from yasuki_gui.constants import CARD_H, CARD_W
from yasuki_gui.services.actions import (
    REGISTRY as ACTIONS,
    ActionContext,
    build_menu as build_actions_menu,
)
from yasuki_gui.services.drag import Drag, DragKind
from yasuki_gui.services.hittest import (
    bounds_contains as hittest_bounds_contains,
    resolve_drop_target as hittest_resolve_drop_target,
)
from yasuki_gui.services.permissions import can_interact
from yasuki_gui.tags import card_tag
from yasuki_gui.ui.images import load_back_image as _lbi, load_image as _li
from yasuki_gui.visuals import MarqueeBoxVisual


class FieldController:
    def __init__(self, view) -> None:
        self.view = view
        self.drag: Drag = Drag()
        self._hotkeys: Hotkeys = DEFAULT_HOTKEYS
        self._hover_card_tag: str | None = None
        self._hover_zone_tag: str | None = None
        self._context_menu = tk.Menu(None, tearoff=0)
        self._context_tag: str | None = None
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_rect: int | None = None
        self._hand_ghost_id: int | None = None
        self._hand_ghost_photo: object | None = None
        self._group_drag_init: dict[str, tuple[int, int]] = {}
        self._group_mouse_start: tuple[int, int] | None = None

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
        v.bind_all("<Control-t>", self.on_toggle_player)

    def configure_hotkeys(self, hotkeys: Hotkeys) -> None:
        old = {
            self._hotkeys.bow,
            self._hotkeys.flip,
            self._hotkeys.invert,
            self._hotkeys.fill,
            self._hotkeys.destroy,
            self._hotkeys.draw,
            self._hotkeys.shuffle,
            self._hotkeys.inspect,
        }
        for key in {k for k in old if k}:
            try:
                self.view.unbind_all(f"<KeyPress-{key}>")
            except tk.TclError:
                pass
        self._hotkeys = hotkeys
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

    # ----- helpers ----------------------------------------------------------

    def _owner_of(self, tag: str) -> PlayerId | None:
        if tag.startswith("card:"):
            sp = self.view.sprites.get(tag)
            return sp.card.owner if sp else None
        key = self.view.key_for_tag(tag)
        return key.owner if key is not None else None

    def _from_canvas(self, x: int, y: int):
        return self.view.canonical_pos(x, y)

    def _update_hover(self, e: tk.Event) -> None:
        tag = self.view.resolve_tag_at(e)
        self._hover_card_tag = tag if tag and tag.startswith("card:") else None
        self._hover_zone_tag = tag if tag and tag.startswith("zone:") else None

    def _start_marquee(self, x: int, y: int) -> None:
        self._marquee_start = (x, y)
        if self._marquee_rect is None:
            self._marquee_rect = self.view.create_rectangle(
                x, y, x, y, outline=theme.SELECT, width=2, dash=(4, 2), tags=("marquee",)
            )
        else:
            self.view.coords(self._marquee_rect, x, y, x, y)
            self.view.itemconfig(self._marquee_rect, outline=theme.SELECT, width=2, dash=(4, 2))
        self.view.tag_raise(self._marquee_rect)

    def _update_marquee(self, x: int, y: int) -> None:
        if self._marquee_start is None or self._marquee_rect is None:
            return
        x0, y0 = self._marquee_start
        self.view.coords(self._marquee_rect, x0, y0, x, y)
        self.view.tag_raise(self._marquee_rect)
        rect_visual = MarqueeBoxVisual((min(x0, x), min(y0, y), max(x0, x), max(y0, y)))
        new_sel = {tag for tag, sp in self.view.sprites.items() if sp.intersects(rect_visual)}
        self.view._set_selection(new_sel)

    def _end_marquee(self) -> None:
        self._marquee_start = None
        if self._marquee_rect is not None:
            self.view.delete(self._marquee_rect)
            self._marquee_rect = None

    def _clear_hand_ghost(self) -> None:
        if self._hand_ghost_id is not None:
            self.view.delete(self._hand_ghost_id)
            self._hand_ghost_id = None
        self._hand_ghost_photo = None

    def _draw_hand_ghost(self, card: L5RCard, x: int, y: int) -> None:
        self._clear_hand_ghost()
        viewer = self.view.seat
        owner = card.owner
        show_front = not (owner is not None and owner != viewer and not card.shown)
        photo = (
            _li(card.image_front, card.bowed, card.inverted, master=self.view)
            if show_front
            else _lbi(card.side, card.bowed, card.inverted, card.image_back, master=self.view)
        )
        if photo is None:
            w, h = (CARD_H, CARD_W) if card.bowed else (CARD_W, CARD_H)
            self._hand_ghost_id = self.view.create_rectangle(
                x - w // 2,
                y - h // 2,
                x + w // 2,
                y + h // 2,
                outline=theme.SELECT,
                dash=(3, 3),
                width=2,
                tags=("hand-ghost",),
            )
            return
        self._hand_ghost_photo = photo
        self._hand_ghost_id = self.view.create_image(x, y, image=photo, tags=("hand-ghost",))

    # ----- press / motion / release -----------------------------------------

    def _toggle_selection_at(self, tag: str | None, e: tk.Event) -> None:
        """While the engine awaits a choice, a click on a candidate card toggles its selection
        (the field ignores non-candidates); clicks elsewhere do nothing."""
        card_id = self._card_at(tag, e)
        if card_id is not None:
            self.view.toggle_selection(card_id)

    def _card_at(self, tag: str | None, e: tk.Event) -> str | None:
        """The id of the card clicked — a battlefield sprite, one of your own hand cards, or the
        card in one of your own provinces."""
        if not tag:
            return None
        if tag.startswith("card:"):
            return self.view.card_id_for_tag(tag)
        if tag.startswith("zone:"):
            hv = self.view.hands.get(tag)
            if hv is not None:
                if hv.owner is not self.view.seat:
                    return None
                idx = hv.index_at(e.x)
                if idx is None or idx >= len(hv.cards):
                    return None
                return hv.cards[idx].id
            return self._province_card_at(tag)
        return None

    def _province_card_at(self, tag: str) -> str | None:
        """The id of the card in your own province ``tag``, or None if it is not your province or is
        empty."""
        key = self.view.key_for_tag(tag)
        if not isinstance(key, ZoneKey) or key.role is not ZoneRole.PROVINCE:
            return None
        if key.owner is not self.view.seat:
            return None
        zv = self.view.zones.get(tag)
        return zv.cards[-1].id if zv is not None and zv.cards else None

    def _activate_card_at(self, tag: str | None, e: tk.Event) -> None:
        """In rules mode, a click on a card invokes the action it offers (e.g. recruit a holding);
        the host resolves which action that card offers."""
        card_id = self._card_at(tag, e)
        if card_id is not None and self.view.on_card_activated is not None:
            self.view.on_card_activated(card_id)

    def on_press(self, e: tk.Event) -> None:
        self.view.focus_set()
        tag = self.view.resolve_tag_at(e)
        if self.view.selecting:
            self._toggle_selection_at(tag, e)
            return
        if self.view.rules_mode:
            self._activate_card_at(tag, e)
            return
        if not tag:
            self.view._clear_selection()
            self._start_marquee(e.x, e.y)
            self.drag = Drag()
            return

        owner = self._owner_of(tag)
        if not can_interact(self.view, owner):
            self.drag = Drag()
            return

        if tag.startswith("card:"):
            sel = getattr(self.view, "_selected", set())
            if tag not in sel:
                self.view._set_selection({tag})
                sel = {tag}
            if len(sel) > 1:
                self._group_drag_init = {
                    t: (sp.x, sp.y)
                    for t in sel
                    if (sp := self.view.sprites.get(t)) and can_interact(self.view, sp.card.owner)
                }
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

        if tag.startswith("zone:"):
            hv = self.view.hands.get(tag)
            if hv is not None:
                idx = hv.index_at(e.x)
                if idx is None or idx >= len(hv.cards):
                    return
                card = hv.cards[idx]
                self.drag = Drag(
                    kind=DragKind.HAND,
                    src_tag=tag,
                    card=card,
                    src_bbox=hv.bbox,
                    hand_origin_index=idx,
                    offset=(CARD_W // 2, CARD_H // 2),
                )
                self._draw_hand_ghost(card, e.x, e.y)
            return

    def on_motion(self, e: tk.Event) -> None:
        d = self.drag
        if self._marquee_start is not None:
            self._update_marquee(e.x, e.y)
        if d.kind is DragKind.CARD and self._group_mouse_start and self._group_drag_init:
            self._drag_group(e)
            return
        if d.kind is DragKind.HAND and d.src_tag and d.card:
            if d.left_source(e.x, e.y):
                self._lift_hand_card_to_battlefield(e)
            else:
                self._draw_hand_ghost(d.card, e.x, e.y)
            return
        if d.kind is DragKind.CARD and d.sprite_tag:
            sp = self.view.sprites.get(d.sprite_tag)
            if sp:
                sp.move_to(self.view, e.x - d.offset[0], e.y - d.offset[1])

    def on_move(self, e: tk.Event) -> None:
        d = self.drag
        if d.kind is DragKind.CARD and self._group_mouse_start and self._group_drag_init:
            self._drag_group(e)
            return
        if d.kind is DragKind.HAND and d.src_tag and d.card:
            if d.left_source(e.x, e.y):
                self._lift_hand_card_to_battlefield(e)
            else:
                self._draw_hand_ghost(d.card, e.x, e.y)
            return
        self._update_hover(e)
        if self._marquee_start is not None and d.kind is DragKind.NONE:
            self._update_marquee(e.x, e.y)
        if d.kind is DragKind.CARD and d.sprite_tag and not self._group_drag_init:
            sp = self.view.sprites.get(d.sprite_tag)
            if sp:
                sp.move_to(self.view, e.x - d.offset[0], e.y - d.offset[1])

    def _drag_group(self, e: tk.Event) -> None:
        dx = e.x - self._group_mouse_start[0]
        dy = e.y - self._group_mouse_start[1]
        for t, (x0, y0) in self._group_drag_init.items():
            sp = self.view.sprites.get(t)
            if sp:
                sp.move_to(self.view, x0 + dx, y0 + dy)

    def _lift_hand_card_to_battlefield(self, e: tk.Event) -> None:
        self._clear_hand_ghost()
        card = self.drag.card
        events = self.view.dispatch(
            MoveCard(card.id, BATTLEFIELD, position=self._from_canvas(e.x, e.y))
        )
        self.drag = self._grab_moved_sprite(events)

    def _grab_moved_sprite(self, events: list[Event]) -> Drag:
        """Pick up the sprite a hand drag-out just created so the gesture keeps dragging it."""
        for event in events:
            intent = event.intent
            if isinstance(intent, MoveCard) and intent.to == BATTLEFIELD:
                tag = card_tag(intent.card_id)
                sp = self.view.sprites.get(tag)
                if sp:
                    return Drag(kind=DragKind.CARD, src_tag=tag, sprite_tag=tag, card=sp.card)
        return Drag()

    def on_release(self, e: tk.Event) -> None:
        if self._marquee_start is not None:
            self._end_marquee()
        d = self.drag
        self.drag = Drag()
        self._clear_hand_ghost()
        group_init = self._group_drag_init
        self._group_drag_init = {}
        self._group_mouse_start = None

        if d.kind is DragKind.HAND and d.src_tag and d.card:
            hv = self.view.hands.get(d.src_tag)
            if hv and hittest_bounds_contains(hv.bbox, e.x, e.y):
                idx = hv.index_at(e.x)
                if idx is None:
                    idx = len(hv.cards)
                self.view.dispatch(ReorderHand(d.card.id, idx))
            return

        if d.kind is not DragKind.CARD or not d.sprite_tag:
            return
        sp = self.view.sprites.get(d.sprite_tag)
        if not sp:
            return
        if group_init:
            moves = tuple(
                (self.view.card_id_for_tag(t), *self._from_canvas(s.x, s.y))
                for t in group_init
                if (s := self.view.sprites.get(t))
            )
            self.view.dispatch(SetCardPositions(moves))
            return
        drop = hittest_resolve_drop_target(self.view, sp.x, sp.y)
        key = self.view.key_for_tag(drop) if drop else None
        if isinstance(key, ZoneKey):
            self.view.dispatch(MoveCard(d.card.id, key))
            return
        pos = self._from_canvas(sp.x, sp.y)
        self.view.dispatch(SetCardPos(d.card.id, pos.x, pos.y))

    # ----- double click / context / keys ------------------------------------

    def on_double_click(self, e: tk.Event) -> None:
        tag = self.view.resolve_tag_at(e)
        if not tag:
            return
        if tag.startswith("zone:"):
            key = self.view.key_for_tag(tag)
            zone = self.view.state.zones.get(key) if isinstance(key, ZoneKey) else None
            if zone is None or key.role is ZoneRole.HAND or not zone.cards:
                return
            if not can_interact(self.view, key.owner):
                return
            zv = self.view.zones.get(tag)
            pos = self._from_canvas(zv.x, zv.y) if zv else None
            self.view.dispatch(MoveCard(zone.cards[-1].id, BATTLEFIELD, position=pos))
            return
        if tag.startswith("card:"):
            ctx = ActionContext(card_tag=tag, event=e, owner=self._owner_of(tag))
            act = ACTIONS["card.toggle_bow"]
            if act.when(self.view, ctx):
                act.run(self.view, ctx)

    def on_context(self, e: tk.Event) -> None:
        self.view.focus_set()
        tag = self.view.resolve_tag_at(e)
        self._context_menu.delete(0, "end")
        self._context_tag = tag
        if not tag:
            build_actions_menu(
                self._context_menu,
                self.view,
                ActionContext(event=e),
                [ACTIONS["table.create_token"]],
            )
            self._popup(e)
            return
        owner = self._owner_of(tag)
        if tag.startswith("card:"):
            sel = getattr(self.view, "_selected", set())
            if tag not in sel:
                self.view._set_selection({tag})
            self._build_card_menu(tag, e, owner)
        elif tag.startswith("zone:"):
            ctx = ActionContext(zone_tag=tag, event=e, owner=owner)
            build_actions_menu(
                self._context_menu,
                self.view,
                ctx,
                [
                    ACTIONS[a]
                    for a in ("zone.toggle_flip", "zone.fill", "zone.destroy", "zone.discard")
                ],
            )
        self._popup(e)

    def _popup(self, e: tk.Event) -> None:
        try:
            self._context_menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._context_menu.grab_release()
            self._context_tag = None

    def _build_card_menu(self, tag: str, e: tk.Event, owner: PlayerId | None) -> None:
        ctx = ActionContext(card_tag=tag, event=e, owner=owner)
        sp = self.view.sprites[tag]
        hk = self._hotkeys
        menu = self._context_menu

        def add(label: str, action_id: str) -> None:
            act = ACTIONS[action_id]
            menu.add_command(
                label=label,
                command=lambda: act.run(self.view, ctx),
                state="normal" if act.when(self.view, ctx) else "disabled",
            )

        add(f"Unbow ({hk.bow})" if sp.card.bowed else f"Bow ({hk.bow})", "card.toggle_bow")
        add(
            f"Uninvert ({hk.invert})" if sp.card.inverted else f"Invert ({hk.invert})",
            "card.toggle_invert",
        )
        add(
            f"Flip Down ({hk.flip})" if sp.card.face_up else f"Flip Up ({hk.flip})",
            "card.toggle_flip",
        )
        send_menu = tk.Menu(menu, tearoff=0)
        build_actions_menu(
            send_menu,
            self.view,
            ctx,
            [
                ACTIONS[a]
                for a in (
                    "card.send_hand",
                    "card.send_fate_disc",
                    "card.send_dynasty_disc",
                    "card.send_deck_top",
                    "card.send_deck_bottom",
                )
            ],
        )
        menu.add_cascade(label="Send to", menu=send_menu)
        menu.add_separator()
        if sp.card.back_card_id is not None:
            add("Flip Face", "card.flip_face")
        add("Note…", "card.set_note")
        add("Duplicate", "card.duplicate")
        if sp.card.is_token:
            add("Remove", "card.remove")

    def on_escape(self, e: tk.Event) -> None:
        self.view._clear_selection()

    def on_key(self, e: tk.Event) -> None:
        key = getattr(e, "keysym", "").lower()
        hk = self._hotkeys

        if self._hover_zone_tag and key in {hk.flip, hk.fill, hk.destroy, hk.invert}:
            ctx = ActionContext(
                zone_tag=self._hover_zone_tag, event=e, owner=self._owner_of(self._hover_zone_tag)
            )
            action_id = {
                hk.flip: "zone.toggle_flip",
                hk.fill: "zone.fill",
                hk.destroy: "zone.destroy",
                hk.invert: "zone.discard",
            }[key]
            self._run_if_enabled(action_id, ctx)
            return

        sel = getattr(self.view, "_selected", set())
        target_tag = next(iter(sel)) if sel else self._hover_card_tag
        if not target_tag:
            return
        ctx = ActionContext(card_tag=target_tag, event=e, owner=self._owner_of(target_tag))
        action_id = {
            hk.bow: "card.toggle_bow",
            hk.flip: "card.toggle_flip",
            hk.invert: "card.toggle_invert",
        }.get(key)
        if action_id:
            self._run_if_enabled(action_id, ctx)

    def _run_if_enabled(self, action_id: str, ctx: ActionContext) -> None:
        act = ACTIONS[action_id]
        if act.when(self.view, ctx):
            act.run(self.view, ctx)

    def on_toggle_player(self, e: tk.Event) -> None:
        """Switch the viewing/acting seat (debug only), flipping the board to that seat's view."""
        if not getattr(gui_config, "DEBUG_MODE", False):
            return
        self.view.seat = PlayerId.P2 if self.view.seat is PlayerId.P1 else PlayerId.P1
        self.view.reconcile_all()
        if self.view.on_local_player_changed is not None:
            self.view.on_local_player_changed()
