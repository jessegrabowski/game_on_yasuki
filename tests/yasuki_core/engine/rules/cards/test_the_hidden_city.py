from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.effects import AttachCard
from yasuki_core.engine.rules.equip import equip_targets, may_attach
from yasuki_core.engine.rules.flow import submit
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import (
    attachment,
    personality,
    put_in_play,
    register,
    two_seat_game,
)

P1 = PlayerId.P1


def _brothers(card_id: str = "brothers"):
    return attachment(card_id, printed_id="brothers_in_arms", force=2)


def _city_game(*, in_discard=(), in_deck=()):
    """A board with a Samurai and a non-Samurai, and spare copies salted where the search looks."""
    game = two_seat_game()
    put_in_play(game, personality("samurai", keywords=("Samurai",)))
    put_in_play(game, personality("courtier", keywords=("Courtier",)))
    for card_id in in_discard:
        game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].add(
            register(game.table, _brothers(card_id))
        )
    for card_id in in_deck:
        game.table.decks[DeckKey(P1, Side.FATE)].cards.append(
            register(game.table, _brothers(card_id))
        )
    return game


def test_brothers_in_arms_only_attaches_to_a_samurai():
    game = _city_game()
    card = _brothers()

    assert may_attach(game, game.table.cards_by_id["samurai"], card) is True
    assert may_attach(game, game.table.cards_by_id["courtier"], card) is False
    assert [target.id for target in equip_targets(game, card)] == ["samurai"]


def test_brothers_in_arms_takes_a_copy_from_the_discard_pile():
    game = _city_game(in_discard=("spare",))
    game.table.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(game.table, _brothers()))

    resolve_effects(game, [AttachCard("brothers", "samurai")])

    assert isinstance(game.pending, ChooseCards)
    assert game.pending.candidates == ("spare",)


def test_brothers_in_arms_reads_the_deck_only_when_the_discard_holds_none():
    """ "Your Fate discard pile, then deck" is an order, not a choice: a discarded copy is never
    passed over in favor of shuffling for one."""
    game = _city_game(in_discard=("spare",), in_deck=("buried",))
    hand = game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    hand.add(register(game.table, _brothers()))

    resolve_effects(game, [AttachCard("brothers", "samurai")])

    assert game.pending.candidates == ("spare",)


def test_brothers_in_arms_puts_the_copy_it_finds_into_hand():
    game = _city_game(in_deck=("buried",))
    hand = game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    hand.add(register(game.table, _brothers()))
    resolve_effects(game, [AttachCard("brothers", "samurai")])
    submit(game, DecisionResponse(("buried",)))

    assert game.table.cards_by_id["buried"] in hand.cards


def test_brothers_in_arms_stays_quiet_when_it_did_not_come_from_hand():
    """The trigger reads "from your hand". An effect that attaches a copy off the discard pile must
    not start a chain that refills the discard pile it came from."""
    game = _city_game(in_discard=("spare",))
    discarded = register(game.table, _brothers("fetched"))
    game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].add(discarded)

    resolve_effects(game, [AttachCard("fetched", "samurai")])

    assert game.pending is None


def test_brothers_in_arms_asks_nothing_when_no_copy_is_left():
    game = _city_game()
    hand = game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    hand.add(register(game.table, _brothers()))

    resolve_effects(game, [AttachCard("brothers", "samurai")])

    assert game.pending is None


def test_brothers_in_arms_stays_quiet_when_a_different_card_enters_play():
    """The event reaches every copy of a printed id in play, not only the card that arrived. Without
    a self-check an in-play Brothers in Arms fires again each time anything else is Equipped, and
    the player is asked to search for a card they did not play."""
    # Two spares, so one is still fetchable after the first search — otherwise a re-fire finds
    # nothing and the bug hides behind an empty discard pile.
    game = _city_game(in_discard=("spare", "another"))
    hand = game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    hand.add(register(game.table, _brothers()))
    resolve_effects(game, [AttachCard("brothers", "samurai")])
    submit(game, DecisionResponse(("spare",)))
    assert game.pending is None

    hand.add(register(game.table, attachment("katana", printed_id="plain_item")))
    resolve_effects(game, [AttachCard("katana", "samurai")])

    assert game.pending is None
