from dataclasses import dataclass, field
from typing import Protocol, Literal, Any
from collections.abc import Callable, Mapping
from collections.abc import Iterable

import tkinter as tk
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.gui.constants import CARD_W, CARD_H, DRAW_OFFSET
from app.gui.config import DEFAULT_HOTKEYS as HK
from app.engine.zones import DynastyDiscardZone, ProvinceZone, HandZone, Zone, FateDiscardZone
from app.gui.services.hittest import deck_expected_side
from app.gui.ui.images import ImageProvider
from app.gui.ui.dialogs import Dialogs
from app.engine.players import PlayerId


class HasView(Protocol):
    """Minimal protocol for views that support actions."""

    sprites: Mapping[str, Any]
    decks: Mapping[str, Any]
    zones: Mapping[str, Any]
    hands: Mapping[str, Any]
    local_player: PlayerId

    # minimal draw APIs
    def redraw_deck(self, tag: str) -> None: ...
    def redraw_zone(self, tag: str) -> None: ...
    def remove_card_sprite(self, tag: str) -> None: ...
    def add_card(self, card: L5RCard, x: int, y: int) -> str: ...


@dataclass(frozen=True)
class ActionContext:
    """Exactly one of these should be set depending on context."""

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


@dataclass(frozen=True)
class Redraw:
    decks: set[str] = field(default_factory=set)
    zones: set[str] = field(default_factory=set)
    sprites: set[str] = field(default_factory=set)
    # zones to remove from view (for destroy operations)
    remove_zones: set[str] = field(default_factory=set)
    # zones to create: list of (Zone, x, y, w, h)
    new_zones: list[tuple[Zone, int, int, int, int]] = field(default_factory=list)


class FieldActions:
    def __init__(self, view: HasView):
        self.view = view

    def _owns_card(self, card: L5RCard) -> bool:
        owner = getattr(card, "owner", None)
        lp = getattr(self.view, "local_player", None)
        return owner is None or lp is None or owner == lp

    def _zone_owned_by_card(self, zone: Zone, card: L5RCard) -> bool:
        z_owner = getattr(zone, "owner", None)
        c_owner = getattr(card, "owner", None)
        return z_owner is None or c_owner is None or z_owner == c_owner

    def _zone_owned_by_local(self, zone: Zone) -> bool:
        z_owner = getattr(zone, "owner", None)
        lp = getattr(self.view, "local_player", None)
        return z_owner is None or lp is None or z_owner == lp

    def _deck_owned_by_local(self, dtag: str) -> bool:
        dv = self.view.decks.get(dtag)
        if not dv:
            return False
        d_owner = getattr(dv, "owner", None)
        lp = getattr(self.view, "local_player", None)
        return d_owner is None or lp is None or d_owner == lp

    def make_deck_search_draw_cb(self, dtag: str):
        v = self.view
        dv = v.decks[dtag]

        def draw_cb(idx_in_deck: int) -> None:
            # Permission: deck must be owned by local
            if not self._deck_owned_by_local(dtag):
                return
            # Remove card from deck at index and place as battlefield sprite near deck
            if idx_in_deck < 0 or idx_in_deck >= len(dv.deck.cards):
                return
            card = dv.deck.cards.pop(idx_in_deck)
            # Enforce owner matching if both set
            d_owner = getattr(dv, "owner", None)
            c_owner = getattr(card, "owner", None)
            if d_owner is not None and c_owner is not None and d_owner != c_owner:
                dv.deck.cards.insert(idx_in_deck, card)
                return
            card.turn_face_down()

            offset = CARD_W + DRAW_OFFSET
            draw_x = dv.x - offset if card.side is Side.FATE else dv.x + offset
            draw_y = dv.y
            v.add_card(card, draw_x, draw_y)
            # Trigger redraw of deck via view API
            try:
                v.apply_redraw(Redraw(decks={dtag}))  # type: ignore[attr-defined]
            except Exception:
                # fallback if view doesn't expose apply_redraw
                v.redraw_deck(dtag)

        return draw_cb

    def _remove_from_all_zones(self, card: L5RCard) -> None:
        v = self.view
        # Prefer view helper if available
        if hasattr(v, "_remove_from_all_zones"):
            try:
                getattr(v, "_remove_from_all_zones")(card)  # type: ignore[misc]
                return
            except Exception:
                pass

        bf = getattr(v, "battlefield_zone", None)
        if bf is None:
            bf = getattr(v, "_battlefield_zone", None)
        if bf is not None:
            try:
                bf.remove(card)
            except Exception:
                pass
        for zv in v.zones.values():
            try:
                zv.zone.remove(card)
            except Exception:
                pass
        for hv in v.hands.values():
            try:
                hv.zone.remove(card)
            except Exception:
                pass

    def _find_zone_tag_by_type(self, zone_type: type[Zone]) -> str | None:
        v = self.view
        if hasattr(v, "_find_zone_tag_by_type"):
            try:
                return getattr(v, "_find_zone_tag_by_type")(zone_type)  # type: ignore[misc]
            except Exception:
                pass
        for tag, zv in v.zones.items():
            if isinstance(zv.zone, zone_type):
                return tag
        for tag, hv in v.hands.items():
            if isinstance(hv.zone, zone_type):
                return tag
        return None

    def _find_zone_tag_by_type_and_owner(
        self, zone_type: type[Zone], owner: PlayerId | None
    ) -> str | None:
        """Find a zone tag by type, preferring zones owned by `owner` when provided.
        Falls back to any zone of that type if no owner-matching zone found.
        Searches hands first for HandZone, else zones.
        """
        v = self.view
        # Prefer matching owner
        # Hands first if requesting HandZone
        if zone_type is HandZone:
            for tag, hv in v.hands.items():
                if isinstance(hv.zone, HandZone) and getattr(hv.zone, "owner", None) == owner:
                    return tag
            # fallback: any hand
            for tag, hv in v.hands.items():
                if isinstance(hv.zone, HandZone):
                    return tag
            return None
        # Non-hand zones
        for tag, zv in v.zones.items():
            if isinstance(zv.zone, zone_type) and getattr(zv.zone, "owner", None) == owner:
                return tag
        # fallback: any such zone
        for tag, zv in v.zones.items():
            if isinstance(zv.zone, zone_type):
                return tag
        return None

    def _find_deck_tag_by_side(self, side: Side) -> str | None:
        v = self.view
        # Prefer by label
        for tag, dv in v.decks.items():
            label = getattr(dv, "label", "")
            if side is Side.FATE and "Fate" in label:
                return tag
            if side is Side.DYNASTY and "Dynasty" in label:
                return tag
        # Fallback: infer from top card side
        for tag, dv in v.decks.items():
            try:
                top = dv.deck.peek(1)
                if top and top[0].side is side:
                    return tag
            except Exception:
                continue
        return None

    def _targets_for(self, tag: str, selection: set[str]) -> set[str]:
        return selection if (selection and tag in selection) else {tag}

    def toggle_bow(self, tag: str, selection: set[str]) -> Redraw:
        rd = Redraw()
        for t in self._targets_for(tag, selection):
            sp = self.view.sprites.get(t)
            if not sp:
                continue
            if not self._owns_card(sp.card):
                continue
            if sp.card.bowed:
                sp.card.unbow()
            else:
                sp.card.bow()
            rd.sprites.add(t)
        return rd

    def toggle_flip(self, tag: str, selection: set[str]) -> Redraw:
        rd = Redraw()
        for t in self._targets_for(tag, selection):
            sp = self.view.sprites.get(t)
            if not sp:
                continue
            if not self._owns_card(sp.card):
                continue
            if sp.card.face_up:
                sp.card.turn_face_down()
            else:
                sp.card.turn_face_up()
            rd.sprites.add(t)
        return rd

    def toggle_invert(self, tag: str, selection: set[str]) -> Redraw:
        rd = Redraw()
        for t in self._targets_for(tag, selection):
            sp = self.view.sprites.get(t)
            if not sp:
                continue
            if not self._owns_card(sp.card):
                continue
            if sp.card.inverted:
                sp.card.uninvert()
            else:
                sp.card.invert()
            rd.sprites.add(t)
        return rd

    # Override public API to accept card sprite tags (string), ensuring compatibility with tests
    def send_to_hand(self, card_tag: str) -> Redraw:  # type: ignore[override]
        rd = Redraw()
        v = self.view
        sp = v.sprites.get(card_tag)
        if not sp:
            return rd
        if not self._owns_card(sp.card):
            return rd
        ztag = self._find_zone_tag_by_type(HandZone)
        if not ztag:
            return rd
        hv = v.hands.get(ztag)
        if not hv or not hv.zone.has_capacity():
            return rd
        if not self._zone_owned_by_local(hv.zone) or not self._zone_owned_by_card(hv.zone, sp.card):
            return rd
        self._remove_from_all_zones(sp.card)
        sp.card.turn_face_down()
        hv.zone.add(sp.card)
        v.remove_card_sprite(card_tag)
        rd.zones.add(ztag)
        return rd

    def send_to_fate_discard(self, card_tag: str) -> Redraw:  # type: ignore[override]
        rd = Redraw()
        v = self.view
        sp = v.sprites.get(card_tag)
        if not sp:
            return rd
        if not self._owns_card(sp.card):
            return rd
        if sp.card.side is not Side.FATE:
            return rd
        ztag = self._find_zone_tag_by_type(FateDiscardZone)
        if not ztag:
            return rd
        zv = v.zones.get(ztag)
        if not zv or not zv.zone.has_capacity():
            return rd
        if not self._zone_owned_by_local(zv.zone) or not self._zone_owned_by_card(zv.zone, sp.card):
            return rd
        self._remove_from_all_zones(sp.card)
        zv.zone.add(sp.card)
        v.remove_card_sprite(card_tag)
        rd.zones.add(ztag)
        return rd

    def send_to_dynasty_discard(self, card_tag: str) -> Redraw:  # type: ignore[override]
        rd = Redraw()
        v = self.view
        sp = v.sprites.get(card_tag)
        if not sp:
            return rd
        if not self._owns_card(sp.card):
            return rd
        if sp.card.side is not Side.DYNASTY:
            return rd
        ztag = self._find_zone_tag_by_type(DynastyDiscardZone)
        if not ztag:
            return rd
        zv = v.zones.get(ztag)
        if not zv or not zv.zone.has_capacity():
            return rd
        if not self._zone_owned_by_local(zv.zone) or not self._zone_owned_by_card(zv.zone, sp.card):
            return rd
        self._remove_from_all_zones(sp.card)
        zv.zone.add(sp.card)
        v.remove_card_sprite(card_tag)
        rd.zones.add(ztag)
        return rd

    def send_to_deck_top(self, card_tag: str) -> Redraw:  # type: ignore[override]
        rd = Redraw()
        v = self.view
        sp = v.sprites.get(card_tag)
        if not sp:
            return rd
        if not self._owns_card(sp.card):
            return rd
        dtag = self._find_deck_tag_by_side(sp.card.side)
        if not dtag:
            return rd
        if not self._deck_owned_by_local(dtag):
            return rd
        dv = v.decks[dtag]
        d_owner = getattr(dv, "owner", None)
        c_owner = getattr(sp.card, "owner", None)
        if d_owner is not None and c_owner is not None and d_owner != c_owner:
            return rd
        self._remove_from_all_zones(sp.card)
        sp.card.turn_face_down()
        dv.deck.add_to_top([sp.card])
        v.remove_card_sprite(card_tag)
        rd.decks.add(dtag)
        return rd

    def send_to_deck_bottom(self, card_tag: str) -> Redraw:  # type: ignore[override]
        rd = Redraw()
        v = self.view
        sp = v.sprites.get(card_tag)
        if not sp:
            return rd
        if not self._owns_card(sp.card):
            return rd
        dtag = self._find_deck_tag_by_side(sp.card.side)
        if not dtag:
            return rd
        if not self._deck_owned_by_local(dtag):
            return rd
        dv = v.decks[dtag]
        d_owner = getattr(dv, "owner", None)
        c_owner = getattr(sp.card, "owner", None)
        if d_owner is not None and c_owner is not None and d_owner != c_owner:
            return rd
        self._remove_from_all_zones(sp.card)
        sp.card.turn_face_down()
        dv.deck.add_to_bottom([sp.card])
        rd.decks.add(dtag)
        return rd

    def zone_flip_up(self, ztag: str) -> Redraw:
        rd = Redraw()
        zv = self.view.zones.get(ztag)
        if not zv or not zv.zone.cards:
            return rd
        if not self._zone_owned_by_local(zv.zone):
            return rd
        top = zv.zone.cards[-1]
        top.turn_face_up()
        rd.zones.add(ztag)
        return rd

    def zone_flip_down(self, ztag: str) -> Redraw:
        rd = Redraw()
        zv = self.view.zones.get(ztag)
        if not zv or not zv.zone.cards:
            return rd
        if not self._zone_owned_by_local(zv.zone):
            return rd
        top = zv.zone.cards[-1]
        top.turn_face_down()
        rd.zones.add(ztag)
        return rd

    def zone_fill(self, ztag: str) -> Redraw:
        rd = Redraw()
        zv = self.view.zones.get(ztag)
        if not zv:
            return rd
        if not self._zone_owned_by_local(zv.zone):
            return rd
        zone = zv.zone
        if not getattr(zone, "has_capacity", lambda: True)():
            return rd
        allowed = getattr(zone, "allowed_side", None)
        if allowed is not None and allowed is not Side.DYNASTY:
            return rd
        # find dynasty deck using helper for consistent behavior
        deck_tag: str | None = self._find_deck_tag_by_side(Side.DYNASTY)
        if deck_tag is None:
            return rd
        if not self._deck_owned_by_local(deck_tag):
            return rd
        dv = self.view.decks[deck_tag]
        card = dv.deck.draw_one()
        if card is None:
            return rd
        # Ensure zone owner matches card owner if both set
        if not self._zone_owned_by_card(zone, card):
            dv.deck.add_to_top([card])
            return rd
        # Province cards: ensure unbowed, draw face down
        if isinstance(zone, ProvinceZone) and getattr(card, "bowed", False):
            card.unbow()
        card.turn_face_down()
        added_ok = True
        try:
            added = zone.add(card)
            if isinstance(added, bool):
                added_ok = added
        except Exception:
            added_ok = True
        if not added_ok:
            dv.deck.add_to_top([card])
            return rd
        rd.zones.add(ztag)
        rd.decks.add(deck_tag)
        return rd

    def zone_destroy(self, ztag: str) -> Redraw:
        rd = Redraw()
        v = self.view
        zv = v.zones.get(ztag)
        if not zv or not isinstance(zv.zone, ProvinceZone):
            return rd
        if not self._zone_owned_by_local(zv.zone):
            return rd
        zone = zv.zone
        disc_tag = self._find_zone_tag_by_type(DynastyDiscardZone)
        if disc_tag:
            discard_zone = v.zones[disc_tag].zone
            if not self._zone_owned_by_local(discard_zone):
                return rd
            while zone.cards:
                card = zone.cards.pop()
                if not card.face_up:
                    card.turn_face_up()
                # enforce same owner
                if self._zone_owned_by_card(discard_zone, card):
                    discard_zone.add(card)
            rd.zones.add(disc_tag)
        else:
            while zone.cards:
                card = zone.cards.pop()
                if not card.face_up:
                    card.turn_face_up()
                v.add_card(card, zv.x, zv.y)
        # mark the zone to be removed; view will handle deletion and relayout
        rd.remove_zones.add(ztag)
        return rd

    def zone_discard(self, ztag: str) -> Redraw:
        rd = Redraw()
        v = self.view
        zv = v.zones.get(ztag)
        if not zv or not zv.zone.cards:
            return rd
        if not self._zone_owned_by_local(zv.zone):
            return rd
        card = zv.zone.cards.pop()
        if not card.face_up:
            card.turn_face_up()
        disc_tag = self._find_zone_tag_by_type(DynastyDiscardZone)
        if not disc_tag:
            # put it back
            zv.zone.cards.append(card)
            return rd
        discard_zone = v.zones[disc_tag].zone
        if not self._zone_owned_by_local(discard_zone) or not self._zone_owned_by_card(
            discard_zone, card
        ):
            # put it back
            zv.zone.cards.append(card)
            return rd
        v.zones[disc_tag].zone.add(card)
        rd.zones.update({ztag, disc_tag})
        return rd

    def deck_draw(self, dtag: str) -> Redraw:
        rd = Redraw()
        v = self.view
        if not self._deck_owned_by_local(dtag):
            return rd
        dv = v.decks[dtag]
        card = dv.deck.draw_one()
        if card is None:
            return rd
        # If the deck has an owner and the card has none, adopt the deck owner
        d_owner = getattr(dv, "owner", None)
        c_owner = getattr(card, "owner", None)
        if d_owner is not None and c_owner is None:
            try:
                object.__setattr__(card, "owner", d_owner)
                c_owner = d_owner
            except Exception:
                pass
        # Card must belong to same owner as the deck to proceed if both set
        if d_owner is not None and c_owner is not None and d_owner != c_owner:
            dv.deck.add_to_top([card])
            return rd
        if card.side is Side.FATE:
            # Send to hand: prefer the hand zone owned by the deck owner; fallback to local
            desired_owner: PlayerId | None = (
                d_owner if d_owner is not None else getattr(v, "local_player", None)
            )
            hand_tag = self._find_zone_tag_by_type_and_owner(HandZone, desired_owner)
            if hand_tag:
                hv = v.hands[hand_tag]
                # Ensure ownership checks pass (should if desired_owner chosen); else fallback battlefield
                if self._zone_owned_by_local(hv.zone) and self._zone_owned_by_card(hv.zone, card):
                    card.turn_face_up()
                    hv.zone.add(card)
                    rd.zones.add(hand_tag)
                    rd.decks.add(dtag)
                    return rd
        # Dynasty draw: prefer filling an empty province if available
        if card.side is Side.DYNASTY:
            for ztag, zv in v.zones.items():
                if (
                    isinstance(zv.zone, ProvinceZone)
                    and zv.zone.has_capacity()
                    and self._zone_owned_by_card(zv.zone, card)
                ):
                    # Only if province is owned by local
                    if not self._zone_owned_by_local(zv.zone):
                        continue
                    card.turn_face_down()
                    zv.zone.add(card)
                    rd.zones.add(ztag)
                    rd.decks.add(dtag)
                    return rd
        # else: to battlefield near deck, face down
        card.turn_face_down()
        offset = CARD_W + DRAW_OFFSET
        draw_x = dv.x - offset if card.side is Side.FATE else dv.x + offset
        draw_y = dv.y
        v.add_card(card, draw_x, draw_y)
        rd.decks.add(dtag)
        return rd

    def deck_shuffle(self, dtag: str) -> Redraw:
        rd = Redraw()
        if not self._deck_owned_by_local(dtag):
            return rd
        dv = self.view.decks[dtag]
        dv.deck.shuffle()
        rd.decks.add(dtag)
        return rd

    def deck_flip_top(self, dtag: str) -> Redraw:
        rd = Redraw()
        if not self._deck_owned_by_local(dtag):
            return rd
        dv = self.view.decks[dtag]
        top = dv.deck.peek(1)
        if not top:
            return rd
        top[0].turn_face_up()
        rd.decks.add(dtag)
        return rd

    def create_province(self, dtag: str) -> Redraw:
        rd = Redraw()
        v = self.view
        if not self._deck_owned_by_local(dtag):
            return rd
        dv = v.decks.get(dtag)
        if not dv:
            return rd
        # Only enable for dynasty decks
        expected = deck_expected_side(dv)
        if "Dynasty" not in getattr(dv, "label", "") and expected is not Side.DYNASTY:
            return rd
        # Determine owner to group provinces by
        owner = getattr(dv, "owner", None)
        if owner is None:
            owner = getattr(v, "local_player", None)
        # Find existing provinces for this owner and compute the right-most x
        owned_provinces: list[tuple[str, Any]] = [
            (tag, zv)
            for tag, zv in v.zones.items()
            if isinstance(zv.zone, ProvinceZone) and getattr(zv.zone, "owner", None) == owner
        ]
        if owned_provinces:
            rightmost_x = max(zv.x for _, zv in owned_provinces)
            place_x = rightmost_x + CARD_W
        else:
            # Seed near the dynasty deck; relayout will center it
            place_x = dv.x
        place_y = dv.y
        # Request new zone creation (draw will happen in view.apply_redraw)
        new_zone = ProvinceZone(owner=owner)
        rd.new_zones.append((new_zone, place_x, place_y, CARD_W, CARD_H))
        # Mark existing owner provinces for redraw (view will also add moved ones)
        for tag, _ in owned_provinces:
            rd.zones.add(tag)
        return rd

    def drop_sprite_into_zone(self, sprite_tag: str, zone_tag: str) -> Redraw:
        rd = Redraw()
        v = self.view
        sp = v.sprites.get(sprite_tag)
        if not sp:
            return rd
        if not self._owns_card(sp.card):
            return rd
        # Determine target zone (regular or hand)
        zv = v.zones.get(zone_tag)
        hv = v.hands.get(zone_tag)
        target_zone: Zone | None = None
        if zv is not None:
            target_zone = zv.zone
        elif hv is not None:
            target_zone = hv.zone
        if target_zone is None:
            return rd
        # Target must be owned by local and share owner with card if both set
        if not self._zone_owned_by_local(target_zone) or not self._zone_owned_by_card(
            target_zone, sp.card
        ):
            return rd
        allowed = getattr(target_zone, "allowed_side", None)
        if allowed is not None and sp.card.side is not allowed:
            return rd
        if not target_zone.has_capacity():
            return rd
        # Remove from any prior location
        self._remove_from_all_zones(sp.card)
        # Special handling for hand: insert by index and flip face down
        if hv is not None:
            sp.card.turn_face_down()
            idx = hv.index_at(sp.x) or len(hv.zone.cards)
            hv.zone.cards.insert(idx, sp.card)
            v.remove_card_sprite(sprite_tag)
            rd.zones.add(zone_tag)
            return rd
        # Regular zones: if a province, ensure unbowed
        if isinstance(target_zone, ProvinceZone) and getattr(sp.card, "bowed", False):
            sp.card.unbow()
        target_zone.add(sp.card)
        v.remove_card_sprite(sprite_tag)
        rd.zones.add(zone_tag)
        return rd

    def drop_sprite_into_deck(self, sprite_tag: str, deck_tag: str) -> Redraw:
        rd = Redraw()
        v = self.view
        sp = v.sprites.get(sprite_tag)
        if not sp:
            return rd
        if not self._owns_card(sp.card):
            return rd
        dv = v.decks.get(deck_tag)
        if not dv:
            return rd
        # Deck must be owned by local and share owner with card if both set
        if not self._deck_owned_by_local(deck_tag):
            return rd
        d_owner = getattr(dv, "owner", None)
        c_owner = getattr(sp.card, "owner", None)
        if d_owner is not None and c_owner is not None and d_owner != c_owner:
            return rd
        expected = deck_expected_side(dv)
        if expected is not None and sp.card.side is not expected:
            return rd
        self._remove_from_all_zones(sp.card)
        sp.card.turn_face_down()

        if sp.card.bowed:
            sp.card.unbow()
        if sp.card.inverted:
            sp.card.uninvert()

        dv.deck.add_to_top([sp.card])
        v.remove_card_sprite(sprite_tag)
        rd.decks.add(deck_tag)
        return rd


@_register
def card_bow() -> Action:
    def _in_province(view: HasView, card: L5RCard) -> bool:
        for _, zv in view.zones.items():
            try:
                if isinstance(zv.zone, ProvinceZone) and card in zv.zone.cards:
                    return True
            except Exception:
                continue
        return False

    def when(view, ctx):
        if not (ctx.card_tag and ctx.card_tag in view.sprites):
            return False

        sp = view.sprites[ctx.card_tag]

        # Disallow bowing if the card currently resides in any province
        if _in_province(view, sp.card):
            return False

        owner = ctx.owner if ctx.owner is not None else getattr(sp.card, "owner", None)
        return owner is None or owner == view.local_player

    def run(view, ctx):
        selection = getattr(view, "_selected", set())
        rd = FieldActions(view).toggle_bow(ctx.card_tag, selection)
        view.apply_redraw(rd)

    return Action(
        id="card.toggle_bow", label="Bow / Unbow", hotkey=HK.bow, when=when, run=run, group="card"
    )


@_register
def card_flip() -> Action:
    def when(view, ctx):
        if not (ctx.card_tag and ctx.card_tag in view.sprites):
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.sprites[ctx.card_tag].card, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        selection = getattr(view, "_selected", set())
        rd = FieldActions(view).toggle_flip(ctx.card_tag, selection)
        view.apply_redraw(rd)

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
        if not (ctx.card_tag and ctx.card_tag in view.sprites):
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.sprites[ctx.card_tag].card, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        selection = getattr(view, "_selected", set())
        rd = FieldActions(view).toggle_invert(ctx.card_tag, selection)
        view.apply_redraw(rd)

    return Action(
        id="card.toggle_invert", label="Invert", hotkey=HK.invert, when=when, run=run, group="card"
    )


@_register
def card_send_to_hand() -> Action:
    def when(view, ctx):
        if not (
            ctx.card_tag
            and ctx.card_tag in view.sprites
            and hasattr(view, "_find_zone_tag_by_type")
        ):
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.sprites[ctx.card_tag].card, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).send_to_hand(ctx.card_tag)
        view.apply_redraw(rd)

    return Action(id="card.send_hand", label="Send to Hand", when=when, run=run, group="send")


@_register
def card_send_to_fate_discard() -> Action:
    def when(view, ctx):
        if not ctx.card_tag or ctx.card_tag not in view.sprites:
            return False
        if view.sprites[ctx.card_tag].card.side is not Side.FATE:
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.sprites[ctx.card_tag].card, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).send_to_fate_discard(ctx.card_tag)
        view.apply_redraw(rd)

    return Action(id="card.send_fate_disc", label="Fate Discard", when=when, run=run, group="send")


@_register
def card_send_to_dynasty_discard() -> Action:
    def when(view, ctx):
        if not ctx.card_tag or ctx.card_tag not in view.sprites:
            return False
        if view.sprites[ctx.card_tag].card.side is not Side.DYNASTY:
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.sprites[ctx.card_tag].card, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).send_to_dynasty_discard(ctx.card_tag)
        view.apply_redraw(rd)

    return Action(
        id="card.send_dynasty_disc", label="Dynasty Discard", when=when, run=run, group="send"
    )


@_register
def card_send_to_top() -> Action:
    def when(view, ctx):
        if not ctx.card_tag or ctx.card_tag not in view.sprites:
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.sprites[ctx.card_tag].card, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).send_to_deck_top(ctx.card_tag)
        view.apply_redraw(rd)

    return Action(id="card.send_deck_top", label="Top of Deck", when=when, run=run, group="send")


@_register
def card_send_to_bottom() -> Action:
    def when(view, ctx):
        if not ctx.card_tag or ctx.card_tag not in view.sprites:
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.sprites[ctx.card_tag].card, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).send_to_deck_bottom(ctx.card_tag)
        view.apply_redraw(rd)

    return Action(
        id="card.send_deck_bottom", label="Bottom of Deck", when=when, run=run, group="send"
    )


@_register
def check_draw() -> Action:
    def when(view, ctx):
        if not (
            ctx.deck_tag and ctx.deck_tag in view.decks and view.decks[ctx.deck_tag].deck.cards
        ):
            return False
        owner = (
            ctx.owner if ctx.owner is not None else getattr(view.decks[ctx.deck_tag], "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).deck_draw(ctx.deck_tag)
        view.apply_redraw(rd)

    return Action(id="deck.draw", label="Draw", hotkey=HK.draw, when=when, run=run, group="deck")


@_register
def check_shuffle() -> Action:
    def when(view, ctx):
        if not (ctx.deck_tag and ctx.deck_tag in view.decks):
            return False
        owner = (
            ctx.owner if ctx.owner is not None else getattr(view.decks[ctx.deck_tag], "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).deck_shuffle(ctx.deck_tag)
        view.apply_redraw(rd)

    return Action(
        id="deck.shuffle", label="Shuffle", hotkey=HK.shuffle, when=when, run=run, group="deck"
    )


@_register
def deck_flip_top_card() -> Action:
    def when(view, ctx):
        if not (
            ctx.deck_tag and ctx.deck_tag in view.decks and view.decks[ctx.deck_tag].deck.cards
        ):
            return False
        owner = (
            ctx.owner if ctx.owner is not None else getattr(view.decks[ctx.deck_tag], "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).deck_flip_top(ctx.deck_tag)
        view.apply_redraw(rd)

    return Action(
        id="deck.flip_top", label="Flip Top", hotkey=HK.flip, when=when, run=run, group="deck"
    )


@_register
def deck_inspect() -> Action:
    def when(view, ctx):
        if not (ctx.deck_tag and ctx.deck_tag in view.decks):
            return False
        owner = (
            ctx.owner if ctx.owner is not None else getattr(view.decks[ctx.deck_tag], "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        dv = view.decks[ctx.deck_tag]
        master = view.winfo_toplevel() if hasattr(view, "winfo_toplevel") else view
        dialogs = Dialogs(master, ImageProvider(master))
        dialogs.deck_inspect(dv)

    return Action(
        id="deck.inspect", label="Inspect", hotkey=HK.inspect, when=when, run=run, group="deck"
    )


@_register
def deck_search_action() -> Action:
    def when(view, ctx):
        if not (ctx.deck_tag and ctx.deck_tag in view.decks):
            return False
        owner = (
            ctx.owner if ctx.owner is not None else getattr(view.decks[ctx.deck_tag], "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        dv = view.decks[ctx.deck_tag]
        master = view.winfo_toplevel() if hasattr(view, "winfo_toplevel") else view
        dialogs = Dialogs(master, ImageProvider(master))
        draw_cb = FieldActions(view).make_deck_search_draw_cb(ctx.deck_tag)
        dialogs.deck_search(dv, draw_cb, n=None)

    return Action(id="deck.search", label="Search", when=when, run=run, group="deck")


@_register
def province_flip_card() -> Action:
    def when(view, ctx):
        if not (
            ctx.zone_tag and ctx.zone_tag in view.zones and view.zones[ctx.zone_tag].zone.cards
        ):
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.zones[ctx.zone_tag].zone, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        zv = view.zones[ctx.zone_tag]
        if zv.zone.cards and zv.zone.cards[-1].face_up:
            rd = FieldActions(view).zone_flip_down(ctx.zone_tag)
        else:
            rd = FieldActions(view).zone_flip_up(ctx.zone_tag)
        view.apply_redraw(rd)

    return Action(
        id="zone.toggle_flip", label="Flip Top", hotkey=HK.flip, when=when, run=run, group="zone"
    )


@_register
def province_fill() -> Action:
    def when(view, ctx):
        if not (ctx.zone_tag and ctx.zone_tag in view.zones):
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.zones[ctx.zone_tag].zone, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).zone_fill(ctx.zone_tag)
        view.apply_redraw(rd)

    return Action(id="zone.fill", label="Fill", hotkey=HK.fill, when=when, run=run, group="zone")


@_register
def province_destroy() -> Action:
    def when(view, ctx):
        if not (ctx.zone_tag and ctx.zone_tag in view.zones):
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.zones[ctx.zone_tag].zone, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).zone_destroy(ctx.zone_tag)
        view.apply_redraw(rd)

    return Action(
        id="zone.destroy", label="Destroy", hotkey=HK.destroy, when=when, run=run, group="zone"
    )


@_register
def province_discard() -> Action:
    def when(view, ctx):
        if not (
            ctx.zone_tag
            and ctx.zone_tag in view.zones
            and isinstance(view.zones[ctx.zone_tag].zone, ProvinceZone)
            and view.zones[ctx.zone_tag].zone.cards
        ):
            return False
        owner = (
            ctx.owner
            if ctx.owner is not None
            else getattr(view.zones[ctx.zone_tag].zone, "owner", None)
        )
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).zone_discard(ctx.zone_tag)
        view.apply_redraw(rd)

    return Action(
        id="zone.discard", label="Discard", hotkey=HK.invert, when=when, run=run, group="zone"
    )


@_register
def deck_create_province() -> Action:
    def when(view, ctx):
        if not (ctx.deck_tag and ctx.deck_tag in view.decks):
            return False
        dv = view.decks[ctx.deck_tag]
        # Only dynasty decks can create provinces
        if "Dynasty" in getattr(dv, "label", ""):
            pass
        else:
            expected = deck_expected_side(dv)
            if expected is not Side.DYNASTY:
                return False
        owner = ctx.owner if ctx.owner is not None else getattr(dv, "owner", None)
        return owner is None or owner == view.local_player

    def run(view, ctx):
        rd = FieldActions(view).create_province(ctx.deck_tag)
        view.apply_redraw(rd)

    return Action(
        id="deck.create_province", label="Create Province", when=when, run=run, group="deck"
    )
