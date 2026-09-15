"""
sports.py — Stockage du module "Sports" (agenda d'entrainement).

Comme finances.json, sports.json appartient a l'utilisateur actif.

Emplacement : <app_dir>/users/<slug>/sports.json
Backup quotidien : <app_dir>/users/<slug>/backups_sports/sports_YYYY-MM-DD.json

Modele de donnees
─────────────────
sessions : une seance = un jour + un sport + les champs propres a ce sport
  {id, date:"YYYY-MM-DD", time:"HH:MM", sport:"course", note:"",
   duration: minutes, distance: km (metres pour la natation), elevation: m D+,
   subtype/lieu/kind/groups/routineId selon le sport}

customSports : sports ajoutes par l'utilisateur
  {id, label, icon, color, fields: [...]}  -- fields pioches dans FIELD_CATALOG

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
    {"id": "rando",    "label": "Randonnée",                   "icon": "🥾", "color": "#65a30d",
     "fields": ["distance_km", "duration", "elevation", "subtype"]},
    {"id": "autre",    "label": "Autre",                      "icon": "🥋", "color": "#71717a",
     "fields": ["duration"]},
]

# Types de seance modifiables par l'utilisateur
DEFAULT_SUBTYPES = {
    "course": ["Footing", "Fractionné", "Sortie longue", "Côtes", "Compétition"],
    "rando":  ["Balade", "Journée", "Trek", "Montagne", "Raquettes"],
}

# Champs disponibles quand l'utilisateur cree son propre sport : ce sont
# exactement ceux que l'UI sait deja afficher (voir spApplyFields()).
FIELD_CATALOG = [
    {"id": "duration",    "label": "Durée",                 "hint": "en minutes"},
    {"id": "distance_km", "label": "Distance (km)",         "hint": "décimales autorisées"},
    {"id": "distance_m",  "label": "Distance (m)",          "hint": "comme la natation"},
    {"id": "elevation",   "label": "Dénivelé +",            "hint": "en mètres"},
    {"id": "subtype",     "label": "Type de séance",        "hint": "liste que tu remplis toi-même"},
    {"id": "kind",        "label": "Entraînement / Match",   "hint": "comme le football"},
    {"id": "lieu",        "label": "Lieu",                  "hint": "eau libre / bassin 25 / bassin 50"},
    {"id": "routine",     "label": "Routine",               "hint": "circuit nommé réutilisable"},
    {"id": "groups",      "label": "Groupes musculaires",   "hint": "comme la musculation"},
]


def default_data() -> dict:
    return {
        "_meta": {
            "version": 1,
            "schema": "sports.v1",
            "createdAt":   datetime.date.today().isoformat(),
            "lastSavedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        },
        "sessions": [],
        "customSports": [],      # sports ajoutes par l'utilisateur (memes champs)
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

def load_data() -> dict:
    return _store.load()


def save_data(data: dict) -> None:
    _store.save(data)
