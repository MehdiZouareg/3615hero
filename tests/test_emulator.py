"""L'émulateur local : la page est servie et le service répond sous /service/."""
import base64

from fastapi.testclient import TestClient

from tests.test_minipavi import DOC_CNX_WEB
from tests.vdt import decode
from tools import emulator


def test_emulateur_local(tmp_path, monkeypatch):
    monkeypatch.setattr(emulator, "ROOT", tmp_path)
    monkeypatch.setenv("HEROS_BOOKS_DIR", str(emulator.PAGE.parent.parent / "books"))
    client = TestClient(emulator.build(8037), follow_redirects=False)
    assert client.get("/").headers["location"] == "/emu"
    page = client.get("/emu")
    assert page.status_code == 200 and "fausse passerelle MiniPavi" in page.text
    body = client.post("/service/", json=DOC_CNX_WEB).json()
    assert body["next"] == "http://127.0.0.1:8037/service/"
    assert "HHEERROOSS" in decode(base64.b64decode(body["content"]))[7]
