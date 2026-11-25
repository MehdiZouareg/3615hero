"""Dés seedables : toute la part de hasard du moteur passe par ici."""
from __future__ import annotations

import random
import re

_EXPR = re.compile(r"^\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


def parse_expr(expr: str) -> tuple[int, int, int]:
    """'2d6+12' -> (2, 6, 12). Lève ValueError si l'expression est invalide."""
    m = _EXPR.match(str(expr))
    if not m:
        raise ValueError(f"expression de dés invalide : {expr!r}")
    count = int(m.group(1) or 1)
    sides = int(m.group(2))
    bonus = int(m.group(3).replace(" ", "")) if m.group(3) else 0
    if count < 1 or sides < 2:
        raise ValueError(f"expression de dés invalide : {expr!r}")
    return count, sides, bonus


class Dice:
    """Source de hasard. Avec une graine, les tirages sont reproductibles."""

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def d(self, sides: int = 6) -> int:
        return self._rng.randint(1, sides)

    def roll(self, count: int = 1, sides: int = 6) -> int:
        return sum(self.d(sides) for _ in range(count))

    def roll_expr(self, expr: str) -> int:
        count, sides, bonus = parse_expr(expr)
        return self.roll(count, sides) + bonus


class FixedDice(Dice):
    """Dés truqués pour les tests : renvoie les valeurs données, dans l'ordre."""

    def __init__(self, values: list[int]):
        super().__init__(0)
        self._values = list(values)

    def d(self, sides: int = 6) -> int:
        if not self._values:
            raise RuntimeError("FixedDice : plus de valeurs")
        return self._values.pop(0)
