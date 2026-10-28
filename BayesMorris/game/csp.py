"""
Nine Men's Morris as a Constraint Satisfaction Problem (CSP) with
*incremental* constraint propagation.  Used by Human-vs-Human mode.

Model
-----
Variables (base)      cell[p]  p = 0..23, domain {EMPTY, P1, P2}
                      hand[P], turn, pending_capture      (small scalar variables)
Derived variables     mill[i]      owner / open-two threat of mill line i
                      move[p]      domain of legal destinations of the piece on p
                      flying[P]    may player P fly?
                      captable[P]  domain of pieces of P that may be removed
                      status       game result (a domain wipe-out = player blocked)

Constraints (45 in total)
-------------------------
    MillConstraint(i)      16   reads the 3 cells of line i
    MoveConstraint(p)      24   reads cell p, its neighbours and flying[*]
    FlyingConstraint(P)     2   reads pieces[P], hand[P]
    CaptureConstraint(P)    2   reads pieces[P] and every mill[i]
    StatusConstraint        1   reads every move[p], pieces, hand, turn

Incremental propagation (AC-3 style worklist)
---------------------------------------------
After a move only the variables that were assigned are "changed".  Only the
constraints *subscribed* to a changed variable are queued.  Revising a
constraint may prune/alter a derived domain, which in turn queues the
constraints subscribed to that domain, until a fixed point is reached.
A typical move therefore revises ~10-15 of the 45 constraints, instead of
re-solving the whole board from scratch.  ``verify_consistency()`` proves the
incremental result equals a from-scratch propagation (used by the tests).

A move is legal iff its value is still in the propagated domain:
    place(p)      p in placements()          (cell domain not yet pruned)
    move(s, t)    t in destinations(s)       (move[s] domain)
    capture(p)    p in captures()            (captable domain; mill pieces pruned)
"""
from collections import deque

from .board import ADJACENCY, MILLS
from .rules import HUMAN, AI, EMPTY, Move, opponent

P1, P2 = HUMAN, AI
PLAYER_NAME = {P1: "Player 1", P2: "Player 2"}
MILLS_OF = {p: [i for i, m in enumerate(MILLS) if p in m] for p in range(24)}


# --------------------------------------------------------------------------
# Constraints.  Each one lists the variables it reads, the variable it writes
# and a revise() that recomputes the written domain.  revise() returns True
# when the domain actually changed (which is what triggers further propagation).
# --------------------------------------------------------------------------
class Constraint:
    kind = "constraint"

    def __init__(self, reads, writes):
        self.reads = tuple(reads)
        self.writes = writes

    def revise(self, csp):  # pragma: no cover - interface
        raise NotImplementedError


class MillConstraint(Constraint):
    """Line i is a mill if its 3 cells hold the same player; it is a
    *threat* if two cells hold player X and the third is still EMPTY."""
    kind = "mill"

    def __init__(self, index):
        self.index = index
        super().__init__([("cell", p) for p in MILLS[index]], ("mill", index))

    def revise(self, csp):
        line = MILLS[self.index]
        vals = [csp.board[p] for p in line]
        owner = threat = None
        if vals[0] != EMPTY and vals.count(vals[0]) == 3:
            owner = vals[0]
        elif vals.count(EMPTY) == 1:
            for player in (P1, P2):
                if vals.count(player) == 2:
                    threat = (player, line[vals.index(EMPTY)])
        changed = (csp.mill_owner[self.index], csp.mill_threat[self.index]) != (owner, threat)
        csp.mill_owner[self.index] = owner
        csp.mill_threat[self.index] = threat
        return changed


class MoveConstraint(Constraint):
    """Adjacency constraint: a piece on p may go to an EMPTY neighbour
    (or to any EMPTY point if its owner is flying)."""
    kind = "move"

    def __init__(self, p):
        self.p = p
        reads = [("cell", p)] + [("cell", n) for n in ADJACENCY[p]]
        reads += [("flying", P1), ("flying", P2)]
        super().__init__(reads, ("move", p))

    def revise(self, csp):
        owner = csp.board[self.p]
        if owner == EMPTY:
            new = frozenset()
        elif csp.flying[owner]:
            new = frozenset(csp.empties)
        else:
            new = frozenset(n for n in ADJACENCY[self.p] if csp.board[n] == EMPTY)
        changed = new != csp.move_dom[self.p]
        csp.move_dom[self.p] = new
        return changed


class FlyingConstraint(Constraint):
    """Relaxes the adjacency constraint once a player is down to 3 pieces."""
    kind = "flying"

    def __init__(self, player):
        self.player = player
        super().__init__([("pieces", player), ("hand", player)], ("flying", player))

    def revise(self, csp):
        new = csp.hand[self.player] == 0 and len(csp.pieces[self.player]) == 3
        changed = new != csp.flying[self.player]
        csp.flying[self.player] = new
        return changed


class CaptureConstraint(Constraint):
    """Pieces inside a mill are pruned from the capture domain, unless every
    piece of that player is in a mill."""
    kind = "capture"

    def __init__(self, player):
        self.player = player
        reads = [("pieces", player)] + [("mill", i) for i in range(len(MILLS))]
        super().__init__(reads, ("captable", player))

    def revise(self, csp):
        pl = self.player
        pieces = csp.pieces[pl]
        protected = {p for p in pieces
                     if any(csp.mill_owner[i] == pl for i in MILLS_OF[p])}
        new = frozenset(pieces - protected) or frozenset(pieces)
        changed = new != csp.captable[pl]
        csp.captable[pl] = new
        return changed


class StatusConstraint(Constraint):
    """Global constraint: once placement is over, a player with < 3 pieces, or
    whose pieces all have an empty move domain (domain wipe-out) on their own
    turn, has lost."""
    kind = "status"

    def __init__(self):
        reads = [("move", p) for p in range(24)]
        reads += [("pieces", P1), ("pieces", P2), ("hand", P1), ("hand", P2),
                  ("turn",), ("pending",)]
        super().__init__(reads, ("status",))

    def revise(self, csp):
        winner = None
        if csp.hand[P1] == 0 and csp.hand[P2] == 0:
            for pl in (P1, P2):
                if len(csp.pieces[pl]) < 3:
                    winner = opponent(pl)
            if winner is None and not csp.pending_capture:
                mover = csp.turn
                if not any(csp.move_dom[p] for p in csp.pieces[mover]):
                    winner = opponent(mover)
        changed = winner != csp.winner
        csp.winner = winner
        return changed


# --------------------------------------------------------------------------
class MorrisCSP:
    N_CONSTRAINTS = len(MILLS) + 24 + 2 + 2 + 1   # 45

    def __init__(self):
        self.constraints = (
            [MillConstraint(i) for i in range(len(MILLS))]
            + [MoveConstraint(p) for p in range(24)]
            + [FlyingConstraint(P1), FlyingConstraint(P2)]
            + [CaptureConstraint(P1), CaptureConstraint(P2)]
            + [StatusConstraint()]
        )
        # variable -> constraints subscribed to it
        self.subscribers = {}
        for c in self.constraints:
            for var in c.reads:
                self.subscribers.setdefault(var, []).append(c)
        self.move_constraint = {c.p: c for c in self.constraints
                                if isinstance(c, MoveConstraint)}
        self.reset()

    # ------------------------------------------------------------ state
    def reset(self):
        if hasattr(self, "board"):
            self.board[:] = [EMPTY] * 24      # keep list identity for GameState
        else:
            self.board = [EMPTY] * 24
        self._load(self.board, {P1: 9, P2: 9}, P1, False)
        self.removed = {P1: 0, P2: 0}
        self.last_move = None
        self.message = "Player 1 - place a piece."
        self.total_revisions = 0
        self.moves_made = 0
        self.last_stats = {"revisions": 0, "changed": [], "queued": 0}
        self._run(deque(self.constraints), set(self.constraints))

    def _load(self, board, hand, turn, pending):
        if board is not self.board:
            self.board[:] = board
        self.hand = dict(hand)
        self.turn = turn
        self.pending_capture = pending
        self.winner = None
        self.empties = {p for p in range(24) if self.board[p] == EMPTY}
        self.pieces = {pl: {p for p in range(24) if self.board[p] == pl}
                       for pl in (P1, P2)}
        self.mill_owner = [None] * len(MILLS)
        self.mill_threat = [None] * len(MILLS)
        self.move_dom = {p: frozenset() for p in range(24)}
        self.flying = {P1: False, P2: False}
        self.captable = {P1: frozenset(), P2: frozenset()}

    # ---------------------------------------------------- propagation
    def _run(self, queue, queued):
        revisions = 0
        changed_vars = []
        while queue:
            c = queue.popleft()
            queued.discard(c)
            revisions += 1
            if c.revise(self):
                changed_vars.append(c.writes)
                for sub in self.subscribers.get(c.writes, ()):
                    if sub not in queued:
                        queued.add(sub)
                        queue.append(sub)
        return revisions, changed_vars

    def _propagate(self, assigned):
        """Queue only the constraints subscribed to the assigned variables."""
        queue, queued = deque(), set()

        def push(c):
            if c not in queued:
                queued.add(c)
                queue.append(c)

        for var in assigned:
            for c in self.subscribers.get(var, ()):
                push(c)
        # A flying piece may land on *any* empty point, so its move domain
        # depends on every cell: re-queue those few constraints explicitly.
        if any(v[0] == "cell" for v in assigned):
            for pl in (P1, P2):
                if self.flying[pl]:
                    for p in self.pieces[pl]:
                        push(self.move_constraint[p])
        initial = len(queue)
        revisions, changed = self._run(queue, queued)
        self.total_revisions += revisions
        # accumulate over the (up to two) passes that make up one action
        self.last_stats["revisions"] += revisions
        self.last_stats["changed"] = self.last_stats["changed"] + changed
        self.last_stats["queued"] += initial

    def _set_cell(self, p, value):
        old = self.board[p]
        changed = [("cell", p)]
        if old != EMPTY:
            self.pieces[old].discard(p)
            changed.append(("pieces", old))
        self.board[p] = value
        if value == EMPTY:
            self.empties.add(p)
        else:
            self.empties.discard(p)
            self.pieces[value].add(p)
            changed.append(("pieces", value))
        return changed

    # ------------------------------------------------------- domains
    def phase(self):
        if self.hand[P1] > 0 or self.hand[P2] > 0:
            return "PLACEMENT"
        if self.flying[P1] or self.flying[P2]:
            return "FLYING"
        return "MOVEMENT"

    def placements(self):
        if self.winner or self.pending_capture or self.hand[self.turn] <= 0:
            return frozenset()
        return frozenset(self.empties)

    def destinations(self, src):
        if (self.winner or self.pending_capture or self.hand[self.turn] > 0
                or not (0 <= src < 24) or self.board[src] != self.turn):
            return frozenset()
        return self.move_dom[src]

    def captures(self):
        if not self.pending_capture or self.winner:
            return frozenset()
        return self.captable[opponent(self.turn)]

    def threats(self, player):
        """Points where `player` could complete a mill right now."""
        result = set()
        for i, th in enumerate(self.mill_threat):
            if th is None or th[0] != player:
                continue
            cell = th[1]
            if self.hand[player] > 0:
                result.add(cell)
            elif any(cell in self.move_dom[p] for p in self.pieces[player]
                     if p not in MILLS[i]):
                result.add(cell)
        return result

    # --------------------------------------------------------- actions
    def place(self, pos):
        if self.winner:
            return False, "The game is over."
        if self.pending_capture:
            return False, "Mill! Remove an opponent piece first."
        if self.hand[self.turn] <= 0:
            return False, "No pieces left to place - move a piece."
        if pos not in self.placements():
            return False, "That point is occupied."
        player = self.turn
        self._begin_action()
        changed = self._set_cell(pos, player)
        self.hand[player] -= 1
        changed.append(("hand", player))
        self.last_move = Move("place", target=pos)
        self._finish_action(changed, player, pos)
        return True, self.message

    def move(self, src, dst):
        if self.winner:
            return False, "The game is over."
        if self.pending_capture:
            return False, "Mill! Remove an opponent piece first."
        if self.hand[self.turn] > 0:
            return False, "Placement is not finished yet."
        player = self.turn
        if not (0 <= src < 24) or self.board[src] != player:
            return False, "Select one of your own pieces."
        if dst not in self.destinations(src):
            return False, "That is not a legal destination."
        self._begin_action()
        changed = self._set_cell(src, EMPTY) + self._set_cell(dst, player)
        self.last_move = Move("move", source=src, target=dst)
        self._finish_action(changed, player, dst)
        return True, self.message

    def capture(self, pos):
        if not self.pending_capture:
            return False, "No capture is required."
        player = self.turn
        enemy = opponent(player)
        if pos not in self.captures():
            if 0 <= pos < 24 and self.board[pos] == enemy:
                return False, "That piece is protected by a mill."
            return False, "Choose one of the opponent's pieces."
        self._begin_action()
        changed = self._set_cell(pos, EMPTY)
        self.removed[enemy] += 1
        self.pending_capture = False
        changed.append(("pending",))
        self.last_move = Move("remove", remove=pos)
        self._advance_turn(changed)
        self._set_message(f"{PLAYER_NAME[player]} removed {pos}. ")
        return True, self.message

    def _begin_action(self):
        self.moves_made += 1
        self.last_stats = {"revisions": 0, "changed": [], "queued": 0}

    def _finish_action(self, changed, player, target):
        """Propagate the assignment; a mill (when a capture exists) keeps the
        turn for the capture, otherwise the turn passes to the opponent."""
        # Propagate first so mill[] is up to date, then decide on the capture.
        self._propagate(changed)
        formed = any(self.mill_owner[i] == player for i in MILLS_OF[target])
        if formed and self.captable[opponent(player)]:
            self.pending_capture = True
            self._propagate([("pending",)])
            # keep stats of the whole action
            self.message = (f"{PLAYER_NAME[player]} formed a mill! "
                            f"Remove an opponent piece.")
            return
        self._advance_turn([])
        self._set_message("")

    def _advance_turn(self, changed):
        self.turn = opponent(self.turn)
        self._propagate(list(changed) + [("turn",)])

    def _set_message(self, prefix):
        if self.winner:
            self.message = f"{prefix}{PLAYER_NAME[self.winner]} WINS!"
        else:
            kind = "place a piece" if self.hand[self.turn] > 0 else "move a piece"
            self.message = f"{prefix}{PLAYER_NAME[self.turn]} - {kind}."

    # ------------------------------------------------------ diagnostics
    def snapshot(self):
        return (tuple(self.mill_owner), tuple(self.mill_threat),
                tuple(self.move_dom[p] for p in range(24)),
                (self.flying[P1], self.flying[P2]),
                (self.captable[P1], self.captable[P2]), self.winner)

    def verify_consistency(self):
        """True if the incrementally maintained domains equal a full
        from-scratch propagation of the same board (used by the tests)."""
        fresh = MorrisCSP()
        fresh._load(list(self.board), self.hand, self.turn, self.pending_capture)
        fresh._run(deque(fresh.constraints), set(fresh.constraints))
        return fresh.snapshot() == self.snapshot()

    def stats(self):
        return {
            "constraints": self.N_CONSTRAINTS,
            "last_revisions": self.last_stats["revisions"],
            "last_changed": len(self.last_stats["changed"]),
            "total_revisions": self.total_revisions,
            "full_cost": self.N_CONSTRAINTS * max(1, self.moves_made),
        }
