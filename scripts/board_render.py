from __future__ import annotations

from collections.abc import Iterable

Cell = tuple[int, int]


def build_ludo_cross_cells(arm_width: int = 3, arm_length: int = 5) -> set[Cell]:
    if arm_width <= 0 or arm_length <= 0:
        raise ValueError("arm_width and arm_length must be positive")
    if arm_length < arm_width:
        raise ValueError("arm_length must be >= arm_width")

    cells: set[Cell] = set()

    # Center square (arm_width x arm_width)
    for y in range(arm_width):
        for x in range(arm_width):
            cells.add((x, y))

    # Top arm (vertical rectangle)
    for y in range(-arm_length, 0):
        for x in range(arm_width):
            cells.add((x, y))

    # Bottom arm (vertical rectangle)
    for y in range(arm_width, arm_width + arm_length):
        for x in range(arm_width):
            cells.add((x, y))

    # Left arm (horizontal rectangle)
    for y in range(arm_width):
        for x in range(-arm_length, 0):
            cells.add((x, y))

    # Right arm (horizontal rectangle)
    for y in range(arm_width):
        for x in range(arm_width, arm_width + arm_length):
            cells.add((x, y))

    return cells


def render_cells_ascii(
    cells: Iterable[Cell],
    cell_w: int = 3,
    cell_h: int = 1,
    labels: dict[Cell, str] | None = None,
) -> str:
    cell_set = set(cells)
    if not cell_set:
        return ""

    min_x = min(x for x, _ in cell_set)
    max_x = max(x for x, _ in cell_set)
    min_y = min(y for _, y in cell_set)
    max_y = max(y for _, y in cell_set)

    width = max_x - min_x + 1
    height = max_y - min_y + 1

    rows = height * (cell_h + 1) + 1
    cols = width * (cell_w + 1) + 1

    canvas = [[" " for _ in range(cols)] for _ in range(rows)]

    def draw_horizontal(row: int, col_start: int, col_end: int) -> None:
        for c in range(col_start + 1, col_end):
            canvas[row][c] = "-"
        canvas[row][col_start] = "+"
        canvas[row][col_end] = "+"

    def draw_vertical(col: int, row_start: int, row_end: int) -> None:
        for r in range(row_start + 1, row_end):
            canvas[r][col] = "|"
        canvas[row_start][col] = "+"
        canvas[row_end][col] = "+"

    for x, y in cell_set:
        gx = x - min_x
        gy = y - min_y
        top = gy * (cell_h + 1)
        left = gx * (cell_w + 1)
        bottom = top + cell_h + 1
        right = left + cell_w + 1

        draw_horizontal(top, left, right)
        draw_horizontal(bottom, left, right)
        draw_vertical(left, top, bottom)
        draw_vertical(right, top, bottom)

        if labels and (x, y) in labels:
            label = labels[(x, y)]
            label = label[:cell_w]
            inner_row = top + 1
            inner_left = left + 1
            padded = label.center(cell_w)
            for i, ch in enumerate(padded):
                canvas[inner_row][inner_left + i] = ch

    return "\n".join("".join(row).rstrip() for row in canvas)


def build_outer_track(cells: set[Cell]) -> list[Cell]:
    if not cells:
        return []

    edges: list[tuple[tuple[int, int], tuple[int, int], Cell]] = []

    for x, y in cells:
        if (x, y - 1) not in cells:
            edges.append(((x, y), (x + 1, y), (x, y)))
        if (x + 1, y) not in cells:
            edges.append(((x + 1, y), (x + 1, y + 1), (x, y)))
        if (x, y + 1) not in cells:
            edges.append(((x + 1, y + 1), (x, y + 1), (x, y)))
        if (x - 1, y) not in cells:
            edges.append(((x, y + 1), (x, y), (x, y)))

    start_map: dict[tuple[int, int], list[tuple[tuple[int, int], tuple[int, int], Cell]]] = {}
    for edge in edges:
        start_map.setdefault(edge[0], []).append(edge)

    start_edge = edges[0]
    sequence_edges: list[tuple[tuple[int, int], tuple[int, int], Cell]] = []
    visited: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    current = start_edge

    while True:
        sequence_edges.append(current)
        visited.add((current[0], current[1]))

        next_edges = start_map.get(current[1], [])
        if not next_edges:
            break

        next_edge = None
        for edge in next_edges:
            if (edge[0], edge[1]) not in visited:
                next_edge = edge
                break
        if not next_edge:
            break

        current = next_edge
        if current[0] == start_edge[0] and current[1] == start_edge[1]:
            break

    cell_cycle: list[Cell] = []
    for _, _, cell in sequence_edges:
        if not cell_cycle or cell != cell_cycle[-1]:
            cell_cycle.append(cell)

    if cell_cycle and cell_cycle[0] == cell_cycle[-1]:
        cell_cycle.pop()

    return cell_cycle


def render_ludo_cross(
    arm_width: int = 3,
    arm_length: int = 5,
    label_track: bool = False,
) -> str:
    cells = build_ludo_cross_cells(arm_width=arm_width, arm_length=arm_length)

    labels: dict[Cell, str] | None = None
    if label_track:
        track = build_outer_track(cells)
        start_cell = (0, -(arm_length - 2))
        if start_cell not in track:
            raise ValueError("start cell not found on outer track")

        track = list(reversed(track))
        start_index = track.index(start_cell)
        ordered_track = track[start_index:] + track[:start_index]
        labels = {}
        step = 2 * arm_length + 1
        safe_offset = 2 * arm_length - 5
        for i, cell in enumerate(ordered_track):
            label = str(i)
            if i % step == 0:
                label = f"S{label}"
            elif (i - safe_offset) % step == 0:
                label = f"H{label}"
            labels[cell] = label

    return render_cells_ascii(cells, labels=labels)


if __name__ == "__main__":
    raw = input("Enter grid length N: ").strip()
    arm_length = int(raw)
    print(render_ludo_cross(arm_width=3, arm_length=arm_length, label_track=True))
