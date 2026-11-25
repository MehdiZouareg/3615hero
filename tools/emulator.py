#!/usr/bin/env python3
"""Émulateur local : un Minitel et une fausse passerelle MiniPavi dans le navigateur.

    python tools/emulator.py [--port 8037]

Puis ouvrir http://127.0.0.1:8037/emu

La page joue les deux rôles que tient MiniPavi en vrai : elle affiche le Vidéotex
et gère la saisie (champ, écho, Correction, Annulation, touches de fonction), puis
appelle le service en POST exactement comme le ferait la passerelle. C'est un outil
de mise au point : il ne remplace pas un essai sur le vrai MiniPavi.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: E402

from app.main import create_app  # noqa: E402

PAGE = Path(__file__).with_name("emulator.html")


def build(port: int):
    # Le vrai service, monté sous /service : la page l'appelle comme le ferait MiniPavi.
    # À la racine, on sert l'émulateur (le vrai service, lui, renverrait vers minipavi.fr).
    service = create_app(db_path=ROOT / "data" / "emulateur.sqlite3",
                         public_url=f"http://127.0.0.1:{port}/service/")
    app = FastAPI(title="Émulateur 3615 HEROS", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/service", service)

    @app.get("/")
    def root():
        return RedirectResponse("/emu")

    @app.get("/emu")
    def emulator():
        return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8037)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    print(f"Émulateur : http://127.0.0.1:{args.port}/emu")
    uvicorn.run(build(args.port), host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
