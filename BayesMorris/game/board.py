# Nine Men's Morris board geometry and static relationships.

POSITIONS = {
    0: (80, 80),   1: (400, 80),   2: (720, 80),
    3: (160, 160), 4: (400, 160), 5: (640, 160),
    6: (240, 240), 7: (400, 240), 8: (560, 240),
    9: (80, 400),  10: (160, 400), 11: (240, 400),
    12: (560, 400), 13: (640, 400), 14: (720, 400),
    15: (240, 560), 16: (400, 560), 17: (560, 560),
    18: (160, 640), 19: (400, 640), 20: (640, 640),
    21: (80, 720),  22: (400, 720), 23: (720, 720),
}

# Board edges. These are used to draw the traditional three nested squares
# and their connecting lines.
DRAW_LINES = [
    (0, 1), (1, 2), (2, 14), (14, 23), (23, 22), (22, 21),
    (21, 9), (9, 0),
    (3, 4), (4, 5), (5, 13), (13, 20), (20, 19), (19, 18),
    (18, 10), (10, 3),
    (6, 7), (7, 8), (8, 12), (12, 17), (17, 16), (16, 15),
    (15, 11), (11, 6),
    (1, 4), (4, 7), (9, 10), (10, 11), (12, 13), (13, 14),
    (16, 19), (19, 22)
]

# Legal adjacency graph for movement, derived from the drawn board lines so the
# two can never disagree.  Corner points of the three squares are NOT joined
# to each other (e.g. 15-18 or 18-21): only the midpoints are connected
# (1-4-7, 9-10-11, 12-13-14, 16-19-22).
ADJACENCY = {p: set() for p in POSITIONS}
for _a, _b in DRAW_LINES:
    ADJACENCY[_a].add(_b)
    ADJACENCY[_b].add(_a)

MILLS = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (9, 10, 11), (12, 13, 14), (15, 16, 17),
    (18, 19, 20), (21, 22, 23),
    (0, 9, 21), (3, 10, 18), (6, 11, 15),
    (1, 4, 7), (16, 19, 22), (8, 12, 17),
    (5, 13, 20), (2, 14, 23)
]

def neighbors(position):
    return ADJACENCY.get(position, set())

def forms_mill(board, position, player):
    if position < 0 or position >= 24 or board[position] != player:
        return False
    for mill in MILLS:
        if position in mill and all(board[p] == player for p in mill):
            return True
    return False

def mills_for_player(board, player):
    return [mill for mill in MILLS if all(board[p] == player for p in mill)]

def potential_mills(board, player):
    count = 0
    for mill in MILLS:
        values = [board[p] for p in mill]
        if values.count(player) == 2 and values.count("x") == 1:
            count += 1
    return count
