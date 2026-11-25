# Protocole MiniPavi ↔ service — notes de l'étape 0

Relevé le 25/11/2026. Tout ce qui suit vient des sources listées en bas, pas de mémoire.
Les points non confirmés sont regroupés dans « Points flous » et seront tous isolés dans
`app/minipavi.py`.

## 1. Principe

- La passerelle est toujours à l'initiative : elle fait un **POST HTTP avec un corps JSON**
  vers l'URL du service, le service répond en JSON. [doc §1.1]
- À la connexion, elle appelle l'URL du service ; ensuite elle appelle l'URL que le service
  a donnée dans `next` à la réponse précédente (URL absolue). [doc §3.1]
- Le `User-Agent` de la passerelle contient `MiniPAVI` ; la lib PHP redirige tout autre
  visiteur vers l'émulateur web. [MiniPaviCli.php, `start()`]

## 2. Requête passerelle → service

```json
{
  "PAVI": {
    "version": "1.2",
    "uniqueId": "1714813977354",
    "remoteAddr": "0184257626",
    "typesocket": "other",
    "versionminitel": "Cz6",
    "content": ["ligne 1", "ligne 2"],
    "context": "",
    "datas": "",
    "fctn": "ENVOI",
    "webmedia": 0
  },
  "URLPARAMS": {"cle": "valeur"}
}
```
(exemple de la doc §2.2, `URLPARAMS` ajouté d'après §2.1)

| Clé | Sens |
|---|---|
| `version` | version de la passerelle |
| `uniqueId` | identifiant unique de la connexion ; les 4 derniers chiffres sont le code pin WebMedia |
| `remoteAddr` | IP de l'utilisateur, ou son numéro de téléphone s'il est connu |
| `typesocket` | `websocket`, `websocketssl` ou `other` |
| `versionminitel` | 3 caractères du type de Minitel, sinon `???` ; pas forcément renseigné dès la connexion |
| `content` | **tableau** : la saisie. Une ligne → indice 0. Plusieurs lignes ou champs → un élément chacun. `[]` à la connexion |
| `context` | chaîne libre renvoyée telle quelle par la passerelle (65 000 caractères max côté lib) |
| `datas` | données facultatives de la passerelle (captures d'écran…) |
| `fctn` | touche de fonction ou événement, voir ci-dessous |
| `webmedia` | 0/1, lecteur WebMedia connecté |
| `URLPARAMS` | paramètres de l'URL d'appel ; **clé absente** s'il n'y en a pas |

Valeurs de `fctn` [doc §2.1] : `ENVOI`, `SUITE`, `RETOUR`, `ANNULATION`, `CORRECTION`,
`GUIDE`, `REPETITION`, `SOMMAIRE`, `CNX`, `FIN`, `DIRECT`, `DIRECTCNX`,
`DIRECTCALLFAILED`, `DIRECTCALLENDED`, `BGCALL`, `BGCALL-SIMU`, `BGCALL-WM-START`,
`BGCALL-WM-STOP`, `DATAS`.

- `CNX` : nouvelle connexion. `DIRECTCNX` : à traiter comme une nouvelle connexion.
- `FIN` : l'utilisateur s'est déconnecté (Connexion/Fin, raccroché). Les services
  d'exemple ne renvoient rien d'utile dans ce cas.
- `BGCALL-WM-*` : état du lecteur WebMedia, à ignorer (la lib les ignore par défaut).

## 3. Réponse service → passerelle

```json
{
  "version": "1.1",
  "content": "<Vidéotex en base64>",
  "context": "…",
  "echo": "on",
  "directcall": "no",
  "next": "https://mon.domaine/minipavi",
  "COMMAND": {
    "name": "InputTxt",
    "param": {"x": 2, "y": 24, "l": 2, "char": "", "spacechar": ".",
              "prefill": "", "cursor": "on", "validwith": 221}
  }
}
```

| Clé | Sens |
|---|---|
| `version` | version du client (la lib envoie `1.1`) |
| `content` | page Vidéotex, **octets 7 bits encodés en base64** |
| `context` | données libres renvoyées à l'appel suivant (UTF-8) |
| `echo` | `on` / `off` : écho par la passerelle des caractères tapés |
| `next` | prochaine URL appelée (saisie suivante **ou déconnexion**) |
| `directcall` | `no` ; `yes` → rappel immédiat avec `fctn=DIRECT` ; `yes-cnx` → `DIRECTCNX`. Limité à 2 usages consécutifs |
| `COMMAND` | facultatif, objet `{name, param}` |

### Commandes utiles au projet

**`InputTxt`** — une ligne de saisie. `x` colonne 1-40, `y` ligne, `l` longueur,
`char` caractère affiché à la place de la frappe (code secret), `spacechar` caractère de
fond du champ, `prefill`, `cursor` `on`/`off`, `validwith` somme de :

| SOMMAIRE | RETOUR | REPETITION | GUIDE | SUITE | ENVOI | AUTOSEND |
|---|---|---|---|---|---|---|
| 1 | 4 | 8 | 16 | 64 | 128 | 256 |

CORRECTION et ANNULATION ne se déclarent pas : **la passerelle les gère elle-même** pour
corriger la saisie. `AUTOSEND` : le caractère tapé part aussitôt avec `fctn=ENVOI`,
longueur ramenée à 1, écho et pré-remplissage coupés.

**`InputForm`** — jusqu'à 30 champs : `x`, `y`, `l`, `char`, `prefill` sont des tableaux ;
SUITE/RETOUR servent à changer de champ, donc `validwith` ne peut contenir que
SOMMAIRE, REPETITION, GUIDE, ENVOI. Utile pour pseudo + code (champ code masqué).

**`InputMsg`** — zone multi-lignes (`x`,`y`,`w`,`h`), mêmes restrictions. Pas prévu ici.

**`libCnx`** — `{"name":"libCnx"}`, sans paramètre : déconnecte l'utilisateur du
service, qui retourne à l'accueil de la passerelle.

Autres commandes existantes, hors périmètre : `PushServiceMsg`, `BackgroundCall`,
`connectToExt`, `connectToTln`, `connectToWs`, `duplicateStream`, `setParam`,
`getScreen`, `getScreenList`.

## 4. Vidéotex (d'après les constantes de la lib)

- Positionnement : `1F`, `40+ligne`, `40+colonne` (ligne 0-24, colonne 1-40).
- Effacement : `0C` ; fin de ligne `18` ; curseur `11` on / `14` off ; répétition `12`, `3F+n`.
- G1 semi-graphique `0E`, retour G0 `0F`. Tailles `1B 4C..4F` (normale, double hauteur,
  double largeur, les deux). Couleurs texte `1B 40..47`, fond `1B 50..57`, inversion
  `1B 5D` / `1B 5C`, clignotement `1B 48` / `1B 49`, soulignement `1B 5A` / `1B 59`.
- Ligne 0 : la lib écrit en `1F 40 41`, texte, `18`, puis `0A` pour revenir à la position
  précédente.
- Accents (G2) : `19` + diacritique + lettre. Grave `41`, aigu `42`, circonflexe `43`,
  tréma `48`, cédille `19 4B 63`. œ `19 7A`, Œ `19 6A`, ß `19 7B`, £ `19 23`, ° `19 30`.
  La lib remplace `’` par `'` et supprime les caractères de contrôle du texte.

## 5. Déconnexion

- Par l'utilisateur : la passerelle appelle `next` avec `fctn=FIN`. C'est là qu'on
  sauvegarde (et on sauvegardera de toute façon à chaque paragraphe).
- Par le service : commande `libCnx`.

## 6. Accès et tests

- Émulateur web : `https://www.minipavi.fr/emulminitel/index.php` (variante réaliste :
  `indexminitel.php`). Appel direct d'un service :
  `…/emulminitel/index.php?gw=<urlencode("wss://go.minipavi.fr:8181/?url=" + urlencode(URL du service))>`
- WebSocket : `ws://go.minipavi.fr:8182` et `wss://go.minipavi.fr:8181`.
  Telnet : `go.minipavi.fr:516`. Téléphone : 09 72 10 17 21.
- Le README annonce qu'on peut taper l'URL du service depuis l'accueil MiniPavi ou y
  créer un « profil créateur » ; non vérifié, voir §7.

## 7. Points tranchés par le code de la passerelle

Lecture de `minipavi.php`, `lib/class.MiniPavi.php`, `lib/class.WebSocket.php` et
`lib/class.InCnx.php` du dépôt https://github.com/ludosevilla/minipavi (branche main),
par l'intermédiaire d'un agent de lecture : à revérifier en cas de doute.

1. **Sans `COMMAND`** : toutes les touches de fonction (Envoi, Suite, Retour, Sommaire,
   Guide, Répétition, Correction, Annulation) déclenchent un appel ; les caractères
   tapés sont ignorés. `content` contient alors le reste de la dernière saisie : il ne
   faut pas le lire. Les écrans sans saisie n'envoient donc pas de commande.
2. **Avec `InputTxt`** : une touche absente de `validwith` est ignorée en silence ;
   Correction et Annulation sont traitées localement ; la passerelle dessine le champ
   et place le curseur. L'écho n'a lieu que si la réponse porte `"echo":"on"`.
   `y` de 0 à 24 est accepté ; nous restons dans 1-24.
3. **Saisie** : `content` est en UTF-8. Les séquences d'accent connues sont converties,
   les autres supprimées ; il n'est pas établi qu'un accent tapé au clavier arrive
   jusqu'au service. Aucune conversion de casse : le pseudo est mis en majuscules ici.
4. **Appel HTTP** : `User-Agent: MiniPAVI/1.6`, `Content-Type: application/json`,
   connexion 4 s, réponse 25 s, jusqu'à 3 essais sur délai dépassé, redirections
   suivies, certificat HTTPS vérifié par défaut. Le code HTTP n'est pas regardé : un
   corps non JSON affiche « Réponse non JSON », un échec « Service indisponible » puis
   déconnexion. Réponse limitée à environ 100 000 octets, contexte à 64 000 caractères.
5. **Déconnexion** : Connexion/Fin n'appelle le service avec `fctn=FIN` que si
   l'utilisateur est arrivé par l'accueil MiniPavi ; sinon, et en cas de raccroché, le
   service n'est **pas prévenu**. La partie est donc sauvegardée à chaque paragraphe.
   Inactivité : déconnexion au bout de 600 s.
6. **URL WebSocket** : c'est `/?url=<URL encodée>` (le `/url=` du README est inexact).
7. **`directcall`** : 5 rappels enchaînés au plus.
8. **Majuscules accentuées** (hors adaptateur, dans `videotex/`) : affichage non garanti
   sur Minitel 1 ; le rendu les envoie sans accent.

Reste non vérifié : la saisie de l'URL d'un service depuis l'écran d'accueil MiniPavi
(annoncée par le README, introuvable dans le code lu).

### Vérifications faites à l'étape du rendu

- `videotex-codes.pdf` (minipavi.fr) confirme : positionnement `1F`, effacements,
  curseur, `0E`/`0F`, `19` pour G2, tous les attributs `1B 40..5D`, et la répétition
  `12` + (0x40 + nombre de répétitions). Il précise que taille et inversion sont
  indisponibles en semi-graphique, et que couleur de fond, lignage et masquage ne
  prennent effet que sur un espace.
- Non confirmé par une doc Minitel lue : la table G2 (accents `41 42 43 48 4B`, œ `7A`…)
  ne repose que sur la lib MiniPavi et sur la norme T.51 ; le codage des mosaïques
  (0x20 + 1, 2, 4, 8, 16, 64 par pavé) sur les tables Wikipédia « Videotex character
  set » ; la remise à zéro des attributs par `1F` n'est établie nulle part, donc le
  rendu annule lui-même chaque attribut qu'il pose. `stum1b.pdf`, qui trancherait,
  dépasse la taille lisible par mon outil.

## Sources

- Doc officielle « MiniPaviCli & protocole » :
  https://raw.githubusercontent.com/ludosevilla/minipaviCli/master/MiniPaviCli-doc.pdf (§1 à §4)
- Lib PHP : https://github.com/ludosevilla/minipaviCli/blob/main/MiniPaviCli.php
- Exemples : `MiniMeteo/index.php`, `DisplayPaginatedText.php` du même dépôt, et son README
- https://www.minipavi.fr (accès, émulateurs)
- Code de la passerelle : https://github.com/ludosevilla/minipavi (voir §7)
