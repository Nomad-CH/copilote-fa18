"""Reception des donnees envoyees par CopiloteExport.lua (RWR, ecrans, emport).

Complete DCS-BIOS : DCS-BIOS donne les interrupteurs et les voyants, ce lien
donne ce qui est affiche sur les ecrans et l'emport reel.
"""
import collections
import json
import re
import socket
import threading
import time

# Symboles du RWR ALR-67 du Hornet -> (nom annonce, contre-mesure conseillee)
# d'apres la planche "RWR THREATS" du Kneeboard Suite de DimOn envoyee par Lucas.
# Contre-mesure : "C" paillettes, "F" leurres IR, "E" evasive, None = pas de conseil.
# Un symbole inconnu est annonce tel quel et note dans la boite noire.
MENACES = {
    # --- avions
    "14": ("F-14", None), "16": ("F-16", None), "18": ("F/A-18", None),
    "21": ("MiG-21", None), "23": ("MiG-23", None), "25": ("MiG-25", None),
    "29": ("MiG-29 ou Flanker", None), "30": ("Su-30", None), "31": ("MiG-31", None),
    "34": ("Su-34", None), "37": ("Viggen", None), "50": ("AWACS", None),
    "64": ("Apache", None), "E2": ("Hawkeye", None), "E3": ("AWACS", None),
    "F1": ("Mirage F1", None), "F2": ("Tornado", None), "F4": ("F-4", None),
    "F5": ("F-5", None), "JF": ("JF-17", None), "M2": ("Mirage 2000", None),
    # --- radars de veille
    "S": ("radar de veille", None), "BB": ("Big Bird, SA-10", None),
    "CS": ("Clam Shell, SA-10", None), "DE": ("Dog Ear", None), "FC": ("Fire Can", None),
    "HQ": ("radar HQ-7", None), "SD": ("Snow Drift, SA-11", None), "TS": ("Tin Shield", None),
    # --- sol-air
    "2": ("SA-2", "C"), "3": ("SA-3", "C"), "5": ("SA-5", "C"), "6": ("SA-6", "C"),
    "7": ("HQ-7", "E"), "8": ("SA-8", "C"), "10": ("SA-10", "C"), "11": ("SA-11", "C"),
    "13": ("SA-13", "F"), "22": ("Pantsir", "C"), "A": ("artillerie", "E"),
    "CR": ("Phalanx", "E"), "HK": ("Hawk", "C"), "IT": ("IRIS-T", "F"),
    "NS": ("NASAMS", "C"), "P": ("Patriot", "C"), "RO": ("Roland", "C"),
    "RP": ("Rapier", "E"), "RT": ("Rapier", "E"),
    # --- navires
    "40": ("Tarawa", "F"), "49": ("frégate Perry", "C"), "AE": ("Arleigh Burke", "C"),
    "FR": ("Forrestal", "C"), "HN": ("destroyer 052C", "C"), "HP": ("corvette Grisha", "C"),
    "IV": ("Invincible", "C"), "LC": ("La Combattante", "E"), "MR": ("destroyer 052B", "C"),
    "PS": ("navire 071", "E"), "SC": ("Ropucha", "E"), "SS": ("porte-avions", "C"),
    "SW": ("Kuznetsov", "C"), "T2": ("Moskva", "C"), "TP": ("frégate Condell", "E"),
    "U": ("menace inconnue", None),
}
# Symboles partages entre un avion et un SAM : on tranche avec le voyant SAM
AMBIGUS = {"15": (("F-15", None), ("SA-15", "C")), "19": (("MiG-19", None), ("SA-19", "E"))}

CONSEIL = {"C": "Paillettes !", "F": "Leurres !", "E": "Évasive !"}

# compatibilite : symbole -> nom
SYMBOLES = {s: n for s, (n, _c) in MENACES.items()}
SYMBOLES.update({s: f"{a[0]} ou {b[0]}" for s, (a, b) in AMBIGUS.items()})


def menace(symbole, voyant_sam=None):
    """(nom, conseil) pour un symbole RWR. voyant_sam : voyant SAM allume ?"""
    if symbole in AMBIGUS:
        avion, sam = AMBIGUS[symbole]
        if voyant_sam is True:
            return sam
        if voyant_sam is False:
            return avion
        return (f"{avion[0]} ou {sam[0]}", None)
    return MENACES.get(symbole, (f"menace {symbole}", None))


# Stations du Hornet (1 = saumon gauche ... 9 = saumon droit)
NOMS_STATIONS = {1: "SAUMON G", 2: "EXT G", 3: "INT G", 4: "FUS G", 5: "CENTRE",
                 6: "FUS D", 7: "INT D", 8: "EXT D", 9: "SAUMON D"}


def nom_menace(symbole, voyant_sam=None):
    return menace(symbole, voyant_sam)[0]


def elements(txt):
    """Texte d'un ecran -> liste de (nom, valeur)."""
    out = []
    for bloc in txt.split("\x1f"):
        lignes = [l for l in bloc.split("\n") if l.strip() not in ("children are {", "}")]
        if not lignes or not lignes[0].strip():
            continue
        out.append((lignes[0].strip(), "\n".join(l for l in lignes[1:] if l.strip()).strip()))
    return out


def symboles_rwr(txt):
    return [v for n, v in elements(txt) if n.startswith("RWR_ThreatSymbol") and v]


# Reconnaissance de la page affichee sur un DDI ou l'AMPCD, d'apres les
# noms d'elements vus pendant tes vols. L'ordre compte (la page SA contient
# aussi une rose HSI, la page radar une superposition EW).
_PAGES = [
    ("STORES", re.compile(r"^STA\d_Label_TYPE$|^Master_Arm_Status$")),
    ("SA", re.compile(r"^SA_AIR_DEFENSE|^SA_Tracks|^SA_EW_Root|^SA_MEZ|^SA_FLOT")),
    ("RADAR", re.compile(r"^RDR_AA|^Radar_border$|^TWS_Tracks")),
    ("FLIR", re.compile(r"^MPD_AFLIR")),
    ("HSI", re.compile(r"^HSI_Main_Root$")),
]
_MENU = re.compile(r"^(ATTK|FCS|BIT|ENG|FUEL|STORES|FLIR|SA|HSI|RDR)_\d__id")


def page_ecran(txt):
    if not txt:
        return ""
    noms = [n for n, _v in elements(txt)]
    for page, motif in _PAGES:
        if any(motif.search(n) for n in noms):
            return page
    if sum(bool(_MENU.search(n)) for n in noms) >= 3:
        return "MENU"
    return "AUTRE"


class ExportDCS:
    def __init__(self, port=7790, port_ordres=7791):
        self.port = port
        self.port_ordres = port_ordres
        self._envoi = None
        self.dernier = 0.0
        self.erreur = ""
        self.ecrans = {}            # numero -> texte
        self.emport = None          # dict envoye par le Lua
        self.leurres = None         # (paillettes, leurres IR)
        self.position = None        # avion : lat, lon, alt (m), cap (rad)
        self.vue = None             # centre de la vue / carte F10 : lat, lon, sol (m), haut (m)
        self.args = {}              # position de quelques commandes du cockpit (argument DCS -> valeur)
        self.temps_modele = None    # horloge de la mission (repart de zero a chaque mission)
        self.sols = {}              # reponses aux demandes d'altitude du sol
        self._n_sol = 0
        self._rwr = collections.deque(maxlen=40)   # (heure, tuple de symboles)
        self._verrou = threading.Lock()
        self._stop = False

    # -------------------------------------------------------------- ordres
    def clic(self, appareil, commande, valeur):
        """Clic sur une commande du cockpit, par le lien (version 3 et plus)."""
        if self._envoi is None:
            self._envoi = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        msg = f"clic {int(appareil)} {int(commande)} {float(valeur):g}"
        self._envoi.sendto(msg.encode(), ("127.0.0.1", self.port_ordres))

    def demander_sol(self, lat, lon):
        """Altitude du sol (m) d'un point : la reponse arrive dans self.sols[n]."""
        if self._envoi is None:
            self._envoi = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._n_sol += 1
        self._envoi.sendto(f"sol {self._n_sol} {lat:.7f} {lon:.7f}".encode(),
                           ("127.0.0.1", self.port_ordres))
        return self._n_sol

    def arg(self, numero):
        return self.args.get(numero)

    @property
    def ordres_possibles(self):
        """Le lien installe sait-il recevoir des clics ? (il envoie alors 'args')"""
        return self.vivant and bool(self.args)

    # -------------------------------------------------------------- etat
    @property
    def vivant(self):
        return time.time() - self.dernier < 2.0

    def menaces(self):
        """{symbole: 'presente' | 'clignote'} pour les 2 dernieres secondes.

        Un symbole qui apparait et disparait plusieurs fois en 1,5 s clignote :
        c'est ce qu'a fait le SA-8 pendant ton deuxieme vol.
        """
        maintenant = time.time()
        with self._verrou:
            hist = [(t, s) for t, s in self._rwr if maintenant - t <= 2.0]
        if not hist:
            return {}
        vus = set().union(*(set(s) for _t, s in hist))
        recent = [(t, s) for t, s in hist if maintenant - t <= 1.5]
        out = {}
        for sym in vus:
            presences = [sym in s for _t, s in recent]
            bascules = sum(1 for a, b in zip(presences, presences[1:]) if a != b)
            if bascules >= 2:
                out[sym] = "clignote"
            elif presences and presences[-1]:
                out[sym] = "presente"
            elif any(sym in s for t, s in hist if maintenant - t <= 0.6):
                out[sym] = "presente"
        return out

    def page(self, numero):
        return page_ecran(self.ecrans.get(numero, ""))

    def stations(self):
        """{numero de station: (nom de l'arme, nombre)}"""
        e = self.emport or {}
        out = {}
        for s in e.get("stations", []) or []:
            try:
                out[int(s.get("st", 0))] = (s.get("nom") or "", int(s.get("n") or 0))
            except (TypeError, ValueError):
                continue
        return out

    # --------------------------------------------------------- reception
    def demarrer(self):
        threading.Thread(target=self._boucle, daemon=True).start()

    def arreter(self):
        self._stop = True

    def traiter(self, paquet):
        k = paquet.get("k")
        maintenant = time.time()
        if k == "etat":
            with self._verrou:
                self._rwr.append((maintenant, tuple(symboles_rwr(paquet.get("rwr") or ""))))
            self.emport = paquet.get("emport")
            l = paquet.get("leurres")
            self.leurres = tuple(int(x) for x in l) if l else None
            self.ecrans[7] = paquet.get("rwr") or ""
            self.position = paquet.get("pos") or None
            if isinstance(paquet.get("t"), (int, float)):
                self.temps_modele = float(paquet["t"])
            self.vue = paquet.get("vue") or None
            if isinstance(paquet.get("sols"), dict):
                for k, v in paquet["sols"].items():
                    if isinstance(v, (int, float)):
                        self.sols[int(k)] = float(v)
            if isinstance(paquet.get("args"), dict):
                self.args = {int(k): float(v) for k, v in paquet["args"].items()}
            self.dernier = maintenant
        elif k == "ecran":
            try:
                self.ecrans[int(paquet.get("i"))] = paquet.get("txt") or ""
            except (TypeError, ValueError):
                pass
            self.dernier = maintenant
        elif k == "fin":
            self.dernier = 0.0

    def _boucle(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(("127.0.0.1", self.port))
        except OSError as ex:
            self.erreur = f"port {self.port} occupé ({ex})"
            return
        s.settimeout(1.0)
        while not self._stop:
            try:
                donnees, _ = s.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                continue
            try:
                self.traiter(json.loads(donnees.decode("utf-8", "replace")))
            except (ValueError, AttributeError):
                continue
        s.close()
