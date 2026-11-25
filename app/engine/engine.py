"""Logique de jeu pure : aucune notion d'écran, de Minitel ou de HTTP.

Le moteur fait évoluer un GameState et renvoie à chaque action la liste des
événements survenus (lignes de texte brut), que l'appelant affiche comme il veut.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .dice import Dice
from .models import Book, Character, Choice, Condition, EnemyState, GameState, Paragraph


class GameError(Exception):
    """Action impossible dans l'état courant."""


# --------------------------------------------------------------------------
# Systèmes de combat interchangeables
# --------------------------------------------------------------------------

class CombatSystem(Protocol):
    def assaut(self, perso: Character, ennemi: EnemyState, dice: Dice) -> tuple[int, int, list[str]]:
        """Joue un assaut. Renvoie (dégâts au héros, dégâts à l'ennemi, récit)."""

    def fuite(self, perso: Character, ennemi: EnemyState, dice: Dice) -> tuple[int, list[str]]:
        """Prix de la fuite. Renvoie (dégâts au héros, récit)."""


class DefisFantastiques:
    """2d6 + HABILETÉ de chaque côté ; le plus fort blesse l'autre de 2 points."""

    DEGATS = 2

    def assaut(self, perso, ennemi, dice):
        fa_heros = dice.roll(2, 6) + perso.stats.get("habilete", 0)
        fa_ennemi = dice.roll(2, 6) + ennemi.habilete
        recit = [f"Votre force d'attaque : {fa_heros}. {ennemi.nom} : {fa_ennemi}."]
        if fa_heros > fa_ennemi:
            recit.append(f"Vous blessez {ennemi.nom} !")
            return 0, self.DEGATS, recit
        if fa_ennemi > fa_heros:
            recit.append(f"{ennemi.nom} vous blesse !")
            return self.DEGATS, 0, recit
        recit.append("Vos armes s'entrechoquent sans résultat.")
        return 0, 0, recit

    def fuite(self, perso, ennemi, dice):
        return self.DEGATS, [f"En fuyant, vous recevez un dernier coup de {ennemi.nom}."]


COMBAT_SYSTEMS: dict[str, type] = {"defis_fantastiques": DefisFantastiques}


def register_combat_system(name: str, cls: type) -> None:
    COMBAT_SYSTEMS[name] = cls


# --------------------------------------------------------------------------
# Actions proposées au joueur
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Action:
    kind: Literal["choix", "test", "assaut", "fuite"]
    libelle: str
    index: int = 0  # indice dans paragraph.choix pour kind == "choix"


def condition_ok(cond: Condition, perso: Character) -> bool:
    if cond.objet is not None:
        return cond.objet in perso.inventaire
    if cond.sans_objet is not None:
        return cond.sans_objet not in perso.inventaire
    if cond.flag is not None:
        return cond.flag in perso.flags
    if cond.sans_flag is not None:
        return cond.sans_flag not in perso.flags
    value = perso.stats.get(cond.stat, 0)
    if cond.min is not None and value < cond.min:
        return False
    if cond.max is not None and value > cond.max:
        return False
    return True


def choice_ok(choice: Choice, perso: Character) -> bool:
    return all(condition_ok(c, perso) for c in choice.si)


# --------------------------------------------------------------------------
# Moteur
# --------------------------------------------------------------------------

class Engine:
    def __init__(self, book: Book, dice: Dice | None = None, combat: CombatSystem | None = None):
        self.book = book
        self.dice = dice or Dice()
        if combat is None:
            try:
                combat = COMBAT_SYSTEMS[book.systeme_combat]()
            except KeyError:
                raise GameError(f"système de combat inconnu : {book.systeme_combat}") from None
        self.combat = combat

    # -- création ---------------------------------------------------------

    def new_character(self, nom: str) -> Character:
        stats = {k: self.dice.roll_expr(expr) for k, expr in self.book.personnage.stats.items()}
        return Character(nom=nom, stats=dict(stats), initial=dict(stats),
                         inventaire=list(self.book.personnage.inventaire))

    def new_game(self, nom: str, perso: Character | None = None) -> tuple[GameState, list[str]]:
        perso = perso or self.new_character(nom)
        state = GameState(livre=self.book.id, perso=perso, paragraphe=self.book.depart)
        return state, self._enter(state, self.book.depart)

    # -- lecture ----------------------------------------------------------

    def paragraph(self, state: GameState) -> Paragraph:
        return self.book.paragraphes[state.paragraphe]

    def actions(self, state: GameState) -> list[Action]:
        """Ce que le joueur peut faire maintenant. Vide si la partie est finie."""
        if state.fin:
            return []
        para = self.paragraph(state)
        if state.ennemi is not None:
            out = [Action("assaut", "Combattre")]
            if para.combat and para.combat.fuite is not None:
                out.append(Action("fuite", "Fuir"))
            return out
        if para.test is not None:
            return [Action("test", para.test.libelle or f"Tester votre {para.test.stat}")]
        return [Action("choix", c.libelle, i) for i, c in enumerate(para.choix)
                if choice_ok(c, state.perso)]

    # -- actions ----------------------------------------------------------

    def act(self, state: GameState, action: Action) -> list[str]:
        """Applique une action renvoyée par actions(). Renvoie le récit."""
        if action not in self.actions(state):
            raise GameError("action indisponible")
        para = self.paragraph(state)
        if action.kind == "choix":
            return self._enter(state, para.choix[action.index].vers)
        if action.kind == "test":
            return self._run_test(state, para)
        if action.kind == "assaut":
            return self._assaut(state, para)
        return self._fuite(state, para)

    def _run_test(self, state: GameState, para: Paragraph) -> list[str]:
        test = para.test
        perso = state.perso
        tirage = self.dice.roll(2, 6)
        valeur = perso.stats.get(test.stat, 0)
        ok = tirage <= valeur
        recit = [f"Vous lancez les dés : {tirage} contre {test.stat} {valeur}.",
                 "Réussi !" if ok else "Raté !"]
        if test.stat == "chance":  # règle Défis Fantastiques : la chance s'use
            perso.stats["chance"] = max(0, valeur - 1)
        return recit + self._enter(state, test.reussite if ok else test.echec)

    def _assaut(self, state: GameState, para: Paragraph) -> list[str]:
        perso, ennemi, vie = state.perso, state.ennemi, self.book.personnage.stat_vie
        d_heros, d_ennemi, recit = self.combat.assaut(perso, ennemi, self.dice)
        perso.stats[vie] = max(0, perso.stats[vie] - d_heros)
        ennemi.endurance = max(0, ennemi.endurance - d_ennemi)
        if ennemi.endurance == 0:
            state.ennemi = None
            recit.append(f"{ennemi.nom} s'effondre. Vous êtes vainqueur !")
            return recit + self._enter(state, para.combat.victoire)
        if perso.stats[vie] == 0:
            state.ennemi = None
            recit.append("Vous succombez à vos blessures.")
            if para.combat.defaite is not None:
                return recit + self._enter(state, para.combat.defaite, vivant=False)
            state.fin = "mort"
        return recit

    def _fuite(self, state: GameState, para: Paragraph) -> list[str]:
        perso, vie = state.perso, self.book.personnage.stat_vie
        degats, recit = self.combat.fuite(perso, state.ennemi, self.dice)
        perso.stats[vie] = max(0, perso.stats[vie] - degats)
        state.ennemi = None
        if perso.stats[vie] == 0:
            recit.append("Ce coup vous est fatal.")
            state.fin = "mort"
            return recit
        return recit + self._enter(state, para.combat.fuite)

    # -- entrée dans un paragraphe -----------------------------------------

    def _enter(self, state: GameState, pid: int, vivant: bool = True) -> list[str]:
        if pid not in self.book.paragraphes:
            raise GameError(f"paragraphe {pid} inexistant")
        state.paragraphe = pid
        state.ennemi = None
        para = self.book.paragraphes[pid]
        perso, vie = state.perso, self.book.personnage.stat_vie
        recit: list[str] = []
        for eff in para.effets:
            recit += self._apply(eff, perso)
        if para.fin is not None:
            state.fin = para.fin
        elif perso.stats.get(vie, 1) <= 0:
            # mort par effet, ou paragraphe de défaite qui n'est pas marqué fin
            state.fin = "mort"
            if vivant:
                recit.append("Vos forces vous abandonnent.")
        elif para.combat is not None:
            c = para.combat
            state.ennemi = EnemyState(nom=c.ennemi, habilete=c.habilete, endurance=c.endurance)
        return recit

    def _apply(self, eff, perso: Character) -> list[str]:
        if eff.stat is not None:
            avant = perso.stats.get(eff.stat, 0)
            apres = max(0, avant + eff.delta)
            if eff.delta > 0:  # on ne dépasse jamais son total de départ
                apres = min(apres, max(avant, perso.initial.get(eff.stat, apres)))
            perso.stats[eff.stat] = apres
            if apres == avant:
                return []
            return [f"{eff.stat.capitalize()} {apres - avant:+d} (reste {apres})."]
        if eff.gagne is not None:
            if eff.gagne in perso.inventaire:
                return []
            perso.inventaire.append(eff.gagne)
            return [f"Vous obtenez : {eff.gagne}."]
        if eff.perd is not None:
            if eff.perd not in perso.inventaire:
                return []
            perso.inventaire.remove(eff.perd)
            return [f"Vous perdez : {eff.perd}."]
        if eff.pose_flag is not None:
            if eff.pose_flag not in perso.flags:
                perso.flags.append(eff.pose_flag)
            return []
        if eff.retire_flag in perso.flags:
            perso.flags.remove(eff.retire_flag)
        return []
