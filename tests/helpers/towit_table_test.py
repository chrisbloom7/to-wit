"""Tests for towit_table: width fitting and truncation for the text tables."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit')))
from towit_table import display_width, fit_widths, pad, truncate

# Search-like layout: ID, Title, Keywords, Msg, Snippet, Date. Only Title, Keywords and Snippet shrink.
FLOORS = [None, 8, 8, None, 8, None]
KEYWORDS = 2
SEP = 2


def fit(widths, target, floors=FLOORS, indent=0, droppable=KEYWORDS):
    return fit_widths(widths, floors, target, sep_width=SEP, indent_width=indent, droppable=droppable)


def total(widths, kept, indent=0):
    return sum(widths[i] for i in kept) + SEP * (len(kept) - 1) + indent


class TestTruncate(unittest.TestCase):
    def test_short_string_unchanged(self):
        self.assertEqual(truncate('abc', 3), 'abc')

    def test_long_string_gets_ellipsis_within_width(self):
        self.assertEqual(truncate('abcdef', 4), 'abc…')

    def test_empty_string(self):
        self.assertEqual(truncate('', 5), '')


class TestDisplayWidth(unittest.TestCase):
    def test_ascii_is_one_cell_per_character(self):
        self.assertEqual(display_width('abc'), 3)

    def test_cjk_is_two_cells_per_character(self):
        self.assertEqual(display_width('中文'), 4)

    def test_wide_emoji_is_two_cells(self):
        self.assertEqual(display_width('🚀'), 2)

    def test_mixed_text(self):
        self.assertEqual(display_width('API 接口 🚀'), 11)

    def test_combining_mark_takes_no_cell(self):
        self.assertEqual(display_width('e\u0301'), 1)

    def test_empty_string(self):
        self.assertEqual(display_width(''), 0)


class TestTruncateWide(unittest.TestCase):
    def test_cjk_that_fits_is_unchanged(self):
        self.assertEqual(truncate('中文', 4), '中文')

    def test_cjk_is_cut_by_display_width(self):
        self.assertEqual(truncate('中文标题', 5), '中文…')

    def test_wide_character_that_would_straddle_the_edge_is_dropped(self):
        out = truncate('中文标题', 6)
        self.assertEqual(out, '中文…')
        self.assertLessEqual(display_width(out), 6)

    def test_mixed_text_never_exceeds_width(self):
        for width in range(1, 12):
            self.assertLessEqual(display_width(truncate('ab中文🚀cd标题', width)), width, width)

    def test_emoji_is_cut_by_display_width(self):
        self.assertEqual(truncate('🚀🚀🚀', 4), '🚀…')


class TestPad(unittest.TestCase):
    def test_ascii_padded_like_ljust(self):
        self.assertEqual(pad('ab', 5), 'ab   ')

    def test_cjk_padded_to_display_width(self):
        self.assertEqual(pad('中文', 6), '中文  ')
        self.assertEqual(display_width(pad('中文', 6)), 6)

    def test_never_shortens(self):
        self.assertEqual(pad('中文', 3), '中文')


class TestFitWidthsZero(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(fit_widths([], [], 80, sep_width=2, indent_width=0), ([], []))

    def test_already_fits_changes_nothing(self):
        widths = [36, 20, 10, 3, 20, 10]
        out, kept = fit(widths, 200)
        self.assertEqual(out, widths)
        self.assertEqual(kept, [0, 1, 2, 3, 4, 5])

    def test_no_shrinkable_columns_returns_widths_and_never_raises(self):
        out, kept = fit_widths([36, 10], [None, None], 20, sep_width=2, indent_width=0)
        self.assertEqual(out, [36, 10])
        self.assertEqual(kept, [0, 1])

    def test_input_is_not_mutated(self):
        widths = [36, 40, 30, 3, 40, 10]
        fit(widths, 100)
        self.assertEqual(widths, [36, 40, 30, 3, 40, 10])


class TestFitWidthsOne(unittest.TestCase):
    def test_single_shrinkable_column_loses_exactly_the_overflow(self):
        widths = [36, 40, 3, 10]
        floors = [None, 8, None, None]
        out, kept = fit_widths(widths, floors, 80, sep_width=2, indent_width=0)
        self.assertEqual(sum(out) + 2 * 3, 80)
        self.assertEqual(out[0], 36)
        self.assertEqual(out[2:], [3, 10])
        self.assertEqual(kept, [0, 1, 2, 3])


class TestFitWidthsMany(unittest.TestCase):
    def test_total_equals_target_and_none_below_floor(self):
        widths = [36, 50, 30, 3, 60, 10]
        out, kept = fit(widths, 116, indent=2)
        self.assertEqual(kept, [0, 1, 2, 3, 4, 5])
        self.assertEqual(total(out, kept, 2), 116)
        for i, floor in enumerate(FLOORS):
            if floor is not None:
                self.assertGreaterEqual(out[i], floor)

    def test_reductions_follow_slack(self):
        # slack: Title 42, Keywords 0 (already at floor), Snippet 12
        widths = [36, 50, 8, 3, 20, 10]
        out, _ = fit(widths, total(widths, range(6)) - 18)
        self.assertEqual(out[2], 8)  # a column at its floor gives up nothing
        self.assertEqual(widths[1] - out[1] + widths[4] - out[4], 18)
        self.assertGreater(widths[1] - out[1], widths[4] - out[4])

    def test_fixed_columns_never_change(self):
        widths = [36, 50, 30, 3, 60, 10]
        out, _ = fit(widths, 100)
        self.assertEqual([out[0], out[3], out[5]], [36, 3, 10])

    def test_largest_remainder_rounding_loses_nothing(self):
        # overflow 7 over three equal-slack columns: reductions 3, 2, 2
        widths = [10, 20, 20, 20]
        floors = [None, 8, 8, 8]
        natural = sum(widths) + 2 * 3
        out, kept = fit_widths(widths, floors, natural - 7, sep_width=2, indent_width=0)
        self.assertEqual(total(out, kept), natural - 7)
        self.assertEqual(sorted(widths[i] - out[i] for i in (1, 2, 3)), [2, 2, 3])


class TestFitWidthsBoundaries(unittest.TestCase):
    WIDTHS = [36, 30, 20, 3, 40, 10]

    def test_exactly_fits(self):
        natural = total(self.WIDTHS, range(6))
        out, kept = fit(self.WIDTHS, natural)
        self.assertEqual(out, self.WIDTHS)

    def test_one_over_reduces_by_one(self):
        natural = total(self.WIDTHS, range(6))
        out, kept = fit(self.WIDTHS, natural - 1)
        self.assertEqual(sum(self.WIDTHS) - sum(out), 1)
        self.assertEqual(kept, [0, 1, 2, 3, 4, 5])

    def test_overflow_equal_to_all_slack_goes_to_floors_and_keeps_keywords(self):
        natural = total(self.WIDTHS, range(6))
        slack = (30 - 8) + (20 - 8) + (40 - 8)
        out, kept = fit(self.WIDTHS, natural - slack)
        self.assertEqual(out[1], 8)
        self.assertEqual(out[2], 8)
        self.assertEqual(out[4], 8)
        self.assertEqual(kept, [0, 1, 2, 3, 4, 5])

    def test_overflow_beyond_slack_drops_keywords_then_shrinks(self):
        natural = total(self.WIDTHS, range(6))
        slack = (30 - 8) + (20 - 8) + (40 - 8)
        target = natural - slack - 5  # not reachable with Keywords at its floor
        out, kept = fit(self.WIDTHS, target)
        self.assertEqual(kept, [0, 1, 3, 4, 5])
        self.assertLessEqual(total(out, kept), target)
        self.assertEqual(total(out, kept), target)

    def test_omitting_empty_keywords_leaves_full_width_for_other_columns(self):
        widths = [36, 30, 8, 3, 40, 10]
        kept_columns = [0, 1, 3, 4, 5]
        target = total(widths, kept_columns, indent=2)
        out, kept = fit_widths(widths, FLOORS, target, sep_width=SEP, indent_width=2,
                               droppable=KEYWORDS, omit_droppable=True)
        self.assertEqual(out, widths)
        self.assertEqual(kept, kept_columns)

    def test_too_narrow_for_anything_returns_floors_without_raising(self):
        out, kept = fit(self.WIDTHS, 20)
        self.assertEqual(kept, [0, 1, 3, 4, 5])
        self.assertEqual([out[i] for i in kept], [36, 8, 3, 8, 10])

    def test_id_is_never_shrunk_or_dropped(self):
        for target in (10, 40, 70, 90):
            out, kept = fit(self.WIDTHS, target)
            self.assertIn(0, kept)
            self.assertEqual(out[0], 36)

    def test_without_droppable_column_nothing_is_dropped(self):
        out, kept = fit(self.WIDTHS, 20, droppable=None)
        self.assertEqual(kept, [0, 1, 2, 3, 4, 5])
        self.assertEqual([out[1], out[2], out[4]], [8, 8, 8])


class TestFitWidthsExceptions(unittest.TestCase):
    def test_natural_width_below_floor_does_not_grow(self):
        widths = [36, 5, 3, 3, 40, 10]
        out, _ = fit(widths, 60)
        self.assertLessEqual(out[1], 5)
        self.assertLessEqual(out[2], 3)

    def test_length_mismatch_raises_value_error(self):
        with self.assertRaises(ValueError):
            fit_widths([1, 2], [None], 10, sep_width=2, indent_width=0)

    def test_droppable_index_out_of_range_raises_value_error(self):
        with self.assertRaises(ValueError):
            fit_widths([1, 2], [None, 1], 10, sep_width=2, indent_width=0, droppable=5)


class TestFitWidthsScenario(unittest.TestCase):
    def test_demo_like_search_row_fits_every_terminal_from_80(self):
        widths = [36, 52, 24, 3, 70, 10]
        for cols in (80, 100, 120, 160):
            out, kept = fit(widths, cols - 4, indent=2)
            self.assertLessEqual(total(out, kept, 2), cols - 4, cols)
            self.assertEqual(out[0], 36)
        _, kept80 = fit(widths, 76, indent=2)
        self.assertNotIn(KEYWORDS, kept80)
        _, kept160 = fit(widths, 156, indent=2)
        self.assertIn(KEYWORDS, kept160)


if __name__ == '__main__':
    unittest.main()
