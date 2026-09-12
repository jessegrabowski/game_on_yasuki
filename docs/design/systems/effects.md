# Effects

An effect is one change to game state, written as data. A card builds the list and hands it back,
and the cascade in [Triggers and the cascade](triggers-and-the-cascade.md) commits each one. This
page is about the effects themselves: what an effect owes the engine, which ones another card can
react to, and how to make one wait.

## The contract

Three methods, and only one of them is required reading for a card author:

```python
class Effect(ABC):
    """One change to game state, described as data.

    Triggers and activated abilities return lists of effects rather than mutating the board, and the
    cascade commits each through :meth:`~.perform`.
    """

    __slots__ = ()

    @abstractmethod
    def perform(self, game: GameState) -> list[GameEvent]:
        """Commit this effect and return the events it raises, for the cascade to drain."""
```

{meth}`~.Effect.is_payable` answers whether an ability may pay this effect as a cost, and defaults
to yes. {meth}`~.Effect.describe` names the effect in one line for a cascade trace, and is abstract
so that a new effect cannot ship unreadable.

Every effect is a frozen dataclass. A card returns instances, never subclasses: the vocabulary is
closed, and [Card Vocabulary](../card_vocabulary.md) names every one, with
{class}`~.InterruptingEffect` and {class}`~.AttackEffect` as the two abstract categories.

## Not every effect changes a card

Some write engine bookkeeping and touch no card at all. The `Grant` effects append to
`game.ongoing`, which is the list the `effective_*` read path consults.
{class}`~.DelayedEffect` appends to `game.delayed`. {class}`~.Then` pushes onto `game.stack`.
{class}`~.GrantPriority` replaces `game.round`, {class}`~.DelayStraighten` writes
`game.straighten_delayed`, and {class}`~.PayFavorCost` sets one flag.

{class}`~.GrantModifier` is the shape they share:

```python
def perform(self, game: GameState) -> list[GameEvent]:
    game.ongoing.append(
        Modifier(self.source_id, self.target_id, self.stat, self.amount, self.duration)
    )
    return []
```

Nothing on the board moved. The modifier is recorded, and every later read of that stat adds it up.
[Stats](stats.md) covers the read path.

## Which effects another card can react to

A trigger fires on an event, so an effect that raises none is invisible to every other card.
These raise one: {class}`AdjustCounter <yasuki_core.engine.rules.effects.AdjustCounter>`,
{class}`~.Destroy`, {class}`~.Discard`,
{class}`DestroyProvince <yasuki_core.engine.rules.effects.DestroyProvince>`,
{class}`~.AttachCard`, {class}`~.PutIntoPlay`, {class}`~.CreateToken`, {class}`~.Straighten`,
{class}`~.RevealProvinces`, and the three attacks through {class}`~.AttackEffect`. Every other
effect returns an empty list.

This is worth knowing in both directions. A card that should provoke a reaction has to reach for
the effect that raises the event, and a card that quietly does something no opponent may answer is
often correct rather than incomplete.

## Making an effect wait

An effect returned inline runs before the events already queued behind it. When a step has to
follow another card's reaction to what just happened, it goes inside a `Then`:

```python
@dataclass(frozen=True, slots=True)
class Then(Effect):
    """Defer ``effects`` until the current step has fully resolved, cascade included.

    Effects placed inline run before the events already queued behind them, so a step that must
    follow another card's reaction to what just happened belongs here instead.
    """

    effects: tuple[Effect, ...]
```

{card}`Agasha Beiru` needs it. She recruits a Fortification out of the discard pile and then walls
the Province it landed on, and she cannot know which Province that is until the recruit has
finished asking:

```python
return [
    RecruitCard(target.id),
    Then((CounterOnAttachedProvince(target.id, WALL, 1),)),
]
```

## The half of the invariant that is not about cards

No card module in the package calls the mutation layer. The flow does, in a handful of places where
a board change has no effect behind it, and a caller that mutates directly owes the board the same
settling the cascade would have done:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:start-at: def enforce_state_based_actions(game: GameState) -> None:
:end-before: queue: list[GameEvent] = []
:language: python
```

This is a convention, and nothing enforces it. `turn/sequence.py`, `rulebook/recruit.py` and
`rulebook/equip.py` call it. A card author never needs it, and a card that reaches for the
mutation layer instead of returning an effect is doing something wrong.

## Creating a card

{class}`~.CreateToken` is the one effect that makes a card, and its fields carry the whole of what
creation means:

```python
token_id: str
owner: PlayerId
creator_id: str
attach_to: str | None = None
stats: tuple[tuple[Stat, int], ...] = ()
clan: str | None = None
banish_at_turn_end: bool = False
```

`token_id` names a template the deck load resolved, so a created card is a real card with a print
behind it. `creator_id` records who made it, which is how a card speaks about its creation later.
`attach_to` makes creating-and-attaching one effect, since a created card has no id to attach in a
second step. `stats` fills in a template's variable stat line, and `banish_at_turn_end` is settled
at creation because by the time the turn ends there is nothing left to decide.

[Cards that create cards](../../contributing/creating_cards.md) works through each of them.

## Where a card plugs in

By returning effects and nothing else. [Writing an ability](../../contributing/an_ability.md) is
the four parts in order, and [Reacting to an event](../../contributing/reacting_to_events.md) is
the same list returned from a trigger.
