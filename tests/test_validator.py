from pathlib import Path

from app.engine.models import Book, load_book
from tools.validate_book import main, report, validate

ROOT = Path(__file__).parent.parent
MINI = Path(__file__).parent / "fixtures" / "mini"

STATS = {"stats": {"habilete": "1d6+6", "endurance": "2d6+12", "chance": "1d6+6"}}


def mk(paragraphes: dict, **kw) -> Book:
    return Book.model_validate({"titre": "T", "personnage": dict(STATS, **kw.pop("personnage", {})),
                                "paragraphes": paragraphes, **kw})


def ch(vers, **si):
    return {"libelle": f"vers {vers}", "vers": vers, **({"si": [si]} if si else {})}


FIN = {"texte": "fin", "fin": "victoire"}
MORT = {"texte": "mort", "fin": "mort"}


def codes(book, level="erreur"):
    return {(i.code, i.paragraphe) for i in validate(book) if i.level == level}


def test_livre_sain():
    book = mk({1: {"texte": "a", "choix": [ch(2), ch(3)]}, 2: FIN, 3: MORT})
    assert validate(book) == []
    text, code = report(book, [])
    assert code == 0 and "OK" in text


def test_fixture_mini():
    # le §8 de la fixture est volontairement orphelin
    assert codes(load_book(MINI)) == {("inatteignable", 8)}


def test_destination_inexistante():
    book = mk({1: {"texte": "a", "choix": [ch(2), ch(99)]}, 2: FIN})
    assert ("destination", 1) in codes(book)


def test_inatteignable():
    book = mk({1: {"texte": "a", "choix": [ch(2)]}, 2: FIN, 3: {"texte": "x", "choix": [ch(2)]}})
    assert codes(book) == {("inatteignable", 3)}


def test_cul_de_sac():
    book = mk({1: {"texte": "a", "choix": [ch(2), ch(3)]}, 2: FIN, 3: {"texte": "rien"}})
    assert codes(book) == {("cul-de-sac", 3)}


def test_objet_jamais_donne():
    book = mk({1: {"texte": "a", "choix": [ch(2), ch(3, objet="clé")]}, 2: FIN, 3: MORT})
    issues = [i for i in validate(book) if i.code == "condition"]
    assert len(issues) == 1 and issues[0].paragraphe == 1
    assert "donné nulle part" in issues[0].message
    # le §3 n'est donc atteignable par aucun chemin réel
    assert ("inatteignable", 3) in codes(book)


def test_objet_donne_mais_pas_sur_le_chemin():
    # la clé est donnée au §3, qui ne mène jamais au §2 où elle est exigée
    book = mk({
        1: {"texte": "a", "choix": [ch(2), ch(3)]},
        2: {"texte": "porte", "choix": [ch(4, objet="clé"), ch(5)]},
        3: {"texte": "clé", "effets": [{"gagne": "clé"}], "choix": [ch(5)]},
        4: FIN, 5: MORT,
    })
    found = codes(book)
    assert ("condition", 2) in found and ("victoire", None) in found


def test_objet_perdu_avant_la_porte():
    book = mk({
        1: {"texte": "a", "effets": [{"gagne": "clé"}], "choix": [ch(2)]},
        2: {"texte": "vol", "effets": [{"perd": "clé"}], "choix": [ch(3, objet="clé"), ch(4)]},
        3: FIN, 4: MORT,
    })
    assert ("condition", 2) in codes(book)


def test_flag_jamais_pose_et_sans_flag():
    book = mk({1: {"texte": "a", "choix": [ch(2, flag="vu"), ch(3, sans_flag="vu")]}, 2: MORT, 3: FIN})
    issues = [i for i in validate(book) if i.code == "condition"]
    assert len(issues) == 1 and "posé nulle part" in issues[0].message


def test_objet_obtenable_par_une_boucle():
    # il faut repasser par le §1 après avoir pris la clé : c'est valide
    book = mk({
        1: {"texte": "a", "choix": [ch(2), ch(3, objet="clé")]},
        2: {"texte": "clé", "effets": [{"gagne": "clé"}], "choix": [ch(1)]},
        3: FIN,
    })
    assert codes(book) == set()


def test_boucle_sans_issue():
    book = mk({
        1: {"texte": "a", "choix": [ch(2), ch(4)]},
        2: {"texte": "b", "choix": [ch(3)]},
        3: {"texte": "c", "choix": [ch(2)]},
        4: FIN,
    })
    issues = [i for i in validate(book) if i.code == "boucle"]
    assert len(issues) == 1 and "§2, §3" in issues[0].message


def test_boucle_avec_issue_acceptee():
    book = mk({1: {"texte": "a", "choix": [ch(2)]}, 2: {"texte": "b", "choix": [ch(1), ch(3)]}, 3: FIN})
    assert codes(book) == set()


def test_impasse_selon_inventaire():
    # au §2, sans la corde, plus aucun choix
    book = mk({
        1: {"texte": "a", "choix": [ch(2), ch(3)]},
        2: {"texte": "puits", "choix": [ch(4, objet="corde")]},
        3: {"texte": "corde", "effets": [{"gagne": "corde"}], "choix": [ch(2)]},
        4: FIN,
    })
    assert ("impasse", 2) in codes(book)


def test_aucune_victoire():
    book = mk({1: {"texte": "a", "choix": [ch(2)]}, 2: MORT})
    assert codes(book) == {("victoire", None)}


def test_combat_sans_defaite_est_une_issue():
    book = mk({
        1: {"texte": "a", "combat": {"ennemi": "Rat", "habilete": 5, "endurance": 2, "victoire": 2}},
        2: FIN,
    })
    assert codes(book) == set()


def test_stat_inconnue_et_avertissements():
    book = mk({
        1: {"texte": "a", "test": {"stat": "magie", "reussite": 2, "echec": 2}},
        2: {"texte": "b", "choix": [ch(3, stat="habilete", min=10)]},
        3: FIN,
    }, flags_visibles={"fantome": "Jamais posé"})
    assert ("stat-inconnue", 1) in codes(book)
    assert codes(book, "attention") == {("choix-stats", 2), ("flag-visible", None), ("sans-mort", None)}
    assert report(book, [i for i in validate(book) if i.level == "attention"], strict=True)[1] == 1


def test_cli_codes_retour(tmp_path, capsys):
    assert main([str(MINI)]) == 1
    assert "inatteignable" not in capsys.readouterr().err
    bad = tmp_path / "book.yaml"
    bad.write_text("titre: X\nparagraphes: {1: {texte: a, surprise: 1}}\n", encoding="utf-8")
    assert main([str(bad)]) == 2
    assert "mal formé" in capsys.readouterr().err
