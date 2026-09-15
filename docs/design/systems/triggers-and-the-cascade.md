# Triggers and the cascade

A card never changes the board. It returns *effects*, and one function commits them. Committing an
effect raises *events*, events wake more triggers, and those triggers return more effects. That loop
is the cascade, and it is the engine's answer to "and then what happened".

Every piece of code below is from {mod}`yasuki_core.engine.rules.triggers`, and each block says
which symbol it is. Public symbols link to their API entry, which carries a source link. The
private helpers have no API entry, so they are named but not linked. Read them through the module
link above.

## What a trigger reads

{class}`~yasuki_core.engine.rules.triggers.TriggerContext`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: TriggerContext
:language: python
```

`game` is the live board, `card` is the copy whose trigger is firing, and `event` is what just
happened. A trigger takes one of these and returns a list of effects:

`rise_of_jigoku.py`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/cards/rise_of_jigoku.py
:pyobject: _rural_market_entered_play
:language: python
```

It must not mutate anything. There is exactly one place the board changes,
{func}`~yasuki_core.engine.rules.triggers.apply_effect`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: apply_effect
:language: python
```

Everything a trigger wants to happen goes through the effects it returns, which is what lets the
engine order them, settle the rules between them, and replay the game from its inputs.

## Which copies react

A seat may control three copies of {card}`Rural Market`, all sharing a `printed_id`. Collection
walks the battlefield and gathers every trigger registered for the event, so all three fire and
each decides for itself whether the event was about it. `_card_triggers`, the half of `_collect`
that gathers the cards' triggers:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _card_triggers
:language: python
```

The `departed` branch is the carve-out that makes "after this card is destroyed" possible at all. A
card is already in a discard pile by the time its destruction is announced, so without it the card
would be gone before its own trigger could run.

{card}`Goju Kaxt` is the card that needs it. `torn_asunder.py`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/cards/torn_asunder.py
:pyobject: _goju_kaxt_destroyed
:language: python
```

The Follower announces his own death from the discard pile, and nothing else could announce it for
him. Many printed cards carry a clause of that shape, so this is a category rather than one
card's quirk.

Compare that guard with {card}`Rural Market`'s, which is written identically and means the
opposite. Rural Market reacts to *other* Farms dying, so `ctx.event.card_id != ctx.card.id`
excludes itself. Goju Kaxt reacts only to itself, so the same line requires itself. The event says
which card it is about, and what the trigger does with that is the whole difference.

The carve-out covers a card's own departure and nothing else. Everything after it is over for that
card, which is why a Personality killed on arrival does not go on to take his enter-play trait.

Order is fixed before anything fires, by `_canonical_order`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _canonical_order
:language: python
```

Owner then card id. Two cards reacting to the same event resolve the same way every time, which
replay depends on.

## The rulebook reacts too

Some consequences follow an occurrence with no card behind them. After a dishonorable Personality
is destroyed, his controller loses Honor equal to his printed Personal Honor, and the CR calls that
a rulebook effect. It is a trigger with nobody to register it, so `rulebook_trigger` registers it
against the event type alone:

```{literalinclude} ../../../src/yasuki_core/engine/rules/rulebook/dishonor.py
:pyobject: lose_honor_for_a_dishonorable_death
:language: python
```

A rulebook trigger fires after every card's trigger for the same event, and its context card is the
card the event names, which is how the Honor loss above knows whose death it is reacting to. An
event about no card fires no rulebook trigger. The loss is an ordinary `GainHonor` in the cascade,
so any card reading `HonorChanged` sees it, and like every trigger's effect it is never held at the
Interrupt step.

## The walk

`_advance` is a worklist run to a fixpoint. The whole machine is its loop body:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:start-at: while True:
:end-at: firing = _collect(game, event)
:language: python
```

Three repeating steps. Apply the effects in hand, each committing at once with the events it raises
joining the queue. Fire the next trigger still waiting on the current event, whose effects become
the next effects in hand. Pop the next event and collect what answers it.

`_settle_state_based_actions` runs after every effect, not once at the end. That is the order the
Comprehensive Rules give, and it is why a Personality who dies as he arrives is dead before his
arrival is announced.

A trigger that re-emits the event that woke it would spin forever. The walk raises after 1,000
events and prints the last sixty steps, alternating events and the cards that reacted to them.
Sixty is usually enough to see the cycle.

## Pausing to ask

The first branch in that loop handles a pause. An
{class}`~yasuki_core.engine.rules.effects.InterruptingEffect` cannot resolve without an answer from
a player. {card}`Wheat Farm` is one: entering play, it offers its controller a choice of up to two
other Farms to give a token, and the cascade cannot go on until someone picks. The machine stops
and `_stash` stores everything still outstanding:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _stash
:language: python
```

The effects after this one, the triggers not yet fired, the event being processed, and the queue
behind it. The order in the loop above matters: the stash happens *before* `effect.request` is
called, because the work stack is last-in-first-out and an effect whose request queues its own work
needs that work to run first.

When the seat answers, {func}`~yasuki_core.engine.rules.triggers.resume_cascade`
picks up exactly where it stopped:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: resume_cascade
:language: python
```

The answer's effects splice in where the interrupting effect stood. Triggers whose card has left
play in the meantime are dropped, since a card off the battlefield reacts to nothing.

This is also why a paused decision names its resolver with a string rather than holding the
function. A stored closure would not rebuild to an equal object, and a pending decision has to
survive being written to a replay log and read back.

The other half of pausing is that nothing may drive the machine again until the question is
answered. A second walk started over an open question would pause on its own first interrupting
effect and overwrite the request, and the first question would be gone with nothing failing.
Every entry point below checks this first, `_refuse_mid_decision`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _refuse_mid_decision
:language: python
```

It always raises. The web server and the desktop client both drive this machinery, and a check
that only fails in tests eventually ships.

## Entry points

Five functions start a walk, and all of them check for an open question first.

{func}`~yasuki_core.engine.rules.triggers.fire`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: fire
:language: python
```

An empty walk with one event in the queue. {func}`~yasuki_core.engine.rules.triggers.fire_all` is
the same walk with several:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: fire_all
:language: python
```

The distinction is the rule, not a convenience. Occurrences that happen at the same instant go
through `fire_all` together: every card the end-of-turn discard removes, every card a turn's
straighten stands up, every pre-game permanent entering play. Firing them one at a time imposes
an order the rules do not give, and once a trigger on the first one pauses, the second call would
be a walk driven mid-decision.

{func}`~yasuki_core.engine.rules.triggers.resolve_effects` is the walk entered with effects in
hand and an empty queue, which is how a cost, a rulebook procedure's effects or a resolver's output
gets its derived reactions. {func}`~yasuki_core.engine.rules.triggers.resolve_action_effects` is
the same walk for an action's own effects, the ones step E of the Action Sequence hands over, and
the only ones the walk holds at the Interrupt step: each is wrapped as an `InterruptStep` on its
way through, while what a trigger returns inside that cascade is a trait's or the rulebook's and is
applied unwrapped. A `Then` among the action's effects carries that provenance to the deferred
step. {func}`~yasuki_core.engine.rules.triggers.resolve_delayed` is `resolve_effects` over the
effects held until a given moment. {func}`~yasuki_core.engine.rules.triggers.enforce_state_based_actions`
is how a caller that mutated the board directly gets the same guarantee the walk gives itself
after every effect: it settles the rules first and starts a walk only if that raised anything.
It carries the check itself because `_advance` would see the open question only after the rules
had already mutated the board.

## One cascade, end to end

Everything above shows a mechanism on its own. This follows one real cascade across the edge of
the walk, through the pause, the answer, and the work that resumes underneath, with the stack and
`pending` shown at each step. It is a session driven by hand with nothing but the engine's own
calls, and every assertion held when it ran. The trace lines are what the engine recorded:
`triggers._trace` is the ring buffer the walk prints when it fails to converge, and reading it
here shows the same lines a failure would.

The board is P1 holding two copies of {card}`Spearmen of the Akasha` in a hand that will be two
cards over the limit once the turn ends, with two Naga Personalities in play. The Spearmen's
trait reads "after the Spearmen reach the discard from hand or deck, offer to banish them for a
Naga Follower".

```python
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.cards.onyx_edition import NAGA_FOLLOWER
from yasuki_core.engine.rules.vocabulary.actions import Pass
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseCards,
    DecisionResponse,
    DiscardToHandSize,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.factory import build_token_print
from yasuki_core.game_pieces.prints import AttachmentPrint, FatePrint, PersonalityPrint

P1, P2 = PlayerId.P1, PlayerId.P2
state = TableState.empty_two_seat()
hand = state.zones[ZoneKey(P1, ZoneRole.HAND)]

# The Naga Follower the Spearmen can become, loaded as a creatable token template. A created
# token is stamped from a print the table already holds, the way a deck load provides one.
state.creatable_tokens[NAGA_FOLLOWER] = build_token_print(
    {
        "card_id": NAGA_FOLLOWER,
        "name": "Naga",
        "types": ["Follower", "Proxy"],
        "keywords": ["Naga", "Nonhuman"],
        "force": 1,
        "chi": None,
        "gold_cost": 0,
    }
)

# Two Naga Personalities on the battlefield, so each Spearmen has someone to become a Follower
# of. The trait offers only Naga bearers, and offers nothing when there are none.
for bearer in ("shahai", "shahai2"):
    card = L5RCard.of(
        PersonalityPrint,
        id=bearer,
        name=bearer,
        side=Side.DYNASTY,
        owner=P1,
        force=2,
        chi=2,
        keywords=("Naga",),
    )
    state.cards_by_id[card.id] = card
    state.battlefield.add(card)

# Seven filler cards in hand and one in the fate deck. The end of the turn draws one, so the hand
# will hold ten against a limit of eight, and the trim will ask for two.
for index in range(7):
    filler = L5RCard.of(FatePrint, id=f"P1-h{index}", name="H", side=Side.FATE, owner=P1)
    state.cards_by_id[filler.id] = filler
    hand.add(filler)
drawn = L5RCard.of(FatePrint, id="P1-fd0", name="F", side=Side.FATE, owner=P1)
state.cards_by_id[drawn.id] = drawn
state.decks[DeckKey(P1, Side.FATE)].cards = [drawn]

# Two copies of the Spearmen in hand. The printed id is what the trait is registered on, so both
# copies react to a discard, and each one's handler checks whether the event names its own card.
for card_id in ("spearmen", "spearmen2"):
    spearmen = L5RCard.of(
        AttachmentPrint,
        id=card_id,
        name="Spearmen of the Akasha",
        side=Side.FATE,
        owner=P1,
        printed_id="spearmen_of_the_akasha",
        attachment_type=AttachmentType.FOLLOWER,
        force=2,
        keywords=("Naga", "Nonhuman", "Kharmic"),
    )
    state.cards_by_id[card_id] = spearmen
    hand.add(spearmen)

# Starting the session snapshots the table into the log and opens the first turn from that
# snapshot, so `game` is the live state and `state` is only the starting record.
session = EngineSession.start(state, P1)
game = session.game
```

**The turn ends.** Four passes play P1's turn out. A round closes once every seat entitled to
act in it has passed in a row, and only the Action Phase admits the other seat, so it takes two
passes where the Battle and Dynasty Phases take one. The last pass ends the turn: `_end_turn`
draws, finds the hand two over, sets `DiscardToHandSize` on `pending` and returns. The stack is
empty, and the round is still P1's.

```python
session.act(P1, Pass())  # Action Phase: P1 declines to act
session.act(P2, Pass())  # Action Phase: P2 may take Open actions here and declines, so it closes
session.act(P1, Pass())  # Battle Phase: only the active seat may declare an attack
session.act(P1, Pass())  # Dynasty Phase: only the active seat acts, and the pass ends the turn

assert isinstance(game.pending, DiscardToHandSize) and game.pending.count == 2
assert game.stack == []
triggers._trace.clear()
```

**P1 answers, naming both Spearmen.** `submit` clears `pending`, pushes `BeginNextTurn` so the
next turn waits behind whatever the discard raises, and calls `apply_discard`. That moves both
cards to the discard and announces them as one instant: `fire_all` with two `CardDiscarded`
events. The walk pops the first event, collects both Spearmen's triggers, and fires the first. It
returns a `Choose`, an interrupting effect, so `_stash` pushes a `ResumeCascade` holding the
second trigger and the second event, and the effect's request goes on `pending`. Back in `submit`,
the drain stops at once because a question is open, and the yield hands nothing on because the
round has not changed. The next turn has not begun.

```python
session.submit(P1, DecisionResponse(("spearmen", "spearmen2")))

assert isinstance(game.pending, ChooseCards)
assert game.pending.candidates == ("shahai", "shahai2")
# The next turn, then the stash on top of it: LIFO, so the stash resumes first.
assert [type(item).__name__ for item in game.stack] == ["BeginNextTurn", "ResumeCascade"]
assert game.active is P1 and game.round.priority is P1
# The event, then the one trigger that ran before the pause.
assert list(triggers._trace) == [
    "CardDiscarded",
    "  spearmen_of_the_akasha (spearmen) reacts",
]
triggers._trace.clear()
```

**P1 chooses shahai.** `submit` clears `pending` and runs the choice resolver, which returns a
`Banish` and a `CreateToken`. `resume_paused_cascade` pops the stash and continues the walk with
those two effects in hand, ahead of the second trigger and the second event. Both apply, then the
second trigger fires for the second event, returns its own `Choose`, and the walk stashes and
pauses again. The stack reads the same as before because it is the same shape: the next turn
under a fresh stash.

```python
session.submit(P1, DecisionResponse(("shahai",)))

assert isinstance(game.pending, ChooseCards)
assert [type(item).__name__ for item in game.stack] == ["BeginNextTurn", "ResumeCascade"]
assert game.active is P1
# The answer's two effects, then the second event and its trigger, which pauses again.
assert list(triggers._trace) == [
    "    banish spearmen",
    "    P1 creates naga on shahai",
    "CardDiscarded",
    "  spearmen_of_the_akasha (spearmen2) reacts",
]
triggers._trace.clear()
```

**P1 chooses shahai2.** The same again, and this time the walk finds nothing left to fire or pop
and returns with `pending` clear. Now `submit`'s drain has work: it pops `BeginNextTurn`, which
begins the next turn. The two `EnteredPlay` lines are the Naga Followers the two answers created,
whose entry was queued behind the second answer's effects. P2's turn then opens through the same
stack, each of its instants a walk of its own: nothing to straighten here, the Province reveal,
the announcement. The active seat is P2 and the round is P2's, so the yield at the end of
`submit` sees a round it was not asked in and hands nothing on.

```python
session.submit(P1, DecisionResponse(("shahai2",)))

assert game.pending is None
assert game.stack == []
assert game.active is P2 and game.round.priority is P2
# The last answer's effects, the two Followers entering play, and P2's turn opening.
assert list(triggers._trace) == [
    "    banish spearmen2",
    "    P1 creates naga on shahai2",
    "EnteredPlay",
    "EnteredPlay",
    "    reveal P2's provinces",
    "TurnStarted",
]
banished = game.table.zones[ZoneKey(P1, ZoneRole.FATE_BANISH)]
assert sorted(card.id for card in banished.cards) == ["spearmen", "spearmen2"]
```

Read against the four rules on [Decisions and resumption](decisions-and-resumption.md), every step
uses one. The clear at the top of `submit` is rule 1, and it is what let the second question be
asked at all. `BeginNextTurn` waiting under the stash is rule 2. The two events announced together
is rule 3, and it is why the second Spearmen's offer was still in the stash when the first was
answered. A second `fire` would have overwritten it. Rule 4 is what would have fired had any step driven the walk while a
`ChooseCards` was open, and before these rules were true, the end-of-turn arm did exactly that
and the Spearmen never asked.
