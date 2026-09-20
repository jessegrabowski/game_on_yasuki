# Adding a card

Read the card's text, find the shape, and go to the page for that shape. This page is the index and
the mechanics that apply to every card, not a tutorial.

If you have never written one, read [What a card is](what_a_card_is.md) and
[The card data](the_card_data.md) first, then come back here with a card in hand.

## Which hook?

| The card says | Hook | Example |
|---|---|---|
| Produces a variable amount of gold | `@gold_handler(id)` | {card}`Jade Works` |
| Costs less to bring into play, conditionally | `@recruit_discount(id)` | {card}`Colonial Farm` |
| "After X happens..." | `@on(Event, id)` | {card}`Rice Farm` |
| An activated ability with a cost | `register_ability(id, Ability(...))` | {card}`Millet Farm` |
| "Response: after X..." | `register_ability(id, Ability(timings=(ActionTiming.RESPONSE,), ...))` | {card}`Caravansary` |
| "X have +NF while Y" for the rest of the turn | effects returning `GrantConditionalModifier(...)` | {card}`Flashy Technique` |
| "cannot attack" | `register_cannot_attack(id)` | {card}`Daidoji Kaede` |
| "After this battle's resolution, if X, ..." | effects returning `DelayedEffect(Evaluate(...), END_OF_BATTLE)` | {card}`Daidoji Tashiko` |
| Gives a card an ability, as in "she has 'Battle: Ranged 3'" | `@granted_ability(id)` and effects returning `GrantAbility(...)` | {card}`Daidoji Kaede` |
| Buy an extra effect while recruiting | `register_invest(id, InvestAbility(...))` | {card}`Rebuilt Harbor` |
| "Interrupt: ..." against a pending effect | `register_interrupt(id, Interrupt(...))` | {card}`Okura is Released` |
| "Interrupt: ..." on a card in play | `register_interrupt(id, Interrupt(..., located_at=(CardLocation.BATTLEFIELD,)))` | {card}`Doji Yuten` |
| "Interrupt: Target your X. The action targets him instead" | `Interrupt(answers=ResolveAbility, targets=...)` replacing its `target_id` | {card}`Final Sacrifice` |
| "Interrupt: ... negate the action's effects" | `Interrupt(answers=Effect, answers_every=True)` returning `Negated` | none yet |
| "Interrupt: ..." on an Event in a Province | `register_interrupt(id, Interrupt(..., located_at=(CardLocation.PROVINCE,)))` | none yet |
| "Unstoppable Battle: ..." | `Ability(..., unstoppable=True)` | none yet |
| May Proclaim for an amount other than Personal Honor | `@proclaim_gain(id)` | {card}`Ninube Aitso, "Doji Yeiko" (Experienced)` |
| "You may Recruit this Holding as a Political Open action" | `register_recruit_timing(id, RecruitTiming(...))` | {card}`The Ivory Courtroom` |
| Gives another card's abilities Tireless | `@tireless_grant(id)` | {card}`Shrine to Inari` |
| Carries a keyword only sometimes | `@keyword_grant(id)` | {card}`Fortified Farmlands` |
| Gives a card a stat by its text while in play, itself or another | `@stat_grant(id)` | {card}`Haramaki-do`, {card}`Daidoji Tashiko` |
| Limits what it will attach to | `@attach_restriction(id)` | {card}`Brothers in Arms` |
| Buys its Invest cheaper, conditionally | `@invest_discount(id)` | {card}`Moto Ikarichi, Bloodseeker` |
| Changes the strength of an attack | `@attack_strength_against(id)` | {card}`Aseth's Legion` |
| Changes a Province's strength | `@province_strength_grant(id)` | {card}`Defensive Memorial` |
| Puts itself into play from hand, as an Edict, Kata or Ring | `register_entry(id, ...)` | {card}`Act With Authority` |
| An Event played from the Province it sits in | `register_event_entry(id)` | {card}`Shadow of the Dark God` |
| Raises its own Gold Production as it bows | `register_self_grant(id, n)`, or `@self_grant(id)` when the grant has a condition | {card}`Jade Mine`, {card}`Slave Pits` |
| Enters play in a state the rule does not give it ("Enters play unbowed", "enters play dishonorable") | `@entry_state(id)` | {card}`Poorly Placed Garden`, {card}`Matsu Gakuya` |
| "Before X enters play, ..." | `@before_entering_play(id)` | {card}`Matsu Gonshiro, Soul of Matsu Shimei` |
| "May remain bowed" | `register_may_remain_bowed(id)` | {card}`Culling Grounds` |
| Waives the bow cost of the Personality it hangs on | `register_bow_waiver(id)` | {card}`Shadowlands Ambassador` |
| Pays somebody's Imperial Favor cost | `@favor_payer(id)` | {card}`Manjodh` |
| "You have a +N Lobby Bonus" | `@lobby_bonus_grant(id)` | {card}`Shigekawa's Court` |
| Stops a player Lobbying at all | `@lobby_bar(id)` | {card}`Wasp Sensei` |
| "May not Lobby" | `register_may_not_lobby(id)` | {card}`Moto Chen` |

The `id` is the card's database id, the same string as in the set YAML. A pre-commit hook rejects an
id no card has and tells you the nearest real one.
[Registration and the audit](../design/systems/registration-and-the-audit.md) is why that hook
exists.

These are the events a trigger can answer: `EnteredPlay`, `Destroyed`, `Straightened`,
`Dishonored`, `Rehonored`, `CardDiscarded`, `CounterGained`, `Revealed`, `TurnStarted`,
`ProducingGold` and `ProducedGold`. A card whose moment is not one of them needs a new event,
which is a core change.

## Three cards, complete

The table names the hook. It does not show the hook's signature, the helpers a predicate calls, or
where any of them is imported from, and a handler written from the table alone gets those wrong.
Each card below is its whole implementation as it stands in its set module, preceded by that
module's import block, so every name in the block resolves to a line above it. Copy the shape that
matches your card, then read the page for it.

### A trigger

{card}`Rice Farm` reads *"After your turn begins, give this Holding a +1GP Wealth token."* One
event, one guard, one effect, in `src/yasuki_core/engine/rules/cards/chaos_reigns_part_ii.py`.
[Reacting to events](reacting_to_events.md) walks through it.

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/chaos_reigns_part_ii.py
:start-at: from yasuki_core
:end-before: "# ---"
:language: python
```

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/chaos_reigns_part_ii.py
:start-at: "# --- Rice Farm ---"
:end-before: "# --- Shosuro Aoki"
:language: python
```

### An ability

{card}`Dull Tanto` reads *"Open: Give a target Personality two -1F tokens. Destroy this Item."*
A target predicate, an effects helper, and a registration, in
`src/yasuki_core/engine/rules/cards/road_to_ruin.py`. [Writing an ability](an_ability.md) walks
through it. Note what the predicate calls: `personalities_in_play`, from
`src/yasuki_core/engine/rules/board/queries.py`, which is where the other questions a predicate
asks of the board live.

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/road_to_ruin.py
:start-at: from yasuki_core
:end-before: "# ---"
:language: python
```

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/road_to_ruin.py
:start-at: "# --- Dull Tanto ---"
:end-before: "# --- Outlying Farms"
:language: python
```

### A trigger and a keyword grant on one card

{card}`Chuda Jomei` reads *"After Jomei enters play, lose 3 Honor. Open: Give a target Human
Personality :shadowlands:."* Two sentences, two hooks, one block, in
`src/yasuki_core/engine/rules/cards/chaos_reigns_part_iii.py`. The trigger guards on
`ctx.event.card_id`, because every copy in play hears the event. The predicate reads *Human* as the
absence of the Nonhuman keyword, which is how the rules define the word (CR, Human), and the
effect is `GrantKeyword` with the duration the rules give an unqualified "give"
([Writing an ability](an_ability.md) says which). Every effect a handler may return is a
dataclass in `src/yasuki_core/engine/rules/effects.py`, and every keyword the engine reads is a
constant in `src/yasuki_core/engine/rules/vocabulary/keywords.py`. Open those two files before
writing a name that is not in a block on this page.

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/chaos_reigns_part_iii.py
:start-at: from yasuki_core
:end-before: "# ---"
:language: python
```

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/chaos_reigns_part_iii.py
:start-at: "# --- Chuda Jomei ---"
:end-before: "# --- Doji Maya"
:language: python
```

## Which page?

Work down this list. Each rung costs more than the one above, so stop at the first that can say
what the card does.

1. **A number.** The card produces gold, or costs less, or has a stat it did not print. Answer with
   a number and write no effects at all. [Holdings and gold](holdings_and_gold.md) and
   [Stats and costs](stats_and_costs.md).
2. **A reaction.** "After X happens, do Y." Return a list of effects from a trigger.
   [Reacting to an event](reacting_to_events.md).
3. **An ability.** The card does something on purpose, for a cost.
   [Writing an ability](an_ability.md), then
   [A card that prints two abilities](several_abilities.md) when it prints more than one.
4. **A question.** The card says "choose" or "may", so a seat has to answer before it can finish.
   [Asking the player a question](asking_a_question.md).

Then by what the card is:

- Hangs on a Personality: [Cards that attach](attachments.md)
- Fights, or changes a fight: [Cards that act in a battle](battle_cards.md)
- Makes a card: [Cards that create cards](creating_cards.md)
- Acts from hand or a Province, or stays in play:
  [Cards that act from outside play](cards_outside_play.md)
- Touches the Imperial Favor or Lobby: [The Favor and the court](the_favor_and_the_court.md)

## Where the code goes

A reprinted card is implemented once, in the set that printed it first, and
`test_every_card_is_implemented_in_its_first_printing_module` enforces that. Find that set, open
the module of the same name as its YAML file, and add the card in id order under a header:

```python
# --- Rice Farm ---
```

The module is an address, not a claim about the text. A card's text can be rewritten between arcs
under one id (Ring of Air is one id across two dozen printings), and the ruleset the engine plays
under decides which text it models. The first printing still decides the module because it is the
one location the hooks can compute from an id alone.

Everything the card does goes in that one block: its triggers, its target predicates, its effects
helper, its registration. A pre-commit hook asserts the ordering, the one-header-per-card rule, and
that the header names the card the block registers, on the modules your commit touches.

Name every function in the block for the card and the job it does, as `_<card id>_<role>`, where the
role is one of `cost`, `targets`, `effects`, `interrupt`, an entry point of a registry (`gold`, `invest`,
`keywords`, `recruit_discount`, `invest_discount`, `stat_grant`, `attach_restriction`,
`attack_strength`, `province_strength`, `lobby_bonus`, `lobby_bar`, `favor_payer`, `entry_state`,
`before_entering_play`), or the event a
trigger answers (`entered_play`, `destroyed`, `straightened`, `dishonored`, `rehonored`,
`turn_started`, `counter_gained`, `card_discarded`, `producing_gold`, `produced_gold`,
`entered_play_or_destroyed`). A card printing
several abilities qualifies the role with that ability's key, as in
`_incendiary_archers_fear_effects`, since one name per role would collide between them, and the key
has to be one the module really registers. A choice resolver is named for the choice instead,
`_resolve_<the string it is registered under>`. Helpers the block calls but never registers only
need the card's id in front.

The point is grep. A card's whole implementation answers a search for its id, and every handler of a
kind answers a search for its role. A test enforces it, and `ROLES` in `hooks/card_layout.py` is
where a genuinely new role gets added.

A brand new set module needs a line in `cards/__init__.py`. A test will tell you if you forget.

## Checking your work

```bash
pixi run test          # the suite
pre-commit run --all   # includes the card-id check
```

Write the test with the card. The suite is how a mass refactor knows it did not drop your
registration. Every implemented card is covered, and that is not an accident.

The bots are separate. A new ability is invisible to them until someone writes a hint for it, and
[Bots and policies](../design/systems/bots-and-policies.md) covers why that is the safe default.
