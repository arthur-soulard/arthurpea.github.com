# Suivi PEA

Application Windows de suivi de Plan d'Épargne en Actions (PEA) — entièrement locale, données chiffrées sur votre machine, cours actualisés automatiquement via Yahoo Finance.

![icon](assets/icon_512.png)

## ✨ Fonctionnalités

- **Suivi complet** : positions, transactions (achats/ventes), dépôts, dividendes, wishlist
- **Cours auto-actualisés** toutes les 3 min via Yahoo Finance (zéro clé API)
- **Performance TWR** comparée à CAC 40, S&P 500 et ETF World
- **Simulateurs** : projection DCA, objectifs long terme, comparateur d'actifs (1m / 6m / YTD / 3-5-15 ans)
- **Stratégie** : règles personnalisables avec vérification automatique (concentration, allocation, frais...)
- **Sécurité** : code PIN à 4 chiffres optionnel
- **Personnalisation** : 7 couleurs d'accent, thèmes clair/sombre/auto
- **Multi-PEA** : gestion de plusieurs profils dans la même app
- **Rapport annuel** imprimable / exportable en PDF
- **100% local** : aucune donnée envoyée nulle part (sauf à Yahoo pour les cours publics)

## 📦 Installation

### Pour les utilisateurs

1. Télécharger la dernière version : [Releases](../../releases/latest)
2. Lancer **`Suivi_PEA_Setup.exe`**
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
python -m PyInstaller build/suivi_pea.spec --clean --noconfirm

# Build l'installateur (nécessite Inno Setup 6)
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build/suivi_pea.iss
```

Les fichiers générés sont dans `dist/`.

## 📂 Stockage des données

Les données utilisateur sont stockées localement dans le dossier `Donnees/` à côté de l'exécutable :

```
Suivi PEA/
├── Suivi_PEA.exe
└── Donnees/
    ├── default/
    │   ├── pea_data.json     # données du profil actif
    │   └── backups/          # backup quotidien (rotation 7 jours)
    ├── pin.hash              # hash du code PIN (si configuré)
    └── profiles.json         # liste des profils (multi-PEA)
```

Sur installation via Setup.exe : `%LocalAppData%\Programs\Suivi PEA\Donnees\`

## 🏗 Architecture

```
src/
├── app.py              # Point d'entrée pywebview, fenêtre native
├── server.py           # Serveur HTTP local (Yahoo proxy + endpoints data)
├── storage.py          # Lecture/écriture JSON, multi-profils, backups
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
