# BayesMorris

Voice-Controlled 9 Men's Morris — Human vs Human / Human vs AI

## Game modes (menu on start-up)

Click a card or press `1` / `2` when the window opens. Press `M` (or say "menu") to return to the menu.

| Mode | Engine |
|------|--------|
| **1 - Human vs Human** | Rules enforced as a **Constraint Satisfaction Problem** with **incremental constraint propagation** (`game/csp.py`) |
| **2 - Human vs AI** | **Conspiracy Number Search** (`ai/cns.py`) + Bayesian opponent model |

### Human vs Human: CSP with incremental propagation

- Variables: 24 cells (domain {empty, P1, P2}) plus derived domains: `mill[i]`, `move[p]`, `flying[P]`, `captable[P]`, `status`.
- 45 constraints: 16 mill, 24 adjacency/move, 2 flying, 2 capture, 1 global status (a domain wipe-out = blocked player loses).
- A move is legal only if it is in the propagated domain (`placements()`, `destinations(src)`, `captures()`).
- After a move only constraints subscribed to the changed variables are queued (AC-3 style worklist). Typically ~10-15 of 45 are revised instead of re-solving the whole board. The side panel shows the live counts.
- Hints: green ring = point where you can complete a mill, amber ring = point where the opponent threatens one.
- `MorrisCSP.verify_consistency()` checks the incremental domains against a from-scratch propagation.

### Human vs AI: Conspiracy Number Search

CNS (McAllester, 1988) grows the game tree best-first instead of to a fixed depth. Every node keeps, for each value bucket v, the minimum number of leaves that would have to change for its minimax value to become >= v (`ge`) or <= v (`le`): MAX nodes take MIN for `ge` and SUM for `le`, MIN nodes the reverse. For a threshold T the root value is *stable* when no value other than the current one can be reached by changing fewer than T leaves; otherwise the leaf on the cheapest conspiracy is expanded. When stable, T is raised, until the 1.5 s budget ends. The side panel shows the confirmed T, node count and depth. `ai/minimax.py` is kept for comparison but no longer used by the game.

## Look and feel

- Wooden table and board with engraved lines, and glossy 3D white / black balls.
- No sidebar: the top-centre strip shows which colour each player has and whose turn it is (the active player's ball pulses and glows).
- While you speak, a microphone pill with a live level waveform appears under the strip.
- The window scales to fit any screen (resizable, `F11` = fullscreen).

## Features

- Clean Pygame visual board with 24 valid positions.
- Two game modes chosen from a start-up menu (see above).
- Stage 1 placement, Stage 2 movement, and flying when a player has 3 pieces.
- Mill detection and legal capture rules.
- Conspiracy Number Search (Human vs AI) and CSP rule engine (Human vs Human).
- Heuristic evaluation (CNS leaf values).
- A discrete Bayesian Network predicts the human's likely strategy:
  - MILL
  - BLOCK
  - CAPTURE
  - MOVE
  - RANDOM
- Bayesian prediction adds a bonus when CNS chooses among its root moves.
- Voice commands with SpeechRecognition when available.
- Text/keyboard fallback when microphone libraries are unavailable.
- Text-to-speech feedback using pyttsx3 when available.
- Modular project structure.

## Project structure

```text
BayesMorris/
├── main.py
├── requirements.txt
├── README.md
├── data/
│   └── training_moves.csv
├── game/
│   ├── __init__.py
│   ├── board.py
│   ├── rules.py
│   ├── csp.py              <- CSP + incremental propagation (Human vs Human)
│   └── game_state.py
├── ai/
│   ├── __init__.py
│   ├── cns.py              <- Conspiracy Number Search (Human vs AI)
│   ├── minimax.py          (kept for comparison)
│   ├── heuristic.py
│   └── bayesian_model.py
├── voice/
│   ├── __init__.py
│   ├── speech_input.py
│   ├── command_parser.py
│   └── speech_output.py
└── gui/
    ├── __init__.py
    ├── board_ui.py
    ├── animations.py
    └── widgets.py
```

## Installation

Python 3.10+ is recommended.

```bash
pip install -r requirements.txt
```

For voice input, SpeechRecognition normally needs an audio backend. On Windows, if PyAudio installation is problematic, install a compatible PyAudio wheel or use the built-in text fallback.

Voice recognition uses Google's free web recognizer, so it **needs an internet connection** and a working microphone. If voice is unavailable, the side panel shows the exact reason.

Run:

```bash
python main.py
```

## Controls

Mouse:
- Click an empty point during placement.
- During movement, click your piece and then its destination.
- During a mill capture, click the opponent piece to remove.

Keyboard/text fallback:
- Enter a position such as `12`.
- Movement can be entered as `4 5`.
- Capture can be entered as `8`.
- `V` = press once, then speak one command (push-to-talk).
- `R` restarts the game (same mode), `M` returns to the mode menu, `F11` toggles fullscreen.
- `ESC` exits.

Voice examples:
- "place twelve"
- "move four to five"
- "remove eight"
- "restart game"

## AI design

The Bayesian Network is deliberately used as a probabilistic prediction layer rather than replacing Minimax.

```text
Board Features
   |
   +--> Human Threat
   +--> AI Threat
   +--> Piece Advantage
   +--> Game Stage
            |
            v
     Bayesian Network
            |
            v
   Predicted Human Strategy
            |
            v
     Minimax + Alpha-Beta
            |
            v
        AI Move
```

The Bayesian model learns/updates action frequencies from the included training CSV and from moves played during the current game. It estimates:

P(HumanStrategy | Board Features)

and gives Minimax an additional strategic score.

## Notes

This is an educational project implementation. The Bayesian Network is a discrete, hand-structured network with learned conditional frequency tables and Laplace smoothing. This keeps the project portable and easy to explain in a viva without making the game dependent on a heavyweight probabilistic package.


## Troubleshooting voice

Run `python -m voice.diagnose`. It checks the libraries, microphone, internet and speech service and prints the exact fix.

- **"No microphone backend"** -> `pip install sounddevice` (PyAudio is no longer required).
- **"Speech service unreachable"** -> Google's free recognizer needs internet.
- **"No speech heard"** -> Windows: Settings > Privacy & security > Microphone > allow desktop apps; check the default input device.
- Mouse and typed moves (`12`, `4 5` + Enter) always work without voice.

`__pycache__` folders are Python's bytecode cache (safe to delete). The game no longer creates them, and `.vscode/settings.json` hides any that exist.
