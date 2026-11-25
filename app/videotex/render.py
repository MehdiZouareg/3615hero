"""Mise en page Vidéotex 40 x 24 : texte, accents, pagination, cadres, mosaïques.

Deux niveaux :
- des fonctions pures sur du texte (normalize, wrap, paginate, encode_text) ;
- Page, qui compose un écran et produit les octets à envoyer. Page tient aussi
  une grille de caractères (aperçu texte) et refuse tout débordement.
"""
from __future__ import annotations

import re
import textwrap
import unicodedata

from . import codes as C

# Caractères typographiques sans équivalent Minitel -> remplacement
_REPLACE = {
    "’": "'", "‘": "'", "“": '"', "”": '"', "«": '"', "»": '"',
    "…": "...", "—": "-", "–": "-", "−": "-", " ": " ", " ": " ",
    " ": " ", "\t": " ", "æ": "ae", "Æ": "AE", "`": "'", "^": " ", "~": "-",
    "{": "(", "}": ")", "[": "(", "]": ")", "\\": "/", "|": "/",
}
_DIRECT = set(C.G2_ACCENTS) | set(C.G2_SYMBOLS)


def normalize(text: str) -> str:
    """Ramène un texte au répertoire affichable ; 1 caractère = 1 case d'écran.

    Les majuscules accentuées perdent leur accent (affichage non garanti sur
    Minitel 1), les caractères inconnus deviennent '?'.
    """
    # guillemets français : on colle le guillemet droit au mot, comme en ASCII
    text = re.sub("«[   ]", "«", text)
    text = re.sub("[   ]»", "»", text)
    out: list[str] = []
    for ch in unicodedata.normalize("NFC", text):
        if ch in _REPLACE:
            out.append(_REPLACE[ch])
        elif ch in _DIRECT or (" " <= ch <= "}" and ch not in C.G0_FORBIDDEN):
            out.append(ch)
        elif ch == "\n":
            out.append(ch)
        else:
            base = unicodedata.normalize("NFD", ch)[0]
            if base in _REPLACE:
                base = _REPLACE[base]
            out.append(base if base.isascii() and base.isprintable() and base not in C.G0_FORBIDDEN else "?")
    return "".join(out)


def encode_text(text: str) -> bytes:
    """Texte déjà normalisé (ou non) -> octets Vidéotex 7 bits, sans attribut."""
    out = bytearray()
    for ch in normalize(text).replace("\n", " "):
        out += C.G2_ACCENTS.get(ch) or C.G2_SYMBOLS.get(ch) or ch.encode("ascii")
    return bytes(out)


def wrap(text: str, width: int = C.COLS) -> list[str]:
    """Coupe un texte en lignes d'au plus `width` cases. Les sauts de ligne du
    texte séparent des alinéas, rendus par une ligne vide."""
    lines: list[str] = []
    for i, para in enumerate(normalize(text).strip("\n").split("\n")):
        para = " ".join(para.split())
        if i and lines and lines[-1] != "":
            lines.append("")
        if para:
            # ponctuation haute : jamais de retour à la ligne avant « : ; ! ? »
            para = re.sub(r" (?=[:;!?])", "", para)
            lines += [l.replace("", " ") for l in
                      textwrap.wrap(para, width, break_long_words=True, break_on_hyphens=False)]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def paginate(lines: list[str], height: int, first_height: int | None = None) -> list[list[str]]:
    """Répartit des lignes en pages. `first_height` : hauteur de la première page
    si elle diffère (illustration). Aucune page ne commence ni ne finit par une
    ligne vide ; il y a toujours au moins une page."""
    if height < 1:
        raise ValueError("hauteur de page nulle")
    pages: list[list[str]] = []
    cur: list[str] = []
    limit = first_height if first_height is not None else height
    for line in lines:
        if line == "" and not cur:
            continue
        if len(cur) >= max(limit, 1):
            while cur and cur[-1] == "":
                cur.pop()
            pages.append(cur)
            cur, limit = [], height
            if line == "":
                continue
        cur.append(line)
    while cur and cur[-1] == "":
        cur.pop()
    if cur or not pages:
        pages.append(cur)
    return pages


# --------------------------------------------------------------------------
# Semi-graphique
# --------------------------------------------------------------------------

def mosaic(art: list[str]) -> list[bytes]:
    """Dessin en « pixels » -> lignes de codes G1.

    `art` : lignes de texte où tout caractère autre que l'espace et le point est
    un pixel allumé. Une case Minitel fait 2 pixels de large sur 3 de haut ; le
    dessin est complété à droite et en bas.
    Code d'une case : 0x20 + 1 (haut gauche) + 2 (haut droite) + 4 (milieu
    gauche) + 8 (milieu droite) + 16 (bas gauche) + 64 (bas droite).
    """
    if not art:
        return []
    w = max(len(l) for l in art)
    w += w % 2
    rows = [l.ljust(w) for l in art]
    while len(rows) % 3:
        rows.append(" " * w)
    if w // 2 > C.COLS:
        raise ValueError(f"illustration trop large : {w} pixels (80 au plus)")
    on = lambda r, c: rows[r][c] not in " ."
    out = []
    for r in range(0, len(rows), 3):
        line = bytearray()
        for c in range(0, w, 2):
            code = 0x20
            for bit, (dr, dc) in zip((1, 2, 4, 8, 16, 64), ((0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1))):
                if on(r + dr, c + dc):
                    code |= bit
            line.append(code)
        out.append(bytes(line))
    return out


# --------------------------------------------------------------------------
# Composition d'un écran
# --------------------------------------------------------------------------

class Page:
    """Un écran en cours de composition."""

    def __init__(self, clear: bool = True):
        self.buf = bytearray()
        self.grid = [[" "] * C.COLS for _ in range(C.ROWS + 1)]  # grid[ligne][colonne-1]
        if clear:
            # ligne 0 à part : l'effacement de page ne la touche pas
            self.buf += C.pos(0, 1) + C.CLR_EOL + C.pos(1, 1) + C.CLS + C.CUR_OFF

    # -- sorties ----------------------------------------------------------

    def data(self) -> bytes:
        return bytes(self.buf)

    def preview(self) -> list[str]:
        """Aperçu texte de l'écran, lignes 0 à 24, sans les attributs."""
        return ["".join(row).rstrip() for row in self.grid]

    # -- écriture ---------------------------------------------------------

    def text(self, row: int, col: int, text: str, *, color: int | None = None,
             inverse: bool = False, blink: bool = False, underline: bool = False,
             double_height: bool = False, double_width: bool = False) -> "Page":
        text = normalize(text).replace("\n", " ")
        if not text:
            return self
        cell = 2 if double_width else 1
        if not 1 <= row <= C.ROWS:
            raise ValueError(f"ligne {row} hors écran (la ligne 0 passe par line0)")
        if col < 1 or col + len(text) * cell - 1 > C.COLS:
            raise ValueError(f"débordement ligne {row} : {len(text) * cell} cases en colonne {col}")
        if double_height and row < 2:
            raise ValueError("la double hauteur occupe aussi la ligne du dessus")
        on, off = bytearray(), bytearray()
        if color is not None and color != C.WHITE:
            on += C.fg(color); off += C.fg(C.WHITE)
        if blink:
            on += C.BLINK; off += C.STEADY
        if inverse:
            on += C.INVERSE_ON; off += C.INVERSE_OFF
        if underline:  # attribut série : validé par un espace, qui occupe une case
            raise ValueError("soulignement non géré : utiliser hline")
        if double_height or double_width:
            on += (C.SIZE_DOUBLE if double_height and double_width
                   else C.SIZE_DOUBLE_H if double_height else C.SIZE_DOUBLE_W)
            off += C.SIZE_NORMAL
        self.buf += C.pos(row, col) + on + encode_text(text) + off
        for i, ch in enumerate(text):
            for k in range(cell):
                self.grid[row][col - 1 + i * cell + k] = ch
                if double_height:
                    self.grid[row - 1][col - 1 + i * cell + k] = ch
        return self

    def center(self, row: int, text: str, **attrs) -> "Page":
        text = normalize(text)
        width = len(text) * (2 if attrs.get("double_width") else 1)
        return self.text(row, max(1, (C.COLS - width) // 2 + 1), text, **attrs)

    def bar(self, row: int, text: str = "", color: int = C.WHITE) -> "Page":
        """Bandeau pleine largeur en vidéo inverse, texte centré."""
        return self.text(row, 1, normalize(text)[:C.COLS].center(C.COLS), color=color, inverse=True)

    def hline(self, row: int, col: int = 1, width: int = C.COLS, color: int | None = None,
              char: str = "─") -> "Page":
        if col < 1 or col + width - 1 > C.COLS or not 1 <= row <= C.ROWS:
            raise ValueError("filet hors écran")
        self.buf += C.pos(row, col)
        if color is not None and color != C.WHITE:
            self.buf += C.fg(color)
        self.buf += C.repeat(C.G0_SPECIAL.get(char) or encode_text(char), width)
        if color is not None and color != C.WHITE:
            self.buf += C.fg(C.WHITE)
        self.grid[row][col - 1:col - 1 + width] = ["-" if char == "─" else char] * width
        return self

    def frame(self, top: int, left: int, height: int, width: int, color: int | None = None) -> "Page":
        """Cadre : filets en haut et en bas, barres sur les côtés. L'intérieur
        fait (height - 2) lignes sur (width - 2) colonnes."""
        if height < 3 or width < 3:
            raise ValueError("cadre trop petit")
        self.hline(top, left + 1, width - 2, color, char="_")
        for r in range(top + 1, top + height - 1):
            for c in (left, left + width - 1):
                self.buf += C.pos(r, c)
                if color is not None and color != C.WHITE:
                    self.buf += C.fg(color)
                self.buf += C.G0_SPECIAL["│"]
                if color is not None and color != C.WHITE:
                    self.buf += C.fg(C.WHITE)
                self.grid[r][c - 1] = "|"
        self.hline(top + height - 1, left + 1, width - 2, color, char="¯")
        return self

    def lines(self, top: int, lines: list[str], col: int = 1, **attrs) -> "Page":
        for i, line in enumerate(lines):
            self.text(top + i, col, line, **attrs)
        return self

    def art(self, top: int, art: list[str], color: int | None = None, col: int | None = None) -> "Page":
        """Illustration semi-graphique, centrée par défaut. Renvoie la page ;
        la hauteur occupée est len(mosaic(art))."""
        rows = mosaic(art)
        if not rows:
            return self
        width = len(rows[0])
        col = col or (C.COLS - width) // 2 + 1
        if top < 1 or top + len(rows) - 1 > C.ROWS or col + width - 1 > C.COLS:
            raise ValueError("illustration hors écran")
        for i, codes in enumerate(rows):
            self._mosaic_row(top + i, col, codes, color)
        return self

    def _mosaic_row(self, row: int, col: int, codes: bytes, color: int | None) -> None:
        """Écrit une ligne de codes G1. Les cases vides (0x20) sont sautées : on
        peut ainsi superposer plusieurs dessins de couleurs différentes."""
        colored = color is not None and color != C.WHITE
        k = 0
        while k < len(codes):
            if codes[k] == 0x20:
                k += 1
                continue
            j = k
            while j < len(codes) and codes[j] != 0x20:
                j += 1
            self.buf += C.pos(row, col + k) + C.G1 + (C.fg(color) if colored else b"")
            run = k
            while run < j:  # compression des répétitions
                n = 1
                while run + n < j and codes[run + n] == codes[run]:
                    n += 1
                self.buf += C.repeat(codes[run:run + 1], n)
                run += n
            self.buf += (C.fg(C.WHITE) if colored else b"") + C.G0
            for c in range(k, j):
                self.grid[row][col - 1 + c] = "#"
            k = j

    def frieze(self, row: int, tile: list[str], color: int | None = None,
               col: int = 1, width: int = C.COLS) -> "Page":
        """Frise ornementale : un motif en pixels (3 de haut) répété sur la largeur."""
        if not 1 <= row <= C.ROWS or col < 1 or col + width - 1 > C.COLS:
            raise ValueError("frise hors écran")
        tile = (list(tile) + ["", "", ""])[:3]
        tw = max(len(l) for l in tile) or 1
        count = width * 2 // tw  # motifs entiers seulement, centrés
        margin = (width * 2 - count * tw) // 2
        lines = [" " * margin + l.ljust(tw) * count for l in tile]
        self._mosaic_row(row, col, mosaic(lines)[0], color)
        return self

    def gauge(self, row: int, col: int, width: int, value: int, maximum: int,
              color: int | None = None) -> "Page":
        """Jauge horizontale de `width` cases, précise à la demi-case."""
        if not 1 <= row <= C.ROWS or col < 1 or col + width - 1 > C.COLS or width < 1:
            raise ValueError("jauge hors écran")
        half = 0 if maximum <= 0 else max(0, min(width * 2, round(value * width * 2 / maximum)))
        if value > 0 and half == 0:
            half = 1  # tant qu'il reste un point, la jauge n'est pas vide
        full, rest = divmod(half, 2)
        # plein : milieu + bas des deux colonnes ; demi : colonne gauche ; vide : filet du bas
        codes = bytes([0x7C] * full + [0x74] * rest + [0x70] * (width - full - rest))
        self._mosaic_row(row, col, codes, color)
        return self

    def line0(self, text: str, blink: bool = False) -> "Page":
        """Message en ligne de statut ; le curseur revient ensuite où il était."""
        text = normalize(text)[:C.COLS - 1]
        self.buf += C.pos(0, 1) + (C.BLINK if blink else b"") + encode_text(text)
        self.buf += (C.STEADY if blink else b"") + C.CLR_EOL + C.DOWN
        self.grid[0] = list(text.ljust(C.COLS))
        return self

    def keys(self, row: int, items: list[tuple[str, str]], color: int = C.GREEN) -> "Page":
        """Rappel des touches, aligné à droite : [("Suite", "SUITE"), ...] donne
        « Suite [SUITE] » avec le nom de la touche en vidéo inverse."""
        total = sum(len(normalize(l)) + len(k) + (3 if l else 2) for l, k in items) + len(items) - 1
        col = C.COLS - total + 1
        if col < 1:
            raise ValueError("rappel de touches trop long")
        for label, key in items:
            label = normalize(label)
            if label:
                self.text(row, col, label, color=color)
                col += len(label) + 1
            self.text(row, col, f" {key} ", color=color, inverse=True)
            col += len(key) + 3
        return self
