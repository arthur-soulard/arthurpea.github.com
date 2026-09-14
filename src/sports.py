"""
sports.py — Stockage du module "Sports" (agenda d'entrainement).

Comme finances.json, sports.json est COMMUN a tous les profils PEA.

Emplacement : <app_dir>/sports.json
Backup quotidien : <app_dir>/backups_sports/sports_YYYY-MM-DD.json

Modele de donnees
─────────────────
sessions : une seance = un jour + un sport + les champs propres a ce sport
  {id, date:"YYYY-MM-DD", time:"HH:MM", sport:"course", note:"",
   duration: minutes, distance: km (metres pour la natation), elevation: m D+,
   subtype/lieu/kind/groups/routineId selon le sport}

routines : circuits nommes et reutilisables (abdos, gainage, renfo)
  {id, name, note}   -- un simple libelle, rattache a une seance de muscu

subtypes : types de seance editables, par sport
  {"course": ["Footing", "Fractionne", ...]}

goals : objectifs
  kind "perf"  -> performance ponctuelle, validee a la main
  kind "event" -> evenement date (compte a rebours + volume accumule)
  {id, kind, title, sport, target, date, status:"active|done|archived",
   createdAt, doneAt, note}
"""
from __future__ import annotations

import datetime

import jsonstore


# ─── Catalogue des sports ─────────────────────────────────────────────────────
# "fields" pilote le formulaire de saisie cote UI (voir sportsFieldsFor()).

SPORTS = [
    {"id": "course",   "label": "Course à pied / Trail", "icon": "🏃", "color": "#d97706",
     "fields": ["distance_km", "duration", "elevation", "subtype"]},
    {"id": "velo",     "label": "Vélo / Home trainer",   "icon": "🚴", "color": "#2563eb",
     "fields": ["distance_km", "duration", "elevation"]},
    {"id": "natation", "label": "Natation",                   "icon": "🏊", "color": "#0891b2",
     "fields": ["distance_m", "duration", "lieu"]},
    {"id": "muscu",    "label": "Musculation / Renfo",        "icon": "💪", "color": "#7c3aed",
     "fields": ["duration", "groups", "routine"]},
    {"id": "foot",     "label": "Football",                   "icon": "⚽",     "color": "#16a34a",
     "fields": ["duration", "kind"]},
    {"id": "autre",    "label": "Autre",                      "icon": "🥋", "color": "#71717a",
     "fields": ["duration"]},
]

# Types de seance modifiables par l'utilisateur (pour l'instant : course a pied)
DEFAULT_SUBTYPES = {
    "course": ["Footing", "Fractionné", "Sortie longue", "Côtes", "Compétition"],
}


def default_data() -> dict:
    return {
        "_meta": {
            "version": 1,
            "schema": "sports.v1",
            "createdAt":   datetime.date.today().isoformat(),
            "lastSavedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        },
        "sessions": [],
        "routines": [],          # circuits nommes, reutilisables (ex. "Circuit abdos")
        "goals":    [],
        "subtypes": {k: list(v) for k, v in DEFAULT_SUBTYPES.items()},
        "_nid":     {"session": 1, "routine": 1, "goal": 1},
    }


_store = jsonstore.JsonStore(
    filename="sports.json",
    backup_dirname="backups_sports",
    schema="sports.v1",
    default_factory=default_data,
)


def get_sports_path():
    return _store.path()


def load_data() -> dict:
    return _store.load()


def save_data(data: dict) -> None:
    _store.save(data)
