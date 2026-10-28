import time

from game.rules import (
    AI, HUMAN, EMPTY, apply_move, creates_mill_after,
    removable_positions, legal_moves, count_pieces, board_stage, opponent
)
from game.board import potential_mills
from ai.heuristic import potential_mills_heuristic

INF = float("inf")
WIN = 100000


class SearchTimeout(Exception):
    """Raised internally when the per-move time budget is used up."""


class MinimaxAI:
    """
    Minimax with alpha-beta pruning, iterative deepening and a time budget.

    The time budget is what prevents the "AI keeps thinking" problem: the
    search always returns the best move from the deepest *completed* depth,
    so a single AI turn can never run for more than ~time_limit seconds.
    """

    def __init__(self, depth=3, bayesian=None, time_limit=1.5):
        self.depth = depth              # maximum depth of iterative deepening
        self.bayesian = bayesian
        self.time_limit = time_limit
        self._deadline = None
        self._nodes = 0

    # ------------------------------------------------------------------ moves
    def complete_moves(self, board, player, stage):
        """Full turn options; a mill-forming move includes its capture."""
        result = []
        enemy = opponent(player)
        for move in legal_moves(board, player, stage):
            temp = apply_move(board, move, player)
            if temp is None:
                continue
            if creates_mill_after(board, move, player):
                choices = removable_positions(temp, enemy)
                if choices:
                    for rem in choices:
                        result.append((move, rem, True))
                    continue
            result.append((move, -1, False))
        # Mill-forming moves first -> far better alpha-beta pruning.
        result.sort(key=lambda item: not item[2])
        return [(m, r) for m, r, _ in result]

    def apply_turn(self, board, player, move, remove):
        temp = apply_move(board, move, player)
        if temp is None:
            return None
        if remove >= 0:
            temp[remove] = EMPTY
        return temp

    # --------------------------------------------------------------- bayesian
    def strategic_bonus(self, board, move, predicted):
        if not predicted:
            return 0
        strategy, probabilities = predicted
        bonus = 0
        temp = apply_move(board, move, AI)
        if strategy == "MILL" and temp:
            bonus += 40 * (potential_mills(board, HUMAN) - potential_mills(temp, HUMAN))
        elif strategy == "BLOCK" and temp:
            bonus += 20 * max(0, potential_mills(board, HUMAN) - potential_mills(temp, HUMAN))
        elif strategy == "CAPTURE":
            bonus += 5
        return bonus + int(20 * probabilities.get(strategy, 0))

    # ----------------------------------------------------------------- search
    def terminal_score(self, board, hp, ap, depth):
        # Piece-count wins only exist once placement is finished. (The old
        # code applied this during placement, when a player legitimately has
        # <3 pieces on the board, which made the AI think it had already won.)
        if hp < 9 or ap < 9:
            return None
        if count_pieces(board, HUMAN) < 3:
            return WIN + depth
        if count_pieces(board, AI) < 3:
            return -WIN - depth
        return None

    def _tick(self):
        self._nodes += 1
        if self._nodes & 255 == 0 and self._deadline is not None \
                and time.time() > self._deadline:
            raise SearchTimeout()

    def search(self, board, hp, ap, depth, maximizing, alpha, beta):
        self._tick()
        score = self.terminal_score(board, hp, ap, depth)
        if score is not None:
            return score

        stage = board_stage(board, hp, ap)
        if depth == 0:
            return potential_mills_heuristic(board, stage)

        player = AI if maximizing else HUMAN
        options = self.complete_moves(board, player, stage)
        if not options:
            return -WIN - depth if maximizing else WIN + depth

        value = -INF if maximizing else INF
        for move, remove in options:
            new_board = self.apply_turn(board, player, move, remove)
            if new_board is None:
                continue
            nhp, nap = hp, ap
            if move.kind == "place":
                if maximizing:
                    nap += 1
                else:
                    nhp += 1
            score = self.search(new_board, nhp, nap, depth - 1,
                                not maximizing, alpha, beta)
            if maximizing:
                value = max(value, score)
                alpha = max(alpha, value)
            else:
                value = min(value, score)
                beta = min(beta, value)
            if beta <= alpha:
                break
        return value

    def _search_root(self, board, hp, ap, stage, depth, options, predicted):
        best, best_score = None, -INF
        alpha = -INF
        for move, remove in options:
            new_board = self.apply_turn(board, AI, move, remove)
            if new_board is None:
                continue
            nap = ap + (1 if move.kind == "place" else 0)
            score = self.search(new_board, hp, nap, depth - 1, False, alpha, INF)
            score += self.strategic_bonus(board, move, predicted)
            if score > best_score:
                best_score, best = score, (move, remove)
            alpha = max(alpha, best_score)
        return best, best_score

    def best_move(self, board, stage, predicted=None, human_placed=9, ai_placed=9):
        options = self.complete_moves(board, AI, stage)
        if not options:
            return None, -INF

        options.sort(
            key=lambda item: self.strategic_bonus(board, item[0], predicted),
            reverse=True
        )

        best, best_score = options[0], -INF
        self._deadline = time.time() + self.time_limit
        self._nodes = 0
        try:
            for depth in range(1, self.depth + 1):
                result, score = self._search_root(
                    board, human_placed, ai_placed, stage, depth, options, predicted
                )
                if result is not None:
                    best, best_score = result, score
                    # Search the previous best move first next iteration.
                    options.remove(result)
                    options.insert(0, result)
                if abs(best_score) >= WIN:
                    break
        except SearchTimeout:
            pass
        finally:
            self._deadline = None
        return best, best_score
