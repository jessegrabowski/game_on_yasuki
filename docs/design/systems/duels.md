# Duels

A duel is a procedure the rulebook runs between two Personalities. A card creates it, it has steps
of its own with a window at each, and it resolves inside the cascade of whatever created it.
[The turn machine](turn-flow.md) opens those windows, and
[the trigger cascade](triggers-and-the-cascade.md) resolves what the steps queue.

A duel fought during a battle is still its own procedure, and no battle vocabulary applies inside
one. It stands over the Battle Sequence and is not a step in it.

## One record, and the cards on the table

{class}`~.DuelRecord` is the duel being fought: the two seats, the two Personalities, the step the
procedure stands at, and the outcome once there is one. It sits on
{attr}`~.GameState.duel` and the next duel declared replaces it.

The focused cards are not in the record. Each seat focuses into a zone of its own
({attr}`~.ZoneRole.FOCUS`), so a focused card is somewhere the table already knows about and
redaction already hides. A card id kept in the record instead would be a second answer to "where is
this card" that every board query would have to learn.

`game.duel` is the last duel, ended or not, which is what an effect resolving after a duel reads.
{attr}`~.GameState.duel_being_fought` is None once the duel reaches `DuelStep.ENDED`, which is what
the procedure's own steps read:

```{literalinclude} ../../../src/yasuki_core/engine/rules/state.py
:start-at: def duel_being_fought(self)
:end-at: return None if duel is None or duel.step is DuelStep.ENDED else duel
:dedent: 4
:language: python
```

## The steps are work items, and a window stands in front of each

Every step the CR names is a point a card may react at. {func}`~.queue_duel_steps` pushes each step
with an {class}`~.OpenDuelWindow` in front of it, so a step never runs until the Responses the step
before it announced have been offered.

```{literalinclude} ../../../src/yasuki_core/engine/rules/duel/procedure.py
:start-at: def queue_duel_steps(game: GameState, *steps: DuelWork) -> None:
:end-at: game.stack.append(OpenDuelWindow())
:language: python
```

`RoundKind.DUEL_WINDOW` is the round those windows open, and it permits Responses alone, because a
duel's steps are not an Action Round of their own and the CR gives no other designator a turn inside
one. It is one of `ROUNDS_OVER_HELD_WORK`: closing it resumes the duel's remaining steps from
beneath it rather than yielding priority, since the action that declared the duel has not finished
resolving.

Every step subclasses {class}`~.DuelWork`. A duel that ends early drops its own steps off the stack
and leaves the work of whatever created it alone. The filter tests the base class, so a step added
later cannot be forgotten.

## The focusing loop

{func}`~.declare_duel` opens the duel with one step queued, and the first option belongs to the
challenged seat. {class}`~.OfferFocusOrStrike` puts the option to one seat, and answering it with a
focus queues the option for the other, which is the alternation. A seat with nothing to focus is not
asked at all, because the CR gives it no second option and a question with one answer is not a
decision.

The candidates of a {class}`~.FocusOrStrike` are tokens, not card ids: one `focus_token(card_id)` per
hand card, `DECK_TOP` for the unseen top of the Fate deck, and `STRIKE`. Anything reading them back
has to go through `focus_source`, which is why the board's card-id selection mode cannot answer this
request.

## What may be focused is the arc's business

The focusing changed between arcs while the rest of the procedure did not, so it sits behind
{class}`~.FocusProcedure` on {mod}`yasuki_core.ruleset`. A procedure decides what may be focused,
how many times, and what focusing one card does. The duel keeps the rest: the challenge, the
alternation, the strike, the reveal, the totals and the consequences.

{class}`~.TwentyFestivalsFocusing` is the implemented one: from hand or unseen off the Fate deck,
four times per seat, with nothing owed at the end. A focused card is turned face down and peeked
back to its own controller, because a player may read every card in its own focusing area and may not
read another player's. One taken off the deck is chosen before the seat learns what it is.

Every method that acts returns effects for the duel to resolve, so an arc that applies each Focus
Value as its card is focused is expressible without the duel knowing. `focus_total` is the other half
of that seam: it returns zero for such an arc, and the sum of the focused cards' `Stat.FOCUS` for
this one.

## The strike, the reveal, and the Focus Effects

A strike ends the focusing and queues the rest of the duel in one call, in the CR's order: the
reveal, the Focus Effects it queues, the outcome, the duel's end, the consequences that wait for it,
then the discard.

```{literalinclude} ../../../src/yasuki_core/engine/rules/duel/procedure.py
:start-at: RevealFocusedCards(),
:end-at: DiscardFocusedCards(),
:dedent: 8
:language: python
```

{class}`~.RevealFocusedCards` turns both stacks face up at once and drops the private reads, so
nothing in a duel stays hidden past that point. It then queues
{class}`~.ResolveFocusEffects` with the revealed cards that carry one.

Focus Effects live in a registry of their own, not the trigger system, because the CR resolves them
only for revealed focused cards, in an order the active player chooses, and ignores every other line
of text on them. `ResolveFocusEffects` asks the active player to name the next one while more than
one is left and queues itself again with the rest, so an effect that pauses for a decision resumes
into the next card.

## Deciding it

{class}`~.DecideTheDuel` totals both sides and records who won. The higher total wins, an equal total
is won by a Duelist against a non-Duelist, and any other tie is lost by both:

```{literalinclude} ../../../src/yasuki_core/engine/rules/duel/resolution.py
:start-at: def _outcome_on_totals(game: GameState, duel: DuelRecord) -> DuelOutcome:
:end-at: return DuelOutcome((), (challenger, challenged), totals, focused)
:language: python
```

{class}`~.DuelOutcome` records `winners` and `losers` separately, because an effect may alter one
Personality's outcome without altering the other's. It also records the totals and the ids of the
focused cards, because the duel's last step discards those cards and what a duel was decided on
outlives the duel.

The end, the consequences and the discard are three further steps, so a question a card asks on
{class}`~.DuelResolved` is answered before the duel ends, and the consequences held for
`DUEL_CONSEQUENCES` resolve before the focused cards go to the discard pile.

## A duel that ends without resolution

A Personality leaving play ends the duel where it stands.
{func}`~.duelist_left_play` is a state-based action rather than a reaction, so a Personality
destroyed, discarded or moved out of play ends the duel the same way, and
{func}`~.end_without_resolution` does the ending.

That path drops the duel's own steps off the stack, except one. The Focus Effects of the cards the
strike revealed still resolve, because the CR resolves them whatever becomes of the duel, which
{card}`Relentless` prints as a reminder. A step says for itself whether it outlives an early exit:

```{literalinclude} ../../../src/yasuki_core/engine/rules/duel/records.py
:start-at: survives_early_exit: ClassVar[bool] = False
:end-at: survives_early_exit: ClassVar[bool] = False
:dedent: 4
:language: python
```

The default drops a step, so one added later needs no edit here to be dropped. Only
{class}`~.ResolveFocusEffects` sets it true, and {func}`~.end_without_resolution` requeues it.

Two things have to run after it. The cleanup discards the focused cards those Focus Effects read.
And {class}`~.DropDuelConsequences` lapses the ongoing records scoped to the duel's end and discards
the effects delayed to `DUEL_CONSEQUENCES`, which has to wait because a Focus Effect resolving past
the exit can hold a consequence of its own, and one left held resolves off the next duel's end. The
stack pops its last item first, so all three are pushed in the opposite order. The focused cards
are discarded with no effect.

The outcome it records is `DuelOutcome(winners=(), losers=(), totals={})`, and the empty `totals` is
what tells this duel from a tie. A tie has both seats in `losers` and real numbers in `totals`.
Anything reading an outcome has to branch on the outcome existing before it reads `winners`, since
an empty `winners` means both "nobody won" and, for a duel with no outcome at all, "not decided yet".

{card}`Poisoned Weapon` depends on this. It is playable only between the Focus Effects resolving and
the duel being decided, and the Chi it takes away can end the duel by destroying the Personality it
is played on.

## Where a card plugs in

{class}`~.StartDuel` is the effect that creates one, naming the two Personalities and nothing else.
No duel happens where one player controls both or either card has left play. The CR's wording is
that such a challenge does not happen at all, so nothing is created and nothing fails.
{card}`Sanctioned Duel` is the worked example, and it puts the challenge to the challenged seat with
an `AskOption` first, because a refused challenge creates no duel at all.

A consequence that depends on who won is delayed to `DUEL_CONSEQUENCES` and reads the outcome there.
`@focus_effect` registers a card's "As a Focus Effect" text. `named_duel_stat` is what a card
changes to have a duel compare something other than the ruleset's default.

## What the client sees

{class}`~.DuelView` is the projection, built per viewer. The opponent's focused cards arrive as backs
because `ZoneRole.FOCUS` is not a public role, and each side's total is computed from the cards that
viewer can identify, so a player sees its own stack counted and the opponent's not. Once the duel has
an outcome the view reports `outcome.totals` instead, because the live sum collapses to the bare duel
stat the moment the focused cards are discarded.
