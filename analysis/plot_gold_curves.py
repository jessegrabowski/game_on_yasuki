"""Plot a per-turn metric for each shipped decklist.

Reads the per-turn rows written by ``pixi run sim`` and renders, for every metric named below, two
figures: every deck on shared axes, and a small-multiple grid that keeps each deck's curve legible
against the rest.
"""

import sys
from pathlib import Path

import arviz as az
import matplotlib.pyplot as plt
import pandas as pd

ACCENT = "#2a78d6"
GHOST = "#c3c2b7"
INK = "#0b0b0b"
MUTED = "#898781"
GRID = "#e1e0d9"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]


HDI_PROB = 0.95

# The columns worth a figure, with the axis label and title each is plotted under.
METRICS = {
    "gold": ("mean unbowed gold production", "Gold production at the start of each turn"),
    "clearance": ("P(afford a fresh four-card flop)", "Chance of clearing the provinces"),
}


def load(runs: Path, column: str) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Mean ``column`` by (deck, turn), plus the highest-density interval of the per-game
    observations.

    Returns
    -------
    curves : pandas.DataFrame
        The mean, indexed by turn with one column per deck.
    bands : dict mapping str to pandas.DataFrame
        Per deck, a frame indexed by turn with ``lower`` and ``upper`` columns holding the
        :data:`HDI_PROB` interval across games and seats.
    """
    frames = [pd.read_csv(path) for path in sorted(runs.glob("*.csv"))]
    if not frames:
        raise SystemExit(f"no run files in {runs}")
    rows = pd.concat(frames, ignore_index=True)
    curves = rows.groupby(["deck", "turn"])[column].mean().unstack(0)

    bands = {}
    for deck, per_deck in rows.groupby("deck"):
        turns, lower, upper = [], [], []
        for turn, at_turn in per_deck.groupby("turn"):
            low, high = az.hdi(at_turn[column].to_numpy().astype(float), prob=HDI_PROB)
            turns.append(turn)
            lower.append(low)
            upper.append(high)
        bands[deck] = pd.DataFrame(
            {"lower": lower, "upper": upper}, index=pd.Index(turns, name="turn")
        )
    return curves, bands


def _style(ax):
    ax.set_facecolor("none")
    ax.grid(True, color=GRID, linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)


def overlay(curves: pd.DataFrame, out: Path, ylabel: str, title: str) -> None:
    """Every deck on shared axes, direct-labelled at the right edge."""
    finals = curves.iloc[-1].sort_values(ascending=False)
    order = finals.index
    # Direct labels collide where curves finish close together; push them apart in plot units,
    # keeping the leader order, and let the leader line show which curve each belongs to.
    span = curves.to_numpy().max() - curves.to_numpy().min()
    gap, placed = span * 0.045, []
    for value in finals:
        y = value if not placed else min(value, placed[-1] - gap)
        placed.append(y)

    fig, ax = plt.subplots(figsize=(10, 6.2), dpi=200)
    right = curves.index[-1]
    for rank, (deck, label_y) in enumerate(zip(order, placed, strict=True)):
        colour = SERIES[rank] if rank < len(SERIES) else GHOST
        ax.plot(curves.index, curves[deck], color=colour, linewidth=2, zorder=3)
        end_y = curves[deck].iloc[-1]
        if abs(label_y - end_y) > 1e-9:
            ax.plot(
                [right, right + 0.28],
                [end_y, label_y],
                color=colour,
                linewidth=0.8,
                zorder=3,
                clip_on=False,
            )
        ax.annotate(
            f"  {deck}",
            (right + 0.28, label_y),
            color=colour,
            fontsize=9,
            va="center",
            annotation_clip=False,
        )
    _style(ax)
    ax.set_xlim(curves.index.min(), curves.index.max())
    ax.set_ylim(0, None)
    ax.set_xlabel("turn", color=MUTED, fontsize=10)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=10)
    ax.set_title(f"{title}, by decklist", color=INK, fontsize=13, loc="left", pad=14)
    fig.subplots_adjust(right=0.78)
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print(f"wrote {out}")


def facets(
    curves: pd.DataFrame, bands: dict[str, pd.DataFrame], out: Path, ylabel: str, title: str
) -> None:
    """One panel per deck, each against the full set ghosted behind it, with its HDI shaded."""
    order = curves.iloc[-1].sort_values(ascending=False).index
    rows = (len(order) + 2) // 3
    fig, axes = plt.subplots(rows, 3, figsize=(10, 3.1 * rows), dpi=200, sharex=True, sharey=True)
    for ax, deck in zip(axes.flat, order, strict=False):
        for other in curves.columns:
            ax.plot(curves.index, curves[other], color=GHOST, linewidth=1, zorder=2)
        band = bands[deck]
        ax.fill_between(
            band.index,
            band["lower"],
            band["upper"],
            color=ACCENT,
            alpha=0.16,
            linewidth=0,
            zorder=2,
        )
        ax.plot(curves.index, curves[deck], color=ACCENT, linewidth=2.2, zorder=3)
        ax.set_title(deck, color=INK, fontsize=10, loc="left", pad=6)
        _style(ax)
    for ax in axes.flat[len(order) :]:
        ax.set_visible(False)
    fig.supxlabel("turn", color=MUTED, fontsize=10)
    fig.supylabel(ylabel, color=MUTED, fontsize=10)
    fig.suptitle(
        f"{title}, with {HDI_PROB:.0%} HDI across games",
        color=INK,
        fontsize=13,
        x=0.02,
        ha="left",
    )
    fig.tight_layout(rect=(0.02, 0.02, 1, 0.97))
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print(f"wrote {out}")


if __name__ == "__main__":
    runs = Path(sys.argv[1] if len(sys.argv) > 1 else ".scratch/mc")
    dest = Path(sys.argv[2] if len(sys.argv) > 2 else ".scratch")
    for column, (ylabel, title) in METRICS.items():
        data, intervals = load(runs, column)
        overlay(data, dest / f"{column}_by_deck.png", ylabel, title)
        facets(data, intervals, dest / f"{column}_by_deck_facets.png", ylabel, title)
