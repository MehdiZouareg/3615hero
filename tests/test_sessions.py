import time

from app.sessions import Store, clean_code, clean_pseudo


def test_clean_pseudo_et_code():
    assert clean_pseudo(" zoltan ") == "ZOLTAN"
    assert clean_pseudo("Jean-Luc 2") == "JEANLUC2"
    assert clean_pseudo("é") is None and clean_pseudo("a") is None and clean_pseudo("") is None
    assert clean_pseudo("abcdefghijk") is None  # 11 caractères
    assert clean_code(" 0427 ") == "0427"
    for bad in ("427", "12345", "12a4", "", None):
        assert clean_code(bad) is None


def test_connexions():
    s = Store()
    assert s.get_connection("u1") is None
    s.put_connection("u1", {"screen": "accueil", "nom": "é"})
    s.put_connection("u1", {"screen": "jeu", "nom": "é"})
    assert s.get_connection("u1") == {"screen": "jeu", "nom": "é"}
    s.drop_connection("u1")
    assert s.get_connection("u1") is None


def test_purge_des_connexions_perimees():
    s = Store()
    s.put_connection("vieux", {})
    s.db.execute("UPDATE connexions SET maj = ?", (time.time() - 90000,))
    s.put_connection("neuf", {})
    assert s.purge_connections() == 1
    assert s.get_connection("vieux") is None and s.get_connection("neuf") == {}


def test_parties_par_pseudo_et_code():
    s = Store()
    s.save_game("ZOLTAN", "1234", "demo", {"paragraphe": 1})
    s.save_game("ZOLTAN", "5678", "demo", {"paragraphe": 9})
    s.save_game("ZOLTAN", "1234", "demo", {"paragraphe": 4})  # mise à jour
    assert s.count_games() == 2
    assert s.load_game("ZOLTAN", "1234") == ("demo", {"paragraphe": 4})
    assert s.load_game("ZOLTAN", "0000") is None and s.load_game("AUTRE", "1234") is None
    s.delete_game("ZOLTAN", "1234")
    assert s.load_game("ZOLTAN", "1234") is None and s.count_games() == 1


def test_new_code_evite_les_codes_pris():
    s = Store()
    for i in range(10000):
        if i != 4242:
            s.db.execute("INSERT INTO parties VALUES ('BOB', ?, 'demo', '{}', 0, 0)", (f"{i:04d}",))
    # 9999 codes pris : new_code refuse plutôt que de tourner sans fin
    try:
        s.new_code("BOB")
        raise AssertionError("aurait dû refuser")
    except RuntimeError:
        pass
    code = s.new_code("ALICE")
    assert len(code) == 4 and code.isdigit()


def test_persistance_sur_disque(tmp_path):
    path = tmp_path / "sous" / "dossier" / "heros.sqlite3"
    s = Store(path)
    s.save_game("ZOLTAN", "1234", "demo", {"paragraphe": 7})
    s.put_connection("u1", {"screen": "jeu"})
    s.close()
    s2 = Store(path)
    assert s2.load_game("ZOLTAN", "1234") == ("demo", {"paragraphe": 7})
    assert s2.get_connection("u1") == {"screen": "jeu"}
    s2.close()
