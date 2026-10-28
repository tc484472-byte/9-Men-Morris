"""
Conspiracy Number Search (CNS, McAllester 1988) for Nine Men's Morris.

Alpha-beta searches to a fixed depth.  CNS instead grows the game tree
*best-first*, guided by "conspiracy numbers":

    cn_ge[v]  = minimum number of leaves whose value would have to change
                for this node's minimax value to become >= v
    cn_le[v]  = ... to become <= v

Leaf   : 0 if it already satisfies the bound, else 1 (infinity if the leaf is
         a proven win/loss or at the depth cap and cannot be expanded).
MAX    : cn_ge = MIN over children      cn_le = SUM over children
MIN    : cn_ge = SUM over children      cn_le = MIN over children

Search with a conspiracy threshold T:
    hi = largest v with root.cn_ge[v] < T   (value reachable by < T leaf changes)
    lo = smallest v with root.cn_le[v] < T
When lo == hi the root value is T-stable: at least T leaves would have to be
wrong before the answer could change.  Otherwise expand a leaf on the cheapest
conspiracy that could still widen the interval.  Once stable, T is raised
and the search continues, until the time budget is spent.

Leaf values are the heuristic scores bucketed to R integer levels so that the
conspiracy-number vectors are small and can be backed up incrementally.
The extreme buckets are reserved for proven wins / losses.
The Bayesian prediction of the human's strategy is used as a tie-breaker /
bonus when choosing among the root moves (same role it had with Minimax).
"""
import time

from game.rules import (
    AI, HUMAN, EMPTY, apply_move, creates_mill_after, removable_positions,
    legal_moves, count_pieces, board_stage, opponent,
)
from game.board import potential_mills
from ai.heuristic import potential_mills_heuristic

INF = float("inf")
WIN = 100000            # raw value of a proven win (minus depth: faster is better)
STEP = 40               # heuristic points per bucket
HALF = 15
R = 2 * HALF + 1        # number of value buckets (0 = proven loss, R-1 = proven win)
CN_INF = 10 ** 6        # conspiracy number of "cannot be changed"


# ----------------------------------------------------------------- helpers
def bucket(value):
    if value >= WIN // 2:
        return R - 1
    if value <= -WIN // 2:
        return 0
    b = int(round(value / STEP))
    return max(-(HALF - 1), min(HALF - 1, b)) + HALF


def bucket_to_raw(b):
    if b >= R - 1:
        return WIN
    if b <= 0:
        return -WIN
    return (b - HALF) * STEP


def turn_options(board, player, stage):
    """All complete turns: a move/placement, plus the capture it earns."""
    enemy = opponent(player)
    result = []
    for move in legal_moves(board, player, stage):
        temp = apply_move(board, move, player)
        if temp is None:
            continue
        if creates_mill_after(board, move, player):
            choices = removable_positions(temp, enemy)
            if choices:
                result.extend((move, rem) for rem in choices)
                continue
        result.append((move, -1))
    return result


def apply_turn(board, player, move, remove):
    temp = apply_move(board, move, player)
    if temp is None:
        return None
    if remove >= 0:
        temp[remove] = EMPTY
    return temp


def strategic_bonus(board, move, predicted):
    """Bayesian opponent model: reward moves that counter the human's
    most likely strategy."""
    if not predicted:
        return 0
    strategy, probabilities = predicted
    temp = apply_move(board, move, AI)
    bonus = 0
    if strategy == "MILL" and temp:
        bonus += 40 * (potential_mills(board, HUMAN) - potential_mills(temp, HUMAN))
    elif strategy == "BLOCK" and temp:
        bonus += 20 * max(0, potential_mills(board, HUMAN) - potential_mills(temp, HUMAN))
    elif strategy == "CAPTURE":
        bonus += 5
    return bonus + int(20 * probabilities.get(strategy, 0))


def _leaf_vectors(b, fixed):
    other = CN_INF if fixed else 1
    ge = [0 if b >= v else other for v in range(R)]
    le = [0 if b <= v else other for v in range(R)]
    return ge, le


class Node:
    __slots__ = ("board", "hp", "ap", "maximizing", "depth", "parent",
                 "move", "children", "val", "ge", "le", "fixed")

    def __init__(self, board, hp, ap, maximizing, depth, parent, move):
        self.board = board
        self.hp = hp
        self.ap = ap
        self.maximizing = maximizing      # True -> AI to move
        self.depth = depth
        self.parent = parent
        self.move = move                  # (Move, remove) that led here
        self.children = None
        self.val = 0
        self.ge = self.le = None
        self.fixed = False


class ConspiracyNumberSearch:
    def __init__(self, bayesian=None, time_limit=1.5, max_nodes=60000,
                 max_depth=16, max_threshold=64):
        self.bayesian = bayesian
        self.time_limit = time_limit
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.max_threshold = max_threshold
        self.last_stats = None

    # ------------------------------------------------------------- tree
    def _make_node(self, board, hp, ap, maximizing, depth, parent, move):
        node = Node(board, hp, ap, maximizing, depth, parent, move)
        if hp >= 9 and ap >= 9 and count_pieces(board, HUMAN) < 3:
            node.val, node.fixed = WIN - depth, True
        elif hp >= 9 and ap >= 9 and count_pieces(board, AI) < 3:
            node.val, node.fixed = -(WIN - depth), True
        else:
            stage = board_stage(board, hp, ap)
            node.val = potential_mills_heuristic(board, stage)
            node.fixed = depth >= self.max_depth
        node.ge, node.le = _leaf_vectors(bucket(node.val), node.fixed)
        if depth > self._deepest:
            self._deepest = depth
        return node

    @staticmethod
    def _combine(node):
        kids = node.children
        ge_cols = zip(*[k.ge for k in kids])
        le_cols = zip(*[k.le for k in kids])
        if node.maximizing:
            val = max(k.val for k in kids)
            ge = [min(c) for c in ge_cols]
            le = [min(CN_INF, sum(c)) for c in le_cols]
        else:
            val = min(k.val for k in kids)
            ge = [min(CN_INF, sum(c)) for c in ge_cols]
            le = [min(c) for c in le_cols]
        return val, ge, le

    def _backup(self, node):
        """Propagate changed values / conspiracy numbers towards the root,
        stopping as soon as an ancestor is unaffected (incremental update)."""
        p = node.parent
        while p is not None:
            val, ge, le = self._combine(p)
            if val == p.val and ge == p.ge and le == p.le:
                break
            p.val, p.ge, p.le = val, ge, le
            p = p.parent

    def _expand(self, node):
        player = AI if node.maximizing else HUMAN
        stage = board_stage(node.board, node.hp, node.ap)
        options = turn_options(node.board, player, stage)
        if not options:
            # The side to move is blocked -> it has lost (placement always
            # has a free point, so this only happens in movement stages).
            node.val = -(WIN - node.depth) if node.maximizing else (WIN - node.depth)
            node.fixed = True
            node.ge, node.le = _leaf_vectors(bucket(node.val), True)
            self._backup(node)
            return
        kids = []
        for move, remove in options:
            board = apply_turn(node.board, player, move, remove)
            hp, ap = node.hp, node.ap
            if move.kind == "place":
                if player == AI:
                    ap += 1
                else:
                    hp += 1
            kids.append(self._make_node(board, hp, ap, not node.maximizing,
                                        node.depth + 1, node, (move, remove)))
        node.children = kids
        self.nodes += len(kids)
        self.expansions += 1
        old = (node.val, node.ge, node.le)
        node.val, node.ge, node.le = self._combine(node)
        if (node.val, node.ge, node.le) != old:
            self._backup(node)

    # -------------------------------------------------------- selection
    @staticmethod
    def _range(root, T):
        hi = max(v for v in range(R) if root.ge[v] < T)
        lo = min(v for v in range(R) if root.le[v] < T)
        return lo, hi

    @staticmethod
    def _pick_child(node, direction, v):
        # "any" mode: one child suffices (MIN of costs); "all" mode: every
        # child must change (SUM of costs) -> take the cheapest unsatisfied one.
        any_mode = node.maximizing == (direction == "ge")
        best, best_cost = None, CN_INF
        for child in node.children:
            cost = child.ge[v] if direction == "ge" else child.le[v]
            if cost >= CN_INF or (not any_mode and cost == 0):
                continue
            if cost < best_cost:
                best, best_cost = child, cost
        return best

    def _select_leaf(self, root, lo, hi):
        value = bucket(root.val)
        candidates = []
        if hi > value:
            candidates.append((root.ge[hi], -(hi - value), "ge", hi))
        if lo < value:
            candidates.append((root.le[lo], -(value - lo), "le", lo))
        if not candidates:
            return None
        _, _, direction, v = min(candidates)
        node = root
        while node.children is not None:
            node = self._pick_child(node, direction, v)
            if node is None:
                return None
        return None if node.fixed else node

    # ----------------------------------------------------------- search
    def best_move(self, board, stage, predicted=None, human_placed=9, ai_placed=9):
        started = time.time()
        deadline = started + self.time_limit
        options = turn_options(board, AI, stage)
        if not options:
            return None, -INF
        if len(options) == 1:
            self.last_stats = {"nodes": 1, "expansions": 0, "threshold": 0,
                               "value": 0, "lo": 0, "hi": 0, "depth": 1,
                               "elapsed": 0.0, "best": self._describe(options[0]),
                               "forced": True}
            return options[0], 0

        self.nodes = self.expansions = 0
        self._deepest = 0
        root = self._make_node(list(board), human_placed, ai_placed, True, 0, None, None)
        root.fixed = False
        self._expand(root)

        threshold, confirmed = 2, 1
        lo = hi = bucket(root.val)
        while time.time() < deadline and self.nodes < self.max_nodes:
            lo, hi = self._range(root, threshold)
            if lo == hi:                              # root value is T-stable
                confirmed = threshold
                if abs(root.val) >= WIN // 2 or threshold >= self.max_threshold:
                    break                             # proven result / cap
                threshold += 1
                continue
            leaf = self._select_leaf(root, lo, hi)
            if leaf is None:
                break
            self._expand(leaf)

        best = self._choose(root, board, predicted)
        self.last_stats = {
            "nodes": self.nodes, "expansions": self.expansions,
            "threshold": confirmed, "value": int(root.val),
            "lo": bucket_to_raw(lo), "hi": bucket_to_raw(hi),
            "depth": self._deepest, "elapsed": time.time() - started,
            "best": self._describe(best.move), "forced": False,
        }
        return best.move, root.val

    def _choose(self, root, board, predicted):
        kids = root.children
        wins = [k for k in kids if k.val >= WIN // 2]
        if wins:                                      # fastest proven win
            return max(wins, key=lambda k: k.val)
        safe = [k for k in kids if k.val > -WIN // 2] or kids
        return max(safe, key=lambda k: k.val + strategic_bonus(board, k.move[0], predicted))

    @staticmethod
    def _describe(turn):
        move, remove = turn
        text = move.short()
        return text + (f", remove {remove}" if remove >= 0 else "")
