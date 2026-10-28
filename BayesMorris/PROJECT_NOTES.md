# Implementation notes

## 1. Game engine

The board contains 24 valid points. `game/board.py` stores:
- coordinates
- adjacency
- all 16 mill combinations

`game/game_state.py` owns the mutable game state so that GUI, voice and AI do not directly modify each other's internals.

## 2. Bayesian Network

`ai/bayesian_model.py` implements a discrete probabilistic model.

Input evidence:
- game stage
- human threat level
- AI threat level
- piece advantage
- last move type

Output:
- probability of MILL
- probability of BLOCK
- probability of CAPTURE
- probability of MOVE
- probability of RANDOM

The model uses Laplace smoothing and updates with observations from the current game.

## 3. Minimax

`ai/minimax.py` searches future game states with alpha-beta pruning.

The Bayesian prediction does not replace the search. It affects:
- candidate ordering
- blocking bonus
- strategic evaluation

This gives a hybrid architecture:
Bayesian prediction + deterministic adversarial search.

## 4. Voice

`voice/speech_input.py` uses SpeechRecognition.
`voice/command_parser.py` converts natural commands into structured actions.
`voice/speech_output.py` provides optional TTS.

The GUI remains playable with mouse even if microphone support is unavailable.

## 5. GUI

Pygame renders:
- traditional 9 Men's Morris board
- human/AI pieces
- selected piece
- valid destinations
- capture targets
- last-move highlight
- game stage
- Bayesian probabilities
- voice status
- commands

## 6. Suggested viva explanation

"The Bayesian Network estimates the probability of the human choosing a strategic action from the current board evidence. Minimax then searches the adversarial game tree. Therefore, the Bayesian component handles uncertainty about human behaviour, while Minimax handles optimal game-state reasoning."


## 7. Modes: CSP and Conspiracy Number Search

**Human vs Human - CSP.** Cells are variables with domain {empty, P1, P2}; derived variables (mill state, per-piece move domains, flying, capture domain, game status) are maintained by 45 constraints. Each constraint declares the variables it reads and the one it writes; a worklist propagates only from variables that changed (AC-3 style), so a move revises ~15 of 45 constraints. A move is legal iff it lies in the propagated domain; a blocked player is a domain wipe-out in the status constraint.

**Human vs AI - CNS.** Best-first game-tree search guided by conspiracy numbers (min number of leaves that must change to move the root value). Viva line: "Alpha-beta decides depth in advance; CNS decides *where* to search by asking how many leaf evaluations would have to be wrong before the move choice changes, and stops when that number reaches the threshold T."
