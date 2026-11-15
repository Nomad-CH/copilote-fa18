"""Commandes du cockpit que DCS-BIOS manoeuvre mal.

Pendant tes vols du 15 novembre, la poignee de frein de parking, les boutons de
selection des stations (largage selectif) et la manette des leurres n'ont pas
reagi comme prevu aux ordres DCS-BIOS. Le lien du copilote (version 3) sait
maintenant cliquer directement sur une commande, comme ta souris, et renvoie
sa position exacte.

Pour chaque commande, plusieurs facons de cliquer sont essayees dans l'ordre ;
celle qui marche est retenue dans tes reglages, les autres sont notees dans la
boite noire.
"""

import time

# appareil, commande, argument DCS (d'apres DCS-BIOS)
FREIN_APPAREIL, FREIN_TIRER, FREIN_URGENCE, FREIN_PARK = 5, 3005, 3007, 3006
ARG_FREIN_TIRE, ARG_FREIN_TOURNE = 240, 241

STATIONS = {   # bouton DCS-BIOS -> (appareil, commande, argument du voyant)
    "SJ_CTR": (23, 3005, 152), "SJ_LI": (23, 3006, 154), "SJ_LO": (23, 3007, 156),
    "SJ_RI": (23, 3008, 158), "SJ_RO": (23, 3009, 160),
}
ARG_RWR_VOYANT = 276


def frein_serre(x):
    """Poignee tiree ET tournee sur PARK (etat de ton avion au demarrage a froid)."""
    tire, tourne = x.arg(ARG_FREIN_TIRE), x.arg(ARG_FREIN_TOURNE)
    if tire is None or tourne is None:
        return None
    return tire > 0.5 and tourne > 0.66


FREIN_SERRER = [
    [(FREIN_PARK, 1, 0.4), (FREIN_PARK, 0, 0.4), (FREIN_TIRER, 1, 0.3), (FREIN_TIRER, 0, 0.6)],
    [(FREIN_PARK, 1, 0.5), (FREIN_TIRER, 1, 0.5), (FREIN_TIRER, 0, 0.5), (FREIN_PARK, 0, 0.4)],
    [(FREIN_PARK, 1, 0.5), (FREIN_TIRER, -1, 0.3), (FREIN_TIRER, 0, 0.6)],
]
FREIN_RELACHER = [
    [(FREIN_TIRER, 1, 0.3), (FREIN_TIRER, 0, 0.8)],
    [(FREIN_PARK, 1, 0.3), (FREIN_PARK, 0, 0.4), (FREIN_TIRER, 1, 0.3), (FREIN_TIRER, 0, 0.8)],
    [(FREIN_TIRER, -1, 0.3), (FREIN_TIRER, 0, 0.8)],
]


def _etat_args(x, numeros):
    return {n: x.arg(n) for n in numeros}


def recettes(x, cfg, boite, nom, liste, appareil, reussi, attente=2.5, numeros=()):
    """Essaie les facons de cliquer de `liste` (la retenue d'abord) jusqu'a ce que
    `reussi()` soit vrai. Retient celle qui marche. -> True / False"""
    from .chemins import sauver_config
    retenues = cfg.setdefault("clics_retenus", {})
    ordre = list(range(len(liste)))
    if nom in retenues and retenues[nom] in ordre:
        ordre.remove(retenues[nom])
        ordre.insert(0, retenues[nom])
    trace = []
    for i in ordre:
        for commande, valeur, pause in liste[i]:
            x.clic(appareil, commande, valeur)
            time.sleep(pause)
        fin = time.time() + attente
        while time.time() < fin and not reussi():
            time.sleep(0.2)
        ok = bool(reussi())
        trace.append({"facon": i, "ok": ok, "args": _etat_args(x, numeros)})
        if ok:
            if retenues.get(nom) != i:
                retenues[nom] = i
                try:
                    sauver_config(cfg)
                except OSError:
                    pass
            if boite is not None:
                boite.ecrire("clic_cockpit", commande=nom, reussi=True, trace=trace)
            return True
    if boite is not None:
        boite.ecrire("clic_cockpit", commande=nom, reussi=False, trace=trace)
    return False


def manoeuvrer_frein(x, cfg, boite, serrer):
    """-> True (fait), False (echec), None (lien trop ancien pour cliquer)"""
    if x is None or not x.ordres_possibles:
        return None
    if frein_serre(x) == serrer:
        return True
    return recettes(x, cfg, boite, "frein_serrer" if serrer else "frein_relacher",
                    FREIN_SERRER if serrer else FREIN_RELACHER, FREIN_APPAREIL,
                    lambda: frein_serre(x) == serrer,
                    numeros=(ARG_FREIN_TIRE, ARG_FREIN_TOURNE))


def station_choisie(x, b, bouton):
    v = x.arg(STATIONS[bouton][2]) if x is not None else None
    if v is not None:
        return v > 0.5
    return bool(b.lire(bouton + "_LT"))


def basculer_station(x, cfg, boite, b, bouton):
    """Selectionne / deselectionne une station de largage, en verifiant le voyant."""
    appareil, commande, voyant = STATIONS[bouton]
    if x is None or not x.ordres_possibles:
        b.appuyer(bouton, 0.2)
        return None
    avant = station_choisie(x, b, bouton)
    facons = [[(commande, 1, 0.15), (commande, 0, 0.2)],
              [(commande, 1, 0.3)]]
    return recettes(x, cfg, boite, "station", facons, appareil,
                    lambda: station_choisie(x, b, bouton) != avant, attente=1.5,
                    numeros=(voyant,))


def rwr_allume(x, b):
    v = x.arg(ARG_RWR_VOYANT) if x is not None else None
    if v is not None:
        return v > 0.3
    return bool(b.lire("RWR_LOWER_LT"))
