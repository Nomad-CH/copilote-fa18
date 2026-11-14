"""Disposition des 32 touches du Stream Deck XL (8 colonnes x 4 rangees).

Colonnes 1 a 6 : contenu de la page.  Colonne 7 : le copilote (etat,
message, master caution, STOP).  Colonne 8 : choix de page et voix.
Chaque page est une fonction qui renvoie 24 touches, rangee par rangee.
"""
import threading

from .avion import POS, nom_position
from .deck import (AMBRE, BLEU, BLEU_VIF, GRIS, INACTIF, ROUGE, SOMBRE, VERT, VIDE,
                   Touche, couper)
from .procedures import PROCEDURES


# ------------------------------------------------------------- utilitaires
def _proc(app, cle, titre, confirmer=False):
    actif = app.ex.en_cours == cle
    return Touche(titre, "", AMBRE if actif else BLEU,
                  lambda: app.ex.lancer(cle), confirmer)


def _selecteur(app, ident, titre, nombre, couleurs=None):
    v = app.b.lire(ident)
    nom = nom_position(ident, v)
    fond = (couleurs or {}).get(nom, GRIS)
    return Touche(titre, nom, fond, lambda: app.cycle(ident, nombre))


def _bascule(app, ident, titre, noms=("OFF", "ON"), fonds=(GRIS, VERT), confirmer=False):
    v = 1 if app.b.lire(ident) else 0
    return Touche(titre, noms[v], fonds[v], lambda: app.bascule(ident), confirmer)


def _voyant_bouton(app, bouton, voyant, titre, fond_allume=VERT):
    allume = app.a.allume(voyant)
    return Touche(titre, "ON" if allume else "off", fond_allume if allume else GRIS,
                  lambda: app.appui_bouton(bouton))


def _ligne_etat(app):
    a = app.a
    carbu, bingo = a.carburant, a.bingo
    bas = carbu is not None and bingo and carbu <= bingo
    if a.train_sorti:
        train, f_train = "SORTI", VERT
    elif a.levier_train_bas:
        train, f_train = "TRANSIT", AMBRE
    else:
        train, f_train = "RENTRÉ", SOMBRE
    volets = nom_position("FLAP_SW", app.b.lire("FLAP_SW"))
    return [
        Touche("CARBURANT", "---" if carbu is None else str(carbu), ROUGE if bas else SOMBRE),
        Touche("BINGO", "---" if bingo is None else str(bingo), SOMBRE),
        Touche("RPM  G | D", f"{a.rpm_g} | {a.rpm_d}", SOMBRE),
        Touche("NŒUDS / PIEDS", f"{a.vitesse}\n{a.altitude}", SOMBRE),
        Touche("TRAIN", train, f_train),
        Touche("VOLETS", volets, SOMBRE if volets == "AUTO" else AMBRE),
    ]


# ------------------------------------------------------------------ pages
def page_proc(app):
    return [
        _proc(app, "demarrage_terre", "DÉMARRAGE\nTERRE"),
        _proc(app, "demarrage_pa", "DÉMARRAGE\nPORTE-AV."),
        _proc(app, "ins_ifa", "INS\nIFA"),
        _proc(app, "avant_decollage", "AVANT\nDÉCOLLAGE"),
        _proc(app, "catapulte", "CATAPULTE"),
        _proc(app, "apres_decollage", "APRÈS\nDÉCOLLAGE"),

        _proc(app, "fence_in", "FENCE\nIN"),
        _proc(app, "fence_out", "FENCE\nOUT"),
        _proc(app, "ravitaillement", "RAVITO"),
        _proc(app, "fin_ravitaillement", "FIN\nRAVITO"),
        VIDE,
        _marquer(app),

        _proc(app, "atterrissage", "ATTERR.\nTERRE"),
        _proc(app, "appontage", "APPONTAGE"),
        _proc(app, "apres_atterrissage", "APRÈS\nATTERR."),
        VIDE,
        VIDE,
        _proc(app, "arret", "ARRÊT\nAVION", confirmer=True),
    ] + _ligne_etat(app)


def page_armes(app):
    a, b = app.a, app.b
    arme = a.arme
    stations = [("SJ_LO", "EXT G", 2), ("SJ_LI", "INT G", 3), ("SJ_CTR", "CENTRE", 5),
                ("SJ_RI", "INT D", 7), ("SJ_RO", "EXT D", 8)]
    return [
        Touche("MASTER ARM", "ARMÉ" if arme else "SAFE", ROUGE if arme else VERT,
               lambda: app.bascule("MASTER_ARM_SW")),
        _voyant_bouton(app, "MASTER_MODE_AA", "MASTER_MODE_AA_LT", "MODE A/A"),
        _voyant_bouton(app, "MASTER_MODE_AG", "MASTER_MODE_AG_LT", "MODE A/G"),
        _proc(app, "air_air", "PRÊT\nAIR-AIR"),
        _proc(app, "air_sol", "PRÊT\nAIR-SOL"),
        _proc(app, "securite", "TOUT SUR\nSÉCURITÉ"),

        _selecteur(app, "RADAR_SW", "RADAR", 3, {"OPR": VERT, "STBY": AMBRE}),
        _selecteur(app, "FLIR_SW", "FLIR", 3, {"ON": VERT, "STBY": AMBRE}),
        _bascule(app, "LTD_R_SW", "LASER", ("SAFE", "ARMÉ"), (GRIS, ROUGE)),
        _larguer(app, "chaff"),
        _selecteur(app, "IR_COOL_SW", "REFROID. IR", 3, {"NORM": VERT, "ORIDE": AMBRE}),
        _voyant_bouton(app, "RWR_POWER_BTN", "RWR_LOWER_LT", "RWR"),

        _selecteur(app, "CMSD_DISPENSE_SW", "LEURRES", 3, {"ON": VERT, "BYPASS": AMBRE}),
        _selecteur(app, "ECM_MODE_SW", "BROUILLEUR", 5,
                   {"XMIT": ROUGE, "REC": VERT, "STBY": AMBRE, "BIT": AMBRE}),
        _larguer(app, "flare"),
        _selecteur(app, "SEL_JETT_KNOB", "SÉL. LARGAGE", 5,
                   {"SAFE": VERT, "L FUS": AMBRE, "R FUS": AMBRE, "RACK": AMBRE, "STORES": AMBRE}),
        Touche("LARGAGE\nSÉLECTIF", "", ROUGE, lambda: app.appui_bouton("SEL_JETT_BTN", 0.5), True),
        Touche("LARGAGE\nURGENCE", "", ROUGE, lambda: app.appui_bouton("EMER_JETT_BTN", 0.5), True),
    ] + [_station(app, bouton, nom, num) for bouton, nom, num in stations] + [_marquer(app)]


def _feux(app):
    """Etat lu sur les vrais feux de l'avion (l'interrupteur est mal relu)."""
    from .procedures import FEUX_OFF, FEUX_ON
    b = app.b
    allumes = bool(b.lire("EXT_POSITION_LIGHT_LEFT") or b.lire("EXT_STROBE_LIGHTS")
                   or (b.lire("EXT_FORMATION_LIGHTS") or 0) > 1000)

    def action():
        etapes = FEUX_OFF if allumes else FEUX_ON
        for e in etapes:
            b.envoyer(e.ident, e.valeur())
    return Touche("FEUX EXT.", "ON" if allumes else "OFF", VERT if allumes else GRIS, action)


def _larguer(app, sorte):
    """Largage manuel par l'interrupteur de la manette : avant = paillettes,
    arriere = leurres IR. Le copilote verifie au compteur que c'est parti."""
    titre = "PAILLETTES" if sorte == "chaff" else "LEURRE IR"
    return Touche("LARGUER", titre, BLEU, lambda: app.larguer(sorte))


def _abrege(nom):
    """'GBU-38(V)1/B' -> 'GBU-38', 'FPU_8A' -> 'BIDON'"""
    n = (nom or "").upper()
    if not n or n.startswith("UNKNOWN"):
        return ""
    if "FPU" in n or "FUEL" in n:
        return "BIDON"
    return n.split("(")[0].replace("_", " ").strip()[:8]


def _station(app, bouton, nom, numero):
    """Touche de largage selectif, avec le vrai chargement si le lien DCS marche."""
    choisie = app.a.allume(bouton + "_LT")
    contenu = ""
    if app.export is not None and app.export.vivant:
        arme, n = app.export.stations().get(numero, ("", 0))
        contenu = f"{_abrege(arme)}\nx{n}" if n else "VIDE"
    return Touche(f"STA {numero} {nom}", contenu or nom, AMBRE if choisie else GRIS,
                  lambda: app.appui_bouton(bouton))


def _ddi(app):
    """Pages affichees sur les deux DDI (lues sur les ecrans)."""
    if app.export is None or not app.export.vivant:
        return Touche("DDI G | D", "---", SOMBRE)
    g, d = app.export.page(2) or "-", app.export.page(3) or "-"
    return Touche("DDI G | D", f"{g[:6]}\n{d[:6]}", SOMBRE)


def _train(app):
    a = app.a

    def action():
        if a.levier_train_bas:
            if a.au_sol and app.cfg.get("gardes_sol_vol", True):
                app.dire("Je ne rentre pas le train au sol. Question de principe.")
                return
            app.regler("GEAR_LEVER", POS["GEAR_LEVER"]["UP"])
        else:
            if a.vitesse > 250:
                app.dire("Trop rapide pour le train : passe sous 250 nœuds.")
                return
            app.regler("GEAR_LEVER", POS["GEAR_LEVER"]["DOWN"])

    bas = a.levier_train_bas
    return Touche("LEVIER TRAIN", "BAS" if bas else "HAUT", VERT if bas else GRIS, action, True)


def _volet(app, nom):
    actif = app.a.est("FLAP_SW", nom)
    return Touche("VOLETS", nom, VERT if actif else GRIS,
                  lambda: app.regler("FLAP_SW", POS["FLAP_SW"][nom]))


def _verriere(app):
    a = app.a

    def action():
        if a.verriere_fermee:
            app.regler("CANOPY_SW", POS["CANOPY_SW"]["OPEN"])
            return

        def fermer():
            import time
            app.regler("CANOPY_SW", POS["CANOPY_SW"]["CLOSE"])
            fin = time.time() + 15
            while not a.verriere_fermee and time.time() < fin:
                time.sleep(0.2)
            app.regler("CANOPY_SW", POS["CANOPY_SW"]["HOLD"])
        threading.Thread(target=fermer, daemon=True).start()

    ferme = a.verriere_fermee
    return Touche("VERRIÈRE", "FERMÉE" if ferme else "OUVERTE", GRIS if ferme else AMBRE, action)


def _frein(app):
    serre = app.a.frein_parking
    # entree DCS-BIOS : 2 = serrer le frein de parking, 1 = le relacher
    return Touche("FREIN PARK", "SERRÉ" if serre else "LIBRE", AMBRE if serre else GRIS,
                  lambda: app.regler("EMERGENCY_PARKING_BRAKE_ROTATE", 1 if serre else 2))


def _ailes(app):
    a = app.a

    def action():
        if a.ailes_repliees:
            app.regler("WING_FOLD_PULL", 1)
            app.regler("WING_FOLD_ROTATE", POS["WING_FOLD_ROTATE"]["SPREAD"])
        elif a.au_sol:
            app.regler("WING_FOLD_PULL", 1)
            app.regler("WING_FOLD_ROTATE", POS["WING_FOLD_ROTATE"]["FOLD"])
        else:
            app.dire("Replier les ailes en vol ? Non.")

    plie = a.ailes_repliees
    return Touche("AILES", "PLIÉES" if plie else "DÉPLIÉES", AMBRE if plie else GRIS, action, True)


def _perche(app):
    nom = nom_position("PROBE_SW", app.b.lire("PROBE_SW"))
    sortie = nom != "RETRACT"
    return Touche("PERCHE", "SORTIE" if sortie else "RENTRÉE", AMBRE if sortie else GRIS,
                  lambda: app.regler("PROBE_SW", POS["PROBE_SW"]["RETRACT" if sortie else "EXTEND"]))


def page_avion(app):
    a, b = app.a, app.b
    batt = nom_position("BATTERY_SW", b.lire("BATTERY_SW"))
    siege = a.est("EJECTION_SEAT_ARMED", "ARMED")
    return [
        _train(app),
        _volet(app, "AUTO"),
        _volet(app, "HALF"),
        _volet(app, "FULL"),
        _bascule(app, "HOOK_LEVER", "CROSSE", ("SORTIE", "RENTRÉE"), (AMBRE, GRIS)),
        _bascule(app, "LAUNCH_BAR_SW", "BARRE CATA", ("RENTRÉE", "SORTIE"), (GRIS, AMBRE)),

        _perche(app),
        _bascule(app, "LDG_TAXI_SW", "PHARE"),
        _feux(app),
        _bascule(app, "ANTI_SKID_SW", "ANTI-SKID"),
        _frein(app),
        _verriere(app),

        Touche("BATTERIE", batt, VERT if batt == "ON" else GRIS,
               lambda: app.regler("BATTERY_SW", POS["BATTERY_SW"]["OFF" if batt == "ON" else "ON"]),
               True),
        Touche("APU", "PRÊT" if a.allume("APU_READY_LT") else ("ON" if b.lire("APU_CONTROL_SW") else "OFF"),
               VERT if a.allume("APU_READY_LT") else GRIS,
               lambda: app.bascule("APU_CONTROL_SW")),
        _ailes(app),
        Touche("SIÈGE", "ARMÉ" if siege else "SAFE", GRIS if siege else AMBRE,
               lambda: app.bascule("EJECTION_SEAT_ARMED")),
        Touche("TRIM\nDÉCOLLAGE", "", BLEU, lambda: app.appui_bouton("TO_TRIM_BTN", 2.5)),
        _voix(app),
    ] + _ligne_etat(app)


def _marquer(app):
    return Touche("MARQUER", "", BLEU, app.marquer)


def _voix(app):
    actif = app.voix.active and app.voix.disponible
    valeur = ("ON" if actif else "OFF") if app.voix.disponible else "INDISPO"
    return Touche("VOIX", valeur, VERT if actif else GRIS, app.voix.basculer)


def _a_venir(app, titre, quoi):
    """Fonction prevue mais pas encore construite : grisee, elle le dit."""
    return Touche(titre, "", INACTIF, lambda: app.dire(f"{quoi} : pas encore disponible."))


def page_mission(app):
    return [
        _a_venir(app, "CAPTURER\nPOINT", "Capture d'un point sur la carte"),
        _a_venir(app, "ENVOYER\nÀ L'AVION", "Envoi des points à l'avion"),
        _a_venir(app, "POINT\nPRÉCÉDENT", "Navigation entre les points"),
        _a_venir(app, "POINT\nACTIF", "Navigation entre les points"),
        _a_venir(app, "POINT\nSUIVANT", "Navigation entre les points"),
        _a_venir(app, "FLIR SUR\nLE POINT", "FLIR sur un point"),

        _a_venir(app, "DÉSIGNER\nCIBLE", "Désignation de cible"),
        _a_venir(app, "CODE\nLASER", "Réglage du code laser"),
        _a_venir(app, "JDAM\nCIBLES", "Affectation des JDAM"),
        _a_venir(app, "PROGRAM.\nJDAM", "Programmation des JDAM"),
        _ddi(app),
        _marquer(app),

        _a_venir(app, "TACAN", "Réglage du TACAN"),
        _a_venir(app, "ICLS", "Réglage de l'ICLS"),
        _a_venir(app, "PILOTE\nAUTO", "Pilote automatique"),
        _a_venir(app, "PROG.\nLEURRES", "Programmes de leurres"),
        Touche("FENÊTRE", getattr(app, "mode_fenetre", "").upper(), GRIS,
               lambda: app.fenetre("suivante")),
        Touche("COIN\nFENÊTRE", "", GRIS, lambda: app.fenetre("coin")),
    ] + _ligne_etat(app)


PAGES = {"vol": page_proc, "combat": page_armes, "mission": page_mission, "avion": page_avion}


# ------------------------------------------------------- colonnes communes
def _menace(app):
    """Touche menace : la plus dangereuse du RWR, ou rien."""
    from .exportdcs import SYMBOLES
    m = app.surv.menaces

    def nom_menace(s):
        return SYMBOLES.get(s, s).split(" ou ")[0].split(",")[0]
    if not m:
        return None
    sym = sorted(m, key=lambda s: (m[s]["niveau"] != "clignote", s))[0]
    autres = len(m) - 1
    titre = "MENACE" + (f" +{autres}" if autres else "")
    if m[sym]["niveau"] == "clignote":
        import time
        fond = ROUGE if int(time.time() * 4) % 2 == 0 else (90, 10, 10)
        return Touche(titre, nom_menace(sym)[:8] + "\nACCROCHE", fond)
    return Touche(titre, nom_menace(sym)[:8], AMBRE)


def _etat(app):
    menace = _menace(app) if app.b.en_f18 else None
    if menace is not None:
        return menace
    if app.b.en_pause:
        return Touche("DCS", "PAUSE", AMBRE)
    if not app.b.connecte:
        return Touche("DCS", "HORS\nLIGNE", GRIS)
    if not app.b.vivant:
        return Touche("DCS", "EN\nATTENTE", GRIS)
    if not app.b.en_f18:
        return Touche("AVION", "PAS UN\nF/A-18", AMBRE)
    if app.ex.en_cours:
        i, n = app.ex.avancement
        return Touche(app.ex.titre.upper()[:14], f"{i} / {n}", AMBRE)
    return Touche("F/A-18", "EN LIGNE", VERT)


def composer(app):
    """Les 32 touches a afficher maintenant, dans l'ordre du Stream Deck."""
    contenu = PAGES[app.page](app) if app.b.en_f18 else _attente(app)
    mc = app.a.allume("MASTER_CAUTION_LT") if app.b.en_f18 else False
    copilote = [
        _etat(app),
        Touche(couper(app.message), "", SOMBRE, lambda: app.dire(app.message)),
        Touche("MASTER\nCAUTION", "", AMBRE if mc else GRIS,
               lambda: app.appui_bouton("MASTER_CAUTION_RESET_SW")),
        Touche("STOP", "", ROUGE if app.ex.en_cours else GRIS, app.ex.stop),
    ]

    def nav(cle, titre):
        def aller():
            app.page = cle
        return Touche(titre, "", BLEU_VIF if app.page == cle else GRIS, aller)

    navigation = [
        nav("vol", "VOL"),
        nav("combat", "COMBAT"),
        nav("mission", "MISSION"),
        nav("avion", "AVION"),
    ]
    touches = []
    for r in range(4):
        touches += contenu[r * 6:(r + 1) * 6] + [copilote[r], navigation[r]]
    return touches


def _attente(app):
    t = [VIDE] * 24
    t[8] = Touche("EN ATTENTE", "", SOMBRE)
    t[9] = Touche("Monte dans\nun F/A-18\ndans DCS", "", SOMBRE)
    t[22] = Touche("FENÊTRE", getattr(app, "mode_fenetre", "").upper(), GRIS,
                   lambda: app.fenetre("suivante"))
    t[23] = _voix(app)
    return t


assert all(k in PROCEDURES for k in (
    "demarrage_terre", "demarrage_pa", "ins_ifa", "avant_decollage", "catapulte",
    "apres_decollage", "fence_in", "fence_out", "ravitaillement", "fin_ravitaillement",
    "atterrissage", "appontage", "apres_atterrissage", "arret", "air_air", "air_sol", "securite"))
