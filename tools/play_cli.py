#!/usr/bin/env python3
"""Jouer un livre en console, sans Minitel.

    python tools/play_cli.py books/demo-la-tour [--seed 42] [--nom Zoltan]

À chaque étape : tapez le numéro d'une action, F pour la feuille d'aventure,
R pour les règles, Q pour quitter.
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.dice import Dice  # noqa: E402
from app.engine.engine import Engine  # noqa: E402
from app.engine.models import Book, GameState, load_book  # noqa: E402

WIDTH = 72


def wrap(text: str) -> str:
    return "\n".join(textwrap.fill(p, WIDTH) for p in text.strip().splitlines())


def sheet(book: Book, state: GameState) -> str:
    p = state.perso
    lines = [f"--- {p.nom} ---"]
    lines += [f"  {k.upper():<10} {v:>2} / {p.initial[k]}" for k, v in p.stats.items()]
    lines.append("  Inventaire : " + (", ".join(p.inventaire) or "rien"))
    notes = [label for flag, label in book.flags_visibles.items() if flag in p.flags]
    lines += [f"  * {n}" for n in notes]
    return "\n".join(lines)


def play(book: Book, seed: int | None, nom: str, inp=input, out=print) -> str | None:
    """Boucle de jeu. Renvoie 'victoire', 'mort', ou None si le joueur quitte."""
    engine = Engine(book, Dice(seed))
    state, events = engine.new_game(nom)
    out(f"=== {book.titre} ===")
    if book.resume:
        out(wrap(book.resume))
    out(sheet(book, state))
    shown = None
    while True:
        if shown != state.paragraphe:
            para = engine.paragraph(state)
            out(f"\n[{state.paragraphe}]")
            for line in para.illustration or []:
                out(line)
            out(wrap(para.texte))
            shown = state.paragraphe
        for e in events:
            out(f"  > {e}")
        events = []
        if state.fin:
            out("\n*** VICTOIRE ***" if state.fin == "victoire" else "\n*** VOTRE AVENTURE S'ACHÈVE ICI ***")
            return state.fin
        if state.ennemi:
            vie = book.personnage.stat_vie
            out(f"  {state.ennemi.nom} : habileté {state.ennemi.habilete}, endurance "
                f"{state.ennemi.endurance}  |  vous : endurance {state.perso.stats[vie]}")
        actions = engine.actions(state)
        if not actions:
            out("(aucune action possible : le livre a un cul-de-sac ici)")
            return None
        for i, a in enumerate(actions, 1):
            out(f"  {i}. {a.libelle}")
        try:
            answer = inp("> ").strip().lower()
        except EOFError:
            return None
        if answer == "q":
            return None
        if answer == "f":
            out(sheet(book, state))
            continue
        if answer == "r":
            out(wrap(book.regles or "Ce livre n'a pas de règles particulières."))
            continue
        if not answer.isdigit() or not 1 <= int(answer) <= len(actions):
            out("Choix incorrect.")
            continue
        events = engine.act(state, actions[int(answer) - 1])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("livre", help="dossier du livre ou chemin du book.yaml")
    ap.add_argument("--seed", type=int, default=None, help="graine des dés (parties reproductibles)")
    ap.add_argument("--nom", default="Aventurier")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stdin):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        book = load_book(args.livre)
    except Exception as exc:  # livre illisible : message clair plutôt qu'une trace
        print(f"Livre invalide : {exc}", file=sys.stderr)
        return 2
    return 0 if play(book, args.seed, args.nom) else 1


if __name__ == "__main__":
    sys.exit(main())
