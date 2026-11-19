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
                         entrer, lire_hsi, option_ufc, options_ufc, taper)

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
        "jdam": "ALGN_QUAL" in txt and "Master_Arm_Status" in txt,
        "jdam_type": jdam_type,
        "mode": "TOO" if present("TOO") else ("PP" if present("PP") else None),
        "fusee": (val("JDAM_EFUZ_Val") or "").strip(),
        "alignement": (val("ALGN_QUAL_Val") or "").strip(),
        "dsply": "Miss_Type" in txt and "MISSION_Lbl" not in txt,
        "msn_option": present("MSN"),
        "msn_page": "MISSION_Lbl" in txt,
        "mission": (val("MISSION_Type") or val("Miss_Type") or "").strip(),
        "station": int((val("CurrStation_JDAM") or "0").strip() or 0),
        "tgt_lat": _dms_lu(val("LAT_N_S"), val("LAT_Val")),
        "tgt_lon": _dms_lu(val("LONG_W_E"), val("LONG_Val")),
    }


def _dms_lu(h, texte):
    """ "N", "31° 30' 32.63\"" -> 31.509063 """
    if not texte:
        return None
    m = re.match(r"\s*(\d+)\s*°\s*(\d+)\s*'\s*([\d.]+)", texte)
    if not m:
        return None
    v = int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3)) / 3600
    return -v if (h or "").strip() in ("S", "W") else v


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
    if not r.a.allume("MASTER_MODE_AG_LT") and not r.a.au_sol:
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
    # chaque station JDAM en TOO (le mode est propre a chaque station)
    stations = sorted(stations_jdam(r.export), key=lambda s: ORDRE_LARGAGE.index(s)
                      if s in ORDRE_LARGAGE else 9)
    relu = None
    try:
        _page_msn(r)
        for st in stations or [None]:
            if st is not None:
                _station_msn(r, st)
            m = _mode_station(r, "TOO")
            relu = relu or (m["tgt_lat"], m["tgt_lon"])
        _station_msn(r, stations[0]) if stations else None
        bouton_ddi(r, "msn_retour", (19,), lambda a, b: not b["msn_page"])
    except Echec as ex:
        r.non_confirmes.append("TOO sur chaque station (" + str(ex) + ")")
    d = _ddi(r) if _ddi(r)["jdam"] else d
    info = lire_hsi(r.export)
    texte = f"JDAM prête, mode TOO sur le waypoint {numero}. Fusée {d['fusee'] or 'à vérifier'}."
    if info and info["cap"] is not None and info["dist"] is not None:
        texte += f" Cible au {info['cap']:03d}, {info['dist']:.0f} nautiques."
    texte += " Master arm et largage à toi."
    if getattr(r, "boite", None) is not None:
        r.boite.ecrire("jdam_too", waypoint=numero, cible_lue=relu, stations=stations,
                       stores=d["texte"][:20000])
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


ORDRE_LARGAGE = (8, 2, 7, 3)        # ordre de largage des JDAM dans le Hornet


def stations_jdam(export):
    """{station: nom de la bombe} pour les JDAM a bord (emport reel)."""
    out = {}
    for st, (nom, n) in (export.stations() if export is not None else {}).items():
        if n and "GBU-3" in nom:
            out[st] = nom
    return out


def _page_msn(r):
    """STORES -> JDAM DSPLY (PB11) -> MSN (PB4). L'option MSN n'apparait qu'une fois
    la bombe sous tension depuis un moment (jusqu'a 1 min 30 constate le 19 nov.) :
    on n'appuie que lorsqu'elle est affichee, et on rouvre la page pour la rafraichir."""
    d = _ddi(r)
    if d["msn_page"]:
        return d
    fin = r.horloge() + 150
    annonce = False
    tour = 0
    while r.horloge() < fin:
        d = _ddi(r)
        if d["msn_page"]:
            return d
        if not d["dsply"]:
            if not d["stores"]:
                _page_stores(r)
            bouton_ddi(r, "jdam_dsply", (11,), lambda a, b: b["dsply"] or b["msn_page"])
            d = _ddi(r)
        if d["msn_option"]:
            try:
                return bouton_ddi(r, "jdam_msn", (4,), lambda a, b: b["msn_page"], delai=2.0)
            except Echec:
                pass
        if not annonce:
            r.dire("Bombe en mise en route. J'attends l'option mission, une minute environ.")
            annonce = True
        r.attendre(5)
        tour += 1
        if tour % 3 == 0 and not _ddi(r)["msn_option"]:
            try:                                        # rouvre la page : MENU, STORES, DSPLY
                bouton_ddi(r, "menu", (18,), lambda a, b: not b["dsply"], delai=1.5)
            except Echec:
                pass
    raise Echec("Option MSN absente après 2 min 30. Vérifie que la bombe est choisie (J-82 encadré).")


def _station_msn(r, station):
    for _ in range(6):
        d = _ddi(r)
        if d["station"] == station:
            return d
        bouton_ddi(r, "msn_step", (13,), lambda a, b: b["station"] != a["station"])
    raise Echec(f"Station {station} introuvable avec STEP.")


def _mode_station(r, voulu):
    """Sur la page MSN : le mode PP / TOO est propre a chaque station (fiche
    kneeboard JDAM). MODE = PB5. En TOO, les PP ne s'affichent pas du tout."""
    d = _ddi(r)
    if d["mission"].startswith(voulu):
        return d
    return bouton_ddi(r, "msn_mode", (5,), lambda a, b: b["mission"].startswith(voulu))


def _etat_ufc(r):
    b = r.b
    return {"options": options_ufc(b),
            "bloc": [str(b.lire(n)) for n in ("UFC_SCRATCHPAD_STRING_1_DISPLAY",
                                              "UFC_SCRATCHPAD_STRING_2_DISPLAY",
                                              "UFC_SCRATCHPAD_NUMBER_DISPLAY")]}


def _saisir_coord(r, p, lent, trace):
    """UFC TGT -> POSN -> LAT puis LON, en degres minutes secondes."""
    pause = 0.9 if lent else 0.5
    _appuyer(r, f"{_pb(DDI_G)}14")                     # UFC TGT
    r.attendre(pause)
    trace.append({"etape": "tgt_ufc", **_etat_ufc(r)})
    if not option_ufc(r, "POSN"):
        raise Echec("UFC TGT : option POSN absente.")
    r.attendre(pause)
    for valeur, est_lat, lib in ((p.lat, True, "LAT"), (p.lon, False, "LON")):
        trouve = option_ufc(r, lib, attendu=False)
        r.attendre(pause)
        touche, tete, cent = _dms(valeur, est_lat)
        if lent and not est_lat and len(tete) == 6:
            tete = "0" + tete                           # 2e essai : longitude sur 3 chiffres
        taper(r, touche)
        if lent:
            r.attendre(0.3)
        taper(r, tete)
        trace.append({"etape": lib + "_tape", "option": trouve, "saisie": touche + tete, **_etat_ufc(r)})
        entrer(r)
        r.attendre(pause)
        taper(r, cent)
        trace.append({"etape": lib + "_centiemes", "saisie": cent, **_etat_ufc(r)})
        entrer(r)
        r.attendre(pause)
        d = _ddi(r)
        trace.append({"etape": lib + "_relu", "lat": d["tgt_lat"], "lon": d["tgt_lon"]})
    _appuyer(r, "UFC_CLR")
    r.attendre(0.5)


def _cible_ok(r, p):
    d = _ddi(r)
    return (d["tgt_lat"] is not None and d["tgt_lon"] is not None
            and abs(d["tgt_lat"] - p.lat) < 0.0003 and abs(d["tgt_lon"] - p.lon) < 0.0003)


def _entrer_cible(r, p):
    _mode_station(r, "PP")
    if "PP1" not in _ddi(r)["mission"]:
        bouton_ddi(r, "pp1", (6,), lambda a, b: "PP1" in b["mission"])
    trace = []
    ok = False
    for lent in (False, True):                          # 2e essai plus lent si la relecture est fausse
        _saisir_coord(r, p, lent, trace)
        ok = _cible_ok(r, p)
        if ok:
            break
        _appuyer(r, "UFC_CLR")
        _appuyer(r, "UFC_CLR")
        r.attendre(0.8)
    if ok and p.alt_m is not None:
        _appuyer(r, f"{_pb(DDI_G)}14")
        r.attendre(0.6)
        if option_ufc(r, "ELEV", attendu=False):
            r.attendre(0.5)
            if option_ufc(r, "FEET", attendu=False):
                r.attendre(0.5)
                taper(r, str(max(1, int(round(p.alt_m * 3.28084)))))
                entrer(r)
        _appuyer(r, "UFC_CLR")
    _appuyer(r, "UFC_CLR")
    r.attendre(0.8)
    d = _ddi(r)
    if getattr(r, "boite", None) is not None:
        r.boite.ecrire("jdam_cible", station=d["station"], point=p.dict(),
                       relu=(d["tgt_lat"], d["tgt_lon"]), ok=ok, trace=trace, msn=d["texte"][:20000])
    return ok


def jdam_programmer(r):
    """Programme chaque station JDAM sur son waypoint (fenetre : station -> waypoint)."""
    plan = dict(getattr(r.nav, "jdam", {}) or {})
    if not plan:
        raise Echec("Choisis un waypoint pour au moins une station.")
    a_bord = stations_jdam(r.export)
    plan = {st: n for st, n in plan.items() if n is not None and (not a_bord or st in a_bord)}
    if not plan:
        raise Echec("Aucune de ces stations n'a de JDAM.")
    for st, num in plan.items():
        p = r.nav.par_numero(num)
        if p is None:
            raise Echec(f"Waypoint {num} absent du plan.")
    _preparer(r, "PP")
    _page_msn(r)
    faits, rates = [], []
    for st in sorted(plan, key=lambda s: ORDRE_LARGAGE.index(s) if s in ORDRE_LARGAGE else 9):
        p = r.nav.par_numero(plan[st])
        _station_msn(r, st)
        (faits if _entrer_cible(r, p) else rates).append(st)
    bouton_ddi(r, "msn_retour", (19,), lambda a, b: not b["msn_page"])
    if rates:
        r.non_confirmes.append("stations " + ", ".join(map(str, rates)))
    textes = [f"station {st} sur {r.nav.par_numero(plan[st]).nom}" for st in faits]
    r.dire("JDAM programmées : " + ", ".join(textes) + ". Largage dans l'ordre 8, 2, 7, 3. "
           "Master arm et largage à toi." if textes else "Programmation JDAM non confirmée.")


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
    "jdam_programmer": ("Programmation JDAM", _proc(jdam_programmer, "JDAM stations")),
}
