"""Modèles de données d'un livre-jeu et d'une partie (indépendants du Minitel)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .dice import parse_expr


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(_Strict):
    """Une seule clause par condition ; une liste de conditions est un ET."""

    objet: str | None = None
    sans_objet: str | None = None
    flag: str | None = None
    sans_flag: str | None = None
    stat: str | None = None
    min: int | None = None
    max: int | None = None

    @model_validator(mode="after")
    def _une_clause(self):
        clauses = [self.objet, self.sans_objet, self.flag, self.sans_flag, self.stat]
        if sum(c is not None for c in clauses) != 1:
            raise ValueError("une condition porte sur exactement un objet, flag ou stat")
        if self.stat is not None and self.min is None and self.max is None:
            raise ValueError("condition sur une stat : préciser min et/ou max")
        if self.stat is None and (self.min is not None or self.max is not None):
            raise ValueError("min/max ne s'emploient qu'avec stat")
        return self


class Effect(_Strict):
    """Effet appliqué à l'entrée d'un paragraphe."""

    stat: str | None = None
    delta: int | None = None
    gagne: str | None = None
    perd: str | None = None
    pose_flag: str | None = None
    retire_flag: str | None = None

    @model_validator(mode="after")
    def _un_effet(self):
        kinds = [self.stat, self.gagne, self.perd, self.pose_flag, self.retire_flag]
        if sum(k is not None for k in kinds) != 1:
            raise ValueError("un effet fait exactement une chose")
        if (self.stat is None) != (self.delta is None):
            raise ValueError("stat et delta vont ensemble")
        return self


class Choice(_Strict):
    libelle: str
    vers: int
    si: list[Condition] = Field(default_factory=list)


class StatTest(_Strict):
    """Test sous 2d6 : réussi si le tirage est <= à la stat."""

    stat: str
    reussite: int
    echec: int
    libelle: str | None = None


class Combat(_Strict):
    ennemi: str
    habilete: int
    endurance: int
    victoire: int
    defaite: int | None = None  # None : mort « générique » sans paragraphe dédié
    fuite: int | None = None  # None : fuite impossible


class Paragraph(_Strict):
    texte: str
    illustration: list[str] | None = None  # lignes de semi-graphique, voir render
    effets: list[Effect] = Field(default_factory=list)
    choix: list[Choice] = Field(default_factory=list)
    test: StatTest | None = None
    combat: Combat | None = None
    fin: Literal["victoire", "mort"] | None = None

    @model_validator(mode="after")
    def _une_sortie(self):
        modes = [bool(self.choix), self.test is not None, self.combat is not None, self.fin is not None]
        if sum(modes) > 1:
            raise ValueError("un paragraphe a soit des choix, soit un test, soit un combat, soit une fin")
        return self

    def destinations(self) -> list[int]:
        """Tous les paragraphes vers lesquels celui-ci peut mener."""
        out = [c.vers for c in self.choix]
        if self.test:
            out += [self.test.reussite, self.test.echec]
        if self.combat:
            out += [d for d in (self.combat.victoire, self.combat.defaite, self.combat.fuite) if d is not None]
        return out


class CharacterRules(_Strict):
    stats: dict[str, str]  # nom de stat -> expression de dés, ex. habilete: "1d6+6"
    inventaire: list[str] = Field(default_factory=list)
    stat_vie: str = "endurance"  # la stat qui tue quand elle tombe à 0

    @model_validator(mode="after")
    def _check(self):
        for expr in self.stats.values():
            parse_expr(expr)
        if self.stat_vie not in self.stats:
            raise ValueError(f"stat_vie {self.stat_vie!r} absente des stats")
        return self


class Book(_Strict):
    id: str = ""
    titre: str
    auteur: str = ""
    resume: str = ""
    regles: str = ""
    systeme_combat: str = "defis_fantastiques"
    personnage: CharacterRules
    depart: int = 1
    flags_visibles: dict[str, str] = Field(default_factory=dict)  # flag -> libellé affiché
    paragraphes: dict[int, Paragraph]

    @model_validator(mode="after")
    def _check(self):
        if self.depart not in self.paragraphes:
            raise ValueError(f"paragraphe de départ {self.depart} inexistant")
        return self


class Character(BaseModel):
    nom: str
    stats: dict[str, int]
    initial: dict[str, int]
    inventaire: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class EnemyState(BaseModel):
    nom: str
    habilete: int
    endurance: int


class GameState(BaseModel):
    """État complet d'une partie, sérialisable (sauvegarde)."""

    livre: str
    perso: Character
    paragraphe: int
    ennemi: EnemyState | None = None  # combat en cours
    fin: Literal["victoire", "mort"] | None = None


def load_book(path: str | Path) -> Book:
    """Charge un book.yaml (ou le dossier qui le contient)."""
    path = Path(path)
    if path.is_dir():
        path = path / "book.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} : le livre doit être un dictionnaire YAML")
    data.setdefault("id", path.parent.name)
    return Book.model_validate(data)
