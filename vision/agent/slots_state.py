"""Maquina de estados das vagas com debounce e histerese (CLAUDE.md §6).

O estado bruto por frame entra numa janela deslizante de `debounce_seconds`.
A vaga so vira OCCUPIED se >= `occupied_ratio` dos frames viram bike, e so volta
para EMPTY se <= `empty_ratio`. Entre os dois limites o estado e mantido -- e isso
que absorve as falhas frequentes de deteccao do YOLO no edge (§4).
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

EMPTY = "EMPTY"
OCCUPIED = "OCCUPIED"


@dataclass
class Transition:
    slot_id: str
    kind: str          # "deposit" (EMPTY->OCCUPIED) ou "withdrawal" (OCCUPIED->EMPTY)
    ts: float          # quando a transicao foi CONFIRMADA
    raw_since: float   # quando o estado bruto comecou a mudar -- o buffer de rostos usa isso
    ratio: float


class SlotStateMachine:
    def __init__(
        self,
        slot_ids: List[str],
        debounce_seconds: float = 3.0,
        occupied_ratio: float = 0.7,
        empty_ratio: float = 0.2,
    ):
        self.debounce_seconds = debounce_seconds
        self.occupied_ratio = occupied_ratio
        self.empty_ratio = empty_ratio
        self.state: Dict[str, str] = {sid: EMPTY for sid in slot_ids}
        self._window: Dict[str, Deque[Tuple[float, bool]]] = {sid: deque() for sid in slot_ids}

    def ensure_slot(self, slot_id: str) -> None:
        self.state.setdefault(slot_id, EMPTY)
        self._window.setdefault(slot_id, deque())

    def update(self, ts: float, raw: Dict[str, bool]) -> List[Transition]:
        """Alimenta a janela com o estado bruto do frame e devolve as transicoes confirmadas."""
        transitions: List[Transition] = []
        for slot_id, value in raw.items():
            self.ensure_slot(slot_id)
            window = self._window[slot_id]
            window.append((ts, bool(value)))
            cutoff = ts - self.debounce_seconds
            while len(window) > 1 and window[0][0] < cutoff:
                window.popleft()

            # so decide com a janela cheia de verdade (evita disparo no primeiro frame)
            if window[-1][0] - window[0][0] < self.debounce_seconds * 0.8:
                continue

            ratio = sum(1 for _, v in window if v) / len(window)
            current = self.state[slot_id]

            if current == EMPTY and ratio >= self.occupied_ratio:
                self.state[slot_id] = OCCUPIED
                transitions.append(
                    Transition(slot_id, "deposit", ts, self._run_start(window, True), ratio)
                )
                window.clear()
            elif current == OCCUPIED and ratio <= self.empty_ratio:
                self.state[slot_id] = EMPTY
                transitions.append(
                    Transition(slot_id, "withdrawal", ts, self._run_start(window, False), ratio)
                )
                window.clear()
        return transitions

    @staticmethod
    def _run_start(window: Deque[Tuple[float, bool]], value: bool) -> float:
        """Timestamp do inicio da sequencia atual de `value` na janela."""
        start = window[-1][0]
        for ts, v in reversed(window):
            if v != value:
                break
            start = ts
        return start

    def snapshot(self) -> Dict[str, str]:
        return dict(self.state)

    def coverage_ratio(self, slot_id: str) -> Optional[float]:
        window = self._window.get(slot_id)
        if not window:
            return None
        return sum(1 for _, v in window if v) / len(window)
