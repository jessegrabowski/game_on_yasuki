# Duels

A duel is a procedure the rulebook runs between two Personalities, not a phase and not an Action
Round. It is created by a card, it has steps of its own with a window at each, and it resolves
inside the cascade of whatever created it. [The turn machine](turn-flow.md) owns the windows, and
[the trigger cascade](triggers-and-the-cascade.md) owns the resolution those steps queue into.

Nothing about a duel is a battle. A duel fought during a battle is its own procedure standing over
the Battle Sequence rather than a step of it, and no battle vocabulary applies inside one.

## One record, and the cards are not in it

{class}`~.DuelRecord` is the duel being fought: the two seats, the two Personalities, the step the
procedure stands at, and the outcome once there is one. It sits on
{attr}`~.GameState.duel` and the next duel declared replaces it.

The focused cards are deliberately not in the record. Each seat focuses into a zone of its own
({attr}`~.ZoneRole.FOCUS`), so a focused card is somewhere the table already knows about and
redaction already hides. A card id kept in the record instead would be a second answer to "where is
this card" that every board query would have to learn.

Two readings of the record matter, and they are not the same. `game.duel` is the last duel, ended or
not, which is what an effect resolving after a duel reads. {attr}`~.GameState.duel_being_fought` is
None once the duel reaches `DuelStep.ENDED`, which is what the procedure's own steps read:

```{literalinclude} ../../../src/yasuki_core/engine/rules/state.py
:start-at: def duel_being_fought(self)
:end-at: return None if duel is None or duel.step is DuelStep.ENDED else duel
:dedent: 4
:language: python
```

## The steps are work items, and a window stands in front of each

Every step the CR names is a point a card may react at. {func}`~.queue_duel_steps` is what makes
that true: it pushes each step with an {class}`~.OpenDuelWindow` in front of it, so a step never
runs until the Responses the step before it announced have been offered.

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

Every step subclasses {class}`~.DuelWork`. That is what lets a duel that ends early drop its own
steps off the stack and leave the work of whatever created it alone. A base class rather than a list
of types, so a step added later cannot be forgotten by the filter.

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

The focusing is the part of dueling that changed between arcs while the skeleton around it did not,
so it sits behind {class}`~.FocusProcedure` on {mod}`yasuki_core.ruleset`. A procedure owns what may
be focused, how many times, and what focusing one card does. It does not own the challenge, the
alternation, the strike, the reveal, the totals or the consequences.

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

A Focus Effect is a registry entry rather than a trigger, because the CR resolves these only for
revealed focused cards, in an order the active player chooses, and ignores every other line of text
on them. `ResolveFocusEffects` asks the active player to name the next one while more than one is
left and queues itself again with the rest, so an effect that pauses for a decision resumes into the
next card.

## Deciding it

{class}`~.DecideTheDuel` totals both sides and records who won. The higher total wins, an equal total
is won by a Duelist against a non-Duelist, and any other tie is lost by both:

```{literalinclude} ../../../src/yasuki_core/engine/rules/duel/resolution.py
:start-at: def _outcome_on_totals(game: GameState, duel: DuelRecord) -> DuelOutcome:
:end-at: return DuelOutcome((), (challenger, challenged), totals, focused)
:language: python
```

{class}`~.DuelOutcome` records `winners` and `losers` separately rather than deriving one from the
other, because an effect may alter one Personality's outcome without altering the other's. It also
records the totals and the ids of the focused cards, because the duel's last step discards those
cards and what a duel was decided on outlives the duel.

The end, the consequences and the discard are three further steps, so a question a card asks on
{class}`~.DuelResolved` is answered before the duel ends, and the consequences held for
`DUEL_CONSEQUENCES` resolve before the focused cards go to the discard pile.

## A duel that ends without resolution

A Personality leaving play ends the duel where it stands.
{func}`~.duelist_left_play` is a state-based action rather than a reaction, so a Personality
destroyed, discarded or moved out of play ends the duel the same way, and
{func}`~.end_without_resolution` does the ending.

That path drops every {class}`~.DuelWork` off the stack, lapses the ongoing records that lasted until
the duel's end, and *discards* the effects delayed to `DUEL_CONSEQUENCES` rather than resolving them.
One left held would resolve off the next duel's end. The focused cards are discarded with no effect.

The outcome it records is `DuelOutcome(winners=(), losers=(), totals={})`, and the empty `totals` is
what tells this duel from a tie. A tie has both seats in `losers` and real numbers in `totals`.
Anything reading an outcome has to branch on the outcome existing before it reads `winners`, since
an empty `winners` means both "nobody won" and, for a duel with no outcome at all, "not decided yet".

{card}`Poisoned Weapon` is the card that cares: it is playable only between the Focus Effects
resolving and the duel being decided, and the Chi it takes away can end the duel by destroying the
Personality it is played on.

## Where a card plugs in

{class}`~.StartDuel` is the effect that creates one, naming the two Personalities and nothing else.
No duel happens where one player controls both or either card has left play, which is the CR's own
wording: such a challenge does not happen rather than happening and failing.
{card}`Sanctioned Duel` is the worked example, and it puts the challenge to the challenged seat with
an `AskOption` first, because a refused challenge creates no duel at all.

A consequence that depends on who won is delayed to `DUEL_CONSEQUENCES` and reads the outcome there,
rather than deciding anything at declaration. `@focus_effect` registers a card's "As a Focus Effect"
text. `named_duel_stat` is what a card changes to have a duel compare something other than the
ruleset's default.

## What the client sees

{class}`~.DuelView` is the projection, built per viewer. The opponent's focused cards arrive as backs
because `ZoneRole.FOCUS` is not a public role, and each side's total is computed from the cards that
viewer can identify, so a player sees its own stack counted and the opponent's not. Once the duel has
an outcome the view reports `outcome.totals` instead, because the live sum collapses to the bare duel
stat the moment the focused cards are discarded.
