# Stack and tree

Most people who come to this engine know Magic: The Gathering, and Magic's stack is the model they
bring for "something happens and a card reacts to it". L5R has no stack. Its rules resolve what an
action sets off as a depth-first walk of a tree, and on real boards the two models give different
orders and different results. The worked examples below play both over the same L5R boards.
[Triggers and the cascade](systems/triggers-and-the-cascade.md) describes the engine's loop.

## Magic's stack

Magic keeps a stack that both players can see (Magic Comprehensive Rules, 405). Casting a spell or
activating an ability puts it on top. Every player then gets priority to respond (117), and a
response goes on top of what it answers. When all players pass in turn, the top object resolves, so
the last thing added is the first to happen.

In the standard example, a player casts Giant Growth (+3/+3) on their own Grizzly Bears (2/2), and
the opponent responds with Lightning Bolt (3 damage) on the Bears:

```{mermaid}
flowchart LR
    s1["<b>1. Giant Growth is cast</b><br/><br/>Giant Growth on the Bears"]
    s2["<b>2. Lightning Bolt in response</b><br/><br/>Lightning Bolt on the Bears<br/>Giant Growth on the Bears"]
    s3["<b>3. Bolt resolves, the Bears die</b><br/><br/>Giant Growth, its target gone"]
    s1 --> s2 --> s3
```

Each box lists the stack at one moment, top first. The Bolt resolves first and deals 3 damage to
a 2/2. The Bears die when a player would next receive priority, which is when state-based actions
are checked (704.3). Giant Growth then has no target.

Three more of Magic's rules matter here:

- A spell or ability resolves as a whole. Nothing it causes happens in the middle of it. What it
  triggers waits and is put on the stack the next time a player would receive priority (603.3).
- Triggers waiting together are ordered by their controllers, the active player's first and the
  non-active player's on top of them (603.3b). The non-active player's triggers resolve first.
- Any player with priority may add to the stack, at any depth, including in response to a trigger.

## L5R's tree

L5R has no shared object to put things on. The Twenty Festivals Comprehensive Rules say (CR 20F,
Timing): "Once a triggered trait starts, activate all its costs, targeting, and effects in sequence
before proceeding, even if another action or triggered trait is under way." The effects of an action
are steps taken in written order, and a triggered trait that an effect sets off runs to completion
before the next step. What a step sets off hangs beneath it, and what that sets off hangs beneath
it in turn. The result is a tree, walked depth first: each branch finishes before the walk moves to
the next sibling.

Four more rules decide the shape of the tree:

- Players add to it at only two points of an action, the Interrupt step before its effects and the
  Response step after them. The ShE rules datasheet opens both windows only for an action that is
  neither an Interrupt nor a Response. Nobody can act in answer to a triggered trait.
- "Two things in the game can happen at the same time (e.g., two Personalities being destroyed in
  battle resolution.)" (CR, Timing Conflicts). Such things are one node, and nothing reacts to any
  of them until all of them have happened.
- "If more than one of these things conflict, the active player decides the order in which they
  happen" (CR, Timing Conflicts). The active player orders every trait one node woke, whoever
  controls them. Each trait's own targets and choices still belong to its controller (CR, Choices).
- The state-based rules apply at once. "If a Personality's Chi is ever zero, destroy him
  immediately" (CR). The destruction hangs beneath the effect that zeroed the Chi.

| Question | Magic | L5R |
|---|---|---|
| When does a reaction to an effect resolve? | After the spell or ability that caused it has finished. | Before the next effect of the action or trait under way. |
| Can a player answer a reaction? | Yes, while it is on the stack. | No. A triggered trait resolves at once. |
| Who orders reactions to one occurrence? | Each controller orders their own, and the non-active player's resolve first. | The active player orders all of them. |
| When do the state-based rules apply? | When a player would receive priority. | Immediately. |
| Who sees pending reactions? | Everyone. The stack is public. | Pending traits on cards in a hand are never named to the active player. |

Most of the differences below come from the first row. Magic finishes the thing resolving before
anything it caused, and L5R resolves what an effect caused before the next effect of the thing
resolving.

## Worked examples

Every board below is legal in Shattered Empire, and the engine resolves each one as
described. The numbers in each tree give the order the engine follows.

### Recruiting Rural Market under Shosuro Aoki

P1 controls Shosuro Aoki, "Yoritomo Kayoko" (Experienced): "After your Holding gains any Wealth
tokens, once per turn, draw a card." Rural Market is face up in P1's Province: "After this Holding
enters play, and after your Farm is destroyed, give this Holding a +1GP Wealth token." P1 Recruits
Rural Market.

A Recruit brings the card into play and then refills the Province it left. In L5R the card's
entry is the first step, and everything it sets off finishes before the refill:

```{mermaid}
flowchart TB
    recruit(["P1 Recruits Rural Market"])
    recruit --> enter["1. Rural Market enters play"]
    recruit --> refill["4. the Province refills"]
    enter --> market(["Rural Market's trait"]) --> token["2. a Wealth token on Rural Market"]
    token --> aoki(["Aoki's trait"]) --> draw["3. P1 draws a card"]
```

Read with Magic's stack, the Recruit would resolve as a whole, entry and refill together. Rural
Market's trigger would then go on the stack and resolve, and only then would Aoki's trigger exist
to go on the stack:

```{mermaid}
flowchart LR
    r["Recruit resolves:<br/>enter play, refill"] --> m["Rural Market's trigger<br/>on the stack, resolves:<br/>Wealth token"]
    m --> a["Aoki's trigger<br/>on the stack, resolves:<br/>draw"]
```

The stack gives enter, refill, token, draw. The tree gives enter, token, draw, refill. In Magic
either player could also respond to each trigger while it waited. In L5R neither trait can be
answered, and the refill is the next thing that can happen.

### Blood of Fu Leng and the Kharmic draw

P2's only Personality is Moto Batu, 3F/1C. P1 holds Blood of Fu Leng: "After you discard this
Strategy from a Kharmic action, give a target Personality -1C." P1 takes Blood's Kharmic action,
paying its Gold and discarding it to draw a card.

"Effects linked by the word 'to' mean that the second effect depends on the first effect actually
happening" (CR, Independence of Effects). The discard is the first step and the draw the second.
The discard sets off Blood's trait, whose -1C leaves Moto Batu at zero Chi, and the Chi rule
destroys him. All of that hangs beneath the discard:

```{mermaid}
flowchart TB
    kharmic(["P1's Kharmic action"])
    kharmic --> discard["1. discard Blood of Fu Leng"]
    kharmic --> draw["4. P1 draws a card"]
    discard --> blood(["Blood's trait:<br/>P1 targets Moto Batu"]) --> chi["2. Moto Batu gets -1C"]
    chi --> death(["Chi rule: zero Chi"]) --> destroy["3. Moto Batu is destroyed"]
    destroy --> reactions(["anything that reacts<br/>to his destruction"])
```

Moto Batu is in the discard pile before P1 draws, and any trait reacting to his destruction has
resolved too. Read with Magic's stack, the Kharmic action would resolve whole, discard and draw. The
trigger would go on the stack and resolve, and Moto Batu would die only when a player next received
priority:

```{mermaid}
flowchart LR
    k["Kharmic resolves:<br/>discard, draw"] --> b["Blood's trigger<br/>on the stack, resolves:<br/>-1C"]
    b --> s["priority:<br/>state-based check,<br/>Moto Batu dies"]
```

So the stack draws before the death, and the tree draws after it, once a branch three levels deep
has finished.

### Two Rice Farms under Shosuro Aoki

On some boards the stack and the tree agree. P1 controls Aoki and two Rice Farms: "After your turn
begins, give this Holding a +1GP Wealth token." P1's turn begins, and both Farms trigger.

P1 is the active player, so P1 orders them. The Farm named first resolves completely, and that
includes Aoki's draw, before the second Farm's trait starts:

```{mermaid}
flowchart TB
    begins{{"P1's turn begins"}}
    begins -- "named first" --> farm_a(["first Rice Farm"])
    begins -- "then" --> farm_b(["second Rice Farm"])
    farm_a --> token_a["1. a Wealth token"] --> aoki(["Aoki's trait"]) --> draw["2. P1 draws a card"]
    farm_b --> token_b["3. a Wealth token"]
```

Aoki's draw is once per turn, so the second token draws nothing. Magic gives the same order. Both
triggers go on the stack in P1's order, and when the first resolves, Aoki's trigger goes on top of
the second Farm's and resolves before it. Because the stack is last in, first out, what an ability
triggers resolves before that ability's siblings, which is the depth-first order.

The two models agree when each node of the tree is a single trait with one effect and nobody
responds. They part when a node has more than one effect, as in the first two examples, and when
both players' traits wake at once, as in the next.

### A tie at Fields of Slaughter

P1 is the active player and attacks one of P2's Provinces. At that battlefield P1 has Moto Batu
(3F) and has played Fields of Slaughter: "Gain 2 Honor after each time a card at this battlefield
that you do not control is destroyed." P2 defends with Ikoma Shika (2F) carrying The Forgotten (1F):
"After this Follower enters play or is destroyed, lose 2 Honor and create a 1F ... Follower and
Equip it to your target Personality." Kitsu Shokka is at P2's home, and Ring of Earth is in P2's
hand.

The armies tie at 3 Force. "The Attacker and Defender each destroy all units in the enemy army" (CR,
Battle Resolution), so Moto Batu, Ikoma Shika and The Forgotten are destroyed as one occurrence.
That one node wakes three traits: Fields of Slaughter for Ikoma Shika, Fields of Slaughter for The
Forgotten, and The Forgotten's own. P1 orders all three, P2's included:

```{mermaid}
flowchart TB
    resolution(["battle resolution"])
    resolution --> tie{{"one occurrence: Moto Batu, Ikoma Shika<br/>and The Forgotten destroyed"}}
    resolution --> spoils["5. each side gains Honor<br/>for the cards it destroyed"]
    tie -- "P1 names it first" --> forgotten(["The Forgotten's trait"])
    tie -- "then" --> f1(["Fields: Ikoma Shika"])
    tie -- "then" --> f2(["Fields: The Forgotten"])
    forgotten --> lose["1. P2 loses 2 Honor"]
    forgotten --> equip["2. P2 targets Kitsu Shokka,<br/>the Undead Follower joins him"]
    f1 --> g1["3. P1 gains 2 Honor"]
    f2 --> g2["4. P1 gains 2 Honor"]
```

Every trait sees all three cards already gone, because none of them reacted until the whole
occurrence had happened. P1 decided that The Forgotten resolves first, but P2 chose its target,
since that choice belongs to The Forgotten's controller. After The Forgotten's branch, only Fields
of Slaughter's traits remain, all on one card, so nothing is left to order. The Honor each side
gains for the cards it destroyed is the next step of the battle's resolution, after the whole
subtree.

Under Magic's ordering rule (603.3b), P1 would put both Fields triggers on the stack and P2 would
put The Forgotten's on top, so The Forgotten's would resolve first because P2 is not the active
player. Had P1 wanted the Fields Honor first, Magic would not let P1 choose. Either player could
also respond between the triggers.

Ring of Earth reads "Play after a battle resolves at a Province if it was not destroyed, you were
not the Attacker, and any enemy units were ever at its battlefield." The tie left the Province
standing, and Moto Batu was at its battlefield, so P2 may play it once the battle resolves. A trait
on a card in a hand is never named in the active player's ordering question, because naming it
would show what P2 holds. When public traits wake at the same occurrence, the Ring's resolves after
them, and only P2 is asked about it. On Magic's stack every pending trigger is public.

## How the engine walks the tree

The engine never builds the tree. A depth-first walk needs only the path from the root to the node
it is on, together with what is still to do at each level of that path. The engine keeps that path
as a stack of frames, bottom first, and the walk always works on the top frame. Pushing a frame
descends into a child. Dropping a finished frame returns to the parent, which is whatever frame
sits beneath it. A frame resumes only once everything above it is gone, so the order the walk
visits nodes is the tree's depth-first order, and finished branches leave nothing behind.

There are two kinds of frame, and the walk alternates between them. The live walk in
`triggers._advance` holds mutable versions of both. A pause freezes them into
{class}`~.EffectsFrame` and {class}`~.EventsFrame`.

### Effects frames

An effects frame is the children of one node that are still to visit: an ordered list of effects,
with the {class}`~.Provenance` that says whose they are. The provenance decides what may reach the
effects. An Interrupt can modify only an action's own effects. A cost's payments are no effects,
so no negation reaches them. A trait's effects are marked so that its questions cannot be backed
out of.

The walk takes the first effect and applies it, and the effect commits at once. What the effect
produces then goes to the front of the same frame: its follow-on, such as the Province refill a
Recruit leaves behind, and the second half of a {class}`~.To` if the first half happened. The events
the effect raised become a new events frame pushed on top. So the follow-on waits beneath every
reaction to the effect, which gives the "enter, token, draw, refill" order of the Rural Market
example.

### Events frames

An events frame is one occurrence and the traits it woke. It holds the occurrence's events still to
announce, the triggered traits collected for them, the card the active player named to go next, and
the events of the occurrence that follows.

The walk announces every event in the occurrence before it fires anything, and collects every trait
those events trigger, the cards' and the rulebook's. When it collects several, it asks each once
whether it would do anything on the board the occurrence left, and drops those that would not.
Then it fires the traits one at a time. A fired trait's effects become a new effects frame on top,
so the trait and everything it sets off resolve before the next trait fires. Once two or more
traits outside a hand are left to fire, the walk stops and asks the active player with a
{class}`~.ChooseNextTrigger`, and keeps asking until every one of that occurrence's traits has
been activated. A trait whose card has left where it answers from, such as a card an earlier trait
destroyed, is dropped.

The last field, `following`, holds what the state-based rules demanded after the effect that
raised this occurrence. A Personality at zero Chi is destroyed as soon as the effect commits, but
the announcement of that destruction waits in `following`. It becomes the frame's next occurrence
once every trait of the first has resolved. That puts Moto Batu's death
after the reactions to his -1C, as the last child of that effect.

### The Rural Market example as frames

The tree from the Rural Market example is drawn again below, with each frame boxed. An effects
frame holds the steps of one action or trait, in order. An events frame holds one occurrence and
the traits it woke. Each frame hangs from the step in the frame above it that created it:

```{mermaid}
%%{init: {"flowchart": {"nodeSpacing": 16, "rankSpacing": 24, "subGraphTitleMargin": {"top": 4, "bottom": 8}}}}%%
flowchart TB
    subgraph F1["effects frame: the Recruit"]
        direction LR
        enter["1. Rural Market<br/>enters play"]
        refill["4. refill the Province"]
    end
    subgraph F2["events frame"]
        direction TB
        entered{{"Rural Market<br/>entered play"}} --> market(["Rural Market's trait"])
    end
    subgraph F3["effects frame: the trait"]
        token["2. a Wealth token"]
    end
    subgraph F4["events frame"]
        direction TB
        gained{{"Rural Market<br/>gained Wealth"}} --> aoki(["Aoki's trait"])
    end
    subgraph F5["effects frame: Aoki"]
        draw["3. draw a card"]
    end
    enter -- "raises" --> F2
    market -- "fires" --> F3
    token -- "raises" --> F4
    aoki -- "fires" --> F5
    classDef effects fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
    classDef events fill:#fef3c7,stroke:#b45309,color:#0f172a
    classDef step fill:#ffffff,stroke:#64748b,color:#0f172a
    class F1,F3,F5 effects
    class F2,F4 events
    class enter,refill,entered,market,token,gained,aoki,draw step
```

The walk works on one frame at a time, always the top of the stack, and the stack holds the frames
on the path from the Recruit's frame down to the step being worked on. Each column below is the
stack after one step, top of the stack at the top:

```{mermaid}
%%{init: {"flowchart": {"nodeSpacing": 12, "rankSpacing": 14, "padding": 6, "subGraphTitleMargin": {"top": 4, "bottom": 10}}}}%%
flowchart LR
    subgraph key["key"]
        direction TB
        k1["effects<br/>frame"]:::effects
        k2["events<br/>frame"]:::events
        k1 ~~~ k2
    end
    subgraph s1["A"]
        direction TB
        s1a["entered<br/>play"]:::events
        s1b["Recruit:<br/>refill"]:::effects
        s1a ~~~ s1b
    end
    subgraph s2["B"]
        direction TB
        s2a["trait:<br/>token"]:::effects
        s2b["entered<br/>play"]:::events
        s2c["Recruit:<br/>refill"]:::effects
        s2a ~~~ s2b ~~~ s2c
    end
    subgraph s3["C"]
        direction TB
        s3a["gained<br/>Wealth"]:::events
        s3b["trait:<br/>done"]:::effects
        s3c["entered<br/>play"]:::events
        s3d["Recruit:<br/>refill"]:::effects
        s3a ~~~ s3b ~~~ s3c ~~~ s3d
    end
    subgraph s4["D"]
        direction TB
        s4a["Aoki:<br/>draw"]:::effects
        s4b["gained<br/>Wealth"]:::events
        s4c["trait:<br/>done"]:::effects
        s4d["entered<br/>play"]:::events
        s4e["Recruit:<br/>refill"]:::effects
        s4a ~~~ s4b ~~~ s4c ~~~ s4d ~~~ s4e
    end
    subgraph s5["E"]
        direction TB
        s5a["Recruit:<br/>refill"]:::effects
    end
    key ~~~ s1
    s1 --> s2 --> s3 --> s4 --> s5
    classDef effects fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
    classDef events fill:#fef3c7,stroke:#b45309,color:#0f172a
```

Read the columns against the tree:

- A: The Recruit brings Rural Market into play. Its follow-on, the refill, goes back into the
  Recruit's frame, and an events frame for "entered play" goes on top of it.
- B: That occurrence fires Rural Market's trait, whose effects become a new effects frame on top.
- C: The token commits. The trait's frame has nothing left, and the "gained Wealth" occurrence goes
  on top of it.
- D: That occurrence fires Aoki's trait. The stack now holds all five frames, one per level of the
  tree, from the Recruit's at the bottom to Aoki's at the top.
- E: P1 draws. Every frame above the Recruit's is now finished and is dropped in turn, so the walk
  is back in the Recruit's frame, and the refill applies.

The refill stays at the bottom through every step, because a frame resumes only once the frames
above it are gone. That is the whole of how the stack implies the tree: a frame's parent is the
frame beneath it.

### Simultaneously

An effects frame applies its effects one after another, and each pushes its own events frame. A
{class}`~.Simultaneously` group is how an effect says that several things are one occurrence, as
battle resolution's destruction is ("The Attacker and Defender each destroy all units in the enemy
army").

When the walk reaches a group, it pushes an empty events frame, and above it an effects frame
marked simultaneous that holds the group's members. Each member is applied as it would be alone:
an Interrupt can modify it, a negation can stop it, and it can pause for a question. But a member
pushes no events frame of its own. Its events join the waiting frame beneath the group, and what
the state-based rules demand after it joins that frame's `following`. When the last member has
applied, the group's frame is dropped. The events frame beneath it then holds the whole
occurrence, and the walk announces it, collects its traits and lets the active player order them as
it would for any occurrence. A group inside a group adds its members to the same frame.

The columns below are the stack in the Fields of Slaughter example, top of the stack at the top,
from the moment battle resolution reaches its destruction:

```{mermaid}
%%{init: {"flowchart": {"nodeSpacing": 12, "rankSpacing": 14, "padding": 6, "subGraphTitleMargin": {"top": 4, "bottom": 10}}}}%%
flowchart LR
    subgraph key["key"]
        direction TB
        k1["effects<br/>frame"]:::effects
        subgraph kg["group's frame"]
            k2["member"]:::effects
        end
        k3["events<br/>frame"]:::events
        k1 ~~~ kg ~~~ k3
    end
    subgraph g1["A"]
        direction TB
        subgraph g1g["group"]
            direction TB
            g1a["destroy<br/>Shika"]:::effects
            g1b["destroy<br/>Batu"]:::effects
            g1a ~~~ g1b
        end
        g1c["gathering:<br/>nothing yet"]:::events
        g1d["resolution:<br/>Honor"]:::effects
        g1g ~~~ g1c ~~~ g1d
    end
    subgraph g2["B"]
        direction TB
        subgraph g2g["group"]
            g2a["destroy<br/>Batu"]:::effects
        end
        g2b["gathering: Shika,<br/>The Forgotten"]:::events
        g2c["resolution:<br/>Honor"]:::effects
        g2g ~~~ g2b ~~~ g2c
    end
    subgraph g3["C"]
        direction TB
        g3a["all three<br/>destroyed"]:::events
        g3b["resolution:<br/>Honor"]:::effects
        g3a ~~~ g3b
    end
    subgraph g4["D"]
        direction TB
        g4a["The Forgotten:<br/>lose Honor, Equip"]:::effects
        g4b["all three destroyed:<br/>Fields still to fire"]:::events
        g4c["resolution:<br/>Honor"]:::effects
        g4a ~~~ g4b ~~~ g4c
    end
    key ~~~ g1
    g1 --> g2 --> g3 --> g4
    classDef effects fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
    classDef events fill:#fef3c7,stroke:#b45309,color:#0f172a
    classDef plate fill:#e0e7ff,stroke:#4338ca,color:#0f172a
    class kg,g1g,g2g plate
```

- A: The walk reaches the group. It pushes an empty events frame to gather the occurrence, and the
  group's own frame above it. Battle resolution's Honor for destroyed cards waits beneath both.
- B: The first member destroys Ikoma Shika, and The Forgotten goes with him. Their destruction
  joins the gathering frame, and no events frame is pushed for it.
- C: The second member destroys Moto Batu. The group's frame is now empty and is dropped, and the
  events frame beneath holds all three destructions as one occurrence. The walk announces them,
  collects Fields of Slaughter's two traits and The Forgotten's, and asks P1 to order them.
- D: P1 names The Forgotten, whose trait becomes an effects frame on top. The Fields traits wait in
  the events frame beneath, and the Honor for destroyed cards waits beneath that until the whole
  occurrence has resolved.

A group holds back reactions only. The state-based rules still apply after each member commits, so
a Personality the first member leaves at zero Chi is destroyed before the second member applies,
and only the announcement of that destruction waits for the group.

### Before a card is destroyed

Some traits act before a destruction rather than after it. The Yu trait reads "Before a card with
the Yu trait is destroyed by another player's action during battle, or during resolution, resolve
the Yu effect" (ShE datasheet, The Yu Trait). In the tree, a Yu is a child that has to come before
its parent's destruction, so the walk announces the destruction first, as a
{class}`~.Destroying` events frame, and commits it afterward.

When a destruction comes up and some card answers it, the walk puts the effect back at the head of
its frame, records the card in that frame's `announced`, and pushes the announcement on top. The
traits it wakes resolve as one occurrence, ordered by the active player like any other, and the
destruction commits when it comes back up. A negation in force is read first, so a destruction it
will stop is never announced, as the datasheet requires: "the negation/substitution will always
occur first". A group announces all of its destructions together, above the group's frame, so every
trait sees the whole army still standing.

### Pausing

When a step needs a player's answer, the walk freezes every frame as a {class}`~.ResumeCascade`
and stops. The frames are the open path, and the open path is all that is left to do, so the answer
resumes the walk from the top. An answer to an effect's question splices that answer's effects into
the top effects frame. An answer to a {class}`~.ChooseNextTrigger` moves the named trait to the
front of the top events frame. Players never see this stack or add to it, which is the
difference between it and Magic's.
