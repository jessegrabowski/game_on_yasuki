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
{class}`~.DelayedEffect` appends to `game.delayed`.
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

{class}`~.LookAtTop` is the same shape for a card that reads "look at the top four cards of your
Fate deck". It moves nothing: it writes a {class}`~.Look` to `game.look` naming the seat, the deck
and the cards top first, and marks the seat as a peeker of each. The questions that follow are
ordinary {class}`~.Choose` effects whose candidates are those cards, and a resolver asking the next
one reads {func}`~.remaining_look` so a card an earlier answer moved out has left the pool.
{class}`~.EndLook` clears the slot when the last question is answered. While a look is open no
decision can be backed out of, because the seat has read cards it cannot unread.

## Which effects another card can react to

A trigger fires on an event, so an effect that raises none is invisible to every other card.
These raise one: {class}`AdjustCounter <yasuki_core.engine.rules.effects.AdjustCounter>`,
{class}`~.Destroy`, {class}`~.Discard`,
{class}`DestroyProvince <yasuki_core.engine.rules.effects.DestroyProvince>`,
{class}`~.AttachCard`, {class}`~.PutIntoPlay`, {class}`~.CreateToken`, {class}`~.Straighten`,
{class}`Dishonor <yasuki_core.engine.rules.effects.Dishonor>`,
{class}`Rehonor <yasuki_core.engine.rules.effects.Rehonor>`, {class}`~.RevealProvinces`,
{class}`~.GainHonor`, and the three attacks through {class}`~.AttackEffect`. Every other effect returns an empty list.

{class}`~.Destroy` is also announced before it commits. {meth}`~.Effect.impending` returns what is
announced, and a destruction returns a {class}`~.Destroying` for each card of the unit about to
leave play, so a trait reading "before this card is destroyed" acts while the card still stands.
{class}`~yasuki_core.engine.rules.effects.DestroyProvince` returns a {class}`~.ProvinceDestroying`
the same way, for a trait that acts before a Province is destroyed.
[Triggers and the cascade](triggers-and-the-cascade.md) has the rules for when it is announced.

This is worth knowing in both directions. A card that should provoke a reaction has to reach for
the effect that raises the event, and a card that quietly does something no opponent may answer is
often correct rather than incomplete.

## Effects in order

Effects in a list happen in the order they are written (CR, Order of Effects), and everything an
effect sets off resolves before the next one applies (CR 20F, Timing). A step that follows another
card's reaction to what just happened is therefore the next effect in the list. {card}`Agasha
Beiru` recruits a Fortification out of the discard pile and then walls the Province it landed on.
The recruit asks where the Fortification goes, and its entry resolves, before the counter is
placed:

```{literalinclude} ../../../src/yasuki_core/engine/rules/cards/a_line_in_the_sand.py
:pyobject: _agasha_beiru_effects
:language: python
```

## One effect that depends on another

"Effects linked by the word "to" mean that the second effect depends on the first effect actually
happening" (CR, Independence of Effects). "Bow your Samurai to draw two cards" draws nothing if the
Samurai was already bowed or something prevented the bow. {class}`~.To` writes that link: its
`contingent` effects apply only if its `first` actually happened: it commits as itself, perhaps
adjusted by an Interrupt but not negated or substituted, and {meth}`~.Effect.would_happen` says it
changes something. What reacts to `first` resolves before `contingent` applies. The Courage rulebook
Interrupt discards its card to adjust a Fear, so a negated discard keeps the card in hand and
adjusts nothing:

```{literalinclude} ../../../src/yasuki_core/engine/rules/rulebook/courage_and_honor.py
:pyobject: _discard_and_adjust
:language: python
```

## Effects that happen at once

Effects in a list happen in the order they are written (CR, Order of Effects). Some happen at once:
"Two things in the game can happen at the same time (e.g., two Personalities being destroyed in
battle resolution.)" (CR, Timing Conflicts). Those go inside a
{class}`~yasuki_core.engine.rules.effects.Simultaneously`, which applies each member in turn,
checked, modified and negated as it would be alone, and lets nothing react to any of them until all
have happened. Battle resolution builds one for the army it destroys:

```{literalinclude} ../../../src/yasuki_core/engine/rules/battle/resolution.py
:start-at: "if attacking_force > defending_force:"
:end-before: province = attack.battlefields[battlefield].province
:dedent: 4
:language: python
```

One text acting on several cards is one occurrence per step: "each step of each procedure takes
place simultaneously, in parallel" (CR, Timing Conflicts). An ability that builds its effects per
target and hits several targets returns one group for each step, every target's first effect
together, then every target's second. Two sentences of one card are not a group, and stay in order.

A group holds off triggers only. The walk still enforces the state-based rules after each member
commits, as it does after any effect, so a Personality the first member leaves at zero Chi is
destroyed before the second member applies. What the rules demanded is announced as the occurrence
that follows the group, once the group's own triggers have resolved.

So wrapping two effects in a group does not let both commit before the board is judged. Two clauses
happen in written order even inside one sentence. A clause that depends on an earlier one, as in
"discard a card to draw a card" or "if you put a Ring into play, ...", is a {class}`~.To`, so it
applies only if the earlier one actually happened.

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
