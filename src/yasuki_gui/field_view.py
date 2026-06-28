import tkinter as tk
from types import MappingProxyType

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BoardPos, DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.intents import Event, Intent, apply_intent
from yasuki_core.engine.redaction import ViewSnapshot
from yasuki_core.game_pieces.constants import Side
from yasuki_gui import theme
from yasuki_gui.config import DEFAULT_HOTKEYS, Hotkeys
from yasuki_gui.constants import CARD_H, CARD_W
from yasuki_gui.controller import FieldController
from yasuki_gui.layout import (
    deck_pos,
    discard_pos,
    from_canvas,
    hand_box,
    province_positions,
    to_canvas,
    unplaced_battlefield_pos,
)
from yasuki_gui.services.hittest import resolve_tag_at as hittest_resolve_tag_at
from yasuki_gui.tags import card_id_for_tag, card_tag, deck_tag, zone_tag
from yasuki_gui.ui.images import ImageProvider
from yasuki_gui.visuals import CardSpriteVisual, DeckVisual, HandVisual, ZoneVisual
from yasuki_gui.visuals.cardface import to_render_card


def _deck_label(key: DeckKey) -> str:
    return "Dynasty Deck" if key.side is Side.DYNASTY else "Fate Deck"


_ZONE_LABELS: dict[ZoneRole, str] = {
    ZoneRole.PROVINCE: "Province",
    ZoneRole.FATE_DISCARD: "Fate Discard",
    ZoneRole.FATE_BANISH: "Fate Banish",
    ZoneRole.DYNASTY_DISCARD: "Dynasty Discard",
    ZoneRole.DYNASTY_BANISH: "Dynasty Banish",
}


def _zone_label(key: ZoneKey) -> str:
    return _ZONE_LABELS.get(key.role, key.role.value)


class FieldView(tk.Canvas):
    """Tkinter canvas that renders a single authoritative ``TableState`` and drives it through
    ``apply_intent``.

    The state is the sole source of truth; every visual is a keyed projection of it, rebuilt by
    :meth:`reconcile_all` after each :meth:`dispatch`. Card identity is stable (cards mutate in
    place), so a sprite keeps its card reference across mutations and reconciliation only tracks
    membership and battlefield position.
    """

    def __init__(self, master: tk.Misc, width: int = 800, height: int = 600):
        super().__init__(master, width=width, height=height, bg=theme.SURFACE, highlightthickness=0)
        self._cw = width
        self._ch = height

        self.state: TableState | None = None
        # When set (rules mode), the board renders from this redacted projection instead of the raw
        # table; the manual sandbox leaves it None and renders the full TableState directly.
        self._snapshot: ViewSnapshot | None = None
        self.seat: PlayerId = PlayerId.P1

        self._sprites: dict[str, CardSpriteVisual] = {}
        self._decks: dict[str, DeckVisual] = {}
        self._zones: dict[str, ZoneVisual] = {}
        self._hands: dict[str, HandVisual] = {}
        self._tag_to_key: dict[str, ZoneKey | DeckKey] = {}

        self._hotkeys: Hotkeys = DEFAULT_HOTKEYS
        self._selected: set[str] = set()
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_rect: int | None = None

        self._controller = FieldController(self)
        self._images = ImageProvider(self)

        self.bind("<Enter>", lambda e: self.focus_set())
        self.bind("<Configure>", self._on_configure)

    # ----- public API -------------------------------------------------------

    @property
    def local_player(self) -> PlayerId:
        # Retained name for the controller/permissions affordance layer; the viewing seat is the
        # acting seat in single-player.
        return self.seat

    @local_player.setter
    def local_player(self, seat: PlayerId) -> None:
        self.seat = seat

    @property
    def _flipped(self) -> bool:
        """Whether the battlefield is rendered 180° from the canonical P1 frame (debug other-seat
        view). Positions are stored in P1's frame, so viewing as P2 flips them."""
        return self.seat is PlayerId.P2

    def load_state(self, state: TableState, seat: PlayerId) -> None:
        """Adopt ``state`` as the rendered table, viewed and controlled from ``seat``."""
        self.state = state
        self.seat = seat
        self.delete("all")
        self._sprites.clear()
        self._decks.clear()
        self._zones.clear()
        self._hands.clear()
        self._tag_to_key.clear()
        self._selected.clear()
        self.reconcile_all()

    def dispatch(self, intent: Intent) -> list[Event]:
        """Apply ``intent`` as the acting seat, reconcile the visuals, and return the events.

        A no-op in rules mode (a projection is set): the rules engine owns mutations there, so the
        sandbox intent path is disabled to keep the engine authoritative."""
        if self.state is None or self._snapshot is not None:
            return []
        events = apply_intent(self.state, self.seat, intent)
        if events:
            self.reconcile_all()
        return events

    def render_snapshot(self, snapshot: ViewSnapshot, seat: PlayerId) -> None:
        """Render the board from a redacted projection (rules mode), viewed from ``seat``."""
        self._snapshot = snapshot
        self.seat = seat
        self.reconcile_all()

    def configure_hotkeys(self, hotkeys: Hotkeys) -> None:
        self._hotkeys = hotkeys
        self._controller.configure_hotkeys(hotkeys)

    def resolve_tag_at(self, event: tk.Event) -> str | None:
        return hittest_resolve_tag_at(self, event)

    def key_for_tag(self, tag: str) -> ZoneKey | DeckKey | None:
        return self._tag_to_key.get(tag)

    def canonical_pos(self, x: int, y: int) -> BoardPos:
        """Turn a canvas pixel into the seat-neutral battlefield position the engine stores."""
        w, h = self._canvas_size()
        return from_canvas(x, y, flipped=self._flipped, canvas_w=w, canvas_h=h)

    @staticmethod
    def card_id_for_tag(tag: str) -> str | None:
        return card_id_for_tag(tag)

    # ----- exposed collections (read-only views) ----------------------------

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

    # ----- selection (visual only) ------------------------------------------

    def _clear_selection(self) -> None:
        if not self._selected:
            return
        for tag in list(self._selected):
            sprite = self._sprites.get(tag)
            if sprite:
                sprite.update_selection(self, False)
        self._selected.clear()

    def _set_selection(self, tags: set[str]) -> None:
        if tags == self._selected:
            return
        old = self._selected
        self._selected = set(tags)
        for tag in old - self._selected:
            sp = self._sprites.get(tag)
            if sp:
                sp.update_selection(self, False)
        for tag in self._selected - old:
            sp = self._sprites.get(tag)
            if sp:
                sp.update_selection(self, True)

    # ----- geometry helpers for the controller/hittest ----------------------

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
        self.delete(tag)
        dv = self._decks.get(tag)
        if dv is not None:
            dv.draw(self)

    def redraw_zone(self, tag: str) -> None:
        self.delete(tag)
        if tag in self._zones:
            self._zones[tag].draw(self)
        elif tag in self._hands:
            self._hands[tag].draw(self)

    # ----- reconciliation ---------------------------------------------------

    def reconcile(self, events: list[Event]) -> None:
        # The board is small, so a full reconcile after every accepted intent stays cheap and avoids
        # any chance of a stale projection. Event-targeted redraw can specialise this later.
        self.reconcile_all()

    def reconcile_all(self) -> None:
        if self.state is None and self._snapshot is None:
            return
        self.delete("all")
        self._draw_table()
        self._reconcile_decks()
        self._reconcile_zones()
        self._reconcile_sprites()

    # The render source is the redacted projection in rules mode, else the raw sandbox table. These
    # accessors yield uniform render-data from whichever is active, so reconcile is source-agnostic.

    def _render_decks(self):
        if self._snapshot is not None:
            for key, deck_view in self._snapshot.decks.items():
                top = to_render_card(deck_view.top) if deck_view.top is not None else None
                yield key, deck_view.count, top
        else:
            for key, deck in self.state.decks.items():
                yield key, len(deck.cards), to_render_card(deck.cards[-1]) if deck.cards else None

    def _render_zones(self):
        if self._snapshot is not None:
            for key, zone_view in self._snapshot.zones.items():
                yield key, [to_render_card(card_view) for card_view in zone_view.cards]
        else:
            for key, zone in self.state.zones.items():
                yield key, [to_render_card(card) for card in zone.cards]

    def _render_battlefield(self):
        if self._snapshot is not None:
            for bf_view in self._snapshot.battlefield:
                yield to_render_card(bf_view.card), bf_view.pos
        else:
            for card in self.state.battlefield.cards:
                yield to_render_card(card), self.state.positions.get(card.id)

    def _render_seats(self):
        return self._snapshot.seats if self._snapshot is not None else self.state.seats

    def _zone_keys(self):
        source = self._snapshot.zones if self._snapshot is not None else self.state.zones
        return source.keys()

    def _draw_table(self) -> None:
        """A faint gold midline splitting the two seats' halves, drawn behind every card."""
        w, h = self._canvas_size()
        self.create_line(
            int(w * 0.08), h // 2, int(w * 0.92), h // 2, fill=theme.MIDLINE, tags=("table",)
        )

    def _reconcile_decks(self) -> None:
        w, h = self._canvas_size()
        wanted: set[str] = set()
        for key, count, top in self._render_decks():
            tag = deck_tag(key)
            wanted.add(tag)
            x, y = deck_pos(w, h, key, seat_at_bottom=key.owner is self.seat)
            dv = self._decks.get(tag)
            if dv is None:
                dv = DeckVisual(count, top, x, y, tag, label=_deck_label(key), images=self._images)
                self._decks[tag] = dv
            dv.count, dv.top, dv.x, dv.y = count, top, x, y
            dv.owner = key.owner
            self._tag_to_key[tag] = key
            dv.draw(self)
        for tag in set(self._decks) - wanted:
            self._decks.pop(tag, None)
            self._tag_to_key.pop(tag, None)

    def _reconcile_zones(self) -> None:
        w, h = self._canvas_size()
        province_keys = self._province_keys_by_owner()
        wanted_zones: set[str] = set()
        wanted_hands: set[str] = set()
        for key, cards in self._render_zones():
            tag = zone_tag(key)
            self._tag_to_key[tag] = key
            seat_at_bottom = key.owner is self.seat
            if key.role is ZoneRole.HAND:
                wanted_hands.add(tag)
                bx, by, bw, bh = hand_box(w, h, seat_at_bottom=seat_at_bottom)
                hv = self._hands.get(tag)
                if hv is None:
                    hv = HandVisual(cards, key.owner, bx, by, bw, bh, tag, images=self._images)
                    self._hands[tag] = hv
                hv.cards, hv.owner = cards, key.owner
                hv.x, hv.y, hv.w, hv.h = bx, by, bw, bh
                hv.draw(self)
                continue
            wanted_zones.add(tag)
            is_province = key.role is ZoneRole.PROVINCE
            if is_province:
                ordered = province_keys[key.owner]
                positions = province_positions(w, h, len(ordered), seat_at_bottom=seat_at_bottom)
                px, py = positions[ordered.index(key)]
                bx, by, bw, bh = px, py, CARD_W, CARD_H
            else:
                bx, by, bw, bh = discard_pos(w, h, key, seat_at_bottom=seat_at_bottom)
            label = _zone_label(key)
            zv = self._zones.get(tag)
            if zv is None:
                zv = ZoneVisual(cards, is_province, label, bx, by, bw, bh, tag, images=self._images)
                self._zones[tag] = zv
            zv.cards, zv.is_province, zv.name = cards, is_province, label
            zv.x, zv.y, zv.w, zv.h = bx, by, bw, bh
            zv.draw(self)
        for tag in set(self._zones) - wanted_zones:
            self._zones.pop(tag, None)
            self._tag_to_key.pop(tag, None)
        for tag in set(self._hands) - wanted_hands:
            self._hands.pop(tag, None)
            self._tag_to_key.pop(tag, None)

    def _reconcile_sprites(self) -> None:
        w, h = self._canvas_size()
        wanted: set[str] = set()
        for rc, pos in self._render_battlefield():
            tag = card_tag(rc.id)
            wanted.add(tag)
            x, y = self._sprite_xy(rc, pos, w, h)
            sp = self._sprites.get(tag)
            if sp is None:
                sp = CardSpriteVisual(rc, x, y, tag, images=self._images)
                self._sprites[tag] = sp
            sp.card, sp.x, sp.y = rc, x, y
            sp.draw(self, selected=tag in self._selected)
        for tag in set(self._sprites) - wanted:
            self._sprites.pop(tag, None)
            self._selected.discard(tag)

    def _sprite_xy(self, card, pos: BoardPos | None, w: int, h: int) -> tuple[int, int]:
        if pos is None or pos.x < 0 or pos.y < 0:
            side = Side.FATE if card.side is Side.FATE else Side.DYNASTY
            return unplaced_battlefield_pos(
                w, h, side, card.owner, seat_at_bottom=(card.owner or self.seat) is self.seat
            )
        return to_canvas(pos, flipped=self._flipped, canvas_w=w, canvas_h=h)

    def _province_keys_by_owner(self) -> dict[PlayerId, list[ZoneKey]]:
        by_owner: dict[PlayerId, list[ZoneKey]] = {seat: [] for seat in self._render_seats()}
        for key in self._zone_keys():
            if key.role is ZoneRole.PROVINCE:
                by_owner.setdefault(key.owner, []).append(key)
        for keys in by_owner.values():
            keys.sort(key=lambda k: k.idx or 0)
        return by_owner

    def _canvas_size(self) -> tuple[int, int]:
        w, h = self.winfo_width(), self.winfo_height()
        return (max(w, self._cw), max(h, self._ch))

    def _on_configure(self, event: tk.Event) -> None:
        if event.width > 1 and event.height > 1:
            self._cw, self._ch = event.width, event.height
            if self.state is not None:
                self.reconcile_all()
