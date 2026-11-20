"""Trace de vol : une ligne toutes les 5 secondes, et tout de suite quand quelque chose
d'important change (master arm, mode, pilote auto, leurres, emport, sol/vol), plus
chaque action demandee (tablette, Stream Deck). Elle part dans le diagnostic et permet
de reconstituer ce qui s'est passe au lieu de le deviner.
"""
import json
import math
import os
import threading
import time

TAILLE_MAX = 3_000_000


class Trace:
    def __init__(self, dossier):
        self.dossier = dossier
        self._verrou = threading.Lock()
        self._dernier = 0.0
        self._cle = None

    def _fichier(self):
        return os.path.join(self.dossier, f"trace_{time.strftime('%Y%m%d')}.jsonl")

    def _ecrire(self, donnees):
        try:
            os.makedirs(self.dossier, exist_ok=True)
            chemin = self._fichier()
            if os.path.isfile(chemin) and os.path.getsize(chemin) > TAILLE_MAX:
                return
            with self._verrou, open(chemin, "a", encoding="utf-8") as f:
                f.write(json.dumps({"h": time.strftime("%H:%M:%S"), **donnees},
                                   ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass          # la trace ne doit jamais gener le vol

    def action(self, source, quoi, **details):
        """Une action demandee par le pilote : d'ou elle vient et ce qu'elle demande."""
        self._ecrire({"k": "action", "de": source, "quoi": quoi, **details})

    def tick(self, app):
        b, a, x = app.b, app.a, app.export
        if not b.en_f18:
            return
        maintenant = time.time()

        def lu(nom):
            try:
                return b.lire(nom)
            except Exception:
                return None
        vivant = x is not None and x.vivant
        emport = {}
        if vivant:
            try:
                emport = {st: n for st, (nom, n) in x.stations().items() if n}
            except Exception:
                emport = {}
        discret = {
            "sol": bool(a.au_sol), "arm": bool(a.arme),
            "aa": bool(a.allume("MASTER_MODE_AA_LT")), "ag": bool(a.allume("MASTER_MODE_AG_LT")),
            "disp": lu("CMSD_DISPENSE_SW"), "manette": lu("THROTTLE_DISP_SW"), "ecm": lu("ECM_MODE_SW"),
            "leurres": list(x.leurres) if vivant and x.leurres else None,
            "emport": emport, "proc": app.ex.en_cours,
            "ap": "".join(str(lu(f"UFC_OPTION_CUEING_{i}") or " ") for i in range(1, 6)),
            "alarmes": sorted(x.alarmes) if vivant else [],
            "sam": bool(a.allume("RH_ADV_SAM")), "cw": bool(a.allume("RH_ADV_CW")),
            "ai": bool(a.allume("RH_ADV_AI")),
        }
        cle = json.dumps(discret, sort_keys=True, default=str)
        if cle == self._cle and maintenant - self._dernier < 5:
            return
        self._cle, self._dernier = cle, maintenant
        def valeur(nom):
            v = getattr(a, nom, None)
            try:
                return v() if callable(v) else v
            except Exception:
                return None
        ligne = {"k": "etat", **discret, "alt": valeur("altitude"), "vit": valeur("vitesse"),
                 "carbu": valeur("carburant")}
        if vivant:
            pos = x.position or {}
            for nom, cle_pos in (("cap", "cap"), ("tang", "tang"), ("incl", "incl")):
                v = pos.get(cle_pos)
                if isinstance(v, (int, float)):
                    ligne[nom] = round(math.degrees(v), 1)
            ligne["vol"] = {k: round(v, 2) for k, v in (x.vol or {}).items() if isinstance(v, (int, float))}
            if x.emetteurs:
                ligne["emetteurs"] = x.emetteurs
            ligne["t"] = x.temps_modele
        self._ecrire(ligne)
