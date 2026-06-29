import tkinter as tk
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from tkinter import simpledialog
from typing import Literal, Protocol

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BoardPos, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.intents import (
    Bow,
    DestroyProvince,
    DiscardProvince,
    FillProvince,
    Flip,
    FlipFace,
    Invert,
    MoveCard,
    RemoveCard,
    SetNote,
    SpawnCard,
    Unbow,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.config import DEFAULT_HOTKEYS as HK
from yasuki_gui.ui.dialogs import Dialogs
from yasuki_gui.ui.images import ImageProvider

# A duplicated or token card lands a little down-right of its source so it does not hide it.
_SPAWN_OFFSET = 24


class HasView(Protocol):
    """The slice of FieldView an action needs: the table, the acting seat, and dispatch."""

    seat: PlayerId

    def dispatch(self, intent) -> list: ...
    def key_for_tag(self, tag: str): ...


@dataclass(frozen=True)
class ActionContext:
    """Exactly one of the tag fields is set depending on what was clicked."""

    card_tag: str | None = None
    zone_tag: str | None = None
    deck_tag: str | None = None
    event: tk.Event | None = None
    owner: PlayerId | None = None


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    hotkey: str | None = None
    when: Callable[[HasView, ActionContext], bool] = lambda v, c: True
    run: Callable[[HasView, ActionContext], None] = lambda v, c: None
    group: str = "default"


def _get_tk_state(enabled: bool) -> Literal["normal", "disabled"]:
    return "normal" if enabled else "disabled"


def build_menu(menu: tk.Menu, view: HasView, ctx: ActionContext, actions: Iterable[Action]) -> None:
    last_group: str | None = None
    for a in actions:
        if last_group is not None and a.group != last_group:
            menu.add_separator()
        last_group = a.group
        enabled = a.when(view, ctx)
        cmd = (lambda act=a: act.run(view, ctx)) if enabled else None
        label = a.label if a.hotkey is None else f"{a.label} ({a.hotkey})"
        menu.add_command(label=label, state=_get_tk_state(enabled), command=cmd)


REGISTRY: dict[str, Action] = {}


def _register(factory: Callable[[], Action]) -> Action:
    action = factory()
    REGISTRY[action.id] = action
    return action


# ----- context helpers ------------------------------------------------------


def _card(view: HasView, tag: str | None) -> L5RCard | None:
    if not tag or view.state is None:
        return None
    return view.state.cards_by_id.get(view.card_id_for_tag(tag) or "")


def _may(view: HasView, owner: PlayerId | None) -> bool:
    """UI affordance: a card/zone/deck is actionable when public or owned by the acting seat. This
    only grays out menu items — ``apply_intent`` re-validates ownership on dispatch."""
    return owner is None or owner == view.seat


def _selection_ids(view: HasView, ctx: ActionContext) -> tuple[str, ...]:
    """The battlefield card ids a card action targets: the live selection when the clicked card is
    part of it, else just the clicked card."""
    selected = getattr(view, "_selected", set())
    tags = selected if (selected and ctx.card_tag in selected) else {ctx.card_tag}
    ids = [view.card_id_for_tag(t) for t in tags if t]
    state = view.state
    return tuple(
        cid for cid in ids if cid and state is not None and _may(view, state.cards_by_id[cid].owner)
    )


def _card_owner(view: HasView, ctx: ActionContext) -> PlayerId | None:
    card = _card(view, ctx.card_tag)
    return ctx.owner if ctx.owner is not None else (card.owner if card else None)


# ----- card actions ---------------------------------------------------------


def _card_when(view: HasView, ctx: ActionContext) -> bool:
    return _card(view, ctx.card_tag) is not None and _may(view, _card_owner(view, ctx))


@_register
def card_bow() -> Action:
    def run(view, ctx):
        card = _card(view, ctx.card_tag)
        ids = _selection_ids(view, ctx)
        if not ids:
            return
        view.dispatch(Unbow(ids) if card and card.bowed else Bow(ids))

    return Action("card.toggle_bow", "Bow / Unbow", HK.bow, _card_when, run, "card")


@_register
def card_flip() -> Action:
    def run(view, ctx):
        ids = _selection_ids(view, ctx)
        if ids:
            view.dispatch(Flip(ids))

    return Action("card.toggle_flip", "Flip Up/Down", HK.flip, _card_when, run, "card")


@_register
def card_invert() -> Action:
    def run(view, ctx):
        ids = _selection_ids(view, ctx)
        if ids:
            view.dispatch(Invert(ids))

    return Action("card.toggle_invert", "Invert", HK.invert, _card_when, run, "card")


def _send_to(role: ZoneRole, side: Side | None, to_bottom: bool = False):
    def run(view, ctx):
        card = _card(view, ctx.card_tag)
        if card is None:
            return
        view.dispatch(MoveCard(card.id, ZoneKey(view.seat, role), to_bottom=to_bottom))

    def when(view, ctx):
        card = _card(view, ctx.card_tag)
        if card is None or not _may(view, _card_owner(view, ctx)):
            return False
        return side is None or card.side is side

    return run, when


def _send_to_deck(to_bottom: bool):
    def run(view, ctx):
        card = _card(view, ctx.card_tag)
        if card is None:
            return
        view.dispatch(MoveCard(card.id, DeckKey(view.seat, card.side), to_bottom=to_bottom))

    return run


@_register
def card_send_to_hand() -> Action:
    run, when = _send_to(ZoneRole.HAND, Side.FATE)
    return Action("card.send_hand", "Send to Hand", when=when, run=run, group="send")


@_register
def card_send_to_fate_discard() -> Action:
    run, when = _send_to(ZoneRole.FATE_DISCARD, Side.FATE)
    return Action("card.send_fate_disc", "Fate Discard", when=when, run=run, group="send")


@_register
def card_send_to_dynasty_discard() -> Action:
    run, when = _send_to(ZoneRole.DYNASTY_DISCARD, Side.DYNASTY)
    return Action("card.send_dynasty_disc", "Dynasty Discard", when=when, run=run, group="send")


@_register
def card_send_to_top() -> Action:
    return Action(
        "card.send_deck_top", "Top of Deck", when=_card_when, run=_send_to_deck(False), group="send"
    )


@_register
def card_send_to_bottom() -> Action:
    return Action(
        "card.send_deck_bottom",
        "Bottom of Deck",
        when=_card_when,
        run=_send_to_deck(True),
        group="send",
    )


# ----- zone (province) actions ----------------------------------------------


def _province_key(view: HasView, ctx: ActionContext) -> ZoneKey | None:
    key = view.key_for_tag(ctx.zone_tag or "")
    return key if isinstance(key, ZoneKey) and key.role is ZoneRole.PROVINCE else None


@_register
def province_flip_card() -> Action:
    def when(view, ctx):
        key = view.key_for_tag(ctx.zone_tag or "")
        if not isinstance(key, ZoneKey):
            return False
        zone = view.state.zones.get(key)
        return bool(zone and zone.cards) and _may(view, key.owner)

    def run(view, ctx):
        key = view.key_for_tag(ctx.zone_tag or "")
        zone = view.state.zones.get(key) if isinstance(key, ZoneKey) else None
        if zone and zone.cards:
            view.dispatch(Flip((zone.cards[-1].id,)))

    return Action("zone.toggle_flip", "Flip Top", HK.flip, when, run, "zone")


@_register
def province_fill() -> Action:
    def when(view, ctx):
        key = _province_key(view, ctx)
        return key is not None and view.state.zones[key].has_capacity() and _may(view, key.owner)

    def run(view, ctx):
        key = _province_key(view, ctx)
        if key is not None:
            view.dispatch(FillProvince(key))

    return Action("zone.fill", "Fill", HK.fill, when, run, "zone")


@_register
def province_destroy() -> Action:
    def when(view, ctx):
        key = _province_key(view, ctx)
        return key is not None and _may(view, key.owner)

    def run(view, ctx):
        key = _province_key(view, ctx)
        if key is not None:
            view.dispatch(DestroyProvince(key))

    return Action("zone.destroy", "Destroy", HK.destroy, when, run, "zone")


@_register
def province_discard() -> Action:
    def when(view, ctx):
        key = _province_key(view, ctx)
        return key is not None and bool(view.state.zones[key].cards) and _may(view, key.owner)

    def run(view, ctx):
        key = _province_key(view, ctx)
        if key is not None:
            view.dispatch(DiscardProvince(key))

    return Action("zone.discard", "Discard", HK.invert, when, run, "zone")


# ----- tokens and annotations -----------------------------------------------
# These split the decision logic (build and dispatch the intent) from the dialogs that gather input,
# so the intent path is unit-testable without driving Tk.


def fresh_token_id(state) -> str:
    """The lowest ``token-N`` id not already on the table."""
    i = 0
    while f"token-{i}" in state.cards_by_id:
        i += 1
    return f"token-{i}"


def spawn_token(view: HasView, name: str, side: Side, pos: BoardPos) -> None:
    view.dispatch(SpawnCard(fresh_token_id(view.state), name, side, None, pos))


def duplicate_card(view: HasView, card_id: str) -> None:
    """Spawn a token copy of a card's visible face, offset down-right of the original."""
    card = view.state.cards_by_id.get(card_id)
    if card is None:
        return
    face = card.active_face
    origin = view.state.positions.get(card_id) or BoardPos(0.0, 0.0)
    pos = BoardPos(origin.x + _SPAWN_OFFSET, origin.y + _SPAWN_OFFSET)
    image = str(face.image_front) if face.image_front else None
    view.dispatch(SpawnCard(fresh_token_id(view.state), card.name, card.side, image, pos))


def apply_note(view: HasView, card_id: str, text: str | None) -> None:
    view.dispatch(SetNote(card_id, text))


@_register
def card_flip_face() -> Action:
    def when(view, ctx):
        card = _card(view, ctx.card_tag)
        return (
            card is not None
            and card.back_card_id is not None
            and _may(view, _card_owner(view, ctx))
        )

    def run(view, ctx):
        card = _card(view, ctx.card_tag)
        if card is not None:
            view.dispatch(FlipFace((card.id,)))

    return Action("card.flip_face", "Flip Face", when=when, run=run, group="card")


@_register
def card_set_note() -> Action:
    def when(view, ctx):
        card = _card(view, ctx.card_tag)
        return card is not None and card.face_up

    def run(view, ctx):
        card = _card(view, ctx.card_tag)
        if card is None:
            return
        master = view.winfo_toplevel()
        text = simpledialog.askstring(
            "Card note", "Note:", initialvalue=card.note or "", parent=master
        )
        if text is not None:
            apply_note(view, card.id, text)

    return Action("card.set_note", "Note…", when=when, run=run, group="card")


@_register
def card_duplicate() -> Action:
    def when(view, ctx):
        card = _card(view, ctx.card_tag)
        return card is not None and card.face_up

    def run(view, ctx):
        card = _card(view, ctx.card_tag)
        if card is not None:
            duplicate_card(view, card.id)

    return Action("card.duplicate", "Duplicate", when=when, run=run, group="card")


@_register
def card_remove() -> Action:
    def when(view, ctx):
        card = _card(view, ctx.card_tag)
        return card is not None and card.is_token and _may(view, _card_owner(view, ctx))

    def run(view, ctx):
        card = _card(view, ctx.card_tag)
        if card is not None:
            view.dispatch(RemoveCard(card.id))

    return Action("card.remove", "Remove", when=when, run=run, group="card")


@_register
def table_create_token() -> Action:
    def run(view, ctx):
        if ctx.event is None:
            return
        pos = view.canonical_pos(ctx.event.x, ctx.event.y)
        master = view.winfo_toplevel()
        Dialogs(master, ImageProvider(master)).create_token(
            lambda name, side: spawn_token(view, name, side, pos)
        )

    return Action("table.create_token", "Create Token…", run=run, group="table")
