class Allocation:
    """How a fixed number of identical creations is divided among the cards chosen to carry them.

    The total never changes: every creation is placed, so the only question is where. Choosing a
    card splits the total evenly across everything chosen, and the per-card arrows move one creation
    between neighbours rather than adding or removing any. A chosen card therefore always holds at
    least one — taking its last away is deselecting it, which the arrows will not do.

    Parameters
    ----------
    total : int
        How many creations there are to divide.
    """

    def __init__(self, total: int):
        self.total = total
        self._chosen: list[str] = []
        self._amounts: dict[str, int] = {}

    @property
    def chosen(self) -> tuple[str, ...]:
        """The cards carrying something, in the order they were picked."""
        return tuple(self._chosen)

    @property
    def choices(self) -> tuple[str, ...]:
        """The division as the engine reads it: each card named once per creation it takes."""
        return tuple(card_id for card_id in self._chosen for _ in range(self._amounts[card_id]))

    def amount(self, card_id: str) -> int:
        """How many ``card_id`` carries, zero when it was not chosen."""
        return self._amounts.get(card_id, 0)

    def toggle(self, card_id: str) -> None:
        """Choose ``card_id`` or drop it, then split the total evenly over what is left chosen.

        Choosing is refused once there is one creation per chosen card, since a further card could
        only be given nothing.
        """
        if card_id in self._amounts:
            self._chosen.remove(card_id)
        elif len(self._chosen) < self.total:
            self._chosen.append(card_id)
        else:
            return
        self._split_evenly()

    def may_increase(self, card_id: str) -> bool:
        """Whether ``card_id`` can take one more — some other chosen card has one to spare."""
        return self._donor(card_id) is not None

    def may_decrease(self, card_id: str) -> bool:
        """Whether ``card_id`` can give one up: it has one to spare and somewhere to send it."""
        return self._amounts.get(card_id, 0) > 1 and len(self._chosen) > 1

    def increase(self, card_id: str) -> None:
        """Move one creation to ``card_id`` from whichever chosen card carries the most."""
        donor = self._donor(card_id)
        if donor is None:
            return
        self._amounts[donor] -= 1
        self._amounts[card_id] += 1

    def decrease(self, card_id: str) -> None:
        """Move one creation from ``card_id`` to whichever chosen card carries the fewest."""
        if not self.may_decrease(card_id):
            return
        receiver = min(
            (other for other in self._chosen if other != card_id),
            key=lambda other: (self._amounts[other], self._chosen.index(other)),
        )
        self._amounts[card_id] -= 1
        self._amounts[receiver] += 1

    def _donor(self, card_id: str) -> str | None:
        """The chosen card an increase takes from: the fullest of the others, latest picked first so
        the extras an uneven split handed out are the first to move back."""
        if card_id not in self._amounts:
            return None
        others = [other for other in self._chosen if other != card_id and self._amounts[other] > 1]
        if not others:
            return None
        return max(others, key=lambda other: (self._amounts[other], self._chosen.index(other)))

    def _split_evenly(self) -> None:
        """Divide the total over the chosen cards, the earliest picked taking the remainder."""
        chosen = len(self._chosen)
        if not chosen:
            self._amounts = {}
            return
        each, extra = divmod(self.total, chosen)
        self._amounts = {
            card_id: each + (1 if index < extra else 0)
            for index, card_id in enumerate(self._chosen)
        }
