"""Adaptateur du protocole MiniPavi : le seul module couplé à la passerelle.

Tout ce qui est propre à MiniPavi (noms de clés JSON, base64, commandes de
saisie, URL de l'émulateur) vit ici. Voir docs/minipavi-protocol.md.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

CLIENT_VERSION = "1.1"
USER_AGENT_MARK = "MiniPAVI"
GATEWAY_WSS = "wss://go.minipavi.fr:8181"
EMULATOR_URL = "https://www.minipavi.fr/emulminitel/index.php"
MAX_CONTEXT = 64000      # la passerelle tronque le contexte à 64 000 caractères
MAX_CONTENT = 100_000    # et abandonne une réponse de plus de 100 000 octets

# Valeurs de PAVI.fctn
ENVOI, SUITE, RETOUR, SOMMAIRE = "ENVOI", "SUITE", "RETOUR", "SOMMAIRE"
GUIDE, REPETITION, ANNULATION, CORRECTION = "GUIDE", "REPETITION", "ANNULATION", "CORRECTION"
CNX, FIN, DIRECT, DIRECTCNX = "CNX", "FIN", "DIRECT", "DIRECTCNX"
FUNCTION_KEYS = {ENVOI, SUITE, RETOUR, SOMMAIRE, GUIDE, REPETITION, ANNULATION, CORRECTION}

# Masque « validwith » des commandes de saisie
MSK = {SOMMAIRE: 1, RETOUR: 4, REPETITION: 8, GUIDE: 16, SUITE: 64, ENVOI: 128}


class ProtocolError(ValueError):
    """Requête qui ne ressemble pas à un appel de la passerelle."""


@dataclass
class PaviRequest:
    unique_id: str
    fctn: str
    content: list[str] = field(default_factory=list)
    context: str = ""
    remote_addr: str = ""
    typesocket: str = ""
    version_minitel: str = ""
    datas: Any = ""
    url_params: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, payload: Any) -> "PaviRequest":
        if not isinstance(payload, dict) or not isinstance(payload.get("PAVI"), dict):
            raise ProtocolError("clé PAVI absente")
        p = payload["PAVI"]
        unique_id = str(p.get("uniqueId") or "")
        if not unique_id:
            raise ProtocolError("uniqueId absent")
        content = p.get("content")
        if isinstance(content, str):  # tolérance : une chaîne au lieu d'un tableau
            content = [content]
        elif not isinstance(content, list):
            content = []
        params = payload.get("URLPARAMS")
        return cls(
            unique_id=unique_id,
            fctn=str(p.get("fctn") or "").upper(),
            content=[str(c) if c is not None else "" for c in content],
            context=str(p.get("context") or ""),
            remote_addr=str(p.get("remoteAddr") or ""),
            typesocket=str(p.get("typesocket") or ""),
            version_minitel=str(p.get("versionminitel") or ""),
            datas=p.get("datas", ""),
            url_params=params if isinstance(params, dict) else {},
        )

    @property
    def text(self) -> str:
        """Première ligne saisie, sans espaces autour."""
        return self.content[0].strip() if self.content else ""

    @property
    def is_connect(self) -> bool:
        return self.fctn in (CNX, DIRECTCNX)

    @property
    def is_disconnect(self) -> bool:
        return self.fctn == FIN

    @property
    def is_background(self) -> bool:
        """Appels qui ne viennent pas d'une action de l'utilisateur."""
        return self.fctn.startswith("BGCALL") or self.fctn in ("DATAS", "DIRECTCALLFAILED", "DIRECTCALLENDED")


@dataclass
class InputTxt:
    """Zone de saisie d'une ligne, gérée par la passerelle (affichage du champ,
    écho, Correction et Annulation compris)."""

    x: int
    y: int
    length: int
    keys: tuple[str, ...] = (ENVOI,)
    cursor: bool = True
    spacechar: str = "."
    char: str = ""       # si non vide : affiché à la place de chaque frappe
    prefill: str = ""

    def to_command(self) -> dict:
        if not (1 <= self.x <= 40 and 1 <= self.y <= 24 and 1 <= self.length <= 41 - self.x):
            raise ValueError("zone de saisie hors écran")
        mask = 0
        for k in self.keys:
            mask |= MSK[k]
        return {"name": "InputTxt", "param": {
            "x": self.x, "y": self.y, "l": self.length, "char": self.char,
            "spacechar": self.spacechar, "prefill": self.prefill[:self.length],
            "cursor": "on" if self.cursor else "off", "validwith": mask}}


@dataclass
class Disconnect:
    """Demande à la passerelle de déconnecter l'utilisateur du service."""

    def to_command(self) -> dict:
        return {"name": "libCnx"}


@dataclass
class PaviResponse:
    content: bytes = b""
    command: InputTxt | Disconnect | None = None
    context: str = ""
    echo: bool = True
    directcall: str = "no"   # "no", "yes" (rappel immédiat, fctn DIRECT) ou "yes-cnx"

    def to_json(self, next_url: str) -> dict:
        if any(b > 0x7F for b in self.content):
            raise ValueError("le contenu Vidéotex doit être sur 7 bits")
        encoded = base64.b64encode(self.content).decode("ascii")
        if len(encoded) > MAX_CONTENT - 2000:
            raise ValueError("page trop volumineuse pour la passerelle")
        out = {
            "version": CLIENT_VERSION,
            "content": encoded,
            "context": self.context[:MAX_CONTEXT],
            "echo": "on" if self.echo else "off",
            "directcall": self.directcall if self.directcall in ("yes", "yes-cnx") else "no",
            "next": next_url,
        }
        if self.command is not None:
            out["COMMAND"] = self.command.to_command()
        return out


def is_gateway(user_agent: str | None) -> bool:
    return USER_AGENT_MARK in (user_agent or "")


def emulator_url(service_url: str) -> str:
    """Adresse de l'émulateur web de MiniPavi ouvrant directement le service."""
    gateway = f"{GATEWAY_WSS}/?url={quote(service_url, safe='')}"
    return f"{EMULATOR_URL}?gw={quote(gateway, safe='')}"
