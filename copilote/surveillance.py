"""Surveillance de l'avion : le copilote previent quand quelque chose cloche.

Chaque alerte se declenche une fois quand sa condition devient vraie, puis
se rearme quand la condition disparait. Pour en ajouter une, ajouter une
ligne a ALERTES : (cle, condition, [phrases possibles], urgente).
"""
import random
import time

VOYANTS_PANNE = {
    "CLIP_L_GEN_LT": "génératrice gauche",
    "CLIP_R_GEN_LT": "génératrice droite",
    "CLIP_BATT_SW_LT": "batterie",
    "CLIP_FCS_HOT_LT": "commandes de vol en surchauffe",
    "CLIP_GEN_TIE_LT": "couplage génératrices",
    "CLIP_FCES_LT": "commandes de vol",
    "CLIP_APU_ACC_LT": "accumulateur APU",
    "CLIP_CK_SEAT_LT": "siège éjectable non armé",
    "LH_ADV_L_BLEED": "prélèvement d'air gauche",
    "LH_ADV_R_BLEED": "prélèvement d'air droit",
}


def _bingo(a):
    c, b = a.carburant, a.bingo
    return c is not None and b and c <= b and not a.au_sol


def _train_oublie(a):
    return (not a.au_sol and a.vitesse < 175 and not a.levier_train_bas
            and not a.est("FLAP_SW", "AUTO"))


ALERTES = [
    ("feu_g", lambda a: a.allume("FIRE_LEFT_LT"), ["Feu moteur gauche ! Feu moteur gauche !"], True),
    ("feu_d", lambda a: a.allume("FIRE_RIGHT_LT"), ["Feu moteur droit ! Feu moteur droit !"], True),
    ("feu_apu", lambda a: a.allume("FIRE_APU_LT"), ["Feu APU ! Feu APU !"], True),
    ("sam", lambda a: a.allume("RH_ADV_SAM"), ["Missile sol-air ! Défends !"], True),
    ("ai", lambda a: a.allume("RH_ADV_AI"), ["Radar chasseur. Accroché."], True),
    ("aaa", lambda a: a.allume("RH_ADV_AAA"), ["Artillerie antiaérienne."], False),
    ("bingo", _bingo, ["Bingo. Bingo."], True),
    ("fuel_lo", lambda a: a.allume("CLIP_FUEL_LO_LT"), ["Carburant bas ! Carburant bas !"], True),
    ("train_oublie", _train_oublie, ["Train ! Train non sorti !"], True),
    ("train_vitesse", lambda a: not a.au_sol and a.levier_train_bas and a.vitesse > 260,
     ["Survitesse train. 250 nœuds maximum."], False),
    ("arme_sol", lambda a: a.au_sol and a.arme and a.rpm_d > 50, ["Master arm actif au sol."], False),
    ("facteur_g", lambda a: a.g >= 8.0, ["Huit G."], False),
    ("crosse_sol", lambda a: (not a.au_sol and a.est("HOOK_LEVER", "DOWN")
                              and a.est("HOOK_BYPASS_SW", "FIELD") and a.levier_train_bas),
     ["Crosse sortie, hook bypass sur terrain. Vérifie."], False),
]


# Annonce au depart d'une arme, d'apres son nom DCS
def phrase_tir(nom):
    n = nom.upper()
    if "AIM-120" in n or "AIM-54" in n:
        return "Fox trois."
    if "AIM-7" in n:
        return "Fox un."
    if "AIM-9" in n:
        return "Fox deux."
    if "AGM-88" in n:
        return "Magnum."
    if "AGM-65" in n:
        return "Rifle."
    if "AGM-84" in n:
        return "Bruiser."
    if any(m in n for m in ("GBU", "MK-8", "MK8", "CBU", "JSOW", "AGM-154", "BDU")):
        return "Bombe larguée."
    if "FUEL" in n or "FPU" in n:
        return None   # bidon largue : pas d'annonce
    return f"{nom}, tir."


class Surveillance:
    def __init__(self, avion, dire, executeur, export=None, boite=None):
        self.a, self._dire, self.ex = avion, dire, executeur
        self.export = export
        self.boite = boite
        self._prochaine_lecture_pages = 0.0
        self.actives = []          # textes courts pour l'affichage
        self._etat = {}
        self._pannes_vues = set()
        self._mc = False
        self._pret_depuis = None
        # menaces RWR : symbole -> {"niveau": ..., "vu": heure}
        self.menaces = {}
        self._derniere_menace_nommee = 0.0
        self._stations = None
        self._leurres_bas = False
        self._ifa_fait = False
        self._rwr_muet_jusqua = 0.0
        self._rwr_allume = False

    def tick(self):
        a = self.a
        if a.b.en_pause:
            return          # DCS en pause : on garde tout tel quel
        if not a.b.en_f18:
            self._etat.clear()
            self._pannes_vues.clear()
            self._pret_depuis = None
            self.actives = []
            self.menaces = {}
            self._stations = None
            return
        # laisse 3 s au flux pour se stabiliser a l'entree dans le cockpit
        if self._pret_depuis is None:
            self._pret_depuis = time.time()
        if time.time() - self._pret_depuis < 3:
            return

        if self.export is not None and self.export.vivant:
            self._suivre_alignement()
            self._suivre_menaces()
            self._suivre_armes()
            self._suivre_leurres()
            if self.boite is not None and a.b.lire("INS_SW") in (1, 2):   # CV ou GND
                self.boite.alignement(self.export.ecrans, a.b.lire("INS_SW"))
            if self.boite is not None and time.time() >= self._prochaine_lecture_pages:
                self._prochaine_lecture_pages = time.time() + 2.0
                for numero in (2, 3, 4):
                    self.boite.page(numero, self.export.ecrans.get(numero, ""))

        actives = []
        for cle, cond, phrases, urgente in ALERTES:
            try:
                vrai = bool(cond(a))
            except Exception:
                vrai = False
            if vrai:
                actives.append(cle)
                nommee_recente = time.time() - self._derniere_menace_nommee < 4
                if not self._etat.get(cle) and not (cle in ("sam", "ai") and nommee_recente):
                    self._dire(random.choice(phrases), urgente)
            self._etat[cle] = vrai

        # Master caution : on annonce les voyants de panne nouvellement allumes.
        # Muet pendant un demarrage ou un arret, ou tout s'allume normalement.
        pannes = {i for i in VOYANTS_PANNE if a.allume(i)}
        nouvelles = pannes - self._pannes_vues
        self._pannes_vues = pannes
        calme = self.ex.en_cours in ("demarrage_terre", "demarrage_pa", "arret") \
            or (a.rpm_g < 55 and a.rpm_d < 55)
        mc = a.allume("MASTER_CAUTION_LT")
        if not calme:
            if nouvelles:
                self._dire("Alarme. " + ", ".join(VOYANTS_PANNE[i] for i in sorted(nouvelles)) + ".", False)
            elif mc and not self._mc:
                self._dire("Master caution.", False)
        self._mc = mc
        self.actives = actives + sorted(pannes)

    # ------------------------------------------------- donnees de l'export
    def _suivre_alignement(self):
        """A QUAL OK, passe la centrale de GND/CV sur IFA (checklist DimOn)."""
        a = self.a
        ins = a.b.lire("INS_SW")
        if ins not in (1, 2):
            self._ifa_fait = False
            return
        if self._ifa_fait or not a.au_sol or not self.ex.cfg.get("ins_auto_ifa", True):
            return
        from . import alignement
        info = alignement.lire(self.export)
        if info and info["ok"]:
            self._ifa_fait = True
            a.b.envoyer("INS_SW", 4)
            self._dire("Alignement terminé. Centrale sur IFA. Avion prêt.", False)
            # dernier controle du RWR (bouton POWER relu par le lien)
            from . import cockpit
            if cockpit.rwr_allume(self.export, a.b) is False:
                import threading

                def rattraper():
                    ok = cockpit.allumer_rwr(self.export, self.ex.cfg, self.boite)
                    self._dire("RWR allumé." if ok else "RWR éteint. Allume l'ALR-67.", False)
                threading.Thread(target=rattraper, daemon=True).start()

    def _rwr_en_test(self):
        """A sa mise sous tension, le RWR fait un autotest et affiche des symboles
        qui ne sont pas des menaces (Dog Ear et Snow Drift pendant tes vols) :
        on se tait 25 s apres l'allumage, et pendant le demarrage."""
        maintenant = time.time()
        allume = bool(self.export.ecrans.get(7))
        if allume:
            self.a.rwr_etat = True
        if allume and not self._rwr_allume:
            self._rwr_muet_jusqua = maintenant + 25
        self._rwr_allume = allume
        appui = getattr(self.a, "rwr_appui", 0)
        return (maintenant < self._rwr_muet_jusqua or maintenant - appui < 25
                or self.a.allume("RWR_BIT_LT")
                or self.ex.en_cours in ("demarrage_terre", "demarrage_pa"))

    def _suivre_menaces(self):
        from .exportdcs import CONSEIL, menace, nom_menace
        if self._rwr_en_test():
            self.menaces = {}
            return
        maintenant = time.time()
        vues = self.export.menaces()
        sam = self.a.allume("RH_ADV_SAM")
        for sym, niveau in vues.items():
            if self.boite is not None:
                self.boite.symbole_rwr(sym, self.export.ecrans.get(7, ""))
            nom, conseil = menace(sym, sam)
            accroche = f"{nom}, nous accroche ! " + CONSEIL.get(conseil, "")
            connu = self.menaces.get(sym)
            if connu is None:
                self.menaces[sym] = {"niveau": niveau, "vu": maintenant}
                if niveau == "clignote":
                    self._dire(accroche.strip(), True)
                else:
                    self._dire(f"{nom} au RWR.", False)
                self._derniere_menace_nommee = maintenant
            else:
                connu["vu"] = maintenant
                if niveau == "clignote":
                    if connu["niveau"] != "clignote":
                        self._dire(accroche.strip(), True)
                        self._derniere_menace_nommee = maintenant
                    connu["niveau"], connu["calme"] = "clignote", None
                elif connu["niveau"] == "clignote":
                    # redescend apres 3 s sans clignotement
                    if connu.get("calme") is None:
                        connu["calme"] = maintenant
                    elif maintenant - connu["calme"] > 3:
                        connu["niveau"] = niveau
                else:
                    connu["niveau"] = niveau
        for sym in list(self.menaces):
            if sym not in vues and maintenant - self.menaces[sym]["vu"] > 4:
                if self.menaces[sym]["niveau"] == "clignote":
                    self._dire(f"{nom_menace(sym)} perdu.", False)
                del self.menaces[sym]

    def _suivre_armes(self):
        stations = self.export.stations()
        if not stations:
            return
        avant, self._stations = self._stations, stations
        if avant is None:
            return
        # au sol : l'equipe au sol change l'emport (rearmement), ce ne sont pas des tirs
        if self.a.au_sol:
            return
        baisses = [(st, avant[st][0]) for st in stations
                   if st in avant and stations[st][1] < avant[st][1]]
        # tout qui disparait d'un coup : avion perdu ou largage d'urgence, pas de "Fox"
        if not baisses or len(baisses) > 2:
            return
        for _st, nom in baisses:
            phrase = phrase_tir(nom)
            if phrase and phrase.endswith(" parti.") and self.boite is not None:
                self.boite.arme(nom)
            if phrase:
                self._dire(phrase, False)

    def _suivre_leurres(self):
        l = self.export.leurres
        if not l:
            return
        bas = min(l) <= 10
        if bas and not self._leurres_bas:
            if min(l) == 0:
                self._dire("Leurres épuisés.", False)
            else:
                self._dire("Leurres bas.", False)
        self._leurres_bas = bas
