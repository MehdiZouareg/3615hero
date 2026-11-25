"""Parcours complets du service, écran par écran, sans HTTP."""
from pathlib import Path

import pytest

from app import minipavi as mp
from app.engine.dice import Dice
from app.engine.engine import Engine
from app.engine.models import GameState, load_book
from app.screens import Service, pack
from app.sessions import Store
from tests.test_demo_book import SAGE
from tests.vdt import decode

DEMO = Path(__file__).parent.parent / "books" / "demo-la-tour"


class Minitel:
    """Un Minitel de test : envoie des touches, garde le dernier écran décodé."""

    def __init__(self, service: Service, uid: str = "100001234"):
        self.service, self.uid = service, uid
        self.screen: list[str] = [""] * 25
        self.resp: mp.PaviResponse | None = None

    def press(self, fctn: str, text: str | None = None) -> list[str]:
        content = [text] if text is not None else ["reste d'une saisie précédente"]
        self.resp = self.service.handle(mp.PaviRequest(unique_id=self.uid, fctn=fctn, content=content))
        self.resp.to_json("https://heros.test/")  # doit toujours être sérialisable
        data = self.resp.content
        fresh = decode(data)  # lève une erreur au moindre débordement
        assert max(len(l) for l in fresh) <= 40
        if data.startswith(b"\x1f\x40\x41\x18\x1f\x41\x41\x0c"):
            self.screen = fresh
        else:  # mise à jour partielle : seule la ligne 0 change
            self.screen = [fresh[0]] + self.screen[1:]
        return self.screen

    @property
    def cx(self) -> dict:
        return self.service.store.get_connection(self.uid)

    def text(self) -> str:
        return "\n".join(self.screen)

    def flat(self) -> str:
        """L'écran sur une seule ligne, espaces réduits : pour chercher une phrase
        sans dépendre des retours à la ligne."""
        return " ".join(" ".join(self.screen).split())


@pytest.fixture
def book():
    return load_book(DEMO)


def make(book, seed=5):
    seeds = iter(range(seed, seed + 100000))
    return Service({book.id: book}, Store(), lambda: Dice(next(seeds)))


def start_game(m: Minitel, pseudo="zoltan"):
    m.press("CNX")
    m.press("ENVOI", "1")
    m.press("ENVOI")
    m.press("ENVOI", pseudo)
    m.press("ENVOI")


def play_to_end(m: Minitel, strategy) -> GameState:
    for _ in range(400):
        cx = m.cx
        if cx["screen"] == "fin":
            return GameState.model_validate(cx["game"])
        assert cx["screen"] in ("jeu", "combat")
        if m.resp.command is None:  # page de texte sans saisie
            m.press("SUITE")
            continue
        book = m.service.books[cx["book"]]
        actions = Engine(book).actions(GameState.model_validate(cx["game"]))
        wanted = next((i for name in strategy for i, a in enumerate(actions, 1) if a.libelle == name), 1)
        m.press("ENVOI", str(wanted))
    pytest.fail("partie interminable")


# -- accueil --------------------------------------------------------------------

def test_accueil_kiosque(book):
    m = Minitel(make(book))
    screen = m.press("CNX")
    assert "33661155  HHEERROOSS" in screen[7] and screen[6] == screen[7]
    assert all("#" in screen[r] for r in (1, 3, 5))  # bannière semi-graphique  # double hauteur et largeur
    assert "1  La Tour de Cendre" in screen[11]
    assert "R  Reprendre une partie" in screen[20]
    cmd = m.resp.command.to_command()
    assert cmd["name"] == "InputTxt" and cmd["param"]["y"] == 23
    assert m.resp.to_json("u")["echo"] == "on"


def test_accueil_saisies_invalides(book):
    m = Minitel(make(book))
    m.press("CNX")
    assert m.press("ENVOI", "9")[0] == "Choix incorrect"
    assert "33661155" in m.screen[7]  # l'écran n'a pas été redessiné
    assert m.resp.command is not None  # la saisie est relancée
    assert m.press("ENVOI", "")[0] == "Choix incorrect"
    assert m.press("SUITE")[0] == "Pas d'autre page"
    assert m.cx["screen"] == "accueil"


def test_catalogue_pagine(book):
    books = {f"b{i:02d}": book.model_copy(update={"id": f"b{i:02d}", "titre": f"Livre {i:02d}"}) for i in range(8)}
    m = Minitel(Service(books, Store()))
    screen = m.press("CNX")
    assert "Page 1/2" in screen[19] and "Livre 03" in m.text() and "Livre 04" not in m.text()
    screen = m.press("SUITE")
    assert "Page 2/2" in screen[19] and " 7  Livre 06" in m.text()
    m.press("ENVOI", "8")
    assert m.cx["screen"] == "livre" and m.cx["book"] == "b07"


def test_aide_depuis_l_accueil(book):
    m = Minitel(make(book))
    m.press("CNX")
    assert "MODE D'EMPLOI" in m.press("GUIDE")[1]
    while m.cx["screen"] == "guide":
        m.press("SUITE") if "SUITE" in m.screen[24] else m.press("SOMMAIRE")
    assert m.cx["screen"] == "accueil"


# -- création -------------------------------------------------------------------

def test_creation_du_personnage(book):
    m = Minitel(make(book))
    m.press("CNX")
    screen = m.press("ENVOI", "1")
    assert "La Tour de Cendre" in screen[1] and "26 paragraphes" in screen[21]
    assert m.resp.command is None
    m.press("ENVOI")
    assert m.cx["screen"] == "pseudo"
    assert m.press("ENVOI", "é")[0].startswith("Pseudo : 2 à 10")
    screen = m.press("ENVOI", "zoltan")
    cx = m.cx
    assert cx["pseudo"] == "ZOLTAN" and len(cx["code"]) == 4
    assert "VOTRE CODE" in m.text() and "".join(c * 2 for c in cx["code"]) in m.text()
    assert "HABILETE" in m.text() and "ZOLTAN" in screen[4]
    assert m.service.store.load_game("ZOLTAN", cx["code"]) is not None  # sauvegardé dès la création
    screen = m.press("ENVOI")
    assert m.cx["screen"] == "jeu" and "#1" in screen[1] and "ZOLTAN" in screen[2]


def test_paragraphe_pagination_et_choix(book):
    m = Minitel(make(book))
    start_game(m)
    assert "#" in m.screen[6] and "1/2" in m.screen[23]  # illustration et pagination
    assert m.press("RETOUR")[0] == "Première page"
    screen = m.press("SUITE")
    assert "2/2" in screen[23] and " 1  Entrer par la grande porte" in m.text()
    assert m.resp.command.to_command()["param"]["validwith"] & 128
    assert m.press("ENVOI", "7")[0] == "Tapez un numéro de 1 à 2"
    assert m.press("ENVOI", "x")[0] == "Tapez un numéro de 1 à 2"
    m.press("RETOUR")
    assert "1/2" in m.screen[23]
    m.press("ENVOI")  # ENVOI sur une page de texte = SUITE
    m.press("REPETITION")
    assert "2/2" in m.screen[23]
    m.press("ENVOI", "2")
    assert GameState.model_validate(m.cx["game"]).paragraphe == 3


def test_feuille_d_aventure_et_regles(book):
    m = Minitel(make(book))
    start_game(m)
    m.press("SUITE")
    screen = m.press("SOMMAIRE")
    assert "FEUILLE D'AVENTURE" in screen[1] and "épée, lanterne" in m.text()
    assert f"Pseudo ZOLTAN   Code {m.cx['code']}" in screen[20]
    assert "REGLES DU JEU" in m.press("GUIDE")[1]
    m.press("SOMMAIRE")
    assert m.cx["screen"] == "jeu" and m.cx["page"] == 1  # retour à la même page
    m.press("GUIDE")
    assert "HABILETÉ"[:7] in m.text()
    m.press("SOMMAIRE")
    assert m.cx["screen"] == "jeu"


def test_flags_visibles_sur_la_feuille(book):
    m = Minitel(make(book))
    start_game(m)
    cx = m.cx
    cx["game"]["perso"]["flags"] = ["secret_cloche", "corbeau_libre"]
    cx["game"]["perso"]["inventaire"] += ["clé d'argent", "sel consacré", "plume noire"]
    m.service.store.put_connection(m.uid, cx)
    m.press("SOMMAIRE")
    assert "* Vous connaissez le secret de la" in m.text() and "* Un corbeau" in m.text()
    assert "plume noire" in m.text()


def test_combat(book):
    m = Minitel(make(book))
    start_game(m)
    m.press("SUITE")
    m.press("ENVOI", "1")  # la grande porte : le chien d'os
    assert "Chien d'os : habileté 6, endurance 6" in m.text() and "Combattre" in m.text()
    m.press("ENVOI", "1")
    assert m.cx["screen"] == "combat"
    assert "CChhiieenn  dd''ooss" in m.screen[10] and "#" in m.screen[4]  # nom et épées croisées
    assert "ZOLTAN" in m.screen[12] and "HAB 6" in m.screen[13] and "/6" in m.screen[13]
    assert "force d'attaque" in m.text()
    for _ in range(40):
        if m.cx["screen"] != "combat":
            break
        m.press("ENVOI", "")  # ENVOI seul = combattre
    assert m.cx["screen"] in ("jeu", "fin")
    if m.cx["screen"] == "jeu":
        assert "vainqueur" in m.text()  # le récit du dernier assaut ouvre le paragraphe suivant


def test_fuite(book):
    m = Minitel(make(book))
    start_game(m)
    m.press("SUITE")
    m.press("ENVOI", "1")
    m.press("ENVOI", "2")
    state = GameState.model_validate(m.cx["game"])
    assert state.paragraphe == 3 and state.perso.stats["endurance"] == state.perso.initial["endurance"] - 2
    assert "vous recevez un dernier coup" in m.flat()


# -- fins -------------------------------------------------------------------------

def test_partie_jusqu_a_la_victoire(book):
    for seed in range(5, 400, 7):
        m = Minitel(make(book, seed))
        start_game(m)
        code = m.cx["code"]
        state = play_to_end(m, SAGE)
        if state.fin == "victoire":
            break
    else:
        pytest.fail("aucune victoire")
    assert "VVIICCTTOOIIRREE  !!" in m.screen[9] and "#" in m.screen[5]
    assert "ZOLTAN a triomphé" in m.flat()
    assert m.service.store.load_game("ZOLTAN", code) is None  # une partie finie ne se reprend pas
    m.press("ENVOI")
    assert m.cx["screen"] == "accueil" and m.cx["game"] is None


def test_mort(book):
    m = Minitel(make(book))
    start_game(m)
    state = play_to_end(m, ["Descendre par la brèche", "Prendre l'escalier", "Monter l'escalier",
                            "Franchir le vide", "Reprendre votre souffle et monter", "Boire la fiole noire"])
    assert state.fin == "mort" and state.paragraphe == 14
    assert "VVOOUUSS  EETTEESS  MMOORRTT" in m.screen[9]
    assert "s'achève au paragraphe 14" in m.flat()
    assert m.press("GUIDE")[0].startswith("ENVOI pour revenir")


def test_mort_au_combat_sans_paragraphe(book):
    m = Minitel(make(book))
    start_game(m)
    cx = m.cx
    cx["game"]["perso"]["stats"].update(habilete=1, endurance=2)
    m.service.store.put_connection(m.uid, cx)
    m.press("SUITE")
    m.press("ENVOI", "1")
    for _ in range(30):
        if m.cx["screen"] == "fin":
            break
        m.press("ENVOI", "1")
    assert m.cx["screen"] == "fin" and "succombez" in m.text()


# -- sauvegarde et reprise ------------------------------------------------------------

def test_quitter_puis_reprendre(book):
    service = make(book)
    m = Minitel(service)
    start_game(m)
    m.press("SUITE")
    m.press("ENVOI", "2")
    code = m.cx["code"]
    m.press("SOMMAIRE")
    assert m.press("ENVOI", "0")[0] == "Partie sauvegardée"
    assert m.cx["screen"] == "accueil"
    assert service.handle(mp.PaviRequest(unique_id=m.uid, fctn="FIN")).content == b""
    assert service.store.get_connection(m.uid) is None

    m2 = Minitel(service, uid="200009999")  # nouvelle connexion, autre identifiant
    m2.press("CNX")
    m2.press("ENVOI", "r")
    assert m2.cx["screen"] == "reprise_pseudo"
    m2.press("ENVOI", "Zoltan")
    assert "Pseudo : ZOLTAN" in m2.screen[5]
    assert m2.press("ENVOI", "0000" if code != "0000" else "1111")[0] == "Pseudo ou code inconnu"
    screen = m2.press("ENVOI", code)
    assert m2.cx["screen"] == "jeu" and "#3" in screen[1]
    assert "Vous reprenez votre aventure." in m2.text()


def test_reprise_trois_essais(book):
    m = Minitel(make(book))
    m.press("CNX")
    m.press("ENVOI", "R")
    m.press("ENVOI", "PERSONNE")
    m.press("ENVOI", "1234")
    m.press("ENVOI", "abcd")
    assert m.press("ENVOI", "9999")[0] == "Partie introuvable"
    assert m.cx["screen"] == "accueil"


def test_deconnexion_sauvage_puis_reprise(book):
    service = make(book)
    m = Minitel(service)
    start_game(m)
    m.press("SUITE")
    m.press("ENVOI", "2")
    code = m.cx["code"]
    # pas de FIN : la passerelle ne prévient pas toujours. La partie est quand même là.
    livre, etat = service.store.load_game("ZOLTAN", code)
    assert livre == book.id and etat["paragraphe"] == 3


# -- robustesse -----------------------------------------------------------------------

def test_connexion_inconnue_et_evenements(book):
    service = make(book)
    m = Minitel(service)
    assert "HHEERROOSS" in m.press("ENVOI", "1")[7]  # uniqueId inconnu : accueil
    before = m.cx
    assert service.handle(mp.PaviRequest(unique_id=m.uid, fctn="BGCALL-WM-START")).content == b""
    assert m.cx == before
    m.press("CNX")
    assert m.cx["screen"] == "accueil"


def test_erreur_interne_ramene_a_l_accueil(book):
    m = Minitel(make(book))
    start_game(m)
    cx = m.cx
    cx["book"] = "livre-disparu"
    m.service.store.put_connection(m.uid, cx)
    screen = m.press("SUITE")
    assert screen[0].startswith("Erreur du service") and m.cx["screen"] == "accueil"


def test_tous_les_paragraphes_s_affichent(book):
    service = make(book)
    m = Minitel(service)
    start_game(m)
    for pid, para in book.paragraphes.items():
        cx = m.cx
        state = GameState.model_validate(cx["game"])
        state.paragraphe, state.ennemi, state.fin = pid, None, None
        state.perso.inventaire = ["épée", "lanterne", "clé d'argent", "sel consacré", "plume noire"]
        state.perso.flags = ["secret_cloche"]
        Engine(book)._enter(state, pid)
        cx.update(game=state.model_dump(), screen="jeu", page=0,
                  journal=["Vous lancez les dés : 12 contre chance 7.", "Raté !"])
        service.store.put_connection(m.uid, cx)
        seen = ""
        for _ in range(6):
            screen = m.press("REPETITION")
            seen += " ".join(screen[4:22])
            if m.resp.command is not None or "/" not in screen[23] or screen[23].split()[-1].split("/")[0] == screen[23].split()[-1].split("/")[1]:
                break
            m.press("SUITE")
        mots = para.texte.split()
        assert mots[0] in seen and mots[-1] in seen, f"§{pid} tronqué"


def test_pack():
    a, b = ("a", None), ("b", 1)
    blank = ("", None)
    pages = pack([[a], [a], [blank], [b, b], [a]], 3)
    assert pages == [[a, a], [b, b, a]]
    assert pack([], 5) == [[]]
    assert pack([[a]] * 5, 4, first_height=1) == [[a], [a] * 4]
    assert all(p[0] != blank and p[-1] != blank for p in pack([[blank], [a], [blank], [blank], [a], [blank]], 2))
