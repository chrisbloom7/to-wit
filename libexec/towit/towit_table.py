#!/usr/bin/env python3
"""
towit_table — Shared helpers for the text tables printed by `towit search` and `towit list`.

Not a subcommand. `fit_widths` decides column widths so a table fits the terminal; `truncate`
shortens one cell. Widths are measured in characters (len), not terminal display cells.
"""


def truncate(s, width):
    """Shorten s to at most width characters, ending in an ellipsis when it was cut."""
    if len(s) <= width:
        return s
    return s[:width - 1] + '…'


def _shrink(widths, floors, overflow):
    """Reduce shrinkable columns by exactly `overflow` in total, in proportion to their slack.

    Returns the new widths, or None when the total slack is smaller than the overflow. Rounding
    uses largest remainders, so the reduction is exact and no column goes below its floor.
    """
    slack = [0 if f is None else max(0, w - f) for w, f in zip(widths, floors)]
    total_slack = sum(slack)
    if overflow > total_slack:
        return None
    if overflow <= 0 or total_slack == 0:
        return list(widths)
    base = [overflow * s // total_slack for s in slack]
    remainder = [overflow * s % total_slack for s in slack]
    extra = overflow - sum(base)
    for i in sorted(range(len(slack)), key=lambda i: (-remainder[i], i))[:extra]:
        base[i] += 1
    return [w - r for w, r in zip(widths, base)]


def fit_widths(widths, floors, target, sep_width, indent_width, droppable=None, *, omit_droppable=False):
    """Fit column widths into `target` characters.

    widths: natural width of each column. floors: per column, the minimum width it may shrink to,
    or None for a column that must never shrink (such as the ID). A column whose natural width is
    already below its floor never grows. target: maximum line width. sep_width: gap between
    columns. indent_width: fixed left indent. droppable: index of a column to remove entirely
    when shrinking alone cannot fit the table (the least valuable one), or None.
    omit_droppable: remove that column before fitting, for example when all its cells are empty.

    Returns (widths, kept): the new widths (same length as the input; a dropped column keeps its
    natural width but is not in kept) and the indexes of the columns to print, in order. When
    nothing fits, the floors are returned and the terminal wraps; this never raises for that.
    Raises ValueError for inconsistent input.
    """
    if len(widths) != len(floors):
        raise ValueError('widths and floors must have the same length')
    if droppable is not None and not 0 <= droppable < len(widths):
        raise ValueError('droppable is out of range')
    widths = list(widths)
    kept = list(range(len(widths)))
    if omit_droppable and droppable is not None:
        kept.remove(droppable)
        droppable = None
    if not kept:
        return widths, kept

    def overhead(columns):
        return sep_width * (len(columns) - 1) + indent_width

    def overflow_of(columns):
        return sum(widths[i] for i in columns) + overhead(columns) - target

    if overflow_of(kept) <= 0:
        return widths, kept

    def attempt(columns):
        sub = _shrink([widths[i] for i in columns], [floors[i] for i in columns], overflow_of(columns))
        if sub is None:
            return None
        out = list(widths)
        for i, w in zip(columns, sub):
            out[i] = w
        return out

    fitted = attempt(kept)
    if fitted is not None:
        return fitted, kept

    if droppable is not None:
        kept.remove(droppable)
        fitted = attempt(kept)
        if fitted is not None:
            return fitted, kept

    # Does not fit even at the floors: return the floors and let the terminal wrap.
    out = list(widths)
    for i in kept:
        if floors[i] is not None:
            out[i] = min(widths[i], floors[i])
    return out, kept
