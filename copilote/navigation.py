"""Etape 2 de la playlist : la navigation.

- Carnet de points : pris sur la carte F10 (centre de l'ecran), a la position
  de l'avion, ou tapes dans la fenetre. Un point peut devenir un waypoint.
- Waypoints : precedent / suivant, retour base, annonces de passage.
- TACAN (canaux enregistres) et pilote automatique.

Tout passe par les vrais boutons du cockpit (AMPCD et UFC), avec verification
sur les ecrans. Les numeros de boutons qui marchent sont retenus (comme STD HDG),
et tout ce qui ne se passe pas comme prevu est note dans la boite noire.
"""

import json
import math
import os
import re

from .exportdcs import elements

AMPCD = "AMPCD_PB_"
NM = 1852.0
PIEDS = 3.28084

# Boutons de la page HSI, d'apres le texte de ton AMPCD (15 novembre) et la
# numerotation des ecrans du Hornet. Chaque liste est essayee dans l'ordre,
# verifiee, et le bon numero est retenu dans tes reglages.
BOUTONS_HSI = {
    "wpt_plus": (12, 13),
    "wpt_moins": (13, 12),
    "wypt": (11,),
    "tcn": (5, 4, 3),
    "data": (10,),
}
BOUTONS_DATA = {
    "precise": (19,),
    "wpt_plus": (12, 13),
    "wpt_moins": (13, 12),
}


class Echec(Exception):
    pass


# ----------------------------------------------------------------- points
class Point:
    def __init__(self, nom, lat, lon, alt_m=None, source=""):
        self.nom, self.lat, self.lon = nom, float(lat), float(lon)
        self.alt_m = None if alt_m is None else float(alt_m)
        self.source = source

    def dict(self):
        return {"nom": self.nom, "lat": self.lat, "lon": self.lon,
                "alt_m": self.alt_m, "source": self.source}

    def texte(self):
        return f"{ddm(self.lat, True)}  {ddm(self.lon, False)}"


def ddm(valeur, est_lat):
    h = ("N" if valeur >= 0 else "S") if est_lat else ("E" if valeur >= 0 else "W")
    v = abs(valeur)
    d = int(v)
    m = (v - d) * 60
    if round(m, 3) >= 60:
        d, m = d + 1, 0.0
    return f"{h} {d:0{2 if est_lat else 3}d}°{m:06.3f}'"


_NOMBRE = r"(\d+(?:[.,]\d+)?)"


def _une(texte, hemis):
    """'N 41°55'12.3"', 'N41 55.205', '41.92' ... -> degres decimaux ou None."""
    t = texte.strip().upper().replace(",", ".")
    signe = 1
    m = re.match(rf"^([{hemis}])\s*(.*)$", t) or re.match(rf"^(.*?)\s*([{hemis}])$", t)
    if m:
        lettre, reste = (m.group(1), m.group(2)) if m.group(1) in hemis else (m.group(2), m.group(1))
        if lettre in "SW":
            signe = -1
        t = reste
    if t.startswith("-"):
        signe, t = -signe, t[1:]
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums or len(nums) > 3:
        return None
    d = nums[0] + (nums[1] / 60 if len(nums) > 1 else 0) + (nums[2] / 3600 if len(nums) > 2 else 0)
    if len(nums) > 1 and (nums[1] >= 60 or (len(nums) > 2 and nums[2] >= 60)):
        return None
    return signe * d


def lire_coordonnees(texte):
    """Coordonnees tapees -> (lat, lon) en degres, ou None.
    Accepte : N 41°55'12" E 041°51'30"  /  N41 55.200 E041 51.500  /  41.92, 41.86"""
    t = texte.strip().upper().replace("’", "'").replace("″", '"').replace("′", "'")
    m = re.match(r"^\s*([NS].*?)\s+([EWO].*)$", t)
    if m:
        lat, lon = _une(m.group(1), "NS"), _une(m.group(2).replace("O", "W"), "EW")
    else:
        morceaux = re.split(r"[;,\s]+", t.replace(", ", ";"))
        morceaux = [x for x in morceaux if x]
        if len(morceaux) != 2:
            return None
        lat, lon = _une(morceaux[0], "NS"), _une(morceaux[1], "EW")
    if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
        return None
    return lat, lon


def saisie_ufc(valeur, est_lat):
    """Degres -> (touche hemisphere, 'DDMM' ou 'DDDMM', '4 decimales') pour
    la saisie PRECISE du Hornet (degres, minutes, puis decimales des minutes)."""
    touche = ("2" if valeur >= 0 else "8") if est_lat else ("6" if valeur >= 0 else "4")
    v = abs(valeur)
    d = int(v)
    minutes = round((v - d) * 60, 4)
    if minutes >= 60:
        d, minutes = d + 1, 0.0
    entier = int(minutes)
    dec = int(round((minutes - entier) * 10000))
    if dec >= 10000:
        entier, dec = entier + 1, 0
    tete = f"{d:02d}{entier:02d}"
    return touche, tete, f"{dec:04d}"


def distance_cap(lat1, lon1, lat2, lon2):
    """-> (distance en nautiques, cap vrai en degres)"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    d = 2 * r * math.asin(min(1.0, math.sqrt(a)))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return d / NM, (math.degrees(math.atan2(y, x)) + 360) % 360


class Carnet:
    """Les points du copilote, gardes entre deux vols."""

    def __init__(self, chemin):
        self.chemin = chemin
        self.points = []
        self.choisi = 0
        self.prochain_wpt = None   # prochain numero de waypoint libre (cette mission)
        try:
            with open(chemin, encoding="utf-8") as f:
                for d in json.load(f):
                    self.points.append(Point(d["nom"], d["lat"], d["lon"], d.get("alt_m"),
                                             d.get("source", "")))
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def sauver(self):
        try:
            os.makedirs(os.path.dirname(self.chemin), exist_ok=True)
            with open(self.chemin, "w", encoding="utf-8") as f:
                json.dump([p.dict() for p in self.points], f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def ajouter(self, point):
        self.points.append(point)
        self.points = self.points[-30:]
        self.choisi = len(self.points) - 1
        self.sauver()
        return point

    def nom_libre(self, prefixe):
        n = 1
        noms = {p.nom for p in self.points}
        while f"{prefixe} {n}" in noms:
            n += 1
        return f"{prefixe} {n}"

    @property
    def point(self):
        if not self.points:
            return None
        self.choisi = max(0, min(self.choisi, len(self.points) - 1))
        return self.points[self.choisi]

    def suivant(self, pas=1):
        if self.points:
            self.choisi = (self.choisi + pas) % len(self.points)
        return self.point

    def supprimer(self, index):
        if 0 <= index < len(self.points):
            del self.points[index]
            self.sauver()


# ------------------------------------------------------------- page HSI
def _valeur(elems, nom):
    for n, v in elems:
        if n == nom:
            return v
    return None


def _encadre(elems, libelle):
    """L'option `libelle` est-elle encadree ? (element 'XXX_1_box__id:N')"""
    for n, _v in elems:
        if n.startswith(libelle) and "_box" in n:
            return True
    return False


def _present(elems, libelle):
    return any(n.startswith(libelle + "_") or v.replace("\n", "") == libelle for n, v in elems)


def lire_hsi(export, ecrans=(4, 3, 2)):
    """Page HSI (ou sa sous-page DATA) affichee sur l'AMPCD ou un DDI."""
    if export is None or not export.vivant:
        return None
    for i in ecrans:
        txt = export.ecrans.get(i) or ""
        if "WYPT_Page_Number" not in txt and "HSI_Main_Root" not in txt and "PRECISE" not in txt:
            continue
        el = elements(txt)
        info = {"ecran": i, "texte": txt, "elements": el,
                "data": "PRECISE" in txt, "principale": "HSI_Main_Root" in txt,
                "wypt": None, "cap": None, "dist": None, "vs": None,
                "wypt_encadre": _encadre(el, "WYPT"), "tcn_encadre": _encadre(el, "TCN"),
                "precise": _encadre(el, "PRECISE")}
        n = _valeur(el, "WYPT_Page_Number")
        if n is not None and n.strip().isdigit():
            info["wypt"] = int(n.strip())
        trc = _valeur(el, "TRCData") or ""
        m = re.search(r"(\d+)\s*°\s*/\s*([\d.]+)", trc)
        if m:
            info["cap"], info["dist"] = int(m.group(1)), float(m.group(2))
        vs = _valeur(el, "GroundSpeed_TN_UP_Mode") or ""
        m = re.match(r"\s*(\d+)", vs)
        if m:
            info["vs"] = int(m.group(1))
        return info
    return None


def _bouton(info):
    return {4: "AMPCD_PB_", 3: "RIGHT_DDI_PB_", 2: "LEFT_DDI_PB_"}[info["ecran"]]


def _appuyer(r, ident, duree=0.2):
    r.b.envoyer(ident, 1)
    r.attendre(duree)
    r.b.envoyer(ident, 0)
    r.attendre(0.3)


def _hsi(r):
    info = lire_hsi(r.export)
    if info is None:
        raise Echec("Page HSI introuvable. Mets la HSI sur l'AMPCD.")
    return info


def bouton_appris(r, cle, candidats, condition, delai=2.5):
    """Appuie sur le bouton `cle` de la page HSI/DATA, verifie par `condition(avant, apres)`.
    Le numero qui marche est retenu dans les reglages (comme STD HDG)."""
    from .chemins import sauver_config
    connus = r.cfg.setdefault("boutons_hsi", {})
    essais = [connus[cle]] if cle in connus else list(candidats)
    for pb in essais:
        avant = _hsi(r)
        ident = f"{_bouton(avant)}{pb:02d}"
        _appuyer(r, ident)
        fin = r.horloge() + delai
        while r.horloge() < fin:
            apres = lire_hsi(r.export)
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
            apres = lire_hsi(r.export)
            r.boite.ecrire("bouton_hsi_sans_effet", cle=cle, bouton=ident,
                           texte=(apres or avant)["texte"][:20000])
        if cle in connus:          # le bouton retenu ne marche plus : on reapprendra
            del connus[cle]
    raise Echec("Bouton " + cle.replace("_", " ") + " sans effet.")


def _change_wpt(pas):
    def condition(avant, apres):
        return (apres["wypt"] is not None and avant["wypt"] is not None
                and apres["wypt"] != avant["wypt"]
                and (apres["wypt"] - avant["wypt"]) * pas > 0)
    return condition


def annonce_wpt(info):
    if info is None or info["wypt"] is None:
        return ""
    texte = f"Waypoint {info['wypt']}"
    if info["cap"] is not None and info["dist"] is not None:
        texte += f", cap {info['cap']:03d}, {info['dist']:.0f} nautiques"
    return texte + "."


# --------------------------------------------------------- actions (r = executeur)
def wpt_plus(r):
    _choisir_wpt(r, 1)


def wpt_moins(r):
    _choisir_wpt(r, -1)


def _choisir_wpt(r, pas):
    info = _hsi(r)
    if info["data"]:
        raise Echec("Page DATA ouverte. Reviens sur la HSI.")
    if info["wypt"] is None:
        raise Echec("Numéro de waypoint illisible.")
    cle = "wpt_plus" if pas > 0 else "wpt_moins"
    apres = bouton_appris(r, cle, BOUTONS_HSI[cle], _change_wpt(pas))
    _guidage_wpt(r)
    r.attendre(0.8)
    r.dire(annonce_wpt(lire_hsi(r.export) or apres))


def _guidage_wpt(r):
    """WYPT encadre sur la HSI : l'avion (et le pilote auto en CPL) suit le waypoint."""
    info = _hsi(r)
    if not info["wypt_encadre"]:
        bouton_appris(r, "wypt", BOUTONS_HSI["wypt"],
                      lambda a, b: b["wypt_encadre"] and not a["wypt_encadre"])


def retour_base(r):
    """Waypoint 0 (le terrain de depart dans DCS), guidage, cap, distance, carburant."""
    info = _hsi(r)
    if info["wypt"] is None:
        raise Echec("Numéro de waypoint illisible.")
    for _ in range(80):
        info = _hsi(r)
        if info["wypt"] == 0:
            break
        bouton_appris(r, "wpt_moins", BOUTONS_HSI["wpt_moins"], _change_wpt(-1))
    else:
        raise Echec("Waypoint 0 introuvable.")
    _guidage_wpt(r)
    r.attendre(1.0)
    info = lire_hsi(r.export) or info
    texte = "Retour base. " + annonce_wpt(info).replace("Waypoint 0", "Base")
    reste = estimation_carburant(r.a, info)
    if reste is not None:
        texte += f" Carburant à l'arrivée : {int(round(reste, -2))} livres."
        if reste < (r.cfg.get("bingo_lbs") or 0):
            texte += " Sous le BINGO."
    r.dire(texte)


def estimation_carburant(avion, info):
    """Carburant estime a l'arrivee, d'apres le debit des moteurs et la vitesse sol."""
    try:
        carbu = avion.carburant
        debit = (float(avion.b.lire("IFEI_FF_L") or 0) + float(avion.b.lire("IFEI_FF_R") or 0)) * 100
    except (TypeError, ValueError):
        return None
    if not carbu or not debit or not info or not info.get("dist") or not info.get("vs"):
        return None
    heures = info["dist"] / max(info["vs"], 100)
    return carbu - debit * heures


# ------------------------------------------------------------------ UFC
def options_ufc(b):
    return [(b.lire(f"UFC_OPTION_DISPLAY_{i}") or "").strip() for i in range(1, 6)]


def option_ufc(r, libelle, attendu=True):
    """Appuie sur l'option UFC qui porte ce libelle (lu sur l'UFC). Renvoie False si absente."""
    for _ in range(6):
        opts = options_ufc(r.b)
        for i, o in enumerate(opts, 1):
            if o.replace(" ", "").upper().startswith(libelle.replace(" ", "").upper()):
                _appuyer(r, f"UFC_OS{i}")
                return True
        r.attendre(0.25)
    if attendu and getattr(r, "boite", None) is not None:
        r.boite.ecrire("option_ufc_absente", option=libelle, options=options_ufc(r.b))
    return False


def option_choisie(b, libelle):
    for i, o in enumerate(options_ufc(b), 1):
        if o.replace(" ", "").upper().startswith(libelle.replace(" ", "").upper()):
            return (b.lire(f"UFC_OPTION_CUEING_{i}") or "").strip() == ":"
    return False


def taper(r, chiffres):
    for c in chiffres:
        _appuyer(r, f"UFC_{c}", 0.15)


def entrer(r):
    _appuyer(r, "UFC_ENT", 0.15)
    r.attendre(0.3)


# ----------------------------------------------------- point -> waypoint
def point_en_waypoint(r):
    """Cree un waypoint avec le point choisi dans le carnet.
    HSI -> DATA -> PRECISE -> numero libre -> UFC POSN -> latitude, longitude, altitude."""
    nav = r.nav
    p = nav.point
    if p is None:
        raise Echec("Carnet vide. Prends d'abord un point.")
    info = _hsi(r)
    if info["data"] is False and info["wypt"] is None:
        raise Echec("Numéro de waypoint illisible.")
    depart = info["wypt"] or 0
    cible = nav.prochain_wpt or max(20, depart + 1)

    # page DATA
    if not info["data"]:
        bouton_appris(r, "data", BOUTONS_HSI["data"], lambda a, b: b["data"])
    precise_avant = _hsi(r)["precise"]
    try:
        if not precise_avant:
            bouton_appris(r, "data_precise", BOUTONS_DATA["precise"],
                          lambda a, b: b["precise"] and not a["precise"])
        # numero du waypoint
        for _ in range(100):
            d = _hsi(r)
            if d["wypt"] is None:
                raise Echec("Numéro de waypoint illisible sur la page DATA.")
            if d["wypt"] == cible:
                break
            pas = 1 if d["wypt"] < cible else -1
            cle = "data_wpt_plus" if pas > 0 else "data_wpt_moins"
            bouton_appris(r, cle, BOUTONS_DATA["wpt_plus" if pas > 0 else "wpt_moins"],
                          _change_wpt(pas))
        else:
            raise Echec(f"Waypoint {cible} inaccessible.")
        # saisie sur l'UFC : si l'UFC n'affiche pas POSN, on lui passe le
        # waypoint avec l'option UFC de la page DATA (bouton 5)
        if not option_ufc(r, "POSN", attendu=False):
            d = _hsi(r)
            _appuyer(r, f"{_bouton(d)}{r.cfg.get('boutons_hsi', {}).get('data_ufc', 5):02d}")
            r.attendre(0.6)
            if not option_ufc(r, "POSN"):
                raise Echec("Option POSN absente de l'UFC.")
        for valeur, est_lat in ((p.lat, True), (p.lon, False)):
            touche, tete, dec = saisie_ufc(valeur, est_lat)
            taper(r, touche)
            taper(r, tete)
            entrer(r)
            taper(r, dec)
            entrer(r)
        if p.alt_m is not None and option_ufc(r, "ELEV", attendu=False):
            if option_ufc(r, "FEET", attendu=False):
                taper(r, str(max(0, int(round(p.alt_m * PIEDS)))))
                entrer(r)
        _appuyer(r, "UFC_CLR")
        r.attendre(0.8)
        d = _hsi(r)
        attendu = f"{int(abs(p.lat)):d}°"
        if attendu not in d["texte"]:
            r.non_confirmes.append(f"coordonnées du waypoint {cible}")
        if getattr(r, "boite", None) is not None:
            r.boite.ecrire("waypoint_cree", numero=cible, point=p.dict(),
                           texte=d["texte"][:20000])
    finally:
        try:
            d = lire_hsi(r.export)
            if d and d["data"] and d["precise"] and not precise_avant:
                _appuyer(r, f"{_bouton(d)}{r.cfg.get('boutons_hsi', {}).get('data_precise', 19):02d}")
            d = lire_hsi(r.export)
            if d and d["data"]:
                _appuyer(r, f"{_bouton(d)}{r.cfg.get('boutons_hsi', {}).get('data', 10):02d}")
        except Exception:
            pass
    nav.prochain_wpt = cible + 1
    r.dire(f"Waypoint {cible} créé : {p.nom}.")


def aller_au_point(r):
    """Cree le waypoint puis s'y dirige."""
    point_en_waypoint(r)
    cible = r.nav.prochain_wpt - 1
    for _ in range(100):
        info = _hsi(r)
        if info["data"]:
            r.attendre(0.5)
            continue
        if info["wypt"] == cible:
            break
        pas = 1 if (info["wypt"] or 0) < cible else -1
        cle = "wpt_plus" if pas > 0 else "wpt_moins"
        bouton_appris(r, cle, BOUTONS_HSI[cle], _change_wpt(pas))
    _guidage_wpt(r)
    r.attendre(0.8)
    r.dire(annonce_wpt(lire_hsi(r.export)))


# ----------------------------------------------------------------- TACAN
def tacan_choisi(cfg, nav):
    liste = cfg.get("tacan") or []
    if not liste:
        return None
    nav.tacan = max(0, min(getattr(nav, "tacan", 0), len(liste) - 1))
    return liste[nav.tacan]


def regler_tacan(r):
    t = tacan_choisi(r.cfg, r.nav)
    if t is None:
        raise Echec("Aucun canal TACAN enregistré. Ajoute-les dans la fenêtre.")
    canal = str(int(t.get("canal", 0)))
    bande = (t.get("bande") or "X").upper()
    mode = (t.get("mode") or "T/R").upper()
    _appuyer(r, "UFC_TCN")
    r.attendre(0.5)
    if "OFF" in ((r.b.lire("UFC_SCRATCHPAD_STRING_1_DISPLAY") or "")
                 + (r.b.lire("UFC_SCRATCHPAD_STRING_2_DISPLAY") or "")).upper().replace(" ", ""):
        _appuyer(r, "UFC_ONOFF")
    taper(r, canal)
    entrer(r)
    option_ufc(r, bande)
    option_ufc(r, "A/A" if mode == "A/A" else "T/R")
    r.attendre(0.5)
    lu = (r.b.lire("UFC_SCRATCHPAD_NUMBER_DISPLAY") or "").strip()
    if canal not in lu.replace(" ", ""):
        r.non_confirmes.append("canal TACAN")
        if getattr(r, "boite", None) is not None:
            r.boite.ecrire("tacan_non_confirme", voulu=t, lu=lu, options=options_ufc(r.b))
    # guidage TACAN sur la HSI
    try:
        info = _hsi(r)
        if not info["tcn_encadre"]:
            bouton_appris(r, "tcn", BOUTONS_HSI["tcn"],
                          lambda a, b: b["tcn_encadre"] and not a["tcn_encadre"])
        r.attendre(2.0)
        info = lire_hsi(r.export)
    except Echec:
        info = None
    texte = f"TACAN {canal} {bande}, {t.get('nom', '')}."
    if info and info["cap"] is not None and info["dist"]:
        texte += f" Cap {info['cap']:03d}, {info['dist']:.0f} nautiques."
    r.dire(texte)


# ---------------------------------------------------------- pilote auto
def _pilote(libelle, message):
    def action(r):
        if r.a.au_sol:
            raise Echec("Négatif. Pilote automatique en vol uniquement.")
        if libelle == "CPL" and not _hsi(r)["tcn_encadre"]:
            _guidage_wpt(r)
        _appuyer(r, "UFC_AP")
        r.attendre(0.4)
        if not option_ufc(r, libelle):
            raise Echec(f"Option {libelle} absente du pilote automatique.")
        r.attendre(0.5)
        if not option_choisie(r.b, libelle):
            r.non_confirmes.append(f"pilote automatique {libelle}")
            if getattr(r, "boite", None) is not None:
                r.boite.ecrire("pilote_auto_non_confirme", option=libelle,
                               options=options_ufc(r.b),
                               reperes=[r.b.lire(f"UFC_OPTION_CUEING_{i}") for i in range(1, 6)])
        r.dire(message)
    return action


def pilote_off(r):
    _appuyer(r, "STICK_PADDLE_SW", 0.3)
    r.dire("Pilote automatique déconnecté.")


# ------------------------------------------------- passage des waypoints
class SuiviWaypoints:
    """Appele par la surveillance : annonce les passages, sequence si demande."""

    def __init__(self):
        self.wpt = None
        self.min_dist = None
        self.annonce_proche = False

    def tick(self, export, avion, cfg, dire, suivant):
        info = lire_hsi(export)
        if info is None or info["wypt"] is None or info["dist"] is None or avion.au_sol:
            return
        if not info["wypt_encadre"] or info["data"]:
            return
        if info["wypt"] != self.wpt:
            self.wpt, self.min_dist, self.annonce_proche = info["wypt"], info["dist"], False
            return
        d = info["dist"]
        if d < 5 and not self.annonce_proche and self.min_dist is not None and self.min_dist >= 5:
            self.annonce_proche = True
            dire(f"Waypoint {self.wpt} dans 5 nautiques.")
        if self.min_dist is None or d < self.min_dist:
            self.min_dist = d
            return
        # on s'eloigne apres etre passe tout pres : waypoint passe
        if self.min_dist < 1.5 and d > self.min_dist + 0.3:
            passe = self.wpt
            self.min_dist = 1e9
            if cfg.get("nav_sequence_auto", True):
                suivant(passe)
            else:
                dire(f"Waypoint {passe} passé.")


# ------------------------------------------------------ procedures nav
def _proc(fonction, quoi):
    from .procedures import Appelle

    def garde(r):
        try:
            fonction(r)
        except Echec as ex:
            r.dire(str(ex))
            if getattr(r, "boite", None) is not None:
                r.boite.ecrire("navigation_echec", action=quoi, raison=str(ex))
    return [Appelle(garde, quoi)]


def _sequence(r):
    passe = getattr(r.nav, "passe", None)
    info = _hsi(r)
    if passe is not None and info["wypt"] != passe:
        return
    bouton_appris(r, "wpt_plus", BOUTONS_HSI["wpt_plus"], _change_wpt(1))
    r.attendre(0.8)
    r.dire(f"Waypoint {passe} passé. " + annonce_wpt(lire_hsi(r.export)))


PROCEDURES_NAV = {
    "wpt_plus": ("Waypoint suivant", _proc(wpt_plus, "waypoint suivant")),
    "wpt_moins": ("Waypoint précédent", _proc(wpt_moins, "waypoint précédent")),
    "wpt_passe": ("Séquence waypoint", _proc(_sequence, "séquence waypoint")),
    "retour_base": ("Retour base", _proc(retour_base, "retour base")),
    "point_wpt": ("Point vers waypoint", _proc(point_en_waypoint, "point vers waypoint")),
    "aller_point": ("Aller au point", _proc(aller_au_point, "aller au point")),
    "tacan": ("TACAN", _proc(regler_tacan, "TACAN")),
    "ap_balt": ("Pilote auto altitude", _proc(_pilote("BALT", "Pilote auto, maintien d'altitude."),
                                               "pilote auto BALT")),
    "ap_hsel": ("Pilote auto cap", _proc(_pilote("HSEL", "Pilote auto, maintien du cap sélecté."),
                                          "pilote auto HSEL")),
    "ap_cpl": ("Pilote auto couplé", _proc(_pilote("CPL", "Pilote auto couplé sur la navigation."),
                                           "pilote auto CPL")),
    "ap_off": ("Pilote auto off", _proc(pilote_off, "pilote auto off")),
}
