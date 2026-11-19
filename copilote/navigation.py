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
import time

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
    "tcn": (5,),             # TCN a marche le 15 nov. (14 h 58)
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
    """Un waypoint du plan de vol. num = numero dans l'avion ; sync = deja dans l'avion."""

    def __init__(self, nom, lat, lon, alt_m=None, source="", num=None, sync=False, cree=None):
        self.cree = time.time() if cree is None else float(cree)
        self.nom, self.lat, self.lon = nom, float(lat), float(lon)
        self.alt_m = None if alt_m is None else float(alt_m)
        self.source = source
        self.num = None if num is None else int(num)
        self.sync = bool(sync)

    def dict(self):
        return {"nom": self.nom, "lat": self.lat, "lon": self.lon, "alt_m": self.alt_m,
                "source": self.source, "num": self.num, "sync": self.sync, "cree": self.cree}

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
    """Le plan de vol du copilote : les waypoints, gardes entre deux vols.
    Chaque point a un numero de waypoint ; ENVOYER A L'AVION ecrit ceux qui ne
    sont pas encore dans l'avion, LIRE L'AVION recupere la route de la mission."""

    def __init__(self, chemin):
        self.chemin = chemin
        self.points = []
        self.choisi = 0
        self.tacan = 0
        self.cible = None          # numero vers lequel aller (fenetre)
        self.cap_demande = None    # pilote auto sur un cap : None = cap actuel, nombre, ("wpt", n)
        self.fin_mission = 0.0     # derniere heure ou la mission precedente tournait
        self.t_modele = None       # horloge de cette mission (DCS), pour reperer une nouvelle mission
        self._sauve_t = 0.0
        try:
            with open(chemin, encoding="utf-8") as f:
                donnees = json.load(f)
            if isinstance(donnees, dict):
                self.fin_mission = float(donnees.get("fin_mission", 0))
                self.t_modele = donnees.get("t_modele")
                donnees = donnees.get("points", [])
            for d in donnees:
                self.points.append(Point(d["nom"], d["lat"], d["lon"], d.get("alt_m"),
                                         d.get("source", ""), d.get("num"), False, d.get("cree", 0)))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.trier()

    def fin_de_vol(self):
        self.fin_mission = time.time()
        self.sauver()

    def horloge_mission(self, t):
        """Appele chaque seconde avec l'horloge de la mission DCS. Si elle est
        repartie en arriere, c'est une nouvelle mission -> renvoie le nombre de
        waypoints de l'ancienne mission retires (sinon None)."""
        retires = None
        if self.t_modele is not None and t < self.t_modele - 30:
            retires = self.nouvelle_mission()
        self.t_modele = t
        maintenant = time.time()
        self.fin_mission = maintenant
        if maintenant - self._sauve_t > 20:
            self._sauve_t = maintenant
            self.sauver()
        return retires

    def nouvelle_mission(self):
        """Nouveau vol : les waypoints faits pour une mission precedente sont retires
        (ceux prepares depuis la fin du dernier vol restent)."""
        avant = len(self.points)
        limite = self.fin_mission
        self.points = [p for p in self.points if p.cree > limite]
        for p in self.points:
            p.sync = False
        if len(self.points) != avant:
            self.sauver()
        return avant - len(self.points)

    def effacer(self):
        self.points = []
        self.choisi = 0
        self.sauver()

    def trier(self):
        self.points.sort(key=lambda p: (p.num is None, p.num or 0))

    def sauver(self):
        try:
            os.makedirs(os.path.dirname(self.chemin), exist_ok=True)
            with open(self.chemin, "w", encoding="utf-8") as f:
                json.dump({"fin_mission": self.fin_mission, "t_modele": self.t_modele,
                           "points": [p.dict() for p in self.points]},
                          f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def numero_libre(self):
        pris = {p.num for p in self.points if p.num is not None}
        n = max(pris) + 1 if pris else 1
        return max(1, min(n, 59))

    def ajouter(self, point):
        if point.num is None:
            point.num = self.numero_libre()
        self.points = [p for p in self.points if p.num != point.num] + [point]
        self.trier()
        self.choisi = self.points.index(point)
        self.sauver()
        return point

    def par_numero(self, num):
        for p in self.points:
            if p.num == num:
                return p
        return None

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

    def a_envoyer(self):
        return [p for p in self.points if not p.sync and p.num is not None]


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
        else:
            m = re.search(r"(\d+)", _valeur(el, "WYPT_Number") or "")
            if m:
                info["wypt"] = int(m.group(1))
        # page DATA : coordonnees du waypoint affiche, et la route (SEQ)
        info["lat"] = _coord(_valeur(el, "WYPT_Latitude"))
        info["lon"] = _coord(_valeur(el, "WYPT_Longitude"))
        m = re.match(r"\s*(-?\d+)\s*FT", _valeur(el, "WYPT_Elev") or "")
        info["elev_ft"] = int(m.group(1)) if m else None
        info["route"] = [int(x) for x in re.findall(r"\d+", _valeur(el, "WYPT_SequenceData") or "")]
        m = re.match(r"\s*(\d+)", _valeur(el, "HSELData") or "")
        info["hsel"] = int(m.group(1)) % 360 if m else None
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


def _coord(texte):
    """ "N 42°08.9433'" -> 42.149055 """
    if not texte:
        return None
    m = re.match(r"\s*([NSEW])\s*(\d+)\s*°\s*([\d.]+)", texte)
    if not m:
        return None
    v = int(m.group(2)) + float(m.group(3)) / 60
    return -v if m.group(1) in "SW" else v


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
    essais = ([connus[cle]] if cle in connus else []) + [c for c in candidats if c != connus.get(cle)]
    # deuxieme passage avec un appui plus long (l'AMPCD rate parfois un appui bref)
    for pb, duree in [(p, 0.2) for p in essais] + [(p, 0.5) for p in essais]:
        avant = _hsi(r)
        ident = f"{_bouton(avant)}{pb:02d}"
        _appuyer(r, ident, duree)
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
        _aller_numero(r, 1, False)
        info = _hsi(r)
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


# ------------------------------------------------- page DATA (plan de vol)
def _ouvrir_data(r):
    """-> etat a remettre en sortant : (PRECISE etait encadre ?)"""
    info = _hsi(r)
    r.nav.depart_data = info["wypt"]
    if not info["data"]:
        bouton_appris(r, "data", BOUTONS_HSI["data"], lambda a, b: b["data"])
        r.attendre(0.5)
    precise = _hsi(r)["precise"]
    if not precise:
        bouton_appris(r, "data_precise", BOUTONS_DATA["precise"],
                      lambda a, b: b["precise"] and not a["precise"])
    return precise


def _fermer_data(r, precise_avant):
    try:
        d = lire_hsi(r.export)
        boutons = r.cfg.get("boutons_hsi", {})
        if d and d["data"] and d["precise"] and not precise_avant:
            _appuyer(r, f"{_bouton(d)}{boutons.get('data_precise', 19):02d}")
        d = lire_hsi(r.export)
        if d and d["data"]:
            _appuyer(r, f"{_bouton(d)}{boutons.get('data', 10):02d}")
    except Exception:
        pass


def _aller_numero(r, cible, page_data, depart=None):
    """Va au waypoint `cible`. Sur un waypoint vide, la page DATA n'affiche rien
    (pas meme le numero) : on compte alors les crans a partir du dernier numero lu."""
    boutons = r.cfg.get("boutons_hsi", {})
    suppose = depart
    for _ in range(120):
        d = _hsi(r)
        if d["data"] != page_data:
            r.attendre(0.4)
            d = _hsi(r)
        if d["wypt"] is None:
            r.attendre(0.3)
            d = _hsi(r)
        n = d["wypt"] if d["wypt"] is not None else suppose
        if n is None:
            # rien de lisible et aucun repere : un cran pour faire apparaitre un numero
            pb = boutons.get("data_wpt_plus" if page_data else "wpt_plus", 12)
            _appuyer(r, f"{_bouton(d)}{pb:02d}")
            r.attendre(0.8)
            d = _hsi(r)
            if d["wypt"] is None:
                if getattr(r, "boite", None) is not None:
                    r.boite.ecrire("numero_illisible", texte=d["texte"][:20000])
                raise Echec("Numéro de waypoint illisible.")
            continue
        if n == cible:
            return d
        pas = 1 if n < cible else -1
        if d["wypt"] is None:
            # waypoint vide : appui sans verification possible, on compte
            cle = ("data_wpt_plus" if pas > 0 else "data_wpt_moins") if page_data else \
                ("wpt_plus" if pas > 0 else "wpt_moins")
            defaut = 12 if pas > 0 else 13
            _appuyer(r, f"{_bouton(d)}{boutons.get(cle, defaut):02d}")
            r.attendre(0.5)
            suppose = n + pas
            continue
        if page_data:
            cle = "data_wpt_plus" if pas > 0 else "data_wpt_moins"
            cand = BOUTONS_DATA["wpt_plus" if pas > 0 else "wpt_moins"]
        else:
            cle = "wpt_plus" if pas > 0 else "wpt_moins"
            cand = BOUTONS_HSI[cle]
        apres = bouton_appris(r, cle, cand, lambda a, b: b["wypt"] is None or _change_wpt(pas)(a, b))
        suppose = apres["wypt"] if apres["wypt"] is not None else n + pas
    raise Echec(f"Waypoint {cible} inaccessible.")


def _ecrire(r, p):
    """Sur la page DATA, au bon numero : UFC POSN, latitude, longitude, altitude."""
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
    ok = (d["lat"] is not None and d["lon"] is not None
          and abs(d["lat"] - p.lat) < 0.0005 and abs(d["lon"] - p.lon) < 0.0005)
    if getattr(r, "boite", None) is not None:
        r.boite.ecrire("waypoint_ecrit", numero=p.num, point=p.dict(), relu=(d["lat"], d["lon"]),
                       verifie=ok, texte="" if ok else d["texte"][:20000])
    return ok


def envoyer_plan(r):
    """Ecrit dans l'avion les waypoints du plan qui n'y sont pas encore."""
    nav = r.nav
    a_faire = nav.a_envoyer()
    if not a_faire:
        r.dire("Plan de vol déjà dans l'avion.")
        return
    r.dire(f"Envoi de {len(a_faire)} waypoint{'s' if len(a_faire) > 1 else ''}.")
    precise = _ouvrir_data(r)
    faits, rates = [], []
    try:
        for p in sorted(a_faire, key=lambda q: q.num):
            _aller_numero(r, p.num, True, getattr(nav, "depart_data", None))
            nav.depart_data = p.num
            if _ecrire(r, p):
                p.sync = True
                faits.append(p.num)
            else:
                rates.append(p.num)
    finally:
        _fermer_data(r, precise)
        nav.sauver()
    if rates:
        r.non_confirmes.append("waypoints " + ", ".join(map(str, rates)))
        r.dire(f"Waypoints envoyés. À vérifier : {', '.join(map(str, rates))}.")
    else:
        r.dire("Plan de vol envoyé. " + (f"Waypoint {faits[0]}." if len(faits) == 1
                                        else f"Waypoints {faits[0]} à {faits[-1]}."))


def lire_avion(r):
    """Recupere la route de la mission (et le waypoint 0) depuis la page DATA."""
    nav = r.nav
    precise = _ouvrir_data(r)
    lus = []
    try:
        d = _hsi(r)
        if d["wypt"] is None and not d["route"]:
            r.dire("Pas de route dans cette mission.")
            return
        route = sorted(set([0] + (d["route"] or [])))
        route += [p.num for p in nav.points if p.num is not None and p.num not in route]
        depart = getattr(nav, "depart_data", None)
        for num in sorted(set(route)):
            d = _aller_numero(r, num, True, depart)
            depart = num
            r.attendre(0.4)
            d = _hsi(r)
            if d["lat"] is None or d["lon"] is None or (abs(d["lat"]) < 0.01 and abs(d["lon"]) < 0.01):
                continue
            ancien = nav.par_numero(num)
            nom = ancien.nom if ancien and ancien.source != "avion" and \
                abs(ancien.lat - d["lat"]) < 0.0005 else ("Base" if num == 0 else f"WPT {num}")
            alt = None if d["elev_ft"] is None else d["elev_ft"] / PIEDS
            nav.ajouter(Point(nom, d["lat"], d["lon"], alt, "avion", num, True))
            lus.append(num)
    finally:
        _fermer_data(r, precise)
        nav.sauver()
    r.dire(f"{len(lus)} waypoints lus dans l'avion." if lus else "Aucun waypoint lu.")


def aller_wpt(r):
    """Guidage vers le waypoint choisi dans la fenetre (r.nav.cible)."""
    cible = r.nav.cible
    if cible is None:
        raise Echec("Aucun waypoint choisi.")
    p = r.nav.par_numero(cible)
    if p is not None and not p.sync:
        envoyer_plan(r)
    _aller_numero(r, cible, False)
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


def _bloc_note(b):
    return " ".join((b.lire(i) or "").strip() for i in (
        "UFC_SCRATCHPAD_STRING_1_DISPLAY", "UFC_SCRATCHPAD_STRING_2_DISPLAY",
        "UFC_SCRATCHPAD_NUMBER_DISPLAY")).upper()


def _eteint(texte):
    t = texte.replace(" ", "")
    return "OFF" in t or t.startswith("OF")


def ufc_allumer(r, bouton, nom):
    """Fonction UFC (TCN, IFF, D/L, BCN) sur ON. Le bloc-notes de l'UFC affiche
    ON ou OFF : on bascule si besoin, et on note ce qu'on a lu (boite noire)."""
    _appuyer(r, bouton)
    r.attendre(0.6)
    avant = _bloc_note(r.b)
    if "ON" in avant.replace(" ", "") and not _eteint(avant):
        return True
    _appuyer(r, "UFC_ONOFF")
    r.attendre(0.6)
    apres = _bloc_note(r.b)
    # TACAN et D/L affichent ON ; l'IFF affiche ses modes (XP le 15 nov.) une fois en marche
    ok = (("ON" in apres.replace(" ", "")) or (apres.strip() and apres != avant)) and not _eteint(apres)
    if not ok and not _eteint(avant) and _eteint(apres):
        _appuyer(r, "UFC_ONOFF")          # c'etait deja en marche : on remet
        r.attendre(0.6)
        apres = _bloc_note(r.b)
        ok = not _eteint(apres)
    if getattr(r, "boite", None) is not None:
        r.boite.ecrire("ufc_marche", fonction=nom, avant=avant, apres=apres, ok=ok)
    return ok


def regler_tacan(r, pilote=False):
    t = tacan_choisi(r.cfg, r.nav)
    if t is None:
        raise Echec("Aucun canal TACAN enregistré. Ajoute-les dans la fenêtre.")
    canal = str(int(t.get("canal", 0)))
    bande = (t.get("bande") or "X").upper()
    mode = (t.get("mode") or "T/R").upper()
    allume = ufc_allumer(r, "UFC_TCN", "TACAN")
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
    if not allume:
        r.non_confirmes.append("TACAN sur ON")
    # guidage TACAN sur la HSI (possible seulement TACAN en marche)
    info = None
    try:
        r.attendre(1.5)
        info = _hsi(r)
        if not info["tcn_encadre"]:
            bouton_appris(r, "tcn", BOUTONS_HSI["tcn"],
                          lambda a, b: b["tcn_encadre"] and not a["tcn_encadre"])
        r.attendre(2.0)
        info = lire_hsi(r.export)
    except Echec:
        r.non_confirmes.append("guidage TACAN sur la HSI")
    texte = f"TACAN {canal} {bande}, {t.get('nom', '')}."
    if info and info["cap"] is not None and info["dist"]:
        texte += f" Cap {info['cap']:03d}, {info['dist']:.0f} nautiques."
    r.dire(texte)
    if pilote:
        info = lire_hsi(r.export)
        if not (info and info["tcn_encadre"]):
            raise Echec("Guidage TACAN non pris sur la HSI : appuie sur TCN, puis A/P SUIT NAV.")
        _pilote("CPL", "Pilote auto couplé sur le TACAN.")(r)


# ---------------------------------------------------------- pilote auto
def _pilote(libelle, message):
    def action(r):
        if r.a.au_sol:
            raise Echec("Négatif. Pilote automatique en vol uniquement.")
        if libelle == "CPL" and not _hsi(r)["tcn_encadre"]:
            _guidage_wpt(r)
        for essai in range(2):
            _appuyer(r, "UFC_AP")
            r.attendre(0.5)
            if not option_ufc(r, libelle):
                if essai == 0:
                    r.attendre(1.0)
                    continue
                raise Echec(f"Option {libelle} absente du pilote automatique. "
                            "Il faut un guidage (WYPT ou TCN) encadré sur la HSI.")
            r.attendre(1.0)
            if option_choisie(r.b, libelle):
                break
        if not option_choisie(r.b, libelle):
            if getattr(r, "boite", None) is not None:
                r.boite.ecrire("pilote_auto_non_confirme", option=libelle,
                               options=options_ufc(r.b),
                               reperes=[r.b.lire(f"UFC_OPTION_CUEING_{i}") for i in range(1, 6)],
                               vitesse=r.a.vitesse, altitude=r.a.altitude)
            raise Echec("Pilote auto refusé. Avion stabilisé, ailes à plat, manche au neutre, "
                        "puis réessaie.")
        r.dire(message)
    return action


def _ecart(a, b):
    """Ecart d'angle a - b, ramene entre -180 et 180."""
    return (a - b + 180) % 360 - 180


def cap_magnetique(r):
    """Cap magnetique de l'avion (celui de la HSI), ou None."""
    try:
        v = r.b.lire("HDG_DEG_MAG")
        if v is not None:
            return int(v) % 360
    except Exception:
        pass
    return None


def cap_vers(r, lat, lon):
    """Cap magnetique a prendre pour aller vers ce point, depuis la position de l'avion."""
    pos = getattr(r.export, "position", None) if r.export is not None else None
    if not pos or pos.get("lat") is None:
        raise Echec("Position de l'avion inconnue : liaison DCS absente.")
    la1, la2 = math.radians(pos["lat"]), math.radians(lat)
    dl = math.radians(lon - pos["lon"])
    vrai = math.degrees(math.atan2(math.sin(dl) * math.cos(la2),
                                   math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl))) % 360
    mag = cap_magnetique(r)
    if mag is not None and pos.get("cap") is not None:
        vrai_avion = math.degrees(pos["cap"]) % 360
        return round(mag + _ecart(vrai, vrai_avion)) % 360       # corrige la declinaison
    return round(vrai) % 360


def regler_hsel(r, cible):
    """Amene le repere de cap (HSEL, lu sur la HSI) sur le cap voulu avec l'interrupteur HDG."""
    info = lire_hsi(r.export)
    if info is None or info.get("hsel") is None:
        raise Echec("Affiche la HSI : j'ai besoin de lire le cap sélecté.")
    sens = {1: 2, -1: 0}                                # ecart positif -> interrupteur vers la droite
    fin = r.horloge() + 45
    pire = 0
    while r.horloge() < fin:
        info = lire_hsi(r.export)
        if info is None or info.get("hsel") is None:
            raise Echec("HSI masquée pendant le réglage du cap.")
        e = _ecart(cible, info["hsel"])
        if abs(e) <= 1:
            return info["hsel"]
        duree = 1.0 if abs(e) > 40 else 0.45 if abs(e) > 12 else 0.12 if abs(e) > 3 else 0.05
        r.b.envoyer("LEFT_DDI_HDG_SW", sens[1 if e > 0 else -1])
        r.attendre(duree)
        r.b.envoyer("LEFT_DDI_HDG_SW", 1)
        r.attendre(0.35)
        apres = lire_hsi(r.export)
        if apres is not None and apres.get("hsel") is not None:
            bouge = _ecart(apres["hsel"], info["hsel"])
            if abs(bouge) < 1:
                pire += 1
                if pire >= 6:                           # le repere ne bouge pas du tout
                    break
            else:
                pire = 0
                if (bouge > 0) != (e > 0):              # l'interrupteur tourne dans l'autre sens
                    sens = {1: sens[-1], -1: sens[1]}
    if getattr(r, "boite", None) is not None:
        r.boite.ecrire("hsel_non_regle", cible=cible, hsel=(lire_hsi(r.export) or {}).get("hsel"))
    raise Echec("Je n'arrive pas à régler le cap sélecté. Règle-le avec l'interrupteur HDG.")


def pilote_cap_actuel(r):
    r.nav.cap_demande = None
    pilote_cap(r)


def pilote_cap(r):
    """Pilote auto sur un cap : r.nav.cap_demande = None (cap actuel), un nombre,
    ou ("wpt", numero). Regle le repere de cap puis engage HSEL."""
    if r.a.au_sol:
        raise Echec("Négatif. Pilote automatique en vol uniquement.")
    demande = getattr(r.nav, "cap_demande", None)
    if demande is None:
        cap = cap_magnetique(r)
        if cap is None:
            pos = getattr(r.export, "position", None) if r.export is not None else None
            if not pos or pos.get("cap") is None:
                raise Echec("Cap de l'avion inconnu.")
            cap = round(math.degrees(pos["cap"])) % 360
        quoi = "cap actuel"
    elif isinstance(demande, (tuple, list)):
        p = r.nav.par_numero(int(demande[1]))
        if p is None:
            raise Echec(f"Waypoint {demande[1]} absent du plan.")
        cap = cap_vers(r, p.lat, p.lon)
        quoi = f"vers {p.nom or 'le waypoint ' + str(p.num)}"
    else:
        cap = int(demande) % 360
        quoi = "demandé"
    regler_hsel(r, cap)
    _pilote("HSEL", f"Pilote auto, cap {cap:03d}, {quoi}.")(r)


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


def _tacan_pilote(r):
    regler_tacan(r, pilote=True)


def link16(r):
    """Link 16 (le datalink qui montre les ailiers) : D/L appuye DEUX fois sur l'UFC
    (un seul appui = Link 4), puis ON/OFF maintenu (fiche Datalink du kneeboard)."""
    _appuyer(r, "UFC_DL")
    r.attendre(0.5)
    _appuyer(r, "UFC_DL")
    r.attendre(0.6)
    avant = _bloc_note(r.b)
    if "ON" in avant.replace(" ", "") and not _eteint(avant):
        ok = True
    else:
        _appuyer(r, "UFC_ONOFF", 1.5)                  # appui maintenu
        r.attendre(0.6)
        apres = _bloc_note(r.b)
        ok = "ON" in apres.replace(" ", "") and not _eteint(apres)
        if getattr(r, "boite", None) is not None:
            r.boite.ecrire("link16", avant=avant, apres=apres, ok=ok,
                           options=options_ufc(r.b))
    _appuyer(r, "UFC_CLR")
    return ok


def systemes_nav(r):
    """IFF et Link 16 sur ON."""
    rates = []
    if not ufc_allumer(r, "UFC_IFF", "IFF"):
        rates.append("IFF")
    if not link16(r):
        rates.append("Link 16")
    if rates:
        r.non_confirmes.extend(rates)


PROCEDURES_NAV = {
    "wpt_plus": ("Waypoint suivant", _proc(wpt_plus, "waypoint suivant")),
    "wpt_moins": ("Waypoint précédent", _proc(wpt_moins, "waypoint précédent")),
    "wpt_passe": ("Séquence waypoint", _proc(_sequence, "séquence waypoint")),
    "retour_base": ("Retour base", _proc(retour_base, "retour base")),
    "envoyer_plan": ("Envoi du plan de vol", _proc(envoyer_plan, "envoi du plan de vol")),
    "lire_avion": ("Lecture des waypoints", _proc(lire_avion, "lecture des waypoints")),
    "aller_wpt": ("Aller au waypoint", _proc(aller_wpt, "aller au waypoint")),
    "tacan": ("TACAN", _proc(regler_tacan, "TACAN")),
    "tacan_ap": ("TACAN et pilote auto", _proc(_tacan_pilote, "TACAN et pilote auto")),
    "ap_balt": ("Pilote auto altitude", _proc(_pilote("BALT", "Pilote auto, maintien d'altitude."),
                                               "pilote auto BALT")),
    "ap_cap_actuel": ("Pilote auto, garde le cap actuel", _proc(pilote_cap_actuel, "pilote auto cap actuel")),
    "ap_cap": ("Pilote auto sur un cap", _proc(pilote_cap, "pilote auto cap")),
    "ap_hsel": ("Pilote auto cap", _proc(_pilote("HSEL", "Pilote auto, maintien du cap sélecté."),
                                          "pilote auto HSEL")),
    "ap_cpl": ("Pilote auto couplé", _proc(_pilote("CPL", "Pilote auto couplé sur la navigation."),
                                           "pilote auto CPL")),
    "ap_off": ("Pilote auto off", _proc(pilote_off, "pilote auto off")),
    "iff_dl": ("IFF et D/L", _proc(systemes_nav, "IFF et D/L")),
}
