import time


class CircuitBreaker:
    """Đóng mạch khi 1 API ngoài (Gemini/Reddit/Binance) lỗi liên tiếp
    `threshold` lần. Sau `cooldown` giây mới thử lại — tránh hammer
    endpoint đang fail."""

    def __init__(self, threshold: int = 5, cooldown: int = 600):
        self.threshold = threshold
        self.cooldown = cooldown
        self.fails = 0
        self.opened_at = 0.0

    def allow(self) -> bool:
        if self.fails < self.threshold:
            return True
        return time.monotonic() - self.opened_at > self.cooldown

    def record(self, ok: bool):
        if ok:
            self.fails = 0
        else:
            self.fails += 1
            if self.fails == self.threshold:
                self.opened_at = time.monotonic()
