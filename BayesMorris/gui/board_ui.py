"""
BayesMorris user interface (pygame).

Everything is drawn on a fixed logical canvas (LW x LH) which is scaled to the
real window, so the layout looks the same on any screen and the window can
never be taller than the desktop.  Static artwork (wooden table, board, lines)
is rendered once and cached; balls are shaded procedurally (3D look).
"""
import collections
import math
import random
import time

import pygame

from game.board import POSITIONS, DRAW_LINES
from game.rules import HUMAN, AI, EMPTY
from game.game_state import MODE_HVA, MODE_HVH

LW, LH = 1040, 830                      # logical canvas size
BOARD_CX, BOARD_CY = 520, 463           # centre of the board
BOARD_SCALE = 0.74                      # board units -> canvas pixels
PANEL_HALF = int(320 * BOARD_SCALE + 46)
BALL_R = 23

CREAM = (247, 232, 205)
CREAM_DIM = (205, 184, 150)
GOLD = (255, 205, 96)
WARN = (255, 150, 120)
TEAL = (120, 232, 176)
RED = (232, 84, 74)
SHADOW = (28, 15, 6)

MENU_CARDS = {
    MODE_HVH: pygame.Rect(110, 320, 380, 300),
    MODE_HVA: pygame.Rect(550, 320, 380, 300),
}
ERROR_WORDS = ("not ", "occupied", "cannot", "protected", "choose one", "select one",
               "wait", "could not", "unavailable", "only silence")


def _clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


# ---------------------------------------------------------------- artwork
def make_wood(w, h, base, seed, plank=None, grain=1.0):
    """Procedural wood: planks, wavy grain lines and fine speckle."""
    rnd = random.Random(seed)
    surf = pygame.Surface((w, h))
    ph = plank or h
    y = 0
    while y < h:
        hh = min(ph, h - y)
        tone = tuple(int(_clamp(c + rnd.randint(-9, 9), 0, 255)) for c in base)
        surf.fill(tone, (0, y, w, hh))
        for _ in range(int(hh * 0.9 * grain)):
            gy = y + rnd.random() * hh
            amp = rnd.uniform(1.0, 5.0)
            freq = rnd.uniform(0.004, 0.012)
            phase = rnd.uniform(0, 6.28)
            drift = rnd.uniform(-0.03, 0.03)
            delta = rnd.randint(6, 22)
            if rnd.random() < 0.8:
                col = tuple(max(0, c - delta) for c in tone)
            else:
                col = tuple(min(255, c + delta // 2) for c in tone)
            pts = [(x, gy + math.sin(x * freq + phase) * amp + (x - w / 2) * drift)
                   for x in range(0, w + 40, 40)]
            pygame.draw.lines(surf, col, False, pts, rnd.choice((1, 1, 2)))
        if ph < h and y > 0:
            pygame.draw.line(surf, tuple(max(0, c - 40) for c in base), (0, y), (w, y), 2)
            pygame.draw.line(surf, tuple(min(255, c + 18) for c in base), (0, y + 2), (w, y + 2), 1)
        y += hh
    for _ in range(w * h // 45):
        px, py = rnd.randrange(w), rnd.randrange(h)
        r, g, b = surf.get_at((px, py))[:3]
        d = rnd.randint(-9, 9)
        surf.set_at((px, py), (int(_clamp(r + d, 0, 255)), int(_clamp(g + d, 0, 255)),
                               int(_clamp(b + d, 0, 255))))
    return surf


def make_vignette(w, h, strength=170):
    small = pygame.Surface((52, 42), pygame.SRCALPHA)
    for y in range(42):
        for x in range(52):
            dx, dy = (x - 25.5) / 26.0, (y - 20.5) / 21.0
            d = min(1.0, math.sqrt(dx * dx + dy * dy) / 1.05)
            a = int(strength * (max(0.0, d - 0.4) / 0.6) ** 1.6)
            small.set_at((x, y), (12, 6, 2, a))
    return pygame.transform.smoothscale(small, (w, h))


def rounded(surf_wood, radius):
    """Crop a surface to a rounded rectangle (returns SRCALPHA surface)."""
    w, h = surf_wood.get_size()
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    out.blit(surf_wood, (0, 0))
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, w, h), border_radius=radius)
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return out


def _norm(v):
    m = math.sqrt(sum(c * c for c in v))
    return tuple(c / m for c in v)


def build_ball(kind, R=60):
    """Shaded sphere sprite.  kind: 'W' (white/ivory) or 'B' (glossy black)."""
    size = R * 2
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    light = _norm((-0.45, -0.62, 0.64))
    half = _norm((light[0], light[1], light[2] + 1.0))
    for py in range(size):
        for px in range(size):
            dx, dy = (px + 0.5 - R) / R, (py + 0.5 - R) / R
            d2 = dx * dx + dy * dy
            if d2 > 1.05:
                continue
            dist = math.sqrt(d2)
            edge = _clamp((1.0 - dist) * R + 0.5)
            if edge <= 0:
                continue
            nz = math.sqrt(max(0.0, 1.0 - d2))
            diff = max(0.0, dx * light[0] + dy * light[1] + nz * light[2])
            nh = max(0.0, dx * half[0] + dy * half[1] + nz * half[2])
            if kind == "W":
                shade = 0.40 + 0.66 * diff
                shade *= 0.70 + 0.30 * math.sqrt(nz)
                spec = nh ** 55 * 0.95
                bounce = max(0.0, dy) * 0.10          # warm light from the wood
                col = (244 * shade + 255 * spec + 40 * bounce,
                       241 * shade + 255 * spec + 22 * bounce,
                       232 * shade + 255 * spec)
            else:
                spec = nh ** 70 * 1.0 + nh ** 9 * 0.10
                rim = (1.0 - nz) ** 2.6 * 26
                base = 12 + 46 * diff ** 1.3
                col = (base + 255 * spec + rim * 0.8,
                       base + 255 * spec + rim * 0.9,
                       base + 4 + 255 * spec + rim)
            surf.set_at((px, py), (int(_clamp(col[0], 0, 255)), int(_clamp(col[1], 0, 255)),
                                   int(_clamp(col[2], 0, 255)), int(255 * edge)))
    return surf


def build_glow(color, R=64):
    size = R * 2
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    for py in range(size):
        for px in range(size):
            d = math.sqrt((px + 0.5 - R) ** 2 + (py + 0.5 - R) ** 2) / R
            if d < 1.0:
                a = int(255 * (1.0 - d) ** 2.2)
                surf.set_at((px, py), color + (a,))
    return surf


def build_shadow(R=60):
    w, h = int(R * 2.3), int(R * 1.3)
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    for py in range(h):
        for px in range(w):
            dx, dy = (px + 0.5 - w / 2) / (w / 2), (py + 0.5 - h / 2) / (h / 2)
            d = math.sqrt(dx * dx + dy * dy)
            if d < 1.0:
                surf.set_at((px, py), (10, 5, 2, int(150 * (1.0 - d) ** 1.4)))
    return surf


# ---------------------------------------------------------------------- UI
class BoardUI:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("BayesMorris — Nine Men's Morris")
        try:
            dw, dh = pygame.display.get_desktop_sizes()[0]
        except Exception:
            dw, dh = 1280, 720
        scale = min(1.0, (dh * 0.90 - 40) / LH, dw * 0.96 / LW)
        size = (max(520, int(LW * scale)), max(415, int(LH * scale)))
        self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        self.canvas = pygame.Surface((LW, LH)).convert()
        self.clock = pygame.time.Clock()
        self._scale, self._off = 1.0, (0, 0)

        def font(names, px, bold=False):
            return pygame.font.SysFont(names, px, bold=bold)

        serif = "georgia,cambria,palatinolinotype,timesnewroman,dejavuserif"
        sans = "segoeui,helveticaneue,arial,dejavusans"
        self.f_title = font(serif, 78, True)
        self.f_big = font(serif, 54, True)
        self.f_name = font(sans, 23, True)
        self.f_center = font(sans, 25, True)
        self.f_msg = font(sans, 20, True)
        self.f_body = font(sans, 17)
        self.f_small = font(sans, 14)
        self.f_num = font(sans, 12, True)
        self.f_card = font(serif, 31, True)

        self._ball_master = {}
        self._ball_cache = {}
        self._shadow_master = None
        self._shadow_cache = {}
        self._glow_master = {}
        self._glow_cache = {}
        self._wave = collections.deque([0.0] * 24, maxlen=24)
        self._level = 0.0

        self.table = self._build_table()
        self.board_layer = self._build_board_layer()
        self.strip_bg = self._build_strip_bg()
        self.plaque = self._build_plaque()

    # ------------------------------------------------------------ geometry
    def pos(self, index):
        x, y = POSITIONS[index]
        return (int(BOARD_CX + (x - 400) * BOARD_SCALE),
                int(BOARD_CY + (y - 400) * BOARD_SCALE))

    def to_logical(self, pos):
        ox, oy = self._off
        return ((pos[0] - ox) / self._scale, (pos[1] - oy) / self._scale)

    def index_at(self, mouse_pos):
        mx, my = self.to_logical(mouse_pos)
        best, best_dist = None, 30
        for i in range(24):
            x, y = self.pos(i)
            d = math.hypot(mx - x, my - y)
            if d < best_dist:
                best, best_dist = i, d
        return best

    def menu_hit(self, mouse_pos):
        p = self.to_logical(mouse_pos)
        for mode, rect in MENU_CARDS.items():
            if rect.collidepoint(p):
                return mode
        return None

    # ------------------------------------------------------ sprite caches
    def ball(self, kind, radius):
        r = max(4, int(round(radius)))
        key = (kind, r)
        if key not in self._ball_cache:
            if kind not in self._ball_master:
                self._ball_master[kind] = build_ball(kind)
            self._ball_cache[key] = pygame.transform.smoothscale(
                self._ball_master[kind], (2 * r, 2 * r))
        return self._ball_cache[key]

    def shadow(self, radius):
        r = max(4, int(round(radius)))
        if r not in self._shadow_cache:
            if self._shadow_master is None:
                self._shadow_master = build_shadow()
            mw, mh = self._shadow_master.get_size()
            k = r / 60.0
            self._shadow_cache[r] = pygame.transform.smoothscale(
                self._shadow_master, (max(2, int(mw * k)), max(2, int(mh * k))))
        return self._shadow_cache[r]

    def glow(self, color, radius):
        r = max(4, int(round(radius)))
        key = (color, r)
        if key not in self._glow_cache:
            if color not in self._glow_master:
                self._glow_master[color] = build_glow(color)
            self._glow_cache[key] = pygame.transform.smoothscale(
                self._glow_master[color], (2 * r, 2 * r))
        return self._glow_cache[key]

    def draw_ball(self, kind, cx, cy, radius, lift=0, alpha=255):
        sh = self.shadow(radius)
        self.canvas.blit(sh, sh.get_rect(center=(cx + radius * 0.12 + lift * 0.4,
                                                 cy + radius * 0.80 + lift * 0.6)))
        sprite = self.ball(kind, radius)
        if alpha < 255:
            sprite = sprite.copy()
            sprite.set_alpha(alpha)
        self.canvas.blit(sprite, sprite.get_rect(center=(cx, cy - lift)))

    def draw_glow(self, color, cx, cy, radius, alpha=255):
        g = self.glow(color, radius)
        if alpha < 255:
            g = g.copy()
            g.set_alpha(int(alpha))
        self.canvas.blit(g, g.get_rect(center=(cx, cy)))

    def ring(self, color, cx, cy, radius, width, alpha=255):
        size = int(radius * 2 + width * 2 + 4)
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(s, color + (int(alpha),), (size // 2, size // 2), int(radius), width)
        self.canvas.blit(s, s.get_rect(center=(cx, cy)))

    def text(self, txt, font, color, pos, anchor="center", shadow=SHADOW):
        surf = font.render(txt, True, color)
        rect = surf.get_rect()
        setattr(rect, anchor, pos)
        if shadow:
            self.canvas.blit(font.render(txt, True, shadow), rect.move(1, 2))
        self.canvas.blit(surf, rect)
        return rect

    # --------------------------------------------------------- static art
    def _build_table(self):
        table = make_wood(LW, LH, (104, 66, 36), seed=11, plank=104, grain=1.0)
        table.blit(make_vignette(LW, LH), (0, 0))
        return table

    def _build_board_layer(self):
        layer = self.table.copy()
        side = PANEL_HALF * 2
        px, py = BOARD_CX - PANEL_HALF, BOARD_CY - PANEL_HALF
        # soft drop shadow
        for i in range(14, 0, -1):
            s = pygame.Surface((side + i * 4, side + i * 4), pygame.SRCALPHA)
            pygame.draw.rect(s, (8, 4, 1, 9), s.get_rect(), border_radius=26 + i)
            layer.blit(s, (px - i * 2 + 4, py - i * 2 + 12))
        # dark walnut frame + maple playing surface
        frame = rounded(make_wood(side, side, (70, 42, 22), seed=5, grain=0.8), 26)
        layer.blit(frame, (px, py))
        inner = side - 28
        surface = rounded(make_wood(inner, inner, (226, 184, 124), seed=23, grain=0.55), 16)
        layer.blit(surface, (px + 14, py + 14))
        pygame.draw.rect(layer, (255, 226, 170), (px + 14, py + 14, inner, inner), 1, border_radius=16)
        pygame.draw.rect(layer, (96, 60, 30), (px + 13, py + 13, inner + 2, inner + 2), 2, border_radius=17)

        # engraved lines (light edge underneath, dark groove on top)
        for a, b in DRAW_LINES:
            pa, pb = self.pos(a), self.pos(b)
            pygame.draw.line(layer, (244, 214, 160), (pa[0] + 1, pa[1] + 2), (pb[0] + 1, pb[1] + 2), 6)
        for a, b in DRAW_LINES:
            pygame.draw.line(layer, (86, 52, 26), self.pos(a), self.pos(b), 5)
            pygame.draw.line(layer, (116, 76, 42), self.pos(a), self.pos(b), 2)
        # dimples with their numbers (the numbers are used for voice / typing)
        for i in range(24):
            x, y = self.pos(i)
            pygame.draw.circle(layer, (244, 214, 160), (x + 1, y + 2), 16)
            pygame.draw.circle(layer, (60, 36, 18), (x, y), 15)
            pygame.draw.circle(layer, (104, 68, 38), (x, y + 1), 13)
            num = self.f_num.render(str(i), True, (222, 190, 140))
            layer.blit(num, num.get_rect(center=(x, y + 1)))
        return layer

    def _build_strip_bg(self):
        w, h = 860, 106
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(s, (30, 17, 8, 205), (0, 0, w, h), border_radius=28)
        pygame.draw.rect(s, (236, 196, 136, 150), (0, 0, w, h), 2, border_radius=28)
        pygame.draw.line(s, (255, 230, 180, 60), (30, 4), (w - 30, 4), 1)
        return s

    def _build_plaque(self):
        w, h = MENU_CARDS[MODE_HVH].size
        wood = make_wood(w, h, (168, 112, 64), seed=41, grain=0.8)
        card = rounded(wood, 28)
        pygame.draw.rect(card, (255, 226, 176), (0, 0, w, h), 2, border_radius=28)
        pygame.draw.rect(card, (74, 44, 22), (4, 4, w - 8, h - 8), 3, border_radius=25)
        return card

    # ----------------------------------------------------------- present
    def _present(self):
        win = pygame.display.get_surface()
        ww, wh = win.get_size()
        scale = min(ww / LW, wh / LH)
        w, h = max(1, int(LW * scale)), max(1, int(LH * scale))
        ox, oy = (ww - w) // 2, (wh - h) // 2
        if (w, h) == (LW, LH):
            win.blit(self.canvas, (ox, oy))
        else:
            win.fill((22, 12, 5))
            win.blit(pygame.transform.smoothscale(self.canvas, (w, h)), (ox, oy))
        self._scale, self._off = scale, (ox, oy)
        pygame.display.flip()

    # -------------------------------------------------------------- menu
    def draw_menu(self, mouse_pos):
        t = time.time()
        c = self.canvas
        c.blit(self.table, (0, 0))
        self.text("BayesMorris", self.f_title, CREAM, (LW // 2, 120))
        self.text("Nine Men's Morris", self.f_msg, CREAM_DIM, (LW // 2, 185))
        self.text("Choose how you want to play", self.f_center, GOLD, (LW // 2, 262))

        hover = self.menu_hit(mouse_pos)
        cards = [
            (MODE_HVH, "1", "Human vs Human", ("Two players, one board.", "Pass the turn, play face to face.")),
            (MODE_HVA, "2", "Human vs AI", ("Challenge the computer.", "It plans ahead and learns your style.")),
        ]
        for mode, key, name, lines in cards:
            rect = MENU_CARDS[mode].copy()
            lifted = hover == mode
            if lifted:
                rect.y -= 8
            for i in range(10, 0, -1):          # shadow
                s = pygame.Surface((rect.w + i * 3, rect.h + i * 3), pygame.SRCALPHA)
                pygame.draw.rect(s, (8, 4, 1, 12), s.get_rect(), border_radius=30 + i)
                c.blit(s, (rect.x - i + 2, rect.y - i + 12 + (8 if lifted else 0)))
            c.blit(self.plaque, rect.topleft)
            if lifted:
                pygame.draw.rect(c, GOLD, rect, 3, border_radius=28)
            cx, cy = rect.centerx, rect.y + 92
            bob = math.sin(t * 2.2) * 3 if lifted else 0
            self.draw_ball("W", cx - 46, cy - bob, 38)
            self.draw_ball("B", cx + 46, cy + bob, 38)
            if mode == MODE_HVA:
                self.text("AI", self.f_name, (236, 236, 240), (cx + 46, cy + bob), shadow=(0, 0, 0))
            self.text(name, self.f_card, CREAM, (rect.centerx, rect.y + 178))
            for i, line in enumerate(lines):
                self.text(line, self.f_body, (250, 238, 214), (rect.centerx, rect.y + 218 + i * 24))
            self.text(f"Press {key}", self.f_small, GOLD, (rect.centerx, rect.y + 272))

        self.text("Click a card or press 1 / 2     ·     ESC to quit", self.f_small,
                  CREAM_DIM, (LW // 2, 700))
        self._present()

    # -------------------------------------------------------------- game
    def draw(self, game, voice_mode="off", mic_level=None, status="",
             ai_thinking=False, animator=None):
        t = time.time()
        self.canvas.blit(self.board_layer, (0, 0))
        self._draw_turn_strip(game, ai_thinking, t)
        self._draw_voice_pill(voice_mode, mic_level, t)
        self._draw_pieces(game, animator, t)
        if game.winner:
            self._draw_winner(game, t)
        self._draw_footer(game, status)
        self._present()

    # ---- top-centre turn strip
    def _names(self, game):
        return ("Player 1", "Player 2") if game.mode == MODE_HVH else ("You", "AI")

    def _draw_turn_strip(self, game, ai_thinking, t):
        c = self.canvas
        sx, sy = (LW - 860) // 2, 14
        c.blit(self.strip_bg, (sx, sy))
        names = self._names(game)
        hvh = game.mode == MODE_HVH
        pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi / 1.15)

        sides = [
            (HUMAN, "W", names[0], sx + 70, "left"),
            (AI, "B", names[1], sx + 860 - 70, "right"),
        ]
        for owner, kind, name, bx, side in sides:
            active = (game.current_player == owner and not game.winner)
            won = (game.winner == owner)
            lost = bool(game.winner) and not won
            by = sy + 53
            chip = pygame.Rect(0, 0, 294, 86)
            chip.center = (bx + (112 if side == "left" else -112), by)
            if active or won:
                s = pygame.Surface(chip.size, pygame.SRCALPHA)
                pygame.draw.rect(s, GOLD + (int(26 + 22 * pulse),), s.get_rect(), border_radius=22)
                pygame.draw.rect(s, GOLD + (int(130 + 90 * pulse),), s.get_rect(), 2, border_radius=22)
                c.blit(s, chip.topleft)
                self.draw_glow(GOLD, bx, by, 52 + 10 * pulse, alpha=150 + 80 * pulse)
                radius = 33 + 7 * pulse                   # the pulsing "your turn" ball
            else:
                radius = 29
            self.draw_ball(kind, bx, by, radius, alpha=120 if lost else 255)

            tx = bx + 52 if side == "left" else bx - 52
            anchor_n = "midleft" if side == "left" else "midright"
            col = GOLD if (active or won) else (CREAM_DIM if lost else CREAM)
            self.text(name, self.f_name, col, (tx, by - 16), anchor=anchor_n)
            self.text(self._count_text(game, owner), self.f_small, CREAM_DIM, (tx, by + 12), anchor=anchor_n)
            if active:
                tag = "YOUR TURN" if (not hvh and owner == HUMAN) else ("THINKING" if (not hvh) else "TURN")
                self.text(tag, self.f_small, GOLD, (tx, by + 30), anchor=anchor_n)

        # centre: what to do now
        cx = LW // 2
        if game.winner:
            who = names[0] if game.winner == HUMAN else names[1]
            verb = "win!" if (who == "You") else "wins!"
            main, sub, col = f"{who} {verb}", "GAME OVER", GOLD
        elif game.pending_capture:
            main, sub, col = "Remove a piece", "MILL FORMED", (255, 170, 140)
        elif ai_thinking or (not hvh and game.current_player == AI):
            main, sub, col = "AI is thinking" + "." * (int(t * 2.5) % 4), self._stage_text(game), CREAM
        else:
            main = "Place a piece" if game.stage == "PLACEMENT" else self._move_verb(game)
            sub, col = self._stage_text(game), CREAM
        self.text(main, self.f_center, col, (cx, sy + 44))
        self.text(sub, self.f_small, GOLD if game.winner else CREAM_DIM, (cx, sy + 74))

    @staticmethod
    def _stage_text(game):
        return {"PLACEMENT": "PLACEMENT PHASE", "MOVEMENT": "MOVEMENT PHASE",
                "FLYING": "FLYING PHASE"}.get(game.stage, game.stage)

    @staticmethod
    def _move_verb(game):
        return "Fly a piece" if (game.stage == "FLYING" and
                                 game.board.count(game.current_player) == 3) else "Move a piece"

    @staticmethod
    def _count_text(game, owner):
        placed = game.human_placed if owner == HUMAN else game.ai_placed
        on_board = game.board.count(owner)
        hand = 9 - placed
        return f"{hand} to place · {on_board} on board" if hand > 0 else f"{on_board} on board"

    # ---- microphone pill with live waveform
    def _draw_voice_pill(self, mode, level, t):
        c = self.canvas
        cx, cy = LW // 2, 150
        if mode in ("listening", "recognizing"):
            w, h = 410, 46
            rect = pygame.Rect(0, 0, w, h)
            rect.center = (cx, cy)
            s = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(s, (30, 17, 8, 225), s.get_rect(), border_radius=23)
            glow = int(150 + 90 * (0.5 + 0.5 * math.sin(t * 6)))
            pygame.draw.rect(s, (RED if mode == "listening" else GOLD) + (glow,), s.get_rect(), 2, border_radius=23)
            c.blit(s, rect.topleft)
            self._draw_mic_icon(rect.x + 28, cy, RED if mode == "listening" else GOLD)
            label = "Listening..." if mode == "listening" else "Recognizing..."
            self.text(label, self.f_body, CREAM, (rect.x + 54, cy), anchor="midleft")

            # level history -> animated bars (real microphone level when known)
            if mode == "recognizing":
                target = 0.12 + 0.10 * math.sin(t * 9)
            elif level is None:
                target = 0.30 + 0.30 * abs(math.sin(t * 7.3)) * (0.6 + 0.4 * math.sin(t * 2.1))
            else:
                target = min(1.0, (max(0.0, level) / 1500.0) ** 0.6)
            self._level = self._level * 0.45 + target * 0.55
            self._wave.append(self._level)
            n = len(self._wave)
            x0 = rect.right - 22 - n * 9 + 4
            for i, v in enumerate(self._wave):
                jitter = 0.06 * math.sin(t * 9 + i * 0.9)
                bh = 4 + 28 * _clamp(v + jitter * (0.4 + v), 0.04, 1.0)
                bx = x0 + i * 9
                age = i / max(1, n - 1)
                col = (int(150 + 105 * age), int(110 + 95 * age), int(70 + 26 * age))
                pygame.draw.rect(c, col, (bx, cy - bh / 2, 5, bh), border_radius=2)
        else:
            self._level = 0.0
            self._wave.extend([0.0] * len(self._wave))
            txt = "Press V and speak" if mode == "ready" else "Voice unavailable - click or type numbers"
            self._draw_mic_icon(cx - self.f_small.size(txt)[0] // 2 - 16, cy,
                                CREAM_DIM if mode == "ready" else (150, 120, 96), scale=0.8)
            self.text(txt, self.f_small, CREAM_DIM, (cx + 8, cy), shadow=SHADOW)

    def _draw_mic_icon(self, x, y, color, scale=1.0):
        c = self.canvas
        s = scale
        body = pygame.Rect(0, 0, int(10 * s), int(17 * s))
        body.center = (x, y - int(3 * s))
        pygame.draw.rect(c, color, body, border_radius=int(5 * s))
        pygame.draw.arc(c, color, pygame.Rect(x - int(9 * s), y - int(11 * s), int(18 * s), int(18 * s)),
                        math.pi, 2 * math.pi, max(2, int(2 * s)))
        pygame.draw.line(c, color, (x, y + int(7 * s)), (x, y + int(11 * s)), max(2, int(2 * s)))
        pygame.draw.line(c, color, (x - int(5 * s), y + int(11 * s)), (x + int(5 * s), y + int(11 * s)), max(2, int(2 * s)))

    # ---- board pieces and highlights
    def _draw_pieces(self, game, animator, t):
        pulse = 0.5 + 0.5 * math.sin(t * 5)
        selected = game.selected
        dest = game.destinations(selected) if selected is not None else ()
        caps = game.capture_targets()

        for p in dest:                                   # legal destinations
            x, y = self.pos(p)
            self.draw_glow(TEAL, x, y, 26 + 5 * pulse, alpha=235)
            pygame.draw.circle(self.canvas, (28, 96, 64), (x, y), 11)
            pygame.draw.circle(self.canvas, (190, 255, 220), (x, y), 8)
            self.ring(TEAL, x, y, 16 + 3 * pulse, 2, alpha=230)

        age = animator.age() if animator else None
        if age is not None and animator.position is not None:
            x, y = self.pos(animator.position)
            fade = 1.0 - age / animator.duration
            self.ring(GOLD, x, y, BALL_R + 6 + 8 * age, 3, alpha=210 * fade)

        for i, v in enumerate(game.board):
            if v == EMPTY:
                continue
            x, y = self.pos(i)
            kind = "W" if v == HUMAN else "B"
            radius, lift = BALL_R, 0
            if age is not None and animator.position == i and age < 0.30:
                k = age / 0.30
                ease = 1 + 2.7 * (k - 1) ** 3 + 1.7 * (k - 1) ** 2      # ease-out-back
                radius = BALL_R * (0.55 + 0.45 * ease)
                lift = (1 - k) * 22
            if i == selected:
                lift = 6 + 2 * pulse
            if i in caps:
                self.draw_glow(RED, x, y, 38 + 6 * pulse, alpha=150 + 70 * pulse)
            self.draw_ball(kind, x, y, radius, lift=lift)
            if i == selected:
                self.ring(TEAL, x, y - lift, BALL_R + 6, 3, alpha=230)
            if i in caps:
                self.ring(RED, x, y, BALL_R + 7 + 3 * pulse, 3, alpha=235)

    def _draw_winner(self, game, t):
        side = PANEL_HALF * 2
        s = pygame.Surface((side, 190), pygame.SRCALPHA)
        pygame.draw.rect(s, (20, 10, 4, 205), s.get_rect(), border_radius=24)
        pygame.draw.rect(s, GOLD + (200,), s.get_rect(), 2, border_radius=24)
        self.canvas.blit(s, s.get_rect(center=(BOARD_CX, BOARD_CY)))
        names = self._names(game)
        who = names[0] if game.winner == HUMAN else names[1]
        verb = "win!" if who == "You" else "wins!"
        self.text(f"{who} {verb}", self.f_big, GOLD, (BOARD_CX, BOARD_CY - 28))
        self.text("R  new game        M  menu", self.f_msg, CREAM, (BOARD_CX, BOARD_CY + 44))

    # ---- footer: feedback line, voice/typing line, key hints
    def _draw_footer(self, game, status):
        msg = (game.message or "").strip()
        low = msg.lower()
        color = WARN if any(w in low for w in ERROR_WORDS) else CREAM
        self.text(msg[:80], self.f_msg, color, (LW // 2, BOARD_CY + PANEL_HALF + 25))
        if status and status.strip() != msg:
            self.text(status[:96], self.f_small, CREAM_DIM, (LW // 2, BOARD_CY + PANEL_HALF + 49))
        self.text("Click a point  ·  type 12 or 4 5 + Enter  ·  V speak  ·  R restart  ·  M menu  ·  F11 fullscreen",
                  self.f_small, (160, 128, 98), (LW // 2, LH - 13), shadow=None)
