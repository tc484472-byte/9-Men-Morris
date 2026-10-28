from .rules import (
    HUMAN, AI, EMPTY, Move, apply_move, board_stage, creates_mill_after,
    removable_positions, count_pieces, legal_moves, valid_destinations
)
from .board import forms_mill
from .csp import MorrisCSP, P1, P2, PLAYER_NAME

MODE_HVA = "HVA"     # Human vs AI      (Conspiracy Number Search opponent)
MODE_HVH = "HVH"     # Human vs Human   (rules enforced by the CSP engine)
MODE_LABEL = {MODE_HVA: "Human vs AI", MODE_HVH: "Human vs Human"}


class GameState:
    def __init__(self, mode=MODE_HVA):
        self.mode = mode
        self.reset()

    def reset(self, mode=None):
        if mode is not None:
            self.mode = mode
        self.board = [EMPTY] * 24
        self.human_placed = 0
        self.ai_placed = 0
        self.human_removed = 0
        self.ai_removed = 0
        self.current_player = HUMAN
        self.selected = None
        self.pending_capture = False
        self.last_move = None
        self.winner = None
        self.message = "Your turn — place a piece."
        self.human_history = []
        self.ai_history = []
        self.csp = None
        if self.mode == MODE_HVH:
            # Human-vs-Human: every rule is a constraint in the CSP; the
            # GameState mirrors the CSP's (propagated) state for the UI.
            self.csp = MorrisCSP()
            self.board = self.csp.board
            self.message = self.csp.message

    # ------------------------------------------------------------ helpers
    @property
    def stage(self):
        return board_stage(self.board, self.human_placed, self.ai_placed)

    def name_of(self, player):
        if self.mode == MODE_HVH:
            return PLAYER_NAME[player]
        return "Human" if player == HUMAN else "AI"

    def can_human_place(self):
        return self.stage == "PLACEMENT" and self.human_placed < 9

    def can_human_move(self):
        return self.stage != "PLACEMENT" and self.current_player == HUMAN

    # ---- domains shown by the UI (CSP domains in HvH, rules in HvA) -------
    def destinations(self, source):
        if self.csp:
            return self.csp.destinations(source)
        return valid_destinations(self.board, source, HUMAN)

    def capture_targets(self):
        if not self.pending_capture:
            return set()
        if self.csp:
            return set(self.csp.captures())
        return set(removable_positions(self.board, AI))

    # ------------------------------------------- mode-independent actions
    def player_place(self, position):
        if self.csp:
            return self._csp_do(lambda: self.csp.place(position))
        return self.place_human(position)

    def player_move(self, source, target):
        if self.csp:
            return self._csp_do(lambda: self.csp.move(source, target))
        return self.move_human(source, target)

    def player_capture(self, position):
        if self.csp:
            return self._csp_do(lambda: self.csp.capture(position))
        return self.capture_human(position)

    def _csp_do(self, action):
        mover = self.csp.turn
        ok, msg = action()
        if ok:
            history = self.human_history if mover == P1 else self.ai_history
            history.append(self.csp.last_move)
            self._sync_from_csp()
            msg = self.message
        return ok, msg

    def _sync_from_csp(self):
        c = self.csp
        self.current_player = c.turn
        self.pending_capture = c.pending_capture
        self.winner = c.winner
        self.human_placed = 9 - c.hand[P1]
        self.ai_placed = 9 - c.hand[P2]
        self.human_removed = c.removed[P2]      # pieces P1 captured
        self.ai_removed = c.removed[P1]
        self.last_move = c.last_move
        self.message = c.message
        self.selected = None

    # ------------------------------------------------- Human vs AI rules
    def place_human(self, position):
        if self.current_player != HUMAN:
            return False, "It is the AI's turn."
        if not self.can_human_place():
            return False, "Placement stage is over."
        if position not in range(24) or self.board[position] != EMPTY:
            return False, "That position is occupied."
        self.board[position] = HUMAN
        self.human_placed += 1
        self.last_move = Move("place", target=position)
        self.human_history.append(self.last_move)
        self.current_player = AI

        if forms_mill(self.board, position, HUMAN) and removable_positions(self.board, AI):
            self.pending_capture = True
            self.current_player = HUMAN
            self.message = "Mill formed! Remove one AI piece."
        else:
            self.message = "AI is thinking..."
        return True, self.message

    def capture_human(self, position):
        if not self.pending_capture or self.current_player != HUMAN:
            return False, "No capture is required."
        if position not in removable_positions(self.board, AI):
            return False, "That AI piece cannot be captured."
        self.board[position] = EMPTY
        self.human_removed += 1
        self.pending_capture = False
        self.current_player = AI
        self.message = "AI is thinking..."
        return True, self.message

    def move_human(self, source, target):
        if self.current_player != HUMAN or self.stage == "PLACEMENT":
            return False, "You cannot move a piece right now."
        if self.board[source] != HUMAN:
            return False, "Select one of your own pieces."
        if target not in valid_destinations(self.board, source, HUMAN):
            return False, "That is not a legal destination."

        self.board[source] = EMPTY
        self.board[target] = HUMAN
        self.last_move = Move("move", source=source, target=target)
        self.human_history.append(self.last_move)
        if forms_mill(self.board, target, HUMAN) and removable_positions(self.board, AI):
            self.pending_capture = True
            self.current_player = HUMAN
            self.message = "Mill formed! Remove one AI piece."
        else:
            self.current_player = AI
            self.message = "AI is thinking..."
        self.selected = None
        return True, self.message

    def finish_ai_turn(self, move, remove=-1):
        if move.kind == "place":
            self.board[move.target] = AI
            self.ai_placed += 1
        elif move.kind == "move":
            self.board[move.source] = EMPTY
            self.board[move.target] = AI
        self.last_move = move
        self.ai_history.append(move)

        self.message = "Your turn."
        if forms_mill(self.board, move.target, AI):
            choices = removable_positions(self.board, HUMAN)
            if choices:
                if remove not in choices:
                    remove = choices[0]
                self.board[remove] = EMPTY
                self.ai_removed += 1
                self.message = f"AI formed a mill and removed {remove}. Your turn."
        self.current_player = HUMAN
        return remove

    def check_end(self):
        if self.csp:                       # the CSP's status constraint decides
            return self.winner
        # Once both players have placed 9, normal win rules apply.
        if self.human_placed < 9 or self.ai_placed < 9:
            return None
        human = count_pieces(self.board, HUMAN)
        ai = count_pieces(self.board, AI)
        if human < 3:
            self.winner = AI
        elif ai < 3:
            self.winner = HUMAN
        else:
            if not legal_moves(self.board, HUMAN, self.stage):
                self.winner = AI
            elif not legal_moves(self.board, AI, self.stage):
                self.winner = HUMAN
        if self.winner == HUMAN:
            self.message = "YOU WIN!"
        elif self.winner == AI:
            self.message = "AI WINS!"
        return self.winner
