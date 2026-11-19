"""Vue "pilote" de l'etat du F/A-18C : des noms lisibles au lieu d'adresses.

Les positions d'interrupteurs ci-dessous viennent des definitions DCS-BIOS
(valeur 0/1/2 = position basse/milieu/haute) recoupees avec les valeurs
du cockpit DCS.
"""

# Positions nommees, pour que les procedures restent lisibles.
POS = {
    "BATTERY_SW": {"ORIDE": 0, "OFF": 1, "ON": 2},
    "ENGINE_CRANK_SW": {"GAUCHE": 0, "OFF": 1, "DROITE": 2},
    "FLAP_SW": {"FULL": 0, "HALF": 1, "AUTO": 2},
    "PROBE_SW": {"EMERG": 0, "RETRACT": 1, "EXTEND": 2},
    "FLIR_SW": {"OFF": 0, "STBY": 1, "ON": 2},
    "STROBE_SW": {"DIM": 0, "OFF": 1, "BRT": 2},
    "CANOPY_SW": {"CLOSE": 0, "HOLD": 1, "OPEN": 2},
    "WING_FOLD_ROTATE": {"FOLD": 0, "HOLD": 1, "SPREAD": 2},
    "INS_SW": {"OFF": 0, "CV": 1, "GND": 2, "NAV": 3, "IFA": 4},
    "RADAR_SW": {"OFF": 0, "STBY": 1, "OPR": 2},
    # Verifie en vol le 19 nov. : quand la touche affichait BYPASS, l'avion etait sur OFF.
    # L'ordre reel est donc OFF, ON, BYPASS (et, meme construction, OFF ... XMIT).
    "CMSD_DISPENSE_SW": {"OFF": 0, "ON": 1, "BYPASS": 2},
    "ECM_MODE_SW": {"OFF": 0, "STBY": 1, "BIT": 2, "REC": 3, "XMIT": 4},
    "LEFT_DDI_BRT_SELECT": {"OFF": 0, "NIGHT": 1, "DAY": 2},
    "RIGHT_DDI_BRT_SELECT": {"OFF": 0, "NIGHT": 1, "DAY": 2},
    "IR_COOL_SW": {"OFF": 0, "NORM": 1, "ORIDE": 2},
    "SEL_JETT_KNOB": {"L FUS": 0, "SAFE": 1, "R FUS": 2, "RACK": 3, "STORES": 4},
    "GEAR_LEVER": {"DOWN": 0, "UP": 1},
    "HOOK_LEVER": {"DOWN": 0, "UP": 1},
    "MASTER_ARM_SW": {"SAFE": 0, "ARM": 1},
    "HOOK_BYPASS_SW": {"CARRIER": 0, "FIELD": 1},
    "EJECTION_SEAT_ARMED": {"ARMED": 0, "SAFE": 1},
    "LAUNCH_BAR_SW": {"RETRACT": 0, "EXTEND": 1},
    "LTD_R_SW": {"SAFE": 0, "ARM": 1},
}


def nom_position(ident, valeur):
    for nom, v in POS.get(ident, {}).items():
        if v == valeur:
            return nom
    return "?" if valeur is None else str(valeur)


class Avion:
    def __init__(self, bios):
        self.b = bios

    def v(self, ident):
        return self.b.lire(ident)

    def est(self, ident, nom):
        return self.b.lire(ident) == POS[ident][nom]

    def allume(self, ident):
        return self.b.lire(ident) == 1

    # --- moteurs / carburant (lus sur l'IFEI)
    @property
    def rpm_g(self):
        return self.b.nombre("IFEI_RPM_L", 0)

    @property
    def rpm_d(self):
        return self.b.nombre("IFEI_RPM_R", 0)

    @property
    def carburant(self):
        """Carburant total en livres, ou None si l'IFEI est eteint."""
        return self.b.nombre("IFEI_FUEL_UP")

    @property
    def bingo(self):
        return self.b.nombre("IFEI_BINGO")

    # --- vol
    @property
    def vitesse(self):
        return self.b.lire("IAS_US_INT") or 0

    @property
    def altitude(self):
        return self.b.lire("ALT_MSL_FT") or 0

    @property
    def g(self):
        try:
            return float(self.b.lire("G_LOAD") or 0)
        except ValueError:
            return 0.0

    @property
    def au_sol(self):
        # poids sur les roues (train), sinon : un Hornet ne vole pas sous 50 noeuds
        wow = [self.b.lire(i) for i in ("EXT_WOW_NOSE", "EXT_WOW_LEFT", "EXT_WOW_RIGHT")]
        if any(w == 1 for w in wow):
            return True
        return self.vitesse < 50

    @property
    def immobile(self):
        """Au sol et a l'arret. La vitesse indiquee affiche quelques noeuds a l'arret
        (vent) : 8 noeuds pendant ton vol du 15 novembre, frein serre."""
        return self.au_sol and (self.frein_parking or self.vitesse < 25)

    @property
    def rwr_allume(self):
        """Dernier etat connu du RWR (None = inconnu) : confirme par son autotest."""
        return getattr(self, "rwr_etat", None)

    # --- configuration
    @property
    def train_sorti(self):
        return all(self.allume(i) for i in
                   ("FLP_LG_NOSE_GEAR_LT", "FLP_LG_LEFT_GEAR_LT", "FLP_LG_RIGHT_GEAR_LT"))

    @property
    def levier_train_bas(self):
        return self.est("GEAR_LEVER", "DOWN")

    @property
    def ailes_repliees(self):
        return (self.b.lire("EXT_WING_FOLDING") or 0) > 3000

    @property
    def verriere_fermee(self):
        return (self.b.lire("CANOPY_POS") or 0) < 700

    @property
    def frein_parking(self):
        x = getattr(self, "export", None)
        if x is not None and x.ordres_possibles:
            from .cockpit import frein_serre
            v = frein_serre(x)
            if v is not None:
                return v
        # Poignee tiree (PULL = 1) et tournee (ROTATE = 2) : c'est ce que montrait
        # ton cockpit frein serre (marques du 15 nov.). L'etiquette DCS-BIOS
        # "2 = release" est trompeuse : l'entree 2 serre, l'entree 1 relache.
        return (self.b.lire("EMERGENCY_PARKING_BRAKE_ROTATE") == 2
                and self.b.lire("EMERGENCY_PARKING_BRAKE_PULL") == 1)

    @property
    def arme(self):
        return self.est("MASTER_ARM_SW", "ARM")
