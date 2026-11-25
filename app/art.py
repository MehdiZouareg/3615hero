"""Décor semi-graphique du service : bannière, frises, emblèmes.

Les dessins sont des listes de lignes de « pixels » ('#' allumé, '.' éteint),
au format attendu par videotex.render.mosaic : une case Minitel = 2 x 3 pixels.
Les plus grands sont construits par programme plutôt que tapés à la main.
"""
from __future__ import annotations

import math


def _canvas(w: int, h: int) -> list[list[bool]]:
    return [[False] * w for _ in range(h)]


def _art(c: list[list[bool]]) -> list[str]:
    return ["".join("#" if x else "." for x in row) for row in c]


def _rect(c, x0, y0, x1, y1, on=True):
    for y in range(max(0, y0), min(len(c), y1 + 1)):
        for x in range(max(0, x0), min(len(c[0]), x1 + 1)):
            c[y][x] = on


# -- bannière d'accueil : 80 x 15 pixels, soit 40 x 5 cases ------------------------
BANNER_W, BANNER_H = 80, 15


def _banner_layers() -> tuple[list[str], list[str], list[str]]:
    w, h = BANNER_W, BANNER_H
    # montagnes lointaines
    far = _canvas(w, h)
    for peak, height, slope in ((9, 9, 1.1), (24, 6, 1.4), (58, 8, 1.2), (73, 10, 1.0)):
        for x in range(w):
            top = h - 1 - int(max(0.0, height - abs(x - peak) / slope))
            if top < h - 1:
                _rect(far, x, top, x, h - 1)
    # château et colline au premier plan
    near = _canvas(w, h)
    for x in range(w):
        hill = 2 + int(1.6 * math.sin((x - 8) / 11.0) + 1.2 * math.sin(x / 5.0 + 1))
        _rect(near, x, h - max(1, hill), x, h - 1)
    _rect(near, 31, 7, 49, 13)                      # courtine
    for x in range(31, 50, 2):                      # créneaux de la courtine
        near[6][x] = True
    for x0, top in ((27, 4), (48, 4), (37, 1)):     # tours : gauche, droite, donjon
        width = 6 if x0 != 37 else 7
        _rect(near, x0, top + 1, x0 + width - 1, 13)
        for x in range(x0, x0 + width, 2):
            near[top][x] = True
    _rect(near, 39, 10, 41, 13, on=False)           # porte
    near[9][40] = False
    for x, y in ((29, 7), (30, 7), (50, 7), (51, 7), (40, 4), (40, 5)):   # meurtrières
        near[y][x] = False
    # ciel : croissant de lune et étoiles
    sky = _canvas(w, h)
    for y in range(h):
        for x in range(w):
            if (x - 66) ** 2 + (y - 3.5) ** 2 * 1.2 <= 10 and (x - 68) ** 2 + (y - 3) ** 2 * 1.2 > 8:
                sky[y][x] = True
    for x, y in ((4, 1), (13, 3), (20, 0), (33, 2), (46, 0), (55, 2), (61, 5), (76, 1), (71, 6), (2, 6)):
        sky[y][x] = True
    # un calque ne doit jamais partager une case avec un calque dessiné après lui
    def cut(under, over):
        for cy in range(0, h, 3):
            for cx in range(0, w, 2):
                if any(over[y][x] for y in range(cy, cy + 3) for x in (cx, cx + 1)):
                    _rect(under, cx, cy, cx + 1, cy + 2, on=False)
    cut(far, near)
    cut(sky, near)
    cut(sky, far)
    return _art(far), _art(near), _art(sky)


BANNER_FAR, BANNER_NEAR, BANNER_SKY = _banner_layers()


# -- épées croisées : 26 x 15 pixels ----------------------------------------------
def _swords() -> list[str]:
    w, h = 26, 15
    c = _canvas(w, h)
    for y in range(h - 3):                 # lames
        x = 2 + round(y * 1.75)
        for dx in (0, 1):
            c[y][x + dx] = True
            c[y][w - 1 - x - dx] = True
    for sign, cx in ((1, 21), (-1, 4)):    # gardes et pommeaux
        for d in range(-3, 4):
            x, y = cx + d, 11 - sign * round(d * 0.6)
            if 0 <= x < w and 0 <= y < h:
                c[y][x] = True
        px = cx + sign * 2
        _rect(c, px, 13, px + 1, 14)
    return _art(c)


SWORDS = _swords()

SKULL = [
    "...##########...",
    ".##############.",
    "################",
    "###..######..###",
    "###..######..###",
    "################",
    "######.##.######",
    ".##############.",
    "..##.##..##.##..",
    "..##.##..##.##..",
    "....########....",
    "................",
]

CROWN = [
    "..#......##......#..",
    ".###....####....###.",
    "..#......##......#..",
    "..##....####....##..",
    "..###..######..###..",
    "..################..",
    "..################..",
    "..##.##.####.##.##..",
    "..################..",
    "..################..",
    "....................",
    "....................",
]

# -- frises : motifs de 3 pixels de haut, répétés sur la largeur --------------------
FRIEZE_DIAMOND = ["..#...", ".###..", "..#..."]      # losanges
FRIEZE_CHAIN = ["##..", "..##", "##.."]              # maillons
FRIEZE_WAVE = ["#...", ".#.#", "..#."]               # vague
FRIEZE_TEETH = ["####", "#..#", "...."]              # créneaux
