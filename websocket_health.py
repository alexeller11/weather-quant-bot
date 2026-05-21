import time


class TickValidator:
    """Valida ticks de preço, rejeitando saltos maiores que o threshold."""

    def __init__(self, max_delta=0.15):
        self.last_price  = None
        self.valid_ticks = 0
        self.max_delta   = max_delta

    def validate(self, price):
        if self.last_price is None:
            self.last_price = price
            return False

        delta = abs(price - self.last_price)

        if delta > self.max_delta:
            print(f"Tick rejeitado: delta={delta:.4f} > {self.max_delta}")
            return False

        self.valid_ticks += 1
        self.last_price = price
        return True


class ConnectionHealth:
    """Monitora saúde da conexão via frequência de ticks."""

    def __init__(self, max_avg_interval=5.0):
        self.ticks            = []
        self.start_time       = time.time()
        self.max_avg_interval = max_avg_interval

    def register_tick(self):
        self.ticks.append(time.time())

    def healthy(self):
        if len(self.ticks) < 3:
            return False

        intervals = [
            self.ticks[i] - self.ticks[i - 1]
            for i in range(1, len(self.ticks))
        ]

        avg = sum(intervals) / len(intervals)
        return avg <= self.max_avg_interval
