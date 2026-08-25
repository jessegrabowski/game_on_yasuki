from collections.abc import Callable, Iterator

import numpy as np
from numpy.random import Generator

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import effective_gold_production
from yasuki_core.engine.rules.legality import gold_producers, recruit_cost
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import DeckKey, Zone, ZoneRole
from yasuki_core.game_pieces.constants import Side

# A metric answers one question about one seat at one moment. Float rather than int so a
# ratio — a share of provinces, a rate per turn — is expressible alongside a plain count.
Metric = Callable[[GameState, PlayerId], float]


def potential_gold_production(game: GameState, seat: PlayerId) -> int:
    """
    What ``seat``'s straight producers yield at no cost, right now.

    Computed rather than read: ``game.gold`` is a transient pool, filled during a payment and
    cleared at the end of the phase, so it reads zero at every turn boundary.

    Two things are deliberately outside this number, and both make it smaller than
    :func:`~yasuki_core.engine.rules.legality.reachable_gold` for the same board.

    A card's own bow-time grant is excluded, because taking one has a price the card sets — Outlying
    Farms destroys itself — so counting it would report gold a seat may rationally decline. This
    measures sustainable output, which is what a deck is being judged on. That is the same reason
    ``policies._spendable`` leaves it out, and the opposite of what
    :func:`~yasuki_core.engine.rules.economy.maximum_gold_production` answers for affordability.

    A producer's yield can depend on what it pays for (Jade Works yields more against a Jade card),
    and a metric has no payment in flight, so such a producer reports its unconditional base.
    """
    return sum(effective_gold_production(game, card) for card in gold_producers(game, seat))


def province_clearance(rng: Generator, *, samples: int = 500, slots: int = 4) -> Metric:
    r"""
    Build a metric giving the chance ``seat`` could buy out a fresh flop of ``slots`` province
    cards with what it can produce right now.

    A deck is judged on reaching the speed at which what it flips stops constraining it, and that
    is a property of the pair (economy, curve) rather than of either alone: the same production is
    plenty against a deck of Farms and nothing against a deck of five-cost Personalities. What the
    board happens to be showing this turn is a single draw from that distribution, so it is
    resampled instead — ``samples`` hands of ``slots`` cards are dealt without replacement from the
    seat's dynasty deck, each priced with :func:`~yasuki_core.engine.rules.legality.recruit_cost`,
    and the metric is the share whose total the seat's production covers.

    The deck is the right urn even though the seat's live provinces are not in it: those cards are
    where the flop came from, not where the next one comes from. It shrinks over a game, so the
    estimate tracks a seat digging toward the bottom of its own list.

    Affording every card is not the same as buying every card — one Recruit per province per turn,
    and a gold-producing purchase pays for the ones after it — so this reads as a ceiling on
    clearance rather than the rate itself.

    Parameters
    ----------
    rng : numpy.random.Generator
        Draws the hands. Held by the metric rather than spawned per call, so a run reproduces from
        its seed and a longer run leaves the turns it already had alone.
    samples : int, optional
        Hands dealt per call. The estimate is a mean of Bernoullis, so its standard error is at
        worst :math:`1 / (2\sqrt{n})` — under one point at 500. Default 500.
    slots : int, optional
        Cards per hand, which is how many provinces a seat starts with. Default 4.

    Returns
    -------
    Metric
        Callable of ``(game, seat)`` returning a probability in :math:`[0, 1]`, or NaN once the
        dynasty deck holds fewer than ``slots`` cards and no flop of this shape can be priced.
    """

    def clearance(game: GameState, seat: PlayerId) -> float:
        deck = game.table.decks[DeckKey(seat, Side.DYNASTY)].cards
        if len(deck) < slots:
            # Fewer cards left than provinces to fill, so no flop of this shape exists to price.
            return float("nan")
        costs = np.fromiter(
            (recruit_cost(game, card) for card in deck), dtype=np.int64, count=len(deck)
        )
        # argpartition over one random matrix deals every hand at once, and without replacement
        # within a hand — which sampling `slots` indices independently would not give.
        hands = np.argpartition(rng.random((samples, costs.size)), slots - 1, axis=1)[:, :slots]
        return float((costs[hands].sum(axis=1) <= potential_gold_production(game, seat)).mean())

    return clearance


def family_honor(game: GameState, seat: PlayerId) -> int:
    """
    ``seat``'s Family Honor.

    Read directly rather than computed: honor is a standing total set from the stronghold and sensei
    at setup and moved by effects since, so unlike the gold pool it means the same thing at any
    moment. It can go negative, which is a real position rather than an error.
    """
    return game.table.seats[seat].honor


def provinces_held(game: GameState, seat: PlayerId) -> int:
    """
    How many provinces ``seat`` still has.

    The denominator for the other two. Without it a seat holding four full provinces and a seat
    holding none both report zero cleared and zero empty, which are opposite positions.
    """
    return sum(1 for _ in _provinces(game, seat))


def provinces_cleared(game: GameState, seat: PlayerId) -> int:
    """
    How many of ``seat``'s provinces were emptied and refilled during its own turn.

    A province is revealed face-up as its owner's turn begins. Vacating it refills it **face-down**
    from the dynasty deck, so a face-down card at the end of a turn marks a province the seat
    turned over, and a face-up one a card that sat there untouched.

    This is the total, not a verdict on it. Recruiting a card and discarding one leave identical
    boards, and they are opposite signals — a deck delivering what was wanted versus one being dug
    through. Count :class:`~yasuki_core.engine.rules.actions.Recruit` and
    :class:`~yasuki_core.engine.rules.actions.DynastyDiscard` actions for that split; both draw only
    from provinces, so together they attribute every province a seat turned over by choice.

    Those two do not have to add up to this number. A Legacy search and an ability-driven recruit
    both vacate a province without either action being taken, so the shortfall measures how much of
    a seat's province turnover its cards did for it.

    Read this only for a seat whose turn has just ended: its own turn begins by revealing every
    province, so during it the count is zero by construction.
    """
    return sum(1 for zone in _provinces(game, seat) if zone.cards and not zone.cards[0].face_up)


def empty_provinces(game: GameState, seat: PlayerId) -> int:
    """
    How many of ``seat``'s provinces hold no card at all.

    Vacating a province refills it from the dynasty deck, so this is not the ordinary measure of
    buying one out — see :func:`provinces_cleared` for that. A province is only truly empty once
    the dynasty deck has run dry, which makes this a late-game exhaustion signal.
    """
    return sum(1 for zone in _provinces(game, seat) if not zone.cards)


def _provinces(game: GameState, seat: PlayerId) -> Iterator[Zone]:
    """The province zones ``seat`` still holds."""
    return (
        zone
        for key, zone in game.table.zones.items()
        if key.owner is seat and key.role is ZoneRole.PROVINCE
    )
