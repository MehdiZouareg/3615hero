"""Les écrans du service et leur enchaînement.

Service.handle() reçoit une requête MiniPavi déjà décodée et renvoie la réponse.
L'état d'une connexion (écran courant, page, partie en cours) est un simple
dictionnaire conservé par le Store entre deux appels.

Charte : l'or (jaune) pour les titres et les écussons, le rouge pour le danger,
le cyan pour ce que le joueur peut faire, le vert pour les aides. Le bleu, presque
invisible sur un Minitel monochrome, ne sert qu'au décor.
"""
from __future__ import annotations

import logging
from typing import Callable

from . import art
from . import minipavi as mp
from .engine.dice import Dice
from .engine.engine import Engine, GameError
from .engine.models import Book, GameState
from .sessions import Store, clean_code, clean_pseudo
from .videotex import codes as C
from .videotex.render import Page, mosaic, normalize, paginate, wrap

log = logging.getLogger("heros")

BODY_TOP, BODY_ROWS, BODY_COL, BODY_W = 5, 17, 2, 38
MENU_TOP, MENU_ROWS = 4, 18          # écrans sans feuille de personnage en tête
SEP_ROW, PROMPT_ROW, KEYS_ROW = 22, 23, 24
CATALOG_PER_PAGE = 4
MAX_TRIES = 3
GOLD = C.YELLOW

AIDE = """3615 HEROS vous fait jouer à des livres dont vous êtes le héros.
Choisissez un livre dans le catalogue, donnez un pseudo : les dés créent votre personnage et un code à 4 chiffres vous est attribué. Notez-le.
À chaque paragraphe, tapez le numéro de votre choix puis ENVOI. SUITE et RETOUR feuillettent les textes longs.
SOMMAIRE affiche votre feuille d'aventure. GUIDE rappelle les règles du livre. CORRECTION et ANNULATION corrigent votre saisie.
Votre partie est sauvegardée à chaque paragraphe : quittez quand vous voulez avec CONNEXION/FIN, puis reprenez-la depuis l'accueil avec votre pseudo et votre code."""

EPITAPHES = [
    "Les corbeaux se souviendront de vous.",
    "Votre nom s'efface déjà des mémoires.",
    "Un autre ramassera votre épée.",
    "La nuit garde ce qu'elle prend.",
]
LOUANGES = [
    "Les bardes chanteront votre nom.",
    "Peu de héros peuvent en dire autant.",
    "Votre légende ne fait que commencer.",
]

Line = tuple  # (texte, couleur, écusson) : l'écusson est un numéro affiché en vidéo inverse
BLANK: Line = ("", None, None)


def _is_blank(block: list) -> bool:
    return len(block) == 1 and block[0][0] == ""


def pack(blocks: list[list[Line]], height: int, first_height: int | None = None) -> list[list[Line]]:
    """Range des blocs insécables en pages, sans ligne vide en tête ni en fin."""
    pages: list[list[Line]] = []
    cur: list[Line] = []
    limit = max(1, first_height if first_height is not None else height)

    def trim():
        while cur and cur[-1][0] == "":
            cur.pop()

    for block in blocks:
        blank = _is_blank(block)
        if blank and not cur:
            continue
        if cur and len(cur) + len(block) > limit:
            trim()
            pages.append(cur)
            cur, limit = [], height
            if blank:
                continue
        cur.extend(block[:height])
    trim()
    if cur or not pages:
        pages.append(cur)
    return pages


def text_blocks(text: str, color: int | None = None, width: int = BODY_W) -> list[list[Line]]:
    return [[(line, color, None)] for line in wrap(text, width)]


def life_color(value: int, maximum: int) -> int:
    if maximum <= 0 or value * 4 <= maximum:
        return C.RED
    return GOLD if value * 2 <= maximum else C.GREEN


class Service:
    def __init__(self, books: dict[str, Book], store: Store,
                 dice_factory: Callable[[], Dice] = Dice):
        self.books = books
        self.store = store
        self.dice_factory = dice_factory

    # ======================================================================
    # Point d'entrée
    # ======================================================================

    def handle(self, req: mp.PaviRequest) -> mp.PaviResponse:
        if req.is_disconnect:
            self.store.drop_connection(req.unique_id)  # la partie est déjà sauvegardée
            return mp.PaviResponse()
        cx = None if req.is_connect else self.store.get_connection(req.unique_id)
        if req.is_background and cx is not None:
            return mp.PaviResponse()  # rien à afficher, l'écran reste tel quel
        try:
            if cx is None:
                self.store.purge_connections()
                cx = {"screen": "accueil"}
                resp = self.show_accueil(cx)
            elif req.fctn == mp.REPETITION:
                resp = self.show(cx)
            else:
                resp = getattr(self, f"on_{cx['screen']}")(cx, req)
        except Exception:  # un écran ne doit jamais laisser le Minitel sans réponse
            log.exception("erreur sur l'écran %s", (cx or {}).get("screen"))
            cx = {"screen": "accueil"}
            resp = self.show_accueil(cx, "Erreur du service, retour à l'accueil")
        self.store.put_connection(req.unique_id, cx)
        return resp

    def show(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        return getattr(self, f"show_{cx['screen']}")(cx, msg)

    def notice(self, cx: dict, msg: str) -> mp.PaviResponse:
        """Message en ligne 0 sans redessiner l'écran ; la saisie est relancée."""
        resp = self.show(cx)
        resp.content = Page(clear=False).line0(msg).data()
        return resp

    def goto(self, cx: dict, screen: str, msg: str | None = None, **updates) -> mp.PaviResponse:
        cx.update(screen=screen, page=0, **updates)
        return self.show(cx, msg)

    # -- accès à la partie ----------------------------------------------------

    def _game(self, cx: dict) -> tuple[Book, Engine, GameState]:
        book = self.books[cx["book"]]
        return book, Engine(book, self.dice_factory()), GameState.model_validate(cx["game"])

    def _store_game(self, cx: dict, state: GameState) -> None:
        cx["game"] = state.model_dump()
        if state.fin:
            self.store.delete_game(cx["pseudo"], cx["code"])  # une partie finie ne se reprend pas
        else:
            self.store.save_game(cx["pseudo"], cx["code"], cx["book"], cx["game"])

    # -- éléments de décor communs ----------------------------------------------

    def _title(self, p: Page, text: str, color: int = GOLD) -> None:
        """Bandeau de titre et sa frise."""
        p.bar(1, text, color=color)
        p.frieze(2, art.FRIEZE_DIAMOND, color=color)

    def _prompt(self, p: Page, label: str, field: int = 0) -> int:
        """Ligne d'invite : libellé, champ éventuel, touche ENVOI. Renvoie la colonne du champ."""
        p.text(PROMPT_ROW, 2, label)
        col = 3 + len(normalize(label))
        if field:
            p.text(PROMPT_ROW, col + field + 1, "+")
            p.text(PROMPT_ROW, col + field + 3, " ENVOI ", color=C.GREEN, inverse=True)
        else:
            p.text(PROMPT_ROW, col, " ENVOI ", color=C.GREEN, inverse=True)
        return col

    def _badge(self, p: Page, row: int, label: str) -> None:
        p.text(row, 2, f"{label:>2} ", color=GOLD, inverse=True)

    # ======================================================================
    # Accueil et catalogue
    # ======================================================================

    def _catalog(self) -> list[Book]:
        return sorted(self.books.values(), key=lambda b: normalize(b.titre).lower())

    def show_accueil(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        cx.update(screen="accueil", game=None)
        books = self._catalog()
        pages = max(1, -(-len(books) // CATALOG_PER_PAGE))
        page = cx["cat_page"] = min(cx.get("cat_page", 0), pages - 1)
        p = Page()
        p.art(1, art.BANNER_FAR, color=C.BLUE, col=1)
        p.art(1, art.BANNER_SKY, color=GOLD, col=1)
        p.art(1, art.BANNER_NEAR, color=C.WHITE, col=1)
        p.center(7, "3615 HEROS", double_height=True, double_width=True, color=GOLD)
        p.center(8, "Les livres dont vous êtes le héros", color=C.CYAN)
        p.frieze(9, art.FRIEZE_DIAMOND, color=GOLD)
        if not books:
            p.center(14, "Aucun grimoire sur les rayonnages.")
        row = 11
        start = page * CATALOG_PER_PAGE
        for i, book in enumerate(books[start:start + CATALOG_PER_PAGE], start + 1):
            self._badge(p, row, str(i))
            p.text(row, 6, normalize(book.titre)[:34])
            if book.auteur:
                p.text(row + 1, 6, normalize("par " + book.auteur)[:34], color=C.GREEN)
            row += 2
        if pages > 1:
            p.text(19, 31, f"Page {page + 1}/{pages}", color=C.GREEN)
        self._badge(p, 20, "R")
        p.text(20, 6, "Reprendre une partie sauvegardée")
        p.frieze(SEP_ROW, art.FRIEZE_CHAIN, color=C.BLUE)
        col = self._prompt(p, "Votre choix :", field=2)
        keys = [("Aide", "GUIDE")]
        if pages > 1:
            keys.insert(0, ("Autres livres", "SUITE"))
        p.keys(KEYS_ROW, keys)
        if msg:
            p.line0(msg)
        return mp.PaviResponse(p.data(), mp.InputTxt(col, PROMPT_ROW, 2, keys=(
            mp.ENVOI, mp.SUITE, mp.RETOUR, mp.GUIDE, mp.REPETITION, mp.SOMMAIRE)))

    def on_accueil(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        books = self._catalog()
        pages = max(1, -(-len(books) // CATALOG_PER_PAGE))
        if req.fctn == mp.GUIDE:
            return self.goto(cx, "guide", back="accueil")
        if req.fctn in (mp.SUITE, mp.RETOUR):
            page = cx.get("cat_page", 0) + (1 if req.fctn == mp.SUITE else -1)
            if not 0 <= page < pages:
                return self.notice(cx, "Pas d'autre page")
            cx["cat_page"] = page
            return self.show_accueil(cx)
        if req.fctn != mp.ENVOI:
            return self.notice(cx, "Tapez un numéro puis ENVOI")
        choice = req.text.upper()
        if choice == "R":
            return self.goto(cx, "reprise_pseudo", essais=0)
        if choice.isdigit() and 1 <= int(choice) <= len(books):
            return self.goto(cx, "livre", book=books[int(choice) - 1].id)
        return self.notice(cx, "Choix incorrect")

    # ======================================================================
    # Présentation d'un livre
    # ======================================================================

    def show_livre(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        book = self.books[cx["book"]]
        p = Page()
        self._title(p, book.titre)
        row = MENU_TOP
        if book.auteur:
            p.text(row, BODY_COL, normalize("par " + book.auteur)[:BODY_W], color=C.GREEN)
            row += 2
        lines = wrap(book.resume or "Un livre dont vous êtes le héros.", BODY_W)[:20 - row]
        p.lines(row, lines, col=BODY_COL)
        p.text(21, BODY_COL, f"{len(book.paragraphes)} paragraphes", color=C.GREEN)
        p.frieze(SEP_ROW, art.FRIEZE_CHAIN, color=C.BLUE)
        self._prompt(p, "Pousser la porte :")
        p.keys(KEYS_ROW, [("Règles", "GUIDE"), ("Catalogue", "SOMMAIRE")])
        if msg:
            p.line0(msg)
        return mp.PaviResponse(p.data())

    def on_livre(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        if req.fctn in (mp.ENVOI, mp.SUITE):
            return self.goto(cx, "pseudo")
        if req.fctn == mp.GUIDE:
            return self.goto(cx, "guide", back="livre")
        if req.fctn in (mp.SOMMAIRE, mp.RETOUR):
            return self.show_accueil(cx)
        return self.notice(cx, "ENVOI pour commencer")

    # ======================================================================
    # Création du personnage
    # ======================================================================

    def show_pseudo(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        p = Page()
        self._title(p, "NOUVEAU HEROS")
        p.lines(5, wrap("Sous quel nom entrerez-vous dans la légende ? 2 à 10 lettres ou chiffres, "
                        "sans accent.", BODY_W), col=BODY_COL)
        p.lines(9, wrap("Avec le code qui va vous être attribué, ce nom vous permettra de reprendre "
                        "votre partie plus tard.", BODY_W), col=BODY_COL, color=C.GREEN)
        p.text(14, BODY_COL, "Pseudo :")
        p.text(14, 23, "+")
        p.text(14, 25, " ENVOI ", color=C.GREEN, inverse=True)
        p.keys(KEYS_ROW, [("Catalogue", "SOMMAIRE")])
        if msg:
            p.line0(msg)
        return mp.PaviResponse(p.data(), mp.InputTxt(11, 14, 10, keys=(mp.ENVOI, mp.SOMMAIRE, mp.REPETITION)))

    def on_pseudo(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        if req.fctn == mp.SOMMAIRE:
            return self.show_accueil(cx)
        pseudo = clean_pseudo(req.text)
        if req.fctn != mp.ENVOI or pseudo is None:
            return self.notice(cx, "Pseudo : 2 à 10 lettres ou chiffres")
        book = self.books[cx["book"]]
        state, events = Engine(book, self.dice_factory()).new_game(pseudo)
        cx.update(pseudo=pseudo, code=self.store.new_code(pseudo), journal=events)
        self._store_game(cx, state)
        return self.goto(cx, "perso")

    def show_perso(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        book, _, state = self._game(cx)
        p = Page()
        self._title(p, "LES DES ONT PARLE")
        p.center(5, state.perso.nom, double_height=True, color=GOLD)
        row = self._stats_table(p, 7, book, state)
        inv = wrap("Vous emportez : " + (", ".join(state.perso.inventaire) or "rien") + ".", BODY_W)[:2]
        p.lines(row + 1, inv, col=BODY_COL)
        p.frame(15, 5, 5, 32, color=GOLD)
        p.center(16, "VOTRE CODE")
        p.center(18, cx["code"], double_height=True, double_width=True, color=GOLD)
        p.lines(20, wrap("Notez-le : avec votre pseudo, il permet de reprendre la partie.", BODY_W),
                col=BODY_COL, color=C.GREEN)
        self._prompt(p, "Entrer dans l'aventure :")
        if msg:
            p.line0(msg)
        return mp.PaviResponse(p.data())

    def on_perso(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        if req.fctn in (mp.ENVOI, mp.SUITE):
            return self.goto(cx, "jeu")
        if req.fctn == mp.GUIDE:
            return self.goto(cx, "guide", back="perso")
        return self.notice(cx, "ENVOI pour commencer")

    def _stats_table(self, p: Page, row: int, book: Book, state: GameState) -> int:
        """Une ligne par caractéristique : nom, jauge, valeur / total de départ."""
        for name, value in state.perso.stats.items():
            initial = state.perso.initial.get(name, value)
            color = life_color(value, initial) if name == book.personnage.stat_vie else C.CYAN
            p.text(row, 4, normalize(name).upper()[:10])
            p.gauge(row, 15, 14, value, initial, color=color)
            p.text(row, 31, f"{value:>2}", color=GOLD)
            p.text(row, 34, f"/ {initial}", color=C.GREEN)
            row += 1
        return row

    # ======================================================================
    # Reprise d'une partie
    # ======================================================================

    def show_reprise_pseudo(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        p = Page()
        self._title(p, "REPRENDRE UNE PARTIE")
        p.lines(5, wrap("Qui frappe à la porte ? Tapez le pseudo de votre héros.", BODY_W), col=BODY_COL)
        p.text(9, BODY_COL, "Pseudo :")
        p.text(9, 23, "+")
        p.text(9, 25, " ENVOI ", color=C.GREEN, inverse=True)
        p.keys(KEYS_ROW, [("Accueil", "SOMMAIRE")])
        if msg:
            p.line0(msg)
        return mp.PaviResponse(p.data(), mp.InputTxt(11, 9, 10, keys=(mp.ENVOI, mp.SOMMAIRE, mp.REPETITION)))

    def on_reprise_pseudo(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        if req.fctn == mp.SOMMAIRE:
            return self.show_accueil(cx)
        pseudo = clean_pseudo(req.text)
        if req.fctn != mp.ENVOI or pseudo is None:
            return self.notice(cx, "Pseudo : 2 à 10 lettres ou chiffres")
        return self.goto(cx, "reprise_code", pseudo=pseudo)

    def show_reprise_code(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        p = Page()
        self._title(p, "REPRENDRE UNE PARTIE")
        p.text(5, BODY_COL, "Pseudo : " + cx["pseudo"], color=C.GREEN)
        p.lines(7, wrap("Et le mot de passe ? Tapez votre code à 4 chiffres.", BODY_W), col=BODY_COL)
        p.text(10, BODY_COL, "Code   :")
        p.text(10, 17, "+")
        p.text(10, 19, " ENVOI ", color=C.GREEN, inverse=True)
        p.keys(KEYS_ROW, [("Accueil", "SOMMAIRE")])
        if msg:
            p.line0(msg)
        return mp.PaviResponse(p.data(), mp.InputTxt(11, 10, 4, keys=(mp.ENVOI, mp.SOMMAIRE, mp.REPETITION)))

    def on_reprise_code(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        if req.fctn == mp.SOMMAIRE:
            return self.show_accueil(cx)
        code = clean_code(req.text)
        saved = self.store.load_game(cx["pseudo"], code) if code and req.fctn == mp.ENVOI else None
        if saved is None or saved[0] not in self.books:
            cx["essais"] = cx.get("essais", 0) + 1
            if cx["essais"] >= MAX_TRIES:
                return self.show_accueil(cx, "Partie introuvable")
            return self.notice(cx, "Pseudo ou code inconnu")
        cx.update(book=saved[0], code=code, game=saved[1], journal=["Vous reprenez votre aventure."])
        return self.goto(cx, "jeu")

    # ======================================================================
    # Paragraphe
    # ======================================================================

    def _header(self, p: Page, book: Book, state: GameState, title: str | None = None,
                color: int = GOLD) -> None:
        """Lignes 1 à 3 : titre et numéro, nom et caractéristiques, jauge de vie."""
        num = f"#{state.paragraphe}"
        p.text(1, 1, (" " + normalize(title or book.titre))[:C.COLS - len(num) - 2].ljust(C.COLS - len(num) - 1)
               + num + " ", color=color, inverse=True)
        vie = book.personnage.stat_vie
        perso = state.perso
        others = "  ".join(f"{normalize(k).upper()[:3]} {v}" for k, v in perso.stats.items() if k != vie)[:24]
        p.text(2, 2, normalize(perso.nom)[:12], color=GOLD)
        if others:
            p.text(2, C.COLS - len(others), others, color=C.CYAN)
        value, initial = perso.stats.get(vie, 0), perso.initial.get(vie, 0)
        p.text(3, 2, normalize(vie).upper()[:9], color=C.GREEN)
        p.gauge(3, 12, 20, value, initial, color=life_color(value, initial))
        p.text(3, 33, f"{value}/{initial}"[:7], color=GOLD)

    def _jeu_pages(self, cx: dict, book: Book, engine: Engine, state: GameState):
        para = engine.paragraph(state)
        actions = engine.actions(state)
        art_rows = len(mosaic(para.illustration)) if para.illustration else 0
        if art_rows > 8:
            art_rows = 0  # illustration trop haute : on s'en passe plutôt que d'échouer
        blocks: list[list[Line]] = []
        for event in cx.get("journal") or []:
            blocks += text_blocks(event, GOLD)
        if blocks:
            blocks.append([BLANK])
        blocks += text_blocks(para.texte)
        if actions:
            blocks.append([BLANK])
            if state.ennemi is not None:
                e = state.ennemi
                blocks.append([(f"{e.nom} : habileté {e.habilete}, endurance {e.endurance}"[:BODY_W], C.RED, None)])
            for i, action in enumerate(actions, 1):
                lines = wrap(action.libelle, BODY_W - 5)
                blocks.append([(lines[0], C.CYAN, str(i))] + [(l, C.CYAN, "") for l in lines[1:]])
        first = BODY_ROWS - (art_rows + 1) if art_rows else None
        return para, actions, art_rows, pack(blocks, BODY_ROWS, first)

    def _body(self, p: Page, top: int, lines: list[Line]) -> None:
        for i, (text, color, badge) in enumerate(lines):
            if badge is None:
                p.text(top + i, BODY_COL, text, color=color)
            else:  # un choix : écusson numéroté, libellé en retrait
                if badge:
                    self._badge(p, top + i, badge)
                p.text(top + i, BODY_COL + 4, text, color=color)

    def show_jeu(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        book, engine, state = self._game(cx)
        para, actions, art_rows, pages = self._jeu_pages(cx, book, engine, state)
        page = cx["page"] = max(0, min(cx.get("page", 0), len(pages) - 1))
        last = page == len(pages) - 1
        p = Page()
        self._header(p, book, state)
        top = BODY_TOP
        if page == 0 and art_rows:
            p.art(top, para.illustration, color=C.CYAN)
            top += art_rows + 1
        self._body(p, top, pages[page])
        p.frieze(SEP_ROW, art.FRIEZE_CHAIN, color=C.BLUE)
        if len(pages) > 1:
            p.text(PROMPT_ROW, 33, f"{page + 1}/{len(pages)}".rjust(7), color=C.GREEN)
        if msg:
            p.line0(msg)
        if last and actions:
            col = self._prompt(p, "Que faites-vous ?", field=2)
            p.keys(KEYS_ROW, [("Feuille", "SOMMAIRE"), ("Règles", "GUIDE")])
            return mp.PaviResponse(p.data(), mp.InputTxt(col, PROMPT_ROW, 2, keys=(
                mp.ENVOI, mp.RETOUR, mp.SOMMAIRE, mp.GUIDE, mp.REPETITION)))
        p.keys(KEYS_ROW, [("Suite", "SUITE"), ("Feuille", "SOMMAIRE")])
        return mp.PaviResponse(p.data())

    def on_jeu(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        book, engine, state = self._game(cx)
        _, actions, _, pages = self._jeu_pages(cx, book, engine, state)
        page, last = cx.get("page", 0), len(pages) - 1
        if req.fctn == mp.SOMMAIRE:
            return self.goto(cx, "feuille", back="jeu", back_page=page)
        if req.fctn == mp.GUIDE:
            return self.goto(cx, "guide", back="jeu", back_page=page)
        if req.fctn == mp.RETOUR:
            if page == 0:
                return self.notice(cx, "Première page")
            cx["page"] = page - 1
            return self.show_jeu(cx)
        if req.fctn not in (mp.ENVOI, mp.SUITE):
            return self.notice(cx, "Touche sans effet ici")
        if page < last:
            cx["page"] = page + 1
            return self.show_jeu(cx)
        if state.fin:
            return self.goto(cx, "fin")
        if req.fctn == mp.SUITE:
            return self.notice(cx, "Tapez votre choix puis ENVOI")
        return self._act(cx, engine, state, actions, req.text)

    def _act(self, cx, engine: Engine, state: GameState, actions, typed: str) -> mp.PaviResponse:
        if typed == "" and (len(actions) == 1 or cx["screen"] == "combat"):
            typed = "1"  # ENVOI seul : l'unique action, ou « Combattre »
        if not typed.isdigit() or not 1 <= int(typed) <= len(actions):
            return self.notice(cx, f"Tapez un numéro de 1 à {len(actions)}")
        before = state.paragraphe
        try:
            events = engine.act(state, actions[int(typed) - 1])
        except GameError:
            return self.notice(cx, "Action impossible")
        cx["journal"] = events
        self._store_game(cx, state)
        if state.paragraphe == before and state.fin:
            return self.goto(cx, "fin")
        if state.paragraphe == before and state.ennemi is not None:
            return self.goto(cx, "combat")
        return self.goto(cx, "jeu")

    # ======================================================================
    # Combat
    # ======================================================================

    def show_combat(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        book, engine, state = self._game(cx)
        enemy, actions = state.ennemi, engine.actions(state)
        combat = engine.paragraph(state).combat
        vie = book.personnage.stat_vie
        perso = state.perso
        p = Page()
        num = f"#{state.paragraphe}"
        p.text(1, 1, " COMBAT".ljust(C.COLS - len(num) - 1) + num + " ", color=C.RED, inverse=True)
        p.art(3, art.SWORDS, color=GOLD)
        p.center(10, normalize(enemy.nom)[:20], double_height=True, double_width=True, color=C.RED)
        rows = (
            (12, perso.nom, GOLD, perso.stats.get("habilete", 0), perso.stats[vie], perso.initial[vie]),
            (13, enemy.nom, C.RED, enemy.habilete, enemy.endurance, max(combat.endurance, enemy.endurance)),
        )
        for row, name, color, skill, life, life_max in rows:
            p.text(row, BODY_COL, normalize(name)[:11], color=color)
            p.text(row, 14, f"HAB {skill}", color=C.CYAN)
            p.gauge(row, 22, 11, life, life_max, color=life_color(life, life_max))
            p.text(row, 34, f"{life}/{life_max}"[:6], color=GOLD)
        journal = [l for e in cx.get("journal") or [] for l in wrap(e, BODY_W)][:4]
        p.lines(15, journal, col=BODY_COL, color=GOLD)
        for i, action in enumerate(actions[:2], 1):
            self._badge(p, 19 + i, str(i))
            p.text(19 + i, BODY_COL + 4, normalize(action.libelle)[:BODY_W - 5], color=C.CYAN)
        p.frieze(SEP_ROW, art.FRIEZE_CHAIN, color=C.RED)
        col = self._prompt(p, "Que faites-vous ?", field=2)
        p.keys(KEYS_ROW, [("Feuille", "SOMMAIRE"), ("Règles", "GUIDE")])
        if msg:
            p.line0(msg)
        return mp.PaviResponse(p.data(), mp.InputTxt(col, PROMPT_ROW, 2, keys=(
            mp.ENVOI, mp.SOMMAIRE, mp.GUIDE, mp.REPETITION)))

    def on_combat(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        book, engine, state = self._game(cx)
        if req.fctn == mp.SOMMAIRE:
            return self.goto(cx, "feuille", back="combat", back_page=0)
        if req.fctn == mp.GUIDE:
            return self.goto(cx, "guide", back="combat", back_page=0)
        if req.fctn != mp.ENVOI:
            return self.notice(cx, "Tapez votre choix puis ENVOI")
        return self._act(cx, engine, state, engine.actions(state), req.text)

    # ======================================================================
    # Feuille d'aventure
    # ======================================================================

    def show_feuille(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        book, _, state = self._game(cx)
        p = Page()
        self._title(p, "FEUILLE D'AVENTURE")
        p.center(5, state.perso.nom, double_height=True, color=GOLD)
        row = self._stats_table(p, 7, book, state) + 1
        p.text(row, BODY_COL, "BESACE", color=C.GREEN)
        lines = wrap(", ".join(state.perso.inventaire) or "vide", BODY_W - 2)
        notes = [l for flag, label in book.flags_visibles.items() if flag in state.perso.flags
                 for l in wrap("* " + label, BODY_W)]
        room = 19 - (row + 1)
        lines = lines[:max(1, room - min(len(notes), 3))]
        p.lines(row + 1, lines, col=BODY_COL + 2)
        row += 1 + len(lines)
        notes = notes[:max(0, 19 - row)]
        p.lines(row + 1 if notes else row, notes, col=BODY_COL, color=C.CYAN)
        p.text(20, BODY_COL, f"Pseudo {cx['pseudo']}   Code {cx['code']}", color=C.GREEN)
        p.frieze(SEP_ROW, art.FRIEZE_CHAIN, color=C.BLUE)
        p.text(PROMPT_ROW, 2, "Quitter la partie : tapez 0")
        p.text(PROMPT_ROW, 32, "+")
        p.text(PROMPT_ROW, 34, "ENVOI", color=C.GREEN, inverse=True)
        p.keys(KEYS_ROW, [("Retour au jeu", "SOMMAIRE")])
        if msg:
            p.line0(msg)
        return mp.PaviResponse(p.data(), mp.InputTxt(30, PROMPT_ROW, 1, keys=(
            mp.ENVOI, mp.SOMMAIRE, mp.RETOUR, mp.SUITE, mp.GUIDE, mp.REPETITION)))

    def on_feuille(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        if req.fctn == mp.ENVOI and req.text == "0":
            return self.show_accueil(cx, "Partie sauvegardée")
        if req.fctn == mp.GUIDE:
            cx.update(screen="guide", page=0)  # on garde le même écran de retour
            return self.show(cx)
        return self._back(cx)

    def _back(self, cx: dict) -> mp.PaviResponse:
        cx.update(screen=cx.get("back") or "accueil", page=cx.get("back_page", 0))
        if cx["screen"] == "accueil":
            return self.show_accueil(cx)
        return self.show(cx)

    # ======================================================================
    # Guide (règles du livre, ou aide du service depuis l'accueil)
    # ======================================================================

    def _guide_pages(self, cx: dict) -> tuple[str, list[list[str]]]:
        if cx.get("back") == "accueil" or not cx.get("book"):
            title, text = "MODE D'EMPLOI", AIDE
        else:
            book = self.books[cx["book"]]
            title, text = "REGLES DU JEU", (book.regles or "Ce livre n'a pas de règle particulière.") + "\n" + AIDE
        return title, paginate(wrap(text, BODY_W), MENU_ROWS)

    def show_guide(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        title, pages = self._guide_pages(cx)
        page = cx["page"] = max(0, min(cx.get("page", 0), len(pages) - 1))
        p = Page()
        self._title(p, title)
        p.lines(MENU_TOP, pages[page], col=BODY_COL)
        p.frieze(SEP_ROW, art.FRIEZE_CHAIN, color=C.BLUE)
        if len(pages) > 1:
            p.text(PROMPT_ROW, 33, f"{page + 1}/{len(pages)}".rjust(7), color=C.GREEN)
        keys = [("Retour", "SOMMAIRE")]
        if page < len(pages) - 1:
            keys.insert(0, ("Suite", "SUITE"))
        p.keys(KEYS_ROW, keys)
        if msg:
            p.line0(msg)
        return mp.PaviResponse(p.data())

    def on_guide(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        _, pages = self._guide_pages(cx)
        page = cx.get("page", 0)
        if req.fctn in (mp.SUITE, mp.ENVOI) and page < len(pages) - 1:
            cx["page"] = page + 1
            return self.show_guide(cx)
        if req.fctn == mp.RETOUR and page > 0:
            cx["page"] = page - 1
            return self.show_guide(cx)
        if req.fctn == mp.SUITE:
            return self.notice(cx, "Dernière page")
        return self._back(cx)

    # ======================================================================
    # Mort et victoire
    # ======================================================================

    def show_fin(self, cx: dict, msg: str | None = None) -> mp.PaviResponse:
        book, _, state = self._game(cx)
        win = state.fin == "victoire"
        color = GOLD if win else C.RED
        nom = state.perso.nom
        pick = (len(nom) + state.paragraphe) % 100  # même phrase si l'écran est réaffiché
        p = Page().bar(1, book.titre, color=color)
        p.art(3, art.CROWN if win else art.SKULL, color=color)
        p.center(9, "VICTOIRE !" if win else "VOUS ETES MORT", double_height=True, double_width=True, color=color)
        p.frieze(10, art.FRIEZE_DIAMOND if win else art.FRIEZE_TEETH, color=color, col=6, width=30)
        if win:
            text = f"{nom} a triomphé de « {book.titre} ». {LOUANGES[pick % len(LOUANGES)]}"
        else:
            text = (f"L'aventure de {nom} s'achève au paragraphe {state.paragraphe}. "
                    f"{EPITAPHES[pick % len(EPITAPHES)]}")
        lines = [l for e in cx.get("journal") or [] for l in wrap(e, BODY_W)][-4:] if not win else []
        p.lines(12, lines, col=BODY_COL, color=GOLD)
        p.lines(12 + len(lines) + (1 if lines else 0), wrap(text, BODY_W)[:4], col=BODY_COL)
        vie = book.personnage.stat_vie
        bilan = "  ".join(f"{normalize(k).upper()[:3]} {v}" for k, v in state.perso.stats.items() if win or k != vie)
        p.center(21, bilan[:BODY_W], color=C.GREEN)
        p.frieze(SEP_ROW, art.FRIEZE_CHAIN, color=color)
        self._prompt(p, "Retour à l'accueil :")
        if msg:
            p.line0(msg)
        return mp.PaviResponse(p.data())

    def on_fin(self, cx: dict, req: mp.PaviRequest) -> mp.PaviResponse:
        if req.fctn in (mp.ENVOI, mp.SUITE, mp.SOMMAIRE):
            return self.show_accueil(cx)
        return self.notice(cx, "ENVOI pour revenir à l'accueil")
