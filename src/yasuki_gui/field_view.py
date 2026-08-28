import tkinter as tk
from collections.abc import Callable, Iterable
from types import MappingProxyType
from typing import NamedTuple

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BoardPos, DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.intents import Event, Intent, apply_intent
from yasuki_core.engine.redaction import ViewSnapshot
from yasuki_core.game_pieces.prints import PersonalityPrint
from yasuki_gui import theme
from yasuki_gui.config import DEFAULT_HOTKEYS, Hotkeys
from yasuki_gui.constants import ATTACH_STACK_OFFSET, CARD_H, CARD_W, HOME_STACK_OFFSET
from yasuki_gui.controller import FieldController
from yasuki_gui.layout import (
    divider_y,
    from_canvas,
    hand_box,
    home_stack_positions,
    province_positions,
    to_canvas,
    unit_tower_positions,
)
from yasuki_gui.services.allocation import Allocation
from yasuki_gui.services.hittest import resolve_tag_at as hittest_resolve_tag_at
from yasuki_gui.tags import allocation_tag, card_id_for_tag, card_tag, zone_tag
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


# The spinner drawn on a card taking a share of a division: a count and the two arrows that trade
# one creation with the other chosen cards.
ALLOCATION_TAG = "allocation"
SPINNER_W = 46
SPINNER_H = 30


class _AssignmentStep(NamedTuple):
    """The armies as they stood before one step of an assignment, for undo to put back.

    The board's selection is not part of a step: an undo re-presents the assignment, which rebuilds
    selection mode from the decision's own candidates, so any selection restored here would be
    cleared before the player saw it.

    Attributes
    ----------
    armies : list of list of str
        Each army's card ids.
    placements : dict mapping int to int
        Which battlefield each army had been sent to.
    """

    armies: list[list[str]]
    placements: dict[int, int]


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
        # Picks the player has finished making but the engine has not been told about yet. A payment
        # is answered one producer at a time so each can open its own window, and the queue is what
        # lets the player pick the whole payment in one go regardless.
        self._committed: list[str] = []
        self._armies: list[list[str]] = []
        self._army_at: dict[int, int] = {}
        # One entry per undoable step of an assignment. Gathering an army and sending it are
        # scratch work with no consequence in the game until the whole map is answered, so the
        # client is where the steps are remembered and nothing about them reaches the engine.
        self._army_history: list[_AssignmentStep] = []
        # Set instead of a plain selection when the decision divides a fixed number of creations
        # among the cards picked; it holds how many each carries, drawn as a spinner on the card.
        self._allocation: Allocation | None = None

        # Optional UI callbacks the host app installs.
        self.on_local_player_changed: Callable[[], None] | None = None
        self.apply_profile_to_panels: Callable[[], None] | None = None
        self.on_selection_changed: Callable[[], None] | None = None
        self.on_card_activated: Callable[[str], None] | None = None
        # Fires on a right-click that lands on empty board, for the rulebook abilities.
        self.on_board_menu: Callable[[], None] | None = None
        # Fire when the menu bar picks a decklist for either seat. The menu looks them up by name,
        # so they are declared here rather than left to whoever assigns them.
        self.load_deck_from_file: Callable[[str], None] | None = None
        self.load_opponent_deck_from_file: Callable[[str], None] | None = None

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
    def selection(self) -> tuple[str, ...]:
        """The ids currently selected for the pending decision, in the order they were picked. A
        division repeats an id once per creation the card carries."""
        if self._allocation is not None:
            return self._allocation.choices
        return tuple(self._selection)

    @property
    def committed(self) -> tuple[str, ...]:
        """The picks the player has finished making, in the order they were picked, still waiting to
        be sent."""
        return tuple(self._committed)

    def commit_selection(self) -> None:
        """Close the selection: the player has picked everything it means to. The picks move to the
        queue, which survives the rounds of selection mode that answering them takes."""
        self._committed = list(self._selection)
        self._selection = []

    def take_committed(self) -> str | None:
        """Pop the next queued pick, or None when the queue is spent."""
        return self._committed.pop(0) if self._committed else None

    def drop_committed(self) -> None:
        """Discard whatever is left in the queue, for a payment that ended before it was spent."""
        self._committed = []

    @property
    def armies(self) -> tuple[tuple[str, ...], ...]:
        """The armies the player has grouped, in the order they were formed.

        Assigning is a process: units are gathered into an army, the army is sent to a Province, and
        both halves can be undone until the whole map goes to the engine as one answer.
        """
        return tuple(tuple(army) for army in self._armies)

    def army_of(self, card_id: str) -> int | None:
        """Which army ``card_id`` belongs to, or None if it is not in one."""
        return next((index for index, army in enumerate(self._armies) if card_id in army), None)

    def battlefield_of_army(self, index: int) -> int | None:
        """Where army ``index`` has been sent, or None while it is still at home."""
        return self._army_at.get(index)

    def join_army(self, index: int, card_ids: Iterable[str]) -> None:
        """Bring ``card_ids`` into army ``index``, taking each out of whatever army held it."""
        joining = [card_id for card_id in card_ids if self.army_of(card_id) != index]
        for card_id in joining:
            self.leave_army(card_id)
        self._armies[index].extend(joining)
        self._selection = []

    def form_army(self, card_ids: Iterable[str]) -> None:
        """Gather ``card_ids`` into an army, and clear the selection ready for the next one.

        Units already in an army leave it first, so a unit belongs to exactly one — the engine
        refuses the same unit at two battlefields, and an army is what carries it to one.
        """
        joining = list(dict.fromkeys(card_ids))
        for card_id in joining:
            self.leave_army(card_id)
        if joining:
            self._armies.append(joining)
        self._selection = []

    def leave_army(self, card_id: str) -> None:
        """Take ``card_id`` out of whatever army holds it, disbanding an army left empty."""
        index = self.army_of(card_id)
        if index is None:
            return
        self._armies[index].remove(card_id)
        if not self._armies[index]:
            self._disband(index)

    def _disband(self, index: int) -> None:
        """Drop army ``index``, keeping the remaining armies' battlefields with them."""
        self._armies.pop(index)
        self._army_at = {
            (army - 1 if army > index else army): battlefield
            for army, battlefield in self._army_at.items()
            if army != index
        }

    def send_army(self, index: int, battlefield: int) -> None:
        """Send army ``index`` to ``battlefield``."""
        self._army_at[index] = battlefield

    def recall_army(self, index: int) -> None:
        """Bring army ``index`` home, leaving it grouped."""
        self._army_at.pop(index, None)

    def assigned_units(self) -> dict[str, int]:
        """Each unit in an army that has been sent somewhere, to the battlefield it was sent to.
        Units in an army still at home are not assigned and stay out of the answer."""
        return {
            card_id: battlefield
            for index, battlefield in self._army_at.items()
            for card_id in self._armies[index]
        }

    def remember_armies(self) -> None:
        """Record the armies as they stand, so the step about to be taken can be undone."""
        self._army_history.append(
            _AssignmentStep(
                armies=[list(army) for army in self._armies], placements=dict(self._army_at)
            )
        )

    def undo_armies(self) -> bool:
        """Put the armies back as they were before the last remembered step, and say whether there
        was one to go back to."""
        if not self._army_history:
            return False
        self._armies, self._army_at = self._army_history.pop()
        return True

    def disband_armies(self) -> None:
        """Forget every army, for an assignment that ended or was started over.

        The history goes with them: once the assignment is answered its steps are no longer the
        player's to take back.
        """
        self._armies = []
        self._army_at = {}
        self._army_history = []

    def begin_selection(self, candidates: Iterable[str], *, render_bowed: bool = False) -> None:
        """Enter selection mode: only ``candidates`` are selectable, none chosen yet. When
        ``render_bowed`` is set, selected cards preview as bowed (a producer tapped to pay).

        The committed queue is left alone: each round of a payment re-enters selection mode, and
        clearing it here would spend only the first pick the player made."""
        self._selectable = frozenset(candidates)
        self._selection = []
        self._selection_bows = render_bowed
        self._allocation = None

    def begin_allocation(self, candidates: Iterable[str], total: int) -> None:
        """Enter selection mode to divide ``total`` creations among ``candidates``: clicking one
        takes it into the division, and a spinner on each shows how many it carries."""
        self.begin_selection(candidates)
        self._allocation = Allocation(total)

    def adjust_allocation(self, card_id: str, step: int) -> None:
        """Move one creation onto ``card_id`` (``step`` above zero) or off it, and notify the
        listener. Taking one from a card that carries a single creation is refused: unchosen is what
        carrying none means, and the click that says so is the one on the card itself."""
        if self._allocation is None:
            return
        if step > 0:
            self._allocation.increase(card_id)
        else:
            self._allocation.decrease(card_id)
        if self.on_selection_changed is not None:
            self.on_selection_changed()

    def end_selection(self) -> None:
        """Leave selection mode and clear the selection. The committed queue is left alone: a
        payment leaves selection mode between rounds and still has picks to spend."""
        self._selectable = None
        self._selection = []
        self._selection_bows = False
        self._allocation = None
        self.delete(ALLOCATION_TAG)

    def is_selectable(self, candidate: str) -> bool:
        """Whether ``candidate`` — a card id or a zone token — is one the pending decision offers."""
        return self._selectable is not None and candidate in self._selectable

    def toggle_selection(self, card_id: str) -> None:
        """Toggle ``card_id`` in the selection if it is a candidate, and notify the listener."""
        if self._selectable is None or card_id not in self._selectable:
            return
        if self._allocation is not None:
            self._allocation.toggle(card_id)
        elif card_id in self._selection:
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
        """The cards the board draws in play: everything standing at home.

        A unit assigned to a battlefield is drawn there instead — by the battle view, which is the
        only surface that can show four battlefields legibly — so the board leaves it out rather than
        drawing it in two places at once.
        """
        if self._snapshot is not None:
            for bf_view in self._snapshot.battlefield:
                # Through the render card, since a redacted card carries its id under another name.
                rendered = to_render_card(bf_view.card)
                if not self._at_home(rendered.id):
                    continue
                yield rendered, bf_view.pos
        else:
            for card in self.state.battlefield.cards:
                yield to_render_card(card), self.state.positions.get(card.id)

    def _at_home(self, card_id: str) -> bool:
        """Whether ``card_id`` stands in a seat's home rather than at a battlefield.

        A card with no recorded location is at home, which is what every card is until an attack
        moves it — unless the player has sent it to a battlefield and the engine has not been told
        yet, which is a decision already made and so already a card the board has given up.
        """
        if self.army_of(card_id) is not None and card_id in self.assigned_units():
            return False
        location = self._snapshot.locations.get(card_id) if self._snapshot is not None else None
        return location is None or location.is_home

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
            zv.selected_ids = self.selection
            zv.slot_selected = key.token in self.selection
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
        rendered = self._unit_draw_order(list(self._render_battlefield()))
        home = self._home_positions(rendered, w, h)
        placed = {
            rc.id: home.get(rc.id) or to_canvas(pos, flipped=self._flipped, canvas_w=w, canvas_h=h)
            for rc, pos in rendered
        }
        placed.update(self._unit_positions(placed, {rc.id: rc.owner for rc, _ in rendered}))
        placed.update(self._province_attachment_positions(w, h))
        for rc, pos in rendered:
            tag = card_tag(rc.id)
            wanted.add(tag)
            x, y = placed[rc.id]
            sp = self._sprites.get(tag)
            if sp is None:
                sp = CardSpriteVisual(rc, x, y, tag, images=self._images)
                self._sprites[tag] = sp
            sp.card, sp.x, sp.y = rc, x, y
            chosen = self._is_chosen(rc.id)
            sp.bowed_preview = chosen and self._selection_bows
            sp.army_ring = self._army_ring(rc.id)
            sp.draw(self, selected=tag in self._selected or chosen)
        self._sink_province_attachments()
        for tag in set(self._sprites) - wanted:
            self._sprites.pop(tag, None)
            self._selected.discard(tag)
        self._draw_allocation()

    def _army_ring(self, card_id: str) -> str | None:
        """The colour of the army ``card_id`` is gathered into, or None when it is in none. Colours
        cycle, so a seat that gathers more armies than there are still tells them apart locally."""
        army = self.army_of(card_id)
        return None if army is None else theme.ARMY_RINGS[army % len(theme.ARMY_RINGS)]

    def _is_chosen(self, card_id: str) -> bool:
        """Whether ``card_id`` is part of the answer being assembled for the pending decision."""
        if self._allocation is not None:
            return self._allocation.amount(card_id) > 0
        return card_id in self._selection

    def _draw_allocation(self) -> None:
        """Draw a spinner on each card taking a share of a division: how many it carries, and the
        two arrows that trade one with the other chosen cards.

        Drawn over the sprites rather than by them, because it belongs to the decision being
        answered rather than to the card, and it has to sit above a unit's stacked attachments. It
        runs last in the sprite pass for the same reason: a sprite redraws by clearing its whole
        card tag, which the spinner shares so that a click on the count still reaches the card.
        """
        self.delete(ALLOCATION_TAG)
        if self._allocation is None:
            return
        for card_id in self._allocation.chosen:
            sprite = self._sprites.get(card_tag(card_id))
            if sprite is not None:
                self._draw_spinner(self._allocation, card_id, sprite.x, sprite.y)

    def _draw_spinner(self, allocation: Allocation, card_id: str, x: int, y: int) -> None:
        left, right = x - SPINNER_W // 2, x + SPINNER_W // 2
        top, bottom = y - SPINNER_H // 2, y + SPINNER_H // 2
        arrow_left = x + SPINNER_W // 6  # the box splits into a count and a column of two arrows
        # The box covers the middle of the card it sits on, so it carries the card's own tag: a
        # click on the count still reads as a click on the card, which is how it leaves the division.
        on_card = (ALLOCATION_TAG, card_tag(card_id))
        self.create_rectangle(
            left, top, right, bottom, fill=theme.COUNT_BG, outline=theme.SELECT, tags=on_card
        )
        self.create_text(
            (left + arrow_left) // 2,
            y,
            text=str(allocation.amount(card_id)),
            fill=theme.COUNT_FG,
            font=theme.serif(13, "bold"),
            tags=on_card,
        )
        arrows = (
            ("\u25b2", 1, allocation.may_increase(card_id)),
            ("\u25bc", -1, allocation.may_decrease(card_id)),
        )
        for glyph, step, enabled in arrows:
            arrow_top = top if step > 0 else y
            arrow_bottom = y if step > 0 else bottom
            # An arrow with nothing to trade is drawn dim and left untagged, so it is inert rather
            # than falling through to the card and quietly undoing the division.
            tags = (ALLOCATION_TAG, allocation_tag(card_id, step)) if enabled else (ALLOCATION_TAG,)
            # A rectangle behind the glyph, so the whole half of the box is a click target rather
            # than the few pixels the arrow itself covers.
            self.create_rectangle(
                arrow_left,
                arrow_top,
                right,
                arrow_bottom,
                fill=theme.COUNT_BG,
                outline="",
                tags=tags,
            )
            self.create_text(
                (arrow_left + right) // 2,
                (arrow_top + arrow_bottom) // 2,
                text=glyph,
                fill=theme.COUNT_FG if enabled else theme.INK_DIM,
                font=theme.serif(9),
                tags=tags,
            )

    def _at_bottom(self, owner: PlayerId | None) -> bool:
        """Whether ``owner``'s cards lay out along the near edge. An ownerless card sits with the
        viewer's, which is where the board puts anything it cannot attribute."""
        return (owner or self.seat) is self.seat

    def _units(self) -> dict[str, str]:
        """Unit membership from whichever source is rendering: attached card id to Personality."""
        return self._snapshot.units if self._snapshot is not None else self.state.units

    def _sink_province_attachments(self) -> None:
        """Push each Fortification below the Province tableau, so the card standing in the slot
        covers it and only the fanned-out part shows.

        Zones are drawn before sprites, which would otherwise leave a Fortification sitting on top
        of the Province it defends — the reverse of the table, where it is tucked underneath.
        """
        for card_id in self._province_attachments():
            tag = card_tag(card_id)
            if self.find_withtag(tag):
                self.tag_lower(tag, "zone")

    def _province_attachments(self) -> dict[str, ZoneKey]:
        """Province membership from whichever source is rendering: card id to the Province slot."""
        source = self._snapshot if self._snapshot is not None else self.state
        return source.province_attachments

    def _province_attachment_positions(self, w: int, h: int) -> dict[str, tuple[int, int]]:
        """Where each Fortification sits: fanned inboard from the Province slot it defends.

        Inboard rather than up, because a Province is the outermost row of its seat and a stack
        growing outward would leave the board. The slot itself holds a Dynasty card that refills
        behind the Fortification, so the fan starts one step off the slot rather than on it.
        """
        attached = self._province_attachments()
        if not attached:
            return {}
        by_slot: dict[ZoneKey, list[str]] = {}
        for card_id, key in attached.items():
            by_slot.setdefault(key, []).append(card_id)
        positions: dict[str, tuple[int, int]] = {}
        for owner, ordered in self._province_keys_by_owner().items():
            inboard = -1 if self._at_bottom(owner) else 1
            slots = province_positions(w, h, len(ordered), seat_at_bottom=self._at_bottom(owner))
            for index, key in enumerate(ordered):
                members = by_slot.get(key)
                if not members:
                    continue
                x, y = slots[index]
                for step, card_id in enumerate(members, start=1):
                    positions[card_id] = (x, y + inboard * step * ATTACH_STACK_OFFSET)
        return positions

    def _unit_members(self) -> dict[str, list[str]]:
        """Each Personality's attached cards, in attach order."""
        members: dict[str, list[str]] = {}
        for card_id, personality_id in self._units().items():
            members.setdefault(personality_id, []).append(card_id)
        return members

    def _unit_draw_order(self, rendered: list[tuple]) -> list[tuple]:
        """``rendered`` with each Personality's attachments moved directly ahead of him, highest
        first, so every card in the stack covers the one it rides and only title bars show.

        The stack fans up, so the last attachment sits highest and furthest back and has to be drawn
        before the rest of the tower — matching the web board's ``drawTower``.
        """
        units = self._units()
        if not units:
            return rendered
        held: dict[str, list[tuple]] = {}
        loose: list[tuple] = []
        for entry in rendered:
            personality_id = units.get(entry[0].id)
            if personality_id is None:
                loose.append(entry)
            else:
                held.setdefault(personality_id, []).append(entry)
        ordered: list[tuple] = []
        for entry in loose:
            card, _ = entry
            ordered.extend(reversed(held.pop(card.id, ())))
            ordered.append(entry)
        for stranded in held.values():  # its Personality is not on this board
            ordered.extend(stranded)
        return ordered

    def _unit_positions(
        self, placed: dict[str, tuple[int, int]], owners: dict[str, PlayerId | None]
    ) -> dict[str, tuple[int, int]]:
        """Where a unit's cards sit: the attachments fanned up behind their Personality, so each
        title bar clears the card riding it, and the Personality dropped by the height they add.

        Both seats' Personalities stand against the divider, so a stack fanning up off the near
        seat's row would climb into the opponent's half. Sinking the Personality by the tower's own
        height leaves the top of the stack where he stood and grows the unit downward instead. The
        far seat's row already fans away from the divider, so its units stay put.

        Returns a position per attachment, plus the Personality's when he moves. A caller overlays
        these on the home-row placement.
        """
        positions: dict[str, tuple[int, int]] = {}
        for personality_id, members in self._unit_members().items():
            if personality_id not in placed:
                continue
            x, y = placed[personality_id]
            sink = self._at_bottom(owners.get(personality_id))
            leader, attached = unit_tower_positions(x, y, len(members), sink=sink)
            if sink:
                positions[personality_id] = leader
            for card_id, spot in zip(members, attached):
                if card_id in placed:
                    positions[card_id] = spot
        return positions

    def _home_positions(self, rendered, w: int, h: int) -> dict[str, tuple[int, int]]:
        """Stacked home-row positions for the unplaced cards among ``rendered``, grouped per owner:
        copies of one printed card share a column and step down by ``HOME_STACK_OFFSET``, while the
        stronghold, sensei, and distinct holdings each take their own column. Personalities lay out
        in the front (personalities) row; everything else in the holdings row. Attached cards are
        left out — :meth:`_unit_positions` and :meth:`_province_attachment_positions` place them on
        what they hang from."""
        holdings: dict[PlayerId | None, list[tuple[str, object]]] = {}
        personalities: dict[PlayerId | None, list[tuple[str, object]]] = {}
        # An attachment rides its Personality or its Province wherever that stands, so it takes no
        # column of its own — giving it one would shove the real Holdings sideways to make room.
        attached = self._units().keys() | self._province_attachments().keys()
        for rc, pos in rendered:
            if rc.id in attached:
                continue
            if pos is None or pos.x < 0 or pos.y < 0:
                key = getattr(rc, "printed_id", None) or rc.id
                bucket = (
                    personalities
                    if isinstance(getattr(rc, "printed", None), PersonalityPrint)
                    else holdings
                )
                bucket.setdefault(rc.owner, []).append((rc.id, key))
        positions: dict[str, tuple[int, int]] = {}
        for personality_row, by_owner in ((False, holdings), (True, personalities)):
            for owner, unplaced in by_owner.items():
                seat_at_bottom = self._at_bottom(owner)
                positions.update(
                    home_stack_positions(
                        unplaced,
                        w,
                        h,
                        seat_at_bottom=seat_at_bottom,
                        offset=HOME_STACK_OFFSET,
                        personality_row=personality_row,
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
