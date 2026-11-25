"""L'endpoint HTTP, avec les requêtes d'exemple de la doc MiniPavi."""
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app, load_books
from tests.test_minipavi import DOC_CNX_TEL, DOC_CNX_WEB
from tests.vdt import decode

ROOT = Path(__file__).parent.parent
UA = {"User-Agent": "MiniPAVI/1.6"}


@pytest.fixture
def client(tmp_path):
    app = create_app(books_dir=ROOT / "books", db_path=tmp_path / "t.sqlite3",
                     public_url="https://heros.example.org/")
    return TestClient(app, follow_redirects=False)


def envoi(uid, fctn, *content):
    return {"PAVI": dict(DOC_CNX_WEB["PAVI"], uniqueId=uid, fctn=fctn, content=list(content))}


def test_connexion_exemple_de_la_doc(client):
    r = client.post("/", json=DOC_CNX_WEB, headers=UA)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"version", "content", "context", "echo", "directcall", "next", "COMMAND"}
    assert body["next"] == "https://heros.example.org/" and body["directcall"] == "no"
    assert body["COMMAND"]["name"] == "InputTxt"
    screen = decode(base64.b64decode(body["content"]))
    assert "HHEERROOSS" in screen[7] and "La Tour de Cendre" in screen[11]


def test_deux_minitels_en_parallele(client):
    client.post("/", json=DOC_CNX_WEB, headers=UA)
    client.post("/", json=DOC_CNX_TEL, headers=UA)
    a = client.post("/", json=envoi(DOC_CNX_WEB["PAVI"]["uniqueId"], "ENVOI", "1"), headers=UA).json()
    b = client.post("/", json=envoi(DOC_CNX_TEL["PAVI"]["uniqueId"], "GUIDE"), headers=UA).json()
    assert "26 paragraphes" in decode(base64.b64decode(a["content"]))[21]
    assert "MODE D'EMPLOI" in decode(base64.b64decode(b["content"]))[1]


def test_partie_par_http(client):
    uid = "555000111"
    for fctn, content in (("CNX", []), ("ENVOI", ["1"]), ("ENVOI", []), ("ENVOI", ["MEHDI"]), ("ENVOI", [])):
        body = client.post("/", json=envoi(uid, fctn, *content), headers=UA).json()
    screen = decode(base64.b64decode(body["content"]))
    assert "MEHDI" in screen[2] and "#1" in screen[1]
    assert client.post("/", json=envoi(uid, "FIN"), headers=UA).json()["content"] == ""


def test_requete_invalide(client):
    assert client.post("/", json={"bonjour": 1}).status_code == 400
    assert client.post("/", content=b"pas du json", headers={"Content-Type": "application/json"}).status_code == 400


def test_navigateur_redirige_vers_l_emulateur(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["location"].startswith("https://www.minipavi.fr/emulminitel/index.php?gw=")
    assert "heros.example.org" in r.headers["location"]


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True, "livres": ["demo-la-tour"]}


def test_url_deduite_des_en_tetes_du_proxy(tmp_path):
    app = create_app(books_dir=ROOT / "books", db_path=tmp_path / "t.sqlite3")
    c = TestClient(app)
    body = c.post("/", json=DOC_CNX_WEB, headers={"Host": "heros.exemple.fr", "X-Forwarded-Proto": "https"}).json()
    assert body["next"] == "https://heros.exemple.fr/"


def test_livre_invalide_ecarte(tmp_path, caplog):
    (tmp_path / "bon").mkdir()
    (tmp_path / "bon" / "book.yaml").write_text((ROOT / "books/demo-la-tour/book.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "casse").mkdir()
    (tmp_path / "casse" / "book.yaml").write_text(
        "titre: X\npersonnage: {stats: {habilete: 1d6, endurance: 2d6}}\n"
        "paragraphes: {1: {texte: a, choix: [{libelle: b, vers: 99}]}}\n", encoding="utf-8")
    (tmp_path / "illisible").mkdir()
    (tmp_path / "illisible" / "book.yaml").write_text("titre: [", encoding="utf-8")
    assert list(load_books(tmp_path)) == ["bon"]
