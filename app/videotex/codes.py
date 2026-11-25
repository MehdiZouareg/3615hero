"""Constantes Vidéotex (Minitel, profil Télétel).

Valeurs reprises des constantes de MiniPaviCli.php, voir docs/minipavi-protocol.md.
"""
from __future__ import annotations

COLS = 40
ROWS = 24  # lignes 1 à 24 ; la ligne 0 est la ligne de statut

# -- déplacements et effacements ----------------------------------------------
LEFT = b"\x08"
RIGHT = b"\x09"
DOWN = b"\x0a"
UP = b"\x0b"
CLS = b"\x0c"        # efface les lignes 1 à 24, curseur en haut à gauche
CR = b"\x0d"
CLR_EOL = b"\x18"    # efface jusqu'à la fin de la ligne
REP = b"\x12"        # répète le caractère précédent : REP + (0x40 + n)
US = b"\x1f"         # positionnement : US + (0x40 + ligne) + (0x40 + colonne)
CUR_ON = b"\x11"
CUR_OFF = b"\x14"

# -- jeux de caractères -----------------------------------------------------------
G0 = b"\x0f"         # SI : texte
G1 = b"\x0e"         # SO : semi-graphique (mosaïques)
SS2 = b"\x19"        # le caractère suivant est pris dans G2 (accents, symboles)

# -- attributs (ESC + code) -------------------------------------------------------
ESC = b"\x1b"
BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)


def fg(color: int) -> bytes:
    return ESC + bytes([0x40 + color])


def bg(color: int) -> bytes:
    """Couleur de fond : attribut série, ne prend effet qu'au prochain espace."""
    return ESC + bytes([0x50 + color])


BLINK = ESC + b"H"
STEADY = ESC + b"I"
SIZE_NORMAL = ESC + b"L"
SIZE_DOUBLE_H = ESC + b"M"
SIZE_DOUBLE_W = ESC + b"N"
SIZE_DOUBLE = ESC + b"O"
UNDERLINE_OFF = ESC + b"Y"
UNDERLINE_ON = ESC + b"Z"
INVERSE_OFF = ESC + b"\\"
INVERSE_ON = ESC + b"]"

# -- G2 : accents (SS2 + accent + lettre) et symboles (SS2 + code) ------------------
ACCENT_GRAVE = 0x41
ACCENT_AIGU = 0x42
ACCENT_CIRCONFLEXE = 0x43
ACCENT_TREMA = 0x48
ACCENT_CEDILLE = 0x4B

# caractère Unicode -> octets Vidéotex
G2_ACCENTS: dict[str, bytes] = {}
for _accent, _letters in ((ACCENT_GRAVE, "àèìòù"), (ACCENT_AIGU, "áéíóú"),
                          (ACCENT_CIRCONFLEXE, "âêîôû"), (ACCENT_TREMA, "äëïöü")):
    for _c, _base in zip(_letters, "aeiou"):
        G2_ACCENTS[_c] = SS2 + bytes([_accent]) + _base.encode()
G2_ACCENTS["ç"] = SS2 + bytes([ACCENT_CEDILLE]) + b"c"

G2_SYMBOLS: dict[str, bytes] = {
    "£": SS2 + b"\x23", "§": SS2 + b"\x27", "←": SS2 + b"\x2c", "↑": SS2 + b"\x2d",
    "→": SS2 + b"\x2e", "↓": SS2 + b"\x2f", "°": SS2 + b"\x30", "±": SS2 + b"\x31",
    "÷": SS2 + b"\x38", "¼": SS2 + b"\x3c", "½": SS2 + b"\x3d", "¾": SS2 + b"\x3e",
    "Œ": SS2 + b"\x6a", "œ": SS2 + b"\x7a", "ß": SS2 + b"\x7b",
}

# En G0 Télétel, certains codes ASCII affichent un autre dessin : on ne les émet
# jamais tels quels depuis du texte. Clé : caractère Unicode voulu -> code G0.
G0_SPECIAL: dict[str, bytes] = {"─": b"\x60", "│": b"\x7c", "¯": b"\x7e"}
G0_FORBIDDEN = "`^~{}[]\\|"  # dessins nationaux ou ambigus : remplacés avant envoi

# -- touches : masque validwith de MiniPavi ---------------------------------------
MSK_SOMMAIRE = 1
MSK_RETOUR = 4
MSK_REPETITION = 8
MSK_GUIDE = 16
MSK_SUITE = 64
MSK_ENVOI = 128
MSK_AUTOSEND = 256


def pos(row: int, col: int = 1) -> bytes:
    """Place le curseur (ligne 0-24, colonne 1-40)."""
    if not (0 <= row <= ROWS and 1 <= col <= COLS):
        raise ValueError(f"position hors écran : ligne {row}, colonne {col}")
    return US + bytes([0x40 + row, 0x40 + col])


def repeat(char: bytes, n: int) -> bytes:
    """n fois le même caractère (1 <= n <= 64)."""
    if n <= 0:
        return b""
    if n <= 2:
        return char * n
    out = b""
    while n > 64:
        out += char + REP + bytes([0x40 + 63])
        n -= 64
    return out + (char + REP + bytes([0x40 + n - 1]) if n > 1 else char)
