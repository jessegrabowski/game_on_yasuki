from dataclasses import fields, is_dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import FatePrint, HoldingPrint
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.engine.rules.state import BattleOutcome, GameState, Phase
from yasuki_core.engine.rules.decisions import DiscardToHandSize
from yasuki_core.engine.rules import battle, triggers
from yasuki_core.engine.rules.effects import Discard
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.projection import project

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
    two_seat_game,
)


def _game() -> GameState:
    return GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=7)


def test_rules_fields_are_public_to_both_seats():
    game = _game()
    game.phase = Phase.DYNASTY
    game.add_gold(PlayerId.P1, 3)
    game.add_gold(PlayerId.P2, 1)

    for viewer in PlayerId:
        view = project(game, viewer)
        assert view.viewer is viewer
        assert view.turn == 1
        assert view.active is PlayerId.P1
        assert view.phase is Phase.DYNASTY
        assert view.first_player is PlayerId.P1
        # Both seats' gold pools are visible to either viewer.
        assert view.gold == {PlayerId.P1: 3, PlayerId.P2: 1}


def test_pending_decision_reaches_only_the_answerer():
    game = _game()
    request = DiscardToHandSize(PlayerId.P1, ("a", "b", "c"), count=2)
    game.pending = request

    assert project(game, PlayerId.P1).pending == request
    assert project(game, PlayerId.P2).pending is None


def test_table_is_redacted_for_the_viewer():
    game = _game()
    secret = L5RCard.of(FatePrint, id="P1-secret", name="Ambush", side=Side.FATE, owner=PlayerId.P1)
    game.table.cards_by_id[secret.id] = secret
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(secret)

    owner_view = project(game, PlayerId.P1)
    opponent_view = project(game, PlayerId.P2)

    hand_key = ZoneKey(PlayerId.P1, ZoneRole.HAND)
    assert owner_view.table.zones[hand_key].cards[0] is secret
    assert isinstance(opponent_view.table.zones[hand_key].cards[0], HiddenCard)


def test_gold_view_is_decoupled_from_the_live_pool():
    game = _game()
    view = project(game, PlayerId.P1)
    game.add_gold(PlayerId.P1, 5)
    # The projection captured a snapshot; later production does not mutate it.
    assert view.gold[PlayerId.P1] == 0


# --- the viewer's own Legacy pool -----------------------------------------------------------------


def _legacy_holding(card_id: str, owner=PlayerId.P1, production=3) -> L5RCard:
    return L5RCard.of(
        HoldingPrint,
        id=card_id,
        name=f"Estate {card_id}",
        side=Side.DYNASTY,
        owner=owner,
        gold_production=production,
        keywords=("Legacy",),
    )


def _dynasty_holding(card_id: str, owner=PlayerId.P1) -> L5RCard:
    """A plain Holding, for tests where the Legacy keyword would be a false signal."""
    return L5RCard.of(
        HoldingPrint, id=card_id, name=f"Holding {card_id}", side=Side.DYNASTY, owner=owner
    )


def _seed_deck(game: GameState, owner: PlayerId, *cards) -> None:
    game.table.decks[DeckKey(owner, Side.DYNASTY)].cards = list(cards)
    for card in cards:
        game.table.cards_by_id[card.id] = card


def test_the_pool_holds_the_viewers_findable_legacy_cards():
    game = _game()
    estate = _legacy_holding("P1-9")
    plain = L5RCard.of(
        HoldingPrint,
        id="P1-1",
        name="Mine",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_production=2,
    )
    _seed_deck(game, PlayerId.P1, plain, estate)

    assert project(game, PlayerId.P1).legacy_pool == (estate,)


def test_the_pool_is_empty_when_no_legacy_card_remains():
    game = _game()
    _seed_deck(
        game,
        PlayerId.P1,
        L5RCard.of(HoldingPrint, id="P1-1", name="Mine", side=Side.DYNASTY, owner=PlayerId.P1),
    )

    assert project(game, PlayerId.P1).legacy_pool == ()


def test_the_pool_never_reaches_the_other_seat():
    """A seat knows what it built; its opponent's buried cards stay buried."""
    game = _game()
    _seed_deck(game, PlayerId.P1, _legacy_holding("P1-9"))

    assert project(game, PlayerId.P2).legacy_pool == ()


def test_the_pool_is_sorted_rather_than_left_in_deck_order():
    """Which Legacy cards remain is the seat's knowledge; where they sit in the shuffle is not, so
    the deck's order must not survive into the view."""
    game = _game()
    first, second = _legacy_holding("P1-2"), _legacy_holding("P1-1")
    _seed_deck(game, PlayerId.P1, first, second)  # deck order puts P1-2 ahead of P1-1

    assert [card.id for card in project(game, PlayerId.P1).legacy_pool] == ["P1-1", "P1-2"]


def test_the_dynasty_deck_shows_the_seat_what_it_still_holds():
    # A seat built its deck, so what remains in it is its own knowledge — the basis for judging
    # whether a redraw beats the row it is looking at.
    game = _game()
    _seed_deck(game, PlayerId.P1, _dynasty_holding("P1-a"), _dynasty_holding("P1-b"))

    assert [card.id for card in project(game, PlayerId.P1).dynasty_deck] == ["P1-a", "P1-b"]


def test_the_dynasty_deck_never_reaches_the_other_seat():
    game = _game()
    _seed_deck(game, PlayerId.P1, _dynasty_holding("P1-a"))

    assert project(game, PlayerId.P2).dynasty_deck == ()


def test_the_dynasty_deck_is_sorted_rather_than_left_in_deck_order():
    # Composition is the seat's knowledge; the shuffle is not. Leaving deck order in the view would
    # hand a policy the next card to be drawn.
    game = _game()
    _seed_deck(game, PlayerId.P1, _dynasty_holding("P1-2"), _dynasty_holding("P1-1"))

    assert [card.id for card in project(game, PlayerId.P1).dynasty_deck] == ["P1-1", "P1-2"]


def test_a_face_down_province_card_is_still_findable():
    game = _game()
    buried = _legacy_holding("P1-9")
    buried.turn_face_down()
    zone = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(
        owner=PlayerId.P1
    )
    zone.add(buried)
    game.table.cards_by_id[buried.id] = buried

    assert project(game, PlayerId.P1).legacy_pool == (buried,)


def test_a_revealed_province_card_has_left_the_pool():
    """A face-up province card is already recruitable, so the search does not reach it — and the
    policy would see it among its Recruits instead."""
    game = _game()
    revealed = _legacy_holding("P1-9")
    revealed.turn_face_up()
    zone = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(
        owner=PlayerId.P1
    )
    zone.add(revealed)
    game.table.cards_by_id[revealed.id] = revealed

    assert project(game, PlayerId.P1).legacy_pool == ()


def test_a_conditionally_granted_legacy_card_is_findable():
    """Shrine of Courtesy grants itself Legacy while its controller went second, so a search that
    read printed keywords alone would never surface it."""

    def shrine(owner: PlayerId) -> L5RCard:
        return L5RCard.of(
            HoldingPrint,
            id=f"{owner.name}-4",
            name="Shrine of Courtesy",
            side=Side.DYNASTY,
            owner=owner,
            printed_id="shrine_of_courtesy",
            keywords=("Temple", "Unique"),
            gold_production=2,
        )

    game = _game()  # first_player is P1, so P2 went second
    second_players = shrine(PlayerId.P2)
    _seed_deck(game, PlayerId.P2, second_players)
    assert project(game, PlayerId.P2).legacy_pool == (second_players,)

    # The same Holding stays unfindable for the seat that went first: the grant is conditional.
    _seed_deck(game, PlayerId.P1, shrine(PlayerId.P1))
    assert project(game, PlayerId.P1).legacy_pool == ()


def test_a_modified_cards_effective_stats_reach_the_view():
    """A view is all a Policy or a client gets, and modifiers live on the game rather than on the
    card, so without this the only readable number is the printed one."""
    game = two_seat_game()
    farm = put_in_play(game, holding("farm", gold_production=2, counters={"wealth": 2}))

    view = project(game, PlayerId.P1)

    assert view.stat(farm, Stat.GOLD_PRODUCTION) == 4  # printed 2, +1 per Wealth
    assert farm.gold_production == 2  # the card itself still answers what it was printed at


def test_an_attachments_bonus_reaches_the_view():
    """An Item's Force is a modifier derived from the board rather than one recorded on the game, so
    a view that carries only the recorded ones reports the Personality at his printed Force while
    the engine fights the battle at his real one."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", owner=PlayerId.P1, force=5))
    attached(
        game,
        attachment(
            "blade", attachment_type=AttachmentType.ITEM, force_modifier=2, owner=PlayerId.P1
        ),
        "hero",
    )

    assert project(game, PlayerId.P1).stat(hero, Stat.FORCE) == 7


def test_a_card_no_modifier_reaches_falls_back_to_its_printed_stat():
    """Materializing every card in the game would be work to arrive where the card already is, so
    only modified cards are carried and the rest read through."""
    game = two_seat_game()
    plain = put_in_play(game, holding("plain", gold_production=3))

    view = project(game, PlayerId.P1)

    assert plain.id not in view.stats
    assert view.stat(plain, Stat.GOLD_PRODUCTION) == 3


def test_a_stat_printed_as_a_dash_reads_zero_through_the_view():
    game = two_seat_game()
    free = put_in_play(game, holding("free", gold_cost=None))

    assert project(game, PlayerId.P1).stat(free, Stat.GOLD_COST) == 0


def _cards_reachable(node, path="view", seen=None):
    """Every full L5RCard reachable from ``node``, with the attribute path that reached it.

    Walks dataclasses, dicts and sequences generically rather than naming the view's fields, so a
    field added later is swept without anyone remembering to add it here.
    """
    seen = set() if seen is None else seen
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, L5RCard):
        yield path, node
    elif isinstance(node, HiddenCard):
        return
    elif is_dataclass(node):
        for f in fields(node):
            yield from _cards_reachable(getattr(node, f.name), f"{path}.{f.name}", seen)
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _cards_reachable(value, f"{path}[{key!r}]", seen)
    elif isinstance(node, list | tuple | set | frozenset):
        for index, value in enumerate(node):
            yield from _cards_reachable(value, f"{path}[{index}]", seen)


# P2's cards that P1 must never be able to identify, one per place P2 can hide one. The card P2
# leaves in the open is deliberately not among them: it is the sweep's positive control.
HIDDEN_FROM_P1 = frozenset({"P2-hand", "P2-facedown", "P2-indeck"})


def _hiding_game() -> GameState:
    """A game with one of P2's cards in each hiding place, and one in the open."""
    game = two_seat_game()
    in_hand = register(game.table, holding("P2-hand", owner=PlayerId.P2, gold_production=7))
    game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].add(in_hand)
    in_hand.adjust_counter("wealth", 1)  # so it qualifies for the stats materialization

    province_card(game, "P2-facedown", seat=PlayerId.P2, gold_production=1, face_up=False)
    game.modifiers.append(
        Modifier("src", "P2-facedown", Stat.GOLD_PRODUCTION, 4, Duration.PERMANENT)
    )

    in_deck = register(game.table, holding("P2-indeck", owner=PlayerId.P2, gold_production=9))
    in_deck.turn_face_down()
    game.table.decks[DeckKey(PlayerId.P2, Side.DYNASTY)].cards.append(in_deck)

    put_in_play(game, holding("P2-inplay", owner=PlayerId.P2, gold_production=3))
    return game


def test_no_card_the_viewer_cannot_identify_reaches_the_view():
    """The board channels are safe by construction — a snapshot holds a ``CardView``, so redaction
    is a decision the type forces. A field of plain values is not, and this sweeps the whole view so
    the next one added is covered whether or not it carries cards."""
    game = _hiding_game()

    view = project(game, PlayerId.P1)

    leaked = [
        f"{path} -> {card.id}" for path, card in _cards_reachable(view) if card.id in HIDDEN_FROM_P1
    ]
    assert leaked == []
    assert not HIDDEN_FROM_P1 & set(view.stats)


def test_the_sweep_still_sees_what_the_viewer_is_entitled_to():
    """The positive control for the sweep above: a card in the open reaches the view, and reaches it
    with its stats. Without this, a view that carried nothing at all would pass."""
    game = _hiding_game()
    game.table.cards_by_id["P2-inplay"].adjust_counter("wealth", 2)

    view = project(game, PlayerId.P1)

    assert "P2-inplay" in {card.id for _, card in _cards_reachable(view)}
    assert view.stat(game.table.cards_by_id["P2-inplay"], Stat.GOLD_PRODUCTION) == 5


def test_the_viewers_own_hidden_card_still_carries_its_stats_to_them():
    """The mirror of the leak sweep. Entitlement is per-seat, not per-secrecy: a card in the
    viewer's own hand is hidden from the opponent and fully theirs to read, so filtering the stats
    by what the *snapshot* shows must not cost a seat its own cards."""
    game = _game()
    mine = L5RCard.of(
        FatePrint, id="P1-inhand", name="Mine", side=Side.FATE, owner=PlayerId.P1, gold_cost=4
    )
    game.table.cards_by_id[mine.id] = mine
    assert game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(mine)
    game.modifiers.append(Modifier("src", mine.id, Stat.GOLD_COST, 2, Duration.PERMANENT))

    assert project(game, PlayerId.P1).stat(mine, Stat.GOLD_COST) == 6
    assert "P1-inhand" not in project(game, PlayerId.P2).stats  # and stays the opponent's secret


def test_a_discarded_card_reports_the_stats_it_prints():
    """The symptom that surfaced the token bug: a card keeping its counters past the battlefield
    kept reporting the stats they bought, so a destroyed Holding still looked like a producer to
    every policy and client reading the view."""
    game = two_seat_game()
    farm = put_in_play(game, holding("farm", gold_production=2))
    farm.adjust_counter("wealth", 3)
    assert project(game, PlayerId.P1).stat(farm, Stat.GOLD_PRODUCTION) == 5

    triggers.resolve_effects(game, [Discard("farm", PlayerId.P1)])

    assert project(game, PlayerId.P1).stat(farm, Stat.GOLD_PRODUCTION) == 2


def _attack_between(face_up: bool) -> GameState:
    """P1 attacking P2, whose one Province holds a card turned ``face_up`` or not."""
    game = two_seat_game()
    province_card(game, "p2-holding", seat=PlayerId.P2, index=0, face_up=face_up)
    battle.declare_attack(game, PlayerId.P1)
    return game


def test_a_face_up_province_card_reaches_the_attacker_by_name():
    game = _attack_between(face_up=True)

    view = project(game, PlayerId.P1)

    assert view.attack.battlefields[0].occupant.id == "p2-holding"


def test_a_face_down_province_card_reaches_the_attacker_as_a_back():
    """The attack is public, but what is sitting in the Province is not — projecting it out of the
    table rather than the snapshot would hand the attacker the Defender's face-down card."""
    game = _attack_between(face_up=False)

    view = project(game, PlayerId.P1)

    assert isinstance(view.attack.battlefields[0].occupant, HiddenCard)


def test_the_defender_sees_its_own_face_down_province_card_as_a_back_too():
    """Redaction hides a face-down card from its owner as well, and the attack view is the same
    projection — so it says the same thing rather than a second opinion."""
    game = _attack_between(face_up=False)

    view = project(game, PlayerId.P2)

    assert isinstance(view.attack.battlefields[0].occupant, HiddenCard)


def test_the_attack_view_names_the_cards_a_battle_destroyed():
    """The outcome carries ids; a client has to show names, and a destroyed card is in a discard
    both seats may read."""
    game = two_seat_game()
    # A name that is not the id, so the assertion cannot pass by echoing what it was given.
    province_card(game, "p2-holding", seat=PlayerId.P2, index=0, name="Kyuden Bayushi")
    battle.declare_attack(game, PlayerId.P1)
    attack = game.attack
    attack.battlefields = (
        attack.battlefields[0]._replace(
            outcome=BattleOutcome(
                winner=PlayerId.P1,
                destroyed=("p2-holding",),
                province_destroyed=False,
                honor={},
            )
        ),
    ) + attack.battlefields[1:]

    view = project(game, PlayerId.P1)

    assert view.attack.battlefields[0].destroyed_names == ("Kyuden Bayushi",)


def test_a_battlefield_with_no_outcome_names_nothing_destroyed():
    game = two_seat_game()
    province_card(game, "p2-holding", seat=PlayerId.P2, index=0)
    battle.declare_attack(game, PlayerId.P1)

    view = project(game, PlayerId.P1)

    assert view.attack.battlefields[0].destroyed_names == ()
