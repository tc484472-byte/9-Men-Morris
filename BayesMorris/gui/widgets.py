import pygame

class Button:
    def __init__(self, rect, text, font, callback=None):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.font = font
        self.callback = callback

    def draw(self, screen):
        mouse = pygame.mouse.get_pos()
        hovered = self.rect.collidepoint(mouse)
        pygame.draw.rect(screen, (52, 62, 82) if not hovered else (68, 82, 108), self.rect, border_radius=10)
        pygame.draw.rect(screen, (110, 125, 150), self.rect, width=1, border_radius=10)
        label = self.font.render(self.text, True, (235, 238, 245))
        screen.blit(label, label.get_rect(center=self.rect.center))

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos) and self.callback:
                self.callback()
                return True
        return False
