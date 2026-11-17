"""Where to put a box (label, info card) next to a point so that it does not cover other boxes.

Plain geometry in pixels, no Qt: rectangles are (x, y, width, height) tuples. The similarity map uses it for the
selected track's label and the hover / compare cards, which are drawn at a fixed pixel size next to their dots.
"""

BELOW_RIGHT, BELOW_LEFT, ABOVE_RIGHT, ABOVE_LEFT = 'below_right', 'below_left', 'above_right', 'above_left'
CORNERS = (BELOW_RIGHT, BELOW_LEFT, ABOVE_RIGHT, ABOVE_LEFT)


def corner_rect(anchor, size, corner, gap):
    """The box of `size` (width, height) at a corner of `anchor` (x, y), `gap` pixels away from it."""
    (x, y), (width, height) = anchor, size
    left = x + gap if corner in (BELOW_RIGHT, ABOVE_RIGHT) else x - gap - width
    top = y + gap if corner in (BELOW_RIGHT, BELOW_LEFT) else y - gap - height
    return left, top, width, height


def overlap(first, second):
    """Area two rectangles share (0 if they only touch)."""
    width = min(first[0] + first[2], second[0] + second[2]) - max(first[0], second[0])
    height = min(first[1] + first[3], second[1] + second[3]) - max(first[1], second[1])
    return max(width, 0) * max(height, 0)


def outside(rect, bounds):
    """Area of the rectangle that lies outside `bounds` (0 if it fits, or there are no bounds)."""
    if bounds is None:
        return 0
    return rect[2] * rect[3] - overlap(rect, bounds)


def place_box(anchor, size, taken=(), bounds=None, gap=0, corners=CORNERS):
    """(corner, rect) for a box next to `anchor`: the first corner, in the order given, where the box covers none of
    the `taken` rectangles and stays within `bounds` (the visible area). If no corner is free, the one that covers
    the least (overlap first, then the part outside the bounds; on a tie the earlier corner)."""
    best = None
    for rank, corner in enumerate(corners):
        rect = corner_rect(anchor, size, corner, gap)
        cost = (sum(overlap(rect, other) for other in taken), outside(rect, bounds), rank)
        if cost[:2] == (0, 0):
            return corner, rect
        if best is None or cost < best[0]:
            best = cost, corner, rect
    return best[1], best[2]
