# Pilote

Application desktop Windows de suivi personnel : bourse (PEA), budget, prêt étudiant,
sport, santé et patrimoine réunis dans une seule app 100 % locale, multi-utilisateurs.
Aucune donnée ne sort du PC — pas de compte, pas de serveur distant, pas de télémétrie.

Stack : Python + pywebview (fenêtre native avec UI HTML/CSS/JS), PyInstaller pour
compiler en .exe, Inno Setup pour le Setup.exe, GitHub Actions pour build + release.

**Version actuelle : 4.2.2**
(l'app s'appelait « Suivi PEA » jusqu'à la 4.1.0, le dossier du dépôt jusqu'à la 4.1.1)

Dépôt : `C:\Users\Arthur\Desktop\Pilote` — branche `main`, remote
`github.com/arthur-soulard/arthurpilote.github.com` (le nom du dépôt est historique,
il ne suit pas le nom de l'app).

## Structure

```
Pilote/
├── src/
│   ├── app.py          # Point d'entrée, bridge Python↔JS, APP_NAME, APP_VERSION
│   ├── server.py       # Serveur HTTP local (port 7438) + PIN
│   ├── storage.py      # Données PEA + multi-utilisateurs + migrations
│   ├── finances.py     # Module « Mes comptes »   (finances.json)
│   ├── sports.py       # Module « Sports »        (sports.json) + catalogue + champs
│   ├── pret.py         # Module « Prêt étudiant » (pret.json)
│   ├── sante.py        # Module « Santé »         (sante.json) + lecture OCR FitDays
│   ├── ocr_win.ps1     # OCR via Windows.Media.Ocr — appelé par sante.py
│   ├── patrimoine.py   # Module « Patrimoine »    (patrimoine.json)
│   ├── formation.py    # Module « Formation »     (formation.json) + certificats
│   ├── jsonstore.py    # Socle commun : écriture atomique + backup quotidien 7 j
│   ├── sauvegarde.py   # Sauvegarde externe sur clé USB (miroir + archives zip)
│   ├── appicon.py      # Icône recolorée selon la couleur d'accent
│   ├── updater.py      # Auto-updater (check + download + install)
│   ├── notifications.py
│   └── ui/
│       ├── index.html  # TOUTE l'UI (HTML + CSS + JS dans un seul fichier, ~15 100 lignes)
│       └── vendor/     # Chart.js + polices woff2, servis en local (aucun CDN)
├── build/
│   ├── installer.iss   # Script Inno Setup utilisé par la CI (AppVersion à bumper)
│   ├── pilote.spec     # Spec PyInstaller → dist/Pilote.exe
│   └── build.bat       # build local
├── assets/             # icon.ico + make_icon.py (générateur d'icône)
├── .github/workflows/release.yml
└── requirements.txt    # pywebview, pyinstaller, win10toast, pillow
```

En dev, `Donnees` à la racine du dépôt est un lien symbolique vers le dossier de
données de l'app installée.

## Données sur disque

Tout vit dans `<racine app>/Donnees/`. **Chaque utilisateur a son propre dossier**,
tous modules confondus :

```
Donnees/
├── users.json                # liste des utilisateurs + utilisateur actif
├── sauvegarde.json           # config de la sauvegarde USB (niveau installation)
├── users/<slug>/
│   ├── pea_data.json         # PEA              (+ backups/)
│   ├── finances.json         # Mes comptes      (+ backups_finances/)
│   ├── sports.json           # Sports           (+ backups_sports/)
│   ├── pret.json             # Prêt étudiant    (+ backups_pret/)
│   ├── sante.json            # Santé            (+ backups_sante/)
│   ├── patrimoine.json       # Patrimoine       (+ backups_patrimoine/)
│   ├── formation.json        # Formation        (+ backups_formation/)
│   ├── certificats/          # PDF et images des formations validées
│   └── pin.hash              # code PIN de CET utilisateur (si configuré)
├── icones/                   # .ico générés à la couleur d'accent
└── crash.log
```

Rien n'est partagé entre deux utilisateurs — même le thème, la couleur d'accent et
les onglets masqués sont propres à chacun (ils vivent dans `pea_data.json`).

`storage.get_user_dir()` est la racine que `jsonstore.py` et `finances.py` utilisent.

### `_cache` : dans le fichier courant, jamais dans les backups

`pea_data.json` contient une clé `_cache` (cours et historiques Yahoo) qui pèse à
elle seule plus que toutes les données réunies : ~200 Ko contre ~6 Ko. Elle est
volontairement persistée — c'est ce qui fait vivre l'app **hors ligne**
(`Api.load_data` la repasse au serveur via `server.hydrate_cache`).

Mais `storage._daily_backup()` l'**exclut** : un backup ne doit contenir que
l'irremplaçable. Sans ça, 200 Ko de cache régénérable étaient recopiés sept fois
par utilisateur, puis embarqués dans chaque archive de sauvegarde USB. Backup du
jour : 10 Ko au lieu de 418 Ko. Ne pas « simplifier » en resérialisant `data` tel quel.

### Migrations automatiques (idempotentes, ne jamais les supprimer)

* `storage.ensure_migrated()` — une installation antérieure à la 4.1.2
  (`profiles.json` + fichiers de modules à la racine) est déplacée vers
  `users/<slug>/` au premier lancement. `profiles.json` devient `profiles.legacy.json`.
* `storage.migrate_legacy_pin()` — le PIN, global jusqu'à la 4.1.3, est attribué au
  **premier** utilisateur. Appelée au démarrage de `main()` et en fin de `ensure_migrated()`.

## ⚠ Cinq choses à ne JAMAIS casser

1. **`_PIN_SALT`** dans `src/server.py` → sert au hash des codes PIN déjà enregistrés.
2. **L'`AppId` GUID** dans `build/installer.iss` → c'est l'identité de l'installation.
   C'est grâce à lui que le renommage en Pilote n'a pas déplacé les données : le Setup
   reconnaît l'installation existante et réinstalle dans son dossier. Conséquence : le
   dossier d'installation s'appelle toujours `%LocalAppData%\Programs\Suivi PEA\`.
   C'est normal, ne pas « corriger ».
3. **La sémantique de `_hydrationDone`** (index.html) → ce drapeau autorise l'écriture
   disque. Il doit suivre la **réussite de la lecture** (`!_debug.load_error`), jamais le
   volume de données : un utilisateur qui vient d'être créé a un PEA vide et doit
   pouvoir enregistrer. Côté Python, un `pea_data.json` absent n'est **pas** une erreur
   de lecture (`storage.load_data()` laisse `error` à `None`).
4. **`ocr_win.ps1` dans les `datas` de `build/pilote.spec`** → sans cette ligne, l'OCR
   du module Santé fonctionne parfaitement en dev et **échoue silencieusement dans
   l'exe compilé** : le script est introuvable, `ocr_available()` répond « Script OCR
   introuvable » et l'import de captures ne marche plus. Une panne invisible tant
   qu'on ne teste pas le binaire. Vérification : `ocr_win.ps1` doit apparaître comme
   chaîne dans `Pilote.exe`.

5. **`src/ui/vendor/` dans les `datas` de `build/pilote.spec`** → même piège que
   `ocr_win.ps1` : sans cette ligne, Chart.js et les polices sont introuvables dans
   l'exe compilé. Les graphiques disparaissent et la typo retombe sur celle du
   système, alors que tout marche parfaitement en dev.
## Sauvegarde externe sur clé USB (`sauvegarde.py`)

Contrairement à tout le reste, ce module est au niveau de **l'installation**, pas de
l'utilisateur : une sauvegarde embarque le dossier `Donnees/` entier (tous les
espaces, `users.json` compris), pour pouvoir remonter l'installation complète.
Sa config vit donc dans `Donnees/sauvegarde.json`, à côté de `users.json`.

* Une sauvegarde = `Pilote_YYYY-MM-DD_HHhMM.zip` dans la destination. Deux
  sauvegardes dans la même minute portent le même nom et s'écrasent : c'est voulu.
* Écriture en `.zip.part` puis `os.replace()` — une clé débranchée en plein milieu
  ne laisse jamais une archive tronquée sous un nom valide.
* `icones/` et les `.tmp` sont exclus (regénérables). Les `backups_*` sont inclus.
* **La clé est retrouvée par son numéro de série de volume**, pas par sa lettre :
  `E:` qui devient `F:` au rebranchement suivant est suivi automatiquement
  (`_volume_info()` via `GetVolumeInformationW`). Si la clé mémorisée est absente,
  on ne se rabat **pas** sur le chemin brut — il pointerait sur une autre clé ayant
  hérité de la lettre.
* **Un numéro de série nul (`00000000`) est traité comme absent.** Constaté sur une
  vraie clé FAT32 bas de gamme : elle n'en a pas. Le garder reviendrait à « reconnaître »
  n'importe quelle autre clé sans numéro. Repli alors sur le **nom de volume**, puis
  sur le chemin brut. Ne pas « simplifier » en refaisant confiance au numéro.
* Rotation : les `keep` archives les plus récentes (10 par défaut).
* Auto au démarrage dans un thread (`main()`), silencieuse si la clé est absente.
* `restore_from()` : valide l'archive, écrit une archive de sécurité de l'état
  actuel à côté de `Donnees/`, puis **écrase fichier par fichier sans vider le
  dossier** — une archive incomplète ne doit jamais faire disparaître un
  utilisateur qui n'y figure pas. `sauvegarde.json` est volontairement exclu de la
  restauration (sinon on repointerait vers une clé qu'on n'utilise plus).
  Protection zip-slip sur chaque membre.
* API : `sauvegarde_status`, `sauvegarde_set_config`, `sauvegarde_pick_folder`,
  `sauvegarde_use_drive`, `sauvegarde_run`, `sauvegarde_list`,
  `sauvegarde_restore`, `sauvegarde_open_folder`, `sauvegarde_push_usb`,
  `sauvegarde_usb_state`.
* UI : Paramètres → **Sauvegarde USB** (`data-sec="sauvegarde"`), fonctions `sv*`.
  `setGoSection()` déclenche `svRefresh()` seulement à l'ouverture de cette
  section — elle interroge le disque.
* Rien n'est chiffré : le zip est aussi lisible que les JSON d'origine.

**Deux mécanismes distincts, volontairement :**

| | Bouton « 🔑 Téléverser » (accueil) | Archives (Paramètres) |
|---|---|---|
| Écrit | `<clé>/Pilote/Donnees/` en miroir | `Pilote_<date>.zip` |
| Historique | aucun, on écrase | rotation des N dernières |
| Pour | récupérer ses fichiers tout de suite | remonter dans le temps |

`push_to_usb()` choisit la clé toute seule s'il n'y en a qu'une, sinon l'UI
demande laquelle. Le miroir **n'efface jamais** de fichier sur la clé : un
dossier Donnees vidé par accident ne doit pas détruire la sauvegarde.

## Multi-utilisateurs

* API Python (`Api` dans app.py) : `get_users`, `add_user(label, emoji, color)`,
  `update_user`, `delete_user`, `set_active_user`.
* `storage.slugify()` fabrique le slug de dossier. `delete_user` retire l'utilisateur
  de la liste mais **conserve son dossier** sur le disque.
* Côté JS : `USERS_STATE`, `_loadUsers(force)`, `renderHomeUsers()`, `switchUser(slug)`
  (bascule + `location.reload()`), `openUserModal(slug|null)`, `renderUsersList()`,
  `_renderUserPill()` (pastille en bas de sidebar), `userAvatarHtml(u, cls)`.
* `server.with_pin_flags(state)` ajoute `hasPin` à chaque utilisateur — utilisé pour
  afficher le cadenas 🔒.
* **Isolation** : `storage.scan_orphan_data()` exclut tout ce qui vit sous
  `get_app_dir()`. Sans ça l'écran de bienvenue proposerait d'importer les données
  d'un autre utilisateur de la même installation. Ne pas retirer ce filtre.

## Code PIN (un par utilisateur)

* Hash SHA-256 salé dans `users/<slug>/pin.hash`.
* Endpoints `/pin/required`, `/pin/set`, `/pin/check` — tous acceptent `?user=<slug>` ;
  sans ce paramètre ils répondent pour l'utilisateur actif.
* JS : `_isPinRequired(slug)`, `_verifyPin(pin, slug)`, `_setPinServer(pin, slug)`,
  `_checkPinLock()` (écran de verrouillage, awaité dans `boot()` **avant** `renderAll()`).
* L'écran de verrouillage affiche l'avatar + le nom du compte verrouillé et propose
  d'ouvrir un autre compte (chacun reste protégé par son propre code).
* Ça sépare les espaces, ça ne chiffre rien : les JSON restent lisibles sur le disque.

## Icône à la couleur du thème (`appicon.py`)

* Regénère un `.ico` multi-résolution (PNG embarqués, supersampling 4× + LANCZOS,
  même rendu que `assets/make_icon.py`) à la couleur d'accent, mis en cache dans
  `Donnees/icones/pilote_<hex>.ico`.
* Appliqué à la fenêtre + vignette barre des tâches via `WM_SETICON`, sur
  `window.events.shown` et à chaque enregistrement des paramètres
  (`Api.set_app_icon_color`).
* Les raccourcis Windows (.lnk du Bureau, menu Démarrer, barre des tâches épinglée)
  ne se recolorent que sur demande explicite : bouton « 🎨 Recolorer les raccourcis »
  dans Paramètres → Général (`Api.apply_icon_to_shortcuts`, via WScript.Shell).
* L'icône gravée dans le `.exe` reste celle du build : elle ne peut pas changer à chaud.
* Pillow est déclaré dans les `hiddenimports` de `build/pilote.spec` (import paresseux).

## Pour sortir une nouvelle version

1. Modifier le code
2. Bumper `APP_VERSION` dans `src/app.py`
3. Bumper `AppVersion` dans `build/installer.iss`
4. `git add … && git commit && git tag vX.Y.Z && git push origin main && git push origin vX.Y.Z`
5. GitHub Actions build `Pilote.exe` + `Pilote_Setup.exe` et crée la release

Règle importante : le numéro de version ne peut qu'augmenter (comparaison sémantique).
Ne jamais descendre sinon l'auto-updater croit que l'app est déjà à jour.

## Système d'auto-update (tout est en place, ne pas casser)

* `updater.py` interroge
  `https://api.github.com/repos/arthur-soulard/arthurpilote.github.com/releases/latest`
* Il retient le premier asset dont le nom finit par `Setup.exe`
* Si nouvelle version → modal dans l'UI avec barre de progression
* Téléchargement chunké avec progression réelle (fallback 25 Mo si Content-Length absent)
* Un batch Windows attend la fin du process (nom déduit de `sys.executable`, donc
  résistant à un renommage), puis 5 secondes de plus pour libérer le verrou fichier
  PyInstaller `_MEI*`, puis lance `Setup.exe /VERYSILENT /NORESTART /SUPPRESSMSGBOXES`
* L'app se ferme, l'installeur tourne en silence, l'utilisateur relance manuellement
* Logs : `%APPDATA%\Pilote\update.log` et `%TEMP%\pilote_update\update_bat.log`

Points critiques :
* Dans le JS, utiliser `querySelector("#update-modal .upd-btns")` et non
  `getElementById("upd-btns")`
* Le polling JS (`setInterval` 400 ms) doit démarrer **avant** l'appel Python `start_update()`
* `start_update()` côté Python est non-bloquant (lance un thread)
* Ne pas réduire le délai de 5 secondes du batch

## Navigation

Titlebar custom (fenêtre frameless, 36 px) : logo + « Pilote » + boutons fenêtre.
Topbar minimale : logo + « Pilote », indicateur « Dernière actualisation HH:MM » avec
↻ Actualiser (`.refresh-grp`), et ↩ Retour (undo).

Sidebar : un onglet **Accueil** seul en tête, puis 7 sections en accordéon
(`NAV_SECTIONS` dans index.html). Une seule section dépliée à la fois, un second clic
sur l'en-tête la referme, aucune section n'est obligatoirement ouverte. Une pastille
marque la section contenant l'onglet actif. En bas : pastille utilisateur, thème,
Paramètres.

| Entrée          | Onglets (ids des panes : `pane-<id>`)                              |
|-----------------|--------------------------------------------------------------------|
| Accueil         | home                                                               |
| PEA             | dash, pos, perf, sector, div, tx, wish, dep, strat, sim            |
| Mes comptes     | fin-month, fin-year                                                |
| Prêt étudiant   | pr-overview, pr-pea, pr-av, pr-liv, pr-params                      |
| Sports          | sp-agenda, sp-goals, sp-stats                                      |
| Patrimoine      | pa-vue, pa-comptes                                                 |
| Santé           | sa-suivi, sa-mesures, sa-goals                                     |
| Formation       | fo-todo, fo-done, fo-cv, fo-stats                                  |

Fonctions : `_injectSidebar()`, `_setActiveSidebar(id)`, `_navToggleSection(secId)`,
`_navSectionOf(tabId)`. Section dépliée persistée dans `S.uiPrefs.navOpen` ("" = tout
replié). `SIDEBAR_ITEMS` reste dérivé à plat de `NAV_SECTIONS` pour l'API historique
(onglets masquables via ⊘, Ctrl+1..7, écran Paramètres).

Chaque module annexe ajoute son propre patch de `window.goTab` en fin de fichier
(finances, sports, prêt, accueil) : ils s'enchaînent, ne pas casser l'ordre.

## Page d'accueil (`pane-home`)

Ouverte au démarrage. `homeGreeting()` renvoie « Bonjour » avant 18 h, « Bonsoir » après ;
`homeDisplayName()` prend le nom de l'utilisateur actif (sinon `S.prenom`).

Mise en page centrée : grande salutation (`clamp(38px, 5.2vw, 62px)`), date, rang des
utilisateurs (`#home-users`, cliquable pour basculer + « Nouvel utilisateur »), boutons
⚙ Paramètres / ↓ Exporter / ↑ Importer / 🔑 Téléverser vers clé USB, l'état de la clé
(`#home-usb-state`), puis les tuiles décalées vers le bas.

Depuis la 4.1.4, `homeRender()` ne fait plus que la salutation et la date : **les tuiles
sont déléguées à `dashRender()`** (voir « Accueil : tableau de bord modulaire »). Il n'y
a plus de carte codée en dur.

`homeRender()` est rappelée par `renderMetrics()`, `spBootstrap()`, `saRenderAll()`,
`paRenderAll()`, la fin de `boot()` et à chaque `goTab("home")` — ce dernier
rafraîchit aussi l'état de la clé USB (`svRenderUsbState()`) et sort du mode
édition des tuiles quand on quitte l'accueil.

**Écran de bienvenue** (`_showWelcomeIfFirstRun()`) : s'affiche quand le PEA est vide,
donc aussi pour chaque utilisateur nouvellement créé. Il présente les suivis,
rappelle de quel espace il s'agit, et ne propose en récupération que des installations
**extérieures** (voir `scan_orphan_data`).

## Paramètres (`openSettings(section)`)

Modale unique à colonne de sections (`setGoSection(id)`), plus « paramètres du PEA » :

| Section    | Contenu                                                            |
|------------|--------------------------------------------------------------------|
| general    | thème, couleur d'accent, icône de l'app, code PIN de l'utilisateur  |
| users      | liste des utilisateurs, création / édition                          |
| nav        | onglets et blocs masqués (restauration)                             |
| pea        | prénom, banque, date d'ouverture, récap fiscal, rapport annuel      |
| comptes    | catégories & emoji, sources, récurrents                             |
| pret       | renvoi vers l'onglet `pr-params`                                    |
| sport      | mes sports, types de séance, routines                               |
| formation  | domaines, dossier des certificats, nettoyage des orphelins          |
| accueil    | tuiles du tableau de bord (idem bouton ✎ de l'accueil)             |
| sauvegarde | destination USB, sauvegarde auto, rotation, restauration            |
| donnees    | dossier, export/import, mise à jour, réinitialisation, version      |

`openConfig()` reste le point d'entrée historique (ouvre sur `general`). Les onglets
Mes comptes et Sports ont un bouton ⚙ dans leur barre d'actions qui ouvre directement
leur section.

## Serveur local (server.py, port 7438)

* `GET /data` → hydratation initiale de l'UI (+ `_debug.load_error`)
* `GET /cours?tickers=EPA:ESE,WPEA.PA` → cours actuels + variations d1/w1/m1/y1
* `GET /history?tickers=…[&range=max]` → historique journalier
  (ranges : 1mo, 3mo, 6mo, ytd, 1y, 2y, 5y, 10y, max)
* `GET /sparkline`, `/keystats`, `/analysts`, `/search`, `/ping`
* `GET /users` → liste des utilisateurs (+ `hasPin`)
* `GET /pin/required`, `/pin/set`, `/pin/check` — tous avec `?user=<slug>` optionnel
* `GET /scan-orphan-data` → candidats de récupération (installations extérieures)
* `GET /recover-data?from=…` → **le chemin doit figurer dans le scan**, sinon 403 :
  cet endpoint écrase le `pea_data.json` actif, il ne prend pas un chemin libre
* `GET /vendor/<fichier>` → Chart.js et polices, liste blanche d'extensions
  (`.js`, `.css`, `.woff2`), confiné sous `ui/vendor/`
* Cache serveur : 1 h pour l'historique, 60 s pour les cours
* Tickers : `EPA:XXX` → `XXX.PA` (`AMS:`→`.AS`, `ETR:`→`.DE`, `LON:`→`.L`) ; un ticker
  déjà au format Yahoo (`WPEA.PA`) passe tel quel

### ⚠ Le serveur local n'est PAS un endroit privé

Il écoute sur `127.0.0.1`, mais **tout site ouvert dans n'importe quel navigateur du
PC peut lui parler** pendant que Pilote tourne. Avant la 4.2.0, un simple
`fetch("http://127.0.0.1:7438/data")` depuis une page web suffisait à lire le PEA,
les comptes, le patrimoine et la santé — le serveur répondait avec
`Access-Control-Allow-Origin: *`.

Trois verrous, chacun couvrant ce que les autres ne couvrent pas. **Ne pas en
retirer un en pensant que les deux autres suffisent :**

1. **Jeton de session** (`_SESSION_TOKEN`) — régénéré à chaque lancement, injecté
   dans la page au moment de la servir par `_inject_session_token()`, exigé sur tous
   les endpoints de données. Le bloc injecté enveloppe `window.fetch` une fois pour
   toutes : les appels existants n'ont rien à savoir du jeton. → contre le scan de port.
2. **Refus de tout `Origin` étranger** — notre page n'en envoie pas sur un GET
   same-origin, une page tierce en envoie toujours un. → contre le navigateur complice.
3. **Vérification du `Host`** — un domaine attaquant pointé sur `127.0.0.1` arrive
   avec son propre Host. → contre le DNS rebinding.

Corollaires à ne pas défaire :

* **Aucun en-tête CORS.** Tout est same-origin ; il n'y a rien à autoriser.
* **CSP stricte** (`_CSP`) + `X-Frame-Options: DENY` + `nosniff` + `no-referrer`.
  C'est elle qui interdit les CDN : d'où `ui/vendor/`. Ne pas rajouter de
  `<script src="https://…>` dans index.html, il sera silencieusement bloqué.
* `/vendor/` est joignable **sans** jeton : le navigateur charge `<script src>` et
  `<link href>` lui-même, ces requêtes ne passent pas par le wrapper `fetch`. Ces
  fichiers ne contiennent aucune donnée utilisateur, et les verrous Host et Origin
  s'appliquent toujours.
* `/pin/set` exige l'**ancien** code dès qu'un PIN existe. Poser un premier PIN
  reste libre : il n'y a rien à prouver.
* `/pin/check` est ralenti (0,25 s) et bloqué 60 s après 10 échecs, **côté serveur**.
  Le compteur de l'écran de verrouillage est purement cosmétique et ne protège rien.

## Module Sports (sports.json)

API Python : `load_sports()` / `save_sports()` — `load_sports` renvoie aussi le
catalogue (`SPORTS`) et les champs disponibles (`FIELD_CATALOG`).

Catalogue livré : `course`, `velo`, `natation`, `muscu`, `foot`, `rando`, `autre`.
Chaque sport déclare ses `fields`, ce qui pilote le formulaire côté UI via `spHasField()`.

* course   : distance_km, duration, elevation, subtype
* velo     : distance_km, duration, elevation
* natation : distance_m, duration, lieu (libre / 25 / 50)
* muscu    : duration, groups, routine
* foot     : duration, kind (entrainement / match)
* rando    : distance_km, duration, elevation, subtype
* autre    : duration

**Sports personnalisés** : `SP.customSports` = `[{id, label, icon, color, fields}]`.
L'utilisateur les crée depuis le sélecteur de « Nouvelle séance » (bouton
« + Ajouter un sport ») ou Paramètres → Sports → Mes sports, et coche les informations
à saisir parmi `FIELD_CATALOG` (les mêmes que les sports livrés). Id préfixé `perso_`.
`spRebuildCatalog()` compose `SP_CATALOG` = `SP_BASE_CATALOG` + perso + `autre` en
dernier. `spSportById()` retombe explicitement sur `autre`, jamais sur le dernier
élément du tableau. Un sport utilisé par des séances ne peut pas être supprimé.

Ne pas remettre d'`id` de sport en dur dans le code : c'est `spHasField()` qui décide
(distance en mètres, lieu, routine, groupes, kind…).

Données :
* sessions : `{id, date "YYYY-MM-DD", time, sport, duration (min), distance
  (km, ou mètres si le sport a le champ distance_m), elevation, note, + champs du sport}`
* routines : `{id, name, note}` — de simples libellés de circuits, rattachés aux
  séances de muscu par `routineId`. PAS de liste d'exercices.
* goals    : kind `perf` (validation manuelle) ou `event` (date + compte à rebours)
* subtypes : `{"course": [...], "rando": [...]}` — types de séance modifiables

Ce qui compte le plus pour Arthur : le NOMBRE D'HEURES. C'est le KPI principal
partout (accent, première position). L'agenda affiche une bulle emoji de 30 px par
séance (4 par ligne max) + le total d'heures du jour, détail au clic.

## Module Patrimoine (patrimoine.json)

Vue consolidée de ce qu'on possède. **Saisie manuelle une fois par mois** :
l'agrégation bancaire automatique suppose un contrat pro et une validation
réglementaire, hors de portée d'une app locale. Six chiffres par mois suffisent.

API Python : `load_patrimoine()` / `save_patrimoine()` — les deux renvoient
`net`, `serie` et `moisSaisi` déjà calculés, l'UI ne recalcule pas.

* comptes : `{id, label, type, icon, color, auto, archived, note}`
* releves : `{id, compteId, date:"YYYY-MM-01", montant}`

**Trois règles à ne pas casser :**

1. **Tous les relevés sont ancrés au 1er du mois.** C'est ce qui rend la série
   comparable d'un mois à l'autre (`paMoisIso`, `mois_courant`).
2. **Un compte non mis à jour garde sa dernière valeur connue** (`net_worth`
   prend le relevé le plus récent *à cette date ou avant*). Sans ça, oublier
   une ligne ferait s'effondrer le patrimoine ce mois-là.
3. **Le PEA et le prêt ne se saisissent pas** : comptes marqués `auto`,
   pré-remplis par `paValeurAuto()` depuis `window._peaPv.total` et `PR.pret`.
   Pas de double saisie. `_peaPv.total` est posé par `renderMetrics()` — ne pas
   recalculer la valorisation du PEA en parallèle.

Seul le type `dette` compte négativement. Un compte `auto` ne peut pas être
supprimé : il serait recréé au chargement suivant.

## Accueil : tableau de bord modulaire

`homeRender()` ne fait plus que la salutation et délègue les tuiles à
`dashRender()`. Chaque tuile est déclarée dans `DASH_WIDGETS`
(`{id, label, module, tab, render()}`).

* `render()` renvoie `null` quand le module n'a rien à dire → la tuile
  **disparaît** au lieu d'afficher un tiret. C'est ce qui garde l'accueil utile
  (ex. le rappel de relevé s'efface une fois le mois saisi).
* Activation et ordre vivent dans `S.uiPrefs.dash`, réglés dans
  Paramètres → **Accueil** (glisser-déposer, `dashRenderConfig`).
* `DASH_DEFAUT` reproduit l'accueil historique (PEA, sport, objectif sportif) :
  une installation existante ne change pas d'aspect après mise à jour.
* Un widget ajouté par une version ultérieure apparaît **éteint** en fin de
  liste, jamais activé d'office.

### Le crayon : on change les tuiles depuis l'accueil

Bouton **✎ Modifier les tuiles** (`.dash-bar`, au-dessus de la grille) →
`dashToggleEdit()` bascule `_dashEdit` et pose `.dash-editing` sur `#home-cards`.
En mode édition :

* chaque tuile devient cliquable → `dashOpenPick(id)` : la modale `ov-dash-pick`
  liste les widgets et celui qu'on choisit prend **exactement la place** de
  l'ancien (`dashPickApply`) ;
* ✕ retire la tuile, la carte pointillée « + Ajouter une tuile » en ajoute une
  à la fin, le glisser-déposer réordonne (`dashWireHomeDnd` / `dashMove`) ;
* une tuile activée mais sans donnée reste visible en grisé : hors édition elle
  disparaît, mais si elle disparaissait aussi ici on ne pourrait plus la changer.

Paramètres → Accueil reste là et lit la même config : les deux écrans se
resynchronisent (`dashRender()` + `dashRenderConfig()` après chaque écriture).

### Pourquoi les tuiles n'attendent plus

`dashModuleReady(module)` dit si le module a fini de charger. Tant que non, la
tuile affiche un **squelette** au lieu de rien : une tuile absente deux secondes
donnait l'impression que l'accueil ne marchait pas.

Et surtout, `boot()` charge **les six modules en parallèle**
(`Promise.all`), Santé et Patrimoine compris. Avant la 4.2.1 ils n'étaient
bootstrapés qu'à la première visite de leur onglet : leurs quatre tuiles
restaient vides à vie tant qu'on n'y était jamais allé, et cocher la case dans
les paramètres ne faisait visiblement rien. `saBootstrap(discret)` et
`paBootstrap(discret)` chargent alors les **données seules** : le patch de
`goTab` dessine le panneau à la première visite, inutile de le faire au démarrage.

De même, `svRenderUsbState()` publie désormais `window._dashUsb` — la tuile
« Sauvegarde USB » lisait cette variable que personne n'écrivait.

## Module Formation (formation.json)

Ce qui nourrit le CV. Trois natures d'objets sous le même toit, et c'est ce qui
dicte le découpage en quatre onglets :

* les **formations**, qui progressent (`todo` → `encours` → `fini`) et portent
  un certificat une fois terminées — onglets `fo-todo` et `fo-done` ;
* les **expériences, projets et compétences**, qui ne progressent pas : ils
  existent, on les décrit, ils alimentent l'export — onglet `fo-cv` ;
* les **compteurs**, dans `fo-stats`.

API Python : `load_formation()` / `save_formation()` — `load_formation` renvoie
aussi les catalogues (`STATUTS`, `FORMATS`, `PREUVES`, `PRIORITES`, `NIVEAUX`,
`CATEGORIES_COMPETENCE`) et l'état du dossier des certificats. Plus
`formation_add_certificat`, `formation_open_certificat`,
`formation_remove_certificat`, `formation_certificats_state`,
`formation_clean_orphans`, `formation_open_certificats_folder`.

Données :

* formations  : `{id, titre, organisme, url, description, domaineId, format,
                preuve, ects, cpf, dureeEstimee, statut, dateDebut, dateFin,
                dateEcheance, priorite, note, certificat}`
* experiences : `{id, poste, employeur, lieu, debut, fin, missions[], note}`
* projets     : `{id, nom, url, description, techno[], debut, fin, note}`
* competences : `{id, label, categorie, niveau 1-4}`
* domaines    : `{id, label, icon, color}` — éditables, emoji via `finPickIcon`

**Quatre décisions à ne pas défaire :**

1. **Les certificats sont COPIÉS**, jamais référencés là où ils se trouvent
   (`Donnees/users/<slug>/certificats/`). Un chemin vers Téléchargements casse
   au premier rangement, et surtout la sauvegarde USB ne l'embarquerait pas —
   or un certificat est précisément ce qu'on ne peut pas régénérer. Extensions
   en liste blanche, 25 Mo maximum, nom de fichier confiné au dossier
   (`_resolve()`, même protection que le zip-slip de `sauvegarde.py`).
   Ils ne sont **pas** dans les backups quotidiens : `JsonStore` ne sauvegarde
   que le JSON, rien à faire de particulier.
2. **Pas de champ coût.** L'argent vit dans « Mes comptes » ; un même montant
   saisi à deux endroits finit toujours par diverger. Reste `cpf`, qui est une
   info de repérage et pas un montant.
3. **Pas de compteur d'heures.** Une formation a un statut, pas un chronomètre.
   `dureeEstimee` sert aux totaux « charge à venir » et « heures cumulées », et
   personne n'a à la tenir à jour. Un compteur faux vaut moins que pas de compteur.
4. **Supprimer une formation ne supprime pas son certificat**, comme
   `delete_user` qui conserve le dossier. Le ménage est explicite :
   Paramètres → Formation → « Nettoyer les orphelins ».

Détails qui ont une raison :

* `foDomaine()` retombe explicitement sur `dom_autre`, jamais sur le dernier
  élément du tableau. Et `foRenderChartDom()` regroupe par domaine **résolu**,
  pas par id brut : sinon une formation dont le domaine a disparu s'évapore du
  camembert tout en comptant dans le KPI juste au-dessus.
* `foSaveFormation()` efface `dateEcheance` quand le statut passe à `fini`, et
  `dateFin` quand il n'y est plus : sans ça un badge « J−12 » survit sur une
  formation déjà validée.
* `foSafeUrl()` n'ouvre que du `http(s)` — le champ lien est libre.
* Le `poids` des `PREUVES` (diplôme 5 → aucune 1) ordonne l'export CV et le
  graphique : un diplôme se lit avant un badge de MOOC.
* Un domaine utilisé par des formations ne peut pas être supprimé.
* L'export CV est un **bloc de texte à copier**, généré en JS (`foCvText()`).
  Pas de PDF mis en page : il serait retouché ailleurs de toute façon.
* Le fichier est livré avec huit formations d'exemple (`_seed_formations`) —
  un point de départ à corriger, pas une recommandation gravée.

Tuiles d'accueil : `formation-encours`, `formation-annee`, `formation-todo`.
Les échéances restent dans le module (badge dans la liste `fo-todo`) : elles ne
remontent volontairement pas sur l'accueil.

## Module Santé (sante.json)

Pesées de la balance connectée, saisies depuis les captures d'écran de l'app
**FitDays** — il n'existe pas d'API, la capture est le seul pont praticable.

API Python : `load_sante()` / `save_sante()` (+ le catalogue `METRICS`),
`read_screenshots(paths)`, `ocr_available()`.

### Les 14 mesures

`poids` · `imc` · `graisse` · `taux_musculaire` · `poids_sans_graisse` ·
`graisse_sous_cutanee` · `graisse_viscerale` · `eau` · `muscle_squelettique` ·
`masse_musculaire` · `masse_osseuse` · `proteine` · `metabolisme` · `age_corporel`

Chacune porte son `unit`, ses `decimals`, ses `aliases` OCR et son `range`
(bornes physiologiques).

### OCR — ce qui a été mesuré, ne pas le redécouvrir

Moteur : **Windows.Media.Ocr** via `ocr_win.ps1` (PowerShell + WinRT). Aucune
dépendance nouvelle, hors ligne, les captures ne quittent jamais le PC.
Pillow prépare les images ; `ocr_win.ps1` est dans les `datas` de la spec.

Résultat sur les captures réelles : **14/14 en ~10 s** (3 captures).

Quatre pièges, tous traités — ne pas « simplifier » :

1. **La résolution d'origine bat les agrandissements.** Contre-intuitif, mais
   mesuré : 10 valeurs lues à l'échelle 1 contre 8-9 à l'échelle 3, et deux
   fois plus vite. Les petits nombres isolés (graisse viscérale) disparaissent
   dès qu'on agrandit. L'ordre de `VARIANTS` encode ce résultat.
2. **Appariement par COLONNES, jamais par lignes.** FitDays coupe ses libellés
   longs sur deux lignes et place la valeur sur la ligne du milieu :
   `Graisse` / `21.3 %` / `corporelle`. Un appariement ligne à ligne rate la
   moitié des mesures (voir `_extract_values` et `_label_blocks`).
3. **Comparaison des libellés par ENSEMBLE de mots** (`_match_metric`) : le
   moteur renvoie « Corporelle Eau » et « Graisse sous- cutanee eee ».
   L'alias le plus spécifique gagne, sinon « Poids sans graisse » devient
   « Poids ».
4. **L'écran principal est piégé.** Son bloc « Contraste » affiche les ÉCARTS
   depuis la pesée précédente (+1.2 kg, +0.4 %) avec le libellé SOUS le
   chiffre : sans `_contraste_cutoff()`, un écart de 0.4 % est enregistré comme
   une valeur. Le gros cadran, lui, n'a pas de libellé : `_dial_weight()` le
   reconnaît à sa taille (repli quand seul cet écran est fourni).

Autres garde-fous : `%` rendu « 0/0 » (`_PCT_GARBLE`), point décimal perdu
(« 152 » → 15.2 via `_validate`, qui REFUSE plutôt que d'inscrire une valeur
hors bornes), dates rejetées comme valeurs (`_NOT_A_VALUE`).

### L'import ne valide jamais tout seul

L'OCR pré-remplit un formulaire, **surligne en rouge** ce qu'il n'a pas su lire
et attend une validation. Une donnée de santé fausse est pire qu'une donnée
absente : ne pas transformer ça en enregistrement direct.

Données :
* mesures : `{id, date, time, source:"ocr"|"manuel", note, + les 14 métriques}`
* goals   : `{id, metric, target, start, date, status, createdAt, note}`
  → avancement = distance parcourue / distance totale ; perte et gain se
    calculent pareil (`saGoalProgress`, côté JS uniquement — il n'y a
    volontairement pas de second calcul en Python)

UI : `sa*` dans index.html. Les métriques où **baisser est bon** (poids, IMC,
graisses, âge corporel) sont listées dans `saDeltaClass` — c'est ce qui décide
de la couleur verte ou rouge.

## Module Mes comptes (finances.json)

Catégories et sous-catégories **portent chacune un emoji** (`icon`), affiché partout :
liste des transactions, sélecteurs, camembert, top de l'année, récurrents.

* `finCatIcon(c)` / `finSubIcon(s)` avec repli (🏷️ dépense, 💰 revenu, • sous-catégorie)
* `finPickIcon(current, titre, callback)` ouvre la modale `ov-fin-icon` (palette + saisie libre)
* `finances.backfill_icons()` côté Python donne un emoji aux fichiers créés avant la 4.1.2,
  en reconnaissant les libellés du jeu par défaut

## Module Prêt étudiant (pret.json)

API Python : `load_pret()` / `save_pret()`. Capitalisation annuelle de l'AV et moteur
événementiel du Livret A repris à l'identique de l'ancienne app standalone (abandonnée).

* pret        : `{montant, date_deblocage, date_premier_remboursement,
                duree_remboursement, mensualite}`
* pea.achats  : `{id, date, ticker, montant, quantite, cours_achat}`
* pea.ventes  : `{id, date, ticker, quantite, cours_vente, montant (crédité)}`
  → PRU pondéré sur les achats, plus-value réalisée = crédité − qté × PRU,
    plus-value latente sur les parts restantes
* av.contrats : `[{id, label, taux_annuels:[{annee,taux}], depots:[{id,date,montant,note}]}]`
  → MULTI-CONTRATS, chacun avec ses propres taux
* liv         : `{label, taux_history:[{id,date,taux}], mouvements:[{id,date,type,montant,note}]}`
* frais_recurrents : prélevés le MÊME JOUR chaque mois (jour pris sur `date_debut`,
  ramené au dernier jour du mois quand il n'existe pas — voir `prAddMonths`)

Les cours passent par le serveur local (`/cours`), pas de second proxy Yahoo.

## Graphique « Évolution du capital » (onglet Performance, `#card-twr`)

5 plages dans `#perf-range-btns` : 1S (prb-1w), 1M (prb-1m), 6M (prb-6m),
YTD (prb-ytd), Max (prb-max, défaut).

* `setPerfRange(range)`   — change la plage, highlight le bouton, sauvegarde dans
                            `S.uiPrefs.perfRange`, appelle `drawPerfChart()`
* `filterByRange(series, range)` — filtre `_perfFullSeries` par date
                            (ancre = aujourd'hui local, pas le dernier point)
* `buildTwrSeries(history)` — série journalière à partir de l'historique Yahoo
* `drawPerfChart()`       — dessine le Chart.js ; si < 2 points après filtre →
                            bascule sur MAX avec message
* `loadPerfHistory()`     — double fetch : `range=max` + `range=1mo` (30 derniers jours
                            journaliers garantis, fusionnés) pour que 1S/1M aient
                            toujours leurs points récents
* `computePnl(series, allTxs, range)` — P&L sur la plage (TWR pour les plages partielles)

Format labels axe X : 1S, 1M, YTD → « 12 mai » ; 6M, Max → « nov. 25 »

Points critiques :
* `_perfFullSeries` est mis en cache (reconstruit uniquement si null), invalidé à
  chaque `renderPerf()`
* Le fallback < 2 points reset TOUS les boutons (pas seulement YTD/MAX)
* La plage préférée est persistée dans `S.uiPrefs.perfRange` via
  `pywebview.api.save_ui_prefs()`

## Conventions de code

* Tout l'UI vit dans `index.html` (~15 100 lignes). Les modules annexes sont des blocs
  JS autonomes en fin de fichier, préfixés (`fin*`, `sp*`, `pr*`, `sa*`, `pa*`, `dash*`,
  `sv*`, `home*`), avec leur propre patch de `goTab`. **Ordre d'insertion : Sports →
  Prêt → Santé → Patrimoine → Formation → Tableau de bord → `boot()`.** Les patches de `goTab`
  s'enchaînent, ne pas casser l'ordre.
* Primitives de DA à réutiliser : `.card/.card-h/.card-t/.card-b`, `.btn/.btn-primary/
  .btn-ghost/.btn-sm`, `table + .tw`, `.ov/.modal/.fg/.fg-row/.mact` + `closeOv(id)`,
  `.mkpis/.mkpi` (KPIs), `.m-tag`, `.m-empty`, `.m-note`, `.m-acts/.m-iconbtn`,
  `.set-layout/.set-nav/.set-sec` (paramètres), `.home-user/.home-user-av` (utilisateurs),
  `.sp-fields/.sp-field` (choix de champs), `.fin-ico` (emoji catégories),
  `.sa-grid/.sa-cell` + `.sa-fields/.sa-field` (santé), `.pa-cpt/.pa-leg` (patrimoine),
  `.dash-cfg-row` (tuiles), `.sv-drive/.sv-row` (clés USB),
  `showToastModern(msg, "ok"|"warn"|"err")`, `escHtml()`.
* Une `.ov` s'ouvre avec `classList.add("open")` — la règle CSS est `.ov.open
  { display: flex }`. Il n'y a pas de classe `show` pour les modales.
* Les `.ov` sont en `z-index: 9500` (au-dessus de la sidebar 9000, sous la titlebar
  10000). Une modale ouverte **depuis** une autre doit passer par `openOvTop(id)`,
  sinon l'ordre du DOM décide qui est devant.
* Attention à la spécificité : `.fg label` (0-1-1) impose MAJUSCULES + interlettrage.
  Un libellé de texte courant dans un `.fg` doit être ciblé en `label.ma-classe`,
  sinon la règle générale gagne.
* Couleurs uniquement via les variables CSS (`--bg2`, `--brd`, `--accent`, `--g`, `--r`,
  `--mono`…) : thème clair ET sombre, plus une couleur d'accent au choix.
* Un nouveau module de données = un fichier `src/<nom>.py` basé sur
  `jsonstore.JsonStore` + deux méthodes `load_`/`save_` dans la classe `Api` de `app.py`.
  Il sera automatiquement propre à chaque utilisateur. Penser à l'ajouter aussi
  à `DASH_WIDGETS` s'il a un chiffre à montrer sur l'accueil.
* Le JS garde l'état en mémoire (`S`, `SP`, `PR`, `SA`, `PA`) et Python ne fait que
  persister. Exception : `load_patrimoine` / `save_patrimoine` renvoient `net`, `serie`
  et `moisSaisi` déjà calculés — l'UI ne refait pas ces calculs.
* Ne jamais recalculer en parallèle un chiffre qu'un autre module produit déjà
  (`window._peaPv` pour le PEA). Deux calculs = deux résultats divergents un jour.

## Déploiement

* Téléchargement du Setup.exe :
  https://github.com/arthur-soulard/arthurpilote.github.com/releases/latest
* Les mises à jour suivantes sont automatiques depuis l'app

## Pistes en attente (proposées, non décidées)

**Les trois qui manquent le plus** — sans elles, Pilote n'est pas « l'app où je fais
tout ». Recommandées dans cet ordre :

- **Module Tâches** (`taches.json`) : échéance, priorité, projet, récurrence
- **Module Agenda** (`agenda.json`) : mois + semaine, fusionnant séances de sport,
  échéances de prêt, relevé de patrimoine, pesée du 1er
- **Écran « Aujourd'hui »** : tâches du jour + événements + séance prévue + échéances.
  Le premier écran à ouvrir le matin.

Autres pistes :

- Objectif d'heures hebdomadaire, avec jauge en haut de l'agenda sport
- Courbe d'heures cumulées année N vs N−1 dans les statistiques sport
- Échéancier prévisionnel du prêt, mois par mois jusqu'à la dernière mensualité
- Simulateur de sortie : « si je vends tout et solde le prêt, il me reste X € »
- Recherche globale (Ctrl+K) sur transactions, séances, pesées, comptes
- Emoji par défaut pour les catégories créées par l'utilisateur (aujourd'hui 🏷️)
- Import CSV du relevé bancaire pour « Mes comptes »

**Écartées, ne pas y revenir sans raison nouvelle :**

- **Version mobile / PWA** : écartée par Arthur en 4.1.4 pour la sécurité des données.
  Les JSON sont en clair et le PIN ne chiffre rien ; exposer le serveur local, même
  derrière un VPN, sortait les données du PC. Si la question revient, le prérequis
  serait le chiffrement au repos, pas le réseau.
- **Agrégation bancaire automatique** : contrat pro + validation réglementaire,
  hors de portée d'une app locale. D'où la saisie mensuelle du patrimoine.

**Traité depuis** : l'export de tout l'espace utilisateur, longtemps en attente, est
couvert par la sauvegarde USB (archive zip de tout `Donnees/`). L'import par fichier,
lui, ne couvre toujours que `pea_data.json`.
