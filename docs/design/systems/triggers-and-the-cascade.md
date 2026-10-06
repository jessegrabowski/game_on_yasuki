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
each decides for itself whether the event was about it. The registry is keyed by where the card
must be, and a hand is walked only for an event some card registers to answer from hand, so the
common case costs nothing extra. `_card_triggers`, the half of `_collect` that gathers the cards'
triggers:

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

Collection puts the cards' triggers in `_canonical_order`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _canonical_order
:language: python
```

Owner then card id, so collection is the same every time, which replay depends on. It is not the
order they resolve in when they conflict. The walk below asks the active player for that.

## The rulebook reacts too

Some consequences follow an occurrence with no card behind them. After a dishonorable Personality
is destroyed, his controller loses Honor equal to his printed Personal Honor, and the CR calls that
a rulebook effect. It is a trigger with nobody to register it, so `rulebook_trigger` registers it
against the event type alone:

```{literalinclude} ../../../src/yasuki_core/engine/rules/rulebook/dishonor.py
:pyobject: lose_honor_for_a_dishonorable_death
:language: python
```

A rulebook trigger is collected after every card's trigger for the same event, and its context card
is the card the event names, which is how the Honor loss above knows whose death it is reacting to.
An event about no card fires no rulebook trigger. The loss is an ordinary `GainHonor` in the
cascade, so any card reading `HonorChanged` sees it, and like every trigger's effect it is never
held at the Interrupt step.

## The walk

`_advance` is a worklist run to a fixpoint over a stack of frames, bottom first. An effects frame
holds effects still to apply and the provenance they came with. An events frame holds one
occurrence: its events still to announce, the triggers they triggered still to fire, each with the
event it answers, and the events of the occurrence that follows it. The whole machine is its loop
body:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:start-at: while frames:
:end-at: top.firing = _triggered(game, top.firing)
:language: python
```

The top frame decides each step. An effects frame applies its next effect, which commits at once.
The events it raised become a new events frame on top. What the state-based rules then demand of
the board is a later occurrence, so its events are that frame's `following`, announced once the
effect's own triggers have resolved. A moment works the same way: {func}`~.reach_moment` announces
what the lapse left before the events that mark the moment.

An events frame first announces all its events and collects every trigger they wake, since they
are one occurrence. A trait whose condition the occurrence did not meet returns no effects, so when
several were collected, `_triggered` asks each once and drops those that would do nothing. Such a
trait is not triggered, whatever a sibling's resolution makes of the board later. Asking is safe
because a handler never changes the board. The frame then fires its next trigger, whose effects
become a new effects frame on top carrying the trigger's own provenance. A trigger whose card has
since left where it answers from, destroyed by an earlier sibling say, is dropped instead. A frame
with nothing left is dropped, and the walk ends with the stack.

When two or more triggers are left, on one card or several, they conflict, and "the active player
decides the order in which they happen" (CR, Timing Conflicts). The walk stashes itself and asks a
{class}`~.ChooseNextTrigger` naming each trigger, its card and its printed trait, and
{func}`~yasuki_core.engine.rules.triggers.resume_trigger_order` fires the named one first. The
chosen trigger resolves completely, and the active player is asked again for every trigger of the
occurrence, the last included, so nothing fires that the player did not activate. Before asking,
the walk drops any trigger that would now do nothing. Each trigger's own questions stay its
controller's (CR, Choices), a "you may" among them, and a rulebook trigger fires on the card its
event names. A card in a hand is never a candidate, since naming it would show the active player what its
owner holds. A card answers from a hand only to offer entering play, which may follow its condition
immediately and may not be delayed (CR, Ring), so its triggers resolve before the others and before
any order is asked, each asking its own controller. A lone trigger with nothing to conflict with
fires without asking.

A card can also have a trigger another card gives it, as "Your Followers and Personalities at this
battlefield have, 'Yu: ...'" reads. {func}`~yasuki_core.engine.rules.triggers.granted_trigger`
registers it under the granting card, with a `reaches` read saying which cards have it now.
`_collect` reads the grants of the cards in play for the card each event names, so a granted
trigger answers only events about the card it was given, and that card fires it as its own: it is
ordered among the card's other triggers, and a card with two such triggers offers both.

An effect can give a trigger too, as "Give a target Personality, 'Yu: ...'" reads. The effect
records a {class}`~.GrantAbility` naming the card, and the granting card registers the trigger with
{func}`~yasuki_core.engine.rules.triggers.given_by_effect` as its `reaches`. The record outlasts its
source, so `_collect` also reads the records naming the card whose source has left play, as a
Strategy has once it resolved.

Pushing each commit's events on top is what makes the walk depth-first, which is the order the CR
gives: "Once a triggered trait starts, activate all its costs, targeting, and effects in sequence
before proceeding, even if another action or triggered trait is under way" (CR 20F, Timing).
Everything an effect sets off, the triggers its events wake and whatever their own effects set off
in turn, resolves before the next effect in the list applies. A trigger's effects frame, with every
frame above it, finishes before its sibling trigger fires.

A {class}`~.Simultaneously` group is the one exception, for things that happen at once, such as
"two Personalities being destroyed in battle resolution" (CR, Timing Conflicts). The walk pushes an
empty events frame and the group's members above it as an effects frame of their own. Each member's
events join that one events frame, so nothing reacts to any member until all of them have
happened. A {class}`~.To` applies its `first` effect and then its `contingent` effects only if
`first` actually happened, as {func}`~yasuki_core.engine.rules.triggers.happens_as` judges, since
"the second effect depends on the first effect actually happening" (CR, Independence of
Effects).

A destruction can also be acted on before it commits. "Before a card with the Yu trait is
destroyed by another player's action during battle, or during resolution, resolve the Yu effect"
(ShE datasheet, The Yu Trait). Whenever some card answers it, the walk announces a
{class}`~.Destroying` for each card of the unit before the {class}`~.Destroy` commits. It reads the
effect as the Interrupt modifications will leave it and skips one that a negation in force will
negate, since "the negation/substitution will always occur first". It then puts the effect back at
the head of its frame, records the cards in the frame's `announced`, and pushes the announcement as
an events frame. The traits it wakes resolve while the card still stands, and the effect commits
when it comes back up, through the Interrupt modifications and the negation check like any other,
so a negation one of those traits granted stops it. A card leaving with a Personality's unit names
him in `leaves_with`, and one a trait moves out of that unit before the commit stays in play.

A Yu resolves only for a destruction by battle resolution or by another player's action in battle,
unless a card in play widens it. {class}`~.YuWidening`, registered with `register_yu_widening`,
reaches the cards whose Yu resolves though their controller's own action destroyed them: always,
as A Good Day to Die's "Your cards' Yu effects trigger even when destroyed by your actions" reads,
or at the controller's choice, as "you may choose to have the trait trigger" reads. Either way the
destruction still has to come during battle. A chosen Yu asks its controller as it fires, unless it
would do nothing, and resolves on a yes.

A group's destructions are announced together, as one occurrence, before any member commits. The
walk forecasts every member, a `once` negation hiding only the first member it will spend itself
on, and pushes the announcement above the group's frame. A member the forecast missed, a card a
trait put into play say, is announced as it comes up. A destruction the state-based rules demand is
never announced, since no player's action causes it, and nothing is announced when no card answers,
so a game without such a trait walks exactly as before.

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
and `_stash` stores every frame still outstanding:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _stash
:language: python
```

The paused frame keeps the effects after this one, and the frames beneath it keep the triggers not
yet fired, the event being processed, and the queue behind it. Each frame is stored as a frozen
{class}`~yasuki_core.engine.rules.triggers.EffectsFrame` or
{class}`~yasuki_core.engine.rules.triggers.EventsFrame` naming its cards by id, so the stash
compares equal under replay. An effects frame keeps the cards whose destruction it has announced, so
a walk paused while destroying does not announce them again when it resumes. The order in the loop above matters: the stash happens *before*
`effect.request` is called, because the work stack is last-in-first-out and an effect whose request
queues its own work needs that work to run first.

When the seat answers, {func}`~yasuki_core.engine.rules.triggers.resume_cascade`
picks up exactly where it stopped:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: resume_cascade
:language: python
```

The answer's effects splice into the top frame, where the interrupting effect stood, and every
effects frame resumes under its own provenance. Triggers whose card has left play in the meantime
are dropped, since a card off the battlefield reacts to nothing.

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
straighten stands up, every unit a seat assigns to a battlefield in one answer. Firing them one at
a time imposes an order the rules do not give, and once a trigger on the first one pauses, the
second call would be a walk driven mid-decision.

{func}`~yasuki_core.engine.rules.triggers.resolve_effects` is the walk entered with effects in
hand and an empty queue, which is how a rulebook procedure's effects or a resolver's output gets
its derived reactions. {func}`~yasuki_core.engine.rules.triggers.pay_costs` is the same walk for a
cost. A cost is no effect (CR, Effects), so the walk checks every other effect against the
{class}`~.Negation` records in force as it commits and passes a cost's payments through, and a
payment that pauses on a question stays a cost once answered. {func}`~yasuki_core.engine.rules.triggers.resolve_action_effects` is
the same walk for an action's own effects, the ones step E of the Action Sequence hands over. The
first effects an action hands over are held on the stack as a `HeldAction` beneath an Interrupt
round before any resolves, once per action and only when some seat holds an Interrupt, and every
one of the action's effects is checked against the modifications the step collected before it is
applied, while what a trigger returns inside that cascade is a trait's or the rulebook's and is
applied as returned. The provenance also names the card whose action it is, which a
{class}`~.Negation` naming a source reads as each effect commits. {func}`~yasuki_core.engine.rules.triggers.resolve_delayed` is `resolve_effects` over the
effects held until a given moment. An effect an action holds stays that action's: the walk wraps it
in a {class}`~.Attributed` carrying the action's provenance as the delay commits, and resolves it
under that provenance when its moment comes, with the effects held beside it stashed so their order
holds. {func}`~yasuki_core.engine.rules.triggers.reach_moment` is the
same for a moment ongoing records also last until: it lapses them, settles the board their expiry
leaves, and resolves the held effects, in one walk so a question any part asks pauses the rest. {func}`~yasuki_core.engine.rules.triggers.enforce_state_based_actions`
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
    ChooseDiscard,
    ChooseNextTrigger,
    DecisionResponse,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.factory import build_print
from yasuki_core.game_pieces.prints import AttachmentPrint, FatePrint, PersonalityPrint

P1, P2 = PlayerId.P1, PlayerId.P2
state = TableState.empty_two_seat()
hand = state.zones[ZoneKey(P1, ZoneRole.HAND)]

# The Naga Follower the Spearmen can become, loaded as a creatable token template. A created
# token is stamped from a print the table already holds, the way a deck load provides one.
state.creatable_tokens[NAGA_FOLLOWER] = build_print(
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
        printed_id=bearer,
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
    filler = L5RCard.of(
        FatePrint, id=f"P1-h{index}", printed_id=f"P1-h{index}", name="H", side=Side.FATE, owner=P1
    )
    state.cards_by_id[filler.id] = filler
    hand.add(filler)
drawn = L5RCard.of(
    FatePrint, id="P1-fd0", printed_id="P1-fd0", name="F", side=Side.FATE, owner=P1
)
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
announces the turn's end, the rulebook's `DrawCard` resolves, and `EnforceMaximumHandSize` finds the
hand two over. It queues `BeginNextTurn`, then
resolves a `DiscardFromHand` for two cards that P1 picks. That is an interrupting effect, so the
walk stashes a `ResumeCascade` above the next turn and puts a `ChooseDiscard` on `pending`. The
round is still P1's.

```python
session.act(P1, Pass())  # Action Phase: P1 declines to act
session.act(P2, Pass())  # Action Phase: P2 may take Open actions here and declines, so it closes
session.act(P1, Pass())  # Battle Phase: only the active seat may declare an attack
session.act(P1, Pass())  # Dynasty Phase: only the active seat acts, and the pass ends the turn

assert isinstance(game.pending, ChooseDiscard) and game.pending.count == 2
# The next turn, then the stash on top of it: LIFO, so the stash resumes first.
assert [type(item).__name__ for item in game.stack] == ["BeginNextTurn", "ResumeCascade"]
triggers._trace.clear()
```

**P1 answers, naming both Spearmen.** `submit` clears `pending`, and `resume_paused_cascade`
pops the stash and continues the walk with the same `DiscardFromHand`, narrowed to the two cards
named. Nothing is left to choose, so it applies: both cards reach the discard before either is
announced, and the two `CardDiscarded` events become one events frame. The walk announces both and
collects both Spearmen's triggers together, since they answer one occurrence. Each would offer a
Naga, so two triggers conflict, and the active player decides which resolves first (CR, Timing
Conflicts). `_stash` pushes a `ResumeCascade` holding both, and a `ChooseNextTrigger` goes on
`pending`. Back in `submit`, the drain stops at once because a question is open, and the yield
hands nothing on because the round has not changed. The next turn has not begun.

```python
session.submit(P1, DecisionResponse(("spearmen", "spearmen2")))

assert isinstance(game.pending, ChooseNextTrigger)
assert game.pending.candidates == ("spearmen", "spearmen2")
assert [type(item).__name__ for item in game.stack] == ["BeginNextTurn", "ResumeCascade"]
assert game.active is P1 and game.round.priority is P1
# The discard, then both events of the one occurrence.
assert list(triggers._trace) == [
    "    P1 discards 2 from hand, chosen by P1",
    "CardDiscarded",
    "CardDiscarded",
]
triggers._trace.clear()
```

**P1 orders the first Spearmen first.** `resume_trigger_order` pops the stash and continues the
walk, firing the named card's trigger. It returns a `Choose`, an interrupting effect, so `_stash`
pushes a fresh `ResumeCascade` holding the second trigger, and the effect's request goes on
`pending`.

```python
session.submit(P1, DecisionResponse(("spearmen",)))

assert isinstance(game.pending, ChooseCards)
assert game.pending.candidates == ("shahai", "shahai2")
assert [type(item).__name__ for item in game.stack] == ["BeginNextTurn", "ResumeCascade"]
assert list(triggers._trace) == ["  spearmen_of_the_akasha (spearmen) reacts"]
triggers._trace.clear()
```

**P1 chooses shahai.** `submit` clears `pending` and runs the choice resolver, which returns a
`Banish` and a `CreateToken`. `resume_paused_cascade` pops the stash and continues the walk with
those two effects in hand, ahead of the second trigger. Both apply, and the created Naga Follower's
`EnteredPlay` is announced before anything else moves, because what an effect sets off resolves
before the walk goes on. The rulebook's Invest trigger answers it, on the Follower the event names,
and finds nothing Invested. The second trigger is still the occurrence's, so P1 is asked for it
too, alone as it now is: the active player activates every trigger the occurrence woke. The stack
reads the same as before because it is the same shape: the next turn under a fresh stash.

```python
session.submit(P1, DecisionResponse(("shahai",)))

assert isinstance(game.pending, ChooseNextTrigger)
assert game.pending.candidates == ("spearmen2",)
assert [type(item).__name__ for item in game.stack] == ["BeginNextTurn", "ResumeCascade"]
assert game.active is P1
# The answer's two effects, then the Follower entering play.
assert list(triggers._trace) == [
    "    banish spearmen",
    "    P1 creates naga on shahai",
    "EnteredPlay",
    "  naga (token-1) reacts",
]
triggers._trace.clear()
```

**P1 activates the second Spearmen.** It fires, returns its own `Choose`, and pauses the walk again.

```python
session.submit(P1, DecisionResponse(("spearmen2",)))

assert isinstance(game.pending, ChooseCards)
assert list(triggers._trace) == ["  spearmen_of_the_akasha (spearmen2) reacts"]
triggers._trace.clear()
```

**P1 chooses shahai2.** The same again, and this time the walk finds nothing left to fire or pop and
returns with `pending` clear. Now `submit`'s drain has work: it pops `BeginNextTurn`, which begins
the next turn. The `EnteredPlay` line is the second Naga Follower entering play, announced right
after it was created and answered by the Invest trigger, as the first one was. P2's turn then opens
through the same stack, each of its instants a walk of its own: nothing to straighten here, the
Province reveal, the turn's start, and the Action Phase's start. The active seat is P2 and the round
is P2's, so the yield at the end of `submit` sees a round it was not asked in and hands nothing on.

```python
session.submit(P1, DecisionResponse(("shahai2",)))

assert game.pending is None
assert game.stack == []
assert game.active is P2 and game.round.priority is P2
# The last answer's effects, the second Follower entering play, and P2's turn opening.
assert list(triggers._trace) == [
    "    banish spearmen2",
    "    P1 creates naga on shahai2",
    "EnteredPlay",
    "  naga (token-2) reacts",
    "    reveal P2's provinces",
    "TurnBoundary",
    "PhaseStarted",
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
