#!/usr/bin/env python3
"""Validateur d'arborescence d'un livre-jeu.

    python tools/validate_book.py books/demo-la-tour [--strict]

Code retour : 0 si le livre est sain, 1 s'il y a des erreurs (ou des
avertissements avec --strict), 2 si le fichier est illisible.

Méthode : en plus des contrôles statiques, le validateur explore tous les états
abstraits (paragraphe, inventaire, flags) atteignables depuis le départ. Les
stats sont ignorées : un test, un combat ou une condition sur une stat sont
supposés pouvoir tourner dans les deux sens.
"""
from __future__ import annotations

import argparse
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.engine import COMBAT_SYSTEMS  # noqa: E402
from app.engine.models import Book, Choice, load_book  # noqa: E402

MAX_STATES = 200_000
MORT = -1  # nœud virtuel : mort en combat sans paragraphe de défaite

State = tuple[int, frozenset, frozenset]  # (paragraphe, inventaire, flags)


@dataclass(frozen=True)
class Issue:
    level: str  # "erreur" | "attention"
    code: str
    paragraphe: int | None
    message: str

    def __str__(self) -> str:
        where = f"§{self.paragraphe}" if self.paragraphe is not None else "livre"
        return f"{self.level.upper():<9} {where:<6} {self.message}"


def _fmt(pids) -> str:
    return ", ".join(f"§{p}" for p in sorted(pids))


def _enter(book: Book, pid: int, inv: frozenset, flags: frozenset) -> State:
    inv, flags = set(inv), set(flags)
    for e in book.paragraphes[pid].effets:
        if e.gagne is not None:
            inv.add(e.gagne)
        elif e.perd is not None:
            inv.discard(e.perd)
        elif e.pose_flag is not None:
            flags.add(e.pose_flag)
        elif e.retire_flag is not None:
            flags.discard(e.retire_flag)
    return pid, frozenset(inv), frozenset(flags)


def _choice_possible(choice: Choice, inv: frozenset, flags: frozenset) -> bool:
    """Conditions d'objets et de flags ; celles sur les stats sont supposées vraies."""
    for c in choice.si:
        if c.objet is not None and c.objet not in inv:
            return False
        if c.sans_objet is not None and c.sans_objet in inv:
            return False
        if c.flag is not None and c.flag not in flags:
            return False
        if c.sans_flag is not None and c.sans_flag in flags:
            return False
    return True


def validate(book: Book) -> list[Issue]:
    issues: list[Issue] = []
    paras = book.paragraphes

    def err(code, pid, msg):
        issues.append(Issue("erreur", code, pid, msg))

    def warn(code, pid, msg):
        issues.append(Issue("attention", code, pid, msg))

    stats = set(book.personnage.stats)
    if book.systeme_combat not in COMBAT_SYSTEMS:
        err("combat-inconnu", None, f"système de combat inconnu : {book.systeme_combat!r}")

    # ---- contrôles statiques ------------------------------------------------
    gained = set(book.personnage.inventaire)
    flags_set: set[str] = set()
    for p in paras.values():
        gained |= {e.gagne for e in p.effets if e.gagne is not None}
        flags_set |= {e.pose_flag for e in p.effets if e.pose_flag is not None}

    for pid, p in sorted(paras.items()):
        for dest in sorted(set(p.destinations())):
            if dest not in paras:
                err("destination", pid, f"renvoie au §{dest}, qui n'existe pas")
        if not p.destinations() and p.fin is None:
            err("cul-de-sac", pid, "aucun choix, test ou combat, et ce n'est pas une fin")
        used = [e.stat for e in p.effets if e.stat is not None]
        used += [c.stat for ch in p.choix for c in ch.si if c.stat is not None]
        if p.test is not None:
            used.append(p.test.stat)
        for s in sorted(set(used) - stats):
            err("stat-inconnue", pid, f"stat {s!r} absente de la création du personnage")
        if p.combat is not None and "habilete" not in stats and book.systeme_combat == "defis_fantastiques":
            err("stat-inconnue", pid, "combat Défis Fantastiques sans stat 'habilete'")
        if p.choix and all(any(c.stat is not None for c in ch.si) for ch in p.choix):
            warn("choix-stats", pid, "tous les choix dépendent d'une stat : impasse possible")

    for flag in sorted(set(book.flags_visibles) - flags_set):
        warn("flag-visible", None, f"flag visible {flag!r} jamais posé")

    # ---- atteignabilité structurelle (sans tenir compte des conditions) ------
    reach = {book.depart}
    todo = deque([book.depart])
    while todo:
        for dest in paras[todo.popleft()].destinations():
            if dest in paras and dest not in reach:
                reach.add(dest)
                todo.append(dest)
    for pid in sorted(set(paras) - reach):
        err("inatteignable", pid, "aucun chemin n'y mène depuis le départ")

    # ---- exploration des états ------------------------------------------------
    start = _enter(book, book.depart, frozenset(book.personnage.inventaire), frozenset())
    succ: dict[State, set] = {}
    enabled: set[tuple[int, int]] = set()  # (paragraphe, indice de choix) déjà proposé
    todo = deque([start])
    truncated = False
    while todo:
        state = todo.popleft()
        if state in succ:
            continue
        if len(succ) >= MAX_STATES:
            truncated = True
            break
        pid, inv, flags = state
        p = paras[pid]
        dests: list[int] = []
        nexts: set = set()
        if p.fin is None:
            for i, ch in enumerate(p.choix):
                if _choice_possible(ch, inv, flags):
                    enabled.add((pid, i))
                    dests.append(ch.vers)
            if p.test is not None:
                dests += [p.test.reussite, p.test.echec]
            if p.combat is not None:
                dests.append(p.combat.victoire)
                if p.combat.defaite is None:
                    nexts.add(MORT)
                else:
                    dests.append(p.combat.defaite)
                if p.combat.fuite is not None:
                    dests.append(p.combat.fuite)
        for dest in dests:
            if dest in paras:
                nxt = _enter(book, dest, inv, flags)
                nexts.add(nxt)
                todo.append(nxt)
        succ[state] = nexts

    if truncated:
        warn("exploration", None,
             f"plus de {MAX_STATES} états : analyse des conditions et des boucles incomplète")

    visited = {s[0] for s in succ}
    for pid in sorted(reach - visited):
        if not truncated:
            err("inatteignable", pid, "inatteignable compte tenu des objets et flags requis en amont")

    # choix dont la condition n'est jamais remplie en arrivant au paragraphe
    for pid in sorted(visited):
        for i, ch in enumerate(paras[pid].choix):
            if (pid, i) in enabled or truncated:
                continue
            why = []
            for c in ch.si:
                if c.objet is not None and c.objet not in gained:
                    why.append(f"l'objet {c.objet!r} n'est donné nulle part")
                elif c.flag is not None and c.flag not in flags_set:
                    why.append(f"le flag {c.flag!r} n'est posé nulle part")
            reason = " ; ".join(why) or "condition jamais remplie sur aucun chemin menant ici"
            err("condition", pid, f"choix « {ch.libelle} » impossible : {reason}")

    # états d'où plus aucune fin n'est atteignable
    ends = {s for s in succ if paras[s[0]].fin is not None}
    pred: dict = {}
    for s, nexts in succ.items():
        for n in nexts:
            pred.setdefault(n, set()).add(s)
    good = set(ends) | {MORT}
    todo = deque(good)
    while todo:
        for s in pred.get(todo.popleft(), ()):
            if s not in good:
                good.add(s)
                todo.append(s)
    bad = [s for s in succ if s not in good] if not truncated else []
    impasses = sorted({s[0] for s in bad if not succ[s] and paras[s[0]].destinations()})
    for pid in impasses:
        ex = next(s for s in bad if s[0] == pid and not succ[s])
        inv = ", ".join(sorted(ex[1])) or "rien"
        err("impasse", pid, f"aucun choix disponible si l'on arrive avec : {inv}")
    loop = {s[0] for s in bad if succ[s]}
    if loop:
        err("boucle", min(loop), f"boucle sans issue : une fois dans {_fmt(loop)}, plus aucune fin n'est atteignable")

    if not any(paras[s[0]].fin == "victoire" for s in ends):
        err("victoire", None, "aucune fin victorieuse atteignable")
    if not any(p.fin == "mort" for p in paras.values()):
        warn("sans-mort", None, "aucun paragraphe de mort")

    return sorted(set(issues), key=lambda i: (i.level != "erreur", i.paragraphe or 0, i.code, i.message))


def report(book: Book, issues: list[Issue], strict: bool = False) -> tuple[str, int]:
    errors = [i for i in issues if i.level == "erreur"]
    warnings = [i for i in issues if i.level == "attention"]
    fins = sum(1 for p in book.paragraphes.values() if p.fin)
    lines = [f"{book.titre} : {len(book.paragraphes)} paragraphes, {fins} fins"]
    lines += [str(i) for i in issues]
    failed = bool(errors) or (strict and bool(warnings))
    lines.append(f"{'ÉCHEC' if failed else 'OK'} : {len(errors)} erreur(s), {len(warnings)} avertissement(s)")
    return "\n".join(lines), 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("livre", help="dossier du livre ou chemin du book.yaml")
    ap.add_argument("--strict", action="store_true", help="les avertissements font échouer")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        book = load_book(args.livre)
    except Exception as exc:
        print(f"ERREUR    livre  illisible ou mal formé : {exc}", file=sys.stderr)
        return 2
    text, code = report(book, validate(book), args.strict)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
