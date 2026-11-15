"""Etape JDAM : bombes GPS (GBU-38 / 32 / 31, J-82 / J-83 / J-84 sur le STORES).

D'apres tes captures du 15 novembre (marques 1 a 4) et le guide DCS du Hornet :
- les boutons des ecrans sont numerotes a partir du bas a gauche (PB1), dans le
  sens des aiguilles d'une montre ; MENU = PB18 ;
- page STORES (DDI gauche) : le type de bombe est en haut (J-82...), MODE PP/TOO
  = PB5, fusee EFUZ = PB4 (puis INST = PB3), JDAM DSPLY = PB11 ;
- page JDAM DSPLY : MSN = PB4 ; page MSN : PP1 a PP6 = PB6 a PB11,
  TGT UFC = PB14, STEP = PB13, retour = PB19 ;
- HSI : WPDSG (designer le waypoint comme cible) = PB14, le WYPT devient TGT.

Deux facons de viser :
- TOO sur un waypoint (ce que tu as fait a la main) : fiable ;
- PP (cible programmee dans la bombe) : a l'essai, tout est note en boite noire.
Rien n'est largue par le copilote : la detente reste a toi.
"""

import re

from .exportdcs import elements
from .navigation import (Echec, _aller_numero, _appuyer, _guidage_wpt, _hsi, bouton_appris,
                         entrer, lire_hsi, option_ufc, taper)

DDI_G = 2
JDAM_TYPES = ("J-82", "J-83", "J-84")


# ----------------------------------------------------------------- lecture
def lire_ddi(export, ecran=DDI_G):
    if export is None or not export.vivant:
        return None
    txt = export.ecrans.get(ecran) or ""
    el = elements(txt)
    noms = {n for n, _v in el}

    def val(nom):
        for n, v in el:
            if n == nom:
                return v
        return None

    def present(libelle):
        return any(n.startswith(libelle + "_") for n in noms)

    def encadre(libelle):
        return any(n.startswith(libelle) and "_box" in n for n in noms)

    jdam_type = None
    for n, v in el:
        if v.replace("\n", "") in JDAM_TYPES and "__id" in n:
            jdam_type = v.replace("\n", "")
            break
    return {
        "ecran": ecran, "texte": txt, "elements": el,
        "menu_tac": present("STORES") and present("RDR"),
        "stores": "Master_Arm_Status" in txt,
        "jdam": "ALGN_QUAL" in txt,
        "jdam_type": jdam_type,
        "mode": "TOO" if present("TOO") else ("PP" if present("PP") else None),
        "fusee": (val("JDAM_EFUZ_Val") or "").strip(),
        "alignement": (val("ALGN_QUAL_Val") or "").strip(),
        "msn": present("MSN") or any(re.match(r"PP[1-6]_", n) for n in noms),
        "pp_page": any(re.match(r"PP[1-6]_", n) for n in noms),
        "pp_encadre": [int(m.group(1)) for n in noms
                       for m in [re.match(r"PP([1-6])_\d_box", n)] if m],
    }


def _ddi(r, ecran=DDI_G):
    d = lire_ddi(r.export, ecran)
    if d is None:
        raise Echec("Écrans illisibles : liaison DCS absente.")
    return d


def _pb(ecran):
    return {2: "LEFT_DDI_PB_", 3: "RIGHT_DDI_PB_", 4: "AMPCD_PB_"}[ecran]


def bouton_ddi(r, cle, candidats, condition, ecran=DDI_G, delai=2.0):
    """Comme bouton_appris (HSI), pour un DDI. Le numero qui marche est retenu."""
    from .chemins import sauver_config
    connus = r.cfg.setdefault("boutons_ddi", {})
    essais = ([connus[cle]] if cle in connus else []) + [c for c in candidats if c != connus.get(cle)]
    for pb, duree in [(p, 0.2) for p in essais] + [(p, 0.5) for p in essais[:1]]:
        avant = _ddi(r, ecran)
        _appuyer(r, f"{_pb(ecran)}{pb:02d}", duree)
        fin = r.horloge() + delai
        while r.horloge() < fin:
            apres = lire_ddi(r.export, ecran)
            if apres is not None and condition(avant, apres):
                if connus.get(cle) != pb:
                    connus[cle] = pb
                    try:
                        sauver_config(r.cfg)
                    except OSError:
                        pass
                return apres
            r.attendre(0.25)
        if getattr(r, "boite", None) is not None:
            apres = lire_ddi(r.export, ecran) or avant
            r.boite.ecrire("bouton_ddi_sans_effet", cle=cle, bouton=f"{_pb(ecran)}{pb:02d}",
                           texte=apres["texte"][:20000])
    if cle in connus:
        del connus[cle]
    raise Echec("Bouton " + cle.replace("_", " ") + " sans effet.")


# ------------------------------------------------------------ preparation
def _mode_air_sol(r):
    if not r.a.allume("MASTER_MODE_AG_LT"):
        _appuyer(r, "MASTER_MODE_AG", 0.3)
        r.attendre(0.8)
    if not r.a.allume("MASTER_MODE_AG_LT"):
        raise Echec("Mode air-sol refusé.")


def _page_stores(r):
    d = _ddi(r)
    if d["stores"]:
        return d
    if not d["menu_tac"]:
        bouton_ddi(r, "menu", (18,), lambda a, b: b["menu_tac"] or b["stores"])
        d = _ddi(r)
        if not d["menu_tac"] and not d["stores"]:          # menu SUPT : un appui de plus
            bouton_ddi(r, "menu", (18,), lambda a, b: b["menu_tac"] or b["stores"])
    d = _ddi(r)
    if d["stores"]:
        return d
    return bouton_ddi(r, "stores", (5,), lambda a, b: b["stores"])


def _choisir_jdam(r):
    d = _page_stores(r)
    if d["jdam"]:
        return d
    if d["jdam_type"] is None and not any(t in d["texte"] for t in JDAM_TYPES):
        raise Echec("Pas de JDAM à bord.")
    return bouton_ddi(r, "jdam_type", (6, 7, 8, 9, 10), lambda a, b: b["jdam"])


def _mode(r, voulu):
    d = _ddi(r)
    if d["mode"] == voulu:
        return d
    return bouton_ddi(r, "jdam_mode", (5,), lambda a, b: b["mode"] == voulu)


def _fusee_inst(r):
    d = _ddi(r)
    if d["fusee"].upper().startswith("INST"):
        return
    try:
        bouton_ddi(r, "jdam_efuz", (4,), lambda a, b: a["texte"] != b["texte"])
        bouton_ddi(r, "jdam_efuz_inst", (3,), lambda a, b: b["fusee"].upper().startswith("INST")
                   or "INST" in b["texte"] and a["texte"] != b["texte"])
    except Echec:
        r.non_confirmes.append("fusée INST")


def _preparer(r, mode):
    _mode_air_sol(r)
    d = _choisir_jdam(r)
    _mode(r, mode)
    _fusee_inst(r)
    return _ddi(r) or d


# -------------------------------------------------------------------- TOO
def _designer_waypoint(r):
    """WPDSG sur la HSI : le waypoint devient la cible (WYPT -> TGT)."""
    info = _hsi(r)

    def tgt(texte):
        for n, v in elements(texte):
            if n.startswith("WYPT_1__id") and v.replace("\n", "") == "TGT":
                return True
        return False
    if tgt(info["texte"]):
        return
    bouton_appris(r, "wpdsg", (14,), lambda a, b: tgt(b["texte"]))


def jdam_too(r):
    """JDAM en TOO sur le waypoint du plan choisi (ou le waypoint actuel)."""
    if r.a.au_sol:
        raise Echec("Négatif. JDAM en vol uniquement.")
    cible = getattr(r.nav, "cible", None)
    if cible is not None:
        p = r.nav.par_numero(cible)
        if p is not None and not p.sync:
            from .navigation import envoyer_plan
            envoyer_plan(r)
        _aller_numero(r, cible, False)
        r.nav.cible = None
    _guidage_wpt(r)
    numero = _hsi(r)["wypt"]
    _designer_waypoint(r)
    d = _preparer(r, "TOO")
    info = lire_hsi(r.export)
    texte = f"JDAM prête, mode TOO sur le waypoint {numero}. Fusée {d['fusee'] or 'à vérifier'}."
    if info and info["cap"] is not None and info["dist"] is not None:
        texte += f" Cible au {info['cap']:03d}, {info['dist']:.0f} nautiques."
    texte += " Master arm et largage à toi."
    if getattr(r, "boite", None) is not None:
        r.boite.ecrire("jdam_too", waypoint=numero, stores=d["texte"][:20000])
    r.dire(texte)


# --------------------------------------------------------------------- PP
def _dms(valeur, est_lat):
    """Degres -> (touche hemisphere, 'DDMMSS' / 'DDDMMSS', centiemes de seconde)."""
    touche = ("2" if valeur >= 0 else "8") if est_lat else ("6" if valeur >= 0 else "4")
    v = abs(valeur)
    total = round(v * 360000)           # en centiemes de seconde
    d, reste = divmod(total, 360000)
    m, reste = divmod(reste, 6000)
    s, c = divmod(reste, 100)
    return touche, f"{d:02d}{m:02d}{s:02d}", f"{c:02d}"


def jdam_pp(r):
    """Programme la cible PP n (le point choisi dans le plan) dans les JDAM."""
    p = r.nav.point
    if p is None:
        raise Echec("Choisis une cible dans le plan de vol.")
    n_pp = max(1, min(6, int(getattr(r.nav, "pp", 1) or 1)))
    _preparer(r, "PP")
    # JDAM DSPLY puis MSN
    d = _ddi(r)
    if not d["msn"]:
        bouton_ddi(r, "jdam_dsply", (11,), lambda a, b: b["msn"] or b["texte"] != a["texte"])
        d = _ddi(r)
    if not d["pp_page"]:
        bouton_ddi(r, "jdam_msn", (4,), lambda a, b: b["pp_page"])
    stations = [st for st, (nom, n) in (r.export.stations() or {}).items()
                if n and "GBU-3" in nom]
    for k in range(max(1, len(stations))):
        if n_pp not in _ddi(r)["pp_encadre"]:
            bouton_ddi(r, f"pp{n_pp}", (5 + n_pp,), lambda a, b: n_pp in b["pp_encadre"]
                       or a["texte"] != b["texte"])
        _appuyer(r, f"{_pb(DDI_G)}14")                 # TGT UFC
        r.attendre(0.6)
        if not option_ufc(r, "POSN"):
            raise Echec("TGT UFC : option POSN absente.")
        for valeur, est_lat, lib in ((p.lat, True, "LAT"), (p.lon, False, "LON")):
            option_ufc(r, lib, attendu=False)
            touche, tete, cent = _dms(valeur, est_lat)
            taper(r, touche)
            taper(r, tete)
            entrer(r)
            taper(r, cent)
            entrer(r)
        _appuyer(r, "UFC_CLR")
        if p.alt_m is not None:
            _appuyer(r, f"{_pb(DDI_G)}14")
            r.attendre(0.6)
            if option_ufc(r, "ELEV", attendu=False) and option_ufc(r, "FEET", attendu=False):
                taper(r, str(max(1, int(round(p.alt_m * 3.28084)))))
                entrer(r)
            _appuyer(r, "UFC_CLR")
        _appuyer(r, "UFC_CLR")
        if getattr(r, "boite", None) is not None:
            r.boite.ecrire("jdam_pp", pp=n_pp, station_index=k, point=p.dict(),
                           msn=_ddi(r)["texte"][:20000])
        if k < len(stations) - 1:
            _appuyer(r, f"{_pb(DDI_G)}13")             # STEP : bombe suivante
            r.attendre(0.8)
    _appuyer(r, f"{_pb(DDI_G)}19")                     # retour
    r.non_confirmes.append(f"coordonnées PP{n_pp} (à vérifier sur la page MSN)")
    r.dire(f"PP{n_pp} programmé sur {p.nom}. Vérifie la page MSN. Largage à toi.")


def _proc(fonction, quoi):
    from .procedures import Appelle

    def garde(r):
        try:
            fonction(r)
        except Echec as ex:
            r.dire(str(ex))
            if getattr(r, "boite", None) is not None:
                r.boite.ecrire("jdam_echec", action=quoi, raison=str(ex),
                               ddi=(lire_ddi(r.export) or {}).get("texte", "")[:20000])
    return [Appelle(garde, quoi)]


PROCEDURES_ARMES = {
    "jdam_too": ("JDAM sur waypoint", _proc(jdam_too, "JDAM TOO")),
    "jdam_pp": ("JDAM programmée", _proc(jdam_pp, "JDAM PP")),
}
