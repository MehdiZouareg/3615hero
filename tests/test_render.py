from pathlib import Path

import pytest

from app.engine.models import load_book
from app.videotex import codes as C
from app.videotex.render import Page, encode_text, mosaic, normalize, paginate, wrap
from tests.vdt import VdtError, decode

DEMO = Path(__file__).parent.parent / "books" / "demo-la-tour"


# -- codes ---------------------------------------------------------------------

def test_pos():
    assert C.pos(1, 1) == b"\x1f\x41\x41"
    assert C.pos(24, 40) == b"\x1f\x58\x68"
    assert C.pos(0, 1) == b"\x1f\x40\x41"
    for bad in ((25, 1), (1, 41), (1, 0), (-1, 1)):
        with pytest.raises(ValueError):
            C.pos(*bad)


@pytest.mark.parametrize("n", [0, 1, 2, 3, 39, 40, 64, 65, 70])
def test_repeat(n):
    data = C.repeat(b"-", n)
    assert decode(C.pos(1, 1) + data)[1] == "-" * n if n <= 40 else True
    # compte indépendant : chaque REP ajoute (octet - 0x40) copies
    count, i = 0, 0
    while i < len(data):
        if data[i] == 0x12:
            count += data[i + 1] - 0x40; i += 2
        else:
            count += 1; i += 1
    assert count == n
    assert C.repeat(b"x", 3) == b"x\x12\x42"


# -- accents ---------------------------------------------------------------------

def test_accents_francais_en_g2():
    assert encode_text("é") == b"\x19\x42e"
    assert encode_text("è") == b"\x19\x41e"
    assert encode_text("à") == b"\x19\x41a"
    assert encode_text("ê") == b"\x19\x43e"
    assert encode_text("ë") == b"\x19\x48e"
    assert encode_text("ç") == b"\x19\x4bc"
    assert encode_text("ù") == b"\x19\x41u"
    assert encode_text("î") == b"\x19\x43i"
    assert encode_text("œ") == b"\x19\x7a"
    assert encode_text("Déjà") == b"D\x19\x42ej\x19\x41a"


def test_normalize():
    assert normalize("É À Ç Ô") == "E A C O"  # pas de majuscule accentuée
    assert normalize("l’œil… « oui » — non") == 'l\'œil... "oui" - non'.replace('"oui"', '"oui"')
    assert normalize("a b") == "a b"
    assert normalize("ñ ø 🙂 `x`") == "n ? ? 'x'"
    assert normalize("[a] {b} c|d ~") == "(a) (b) c/d -"
    for ch in normalize("tout ça : «é», [x], `y`, ~z~, a|b, 100 % sûr ?"):
        assert len(encode_text(ch)) >= 1


def test_encode_7_bits_et_une_case_par_caractere():
    texte = "Où est passée la clé d'argent, maître Orcan ? Çà et là, l'œuvre gît."
    data = encode_text(texte)
    assert all(b < 0x80 for b in data)
    assert decode(C.pos(1, 1) + encode_text(texte[:40]))[1] == normalize(texte[:40]).rstrip()


# -- wrap et pagination ------------------------------------------------------------

def test_wrap_40_colonnes():
    texte = "Le soir tombe quand vous atteignez le pied de la tour. " * 5 + "\nSecond alinéa."
    lines = wrap(texte)
    assert max(len(l) for l in lines) <= 40
    assert "" in lines and lines[-1] == "Second alinéa."
    assert " ".join(l for l in lines if l).split() == normalize(texte).split()


def test_wrap_mot_trop_long_et_largeur():
    lines = wrap("x" * 95)
    assert [len(l) for l in lines] == [40, 40, 15]
    assert all(len(l) <= 20 for l in wrap("un deux trois quatre cinq six sept huit neuf dix", 20))
    assert wrap("") == [] and wrap("\n\n") == []
    assert wrap("a\n\n\nb") == ["a", "", "b"]


def test_wrap_accents_comptent_pour_une_case():
    ligne = "é" * 40
    assert wrap(ligne + " fin") == [ligne, "fin"]


def test_paginate():
    lines = [f"l{i}" for i in range(10)]
    assert paginate(lines, 4) == [lines[0:4], lines[4:8], lines[8:10]]
    assert paginate(lines, 10) == [lines]
    assert paginate([], 5) == [[]]
    assert paginate(lines, 4, first_height=2)[0] == lines[0:2]
    # pas de ligne vide en tête ni en fin de page
    pages = paginate(["a", "b", "", "c", "d", "", "e"], 2)
    assert pages == [["a", "b"], ["c", "d"], ["e"]]
    assert all(p and p[0] != "" and p[-1] != "" for p in pages)
    with pytest.raises(ValueError):
        paginate(lines, 0)


def test_pagination_ne_perd_rien():
    lines = wrap("mot " * 400)
    for h in (1, 3, 7, 18):
        pages = paginate(lines, h)
        assert [l for p in pages for l in p] == lines
        assert all(len(p) <= h for p in pages)


# -- mosaïques ---------------------------------------------------------------------

def test_mosaic_codes():
    assert mosaic(["##", "##", "##"]) == [b"\x7f"]          # pavé plein
    assert mosaic(["#.", "#.", "#."]) == [b"\x35"]          # moitié gauche
    assert mosaic([".#", ".#", ".#"]) == [b"\x6a"]          # moitié droite
    assert mosaic(["..", "..", ".."]) == [b"\x20"]
    assert mosaic(["#"]) == [b"\x21"]                        # complété à 2 x 3
    assert mosaic(["...#", "", "", "#"]) == [b"\x20\x22", b"\x21\x20"]
    assert mosaic([]) == []
    with pytest.raises(ValueError):
        mosaic(["#" * 82])


# -- Page ---------------------------------------------------------------------------

def test_page_refuse_les_debordements():
    p = Page()
    p.text(1, 1, "x" * 40)
    with pytest.raises(ValueError):
        p.text(1, 2, "x" * 40)
    with pytest.raises(ValueError):
        p.text(2, 1, "x" * 21, double_width=True)
    with pytest.raises(ValueError):
        p.text(1, 1, "Titre", double_height=True)
    with pytest.raises(ValueError):
        p.text(25, 1, "x")
    with pytest.raises(ValueError):
        p.text(0, 1, "x")
    with pytest.raises(ValueError):
        p.keys(24, [("x" * 30, "SOMMAIRE"), ("y", "ENVOI")])
    with pytest.raises(ValueError):
        p.art(23, ["#"] * 9)


def test_page_complete_decodee_identique_a_l_apercu():
    p = Page()
    p.bar(1, "3615 HEROS", color=C.CYAN)
    p.center(4, "LA TOUR", double_height=True, double_width=True, color=C.YELLOW)
    p.frame(6, 2, 6, 38, color=C.BLUE)
    p.lines(7, wrap("Où la clé d'argent a-t-elle été cachée ? Çà et là, peut-être.", 34), col=4)
    p.hline(13, color=C.RED)
    p.art(14, ["..####..", ".######.", "########", "########", ".######.", "..####.."], color=C.GREEN)
    p.text(20, 1, "Clignote", blink=True, inverse=True)
    p.keys(24, [("Suite", "SUITE"), ("", "ENVOI")])
    p.line0("Sauvegardé")
    data = p.data()
    assert all(b < 0x80 for b in data)
    screen = decode(data)
    assert screen == p.preview()
    assert screen[0] == "Sauvegardé"
    assert screen[1] == "3615 HEROS".center(40).rstrip()
    assert screen[3] == screen[4] and "LLAA  TTOOUURR" in screen[4]
    assert screen[24].endswith("Suite  SUITE   ENVOI")
    assert max(len(l) for l in screen) <= 40


def test_page_efface_ecran_et_ligne_0():
    data = Page().data()
    assert data == C.pos(0, 1) + C.CLR_EOL + C.pos(1, 1) + C.CLS + C.CUR_OFF
    assert Page(clear=False).data() == b""


def test_attributs_annules_apres_chaque_ecriture():
    data = Page(clear=False).text(3, 1, "x", color=C.RED, inverse=True, double_height=True).data()
    assert data == (C.pos(3, 1) + C.fg(C.RED) + C.INVERSE_ON + C.SIZE_DOUBLE_H + b"x"
                    + C.fg(C.WHITE) + C.INVERSE_OFF + C.SIZE_NORMAL)


def test_decodeur_detecte_un_debordement():
    with pytest.raises(VdtError):
        decode(C.pos(1, 30) + b"x" * 12)
    with pytest.raises(VdtError):
        decode(C.pos(1, 1) + "é".encode("utf-8"))


# -- le livre de démo tient à l'écran --------------------------------------------------

def test_tous_les_textes_du_livre_de_demo_se_rendent():
    book = load_book(DEMO)
    textes = [book.resume, book.regles] + [p.texte for p in book.paragraphes.values()]
    textes += [c.libelle for p in book.paragraphes.values() for c in p.choix]
    plusieurs_pages = 0
    for texte in textes:
        lines = wrap(texte, 38)
        assert lines and max(len(l) for l in lines) <= 38
        assert "?" not in "".join(lines).replace(" ?", "")  # aucun caractère perdu
        pages = paginate(lines, 12)
        plusieurs_pages += len(pages) > 1
        for page_lines in pages:
            p = Page().lines(4, page_lines, col=2)
            assert decode(p.data()) == p.preview()
    assert plusieurs_pages >= 2  # la pagination est réellement exercée


def test_illustrations_du_livre_de_demo():
    book = load_book(DEMO)
    illustres = [p for p in book.paragraphes.values() if p.illustration]
    assert illustres
    for para in illustres:
        rows = mosaic(para.illustration)
        assert len(rows) <= 8 and len(rows[0]) <= 40
        page = Page().art(3, para.illustration, color=C.CYAN)
        assert decode(page.data()) == page.preview()
        assert any("#" in l for l in page.preview())


def test_wrap_ne_coupe_pas_avant_la_ponctuation_haute():
    lines = wrap("Votre force d'attaque : 19. Chien d'os : 15.", 38)
    assert not any(l.startswith((":", "!", "?", ";")) for l in lines)
    assert max(len(l) for l in lines) <= 38
    assert wrap("mot " * 9 + "fin ?", 40) == [("mot " * 9).strip(), "fin ?"]


def test_frise_et_jauge():
    p = Page(clear=False).frieze(9, ["..#...", ".###..", "..#..."], color=C.YELLOW)
    assert decode(p.data())[9] == "#" * 40 or set(decode(p.data())[9]) <= {"#", " "}
    assert decode(p.data()) == p.preview()
    # jauge : cases pleines 0x7C, demi-case 0x74, piste vide 0x70
    assert b"\x7c\x12\x44" in Page(clear=False).gauge(3, 1, 10, 5, 10).data()      # 5 cases pleines
    half = Page(clear=False).gauge(3, 1, 10, 1, 4).data()                             # 2,5 cases
    assert b"\x7c\x7c\x74\x70" in half
    assert b"\x7c" not in Page(clear=False).gauge(3, 1, 10, 0, 10).data()
    assert b"\x74" in Page(clear=False).gauge(3, 1, 10, 1, 500).data()               # jamais vide tant qu'on vit
    full = Page(clear=False).gauge(3, 1, 10, 99, 10)
    assert decode(full.data())[3] == "#" * 10 == full.preview()[3]
    with pytest.raises(ValueError):
        Page().gauge(3, 35, 10, 1, 2)


def test_calques_superposes():
    p = Page(clear=False)
    p.art(1, ["##....", "##....", "##...."], color=C.BLUE, col=1)
    before = len(p.data())
    p.art(1, ["....##", "....##", "....##"], color=C.YELLOW, col=1)   # la case du milieu reste vide
    assert decode(p.data())[1] == "# #" and p.preview()[1] == "# #"
    assert len(p.data()) - before < 12


def test_decor_du_service():
    from app import art
    for name in ("BANNER_FAR", "BANNER_NEAR", "BANNER_SKY"):
        rows = mosaic(getattr(art, name))
        assert len(rows) == 5 and len(rows[0]) == 40
    # les calques de la bannière ne se recouvrent jamais (une case = une couleur)
    far, near, sky = (mosaic(getattr(art, n)) for n in ("BANNER_FAR", "BANNER_NEAR", "BANNER_SKY"))
    for r in range(5):
        for c in range(40):
            assert sum(layer[r][c] != 0x20 for layer in (far, near, sky)) <= 1
    for emblem in (art.SWORDS, art.SKULL, art.CROWN):
        assert len(mosaic(emblem)) <= 5 and len(mosaic(emblem)[0]) <= 20
