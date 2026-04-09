# -*- coding: utf-8 -*-
# core/engine.py
# RHEA Code CLI — Core entropy/trust engine

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict

ALPHA = 0.6
BETA = 0.3
TRUST_MAX = 1.0
RESEAL_K = 0.82
MEMORY_GATE_THRESHOLD = 1.35
LOW_TRUST_TRUNCATE_FLOOR = 0.40


class RHEAEngine:
    def __init__(self) -> None:
        self.trust = 1.0
        self.entropy_history: Deque[float] = deque(maxlen=12)

    def compute_entropy(self, text: str) -> float:
        if not text:
            return 0.0

        counts: Dict[str, int] = {}
        for c in text:
            counts[c] = counts.get(c, 0) + 1

        total = len(text)
        probs = [count / total for count in counts.values() if count > 0]
        return -sum(p * math.log2(p) for p in probs)

    def update_trust(self, entropy: float) -> str:
        d_trust = -ALPHA * entropy + BETA * (TRUST_MAX - self.trust)
        self.trust += d_trust
        self.trust = max(0.0, min(TRUST_MAX, self.trust))
        self.entropy_history.append(entropy)

        if entropy > MEMORY_GATE_THRESHOLD:
            self.trust = RESEAL_K * self.trust + (1 - RESEAL_K) * TRUST_MAX
            return "🌀"
        if self.trust < 0.45:
            return "⸸"
        if self.trust > 0.9:
            return "🧬"
        return "✫"