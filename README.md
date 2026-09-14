# Pilote

Application Windows de suivi personnel — bourse, budget, sport et prêt étudiant réunis
dans une seule app entièrement locale. Cours actualisés automatiquement via Yahoo Finance.

![icon](assets/icon_512.png)

## ✨ Les quatre univers

**PEA** — positions, transactions, dépôts, dividendes, wishlist, expositions sectorielle
et géographique, performance TWR comparée au CAC 40 / S&P 500 / ETF World, simulateurs
(projection DCA, objectifs, comparateur d'actifs), règles de stratégie vérifiées
automatiquement, rapport annuel imprimable.

**Mes comptes** — budget perso mois par mois : dépenses et revenus catégorisés (chaque
catégorie et sous-catégorie porte son emoji), sources, échéances récurrentes à valider,
récap annuel.

**Prêt étudiant** — suivi d'un prêt à 0 % utilisé comme capital d'investissement :
versements et remboursements, PEA dédié (achats, ventes, PRU, plus-values latentes et
réalisées), assurance vie multi-contrats à capitalisation annuelle, livret A, frais
ponctuels et récurrents.

**Sports** — agenda mensuel des séances (course, vélo, natation, muscu, foot, randonnée…),
sports personnalisés dont tu choisis les informations à saisir, objectifs de performance
et événements datés, statistiques d'heures et carte de régularité.

## ⚙ Transverse

- **Page d'accueil** avec les chiffres qui comptent, et une salutation selon l'heure
- **Multi-utilisateurs** : chacun a son propre PEA, ses comptes, son prêt et son sport —
  on change d'utilisateur directement depuis l'accueil
- **Cours auto-actualisés** toutes les 3 min via Yahoo Finance (zéro clé API)
- **Sécurité** : code PIN à 4 chiffres optionnel (il verrouille l'app entière)
- **Personnalisation** : couleur d'accent libre, thèmes clair / sombre — l'icône de la
  fenêtre et de la barre des tâches prend la couleur choisie
- **Paramètres par domaine** : une section par onglet (Général, Utilisateurs, Navigation,
  PEA, Mes comptes, Prêt, Sports, Données)
- **Mise à jour automatique** depuis les releases GitHub
- **100 % local** : aucune donnée envoyée nulle part (sauf à Yahoo pour les cours publics)

## 📦 Installation

### Pour les utilisateurs

1. Télécharger la dernière version : [Releases](../../releases/latest)
2. Lancer **`Pilote_Setup.exe`**
3. Si Windows SmartScreen affiche un avertissement : "Plus d'infos" → "Exécuter quand même"
4. Suivre l'assistant d'installation
5. Lancer depuis le menu Démarrer ou le raccourci bureau

### Compatibilité

- **Windows 10 / 11** (64 bits)
- Microsoft Edge WebView2 Runtime (pré-installé sur Windows 10+ depuis 2022)
- Connexion internet pour la mise à jour des cours (l'app fonctionne en mode hors-ligne avec le dernier cache)

## 🛠 Développement

### Prérequis

- Python 3.10+
- pip

### Setup

```bash
git clone https://github.com/<votre-user>/suivi-pea.git
cd suivi-pea
pip install -r requirements.txt
python src/app.py
```

### Build

```bash
# Génère l'icône
python assets/make_icon.py

# Build l'exécutable Windows
python -m PyInstaller build/pilote.spec --clean --noconfirm

# Build l'installateur (nécessite Inno Setup 6)
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build/installer.iss
```

Les fichiers générés sont dans `dist/`.

## 📂 Stockage des données

Les données utilisateur sont stockées localement dans le dossier `Donnees/` à côté de l'exécutable :

```
Pilote/
├── Pilote.exe
└── Donnees/
    ├── users.json            # liste des utilisateurs + utilisateur actif
    ├── users/
    │   └── <utilisateur>/
    │       ├── pea_data.json # PEA              (+ backups/)
    │       ├── finances.json # Mes comptes      (+ backups_finances/)
    │       ├── sports.json   # Sports           (+ backups_sports/)
    │       └── pret.json     # Prêt étudiant    (+ backups_pret/)
    ├── icones/               # icônes générées à la couleur d'accent
    └── pin.hash              # hash du code PIN (si configuré), commun à l'app
```

Migration automatique : une installation antérieure à la 4.1.2 (`profiles.json` +
fichiers de modules à la racine) est déplacée au premier lancement vers
`users/<slug>/`, sans perte. L'ancien `profiles.json` est conservé sous le nom
`profiles.legacy.json`.

Sur installation via Setup.exe : `%LocalAppData%\Programs\Pilote\Donnees\`

## 🏗 Architecture

```
src/
├── app.py              # Point d'entrée pywebview, fenêtre native, bridge Python/JS
├── server.py           # Serveur HTTP local (proxy Yahoo + endpoints data)
├── storage.py          # Données PEA, multi-utilisateurs, migration, backups
├── appicon.py          # Icône recolorée selon l'accent (fenêtre + raccourcis)
├── finances.py         # Module Mes comptes
├── sports.py           # Module Sports (+ catalogue des sports)
├── pret.py             # Module Prêt étudiant
├── jsonstore.py        # Socle commun : écriture atomique + backup quotidien
├── updater.py          # Mise à jour automatique
├── notifications.py    # Notifications Windows natives
└── ui/
    └── index.html      # UI complète (HTML + CSS + JS)
```

- **Backend Python** : serveur HTTP local sur 127.0.0.1 + bridge pywebview pour les actions critiques (PIN, save_data)
- **Frontend** : HTML/CSS/JS vanilla, Chart.js pour les graphiques
- **Persistance** : JSON simple, pas de base de données
- **Yahoo Finance** : authentification crumb + cookie pour les endpoints quoteSummary

## 🔒 Confidentialité

- Aucune donnée n'est envoyée vers un serveur tiers
- Seules les requêtes vers `query1.finance.yahoo.com` sont effectuées (cours publics)
- Le code PIN est haché en SHA-256 + salt avant stockage
- Aucun tracker, aucune analytique

## 📜 Licence

Voir [LICENSE](LICENSE).

---

*Made with [Claude](https://claude.ai) as pair-programmer.*
