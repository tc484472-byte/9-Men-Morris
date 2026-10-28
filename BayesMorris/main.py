import sys
sys.dont_write_bytecode = True      # no __pycache__ folders next to the code
import os
import threading
import time
import pygame

from game.game_state import GameState, MODE_HVA, MODE_HVH
from game.csp import PLAYER_NAME
from game.rules import HUMAN, AI, EMPTY
from ai.cns import ConspiracyNumberSearch, turn_options
from ai.bayesian_model import BayesianNetwork
from voice.speech_input import SpeechInput
from voice.command_parser import parse_command
from voice.speech_output import SpeechOutput
from gui.board_ui import BoardUI
from gui.animations import Animator

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data", "training_moves.csv")

class BayesMorrisApp:
    # Voice notes ("Heard: ...", errors, mic level) fade after a few seconds.
    @property
    def voice_status(self):
        return self._voice_status

    @voice_status.setter
    def voice_status(self, value):
        self._voice_status = value
        self._voice_status_at = time.time()

    def __init__(self):
        self.ui = BoardUI()
        self.game = GameState()
        self.bayes = BayesianNetwork(DATA_FILE)
        self.ai = ConspiracyNumberSearch(bayesian=self.bayes, time_limit=1.5)
        self.screen_state = "MENU"      # "MENU" or "GAME"
        self.speech = SpeechInput()
        self.tts = SpeechOutput()
        self.animator = Animator()

        self.voice_enabled = False      # True only while the mic is listening
        self.voice_status = ""
        self.running = True
        self.pending_source = None
        self.text_buffer = ""           # keyboard fallback: type "12" / "4 5" + Enter

        # AI runs on a worker thread so the window never freezes.
        self.ai_thinking = False
        self.ai_generation = 0          # bumped on restart to drop stale results
        self.ai_result = None
        self.ai_lock = threading.Lock()

        if not self.speech.available:
            self.voice_status = f"Voice off: {self.speech.error}"

        self.say("Welcome to BayesMorris. Choose a game mode.")

    # ------------------------------------------------------------- modes
    @property
    def hvh(self):
        return self.game.mode == MODE_HVH

    def is_human_turn(self):
        """Human vs Human: whoever's turn it is.  Human vs AI: the human."""
        return self.hvh or self.game.current_player == HUMAN

    def _drop_stale_voice(self):
        self.speech.poll()              # a late result must not leak into the next game
        self.voice_enabled = False

    def start_game(self, mode):
        self._drop_stale_voice()
        self.ai_generation += 1         # drop any in-flight AI search
        self.ai_thinking = False
        self.ai_result = None
        self.game.reset(mode)
        self.pending_source = None
        self.text_buffer = ""
        self.screen_state = "GAME"
        if mode == MODE_HVH:
            self.say("Human versus human. Player 1, place a piece.")
        else:
            self.say("Human versus AI. Your turn.")

    def go_to_menu(self):
        self._drop_stale_voice()
        self.ai_generation += 1
        self.ai_thinking = False
        self.ai_result = None
        self.pending_source = None
        self.text_buffer = ""
        self.screen_state = "MENU"
        self.say("Choose a game mode.")

    def say(self, text):
        self.tts.speak(text)            # the same text is shown by the game message

    def current_prediction(self):
        if self.hvh:
            return None
        last_type = "MOVE"
        if self.game.human_history:
            last_type = self.game.human_history[-1].kind.upper()
            if last_type == "PLACE":
                last_type = "MOVE"
        return self.bayes.predict_board(self.game.board, self.game.stage, last_type)

    def handle_position(self, position):
        """A point was clicked / spoken by the player whose turn it is."""
        g = self.game
        if position is None or g.winner or self.ai_thinking:
            return
        if not self.is_human_turn():
            return

        # Capture has highest priority.
        if g.pending_capture:
            ok, msg = g.player_capture(position)
            g.message = msg
            if ok:
                self.animator.highlight(position)
                if not self.hvh:
                    self.observe_capture()
                self.after_action()
            return

        # Placement stage.
        if g.stage == "PLACEMENT":
            self.pending_source = None
            ok, msg = g.player_place(position)
            g.message = msg
            if ok:
                self.animator.highlight(position)
                if not self.hvh:
                    self.observe_human_move()
                self.after_action()
            return

        # Movement stage.
        if self.pending_source is None:
            if g.board[position] == g.current_player:
                self.pending_source = position
                g.selected = position
                g.message = f"Selected {position}. Choose destination."
            else:
                g.message = "Select one of your pieces."
        else:
            source = self.pending_source
            if position == source:
                self.pending_source = None
                g.selected = None
                g.message = "Selection cancelled."
                return
            before = list(g.board)
            ok, msg = g.player_move(source, position)
            g.message = msg
            if ok:
                self.pending_source = None
                g.selected = None
                self.animator.highlight(position)
                if not self.hvh:
                    self.observe_human_move(before=before)
                self.after_action()

    def after_action(self):
        """Common tail of a successful human action."""
        self.check_game_end()
        if self.hvh:
            if not self.game.winner:
                self.say(self.game.message)
        elif not self.game.pending_capture:
            self.run_ai_turn()

    def observe_capture(self):
        features = self.bayes.board_features(
            self.game.board, self.game.stage, "MOVE")
        self.bayes.update_from_observation(features, "CAPTURE")

    def observe_human_move(self, before=None):
        if not self.game.human_history:
            return
        move = self.game.human_history[-1]
        after = list(self.game.board)
        if before is None:
            before = list(after)
            if move.kind == "place":
                before[move.target] = EMPTY

        strategy = self.bayes.human_strategy_from_move(
            before, after, move, self.game.stage
        )
        # Learn from the position the human faced *before* moving.
        features = self.bayes.board_features(before, self.game.stage, "MOVE")
        self.bayes.update_from_observation(features, strategy)

    def run_ai_turn(self):
        """Start the AI search on a background thread (non-blocking)."""
        if self.game.winner or self.game.current_player != AI or self.ai_thinking:
            return
        self.ai_thinking = True
        self.game.message = "AI is thinking..."

        board = list(self.game.board)
        stage = self.game.stage
        hp, ap = self.game.human_placed, self.game.ai_placed
        prediction = self.current_prediction()
        generation = self.ai_generation

        def worker():
            try:
                result, _ = self.ai.best_move(board, stage, prediction, hp, ap)
            except Exception as exc:  # never leave the game stuck
                print("AI error:", exc)
                result = "error"
            with self.ai_lock:
                self.ai_result = (generation, result)

        threading.Thread(target=worker, daemon=True).start()

    def poll_ai(self):
        with self.ai_lock:
            item, self.ai_result = self.ai_result, None
        if item is None:
            return
        generation, result = item
        if generation != self.ai_generation:
            return  # game was restarted while the AI was thinking
        self.ai_thinking = False
        self.apply_ai_result(result)

    def apply_ai_result(self, result):
        if self.game.winner:
            return
        if result == "error":
            # Fallback: any legal move, so the game can continue.
            options = turn_options(self.game.board, AI, self.game.stage)
            result = options[0] if options else None
        if result is None:
            self.game.winner = HUMAN
            self.game.message = "YOU WIN! AI has no legal move."
            self.say("You win!")
            return

        move, remove = result
        removed = self.game.finish_ai_turn(move, remove)
        target = move.target if move.kind in ("place", "move") else removed
        if target >= 0:
            self.animator.highlight(target)

        if move.kind == "place":
            spoken = f"AI placed at position {move.target}."
        else:
            spoken = f"AI moved from {move.source} to {move.target}."
        if removed >= 0:
            spoken += f" AI removed position {removed}."

        self.game.message = spoken + " Your turn."
        self.tts.speak(spoken)
        self.check_game_end()

    def check_game_end(self):
        winner = self.game.check_end()
        if not winner:
            return
        if self.hvh:
            self.say(f"{PLAYER_NAME[winner]} wins!")
        elif winner == HUMAN:
            self.say("You win!")
        else:
            self.say("The AI wins.")

    def start_voice(self):
        if not self.speech.available:
            self.voice_status = f"Voice off: {self.speech.error}"
            self.game.message = "Voice unavailable. Use mouse or type numbers."
            return
        if self.ai_thinking:
            self.voice_status = "Wait for the AI to finish."
            return
        if self.speech.start_listening():
            self.voice_enabled = True
            self.voice_status = "Listening... speak now"

    def voice_mode(self):
        """'listening' | 'recognizing' | 'ready' | 'off' - drives the mic pill."""
        if not self.speech.available:
            return "off"
        if self.speech.listening:
            status = (self.speech.status or "").lower()
            return "recognizing" if status.startswith("recogni") else "listening"
        return "ready"

    def mic_level(self):
        """Raw microphone level while listening (None if the backend has no meter)."""
        if self.speech.backend == "sounddevice":
            return self.speech.level
        return None

    def poll_voice(self):
        if self.speech.listening:
            self.voice_status = self.speech.status or "Listening..."
        result = self.speech.poll()
        if result is None:
            return
        self.voice_enabled = False
        kind, payload = result
        if kind != "text":
            self.voice_status = payload
            return
        self.voice_status = f"Heard: {payload}"
        self.execute_command(parse_command(payload))

    def execute_command(self, command):
        action = command.get("action")
        if action == "restart":
            self.reset()
        elif action == "quit":
            self.running = False
        elif action == "menu":
            self.go_to_menu()
        elif self.ai_thinking or not self.is_human_turn():
            self.game.message = "Wait - it is not your turn."
        elif action == "remove" and not self.game.pending_capture:
            self.game.message = "No capture right now - say 'place' or 'move'."
        elif action in ("place", "remove"):
            self.pending_source = None
            self.game.selected = None
            self.handle_position(command["position"])
        elif action == "move":
            if self.game.pending_capture:
                self.game.message = "Mill! Say 'remove' and a position."
            elif self.game.stage == "PLACEMENT":
                self.game.message = "Placement stage: say 'place' and a number."
            else:
                self.pending_source = None
                self.game.selected = None
                self.handle_position(command["source"])
                if self.pending_source is not None:
                    self.handle_position(command["target"])
        else:
            self.game.message = "I could not understand that command."

    def submit_text(self):
        """Keyboard fallback: '12' places/removes, '4 5' moves."""
        nums = [int(n) for n in self.text_buffer.split() if n.isdigit()]
        self.text_buffer = ""
        if len(nums) == 1 and nums[0] <= 23:
            self.execute_command({"action": "place", "position": nums[0]})
        elif len(nums) == 2 and max(nums) <= 23:
            self.execute_command(
                {"action": "move", "source": nums[0], "target": nums[1]})

    def reset(self):
        self.ai_generation += 1       # discard any in-flight AI search
        self.ai_thinking = False
        self.ai_result = None
        self.game.reset()             # same mode
        self.pending_source = None
        self.text_buffer = ""
        self.say("New game started.")

    def run(self):
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif self.screen_state == "MENU":
                    self.handle_menu_event(event)
                else:
                    self.handle_game_event(event)

            if self.screen_state == "MENU":
                self.ui.draw_menu(pygame.mouse.get_pos())
                self.ui.clock.tick(60)
                continue

            self.poll_ai()
            self.poll_voice()

            if (self._voice_status and not self.speech.listening
                    and time.time() - self._voice_status_at > 8):
                self._voice_status = ""
            status = self.voice_status
            if self.text_buffer:
                status = f"Typing: {self.text_buffer}  (Enter to submit)"
            self.ui.draw(
                self.game,
                voice_mode=self.voice_mode(),
                mic_level=self.mic_level(),
                status=status,
                ai_thinking=self.ai_thinking,
                animator=self.animator,
            )
            self.ui.clock.tick(60)

        pygame.quit()
        sys.exit(0)

    def handle_menu_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.key == pygame.K_F11:
                try:
                    pygame.display.toggle_fullscreen()
                except Exception:
                    pass
            elif event.key in (pygame.K_1, pygame.K_KP1):
                self.start_game(MODE_HVH)
            elif event.key in (pygame.K_2, pygame.K_KP2):
                self.start_game(MODE_HVA)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mode = self.ui.menu_hit(event.pos)
            if mode:
                self.start_game(mode)

    def handle_game_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                self.submit_text()
            elif event.key == pygame.K_BACKSPACE:
                self.text_buffer = self.text_buffer[:-1]
            elif event.key == pygame.K_F11:
                try:
                    pygame.display.toggle_fullscreen()
                except Exception:
                    pass
            elif event.key == pygame.K_v:
                self.start_voice()
            elif event.key == pygame.K_r and not self.text_buffer:
                self.reset()
            elif event.key == pygame.K_m and not self.text_buffer:
                self.go_to_menu()
            elif event.unicode and (event.unicode.isdigit() or event.unicode == " "):
                if len(self.text_buffer) < 6:
                    self.text_buffer += event.unicode

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if (self.is_human_turn() and not self.game.winner
                    and not self.ai_thinking):
                position = self.ui.index_at(event.pos)
                self.handle_position(position)

if __name__ == "__main__":
    BayesMorrisApp().run()
