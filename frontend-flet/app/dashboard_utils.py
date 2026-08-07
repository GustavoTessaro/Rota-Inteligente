from __future__ import annotations

import threading
import time
from typing import Any, Callable


DASHBOARD_INDICATORS = [
    ("Total de entregas hoje", "entregas_hoje"),
    ("Entregas concluídas", "entregas_concluidas"),
    ("Entregas em andamento", "entregas_andamento"),
    ("Entregas atrasadas", "entregas_atrasadas"),
    ("Rotas em execução", "rotas_em_execucao"),
    ("Veículos disponíveis", "veiculos_disponiveis"),
    ("Motoristas ativos", "motoristas_ativos"),
]


def get_dashboard_indicator_values(data: dict[str, Any]) -> dict[str, Any]:
    values = {}
    for _, key in DASHBOARD_INDICATORS:
        values[key] = data.get(key, 0)
    return values


class DashboardRefreshController:
    def __init__(self, callback: Callable[[], None], interval: float = 5.0):
        self.callback = callback
        self.interval = interval
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._lock = threading.Lock()
        self._callback_lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
            thread = self._thread
            self._thread = None

        if thread is not None:
            thread.join(timeout=0.5)

    def refresh_once(self) -> None:
        with self._callback_lock:
            try:
                self.callback()
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.refresh_once()
            except Exception:
                pass
            if self._stop_event.wait(self.interval):
                break
