"""Adaptateur MiniPavi, sur les exemples de la doc officielle (MiniPaviCli-doc.pdf §2.2 et §3.3)."""
import base64

import pytest

from app import minipavi as mp

# §2.2 : connexion depuis l'émulateur web
DOC_CNX_WEB = {"PAVI": {"version": "1.2", "uniqueId": "1714813976258", "remoteAddr": "82.65.112.8",
                        "typesocket": "websocketssl", "versionminitel": "Cv;", "content": [],
                        "context": "", "datas": "", "fctn": "CNX", "webmedia": 0}}
# §2.2 : connexion par téléphone
DOC_CNX_TEL = {"PAVI": {"version": "1.2", "uniqueId": "1714813977354", "remoteAddr": "0184257626",
                        "typesocket": "other", "versionminitel": "Cz6", "content": [],
                        "context": "", "datas": "", "fctn": "CNX", "webmedia": 0}}
# §2.2 : envoi d'une saisie de deux lignes
DOC_ENVOI = {"PAVI": {"version": "1.2", "uniqueId": "1714813977354", "remoteAddr": "0184257626",
                      "typesocket": "other", "versionminitel": "Cz6", "content": ["ligne 1", "ligne 2"],
                      "context": "", "datas": "", "fctn": "ENVOI", "webmedia": 0}}


def test_requete_connexion_web():
    req = mp.PaviRequest.parse(DOC_CNX_WEB)
    assert req.unique_id == "1714813976258"
    assert req.fctn == "CNX" and req.is_connect and not req.is_disconnect
    assert req.content == [] and req.text == ""
    assert req.typesocket == "websocketssl" and req.version_minitel == "Cv;"
    assert req.url_params == {}  # la clé URLPARAMS est absente sans paramètre


def test_requete_connexion_telephone():
    req = mp.PaviRequest.parse(DOC_CNX_TEL)
    assert req.remote_addr == "0184257626" and req.typesocket == "other"


def test_requete_envoi():
    req = mp.PaviRequest.parse(DOC_ENVOI)
    assert req.fctn == mp.ENVOI and not req.is_connect
    assert req.content == ["ligne 1", "ligne 2"] and req.text == "ligne 1"


def test_requete_urlparams_fin_et_evenements():
    payload = {"PAVI": dict(DOC_ENVOI["PAVI"], fctn="FIN", content=[" 12 "]), "URLPARAMS": {"step": "20"}}
    req = mp.PaviRequest.parse(payload)
    assert req.is_disconnect and req.url_params == {"step": "20"} and req.text == "12"
    assert mp.PaviRequest.parse({"PAVI": dict(DOC_ENVOI["PAVI"], fctn="DIRECTCNX")}).is_connect
    for fctn in ("BGCALL", "BGCALL-SIMU", "BGCALL-WM-START", "BGCALL-WM-STOP", "DATAS"):
        assert mp.PaviRequest.parse({"PAVI": dict(DOC_ENVOI["PAVI"], fctn=fctn)}).is_background


def test_requete_tolerante_et_rejets():
    req = mp.PaviRequest.parse({"PAVI": {"uniqueId": 42, "fctn": "envoi", "content": "abc", "context": None}})
    assert (req.unique_id, req.fctn, req.content, req.context) == ("42", "ENVOI", ["abc"], "")
    assert mp.PaviRequest.parse({"PAVI": {"uniqueId": "1", "fctn": "SUITE", "content": [None, 3]}}).content == ["", "3"]
    for bad in (None, [], {}, {"PAVI": []}, {"PAVI": {"fctn": "CNX"}}):
        with pytest.raises(mp.ProtocolError):
            mp.PaviRequest.parse(bad)


def test_reponse_input_txt_comme_la_doc():
    # §3.3 : zone de 10 caractères en X=2, Y=20, curseur allumé, validée par Répétition et Envoi
    cmd = mp.InputTxt(2, 20, 10, keys=(mp.REPETITION, mp.ENVOI), prefill="Salut!")
    out = mp.PaviResponse(b"\x1f@A \x12f", cmd, context="a:0:{}").to_json("http://www.monsite.fr/index.php?step=20")
    assert out == {
        "version": "1.1",
        "content": base64.b64encode(b"\x1f@A \x12f").decode(),
        "context": "a:0:{}",
        "echo": "on",
        "directcall": "no",
        "next": "http://www.monsite.fr/index.php?step=20",
        "COMMAND": {"name": "InputTxt", "param": {"x": 2, "y": 20, "l": 10, "char": "", "spacechar": ".",
                                                  "prefill": "Salut!", "cursor": "on", "validwith": 136}},
    }


def test_masque_des_touches():
    def mask(*keys):
        return mp.InputTxt(1, 1, 1, keys=keys).to_command()["param"]["validwith"]

    assert mask(mp.ENVOI) == 128
    assert mask(mp.REPETITION, mp.GUIDE, mp.ENVOI) == 152  # valeur de l'exemple InputMsg de la doc
    assert mask(mp.SOMMAIRE, mp.RETOUR, mp.REPETITION, mp.GUIDE, mp.SUITE, mp.ENVOI) == 221
    with pytest.raises(KeyError):
        mask(mp.CORRECTION)  # gérée par la passerelle, non déclarable


def test_reponse_sans_commande_et_deconnexion():
    out = mp.PaviResponse(b"abc", echo=False).to_json("https://x/")
    assert "COMMAND" not in out and out["echo"] == "off"
    assert mp.PaviResponse(command=mp.Disconnect()).to_json("https://x/")["COMMAND"] == {"name": "libCnx"}
    assert mp.PaviResponse(directcall="yes").to_json("u")["directcall"] == "yes"
    assert mp.PaviResponse(directcall="n'importe quoi").to_json("u")["directcall"] == "no"


def test_reponse_garde_fous():
    with pytest.raises(ValueError):
        mp.PaviResponse("é".encode("utf-8")).to_json("u")       # 8 bits
    with pytest.raises(ValueError):
        mp.PaviResponse(b"x" * 80_000).to_json("u")              # au-delà de ce qu'accepte la passerelle
    with pytest.raises(ValueError):
        mp.InputTxt(35, 1, 10).to_command()                       # déborde de la ligne
    with pytest.raises(ValueError):
        mp.InputTxt(1, 0, 2).to_command()
    assert len(mp.PaviResponse(context="x" * 70_000).to_json("u")["context"]) == 64_000
    assert mp.InputTxt(1, 1, 3, prefill="abcdef").to_command()["param"]["prefill"] == "abc"


def test_user_agent_et_url_emulateur():
    assert mp.is_gateway("MiniPAVI/1.6") and not mp.is_gateway("Mozilla/5.0") and not mp.is_gateway(None)
    url = mp.emulator_url("https://heros.example.org/?a=1&b=2")
    assert url.startswith("https://www.minipavi.fr/emulminitel/index.php?gw=wss%3A%2F%2Fgo.minipavi.fr%3A8181%2F%3Furl%3D")
    assert "&" not in url.split("?gw=")[1]  # l'URL du service est doublement encodée
