from dataclasses import dataclass
from .board import ADJACENCY, MILLS, forms_mill, potential_mills

EMPTY = "x"
HUMAN = "1"
AI = "2"

def count_pieces(board, player):
    return board.count(player)

def opponent(player):
    return AI if player == HUMAN else HUMAN

def removable_positions(board, player):
    """Pieces that may legally be captured from player."""
    positions = [i for i, value in enumerate(board) if value == player]
    non_mill = [i for i in positions if not forms_mill(board, i, player)]
    return non_mill if non_mill else positions

def valid_destinations(board, source, player):
    if source < 0 or source >= 24 or board[source] != player:
        return set()

    own_count = count_pieces(board, player)
    if own_count == 3:
        return {i for i, value in enumerate(board) if value == EMPTY}
    return {i for i in ADJACENCY[source] if board[i] == EMPTY}

def valid_placement_positions(board):
    return {i for i, value in enumerate(board) if value == EMPTY}

def is_winner(board, player, placement_complete=True):
    # A player wins when the opponent has fewer than 3 pieces
    # after placement is complete, or has no legal move.
    opp = opponent(player)
    if placement_complete and count_pieces(board, opp) < 3:
        return True
    if placement_complete and count_pieces(board, opp) > 0:
        if not any(valid_destinations(board, p, opp) for p in range(24)
                   if board[p] == opp):
            return True
    return False

def board_stage(board, human_placed, ai_placed):
    if human_placed < 9 or ai_placed < 9:
        return "PLACEMENT"
    if count_pieces(board, HUMAN) == 3 or count_pieces(board, AI) == 3:
        return "FLYING"
    return "MOVEMENT"

@dataclass(frozen=True)
class Move:
    kind: str
    source: int = -1
    target: int = -1
    remove: int = -1

    def short(self):
        if self.kind == "place":
            return f"Place {self.target}"
        if self.kind == "move":
            return f"Move {self.source} -> {self.target}"
        return f"Remove {self.remove}"

def apply_move(board, move, player):
    new_board = list(board)
    if move.kind == "place":
        if new_board[move.target] != EMPTY:
            return None
        new_board[move.target] = player
    elif move.kind == "move":
        if new_board[move.source] != player or new_board[move.target] != EMPTY:
            return None
        if move.target not in valid_destinations(new_board, move.source, player):
            return None
        new_board[move.source] = EMPTY
        new_board[move.target] = player
    elif move.kind == "remove":
        if new_board[move.remove] != opponent(player):
            return None
        if move.remove not in removable_positions(new_board, opponent(player)):
            return None
        new_board[move.remove] = EMPTY
    else:
        return None
    return new_board

def creates_mill_after(board, move, player):
    temp = list(board)
    if move.kind == "place":
        temp[move.target] = player
        return forms_mill(temp, move.target, player)
    if move.kind == "move":
        temp[move.source] = EMPTY
        temp[move.target] = player
        return forms_mill(temp, move.target, player)
    return False

def legal_moves(board, player, stage, human_placed=9, ai_placed=9):
    moves = []
    if stage == "PLACEMENT":
        for p in valid_placement_positions(board):
            moves.append(Move("place", target=p))
        return moves

    for source in range(24):
        if board[source] != player:
            continue
        for target in valid_destinations(board, source, player):
            moves.append(Move("move", source=source, target=target))
    return moves

def legal_turn_sequences(board, player, stage):
    """
    Generate complete turn choices, including an optional capture after
    a move/placement that forms a mill.
    """
    result = []
    for move in legal_moves(board, player, stage):
        temp = apply_move(board, move, player)
        if temp is None:
            continue
        if creates_mill_after(board, move, player):
            for remove in removable_positions(temp, opponent(player)):
                result.append((move, remove))
        else:
            result.append((move, -1))
    return result
