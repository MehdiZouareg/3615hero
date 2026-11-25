from pathlib import Path

import pytest
from pydantic import ValidationError

from app.engine.dice import Dice, FixedDice, parse_expr
from app.engine.engine import (COMBAT_SYSTEMS, Action, Engine, GameError,
                               register_combat_system)
from app.engine.models import Book, Character, GameState, Paragraph, load_book

MINI = Path(__file__).parent / "fixtures" / "mini"


@pytest.fixture
def book() -> Book:
    return load_book(MINI)


def hero(**stats) -> Character:
    base = {"habilete": 10, "endurance": 20, "chance": 9}
    base.update(stats)
    return Character(nom="Test", stats=dict(base), initial=dict(base), inventaire=["épée"])


def start(book, dice_values=(), **stats):
    engine = Engine(book, FixedDice(list(dice_values)))
    state, events = engine.new_game("Test", hero(**stats))
    return engine, state, events


def pick(engine, state, libelle):
    action = next(a for a in engine.actions(state) if a.libelle == libelle)
    return engine.act(state, action)


# -- dés ---------------------------------------------------------------------

def test_parse_expr():
    assert parse_expr("2d6+12") == (2, 6, 12)
    assert parse_expr("d6") == (1, 6, 0)
    assert parse_expr("1D6 - 1") == (1, 6, -1)
    with pytest.raises(ValueError):
        parse_expr("six")


def test_dice_seed_reproductible():
    a, b = Dice(42), Dice(42)
    assert [a.roll(2, 6) for _ in range(20)] == [b.roll(2, 6) for _ in range(20)]
    assert all(1 <= Dice(i).d(6) <= 6 for i in range(50))


def test_creation_personnage_seedee(book):
    p1 = Engine(book, Dice(7)).new_character("A")
    p2 = Engine(book, Dice(7)).new_character("B")
    assert p1.stats == p2.stats == p1.initial
    assert 7 <= p1.stats["habilete"] <= 12
    assert 14 <= p1.stats["endurance"] <= 24
    assert p1.inventaire == ["épée"]


# -- chargement ---------------------------------------------------------------

def test_load_book(book):
    assert book.id == "mini"
    assert book.paragraphes[2].combat.ennemi == "Gobelin"
    assert book.paragraphes[2].destinations() == [4, 7, 1]


def test_paragraphe_deux_sorties_refuse():
    with pytest.raises(ValidationError):
        Paragraph(texte="x", fin="mort", choix=[{"libelle": "a", "vers": 1}])


def test_condition_mal_formee_refusee():
    with pytest.raises(ValidationError):
        Paragraph(texte="x", choix=[{"libelle": "a", "vers": 1, "si": [{"stat": "chance"}]}])
    with pytest.raises(ValidationError):
        Paragraph(texte="x", choix=[{"libelle": "a", "vers": 1, "si": [{"objet": "a", "flag": "b"}]}])


# -- effets et conditions -----------------------------------------------------

def test_effet_entree_et_conditions(book):
    engine, state, events = start(book)
    assert "torche" in state.perso.inventaire
    assert events == ["Vous obtenez : torche."]
    libelles = [a.libelle for a in engine.actions(state)]
    assert libelles == ["Affronter le gobelin", "Sauter le gouffre"]  # ni clé ni habileté 99

    state.perso.inventaire.append("clé")
    assert "Ouvrir la porte" in [a.libelle for a in engine.actions(state)]
    state.perso.stats["habilete"] = 99
    assert "Passage des forts" in [a.libelle for a in engine.actions(state)]


def test_action_indisponible_refusee(book):
    engine, state, _ = start(book)
    with pytest.raises(GameError):
        engine.act(state, Action("choix", "Ouvrir la porte", 2))


def test_gain_plafonne_perte_objet_et_flag(book):
    engine, state, _ = start(book)
    state.perso.stats["endurance"] = 5
    state.perso.flags.append("a_la_cle")
    events = engine._enter(state, 8)
    assert state.perso.stats["endurance"] == 20  # plafonné au total de départ
    assert "épée" not in state.perso.inventaire
    assert "a_la_cle" not in state.perso.flags
    assert events == ["Endurance +15 (reste 20).", "Vous perdez : épée."]


def test_mort_par_effet(book):
    engine, state, _ = start(book, endurance=3)
    events = engine._enter(state, 5)
    assert state.perso.stats["endurance"] == 0
    assert state.fin == "mort"
    assert engine.actions(state) == []
    assert events[-1] == "Vos forces vous abandonnent."


# -- test de chance -----------------------------------------------------------

def test_chance_reussie_use_la_chance(book):
    engine, state, _ = start(book, [3, 4], chance=7)  # 7 <= 7
    pick(engine, state, "Sauter le gouffre")
    events = engine.act(state, engine.actions(state)[0])
    assert state.paragraphe == 4
    assert state.perso.stats["chance"] == 6
    assert "Réussi !" in events
    assert "clé" in state.perso.inventaire and "a_la_cle" in state.perso.flags


def test_chance_ratee(book):
    engine, state, _ = start(book, [6, 6], chance=7)
    pick(engine, state, "Sauter le gouffre")
    events = engine.act(state, engine.actions(state)[0])
    assert state.paragraphe == 5
    assert state.perso.stats["endurance"] == 17
    assert "Raté !" in events


# -- combat ---------------------------------------------------------------------

def test_combat_victoire(book):
    # assaut : 2 dés héros puis 2 dés ennemi. Gobelin H5 E4 : deux assauts gagnés.
    engine, state, _ = start(book, [6, 6, 1, 1, 6, 6, 1, 1])
    pick(engine, state, "Affronter le gobelin")
    assert state.ennemi.nom == "Gobelin"
    assert [a.kind for a in engine.actions(state)] == ["assaut", "fuite"]
    engine.act(state, engine.actions(state)[0])
    assert state.ennemi.endurance == 2 and state.perso.stats["endurance"] == 20
    events = engine.act(state, engine.actions(state)[0])
    assert state.ennemi is None and state.paragraphe == 4
    assert any("vainqueur" in e for e in events)


def test_combat_blessure_et_egalite(book):
    engine, state, _ = start(book, [1, 1, 6, 6, 1, 1, 3, 4], habilete=5)
    pick(engine, state, "Affronter le gobelin")
    engine.act(state, engine.actions(state)[0])  # 7 contre 17 : blessé
    assert state.perso.stats["endurance"] == 18
    engine.act(state, engine.actions(state)[0])  # 7 contre 12... blessé encore
    assert state.perso.stats["endurance"] == 16
    engine.dice._values = [3, 4, 3, 4]  # 12 contre 12 : égalité
    engine.act(state, engine.actions(state)[0])
    assert state.perso.stats["endurance"] == 16 and state.ennemi.endurance == 4


def test_combat_defaite_mene_au_paragraphe_de_mort(book):
    engine, state, _ = start(book, [1, 1, 6, 6], habilete=1, endurance=2)
    pick(engine, state, "Affronter le gobelin")
    engine.act(state, engine.actions(state)[0])
    assert state.paragraphe == 7 and state.fin == "mort" and state.ennemi is None


def test_fuite(book):
    engine, state, _ = start(book)
    pick(engine, state, "Affronter le gobelin")
    pick(engine, state, "Fuir")
    assert state.paragraphe == 1 and state.ennemi is None
    assert state.perso.stats["endurance"] == 18


def test_fuite_fatale(book):
    engine, state, _ = start(book, endurance=2)
    pick(engine, state, "Affronter le gobelin")
    pick(engine, state, "Fuir")
    assert state.fin == "mort"


def test_systeme_de_combat_enfichable(book):
    class CoupFatal:
        def assaut(self, perso, ennemi, dice):
            return 0, ennemi.endurance, ["Un seul coup suffit."]

        def fuite(self, perso, ennemi, dice):
            return 0, []

    engine = Engine(book, FixedDice([]), combat=CoupFatal())
    state, _ = engine.new_game("T", hero())
    pick(engine, state, "Affronter le gobelin")
    engine.act(state, engine.actions(state)[0])
    assert state.paragraphe == 4

    register_combat_system("coup_fatal", CoupFatal)
    try:
        b2 = book.model_copy(update={"systeme_combat": "coup_fatal"})
        assert isinstance(Engine(b2).combat, CoupFatal)
        with pytest.raises(GameError):
            Engine(book.model_copy(update={"systeme_combat": "inconnu"}))
    finally:
        del COMBAT_SYSTEMS["coup_fatal"]


# -- partie complète et sauvegarde ------------------------------------------------

def test_partie_complete_et_serialisation(book):
    engine, state, _ = start(book, [1, 1], chance=9)
    pick(engine, state, "Sauter le gouffre")
    engine.act(state, engine.actions(state)[0])
    state = GameState.model_validate_json(state.model_dump_json())  # aller-retour sauvegarde
    pick(engine, state, "Revenir au carrefour")
    pick(engine, state, "Ouvrir la porte")
    assert state.fin == "victoire" and engine.actions(state) == []


def test_cli_joue_jusqu_a_la_victoire(book):
    from tools.play_cli import play

    # seed fixe ; on tente la chance jusqu'à obtenir la clé, puis on sort.
    answers = iter(["f", "r", "x", "2", "1", "1", "2", "1", "1", "2", "1", "1", "2", "1", "1", "q"])
    lines: list[str] = []

    def inp(_prompt):
        # dès que la porte est proposée, on la prend
        if any("Ouvrir la porte" in l for l in lines[-6:]):
            n = next(l for l in reversed(lines) if "Ouvrir la porte" in l).strip()[0]
            return n
        return next(answers)

    result = play(book, 3, "Zoltan", inp=inp, out=lines.append)
    assert result == "victoire"
    assert any("Zoltan" in l for l in lines)
    assert "Choix incorrect." in lines
