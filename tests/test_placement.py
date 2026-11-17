"""Placing info boxes next to points without covering each other (core.placement)."""
import unittest

from songselector.core.placement import (
    ABOVE_LEFT,
    ABOVE_RIGHT,
    BELOW_LEFT,
    BELOW_RIGHT,
    corner_rect,
    overlap,
    place_box,
)


class PlacementTests(unittest.TestCase):
    def test_corner_rect_puts_the_box_at_each_corner_with_a_gap(self):
        self.assertEqual(corner_rect((100, 50), (40, 20), BELOW_RIGHT, 5), (105, 55, 40, 20))
        self.assertEqual(corner_rect((100, 50), (40, 20), BELOW_LEFT, 5), (55, 55, 40, 20))
        self.assertEqual(corner_rect((100, 50), (40, 20), ABOVE_RIGHT, 5), (105, 25, 40, 20))
        self.assertEqual(corner_rect((100, 50), (40, 20), ABOVE_LEFT, 5), (55, 25, 40, 20))

    def test_overlap_is_the_shared_area_and_touching_is_none(self):
        self.assertEqual(overlap((0, 0, 10, 10), (5, 5, 10, 10)), 25)
        self.assertEqual(overlap((0, 0, 10, 10), (10, 0, 10, 10)), 0)
        self.assertEqual(overlap((0, 0, 10, 10), (20, 20, 5, 5)), 0)
        self.assertEqual(overlap((0, 0, 10, 10), (2, 2, 3, 3)), 9)

    def test_first_free_corner_in_the_given_order(self):
        self.assertEqual(place_box((100, 100), (40, 20))[0], BELOW_RIGHT)
        taken = [corner_rect((100, 100), (40, 20), BELOW_RIGHT, 0)]
        self.assertEqual(place_box((100, 100), (40, 20), taken)[0], BELOW_LEFT)
        taken.append(corner_rect((100, 100), (40, 20), BELOW_LEFT, 0))
        self.assertEqual(place_box((100, 100), (40, 20), taken)[0], ABOVE_RIGHT)
        order = (ABOVE_LEFT, ABOVE_RIGHT, BELOW_LEFT, BELOW_RIGHT)
        self.assertEqual(place_box((100, 100), (40, 20), corners=order)[0], ABOVE_LEFT)

    def test_boxes_placed_one_after_another_never_overlap(self):
        # Three boxes at nearly the same point, like a label and two cards on a zoomed-out map.
        taken = []
        for anchor, size in (((200, 200), (120, 40)), ((203, 198), (180, 90)), ((198, 204), (180, 90))):
            _corner, rect = place_box(anchor, size, taken, bounds=(0, 0, 800, 600), gap=6)
            self.assertTrue(all(overlap(rect, other) == 0 for other in taken), rect)
            taken.append(rect)

    def test_a_box_near_the_edge_turns_inward(self):
        corner, rect = place_box((790, 590), (100, 50), bounds=(0, 0, 800, 600), gap=6)
        self.assertEqual(corner, ABOVE_LEFT)
        self.assertGreaterEqual(rect[0], 0)
        self.assertLessEqual(rect[1] + rect[3], 600)

    def test_no_free_corner_takes_the_least_covered_one(self):
        anchor, size = (100, 100), (40, 20)
        everywhere = [corner_rect(anchor, size, corner, 0) for corner in (BELOW_RIGHT, BELOW_LEFT, ABOVE_RIGHT)]
        everywhere.append((60, 80, 10, 5))  # covers a little of the last corner
        self.assertEqual(place_box(anchor, size, everywhere)[0], ABOVE_LEFT)


if __name__ == '__main__':
    unittest.main()
