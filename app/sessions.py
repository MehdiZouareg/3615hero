"""Persistance SQLite : connexions en cours et parties sauvegardées.

- `connexions` : l'état d'écran d'un Minitel connecté, indexé par l'uniqueId
  que fournit la passerelle. Effacé à la déconnexion ou après 24 h.
- `parties` : une partie par couple (pseudo, code à 4 chiffres). C'est ce
  couple que le joueur retape pour reprendre.
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS connexions (
    unique_id TEXT PRIMARY KEY,
    etat      TEXT NOT NULL,
    maj       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS parties (
    pseudo TEXT NOT NULL,
    code   TEXT NOT NULL,
    livre  TEXT NOT NULL,
    etat   TEXT NOT NULL,
    cree   REAL NOT NULL,
    maj    REAL NOT NULL,
    PRIMARY KEY (pseudo, code)
);
"""

PSEUDO_MIN, PSEUDO_MAX = 2, 10
STALE_SECONDS = 24 * 3600


def clean_pseudo(raw: str) -> str | None:
    """Pseudo normalisé (majuscules, lettres et chiffres) ou None s'il est invalide."""
    pseudo = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    return pseudo if PSEUDO_MIN <= len(pseudo) <= PSEUDO_MAX else None


def clean_code(raw: str) -> str | None:
    code = (raw or "").strip()
    return code if re.fullmatch(r"\d{4}", code) else None


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # -- connexions ---------------------------------------------------------

    def get_connection(self, unique_id: str) -> dict | None:
        row = self.db.execute("SELECT etat FROM connexions WHERE unique_id = ?", (unique_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_connection(self, unique_id: str, etat: dict) -> None:
        self.db.execute(
            "INSERT INTO connexions (unique_id, etat, maj) VALUES (?, ?, ?) "
            "ON CONFLICT(unique_id) DO UPDATE SET etat = excluded.etat, maj = excluded.maj",
            (unique_id, json.dumps(etat, ensure_ascii=False), time.time()))

    def drop_connection(self, unique_id: str) -> None:
        self.db.execute("DELETE FROM connexions WHERE unique_id = ?", (unique_id,))

    def purge_connections(self, max_age: float = STALE_SECONDS) -> int:
        cur = self.db.execute("DELETE FROM connexions WHERE maj < ?", (time.time() - max_age,))
        return cur.rowcount

    # -- parties ------------------------------------------------------------

    def new_code(self, pseudo: str) -> str:
        """Code à 4 chiffres encore libre pour ce pseudo."""
        used = {r[0] for r in self.db.execute("SELECT code FROM parties WHERE pseudo = ?", (pseudo,))}
        if len(used) >= 9000:
            raise RuntimeError("plus de code disponible pour ce pseudo")
        while True:
            code = f"{secrets.randbelow(10000):04d}"
            if code not in used:
                return code

    def save_game(self, pseudo: str, code: str, livre: str, etat: dict) -> None:
        now = time.time()
        self.db.execute(
            "INSERT INTO parties (pseudo, code, livre, etat, cree, maj) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(pseudo, code) DO UPDATE SET livre = excluded.livre, etat = excluded.etat, "
            "maj = excluded.maj",
            (pseudo, code, livre, json.dumps(etat, ensure_ascii=False), now, now))

    def load_game(self, pseudo: str, code: str) -> tuple[str, dict] | None:
        row = self.db.execute("SELECT livre, etat FROM parties WHERE pseudo = ? AND code = ?",
                              (pseudo, code)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def delete_game(self, pseudo: str, code: str) -> None:
        self.db.execute("DELETE FROM parties WHERE pseudo = ? AND code = ?", (pseudo, code))

    def count_games(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM parties").fetchone()[0]
