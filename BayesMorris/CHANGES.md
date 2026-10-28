# Fixes made

## "AI keeps thinking" (4 causes)
1. **Stuck turn after capture** (main.py): after the human captured a piece, the turn passed to the AI but the AI was never started -> "AI is thinking..." forever. Now the AI starts after captures too.
2. **Wrong terminal test in search** (ai/minimax.py): during placement `<3 pieces` was treated as a win, so the AI saw every move as already won and played blindly early on. Terminal wins now only apply after placement ends; search tracks pieces placed.
3. **Window froze while AI searched** (main.py): search ran inside the event loop. It now runs on a background thread, with iterative deepening and a 1.5 s time budget (depth up to 4), so it can never hang.
4. **TTS blocked the loop** (voice/speech_output.py): `runAndWait()` froze the window on every AI move. TTS now runs on its own thread.

## Voice / V key
- V toggled voice ON/OFF: first press listened, second press disabled it. Now each V press = one listen (push-to-talk).
- Listening blocked the UI and errors were swallowed. Now it runs in a thread and the panel shows the real error (no PyAudio / no mic / no internet).
- Parser rewritten (word-based): fixed "sixteen" -> 6 and 16, "to"/"at" substring matches, "move 4 2 5" (heard for "4 to 5"), homophones (for, ate, won).
- Voice/keyboard commands are ignored when it is not your turn.

## Other
- Keyboard fallback promised in README (type `12` or `4 5`, Enter) is now implemented.
- Bayesian: correct Laplace smoothing, learns from the position *before* the move, learns captures.
- AI mill message no longer overwritten; heuristic skips useless mobility calc in placement.


# Game modes update

- **Start-up menu**: Human vs Human / Human vs AI (click or press 1 / 2; `M` returns to the menu).
- **Human vs Human** (`game/csp.py`): rules modelled as a CSP (45 constraints) with incremental, worklist-based constraint propagation; legal moves/captures/win detection come from the propagated domains. UI shows domains, threat hints and live propagation statistics.
- **Human vs AI** (`ai/cns.py`): Minimax replaced by Conspiracy Number Search with conspiracy-number vectors over bucketed heuristic values, threshold-driven best-first expansion and incremental back-up. Bayesian prediction is kept as a root-move bonus.
- `GameState` takes a mode; mill with no removable opponent piece no longer leaves the game waiting for a capture.
- Voice: "menu" returns to the mode menu.


# UI redesign

- Sidebar removed. Top-centre turn strip with pulsing ball, live microphone waveform while listening, wooden table/board, 3D black & white balls, game-over banner.
- Layout is drawn on a fixed canvas and scaled to the window, so it never overflows the screen; `F11` fullscreen.
- Fixes: voice "remove N" with no capture pending no longer places a piece; stale voice results no longer leak between games; the AI's move is shown in the message line; voice notes fade after a few seconds.
