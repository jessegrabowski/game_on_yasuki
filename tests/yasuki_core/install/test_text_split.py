import pytest

from yasuki_core.install.text_split import ability_keywords, split_text_box, strip_markup


def traits(text):
    return list(split_text_box(text).traits)


def abilities(text):
    return [(a.keywords, a.designators, a.cost, a.text) for a in split_text_box(text).abilities]


def test_an_ability_is_found_by_its_designator_not_its_markup():
    """The markup is being removed from the corpus, so the split cannot depend on it. Same card,
    with and without the tags, has to decompose the same way."""
    marked = "<b>Political Open:</b> Target two Personalities controlled by the same player."
    bare = "Political Open: Target two Personalities controlled by the same player."

    assert abilities(marked) == abilities(bare)
    assert abilities(bare) == [
        (("Political",), ("Open",), None, "Target two Personalities controlled by the same player.")
    ]


def test_a_cost_with_no_designator_is_still_an_ability():
    # The production template of every pre-Onyx Holding: a bow and a colon, no designator word.
    assert abilities("<b>:bow::</b> Produce 2 Gold.") == [((), (), ":bow:", "Produce 2 Gold.")]


def test_an_ability_may_carry_two_designators():
    ability = split_text_box("Battle/Open: Gain 1 Honor.").abilities[0]

    assert ability.designators == ("Battle", "Open")


def test_a_named_trait_opens_a_new_trait():
    text = "Invest :g1:: Search your deck for a Strategy.<br>Yu: Permanently give Tactician."

    assert traits(text) == [
        "Invest :g1:: Search your deck for a Strategy.",
        "Yu: Permanently give Tactician.",
    ]


def test_a_named_trait_word_mid_sentence_is_prose():
    """ "…have Discipline :g2:." names a trait rather than opening one, so it must not split."""
    text = "Dark Virtues in your discard pile have Discipline :g2:. Your fear may target Followers."

    assert traits(text) == [
        "Dark Virtues in your discard pile have Discipline :g2:.",
        "Your fear may target Followers.",
    ]


def test_separate_sentences_are_separate_traits():
    text = "Daisuke cannot defend or attach Followers. Other Deathseekers have +1F while opposed."

    assert traits(text) == [
        "Daisuke cannot defend or attach Followers.",
        "Other Deathseekers have +1F while opposed.",
    ]


@pytest.mark.parametrize(
    "tail",
    [
        "Show it and put it in your hand.",
        "They have +2F while they have both.",
        "Then, destroy the chosen units.",
        # An imperative acting on a pronoun is as dependent as a pronoun subject: the object of
        # "Discard it" is the Ring the sentence before it went looking for.
        "Discard it at the end of the turn if it is not in play.",
        "Bow them as they move.",
    ],
)
def test_a_sentence_that_cannot_stand_alone_continues_the_one_before_it(tail):
    """Its subject has no antecedent of its own, so it is not a separate unit of behavior."""
    assert traits(f"Search your deck for a Ring. {tail}") == [
        f"Search your deck for a Ring. {tail}"
    ]


def test_a_designator_word_inside_a_sentence_does_not_open_an_ability():
    """ "…if your Wind is The Kanpeki Dynasty:" names a card and the colon is the sentence's own.
    Reading it as a prefix invents an ability and truncates the trait that contains it."""
    text = "Invest :g2:, or :g0: if your Wind is The Kanpeki Dynasty: Attach a Follower.<br><b>Battle:</b> :melee: 4."

    assert traits(text) == [
        "Invest :g2:, or :g0: if your Wind is The Kanpeki Dynasty: Attach a Follower."
    ]
    assert abilities(text) == [((), ("Battle",), None, ":melee: 4.")]


def test_a_break_is_a_boundary_an_ability_can_open_at():
    # The prefix is not bolded here and does not follow a period; the <br> is the only boundary.
    text = "Discipline :g2:<br>Iaijutsu Repeatable Battle: Challenge a target enemy Personality."

    assert abilities(text) == [
        (("Iaijutsu",), ("Battle",), None, "Challenge a target enemy Personality.")
    ]


def test_a_prefix_separates_what_classifies_the_ability_from_what_modifies_it():
    """Only the classification rises to the card, so the two cannot share a field."""
    ability = split_text_box("Political Home Open/Engage: Take :favor:.").abilities[0]

    assert ability.keywords == ("Political",)
    assert ability.modifiers == ("Home",)
    assert ability.designators == ("Open", "Engage")


def test_a_two_word_keyword_is_one_keyword():
    """ "Virtue" never opens a prefix alone, so splitting on spaces would invent keywords."""
    ability = split_text_box("Dark Virtue Open, :g3:: Target your Personality.").abilities[0]

    assert ability.keywords == ("Dark Virtue",)


def test_a_card_inherits_the_keywords_of_its_abilities():
    """The CR reads a Strategy with a Political ability as a Political Strategy. Inheritance runs
    upward only, and a modifier is not inherited at all."""
    text = (
        "<b>Economic Battle, :gstar::</b> Move home a target Personality.<br>"
        "<b>Political Tireless Open:</b> Take :favor:."
    )

    assert ability_keywords(text) == ("Economic", "Political")


def test_a_card_with_no_abilities_inherits_nothing():
    assert ability_keywords("Daisuke cannot defend or attach Followers.") == ()


def test_a_classifier_may_govern_an_ability():
    """ "Honesty: Interrupt, :X:: …" is an ability that applies while you have Honesty, not a trait
    that happens to contain one."""
    text = "Honesty: <b>Interrupt, :X::</b> Equip it to your target Personality."

    assert abilities(text) == [((), ("Interrupt",), ":X:", "Equip it to your target Personality.")]


def test_an_ability_inside_leading_reminder_text_is_not_an_ability():
    """The parenthetical restates the Honor keyword, so the card does not own the ability in it —
    the same reason the reminder is not one of the card's traits."""
    text = (
        "<i>(<b>Repeatable Interrupt:</b> Once per action, discard an Honor card to increase or "
        "reduce an Honor gain or loss by 1.)</i><br><b>Battle:</b> Give -2F."
    )

    assert abilities(text) == [((), ("Battle",), None, "Give -2F.")]
    assert traits(text) == []


def test_an_unrecognized_leading_parenthetical_is_kept():
    """Only a known rulebook wording is taken out. Anything else is the card's own text, and
    dropping it would lose rules that nothing else records."""
    text = "(Nothing happens to the loser.)<br><b>Battle:</b> Give -2F."
    box = split_text_box(text)

    assert box.traits == ("(Nothing happens to the loser.)",)
    assert box.reminders == ()


def test_a_focus_effect_under_a_classifier_stays_one_trait():
    text = "Honesty: As a Focus Effect, give this Personality +1C."

    assert traits(text) == [text]


def test_a_granted_ability_stays_inside_the_text_that_grants_it():
    """Quoted text is an ability handed to another card; splitting it out would credit this card
    with an ability it does not have."""
    text = 'Other players\' Personalities have "Yu: The enemy leader may create a Strategy."'

    assert traits(text) == [text]
    assert abilities(text) == []


def test_leading_reminder_text_is_dropped():
    text = "(Draw a card after your Expendable card dies.)<br>Invest :g2:: Dishonor a target."

    assert traits(text) == ["Invest :g2:: Dishonor a target."]


def test_reminder_text_is_separated_wherever_it_sits():
    """It restates a rule the card does not own, so it is not one of the card's traits — but it is
    printed, so it is kept rather than thrown away."""
    text = (
        "(Draw a card after your Expendable card dies.)<br>Invest :g2:: Dishonor a target. "
        "(After this card enters play, you may also pay the Invest cost to get the effect, once.)"
    )
    box = split_text_box(text)

    assert box.traits == ("Invest :g2:: Dishonor a target.",)
    assert box.reminders == (
        "(Draw a card after your Expendable card dies.)",
        "(After this card enters play, you may also pay the Invest cost to get the effect, once.)",
    )


@pytest.mark.parametrize(
    "printed",
    [
        # The corpus already prints this rule two ways, so wording is matched by resemblance.
        "(Draw a card after your Expendable card is destroyed.)",
        "(Draw a card after your Expendable card dies.)",
        # Drift of the kind the designers produce: casing, an article, a hyphen.
        "(When a card with Renew enters play from a province, refill that Province face up.)",
    ],
)
def test_a_reminder_is_recognized_through_the_wording_it_is_printed_with(printed):
    assert split_text_box(f"Akira has Renew. {printed}").reminders == (printed,)


def test_a_reminder_is_recognized_with_its_period_outside_the_parentheses():
    """Some cards close the sentence after the bracket rather than inside it, so the wording has to
    carry the recognition on its own."""
    text = "Give your target Spirit Expendable <i>(Draw a card after your Expendable card is destroyed)</i>."

    assert split_text_box(text).reminders == (
        "(Draw a card after your Expendable card is destroyed)",
    )


def test_a_bracket_holds_one_reminder_per_keyword_the_card_carries():
    """A Loyal Naval Shugenja prints all three rules in one bracket, so the reminders are matched a
    sentence at a time — keying on the whole bracket would need an entry per combination."""
    text = (
        "Kageharu has +1F. <i>(Loyal Personalities will not join other Clans. Once a turn, the "
        "Attacker gets the first Battle action, if it's from a Naval Personality's unit. Shugenja "
        "may attach and cast Spells.)</i>"
    )
    box = split_text_box(text)

    assert box.traits == ("Kageharu has +1F.",)
    assert box.reminders == (
        "(Loyal Personalities will not join other Clans. Once a turn, the Attacker gets the first "
        "Battle action, if it's from a Naval Personality's unit. Shugenja may attach and cast "
        "Spells.)",
    )


def test_a_bracket_mixing_a_reminder_with_the_cards_own_words_is_kept():
    """Dropping it would take the card's own rule with it, so all of it stays."""
    text = "Bow a target. (Shugenja may attach and cast Spells. Nothing happens to the loser.)"
    box = split_text_box(text)

    assert box.reminders == ()
    assert " ".join(box.traits) == text


def test_a_card_keeps_a_parenthetical_the_rulebook_does_not_own():
    """Shaped exactly like reminder text, but it clarifies this card's own effect, so matching the
    wording rather than the shape is what keeps it."""
    box = split_text_box(
        "Your target Personality challenges another. (Nothing happens to the loser.)"
    )

    assert box.reminders == ()
    assert box.traits == (
        "Your target Personality challenges another. (Nothing happens to the loser.)",
    )


@pytest.mark.parametrize(
    ("printed", "separated"),
    [
        # Named for the card, so no fixed wording can list it.
        ("(Bayushi Nomen is not Unique.)", True),
        ("(Tsukimi is not Unique)", True),
        # Numbered for the cost, likewise.
        ("(Pay 0 Gold to play, then remove from the game, this Discipline in your discard.)", True),
        ("(Pay 2 Gold to play, then remove from the game, this Discipline in your discard.)", True),
        # Shaped alike and says something else: the pattern must not reach it.
        ("(Kaagi is not a Duelist.)", False),
        ("(Pay 2 Gold to draw a card.)", False),
    ],
)
def test_a_reminder_naming_a_card_or_a_cost_is_matched_by_pattern(printed, separated):
    """These vary per card, so they are recognized by shape rather than by a listed wording — which
    means the shape has to be tight enough to leave a card's own words alone."""
    box = split_text_box(f"Bow a target. {printed}")

    assert box.reminders == ((printed,) if separated else ())


def test_a_qualifier_in_parentheses_is_not_reminder_text():
    """Reminder text is a whole sentence; a qualifier is a fragment, and the card owns it."""
    box = split_text_box("Destroy a Terrain (if able). Put this Terrain into play.")

    assert box.reminders == ()
    assert box.traits[0] == "Destroy a Terrain (if able)."


def test_a_parenthetical_holding_two_sentences_stays_one_chunk():
    """Cutting between them would leave one half opening a bracket it never closes and the other
    closing one it never opened."""
    text = "Bow a target. (The Military District may now be destroyed. All players lose 1 Honor.)"

    assert traits(text) == [text]


def test_a_break_inside_a_parenthetical_does_not_start_a_line():
    """The aside runs across two printed lines; the break is typesetting, not a boundary."""
    text = "Bow a target.<br>(The Districts may now be destroyed.<br>The Naga player draws a card.)"

    assert traits(text) == [
        "Bow a target.",
        "(The Districts may now be destroyed. The Naga player draws a card.)",
    ]


def test_a_clause_closing_paren_does_not_end_a_sentence():
    text = "Refill this Province with your target discarded (not dead) Personality."

    assert traits(text) == [text]


def test_markup_leaves_no_space_before_punctuation():
    # "<b>Tireless</b>." must not read "Tireless .", and an icon keeps the space in front of it.
    assert strip_markup("Saiko's ability is <b>Tireless</b>.") == "Saiko's ability is Tireless."
    assert strip_markup("Search for a <i>:pearl:</i> Spell.") == "Search for a :pearl: Spell."


def test_a_designator_keeps_its_colon_when_the_tag_closes_before_it():
    """A colon outside the tag is the designator's own, so it must not drift away from it. The
    colon that opens an icon is the one that keeps its space."""
    granted = 'have "<b>Repeatable Battle</b>: Bow a target."'

    assert strip_markup(granted) == 'have "Repeatable Battle: Bow a target."'
    assert strip_markup("<b>Battle, :bow::</b> <i>:melee:</i> 2.") == "Battle, :bow:: :melee: 2."


def test_a_strike_is_the_ability_text_not_its_cost():
    """``Battle, :bow:: :melee: 2`` bows to strike, so the bow is the cost and the strike is what
    the ability does."""
    assert abilities("Battle, :bow:: :melee: 2.") == [((), ("Battle",), ":bow:", ":melee: 2.")]


def test_an_opening_quote_hugs_its_text_and_a_closing_one_does_not():
    assert strip_markup('have "<b>Battle:</b> Bow" and more') == 'have "Battle: Bow" and more'
