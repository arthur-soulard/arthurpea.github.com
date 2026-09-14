"""
finances.py — Stockage du module "Mes comptes" (budget perso).

Comme pea_data.json, finances.json appartient a l'utilisateur actif.

Emplacement : <app_dir>/users/<slug>/finances.json
Backup quotidien : <app_dir>/users/<slug>/backups_finances/finances_YYYY-MM-DD.json

Ecriture atomique (.tmp -> rename) + rotation 7 jours, comme storage.py.
"""
from __future__ import annotations

import os
import json
import shutil
import datetime
import tempfile
from pathlib import Path
from typing import Optional

import storage


FINANCES_FILE = "finances.json"
BACKUP_DIR    = "backups_finances"
BACKUP_KEEP_DAYS = 7


# ─── Chemins ──────────────────────────────────────────────────────────────────

def get_finances_path() -> Path:
    return storage.get_user_dir() / FINANCES_FILE


def get_backup_dir() -> Path:
    d = storage.get_user_dir() / BACKUP_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─── Donnees par defaut ───────────────────────────────────────────────────────

def _default_categories() -> list:
    """Set FR complet : depenses + revenus, chacune avec sous-categories.

    Chaque categorie ET chaque sous-categorie porte un emoji : c'est lui qu'on
    lit en premier dans les listes de transactions, avant meme le libelle.
    """
    return [
        # ── Depenses ──
        {"id": 1, "name": "Alimentation", "icon": "\U0001f6d2", "type": "expense", "color": "#16a34a",
         "subs": [{"id": 1, "name": "Courses",     "icon": "\U0001f6d2"},
                  {"id": 2, "name": "Restaurants", "icon": "\U0001f37d\ufe0f"},
                  {"id": 3, "name": "Livraison",   "icon": "\U0001f6f5"}]},
        {"id": 2, "name": "Logement", "icon": "\U0001f3e0", "type": "expense", "color": "#2563eb",
         "subs": [{"id": 1, "name": "Loyer",                 "icon": "\U0001f511"},
                  {"id": 2, "name": "\u00c9lectricit\u00e9",          "icon": "\u26a1"},
                  {"id": 3, "name": "Internet",              "icon": "\U0001f4f6"},
                  {"id": 4, "name": "Eau",                   "icon": "\U0001f6b0"},
                  {"id": 5, "name": "Assurance habitation",  "icon": "\U0001f6e1\ufe0f"},
                  {"id": 6, "name": "Charges copropri\u00e9t\u00e9",  "icon": "\U0001f3e2"}]},
        {"id": 3, "name": "Transports", "icon": "\U0001f68c", "type": "expense", "color": "#d97706",
         "subs": [{"id": 1, "name": "Carburant",             "icon": "\u26fd"},
                  {"id": 2, "name": "Transports en commun",  "icon": "\U0001f687"},
                  {"id": 3, "name": "Taxi / VTC",            "icon": "\U0001f695"},
                  {"id": 4, "name": "Entretien v\u00e9hicule",   "icon": "\U0001f527"},
                  {"id": 5, "name": "Assurance auto",        "icon": "\U0001f6e1\ufe0f"},
                  {"id": 6, "name": "P\u00e9age / Parking",       "icon": "\U0001f17f\ufe0f"}]},
        {"id": 4, "name": "Sant\u00e9", "icon": "\U0001fa7a", "type": "expense", "color": "#dc2626",
         "subs": [{"id": 1, "name": "M\u00e9decin",             "icon": "\U0001f469\u200d\u2695\ufe0f"},
                  {"id": 2, "name": "Pharmacie",           "icon": "\U0001f48a"},
                  {"id": 3, "name": "Mutuelle",            "icon": "\U0001f4cb"},
                  {"id": 4, "name": "Dentiste / Optique",  "icon": "\U0001f453"}]},
        {"id": 5, "name": "Loisirs", "icon": "\U0001f3ad", "type": "expense", "color": "#7c3aed",
         "subs": [{"id": 1, "name": "Sorties",   "icon": "\U0001f37b"},
                  {"id": 2, "name": "Sport",     "icon": "\U0001f3c3"},
                  {"id": 3, "name": "Vacances",  "icon": "\u2708\ufe0f"},
                  {"id": 4, "name": "Culture",   "icon": "\U0001f3a8"}]},
        {"id": 6, "name": "Abonnements", "icon": "\U0001f501", "type": "expense", "color": "#0891b2",
         "subs": [{"id": 1, "name": "Streaming",          "icon": "\U0001f4fa"},
                  {"id": 2, "name": "T\u00e9l\u00e9phone",         "icon": "\U0001f4f1"},
                  {"id": 3, "name": "Cloud / Logiciels",  "icon": "\u2601\ufe0f"},
                  {"id": 4, "name": "Salle de sport",     "icon": "\U0001f3cb\ufe0f"}]},
        {"id": 7, "name": "Shopping", "icon": "\U0001f6cd\ufe0f", "type": "expense", "color": "#db2777",
         "subs": [{"id": 1, "name": "V\u00eatements",      "icon": "\U0001f455"},
                  {"id": 2, "name": "\u00c9lectronique",   "icon": "\U0001f4bb"},
                  {"id": 3, "name": "Maison / D\u00e9co",  "icon": "\U0001f6cb\ufe0f"}]},
        {"id": 8, "name": "Frais bancaires", "icon": "\U0001f3e6", "type": "expense", "color": "#71717a",
         "subs": [{"id": 1, "name": "Frais de tenue de compte", "icon": "\U0001f4c4"},
                  {"id": 2, "name": "Agios / D\u00e9couvert",       "icon": "\U0001f4c9"},
                  {"id": 3, "name": "Carte bancaire",            "icon": "\U0001f4b3"}]},
        {"id": 9, "name": "Cadeaux & dons", "icon": "\U0001f381", "type": "expense", "color": "#f59e0b",
         "subs": [{"id": 1, "name": "Cadeaux",             "icon": "\U0001f381"},
                  {"id": 2, "name": "Dons / Associations", "icon": "\u2764\ufe0f"}]},
        {"id": 10, "name": "Autres d\u00e9penses", "icon": "\U0001f4e6", "type": "expense", "color": "#a1a1aa",
         "subs": [{"id": 1, "name": "Divers", "icon": "\u2753"}]},
        # ── Revenus ──
        {"id": 11, "name": "Salaire", "icon": "\U0001f4b6", "type": "income", "color": "#16a34a",
         "subs": [{"id": 1, "name": "Salaire net",              "icon": "\U0001f4b6"},
                  {"id": 2, "name": "Heures suppl\u00e9mentaires", "icon": "\u23f0"}]},
        {"id": 12, "name": "Primes", "icon": "\U0001f31f", "type": "income", "color": "#22c55e",
         "subs": [{"id": 1, "name": "Prime annuelle",  "icon": "\U0001f38a"},
                  {"id": 2, "name": "Participation",   "icon": "\U0001f91d"},
                  {"id": 3, "name": "Int\u00e9ressement",  "icon": "\U0001f4c8"}]},
        {"id": 13, "name": "Remboursements", "icon": "\u21a9\ufe0f", "type": "income", "color": "#0d9488",
         "subs": [{"id": 1, "name": "S\u00e9curit\u00e9 sociale",     "icon": "\U0001f3e5"},
                  {"id": 2, "name": "Mutuelle",              "icon": "\U0001f4cb"},
                  {"id": 3, "name": "Frais professionnels",  "icon": "\U0001f4bc"}]},
        {"id": 14, "name": "Cadeaux re\u00e7us", "icon": "\U0001f388", "type": "income", "color": "#a3e635",
         "subs": [{"id": 1, "name": "Cadeaux", "icon": "\U0001f381"}]},
        {"id": 15, "name": "Autres revenus", "icon": "\U0001f4b0", "type": "income", "color": "#84cc16",
         "subs": [{"id": 1, "name": "Divers", "icon": "\u2753"}]},
    ]


# Emoji par defaut quand l'utilisateur n'en a pas choisi
FALLBACK_ICON = {"expense": "\U0001f3f7\ufe0f", "income": "\U0001f4b0"}


def _icon_index() -> dict:
    """{nom en minuscules -> emoji} construit sur le set par defaut."""
    idx = {}
    for c in _default_categories():
        idx[c["name"].lower()] = c["icon"]
        for s in c.get("subs") or []:
            idx.setdefault(s["name"].lower(), s["icon"])
    return idx


def backfill_icons(data: dict) -> dict:
    """
    Donne un emoji aux categories/sous-categories qui n'en ont pas encore
    (fichiers crees avant la v4.1.2). Reconnait les libelles par defaut,
    et retombe sur un emoji generique pour les categories perso.
    """
    idx = _icon_index()
    for c in data.get("categories") or []:
        if not c.get("icon"):
            c["icon"] = idx.get(str(c.get("name", "")).lower()) \
                        or FALLBACK_ICON.get(c.get("type"), "\U0001f3f7\ufe0f")
        for s in c.get("subs") or []:
            if not s.get("icon"):
                s["icon"] = idx.get(str(s.get("name", "")).lower()) or "\u2022"
    return data


def _default_sources() -> list:
    return [
        {"id": 1, "name": "Compte courant (CB)"},
        {"id": 2, "name": "Compte courant (Virement)"},
        {"id": 3, "name": "Compte courant (Prélèvement)"},
        {"id": 4, "name": "Espèces"},
        {"id": 5, "name": "Livret A"},
        {"id": 6, "name": "Carte crédit"},
        {"id": 7, "name": "Autre"},
    ]


def default_data() -> dict:
    return {
        "_meta": {
            "version": 1,
            "schema": "finances.v1",
            "createdAt":   datetime.date.today().isoformat(),
            "lastSavedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        },
        "categories":   _default_categories(),
        "sources":      _default_sources(),
        "transactions": [],
        "recurrences":  [],
        "_nid":         {"tx": 1, "cat": 16, "sub": 100, "src": 8, "rec": 1},
    }


# ─── Lecture / ecriture ───────────────────────────────────────────────────────

def load_data() -> dict:
    """Charge finances.json. Si absent ou KO, retourne les defauts (en memoire)."""
    path = get_finances_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = default_data()
            # Conserve les valeurs sauvegardees, complete avec les defauts manquants
            for k, v in data.items():
                merged[k] = v
            if "_meta" in merged and isinstance(merged["_meta"], dict):
                base_meta = default_data()["_meta"]
                for k, v in base_meta.items():
                    merged["_meta"].setdefault(k, v)
            if "_nid" in merged and isinstance(merged["_nid"], dict):
                base_nid = default_data()["_nid"]
                for k, v in base_nid.items():
                    merged["_nid"].setdefault(k, v)
            return backfill_icons(merged)
        except Exception as e:
            print(f"[finances] lecture KO: {e}", flush=True)
            # Tente le backup le plus recent
            backup = _latest_backup()
            if backup and backup.exists():
                try:
                    with open(backup, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
    return default_data()


def save_data(data: dict) -> None:
    """Ecriture atomique + backup quotidien."""
    path = get_finances_path()
    data.setdefault("_meta", {})
    data["_meta"]["lastSavedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
    data["_meta"].setdefault("schema",    "finances.v1")
    data["_meta"].setdefault("version",   1)
    data["_meta"].setdefault("createdAt", datetime.date.today().isoformat())

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".fin_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise

    _daily_backup(data)


def _daily_backup(data: dict) -> None:
    today = datetime.date.today().isoformat()
    backup_dir = get_backup_dir()
    backup_path = backup_dir / f"finances_{today}.json"
    try:
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[finances] backup quotidien KO: {e}", flush=True)
        return

    backups = sorted(backup_dir.glob("finances_*.json"))
    while len(backups) > BACKUP_KEEP_DAYS:
        old = backups.pop(0)
        try:
            old.unlink()
        except Exception:
            pass


def _latest_backup() -> Optional[Path]:
    backups = sorted(get_backup_dir().glob("finances_*.json"))
    return backups[-1] if backups else None
