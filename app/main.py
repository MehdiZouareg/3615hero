"""Service HTTP appelé par la passerelle MiniPavi.

Configuration par variables d'environnement :
    HEROS_BOOKS_DIR   dossier des livres            (défaut : ./books)
    HEROS_DB          fichier SQLite                (défaut : ./data/heros.sqlite3)
    HEROS_PUBLIC_URL  URL publique du service, celle que MiniPavi rappelle.
                      Si elle est absente, elle est déduite de la requête.

Lancement local : uvicorn app.main:app --port 8036
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from . import minipavi as mp
from .engine.models import Book, load_book
from .screens import Service
from .sessions import Store

log = logging.getLogger("heros")
ROOT = Path(__file__).resolve().parent.parent


def load_books(directory: Path) -> dict[str, Book]:
    """Charge les livres du dossier ; un livre invalide est écarté, pas fatal."""
    sys.path.insert(0, str(ROOT))
    from tools.validate_book import validate

    books: dict[str, Book] = {}
    for path in sorted(directory.glob("*/book.yaml")):
        try:
            book = load_book(path)
        except Exception as exc:
            log.error("livre %s illisible : %s", path.parent.name, exc)
            continue
        errors = [i for i in validate(book) if i.level == "erreur"]
        if errors:
            log.error("livre %s écarté : %d erreur(s), lancez tools/validate_book.py", book.id, len(errors))
            continue
        books[book.id] = book
    log.info("%d livre(s) chargé(s) : %s", len(books), ", ".join(books) or "aucun")
    return books


def create_app(books_dir: str | Path | None = None, db_path: str | Path | None = None,
               public_url: str | None = None, service: Service | None = None) -> FastAPI:
    books_dir = Path(books_dir or os.environ.get("HEROS_BOOKS_DIR") or ROOT / "books")
    db_path = db_path or os.environ.get("HEROS_DB") or ROOT / "data" / "heros.sqlite3"
    public_url = public_url or os.environ.get("HEROS_PUBLIC_URL") or None
    if service is None:
        service = Service(load_books(books_dir), Store(db_path))
    lock = threading.Lock()  # une seule connexion SQLite, un appel à la fois
    app = FastAPI(title="3615 HEROS", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service

    def service_url(request: Request) -> str:
        if public_url:
            return public_url
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        return f"{proto.split(',')[0].strip()}://{host.split(',')[0].strip()}{request.url.path}"

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "livres": sorted(service.books)}

    @app.get("/")
    def from_browser(request: Request):
        # Un navigateur n'a rien à faire ici : on l'envoie sur l'émulateur Minitel.
        return RedirectResponse(mp.emulator_url(service_url(request)), status_code=302)

    @app.post("/")
    async def from_gateway(request: Request):
        try:
            req = mp.PaviRequest.parse(await request.json())
        except Exception as exc:
            return PlainTextResponse(f"Requete MiniPavi invalide : {exc}", status_code=400)
        with lock:
            resp = service.handle(req)
        return JSONResponse(resp.to_json(service_url(request)))

    return app


def __getattr__(name: str):
    # `uvicorn app.main:app` : l'application n'est construite qu'à la demande,
    # pour que l'import du module (tests) ne touche ni aux livres ni à la base.
    if name == "app":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        return create_app()
    raise AttributeError(name)
