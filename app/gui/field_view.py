import tkinter as tk
from types import MappingProxyType

from app.game_pieces.cards import L5RCard
from app.game_pieces.deck import Deck
from app.gui.constants import (
    CANVAS_BG,
    CARD_W,
)
from app.gui.config import Hotkeys, DEFAULT_HOTKEYS
from app.engine.zones import Zone, HandZone, ProvinceZone
from app.gui.visuals import DeckVisual, ZoneVisual, CardSpriteVisual, HandVisual
from app.gui.controller import FieldController
from app.gui.services.hittest import resolve_tag_at as hittest_resolve_tag_at
from app.gui.services.actions import Redraw
from app.gui.ui.images import ImageProvider
from app.engine.players import PlayerId


class FieldView(tk.Canvas):
    """
    Tkinter canvas view.

    Owns drawing and lightweight selection visuals.
    """

    def __init__(self, master: tk.Misc, width: int = 800, height: int = 600):
        super().__init__(master, width=width, height=height, bg=CANVAS_BG, highlightthickness=0)
        self._sprites: dict[str, CardSpriteVisual] = {}
        self._decks: dict[str, DeckVisual] = {}
        self._zones: dict[str, ZoneVisual] = {}
        self._hands: dict[str, HandVisual] = {}
        self._battlefield_zone: Zone | None = None
        self._next_id = 1

        self.local_player: PlayerId = PlayerId.P1

        # Draw-only state
        self._hotkeys: Hotkeys = DEFAULT_HOTKEYS

        # Selection (visual only)
        self._selected: set[str] = set()
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_rect: int | None = None

        self._controller = FieldController(self)
        self._images = ImageProvider(self)

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

    def resolve_tag_at(self, event: tk.Event) -> str | None:
        return hittest_resolve_tag_at(self, event)

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

    def apply_redraw(self, r: Redraw) -> None:
        """Apply a Redraw: remove zones, then redraw zones, decks, then sprites.

        Zones and decks form the background, sprites the foreground.
        Also handles province relayout when zones are removed.
        """
        zones_to_redraw = set(r.zones)
        decks_to_redraw = set(r.decks)
        sprites_to_redraw = set(r.sprites)

        # 1) Create requested zones (collect their tags so callers can assert later if needed)
        created_tags: list[str] = []
        owners_to_relayout: set[PlayerId | None] = set()
        for zone, x, y, w, h in r.new_zones:
            ztag = self.add_zone(zone, x=x, y=y, w=w, h=h)
            created_tags.append(ztag)
            zones_to_redraw.add(ztag)
            # Track province owners for relayout
            if isinstance(zone, ProvinceZone):
                owners_to_relayout.add(getattr(zone, "owner", None))

        # After creation, relayout provinces for affected owners
        for own in owners_to_relayout:
            moved = self._relayout_provinces_centered(own)
            zones_to_redraw.update(moved)

        # 2) Remove zones, then relayout provinces and include any moved province in redraw
        if r.remove_zones:
            for ztag in r.remove_zones:
                # Capture owner before removal for targeted relayout
                owner_removed: PlayerId | None = None
                zv = self._zones.get(ztag)
                if zv is not None and isinstance(zv.zone, ProvinceZone):
                    owner_removed = getattr(zv.zone, "owner", None)
                try:
                    self.delete(ztag)
                except Exception:
                    pass
                self._zones.pop(ztag, None)
                if owner_removed not in owners_to_relayout:
                    owners_to_relayout.add(owner_removed)
            # relayout centered after removals as well for affected owners
            for own in owners_to_relayout:
                moved = self._relayout_provinces_centered(own)
                zones_to_redraw.update(moved)

        # 3) Redraw background (zones, decks) then 4) foreground (sprites)
        for z in zones_to_redraw:
            self.redraw_zone(z)
        for d in decks_to_redraw:
            self.redraw_deck(d)
        for s in sprites_to_redraw:
            self._redraw_sprite(s)

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

    def configure_hotkeys(self, hotkeys: Hotkeys) -> None:
        # Delegate to controller so hotkeys are global
        self._hotkeys = hotkeys
        if hasattr(self, "_controller"):
            self._controller.configure_hotkeys(hotkeys)

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
        deck = DeckVisual(deck, x, y, tag, label, images=self._images)
        # Propagate owner to deck visual if present in label (optional external wiring)
        deck.owner = getattr(deck, "owner", None)  # type: ignore[attr-defined]
        self._decks[tag] = deck
        deck.draw(self)
        return tag

    def add_zone(self, zone: Zone, x: int, y: int, w: int, h: int) -> str:
        tag = f"zone:{self._next_id}"
        self._next_id += 1
        if isinstance(zone, HandZone):
            hv = HandVisual(zone, x, y, w, h, tag, images=self._images)
            self._hands[tag] = hv
            hv.draw(self)
        else:
            zv = ZoneVisual(zone, x, y, w, h, tag, images=self._images)
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

    def redraw_all(self) -> None:
        """
        Redraw all decks, zones (including hands), and refresh sprites.
        """
        # Background visuals first
        for ztag in list(self._zones.keys()):
            self._redraw_zone(ztag)
        for htag in list(self._hands.keys()):
            self._redraw_zone(htag)
        for dtag in list(self._decks.keys()):
            self._redraw_deck(dtag)
        # Foreground sprites
        for stag in list(self._sprites.keys()):
            # Use refresh to preserve selection overlay
            sp = self._sprites.get(stag)
            if sp is not None:
                sp.refresh_face_state(self)

    def flip_orientation(self) -> None:
        """Rotate the entire field 180 degrees around the canvas center.
        Transforms x/y for decks, zones (including hands), and sprites.
        """
        try:
            W, H = self.winfo_width(), self.winfo_height()
        except Exception:
            return
        # Flip background visuals
        for dv in self._decks.values():
            dv.x, dv.y = W - dv.x, H - dv.y
        for zv in self._zones.values():
            zv.x, zv.y = W - zv.x, H - zv.y
        for hv in self._hands.values():
            hv.x, hv.y = W - hv.x, H - hv.y
        # Flip any battlefield sprites
        for sp in self._sprites.values():
            sp.x, sp.y = W - sp.x, H - sp.y

    def _provinces_center_and_sorted(
        self, owner: PlayerId | None
    ) -> tuple[int, list[tuple[str, ZoneVisual]]]:
        """Return a center x and the list of (tag, ZoneVisual) for provinces of a given owner,
        sorted by current x. Center is derived from that owner's decks when possible.
        """
        try:
            W = self.winfo_width()
        except Exception:
            W = 800
        # find this owner's deck xs first
        dyn_x = None
        fate_x = None
        for dv in self._decks.values():
            if getattr(dv, "owner", None) != owner:
                continue
            label = getattr(dv, "label", "")
            if "Dynasty" in label and dyn_x is None:
                dyn_x = dv.x
            elif "Fate" in label and fate_x is None:
                fate_x = dv.x
        if dyn_x is not None and fate_x is not None:
            center_x = (dyn_x + fate_x) // 2
        elif dyn_x is not None:
            center_x = dyn_x
        elif fate_x is not None:
            center_x = fate_x
        else:
            # fallback to canvas center if decks missing or owner None
            center_x = W // 2
        provinces = [
            (tag, zv)
            for tag, zv in self._zones.items()
            if isinstance(zv.zone, ProvinceZone) and getattr(zv.zone, "owner", None) == owner
        ]
        provinces.sort(key=lambda it: it[1].x)
        return center_x, provinces

    def _relayout_provinces_centered(self, owner: PlayerId | None) -> set[str]:
        """Center-justify provinces for a given owner. Returns the set of province tags moved."""
        center_x, provinces = self._provinces_center_and_sorted(owner)
        n = len(provinces)
        moved: set[str] = set()
        if n == 0:
            return moved
        # target x positions: center-justified columns spaced by CARD_W
        offsets = [(i - (n - 1) / 2) * CARD_W for i in range(n)]
        for (tag, zv), off in zip(provinces, offsets):
            new_x = int(center_x + off)
            if zv.x != new_x:
                zv.x = new_x
                moved.add(tag)
        return moved
