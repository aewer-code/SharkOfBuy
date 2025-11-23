import pygame
import sys

# Инициализация Pygame
pygame.init()

# --- Настройки игры ---
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60
PADDLE_WIDTH = 15
PADDLE_HEIGHT = 100
BALL_SIZE = 15
PADDLE_SPEED = 7
BALL_SPEED_X = 5
BALL_SPEED_Y = 5

# Цвета (R, G, B)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
BLUE = (0, 0, 255)

# Создание игрового окна и часов
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Мини-Понг")
clock = pygame.time.Clock()

# Шрифт для счета
font = pygame.font.SysFont(None, 50)

# --- Класс Ракетки (Paddle) ---
class Paddle(pygame.Rect):
    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        self.speed = PADDLE_SPEED

    def move(self, dy):
        self.y += dy
        # Ограничение движения ракетки пределами экрана
        if self.top < 0:
            self.top = 0
        if self.bottom > SCREEN_HEIGHT:
            self.bottom = SCREEN_HEIGHT

    def draw(self, surface):
        pygame.draw.rect(surface, WHITE, self)

# --- Класс Мяча (Ball) ---
class Ball(pygame.Rect):
    def __init__(self, x, y, size):
        super().__init__(x, y, size, size)
        self.speed_x = BALL_SPEED_X
        self.speed_y = BALL_SPEED_Y

    def move(self):
        self.x += self.speed_x
        self.y += self.speed_y

        # Отскок от верхнего и нижнего краев экрана
        if self.top <= 0 or self.bottom >= SCREEN_HEIGHT:
            self.speed_y *= -1

    def draw(self, surface):
        pygame.draw.ellipse(surface, WHITE, self)

    def reset_position(self):
        self.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self.speed_x *= random.choice([-1, 1]) # Случайное направление после гола

# --- Инициализация объектов ---
# Ракетка игрока 1 (слева)
player1 = Paddle(20, SCREEN_HEIGHT // 2 - PADDLE_HEIGHT // 2, PADDLE_WIDTH, PADDLE_HEIGHT)
# Ракетка игрока 2 (справа)
player2 = Paddle(SCREEN_WIDTH - 20 - PADDLE_WIDTH, SCREEN_HEIGHT // 2 - PADDLE_HEIGHT // 2, PADDLE_WIDTH, PADDLE_HEIGHT)
# Мяч
ball = Ball(SCREEN_WIDTH // 2 - BALL_SIZE // 2, SCREEN_HEIGHT // 2 - BALL_SIZE // 2, BALL_SIZE)

# Счета игроков
score1 = 0
score2 = 0

# --- Основной игровой цикл ---
running = True
while running:
    # 1. Обработка событий (ввод пользователя)
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        
        # Управление с клавиатуры (W/S для P1, Up/Down для P2)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_w:
                player1_move = -PADDLE_SPEED
            if event.key == pygame.K_s:
                player1_move = PADDLE_SPEED
            if event.key == pygame.K_UP:
                player2_move = -PADDLE_SPEED
            if event.key == pygame.K_DOWN:
                player2_move = PADDLE_SPEED
        
        if event.type == pygame.KEYUP:
            if event.key == pygame.K_w or event.key == pygame.K_s:
                player1_move = 0
            if event.key == pygame.K_UP or event.key == pygame.K_DOWN:
                player2_move = 0

    # 2. Логика игры (перемещение объектов)
    player1.move(player1_move)
    player2.move(player2_move)
    ball.move()

    # Проверка столкновений мяча с ракетками
    if ball.colliderect(player1) or ball.colliderect(player2):
        ball.speed_x *= -1

    # Проверка голов (выход за левый/правый край)
    if ball.left <= 0:
        score2 += 1
        ball.reset_position()
    if ball.right >= SCREEN_WIDTH:
        score1 += 1
        ball.reset_position()

    # 3. Отрисовка
    screen.fill(BLACK) # Заливаем экран черным фоном

    player1.draw(screen)
    player2.draw(screen)
    ball.draw(screen)

    # Отрисовка счета
    score_text = font.render(f"{score1} - {score2}", True, BLUE)
    screen.blit(score_text, (SCREEN_WIDTH // 2 - score_text.get_width() // 2, 10))

    # Обновление экрана (отрисовка всего, что мы "нарисовали" в буфере)
    pygame.display.flip()

    # 4. Установка частоты кадров (FPS)
    clock.tick(FPS)

# Завершение Pygame
pygame.quit()
sys.exit()
