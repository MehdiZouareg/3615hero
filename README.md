# 3615 HEROS

Un service Minitel pour jouer à des livres dont vous êtes le héros, depuis un vrai Minitel
ou un émulateur, par la passerelle [MiniPavi](https://www.minipavi.fr).

Le Minitel parle à MiniPavi (téléphone, WebSocket ou telnet) ; MiniPavi appelle ce
service en HTTP à chaque touche de fonction ; le service répond une page Vidéotex.

```
Minitel ── MiniPavi ── POST JSON ──> https://votre-domaine/  (FastAPI, ce dépôt)
```

## Démarrage

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # Windows : .venv\Scripts\pip
.venv/bin/python -m pytest -q                      # tous les tests
.venv/bin/python tools/play_cli.py books/demo-la-tour   # jouer en console, sans Minitel
.venv/bin/python tools/validate_book.py books/demo-la-tour
```

Dans la console : le numéro d'une action, `F` pour la feuille d'aventure, `R` pour les
règles, `Q` pour quitter. `--seed 42` rend la partie reproductible.

## Organisation

| Chemin | Rôle |
|---|---|
| `app/engine/` | moteur de jeu pur : modèles, dés seedables, règles. Ne connaît ni le Minitel ni HTTP |
| `app/videotex/` | constantes Vidéotex et mise en page 40 × 24 (accents, pagination, cadres, mosaïques) |
| `app/screens.py` | les écrans et leur enchaînement |
| `app/sessions.py` | SQLite : connexions en cours, parties sauvegardées |
| `app/minipavi.py` | **seul module couplé à MiniPavi** (format des requêtes et des réponses) |
| `app/main.py` | l'application FastAPI |
| `books/` | un dossier par livre, avec son `book.yaml` |
| `tools/` | `validate_book.py`, `play_cli.py` et l'émulateur local (`emulator.py`) |
| `docs/minipavi-protocol.md` | ce qui a été relevé du protocole, sources et points non vérifiés |

## Jouer sur Minitel

- **Accueil** : tapez le numéro d'un livre puis ENVOI, ou `R` pour reprendre une partie.
- **Nouveau héros** : un pseudo (2 à 10 lettres ou chiffres). Les dés créent le personnage
  et un **code à 4 chiffres** est attribué : pseudo + code permettent de reprendre plus tard.
- **Paragraphe** : SUITE et RETOUR feuillettent, puis numéro du choix + ENVOI.
- **SOMMAIRE** : feuille d'aventure. **GUIDE** : règles. **REPETITION** : réaffiche l'écran.
  **CORRECTION / ANNULATION** : corrigent la saisie (c'est la passerelle qui s'en charge).
- **Quitter** : CONNEXION/FIN à tout moment, ou `0` + ENVOI depuis la feuille d'aventure.
  La partie est enregistrée à chaque action ; il n'y a rien à faire pour sauvegarder.
- Une partie terminée, par la mort ou la victoire, est effacée.

## Écrire un livre

Un livre est un fichier `books/<identifiant>/book.yaml`. Le plus simple est de partir de
`books/demo-la-tour/book.yaml`, qui utilise toutes les mécaniques.

```yaml
titre: La Tour de Cendre
auteur: Vous
resume: Texte de présentation affiché dans le catalogue.
regles: Texte affiché par la touche GUIDE.
personnage:
  stats: {habilete: 1d6+6, endurance: 2d6+12, chance: 1d6+6}
  inventaire: [épée, lanterne]
  stat_vie: endurance          # la stat qui tue à zéro (défaut : endurance)
depart: 1
flags_visibles:                # flags montrés sur la feuille d'aventure
  secret_cloche: Vous connaissez le secret de la cloche
paragraphes:
  1:
    texte: |
      Un alinéa par ligne.
    illustration:              # facultatif : dessin en pixels, # allumé, . éteint
      - "..##.."
    effets:                    # appliqués en entrant
      - {stat: endurance, delta: -2}
      - gagne: clé d'argent
      - perd: torche
      - pose_flag: porte_ouverte
      - retire_flag: poursuivi
    choix:
      - {libelle: Monter, vers: 2}
      - libelle: Ouvrir la porte
        vers: 3
        si: [{objet: clé d'argent}, {stat: habilete, min: 9}]
  2:
    texte: Un gouffre.
    test: {stat: chance, reussite: 4, echec: 5, libelle: Sauter}
  3:
    texte: Un garde.
    combat: {ennemi: Garde, habilete: 8, endurance: 6, victoire: 4, defaite: 5, fuite: 1}
  4: {texte: Vous êtes libre., fin: victoire}
  5: {texte: Tout devient noir., fin: mort}
```

Règles du format :

- Un paragraphe a **une seule sortie** : des `choix`, ou un `test`, ou un `combat`, ou une `fin`.
- Conditions de `si` (toutes doivent être vraies) : `objet`, `sans_objet`, `flag`,
  `sans_flag`, ou `stat` avec `min` et/ou `max`. Un choix dont la condition n'est pas
  remplie n'est pas proposé.
- `test` : 2d6 inférieur ou égal à la stat. Un test de `chance` la fait baisser d'un point.
- `combat` : `defaite` et `fuite` sont facultatifs. Sans `defaite`, la mort mène à l'écran
  de fin ; sans `fuite`, on ne peut pas fuir.
- Un gain de stat ne dépasse jamais le total de départ.
- `illustration` : chaque case Minitel fait 2 pixels de large sur 3 de haut ; 80 pixels de
  large et 24 de haut au plus (au-delà de 8 lignes de cases, elle n'est pas affichée).
- Tout champ inconnu est refusé au chargement.

Le combat par défaut est celui des Défis Fantastiques (`systeme_combat: defis_fantastiques`).
Pour en brancher un autre, écrivez une classe avec `assaut()` et `fuite()` et enregistrez-la :

```python
from app.engine.engine import register_combat_system
register_combat_system("mon_systeme", MonSysteme)
```

**Validez toujours un livre avant de le déployer** : un livre qui a des erreurs est écarté
au démarrage du service (une ligne dans les logs le dit).

```bash
python tools/validate_book.py books/mon-livre --strict
```

Le validateur signale les destinations inexistantes, les paragraphes inatteignables, les
culs-de-sac, les objets ou flags exigés qu'on ne peut jamais avoir en arrivant là, les
impasses selon l'inventaire, les boucles sans issue et l'absence de fin victorieuse. Il ne
raisonne pas sur les stats : un test ou un combat est supposé pouvoir tourner dans les deux sens.

## Lancer le service

```bash
.venv/bin/uvicorn app.main:app --port 8036
```

| Variable | Rôle | Défaut |
|---|---|---|
| `HEROS_BOOKS_DIR` | dossier des livres | `./books` |
| `HEROS_DB` | fichier SQLite | `./data/heros.sqlite3` |
| `HEROS_PUBLIC_URL` | URL publique que MiniPavi doit rappeler | déduite de la requête |

Un seul worker : l'état vit dans un fichier SQLite ouvert par un seul processus.

- `POST /` : l'appel de la passerelle.
- `GET /` : un navigateur est redirigé vers l'émulateur Minitel, branché sur le service.
- `GET /healthz` : état et liste des livres chargés.

### Émulateur local

Pour essayer le service sur son poste, sans MiniPavi ni Internet :

```bash
.venv/bin/python tools/emulator.py        # puis ouvrir http://127.0.0.1:8037/emu
```

La page affiche l'écran Minitel et tient le rôle de la passerelle : champ de saisie,
écho, Correction et Annulation, touches de fonction, appels au service (visibles dans le
panneau de droite). Clavier : Entrée = Envoi, Retour arrière = Correction, Échap =
Annulation, Page suivante / précédente = Suite / Retour, F1 = Guide, F2 = Sommaire,
F3 = Répétition. Les parties vont dans `data/emulateur.sqlite3`.

C'est un outil de mise au point écrit pour ce projet : il affiche ce que le service
envoie selon la lecture qui a été faite du Vidéotex et du protocole. Un essai sur le vrai
MiniPavi reste nécessaire, et pour cela le service doit être joignable depuis Internet
(déployez-le, ou exposez le port local par un tunnel de votre choix).

## Déployer

Prérequis : un VPS Debian ou Ubuntu, un accès SSH root ou sudo sans mot de passe, et un
nom de domaine dont le DNS pointe déjà sur le VPS (Caddy en a besoin pour le certificat).

```bash
HEROS_SSH_HOST=moi@mon-vps HEROS_DOMAIN=heros.exemple.fr ./deploy.sh
```

Sous Windows, lancez-le depuis Git Bash. Le script :

1. valide les livres et lance les tests en local (`HEROS_SKIP_TESTS=1` pour sauter les tests) ;
2. envoie `app/`, `books/`, `tools/` et `requirements.txt` ;
3. installe au besoin Python, Caddy et curl, crée l'utilisateur système `heros` ;
4. met à jour le virtualenv et le service systemd `heros` (uvicorn sur `127.0.0.1:8036`) ;
5. ajoute le site à Caddy dans `/etc/caddy/conf.d/heros.caddy`, sans réécrire votre
   `Caddyfile` (il y ajoute seulement une ligne `import conf.d/*.caddy`) ;
6. vérifie que `https://<domaine>/healthz` répond.

On peut le relancer autant de fois qu'on veut. Il ne touche jamais à `data/` : les parties
sauvegardées survivent aux déploiements. Autres variables : `HEROS_REMOTE_DIR` (défaut
`/opt/heros`), `HEROS_PORT` (défaut `8036`).

Si un autre serveur web occupe déjà le port 443, le script installe le service, s'arrête
avant Caddy et vous le dit : il reste à ajouter un `reverse_proxy` vers `127.0.0.1:8036`
dans votre serveur existant.

Sur le VPS :

```bash
systemctl status heros          # état
journalctl -u heros -f          # logs
```

## Brancher le service sur MiniPavi

Il n'y a rien à enregistrer pour jouer : MiniPavi appelle n'importe quelle URL de service
qu'on lui donne.

- **Émulateur web** : ouvrez `https://<domaine>/` dans un navigateur. Vous êtes redirigé
  vers l'émulateur de minipavi.fr, déjà connecté au service. L'adresse complète est
  `https://www.minipavi.fr/emulminitel/index.php?gw=` suivi de
  `wss://go.minipavi.fr:8181/?url=https://<domaine>/` encodé pour une URL.
- **Boîtier ESP32 ou émulateur WebSocket** : `wss://go.minipavi.fr:8181/?url=https%3A%2F%2F<domaine>%2F`
  (l'URL du service doit être encodée).
- **Vrai Minitel par téléphone** : composez le 09 72 10 17 21, puis Connexion/Fin. Vous
  arrivez sur l'accueil de MiniPavi. D'après la documentation de MiniPavi, on peut y créer
  un « profil créateur » pour y référencer son service ou y saisir son URL ; cette étape
  n'a pas été vérifiée ici, voyez https://www.minipavi.fr ou écrivez à l'auteur de MiniPavi.

À savoir :

- MiniPavi laisse 25 secondes au service pour répondre et coupe une connexion inactive
  au bout de 10 minutes.
- La passerelle ne signe pas ses appels : quiconque connaît l'URL peut poster dessus. Le
  service ne détient rien d'autre que des parties de jeu.
- Le code à 4 chiffres est un aide-mémoire, pas une protection.

## Limites connues

- Le rendu n'a été vérifié que par des outils écrits pour ce projet (`tests/vdt.py` et
  l'émulateur local), pas encore sur l'émulateur de MiniPavi ni sur un vrai Minitel. Les points qui
  reposent sur une documentation indirecte (table des accents, codage des mosaïques) sont
  listés dans `docs/minipavi-protocol.md`.
- `deploy.sh` a été relu et sa syntaxe contrôlée, mais pas encore exécuté sur un VPS.
- Les majuscules accentuées sont envoyées sans accent, et les accents ne sont pas acceptés
  dans les pseudos.
