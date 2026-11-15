"""Procedures du F/A-18C executees entierement par le copilote.

Chaque procedure est une liste d'etapes. Pour modifier une procedure, il
suffit d'ajouter, retirer ou deplacer des lignes dans PROCEDURES plus bas.

Etapes disponibles :
  Regle(ident, position)       place un interrupteur (et verifie qu'il a bougé)
  Appui(ident, duree)          appuie sur un bouton
  Attend(condition, ...)       attend qu'une condition soit vraie
  Pause(secondes)
  Dit(texte)                   message du copilote (ecran + voix)
  Touche(nom_config)           raccourci clavier DCS (manettes des gaz)
  Exige(condition, message)    abandonne si la condition est fausse
  Si(condition, [etapes])      etapes executees seulement si condition vraie
  Appelle(fonction)            code libre
"""
import random
import threading
import time

from . import clavier
from .avion import POS, nom_position


class Abandon(Exception):
    pass


# ------------------------------------------------------------------ etapes
class Regle:
    def __init__(self, ident, position, verifie=True, force=False):
        self.ident, self.position, self.verifie = ident, position, verifie
        # force : envoyer meme si DCS-BIOS dit que c'est deja en place (utile
        # pour les interrupteurs dont la position est mal relue)
        self.force = force

    def valeur(self):
        if isinstance(self.position, str):
            return POS[self.ident][self.position]
        return self.position

    def texte(self):
        p = self.position if isinstance(self.position, str) else nom_position(self.ident, self.position)
        return f"{self.ident} > {p}"

    def run(self, r):
        cible = self.valeur()
        if not r.b.connait(self.ident):
            r.non_confirmes.append(self.ident + " (inconnu de DCS-BIOS)")
            return
        if r.b.lire(self.ident) == cible and not self.force:
            return
        r.b.envoyer(self.ident, cible)
        r.attendre(0.35)
        if not self.verifie or self.ident not in r.b.sorties:
            return
        fin = r.horloge() + 1.5
        while r.horloge() < fin:
            lu = r.b.lire(self.ident)
            analogique = r.b.sorties[self.ident].get("max_value") == 65535
            if lu == cible or (analogique and abs(lu - cible) < 1500):
                return
            r.attendre(0.1)
        r.non_confirmes.append(self.texte())


class Appui:
    def __init__(self, ident, duree=0.2):
        self.ident, self.duree = ident, duree

    def texte(self):
        return f"{self.ident} (appui)"

    def run(self, r):
        r.b.envoyer(self.ident, 1)
        r.attendre(self.duree)
        r.b.envoyer(self.ident, 0)
        if self.ident == "RWR_POWER_BTN":
            r.a.rwr_appui = time.time()
        r.attendre(0.25)


class Attend:
    def __init__(self, condition, delai, quoi, aide=None, bloquant=True):
        self.condition, self.delai, self.quoi = condition, delai, quoi
        self.aide, self.bloquant = aide, bloquant

    def texte(self):
        return "attente : " + self.quoi

    def run(self, r):
        debut = r.horloge()
        aide_donnee = False
        while not self.condition(r.a):
            ecoule = r.horloge() - debut
            if self.aide and not aide_donnee and ecoule > min(8, self.delai / 2):
                r.dire(self.aide)
                aide_donnee = True
            if ecoule > self.delai:
                if self.bloquant:
                    raise Abandon(f"Pas obtenu : {self.quoi}")
                r.non_confirmes.append(self.quoi)
                return
            r.attendre(0.2)


class Pause:
    def __init__(self, secondes):
        self.secondes = secondes

    def texte(self):
        return "pause"

    def run(self, r):
        r.attendre(self.secondes)


class Dit:
    """Message du copilote. Plusieurs variantes : il en choisit une au hasard."""

    def __init__(self, *messages):
        self.messages = messages
        self.message = messages[0]

    def texte(self):
        return self.message

    def run(self, r):
        r.dire(random.choice(self.messages))


class Touche:
    """Raccourci clavier DCS (manettes des gaz). Si une condition de reussite
    est donnee, on verifie qu'elle arrive et on reessaie jusqu'a 3 fois."""

    def __init__(self, nom, aide, reussite=None, delai=6.0):
        self.nom, self.aide = nom, aide
        self.reussite, self.delai = reussite, delai

    def texte(self):
        return "clavier : " + self.nom

    def run(self, r):
        combo = r.cfg.get("touches", {}).get(self.nom, "")
        if not (r.cfg.get("clavier_auto", True) and combo):
            r.dire(self.aide)
            return
        for essai in range(3):
            envoye = clavier.combinaison(combo)
            if not envoye:
                break
            if self.reussite is None:
                return
            fin = r.horloge() + self.delai
            while r.horloge() < fin:
                if self.reussite(r.a):
                    return
                r.attendre(0.2)
            if getattr(r, "boite", None) is not None:
                r.boite.ecrire("raccourci_sans_effet", raccourci=combo, commande=self.nom,
                               essai=essai + 1, **clavier.dernier_essai)
        r.dire(self.aide)


class Exige:
    def __init__(self, condition, message, garde_sol_vol=False):
        self.condition, self.message = condition, message
        self.garde_sol_vol = garde_sol_vol

    def texte(self):
        return "verification"

    def run(self, r):
        if self.garde_sol_vol and not r.cfg.get("gardes_sol_vol", True):
            return
        if not self.condition(r.a):
            raise Abandon(self.message)


class Si:
    def __init__(self, condition, etapes):
        self.condition, self.etapes = condition, etapes

    def texte(self):
        return "condition"

    def run(self, r):
        if self.condition(r.a):
            for e in self.etapes:
                r.executer(e)


class Appelle:
    def __init__(self, fonction, quoi="action"):
        self.fonction, self.quoi = fonction, quoi

    def texte(self):
        return self.quoi

    def run(self, r):
        self.fonction(r)


# ---------------------------------------------------------- frein de parking
def manoeuvrer_frein(b, a, attendre, serrer, boite=None):
    """Poignee de frein du Hornet. Releve pendant tes vols du 15 novembre :
    serre = tiree (PULL 1) et tournee (ROTATE 2) ; relache = PULL 0.
    Au relachement, DCS met plusieurs secondes a bouger la poignee : on attend.
    Au serrage, tirer ne marche pas tant que la poignee n'est pas tournee :
    on tourne d'abord, puis on tire (et on essaie aussi la bascule TOGGLE).
    Chaque etape est notee dans la boite noire pour la suite."""
    trace = []

    def note(etape):
        trace.append((etape, b.lire("EMERGENCY_PARKING_BRAKE_PULL"),
                      b.lire("EMERGENCY_PARKING_BRAKE_ROTATE")))

    def attendre_etat(delai):
        fin = time.time() + delai
        while time.time() < fin:
            if a.frein_parking == serrer:
                return True
            attendre(0.25)
        return a.frein_parking == serrer

    note("debut")
    if a.frein_parking == serrer:
        return True
    if serrer:
        essais = [("ROTATE", 2), ("PULL", 1), ("PULL", "TOGGLE"), ("ROTATE", 2)]
    else:
        essais = [("ROTATE", 1), ("PULL", 0), ("PULL", "TOGGLE")]
    ok = False
    for organe, valeur in essais:
        ident = "EMERGENCY_PARKING_BRAKE_" + organe
        if organe == "PULL" and valeur != "TOGGLE" and b.lire(ident) == valeur:
            continue
        b.envoyer(ident, valeur)
        ok = attendre_etat(2.5)
        note(f"{organe} {valeur}")
        if ok:
            break
    if not ok:
        ok = attendre_etat(3)
        note("fin")
    if boite is not None:
        boite.ecrire("frein_parking", serrer=serrer, reussi=ok, trace=trace)
    return ok


def _serrer_frein(r):
    from . import cockpit
    ok = cockpit.manoeuvrer_frein(r.export, r.cfg, getattr(r, "boite", None), True)
    if ok is None:     # lien DCS trop ancien : ancienne methode
        ok = manoeuvrer_frein(r.b, r.a, r.attendre, True, getattr(r, "boite", None))
    if not ok:
        r.non_confirmes.append("frein de parking")
        r.dire("Frein de parking à ta charge.")


# ---------------------------------------------------------- RWR
def allumer_rwr(r):
    """ALR-67 en marche : bouton POWER enfonce (relu par le lien version 3),
    affichage RWR lumineux. Verifie, et note tout dans la boite noire."""
    from . import cockpit
    x = r.export
    boite = getattr(r, "boite", None)
    # les deux generatrices en ligne avant d'allumer
    fin = r.horloge() + 40
    while r.horloge() < fin and r.a.rpm_g < 60:
        r.attendre(0.5)
    ok = cockpit.allumer_rwr(x, r.cfg, boite)
    if ok is None:            # lien ancien : appui DCS-BIOS
        r.b.envoyer("RWR_POWER_BTN", 1)
        r.attendre(0.4)
        r.b.envoyer("RWR_POWER_BTN", 0)
        ok = True
    r.a.rwr_appui = time.time()
    r.a.rwr_etat = bool(ok)
    if x is not None and x.arg(cockpit.ARG_RWR_INTENSITE) is not None \
            and x.arg(cockpit.ARG_RWR_INTENSITE) < 0.3:
        r.b.envoyer("RWR_RWR_INTESITY", 52000)
    if boite is not None and x is not None:
        boite.ecrire("rwr_demarrage", ok=ok, args={n: x.arg(n) for n in (276, 277, 216)},
                     ecran=(x.ecrans.get(7) or "")[:500])
    if not ok:
        r.non_confirmes.append("RWR")
        r.dire("RWR non confirmé. Vérifie-le.")


def _iff_dl(r):
    from .navigation import systemes_nav
    systemes_nav(r)


def _rwr_si_besoin(r):
    from . import cockpit
    etat = cockpit.rwr_allume(r.export, r.b)
    if etat is False or (etat is None and r.a.rwr_etat is not True):
        allumer_rwr(r)


def _modes_off(r):
    """Fence out : sort des modes maitres A/A et A/G (retour NAV)."""
    for mode in ("MASTER_MODE_AA", "MASTER_MODE_AG"):
        if r.a.allume(mode + "_LT"):
            r.b.envoyer(mode, 1)
            r.attendre(0.25)
            r.b.envoyer(mode, 0)
            r.attendre(0.5)


# ---------------------------------------------------------- actions libres
def _regler_bingo(r):
    """Monte le BINGO de l'IFEI jusqu'a la valeur de config (0 = ne rien faire)."""
    cible = int(r.cfg.get("bingo_lbs", 0) or 0)
    if cible <= 0:
        return
    for _ in range(120):
        actuel = r.a.bingo
        if actuel is None:
            r.non_confirmes.append("BINGO (IFEI illisible)")
            return
        if actuel >= cible:
            return
        r.b.envoyer("IFEI_UP_BTN", 1)
        r.attendre(0.08)
        r.b.envoyer("IFEI_UP_BTN", 0)
        r.attendre(0.12)
    r.non_confirmes.append("BINGO")


def _fermer_verriere(r):
    if r.a.verriere_fermee:
        return
    r.b.envoyer("CANOPY_SW", POS["CANOPY_SW"]["CLOSE"])
    fin = r.horloge() + 15
    try:
        while not r.a.verriere_fermee and r.horloge() < fin:
            r.attendre(0.2)
    finally:
        r.b.envoyer("CANOPY_SW", POS["CANOPY_SW"]["HOLD"])
    if not r.a.verriere_fermee:
        r.non_confirmes.append("fermeture verriere")


def _alignement_rapide(r):
    """Encadre STD HDG sur la page HSI : alignement en ~90 s au lieu de ~8 min.
    Le bouton est verifie (l'option s'encadre ou le chrono repart) et retenu."""
    from . import alignement
    from .chemins import sauver_config
    if not r.cfg.get("alignement_rapide", True) or r.b.lire("INS_SW") not in (1, 2):
        return
    info = None
    fin = r.horloge() + 45
    while r.horloge() < fin:
        info = alignement.lire(r.export)
        if info and info["qual"] is not None:
            break
        r.attendre(0.5)
    if not info or info["qual"] is None:
        r.non_confirmes.append("alignement rapide (page HSI introuvable)")
        return
    if info["std_hdg_encadre"]:
        return
    if not info["std_hdg_visible"]:
        r.non_confirmes.append("STD HDG absent de la page HSI")
        return
    connu = r.cfg.get("pb_std_hdg")
    candidats = [connu] if connu else list(alignement.CANDIDATS_STD_HDG)
    for pb in candidats:
        avant = alignement.lire(r.export) or info
        bouton = f"{alignement.BOUTONS[avant['ecran']]}{pb:02d}"
        r.b.envoyer(bouton, 1)
        r.attendre(0.2)
        r.b.envoyer(bouton, 0)
        limite = r.horloge() + 3
        while r.horloge() < limite:
            r.attendre(0.5)
            apres = alignement.lire(r.export)
            if apres is None:
                # la page a change : mauvais bouton, on s'arrete la
                if getattr(r, "boite", None) is not None:
                    r.boite.ecrire("std_hdg_echec", bouton=bouton, raison="page quittée")
                r.dire("Alignement rapide impossible. STD HDG à ta charge.")
                return
            relance = (apres["temps"] is not None and avant["temps"] is not None
                       and apres["temps"] + 5 < avant["temps"])
            if apres["std_hdg_encadre"] or relance:
                if r.cfg.get("pb_std_hdg") != pb:
                    r.cfg["pb_std_hdg"] = pb
                    try:
                        sauver_config(r.cfg)
                    except OSError:
                        pass
                r.dire("Alignement rapide engagé.")
                return
        if getattr(r, "boite", None) is not None:
            r.boite.ecrire("std_hdg_sans_effet", bouton=bouton)
    r.dire("Alignement rapide impossible. STD HDG à ta charge.")


def _hmd(r):
    if r.cfg.get("casque_hmd", True):
        r.b.envoyer("HMD_OFF_BRT", 65535)


# ---------------------------------------------------- blocs reutilisables
# Feux exterieurs. DCS-BIOS relit mal l'interrupteur de la manette (il le croit
# toujours sur ON) : on l'envoie donc a chaque fois. Les feux de position et
# de formation ont aussi leur propre variateur, a zero apres un demarrage a froid.
FEUX_ON = [
    Regle("THROTTLE_EXT_L_SW", 1, verifie=False, force=True),
    Regle("POSITION_DIMMER", 65535, verifie=False),
    Regle("FORMATION_DIMMER", 32768, verifie=False),
    Regle("STROBE_SW", "BRT"),
]
FEUX_OFF = [
    Regle("THROTTLE_EXT_L_SW", 0, verifie=False, force=True),
    Regle("STROBE_SW", "OFF"),
]

AU_SOL = Exige(lambda a: a.au_sol, "Négatif. Procédure sol uniquement.", True)
EN_VOL = Exige(lambda a: not a.au_sol, "Négatif. Procédure vol uniquement.", True)

DEPLIER_AILES = Si(lambda a: a.ailes_repliees, [
    Dit("Ailes repliées. Déploiement."),
    Regle("WING_FOLD_PULL", 1),
    Regle("WING_FOLD_ROTATE", "SPREAD"),
    Attend(lambda a: not a.ailes_repliees, 25, "ailes dépliées", bloquant=False),
    Regle("WING_FOLD_PULL", 0),
])


def _demarrage(porte_avions):
    return [
        AU_SOL,
        Exige(lambda a: a.rpm_g < 10 and a.rpm_d < 10,
              "Négatif. Moteurs déjà en route."),
        Dit("Séquence de démarrage engagée."),
        Regle("BATTERY_SW", "ON"),
        Regle("L_GEN_SW", 1),
        Regle("R_GEN_SW", 1),
        Pause(1.0),
        Regle("APU_CONTROL_SW", 1),
        Attend(lambda a: a.allume("APU_READY_LT"), 60, "APU prêt"),
        # --- moteur droit
        Dit("APU prêt. Démarrage moteur droit."),
        Regle("ENGINE_CRANK_SW", "DROITE", verifie=False),
        Attend(lambda a: a.rpm_d >= 18, 45, "moteur droit à 18 %"),
        Attend(lambda a: a.rpm_d >= 22, 15, "moteur droit à 22 %", bloquant=False),
        Touche("gaz_droit_idle", "Manette droite sur IDLE, à toi.",
              reussite=lambda a: a.rpm_d >= 30, delai=6),
        Attend(lambda a: a.rpm_d >= 60, 90, "moteur droit au ralenti"),
        # --- ecrans et centrale : l'alignement tourne pendant le moteur gauche
        Regle("LEFT_DDI_BRT_SELECT", "DAY"),
        Regle("RIGHT_DDI_BRT_SELECT", "DAY"),
        Regle("AMPCD_BRT_CTL", 65535),
        Regle("HUD_SYM_BRT", 65535),
        Regle("INS_SW", "CV" if porte_avions else "GND"),
        Appelle(_alignement_rapide, "alignement rapide STD HDG"),
        # --- moteur gauche, et les systemes pendant qu'il monte en regime
        Dit("Moteur droit stabilisé. Démarrage moteur gauche."),
        Regle("ENGINE_CRANK_SW", "GAUCHE", verifie=False),
        Appelle(_fermer_verriere, "fermeture verrière"),
        Regle("RADAR_SW", "OPR"),
        Regle("OBOGS_SW", 1),
        Regle("FLIR_SW", "STBY"),
        Regle("CMSD_DISPENSE_SW", "ON"),
        Regle("ECM_MODE_SW", "STBY"),
        Regle("UFC_COMM1_VOL", 45000, verifie=False),
        Regle("UFC_COMM2_VOL", 45000, verifie=False),
        Attend(lambda a: a.rpm_g >= 22, 45, "moteur gauche à 22 %", bloquant=False),
        Touche("gaz_gauche_idle", "Manette gauche sur IDLE, à toi.",
              reussite=lambda a: a.rpm_g >= 30, delai=6),
        Appelle(allumer_rwr, "RWR"),
        Appelle(_iff_dl, "IFF et D/L"),
        Attend(lambda a: a.rpm_g >= 60, 90, "moteur gauche au ralenti"),
        Appelle(_hmd, "casque HMD"),
        Appui("FCS_RESET_BTN", 0.4),
        Regle("FLAP_SW", "HALF"),
        Appui("TO_TRIM_BTN", 2.5),
        Regle("HOOK_BYPASS_SW", "CARRIER" if porte_avions else "FIELD"),
        Regle("ANTI_SKID_SW", 0 if porte_avions else 1),
        *FEUX_ON,
        Regle("EJECTION_SEAT_ARMED", "ARMED"),
        Appelle(_regler_bingo, "réglage BINGO"),
        Dit("Deux moteurs au ralenti. Défenses en ligne : RWR, leurres, brouilleur en veille. "
            "IFF et liaison de données en marche. Passage IFA automatique à QUAL OK. "
            "Test FCS à ta charge."),
    ]


ARRET = [
    AU_SOL,
    Exige(lambda a: a.immobile, "Négatif. Avion en mouvement."),
    Dit("Séquence d'arrêt engagée."),
    Appelle(_serrer_frein, "frein de parking"),
    Regle("MASTER_ARM_SW", "SAFE"),
    Regle("EJECTION_SEAT_ARMED", "SAFE"),
    Regle("FLAP_SW", "AUTO"),
    Regle("LDG_TAXI_SW", 0),
    *FEUX_OFF,
    Regle("INS_SW", "OFF"),
    Regle("RADAR_SW", "OFF"),
    Regle("FLIR_SW", "OFF"),
    Regle("CMSD_DISPENSE_SW", "OFF"),
    Regle("ECM_MODE_SW", "OFF"),
    Regle("OBOGS_SW", 0),
    Regle("CANOPY_SW", "OPEN", verifie=False),
    Touche("gaz_gauche_off", "Manette gauche sur OFF, à toi.",
           reussite=lambda a: a.rpm_g < 50, delai=8),
    Touche("gaz_droit_off", "Manette droite sur OFF, à toi.",
           reussite=lambda a: a.rpm_d < 50, delai=8),
    Attend(lambda a: a.rpm_g < 10 and a.rpm_d < 10, 60, "moteurs arrêtés", bloquant=False),
    Regle("LEFT_DDI_BRT_SELECT", "OFF"),
    Regle("RIGHT_DDI_BRT_SELECT", "OFF"),
    Regle("AMPCD_BRT_CTL", 0),
    Regle("HUD_SYM_BRT", 0),
    Regle("BATTERY_SW", "OFF"),
    Dit("Avion éteint. Fin de mission."),
]

AVANT_DECOLLAGE = [
    AU_SOL,
    DEPLIER_AILES,
    Appelle(_fermer_verriere, "fermeture verrière"),
    Regle("FLAP_SW", "HALF"),
    Appui("TO_TRIM_BTN", 2.5),
    Regle("PROBE_SW", "RETRACT"),
    Regle("HOOK_LEVER", "UP"),
    Regle("LAUNCH_BAR_SW", "RETRACT"),
    Regle("HOOK_BYPASS_SW", "FIELD"),
    Regle("ANTI_SKID_SW", 1),
    Regle("EJECTION_SEAT_ARMED", "ARMED"),
    Regle("MASTER_ARM_SW", "SAFE"),
    Regle("LDG_TAXI_SW", 1),
    *FEUX_ON,
    Dit("Configuration décollage terminée. Frein de parking à ta charge."),
]

CATAPULTE = [
    AU_SOL,
    DEPLIER_AILES,
    Appelle(_fermer_verriere, "fermeture verrière"),
    Regle("FLAP_SW", "HALF"),
    Appui("TO_TRIM_BTN", 2.5),
    Regle("PROBE_SW", "RETRACT"),
    Regle("HOOK_LEVER", "UP"),
    Regle("HOOK_BYPASS_SW", "CARRIER"),
    Regle("ANTI_SKID_SW", 0),
    Regle("EJECTION_SEAT_ARMED", "ARMED"),
    Regle("MASTER_ARM_SW", "SAFE"),
    Regle("LDG_TAXI_SW", 0),
    Regle("LAUNCH_BAR_SW", "EXTEND"),
    Dit("Barre de catapultage sortie. Trim selon la masse, à ta charge."),
]

APRES_DECOLLAGE = [
    EN_VOL,
    Regle("GEAR_LEVER", "UP"),
    Regle("FLAP_SW", "AUTO"),
    Regle("LAUNCH_BAR_SW", "RETRACT"),
    Regle("LDG_TAXI_SW", 0),
    Attend(lambda a: not any(a.allume(i) for i in (
        "FLP_LG_NOSE_GEAR_LT", "FLP_LG_LEFT_GEAR_LT", "FLP_LG_RIGHT_GEAR_LT")),
        15, "train rentré", bloquant=False),
    Dit("Train rentré, volets auto."),
]

FENCE_IN = [
    Regle("MASTER_ARM_SW", "ARM"),
    Regle("RADAR_SW", "OPR"),
    Appelle(_rwr_si_besoin, "RWR"),
    Regle("CMSD_DISPENSE_SW", "ON"),
    Regle("ECM_MODE_SW", "REC"),
    Regle("IR_COOL_SW", "NORM"),
    *FEUX_OFF,
    Regle("LDG_TAXI_SW", 0),
    Dit("Fence in effectué. Master arm, feux éteints."),
]

FENCE_OUT = [
    Regle("MASTER_ARM_SW", "SAFE"),
    Appelle(_modes_off, "modes A/A et A/G"),
    Regle("LTD_R_SW", "SAFE"),
    Regle("ECM_MODE_SW", "STBY"),
    *FEUX_ON,
    Dit("Fence out effectué. Armement sur sécurité, mode NAV, feux allumés."),
]

_TROP_VITE = Exige(lambda a: a.vitesse <= 250,
                   "Négatif. Vitesse trop élevée pour le train : 250 nœuds maximum.")

ATTERRISSAGE = [
    EN_VOL, _TROP_VITE,
    Regle("MASTER_ARM_SW", "SAFE"),
    Regle("GEAR_LEVER", "DOWN"),
    Regle("FLAP_SW", "FULL"),
    Regle("HOOK_LEVER", "UP"),
    Regle("HOOK_BYPASS_SW", "FIELD"),
    Regle("ANTI_SKID_SW", 1),
    Regle("LDG_TAXI_SW", 1),
    Regle("PROBE_SW", "RETRACT"),
    Attend(lambda a: a.train_sorti, 20, "trois vertes", bloquant=False),
    Dit("Trois vertes, pleins volets. Configuration atterrissage."),
]

APPONTAGE = [
    EN_VOL, _TROP_VITE,
    Regle("MASTER_ARM_SW", "SAFE"),
    Regle("GEAR_LEVER", "DOWN"),
    Regle("FLAP_SW", "FULL"),
    Regle("HOOK_LEVER", "DOWN"),
    Regle("HOOK_BYPASS_SW", "CARRIER"),
    Regle("ANTI_SKID_SW", 0),
    Regle("LDG_TAXI_SW", 0),
    Regle("PROBE_SW", "RETRACT"),
    Attend(lambda a: a.train_sorti, 20, "trois vertes", bloquant=False),
    Dit("Trois vertes, pleins volets, crosse sortie. Configuration appontage."),
]

APRES_ATTERRISSAGE = [
    AU_SOL,
    Regle("FLAP_SW", "AUTO"),
    Regle("HOOK_LEVER", "UP"),
    Regle("LDG_TAXI_SW", 1),
    Regle("MASTER_ARM_SW", "SAFE"),
    Regle("CMSD_DISPENSE_SW", "OFF"),
    Regle("ECM_MODE_SW", "OFF"),
    Dit("Volets rentrés, crosse relevée. Configuration roulage."),
]

RAVITAILLEMENT = [
    EN_VOL,
    Regle("MASTER_ARM_SW", "SAFE"),
    Regle("PROBE_SW", "EXTEND"),
    *FEUX_ON,
    Dit("Perche sortie, armement sur sécurité. Prêt au ravitaillement."),
]

FIN_RAVITAILLEMENT = [
    Regle("PROBE_SW", "RETRACT"),
    Dit("Perche rentrée."),
]

# Checklist : une fois QUAL OK sur la page HSI, INS sur IFA (NAV si le GPS
# est restreint). On ne touche a rien si la centrale n'est pas en alignement.
INS_IFA = [
    Exige(lambda a: a.b.lire("INS_SW") in (POS["INS_SW"]["GND"], POS["INS_SW"]["CV"]),
          "Négatif. Centrale pas en alignement."),
    Regle("INS_SW", "IFA"),
    Dit("Centrale sur IFA."),
]

AIR_AIR = [
    Regle("MASTER_ARM_SW", "ARM"),
    Regle("RADAR_SW", "OPR"),
    Regle("IR_COOL_SW", "NORM"),
    Si(lambda a: not a.allume("MASTER_MODE_AA_LT"), [Appui("MASTER_MODE_AA")]),
    Regle("CMSD_DISPENSE_SW", "ON"),
    Dit("Mode air-air. Armement actif."),
]

AIR_SOL = [
    Regle("MASTER_ARM_SW", "ARM"),
    Si(lambda a: not a.allume("MASTER_MODE_AG_LT"), [Appui("MASTER_MODE_AG")]),
    Regle("FLIR_SW", "ON"),
    Regle("CMSD_DISPENSE_SW", "ON"),
    Dit("Mode air-sol. Armement actif. Laser sur sécurité."),
]

SECURITE = [
    Regle("LTD_R_SW", "SAFE"),
    Si(lambda a: a.allume("MASTER_MODE_AA_LT"), [Appui("MASTER_MODE_AA")]),
    Si(lambda a: a.allume("MASTER_MODE_AG_LT"), [Appui("MASTER_MODE_AG")]),
    Regle("MASTER_ARM_SW", "SAFE"),
    Dit("Armement sur sécurité."),
]

PROCEDURES = {
    "demarrage_terre": ("Démarrage terre", _demarrage(False)),
    "demarrage_pa": ("Démarrage porte-avions", _demarrage(True)),
    "ins_ifa": ("INS IFA", INS_IFA),
    "avant_decollage": ("Avant décollage", AVANT_DECOLLAGE),
    "catapulte": ("Catapulte", CATAPULTE),
    "apres_decollage": ("Après décollage", APRES_DECOLLAGE),
    "fence_in": ("Fence in", FENCE_IN),
    "fence_out": ("Fence out", FENCE_OUT),
    "ravitaillement": ("Ravitaillement", RAVITAILLEMENT),
    "fin_ravitaillement": ("Fin ravitaillement", FIN_RAVITAILLEMENT),
    "atterrissage": ("Atterrissage terre", ATTERRISSAGE),
    "appontage": ("Appontage", APPONTAGE),
    "apres_atterrissage": ("Après atterrissage", APRES_ATTERRISSAGE),
    "arret": ("Arrêt", ARRET),
    "air_air": ("Air-air", AIR_AIR),
    "air_sol": ("Air-sol", AIR_SOL),
    "securite": ("Sécurité armement", SECURITE),
}


# ------------------------------------------------------------------ moteur
class Executeur:
    """Execute une procedure a la fois, dans son propre fil."""

    def __init__(self, bios, avion, cfg, dire, export=None):
        self.b, self.a, self.cfg = bios, avion, cfg
        self.export = export
        self._dire = dire
        self.en_cours = None       # cle de la procedure en cours
        self.titre = ""
        self.etape = ""            # texte de l'etape en cours
        self.avancement = (0, 0)
        self.non_confirmes = []
        self._abandon = threading.Event()
        self._verrou = threading.Lock()
        self._pause_totale = 0.0

    def dire(self, texte, urgent=False):
        self._dire(texte, urgent)

    def horloge(self):
        """Temps qui s'arrete quand DCS est en pause."""
        return time.time() - self._pause_totale

    def attendre(self, secondes):
        if self._abandon.wait(secondes):
            raise Abandon("Procédure interrompue.")
        # DCS en pause (menu Echap) : on attend sans compter le temps
        debut_pause = None
        while self.b.en_pause:
            debut_pause = debut_pause or time.time()
            if self._abandon.wait(0.2):
                raise Abandon("Procédure interrompue.")
        if debut_pause:
            self._pause_totale += time.time() - debut_pause
        if not self.b.en_f18:
            raise Abandon("Liaison avec DCS perdue.")

    def executer(self, etape):
        self.etape = etape.texte()
        etape.run(self)

    def lancer(self, cle):
        with self._verrou:
            if self.en_cours:
                self.dire("Procédure déjà en cours.")
                return False
            if not self.b.en_f18:
                self.dire("Négatif. Pas de Hornet en ligne.")
                return False
            self.en_cours = cle
        self.titre, etapes = PROCEDURES[cle]
        self._abandon.clear()
        self.non_confirmes = []
        threading.Thread(target=self._run, args=(etapes,), daemon=True).start()
        return True

    def stop(self):
        if self.en_cours:
            self._abandon.set()

    def _run(self, etapes):
        try:
            for i, e in enumerate(etapes):
                self.avancement = (i + 1, len(etapes))
                if self._abandon.is_set():
                    raise Abandon("Procédure interrompue.")
                self.executer(e)
            if self.non_confirmes:
                n = len(self.non_confirmes)
                self.dire(f"{self.titre} terminé. {n} point"
                          f"{'s' if n > 1 else ''} à vérifier : "
                          + ", ".join(self.non_confirmes[:4]))
        except Abandon as ex:
            # relache les commandes maintenues
            self.b.envoyer("CANOPY_SW", POS["CANOPY_SW"]["HOLD"])
            self.dire(str(ex), urgent=True)
        except Exception as ex:  # ne jamais tuer le copilote
            if getattr(self, "boite", None) is not None:
                self.boite.erreur("procédure " + self.titre, ex)
            self.dire(f"Erreur dans la procédure : {ex}", urgent=True)
        finally:
            self.etape = ""
            self.en_cours = None


# Etape 2 : navigation (waypoints, carnet de points, TACAN, pilote automatique)
from .navigation import PROCEDURES_NAV  # noqa: E402
PROCEDURES.update(PROCEDURES_NAV)

# Etape JDAM
from .armement import PROCEDURES_ARMES  # noqa: E402
PROCEDURES.update(PROCEDURES_ARMES)
