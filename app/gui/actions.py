from dataclasses import dataclass
from typing import Protocol, Literal
from collections.abc import Callable, Mapping
from collections.abc import Iterable

import tkinter as tk
from app.game_pieces.constants import Side
from app.gui.config import DEFAULT_HOTKEYS as HK
from app.engine.zones import DynastyDiscardZone, ProvinceZone


class HasView(Protocol):
    """Minimal protocol for views that support actions."""

    sprites: Mapping[str, object]
    decks: Mapping[str, object]
    zones: Mapping[str, object]
    hands: Mapping[str, object]


@dataclass(frozen=True)
class ActionContext:
    """Exactly one of these should be set depending on context."""

    card_tag: str | None = None
    zone_tag: str | None = None
    deck_tag: str | None = None
    event: tk.Event | None = None


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


@_register
def card_bow() -> Action:
    def when(view, ctx):
        return bool(ctx.card_tag and ctx.card_tag in view.sprites)

    def run(view, ctx):
        sp = view.sprites[ctx.card_tag]
        if sp.card.bowed:
            sp.card.unbow()
        else:
            sp.card.bow()
        sp.refresh_face_state(view)

    return Action(
        id="card.toggle_bow", label="Bow / Unbow", hotkey=HK.bow, when=when, run=run, group="card"
    )


@_register
def card_flip() -> Action:
    def when(view, ctx):
        return bool(ctx.card_tag and ctx.card_tag in view.sprites)

    def run(view, ctx):
        sp = view.sprites[ctx.card_tag]
        if sp.card.face_up:
            sp.card.turn_face_down()
        else:
            sp.card.turn_face_up()
        sp.refresh_face_state(view)

    return Action(
        id="card.toggle_flip",
        label="Flip Up/Down",
        hotkey=HK.flip,
        when=when,
        run=run,
        group="card",
    )


@_register
def card_invert() -> Action:
    def when(view, ctx):
        return bool(ctx.card_tag and ctx.card_tag in view.sprites)

    def run(view, ctx):
        sp = view.sprites[ctx.card_tag]
        if sp.card.inverted:
            sp.card.uninvert()
        else:
            sp.card.invert()
        sp.refresh_face_state(view)

    return Action(
        id="card.toggle_invert", label="Invert", hotkey=HK.invert, when=when, run=run, group="card"
    )


@_register
def card_send_to_hand() -> Action:
    def when(view, ctx):
        return bool(
            ctx.card_tag
            and ctx.card_tag in view.sprites
            and hasattr(view, "_find_zone_tag_by_type")
        )

    def run(view, ctx):
        view._send_card_to_hand(ctx.card_tag)

    return Action(id="card.send_hand", label="Send to Hand", when=when, run=run, group="send")


@_register
def card_send_to_fate_discard() -> Action:
    def when(view, ctx):
        if not ctx.card_tag or ctx.card_tag not in view.sprites:
            return False
        return view.sprites[ctx.card_tag].card.side is Side.FATE

    def run(view, ctx):
        view._send_card_to_fate_discard(ctx.card_tag)

    return Action(id="card.send_fate_disc", label="Fate Discard", when=when, run=run, group="send")


@_register
def card_send_to_dynasty_discard() -> Action:
    def when(view, ctx):
        if not ctx.card_tag or ctx.card_tag not in view.sprites:
            return False
        return view.sprites[ctx.card_tag].card.side is Side.DYNASTY

    def run(view, ctx):
        view._send_card_to_dynasty_discard(ctx.card_tag)

    return Action(
        id="card.send_dynasty_disc", label="Dynasty Discard", when=when, run=run, group="send"
    )


@_register
def card_sent_to_top() -> Action:
    def when(view, ctx):
        if not ctx.card_tag or ctx.card_tag not in view.sprites:
            return False
        return True

    def run(view, ctx):
        side = view.sprites[ctx.card_tag].card.side
        view._send_card_to_deck_top(ctx.card_tag, side)

    return Action(id="card.send_deck_top", label="Top of Deck", when=when, run=run, group="send")


@_register
def card_send_to_bottom() -> Action:
    def when(view, ctx):
        if not ctx.card_tag or ctx.card_tag not in view.sprites:
            return False
        return True

    def run(view, ctx):
        side = view.sprites[ctx.card_tag].card.side
        view._send_card_to_deck_bottom(ctx.card_tag, side)

    return Action(
        id="card.send_deck_bottom", label="Bottom of Deck", when=when, run=run, group="send"
    )


@_register
def check_draw() -> Action:
    def when(view, ctx):
        return bool(
            ctx.deck_tag and ctx.deck_tag in view.decks and view.decks[ctx.deck_tag].deck.cards
        )

    def run(view, ctx):
        view._deck_draw(ctx.deck_tag)

    return Action(id="deck.draw", label="Draw", hotkey=HK.draw, when=when, run=run, group="deck")


@_register
def check_shuffle() -> Action:
    def when(view, ctx):
        return bool(ctx.deck_tag and ctx.deck_tag in view.decks)

    def run(view, ctx):
        view._deck_shuffle(ctx.deck_tag)

    return Action(
        id="deck.shuffle", label="Shuffle", hotkey=HK.shuffle, when=when, run=run, group="deck"
    )


@_register
def deck_flip_top_card() -> Action:
    def when(view, ctx):
        return bool(
            ctx.deck_tag and ctx.deck_tag in view.decks and view.decks[ctx.deck_tag].deck.cards
        )

    def run(view, ctx):
        view._deck_flip_top(ctx.deck_tag)

    return Action(
        id="deck.flip_top", label="Flip Top", hotkey=HK.flip, when=when, run=run, group="deck"
    )


@_register
def deck_inspect() -> Action:
    def when(view, ctx):
        return bool(ctx.deck_tag and ctx.deck_tag in view.decks)

    def run(view, ctx):
        view._deck_inspect(ctx.deck_tag)

    return Action(
        id="deck.inspect", label="Inspect", hotkey=HK.inspect, when=when, run=run, group="deck"
    )


@_register
def province_flip_card() -> Action:
    def when(view, ctx):
        return bool(
            ctx.zone_tag and ctx.zone_tag in view.zones and view.zones[ctx.zone_tag].zone.cards
        )

    def run(view, ctx):
        zv = view.zones[ctx.zone_tag]
        if zv.zone.cards and zv.zone.cards[-1].face_up:
            view._zone_flip_down(ctx.zone_tag)
        else:
            view._zone_flip_up(ctx.zone_tag)

    return Action(
        id="zone.toggle_flip", label="Flip Top", hotkey=HK.flip, when=when, run=run, group="zone"
    )


@_register
def province_fill() -> Action:
    def when(view, ctx):
        return bool(ctx.zone_tag and ctx.zone_tag in view.zones)

    def run(view, ctx):
        view._zone_fill(ctx.zone_tag)

    return Action(id="zone.fill", label="Fill", hotkey=HK.fill, when=when, run=run, group="zone")


@_register
def province_destroy() -> Action:
    def when(view, ctx):
        return bool(ctx.zone_tag and ctx.zone_tag in view.zones)

    def run(view, ctx):
        view._zone_destroy(ctx.zone_tag)

    return Action(
        id="zone.destroy", label="Destroy", hotkey=HK.destroy, when=when, run=run, group="zone"
    )


@_register
def province_discard() -> Action:
    def when(view, ctx):
        return bool(
            ctx.zone_tag
            and ctx.zone_tag in view.zones
            and isinstance(view.zones[ctx.zone_tag].zone, ProvinceZone)
            and view.zones[ctx.zone_tag].zone.cards
        )

    def run(view, ctx):
        zv = view.zones[ctx.zone_tag]
        if not zv.zone.cards:
            return
        card = zv.zone.cards.pop()
        # ensure face-up in discard
        if not card.face_up:
            card.turn_face_up()
        disc_tag = view._find_zone_tag_by_type(DynastyDiscardZone)
        if not disc_tag:
            # if no discard zone, just add back to province to avoid loss
            zv.zone.cards.append(card)
            return
        view._zones[disc_tag].zone.add(card)
        view._redraw_zone(ctx.zone_tag)
        view._redraw_zone(disc_tag)

    return Action(
        id="zone.discard", label="Discard", hotkey=HK.invert, when=when, run=run, group="zone"
    )
