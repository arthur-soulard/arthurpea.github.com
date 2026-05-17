"""
finances.py — Stockage du module "Mes comptes" (budget perso).

Contrairement a pea_data.json qui est par profil PEA, finances.json est
COMMUN a tous les profils (la compta perso ne depend pas du PEA actif).

Emplacement : <app_dir>/finances.json (a cote de profiles.json)
Backup quotidien : <app_dir>/backups_finances/finances_YYYY-MM-DD.json

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
    return storage.get_app_dir() / FINANCES_FILE


def get_backup_dir() -> Path:
    d = storage.get_app_dir() / BACKUP_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─── Donnees par defaut ───────────────────────────────────────────────────────

def _default_categories() -> list:
    """Set FR complet : depenses + revenus, chacune avec sous-categories."""
    return [
        # ── Depenses ──
        {"id": 1, "name": "Alimentation",       "type": "expense", "color": "#16a34a",
         "subs": [{"id": 1, "name": "Courses"},
                  {"id": 2, "name": "Restaurants"},
                  {"id": 3, "name": "Livraison"}]},
        {"id": 2, "name": "Logement",           "type": "expense", "color": "#2563eb",
         "subs": [{"id": 1, "name": "Loyer"},
                  {"id": 2, "name": "Électricité"},
                  {"id": 3, "name": "Internet"},
                  {"id": 4, "name": "Eau"},
                  {"id": 5, "name": "Assurance habitation"},
                  {"id": 6, "name": "Charges copropriété"}]},
        {"id": 3, "name": "Transports",         "type": "expense", "color": "#d97706",
         "subs": [{"id": 1, "name": "Carburant"},
                  {"id": 2, "name": "Transports en commun"},
                  {"id": 3, "name": "Taxi / VTC"},
                  {"id": 4, "name": "Entretien véhicule"},
                  {"id": 5, "name": "Assurance auto"},
                  {"id": 6, "name": "Péage / Parking"}]},
        {"id": 4, "name": "Santé",              "type": "expense", "color": "#dc2626",
         "subs": [{"id": 1, "name": "Médecin"},
                  {"id": 2, "name": "Pharmacie"},
                  {"id": 3, "name": "Mutuelle"},
                  {"id": 4, "name": "Dentiste / Optique"}]},
        {"id": 5, "name": "Loisirs",            "type": "expense", "color": "#7c3aed",
         "subs": [{"id": 1, "name": "Sorties"},
                  {"id": 2, "name": "Sport"},
                  {"id": 3, "name": "Vacances"},
                  {"id": 4, "name": "Culture"}]},
        {"id": 6, "name": "Abonnements",        "type": "expense", "color": "#0891b2",
         "subs": [{"id": 1, "name": "Streaming"},
                  {"id": 2, "name": "Téléphone"},
                  {"id": 3, "name": "Cloud / Logiciels"},
                  {"id": 4, "name": "Salle de sport"}]},
        {"id": 7, "name": "Shopping",           "type": "expense", "color": "#db2777",
         "subs": [{"id": 1, "name": "Vêtements"},
                  {"id": 2, "name": "Électronique"},
                  {"id": 3, "name": "Maison / Déco"}]},
        {"id": 8, "name": "Frais bancaires",    "type": "expense", "color": "#71717a",
         "subs": [{"id": 1, "name": "Frais de tenue de compte"},
                  {"id": 2, "name": "Agios / Découvert"},
                  {"id": 3, "name": "Carte bancaire"}]},
        {"id": 9, "name": "Cadeaux & dons",     "type": "expense", "color": "#f59e0b",
         "subs": [{"id": 1, "name": "Cadeaux"},
                  {"id": 2, "name": "Dons / Associations"}]},
        {"id": 10, "name": "Autres dépenses",   "type": "expense", "color": "#a1a1aa",
         "subs": [{"id": 1, "name": "Divers"}]},
        # ── Revenus ──
        {"id": 11, "name": "Salaire",           "type": "income",  "color": "#16a34a",
         "subs": [{"id": 1, "name": "Salaire net"},
                  {"id": 2, "name": "Heures supplémentaires"}]},
        {"id": 12, "name": "Primes",            "type": "income",  "color": "#22c55e",
         "subs": [{"id": 1, "name": "Prime annuelle"},
                  {"id": 2, "name": "Participation"},
                  {"id": 3, "name": "Intéressement"}]},
        {"id": 13, "name": "Remboursements",    "type": "income",  "color": "#0d9488",
         "subs": [{"id": 1, "name": "Sécurité sociale"},
                  {"id": 2, "name": "Mutuelle"},
                  {"id": 3, "name": "Frais professionnels"}]},
        {"id": 14, "name": "Cadeaux reçus",     "type": "income",  "color": "#a3e635",
         "subs": [{"id": 1, "name": "Cadeaux"}]},
        {"id": 15, "name": "Autres revenus",    "type": "income",  "color": "#84cc16",
         "subs": [{"id": 1, "name": "Divers"}]},
    ]


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
            return merged
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
