"""Mini-interpréteur Vidéotex pour les tests.

Rejoue un flux d'octets sur une grille 25 x 40 et lève VdtError au moindre
débordement ou octet inattendu. Sert de contrôle indépendant de Page.preview().
"""
from __future__ import annotations

from app.videotex import codes as C

_ACCENTS = {v: k for k, v in C.G2_ACCENTS.items()}
_SYMBOLS = {v: k for k, v in C.G2_SYMBOLS.items()}
_G0 = {0x60: "-", 0x7C: "|", 0x7E: "¯"}


class VdtError(AssertionError):
    pass


def decode(data: bytes) -> list[str]:
    grid = [[" "] * 40 for _ in range(25)]
    row, col, saved = 1, 1, None
    g1 = False
    cw = ch = 1  # largeur / hauteur de caractère
    last = None
    i = 0

    def put(char: str):
        nonlocal col, last
        if g1 and (cw, ch) != (1, 1):
            raise VdtError("taille double en semi-graphique")
        if not (0 <= row <= 24) or col < 1 or col + cw - 1 > 40:
            raise VdtError(f"débordement ligne {row} colonne {col}")
        if ch == 2 and row < 2:
            raise VdtError("double hauteur en ligne 0 ou 1")
        for k in range(cw):
            grid[row][col - 1 + k] = char
            if ch == 2:
                grid[row - 1][col - 1 + k] = char
        col += cw
        last = char

    while i < len(data):
        b = data[i]
        if b >= 0x80:
            raise VdtError(f"octet 8 bits {b:#x}")
        if b == 0x1F:
            r, c = data[i + 1] - 0x40, data[i + 2] - 0x40
            if not (0 <= r <= 24 and 1 <= c <= 40):
                raise VdtError(f"positionnement invalide {r},{c}")
            if r == 0 and row != 0:
                saved = (row, col)
            row, col, g1, cw, ch = r, c, False, 1, 1
            i += 3
        elif b == 0x1B:
            a = data[i + 1]
            if a in (0x4C, 0x4D, 0x4E, 0x4F):
                cw, ch = {0x4C: (1, 1), 0x4D: (1, 2), 0x4E: (2, 1), 0x4F: (2, 2)}[a]
            elif not (0x40 <= a <= 0x5F):
                raise VdtError(f"séquence ESC inconnue {a:#x}")
            i += 2
        elif b == 0x19:
            if 0x41 <= data[i + 1] <= 0x4F:
                seq = data[i:i + 3]
                if seq not in _ACCENTS:
                    raise VdtError(f"accent inconnu {seq!r}")
                put(_ACCENTS[seq]); i += 3
            else:
                seq = data[i:i + 2]
                if seq not in _SYMBOLS:
                    raise VdtError(f"symbole G2 inconnu {seq!r}")
                put(_SYMBOLS[seq]); i += 2
        elif b == 0x12:
            n = data[i + 1] - 0x40
            if last is None or not 1 <= n <= 63:
                raise VdtError("répétition invalide")
            for _ in range(n):
                put(last)
            i += 2
        elif b == 0x0C:
            for r in range(1, 25):
                grid[r] = [" "] * 40
            row, col, g1, cw, ch = 1, 1, False, 1, 1
            i += 1
        elif b == 0x18:
            grid[row][col - 1:] = [" "] * (41 - col)
            i += 1
        elif b == 0x0A:
            if row == 0:
                if saved is None:
                    raise VdtError("retour de ligne 0 sans position mémorisée")
                row, col = saved
            else:
                row += 1
            i += 1
        elif b in (0x0E, 0x0F):
            g1 = b == 0x0E
            i += 1
        elif b in (0x11, 0x14):
            i += 1
        elif 0x20 <= b <= 0x7F:
            if g1:
                put(" " if b == 0x20 else "#")
            else:
                put(_G0.get(b, chr(b)))
            i += 1
        else:
            raise VdtError(f"octet de contrôle inattendu {b:#x}")
    return ["".join(r).rstrip() for r in grid]
