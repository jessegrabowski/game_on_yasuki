import tkinter as tk
from types import MappingProxyType

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    BoardPos,
    DeckKey,
    Event,
    Intent,
    TableState,
    ZoneKey,
    ZoneRole,
    apply_intent,
)
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.config import DEFAULT_HOTKEYS, Hotkeys
from yasuki_gui.constants import CANVAS_BG, CARD_H, CARD_W
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


def _deck_label(key: DeckKey) -> str:
    return "Dynasty Deck" if key.side is Side.DYNASTY else "Fate Deck"


class FieldView(tk.Canvas):
    """Tkinter canvas that renders a single authoritative ``TableState`` and drives it through
    ``apply_intent``.

    The state is the sole source of truth; every visual is a keyed projection of it, rebuilt by
    :meth:`reconcile_all` after each :meth:`dispatch`. Card identity is stable (cards mutate in
    place), so a sprite keeps its card reference across mutations and reconciliation only tracks
    membership and battlefield position.
    """

    def __init__(self, master: tk.Misc, width: int = 800, height: int = 600):
        super().__init__(master, width=width, height=height, bg=CANVAS_BG, highlightthickness=0)
        self._cw = width
        self._ch = height

        self.state: TableState | None = None
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
        """Apply ``intent`` as the acting seat, reconcile the visuals, and return the events."""
        if self.state is None:
            return []
        events = apply_intent(self.state, self.seat, intent)
        if events:
            self.reconcile_all()
        return events

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
        if self.state is None:
            return
        self.delete("all")
        self._reconcile_decks()
        self._reconcile_zones()
        self._reconcile_sprites()

    def _reconcile_decks(self) -> None:
        w, h = self._canvas_size()
        wanted: set[str] = set()
        for key, deck in self.state.decks.items():
            tag = deck_tag(key)
            wanted.add(tag)
            x, y = deck_pos(w, h, key, seat_at_bottom=key.owner is self.seat)
            dv = self._decks.get(tag)
            if dv is None:
                dv = DeckVisual(deck, x, y, tag, label=_deck_label(key), images=self._images)
                self._decks[tag] = dv
            dv.deck, dv.x, dv.y = deck, x, y
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
        for key, zone in self.state.zones.items():
            tag = zone_tag(key)
            self._tag_to_key[tag] = key
            seat_at_bottom = key.owner is self.seat
            if key.role is ZoneRole.HAND:
                wanted_hands.add(tag)
                bx, by, bw, bh = hand_box(w, h, seat_at_bottom=seat_at_bottom)
                hv = self._hands.get(tag)
                if hv is None:
                    hv = HandVisual(zone, bx, by, bw, bh, tag, images=self._images)
                    self._hands[tag] = hv
                hv.zone, hv.x, hv.y, hv.w, hv.h = zone, bx, by, bw, bh
                hv.draw(self)
                continue
            wanted_zones.add(tag)
            if key.role is ZoneRole.PROVINCE:
                ordered = province_keys[key.owner]
                positions = province_positions(w, h, len(ordered), seat_at_bottom=seat_at_bottom)
                px, py = positions[ordered.index(key)]
                bx, by, bw, bh = px, py, CARD_W, CARD_H
            else:
                bx, by, bw, bh = discard_pos(w, h, key, seat_at_bottom=seat_at_bottom)
            zv = self._zones.get(tag)
            if zv is None:
                zv = ZoneVisual(zone, bx, by, bw, bh, tag, images=self._images)
                self._zones[tag] = zv
            zv.zone, zv.x, zv.y, zv.w, zv.h = zone, bx, by, bw, bh
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
        for card in self.state.battlefield.cards:
            tag = card_tag(card.id)
            wanted.add(tag)
            x, y = self._sprite_xy(card, w, h)
            sp = self._sprites.get(tag)
            if sp is None:
                sp = CardSpriteVisual(card, x, y, tag, images=self._images)
                self._sprites[tag] = sp
            sp.card, sp.x, sp.y = card, x, y
            sp.draw(self, selected=tag in self._selected)
        for tag in set(self._sprites) - wanted:
            self._sprites.pop(tag, None)
            self._selected.discard(tag)

    def _sprite_xy(self, card, w: int, h: int) -> tuple[int, int]:
        pos = self.state.positions.get(card.id)
        if pos is None or pos.x < 0 or pos.y < 0:
            side = Side.FATE if card.side is Side.FATE else Side.DYNASTY
            return unplaced_battlefield_pos(
                w, h, side, card.owner, seat_at_bottom=(card.owner or self.seat) is self.seat
            )
        return to_canvas(pos, flipped=self._flipped, canvas_w=w, canvas_h=h)

    def _province_keys_by_owner(self) -> dict[PlayerId, list[ZoneKey]]:
        by_owner: dict[PlayerId, list[ZoneKey]] = {seat: [] for seat in self.state.seats}
        for key in self.state.zones:
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
