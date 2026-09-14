"""
pret.py — Stockage du module "Pret etudiant".

Reprend le modele de l'ancienne application standalone Pret_Etudiant.exe
(localStorage cle "pret_v1", schema 6), mais persiste sur disque comme le
reste de Suivi PEA. Le fichier est COMMUN a tous les profils PEA.

Emplacement : <app_dir>/pret.json
Backup quotidien : <app_dir>/backups_pret/pret_YYYY-MM-DD.json

Modele
------
pea.achats  : {id, date, ticker, montant, quantite, cours_achat}
pea.ventes  : {id, date, ticker, quantite, cours_vente, montant} (montant = credite)
av.contrats : [{id, label, taux_annuels:[{annee,taux}], depots:[{id,date,montant,note}]}]
              -> plusieurs contrats possibles, chacun avec ses propres taux
liv         : {label, taux_history:[{id,date,taux}], mouvements:[{id,date,type,montant,note}]}
frais_recurrents : {id, label, montant, date_debut, frequence, nb_occurrences}
              -> preleve le meme jour de chaque mois (jour pris sur date_debut)
"""
from __future__ import annotations

import datetime

import jsonstore


SCHEMA = 6   # aligne sur l'ancienne app standalone


def default_data() -> dict:
    return {
        "_meta": {
            "version": 1,
            "schema": "pret.v1",
            "createdAt":   datetime.date.today().isoformat(),
            "lastSavedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        },
        "schema": SCHEMA,
        "config_locked": False,
        "pret": {
            "montant": 0,
            "date_deblocage": "",
            "date_premier_remboursement": "",
            "duree_remboursement": 0,
            "mensualite": 0,
        },
        "pea": {"ticker": "", "achats": [], "ventes": []},
        "av":  {"contrats": []},
        "liv": {"label": "Livret A", "taux_history": [], "mouvements": []},
        "versements":      [],
        "remboursements":  [],
        "frais":           [],
        "frais_recurrents": [],
    }


_store = jsonstore.JsonStore(
    filename="pret.json",
    backup_dirname="backups_pret",
    schema="pret.v1",
    default_factory=default_data,
)


def get_pret_path():
    return _store.path()


def load_data() -> dict:
    data = _store.load()
    # Les sous-objets doivent toujours exister avec leurs cles (merge peu profond
    # du JsonStore : une cle "pea" sauvegardee ecrase entierement le defaut).
    defaults = default_data()
    for key in ("pret", "pea", "av", "liv"):
        base = dict(defaults[key])
        base.update(data.get(key) or {})
        data[key] = base
    for key in ("versements", "remboursements", "frais", "frais_recurrents"):
        if not isinstance(data.get(key), list):
            data[key] = []
    for key in ("achats", "ventes"):
        if not isinstance(data["pea"].get(key), list):
            data["pea"][key] = []
    _migrate_av(data)
    if not isinstance(data["liv"].get("taux_history"), list):
        data["liv"]["taux_history"] = []
    if not isinstance(data["liv"].get("mouvements"), list):
        data["liv"]["mouvements"] = []
    return data


def _migrate_av(data: dict) -> None:
    """Ancien modele (un seul contrat a plat) -> liste de contrats."""
    av = data["av"]
    if not isinstance(av.get("contrats"), list):
        av["contrats"] = []
    legacy_depots = av.pop("depots", None)
    legacy_taux   = av.pop("taux_annuels", None)
    legacy_label  = av.pop("label", None)
    if (legacy_depots or legacy_taux) and not av["contrats"]:
        av["contrats"].append({
            "id":    "av1",
            "label": legacy_label or "Assurance Vie Fonds Euros",
            "taux_annuels": legacy_taux or [],
            "depots":       legacy_depots or [],
        })
    for c in av["contrats"]:
        if not isinstance(c.get("taux_annuels"), list):
            c["taux_annuels"] = []
        if not isinstance(c.get("depots"), list):
            c["depots"] = []
        c.setdefault("label", "Assurance vie")


def save_data(data: dict) -> None:
    data = dict(data or {})
    # Ces deux cles n'ont de sens que dans l'ancienne app localStorage.
    data.pop("undo_stack", None)
    data.pop("cours_cache", None)
    _store.save(data)
