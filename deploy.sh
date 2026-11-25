#!/usr/bin/env bash
# Déploie 3615 HEROS sur un VPS, en une commande, depuis cette machine.
#
#   HEROS_SSH_HOST=moi@mon-vps HEROS_DOMAIN=heros.exemple.fr ./deploy.sh
#
# Variables :
#   HEROS_SSH_HOST    (obligatoire) cible SSH, ex. root@1.2.3.4 ou un alias de ~/.ssh/config
#   HEROS_DOMAIN      (obligatoire) domaine public, dont le DNS pointe déjà sur le VPS
#   HEROS_REMOTE_DIR  dossier d'installation sur le VPS      (défaut : /opt/heros)
#   HEROS_PORT        port local d'uvicorn                     (défaut : 8036)
#   HEROS_SKIP_TESTS  mettre à 1 pour ne pas lancer pytest avant l'envoi
#
# Le script est idempotent : on peut le relancer autant de fois qu'on veut.
# Il ne touche jamais au dossier data/ du VPS (parties sauvegardées).
# Prérequis côté VPS : Debian ou Ubuntu, accès root ou sudo sans mot de passe.
set -euo pipefail

: "${HEROS_SSH_HOST:?définissez HEROS_SSH_HOST (ex. root@mon-vps)}"
: "${HEROS_DOMAIN:?définissez HEROS_DOMAIN (ex. heros.exemple.fr)}"
REMOTE_DIR="${HEROS_REMOTE_DIR:-/opt/heros}"
PORT="${HEROS_PORT:-8036}"

# Ces valeurs finissent dans des fichiers de configuration : on refuse tout caractère exotique.
[[ "$HEROS_DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || { echo "HEROS_DOMAIN invalide : $HEROS_DOMAIN" >&2; exit 2; }
[[ "$REMOTE_DIR" =~ ^/[A-Za-z0-9._/-]+$ && "$REMOTE_DIR" != *..* ]] || { echo "HEROS_REMOTE_DIR invalide : $REMOTE_DIR" >&2; exit 2; }
[[ "$PORT" =~ ^[0-9]{2,5}$ ]] || { echo "HEROS_PORT invalide : $PORT" >&2; exit 2; }

cd "$(dirname "$0")"

# ---------------------------------------------------------------- contrôles locaux
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
[ -x .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe

echo "==> Validation des livres"
for book in books/*/book.yaml; do
    "$PY" tools/validate_book.py "$book"
done

if [ "${HEROS_SKIP_TESTS:-0}" != "1" ]; then
    echo "==> Tests"
    "$PY" -m pytest -q
fi

# ---------------------------------------------------------------- envoi du code
ARCHIVE="/tmp/heros-deploy-$$.tgz"
echo "==> Envoi du code vers $HEROS_SSH_HOST"
tar czf - --exclude='__pycache__' --exclude='*.pyc' app books tools requirements.txt \
    | ssh "$HEROS_SSH_HOST" "cat > '$ARCHIVE'"

# ---------------------------------------------------------------- installation distante
echo "==> Installation sur le VPS"
ssh "$HEROS_SSH_HOST" \
    "ARCHIVE='$ARCHIVE' REMOTE_DIR='$REMOTE_DIR' DOMAIN='$HEROS_DOMAIN' PORT='$PORT' bash -s" <<'REMOTE_EOF'
set -euo pipefail
trap 'rm -f "$ARCHIVE"' EXIT

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else
    SUDO="sudo"
    sudo -n true 2>/dev/null || { echo "Il faut root ou un sudo sans mot de passe sur le VPS." >&2; exit 1; }
fi
run() { $SUDO "$@"; }

# Écrit un fichier seulement si son contenu change. Renvoie 0 s'il a été modifié.
install_file() {  # install_file <destination> <mode>   (contenu sur l'entrée standard)
    local tmp; tmp="$(mktemp)"; cat > "$tmp"
    if run test -f "$1" && run cmp -s "$tmp" "$1"; then rm -f "$tmp"; return 1; fi
    run install -m "$2" "$tmp" "$1"; rm -f "$tmp"; return 0
}

# -- paquets ------------------------------------------------------------------
need=""
python3 -c 'import venv, ensurepip' 2>/dev/null || need="$need python3 python3-venv"
command -v caddy >/dev/null 2>&1 || need="$need caddy"
command -v curl  >/dev/null 2>&1 || need="$need curl"
if [ -n "$need" ]; then
    command -v apt-get >/dev/null 2>&1 || { echo "Paquets manquants ($need) et pas d'apt-get : installez-les à la main." >&2; exit 1; }
    echo "--> installation de :$need"
    run env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    # shellcheck disable=SC2086
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $need
fi

# -- utilisateur et dossiers ----------------------------------------------------
id heros >/dev/null 2>&1 || run useradd --system --home-dir "$REMOTE_DIR" --shell /usr/sbin/nologin heros
run mkdir -p "$REMOTE_DIR/data"

# -- code : on remplace app/, books/, tools/ ; data/ et .venv/ ne bougent pas -------
run rm -rf "$REMOTE_DIR/app" "$REMOTE_DIR/books" "$REMOTE_DIR/tools"
run tar xzf "$ARCHIVE" -C "$REMOTE_DIR" --no-same-owner

# -- dépendances ------------------------------------------------------------------
[ -x "$REMOTE_DIR/.venv/bin/python" ] || run python3 -m venv "$REMOTE_DIR/.venv"
run "$REMOTE_DIR/.venv/bin/python" -m pip install --quiet --disable-pip-version-check \
    --upgrade -r "$REMOTE_DIR/requirements.txt"
run chown -R heros:heros "$REMOTE_DIR"

# -- service systemd -----------------------------------------------------------------
# Un seul worker : l'état vit dans un fichier SQLite ouvert par un seul processus.
if install_file /etc/systemd/system/heros.service 644 <<UNIT
[Unit]
Description=3615 HEROS - service Minitel (MiniPavi)
After=network.target

[Service]
User=heros
Group=heros
WorkingDirectory=$REMOTE_DIR
Environment=HEROS_PUBLIC_URL=https://$DOMAIN/
Environment=HEROS_DB=$REMOTE_DIR/data/heros.sqlite3
Environment=HEROS_BOOKS_DIR=$REMOTE_DIR/books
ExecStart=$REMOTE_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT --workers 1
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$REMOTE_DIR/data

[Install]
WantedBy=multi-user.target
UNIT
then run systemctl daemon-reload; fi
run systemctl enable --quiet heros.service
run systemctl restart heros.service

echo "--> attente du service"
ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then ok=1; break; fi
    sleep 1
done
if [ "$ok" != 1 ]; then
    echo "Le service ne répond pas. Derniers logs :" >&2
    run journalctl -u heros.service -n 30 --no-pager >&2 || true
    exit 1
fi
echo "--> service en marche : $(curl -fsS "http://127.0.0.1:$PORT/healthz")"

# -- reverse proxy HTTPS (Caddy) ---------------------------------------------------------
# On n'écrase pas le Caddyfile : le site vit dans son propre fichier, importé par le principal.
other="$(run ss -ltnpH 'sport = :443' 2>/dev/null | grep -v caddy || true)"
if [ -n "$other" ]; then
    echo "Le port 443 est déjà pris par un autre serveur que Caddy :" >&2
    echo "$other" >&2
    echo "Le service tourne sur 127.0.0.1:$PORT ; branchez-y votre reverse proxy existant." >&2
    exit 1
fi
changed=0
run mkdir -p /etc/caddy/conf.d
run test -f /etc/caddy/Caddyfile || run touch /etc/caddy/Caddyfile
if ! run grep -qE '^\s*import\s+(/etc/caddy/)?conf\.d/\*\.caddy' /etc/caddy/Caddyfile; then
    printf '\nimport conf.d/*.caddy\n' | run tee -a /etc/caddy/Caddyfile >/dev/null
    changed=1
fi
if install_file /etc/caddy/conf.d/heros.caddy 644 <<CADDY
$DOMAIN {
	encode gzip
	reverse_proxy 127.0.0.1:$PORT
}
CADDY
then changed=1; fi
if ! run caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
    echo "Configuration Caddy invalide :" >&2
    run caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >&2 || true
    exit 1
fi
run systemctl enable --quiet caddy.service
if run systemctl is-active --quiet caddy.service; then
    if [ "$changed" = 1 ]; then run systemctl reload caddy.service; fi
else
    run systemctl start caddy.service
fi
echo "--> Caddy sert https://$DOMAIN/"
REMOTE_EOF

# ---------------------------------------------------------------- contrôle final
URL="https://$HEROS_DOMAIN/"
echo "==> Contrôle public"
if command -v curl >/dev/null 2>&1; then
    ok=0
    for _ in 1 2 3 4 5 6; do   # le premier certificat peut prendre quelques secondes
        if curl -fsS "${URL}healthz" >/dev/null 2>&1; then ok=1; break; fi
        sleep 5
    done
    if [ "$ok" = 1 ]; then
        echo "    ${URL}healthz répond."
    else
        echo "    ${URL}healthz ne répond pas encore (DNS ou certificat en cours ?). Réessayez dans une minute." >&2
    fi
fi
echo
echo "Service Minitel : $URL"
echo "Pour l'essayer dans l'émulateur, ouvrez simplement cette adresse dans un navigateur."
