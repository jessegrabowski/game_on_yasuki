import tkinter as tk
from collections.abc import Callable, Iterable
from types import MappingProxyType

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BoardPos, DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.intents import Event, Intent, apply_intent
from yasuki_core.engine.redaction import ViewSnapshot
from yasuki_gui import theme
from yasuki_gui.config import DEFAULT_HOTKEYS, Hotkeys
from yasuki_gui.constants import CARD_H, CARD_W, HOME_STACK_OFFSET
from yasuki_gui.controller import FieldController
from yasuki_gui.layout import (
    divider_y,
    from_canvas,
    hand_box,
    home_stack_positions,
    province_positions,
    to_canvas,
)
from yasuki_gui.services.hittest import resolve_tag_at as hittest_resolve_tag_at
from yasuki_gui.tags import card_id_for_tag, card_tag, zone_tag
from yasuki_gui.ui.images import ImageProvider
from yasuki_gui.visuals import CardSpriteVisual, HandVisual, ZoneVisual
from yasuki_gui.visuals.cardface import RenderCard, to_render_card


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
        # The viewer's gold pool, drawn as a coin in the battlefield corner; set by the host before
        # each render. The rules engine owns the real value.
        self.gold: int = 0

        self._sprites: dict[str, CardSpriteVisual] = {}
        self._zones: dict[str, ZoneVisual] = {}
        self._hands: dict[str, HandVisual] = {}
        self._tag_to_key: dict[str, ZoneKey | DeckKey] = {}

        self._hotkeys: Hotkeys = DEFAULT_HOTKEYS
        self._selected: set[str] = set()
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_rect: int | None = None

        # Decision selection: when the engine awaits a choice, _selectable holds the candidate ids
        # (None when not choosing) and _selection the chosen subset, both rendered on the board.
        # Selection order is tracked so the last pick can be undone (Ctrl+Z during a payment).
        self._selectable: frozenset[str] | None = None
        self._selection: list[str] = []
        # When choosing how to pay, selected producers preview as bowed (tapped for gold).
        self._selection_bows: bool = False

        # Optional UI callbacks the host app installs.
        self.on_local_player_changed: Callable[[], None] | None = None
        self.apply_profile_to_panels: Callable[[], None] | None = None
        self.on_selection_changed: Callable[[], None] | None = None
        self.on_card_activated: Callable[[str], None] | None = None

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

    @property
    def rules_mode(self) -> bool:
        """Whether the board is engine-driven (a projection is set), so clicks act on cards rather
        than dragging the sandbox."""
        return self._snapshot is not None

    # ----- decision selection (cards chosen on the board for a pending decision) ---------

    @property
    def selecting(self) -> bool:
        """Whether the board is in selection mode, awaiting a choice from the player."""
        return self._selectable is not None

    @property
    def selection(self) -> frozenset[str]:
        """The ids currently selected for the pending decision."""
        return frozenset(self._selection)

    def begin_selection(self, candidates: Iterable[str], *, render_bowed: bool = False) -> None:
        """Enter selection mode: only ``candidates`` are selectable, none chosen yet. When
        ``render_bowed`` is set, selected cards preview as bowed (a producer tapped to pay)."""
        self._selectable = frozenset(candidates)
        self._selection = []
        self._selection_bows = render_bowed

    def end_selection(self) -> None:
        """Leave selection mode and clear the selection."""
        self._selectable = None
        self._selection = []
        self._selection_bows = False

    def toggle_selection(self, card_id: str) -> None:
        """Toggle ``card_id`` in the selection if it is a candidate, and notify the listener."""
        if self._selectable is None or card_id not in self._selectable:
            return
        if card_id in self._selection:
            self._selection.remove(card_id)
        else:
            self._selection.append(card_id)
        if self.on_selection_changed is not None:
            self.on_selection_changed()

    def undo_last_selection(self) -> None:
        """Drop the most recently selected id (Ctrl+Z while paying), and notify the listener."""
        if not self._selection:
            return
        self._selection.pop()
        if self.on_selection_changed is not None:
            self.on_selection_changed()

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

    def bbox_for_zone(self, ztag: str) -> tuple[int, int, int, int]:
        zv = self._zones.get(ztag)
        if zv is not None:
            return zv.bbox
        hv = self._hands.get(ztag)
        return hv.bbox if hv else (0, 0, -1, -1)

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
        self._reconcile_zones()
        self._reconcile_sprites()
        if self.rules_mode and self.gold > 0:
            self._draw_gold()

    def _draw_gold(self) -> None:
        """A gold coin and the viewer's pool in the bottom-left of the battlefield."""
        _, h = self._canvas_size()
        cx, cy, r = 30, h - 30, 15
        self.create_oval(
            cx - r,
            cy - r,
            cx + r,
            cy + r,
            fill=theme.GOLD,
            outline=theme.GOLD_HOVER,
            width=2,
            tags=("gold",),
        )
        self.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, outline=theme.GOLD_HOVER, tags=("gold",))
        self.create_text(
            cx + r + 8,
            cy,
            text=str(self.gold),
            fill=theme.INK,
            anchor="w",
            font=theme.serif(16, "bold"),
            tags=("gold",),
        )

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
        y = divider_y(h)
        self.create_line(int(w * 0.08), y, int(w * 0.92), y, fill=theme.MIDLINE, tags=("table",))

    def _reconcile_zones(self) -> None:
        """Draw the on-board zones only: every seat's provinces and the viewer's own hand. Decks,
        discards, and banishes live in the off-board info panels, and the opponent's hand is never
        shown — those are read through the accessors below, not drawn here."""
        w, h = self._canvas_size()
        province_keys = self._province_keys_by_owner()
        wanted_zones: set[str] = set()
        wanted_hands: set[str] = set()
        for key, cards in self._render_zones():
            seat_at_bottom = key.owner is self.seat
            if key.role is ZoneRole.HAND:
                if key.owner is not self.seat:
                    continue  # the opponent's hand is never drawn
                tag = zone_tag(key)
                self._tag_to_key[tag] = key
                wanted_hands.add(tag)
                bx, by, bw, bh = hand_box(w, h, seat_at_bottom=seat_at_bottom)
                hv = self._hands.get(tag)
                if hv is None:
                    hv = HandVisual(cards, key.owner, bx, by, bw, bh, tag, images=self._images)
                    self._hands[tag] = hv
                hv.cards, hv.owner = cards, key.owner
                hv.x, hv.y, hv.w, hv.h = bx, by, bw, bh
                hv.selected_ids = self.selection
                hv.draw(self)
                continue
            if key.role is not ZoneRole.PROVINCE:
                continue  # discards/banishes are off-board (info panel), not drawn here
            tag = zone_tag(key)
            self._tag_to_key[tag] = key
            wanted_zones.add(tag)
            ordered = province_keys[key.owner]
            positions = province_positions(w, h, len(ordered), seat_at_bottom=seat_at_bottom)
            px, py = positions[ordered.index(key)]
            label = _zone_label(key)
            zv = self._zones.get(tag)
            if zv is None:
                zv = ZoneVisual(
                    cards, True, label, px, py, CARD_W, CARD_H, tag, images=self._images
                )
                self._zones[tag] = zv
            zv.cards, zv.is_province, zv.name = cards, True, label
            zv.x, zv.y, zv.w, zv.h = px, py, CARD_W, CARD_H
            zv.draw(self)
        for tag in set(self._zones) - wanted_zones:
            self._zones.pop(tag, None)
            self._tag_to_key.pop(tag, None)
        for tag in set(self._hands) - wanted_hands:
            self._hands.pop(tag, None)
            self._tag_to_key.pop(tag, None)

    # ----- off-board reads (decks/discards/banishes/hand counts for the info panels) ---------

    def deck_summary(self, key: DeckKey) -> tuple[int, RenderCard | None]:
        """The card count and top render-card of a deck, from the active render source."""
        for deck_key, count, top in self._render_decks():
            if deck_key == key:
                return count, top
        return 0, None

    def zone_render_cards(self, key: ZoneKey) -> list[RenderCard]:
        """The render-cards held in a zone (e.g. a discard or banish pile), bottom to top, from the
        active render source. Empty if the zone is absent."""
        for zone_key, cards in self._render_zones():
            if zone_key == key:
                return cards
        return []

    def hand_count(self, seat: PlayerId) -> int:
        """How many cards ``seat`` holds, from the active render source."""
        return len(self.zone_render_cards(ZoneKey(seat, ZoneRole.HAND)))

    def _reconcile_sprites(self) -> None:
        w, h = self._canvas_size()
        wanted: set[str] = set()
        rendered = list(self._render_battlefield())
        home = self._home_positions(rendered, w, h)
        for rc, pos in rendered:
            tag = card_tag(rc.id)
            wanted.add(tag)
            x, y = home.get(rc.id) or to_canvas(pos, flipped=self._flipped, canvas_w=w, canvas_h=h)
            sp = self._sprites.get(tag)
            if sp is None:
                sp = CardSpriteVisual(rc, x, y, tag, images=self._images)
                self._sprites[tag] = sp
            sp.card, sp.x, sp.y = rc, x, y
            chosen = rc.id in self._selection
            sp.bowed_preview = chosen and self._selection_bows
            sp.draw(self, selected=tag in self._selected or chosen)
        for tag in set(self._sprites) - wanted:
            self._sprites.pop(tag, None)
            self._selected.discard(tag)

    def _home_positions(self, rendered, w: int, h: int) -> dict[str, tuple[int, int]]:
        """Stacked home-row positions for the unplaced cards among ``rendered``, grouped per owner:
        copies of one printed card share a column and step down by ``HOME_STACK_OFFSET``, while the
        stronghold, sensei, and distinct holdings each take their own column."""
        by_owner: dict[PlayerId | None, list[tuple[str, object]]] = {}
        for rc, pos in rendered:
            if pos is None or pos.x < 0 or pos.y < 0:
                key = getattr(rc, "printed_id", None) or rc.id
                by_owner.setdefault(rc.owner, []).append((rc.id, key))
        positions: dict[str, tuple[int, int]] = {}
        for owner, unplaced in by_owner.items():
            seat_at_bottom = (owner or self.seat) is self.seat
            positions.update(
                home_stack_positions(
                    unplaced, w, h, seat_at_bottom=seat_at_bottom, offset=HOME_STACK_OFFSET
                )
            )
        return positions

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
