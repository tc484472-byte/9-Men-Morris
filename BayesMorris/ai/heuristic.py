from game.board import MILLS, potential_mills, forms_mill
from game.rules import HUMAN, AI, count_pieces, legal_moves

def count_mills(board, player):
    return sum(1 for mill in MILLS if all(board[p] == player for p in mill))

def open_two(board, player):
    return potential_mills(board, player)

def mobility(board, player, stage):
    return len(legal_moves(board, player, stage))

def potential_mills_heuristic(board, stage):
    ai = count_pieces(board, AI)
    human = count_pieces(board, HUMAN)
    score = 100 * (ai - human)
    score += 80 * (count_mills(board, AI) - count_mills(board, HUMAN))
    score += 25 * (open_two(board, AI) - open_two(board, HUMAN))
    if stage != "PLACEMENT":
        score += 3 * (mobility(board, AI, stage) - mobility(board, HUMAN, stage))
    if ai == 3:
        score += 10
    if human == 3:
        score -= 10
    return score

def num_pieces_heuristic(board, stage):
    return 100 * (count_pieces(board, AI) - count_pieces(board, HUMAN))
