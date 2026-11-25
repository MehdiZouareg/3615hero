"""Le livre de démo : il passe le validateur, exerce toutes les mécaniques, et se finit."""
from pathlib import Path

import pytest

from app.engine.dice import Dice
from app.engine.engine import Engine
from app.engine.models import load_book
from tools.play_cli import play
from tools.validate_book import main as validate_main
from tools.validate_book import validate

DEMO = Path(__file__).parent.parent / "books" / "demo-la-tour"

# Stratégie « bon joueur » : la première action de cette liste qui est proposée.
SAGE = ["Descendre par la brèche", "Fouiller les niches", "Ouvrir la porte avec la clé d'argent",
        "Libérer le corbeau", "Jeter le sel sur le battant", "Briser le battant de la cloche",
        "Combattre", "Tenter votre chance", "Franchir le vide", "Prendre l'escalier",
        "Reprendre l'escalier", "Fuir par l'escalier", "Continuer à monter",
        "Reprendre votre souffle et monter", "Monter l'escalier"]


@pytest.fixture(scope="module")
def book():
    return load_book(DEMO)


def test_passe_le_validateur_sans_avertissement(book):
    assert validate(book) == []
    assert validate_main([str(DEMO), "--strict"]) == 0


def test_exerce_toutes_les_mecaniques(book):
    paras = book.paragraphes.values()
    assert 20 <= len(book.paragraphes) <= 30
    assert sum(p.combat is not None for p in paras) >= 2
    assert any(p.combat and p.combat.fuite is not None for p in paras)
    assert any(p.test and p.test.stat == "chance" for p in paras)
    assert sum(p.fin == "victoire" for p in paras) == 2
    assert any(p.fin == "mort" for p in paras)
    # un objet clé obtenu à un endroit et exigé plus loin
    donnes = {e.gagne for p in paras for e in p.effets if e.gagne}
    exiges = {c.objet for p in paras for ch in p.choix for c in ch.si if c.objet}
    assert "clé d'argent" in donnes & exiges
    assert any(c.flag for p in paras for ch in p.choix for c in ch.si)
    assert any(e.stat for p in paras for e in p.effets)


def jouer(book, seed, strategie):
    engine = Engine(book, Dice(seed))
    state, _ = engine.new_game("Test")
    for _ in range(300):
        if state.fin:
            return state
        actions = engine.actions(state)
        assert actions, f"aucune action au §{state.paragraphe}"
        choisie = next((a for nom in strategie for a in actions if a.libelle == nom), actions[0])
        engine.act(state, choisie)
    pytest.fail("partie interminable")


def test_les_deux_fins_et_la_mort_sont_jouables(book):
    fins = {(s.fin, s.paragraphe) for s in (jouer(book, seed, SAGE) for seed in range(60))}
    assert ("victoire", 23) in fins  # la vraie fin, avec le secret de la cloche
    presse = ["Entrer par la grande porte", "Combattre", "Monter l'escalier", "Franchir le vide",
              "Reprendre votre souffle et monter", "Continuer à monter", "Trancher la corde",
              "Sauter vers l'escalier"]
    fins = {(s.fin, s.paragraphe) for s in (jouer(book, seed, presse) for seed in range(60))}
    assert ("victoire", 24) in fins  # la fin amère
    assert any(f == "mort" for f, _ in fins)
    fiole = ["Descendre par la brèche", "Prendre l'escalier", "Monter l'escalier", "Franchir le vide",
             "Reprendre votre souffle et monter", "Boire la fiole noire"]
    assert jouer(book, 1, fiole).paragraphe == 14


def test_la_cli_finit_le_livre(book):
    lignes: list[str] = []

    def inp(_prompt):
        # relit les actions affichées depuis le dernier paragraphe et applique SAGE
        menu = []
        for ligne in reversed(lignes):
            t = ligne.strip()
            if t[:1].isdigit() and ". " in t:
                menu.append(t.split(". ", 1))
            elif menu:
                break
        for nom in SAGE:
            for num, libelle in menu:
                if libelle == nom:
                    return num
        return "1"

    seed = next(s for s in range(60) if jouer(book, s, SAGE).fin == "victoire")
    assert play(book, seed, "Zoltan", inp=inp, out=lignes.append) == "victoire"
    assert "*** VICTOIRE ***" in lignes[-1]
