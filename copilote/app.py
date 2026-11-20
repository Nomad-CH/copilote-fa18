"""Le copilote : relie DCS, les procedures, la surveillance, la voix et les touches."""
import collections
import queue
import random
import threading
import time

from . import pages
from . import touches
from .boite_noire import DOSSIER as DOSSIER_BOITE, BoiteNoire
from .avion import POS, Avion
from .deck import COLS, RANGS, ROUGE, Touche, dessiner
from .procedures import Executeur
from .surveillance import Surveillance
from .voix import Voix


ACCUEILS = (
    "Copilote en ligne. Hornet identifié.",
)


class Copilote:
    def __init__(self, bios, cfg, ecran, export=None):
        self.b, self.cfg, self.ecran = bios, cfg, ecran
        self.export = export
        self.a = Avion(bios)
        self.a.export = export
        self.voix = Voix.depuis_config(cfg)
        try:
            from .voix import phrases_connues
            self.voix.preparer(phrases_connues())
        except Exception as ex:
            print(f"Préparation des phrases impossible : {ex}")
        self.boite = BoiteNoire(cfg.get("boite_noire_dossier") or DOSSIER_BOITE)
        self.ex = Executeur(bios, self.a, cfg, self.dire, export)
        self.ex.boite = self.boite
        from .chemins import DONNEES
        from .navigation import Carnet, SuiviWaypoints
        import os as _os
        from .trace import Trace
        self.trace = Trace(self.boite.dossier)
        self._derniere_trace = 0.0
        self.nav = Carnet(_os.path.join(DONNEES, "points.json"))
        self.nav.tacan = 0
        self.ex.nav = self.nav
        self.suivi_wpt = SuiviWaypoints()
        self._dernier_suivi = 0.0
        self.surv = Surveillance(self.a, self.dire, self.ex, export, self.boite)
        self.surv.larguer = self.larguer
        self.page = "vol"
        self.historique = collections.deque(maxlen=40)
        self.nb_messages = 0
        # demandes pour la fenetre (venant du Stream Deck, donc d'un autre fil)
        self.demandes_fenetre = queue.Queue()
        self._verrou_leurres = threading.Lock()
        from .tablette import Tablette
        self.tablette = Tablette(self, cfg)
        self.message = "Copilote prêt."
        self._touches = [None] * (COLS * RANGS)
        self._affiche = [None] * (COLS * RANGS)
        self._confirme = (None, 0.0)      # (index, echeance)
        self._etait_en_f18 = False
        self._dernier_surv = 0.0
        ecran.sur_appui(self.appui)

    # --------------------------------------------------------- messages
    def dire(self, texte, urgent=False):
        self.historique.append((time.strftime("%H:%M:%S"), texte, urgent))
        self.nb_messages += 1
        self.message = texte
        print(time.strftime("[%H:%M:%S] ") + texte, flush=True)
        self.voix.dire(texte, urgent)

    def larguer(self, sorte, auto=False):
        """sorte = 'chaff' (paillettes) ou 'flare' (leurre IR). auto : salve de la
        defense automatique, sans annonce a chaque paillette."""
        threading.Thread(target=self._larguer, args=(sorte, auto), daemon=True).start()

    _silence_leurres = False

    def _larguer(self, sorte, auto=False):
        """Leurres. DISPENSER sur BYPASS (position 2, confirmee en vol) : un appui = un
        largage. Dans DCS il faut aussi un mode A/A ou A/G : le copilote passe en A/G
        tout seul si besoin. On ne fait plus bouger le DISPENSER d'une position a
        l'autre et on n'utilise plus le clic direct sur la manette : les deux
        laissaient l'interrupteur de largage enfonce (leurres qui partaient seuls)."""
        # la defense automatique attend son tour ; un appui manuel en double est ignore
        if not self._verrou_leurres.acquire(blocking=auto, timeout=3 if auto else -1):
            return
        try:
            self._silence_leurres = auto
            b, a, x = self.b, self.a, self.export
            if b.lire("CMSD_DISPENSE_SW") != 2:
                b.envoyer("CMSD_DISPENSE_SW", 2)
                time.sleep(0.5)
            if not self._mode_combat() and not a.au_sol:
                b.envoyer("MASTER_MODE_AG", 1)
                time.sleep(0.3)
                b.envoyer("MASTER_MODE_AG", 0)
                time.sleep(0.8)
                if self._mode_combat():
                    self.dire("Mode air-sol engagé pour les leurres.")
            avant = x.leurres if (x is not None and x.vivant) else None
            ok = self._appui_leurres(sorte, avant)
            if ok is False:
                time.sleep(0.3)
                ok = self._appui_leurres(sorte, avant, 0.4, "bios")   # l'autre methode en secours
            self._relacher_largage()
            self.trace.action("copilote", "largage " + sorte, auto=auto, ok=ok,
                              methode=getattr(self, "_methode_leurres", None),
                              avant=list(avant) if avant else None,
                              apres=list(x.leurres) if x is not None and x.leurres else None)
            if ok is False:
                manque = []
                if not a.arme:
                    manque.append("master arm")
                if not self._mode_combat():
                    manque.append("mode A/A ou A/G")
                if not auto or manque:
                    self.dire("Négatif, aucun largage." + (" Il manque : " + " et ".join(manque) + "." if manque else ""))
                self.boite.ecrire("largage_sans_effet", leurre=sorte, auto=auto,
                                  leurres=x.leurres if x is not None else None,
                                  dispenser=b.lire("CMSD_DISPENSE_SW"), arme=bool(a.arme),
                                  mode=self._mode_combat(),
                                  args=dict(x.args) if x is not None else None)
        finally:
            self._relacher_largage()                         # interrupteur de largage toujours relache
            self._verrou_leurres.release()

    def _mode_combat(self):
        return bool(self.a.allume("MASTER_MODE_AA_LT") or self.a.allume("MASTER_MODE_AG_LT"))

    def _attendre_largage(self, avant, delai=1.0):
        """Attend que le compteur de leurres baisse (rend la main des que c'est vu)."""
        x = self.export
        fin = time.time() + delai
        while time.time() < fin:
            apres = x.leurres or avant
            if apres != avant:
                return apres
            time.sleep(0.1)
        return x.leurres or avant

    def _appui_direct(self, sorte, duree):
        """Appui sur l'interrupteur de largage par le lien DCS. C'est la seule methode
        qui largue a chaque fois : par DCS-BIOS, seul le premier appui marchait (trace
        du vol du 20 nov. a 22 h 35)."""
        x = self.export
        cmd, val = (3032, 1) if sorte == "chaff" else (3033, -1)
        x.clic(13, cmd, val)
        time.sleep(duree)
        x.clic(13, cmd, 0)
        time.sleep(0.05)
        x.clic(13, cmd, 0)                                   # relachement envoye deux fois

    def _appui_bios(self, sorte, duree):
        b = self.b
        b.envoyer("THROTTLE_DISP_SW", 1)
        time.sleep(0.15)
        b.envoyer("THROTTLE_DISP_SW", 2 if sorte == "chaff" else 0)
        time.sleep(duree)
        b.envoyer("THROTTLE_DISP_SW", 1)
        time.sleep(0.05)
        b.envoyer("THROTTLE_DISP_SW", 1)

    def _relacher_largage(self):
        x = self.export
        if x is not None and x.ordres_possibles:
            x.clic(13, 3032, 0)
            x.clic(13, 3033, 0)
        self.b.envoyer("THROTTLE_DISP_SW", 1)

    def _appui_leurres(self, sorte, avant, duree=0.25, methode=None):
        """Un appui sur l'interrupteur de largage, toujours relache ensuite.
        -> True/False, None si invérifiable."""
        x = self.export
        direct = x is not None and x.ordres_possibles
        methode = methode or ("direct" if direct else "bios")
        (self._appui_direct if methode == "direct" and direct else self._appui_bios)(sorte, duree)
        self._methode_leurres = methode
        if avant is None:
            return None
        apres = self._attendre_largage(avant)
        paillettes, ir = avant[0] - apres[0], avant[1] - apres[1]
        if paillettes <= 0 and ir <= 0:
            return False
        if self._silence_leurres:
            return True
        if paillettes > 0 and ir > 0:
            self.dire("Paillettes et leurres.")
        elif paillettes > 0:
            self.dire("Paillettes." if sorte == "chaff" else "Paillettes larguées, pas de leurre IR.")
        else:
            self.dire("Leurre." if sorte == "flare" else "Leurre IR largué, pas de paillettes.")
        return True

    def fenetre(self, action):
        """action : 'suivante' (pleine -> barre -> cachee) ou 'coin'."""
        self.demandes_fenetre.put(action)

    def frein_parking(self, serrer):
        threading.Thread(target=self._frein_parking, args=(serrer,), daemon=True).start()

    def _frein_parking(self, serrer):
        from . import cockpit
        from .procedures import manoeuvrer_frein
        ok = cockpit.manoeuvrer_frein(self.export, self.cfg, self.boite, serrer)
        if ok is None:
            self.dire("Liaison DCS à mettre à jour pour le frein : relance la mission.")
            ok = manoeuvrer_frein(self.b, self.a, time.sleep, serrer, self.boite)
        if ok:
            self.dire("Frein de parking serré." if serrer else "Frein de parking relâché.")
        else:
            self.dire("Négatif. Frein de parking à ta charge.")

    STATIONS_LARGAGE = [("SJ_LO", "extérieure gauche"), ("SJ_LI", "intérieure gauche"),
                        ("SJ_CTR", "centrale"), ("SJ_RI", "intérieure droite"),
                        ("SJ_RO", "extérieure droite")]

    def largage_selectif(self):
        threading.Thread(target=self._largage_selectif, daemon=True).start()

    def _largage_selectif(self):
        """Tu choisis les stations, le copilote fait le reste : selecteur sur
        STORES (ou RACK), master arm, bouton SEL JETT, puis tout remis en securite."""
        b, a = self.b, self.a
        choisies = self.stations_choisies()
        if not choisies:
            self.dire("Négatif. Aucune station sélectionnée.")
            return
        if a.au_sol:
            self.dire("Négatif. Pas de largage au sol.")
            return
        mode = self.cfg.get("largage_mode", "STORES")
        arme_avant = a.arme
        try:
            if not arme_avant:
                b.envoyer("MASTER_ARM_SW", 1)
            b.envoyer("SEL_JETT_KNOB", POS["SEL_JETT_KNOB"][mode])
            time.sleep(0.6)
            b.appuyer("SEL_JETT_BTN", 0.5)
            time.sleep(1.0)
        finally:
            b.envoyer("SEL_JETT_KNOB", POS["SEL_JETT_KNOB"]["SAFE"])
            time.sleep(0.3)
            from . import cockpit
            for s, _ in choisies:
                if cockpit.station_choisie(self.export, b, s):
                    cockpit.basculer_station(self.export, self.cfg, self.boite, b, s)
            if not arme_avant:
                b.envoyer("MASTER_ARM_SW", 0)
        quoi = "Bidons et charges" if mode == "STORES" else "Pylônes"
        noms = ", ".join(nom for _, nom in choisies)
        self.dire(f"Largage effectué. Station {noms}." if len(choisies) == 1
                  else f"Largage effectué. Stations {noms}.")
        self.boite.ecrire("largage_selectif", mode=mode, stations=[s for s, _ in choisies],
                          quoi=quoi)

    # stations que le largage selectif sait larguer (les autres n'ont pas de bouton)
    STATION_BOUTON = {5: "SJ_CTR", 3: "SJ_LI", 2: "SJ_LO", 7: "SJ_RI", 8: "SJ_RO"}

    def larguer_stations(self, stations):
        threading.Thread(target=self._larguer_stations, args=(list(stations),), daemon=True).start()

    def _larguer_stations(self, stations):
        """Largage selectif des stations choisies sur la tablette : le copilote
        selectionne exactement ces stations, puis fait le largage habituel."""
        from . import cockpit
        voulus = {self.STATION_BOUTON[s] for s in stations if s in self.STATION_BOUTON}
        refusees = [s for s in stations if s not in self.STATION_BOUTON]
        if not voulus:
            self.dire("Négatif. Pas de largage sélectif sur cette station.")
            return
        if self.a.au_sol:
            self.dire("Négatif. Pas de largage au sol.")
            return
        for bouton in self.STATION_BOUTON.values():
            if cockpit.station_choisie(self.export, self.b, bouton) != (bouton in voulus):
                cockpit.basculer_station(self.export, self.cfg, self.boite, self.b, bouton)
                time.sleep(0.3)
        if refusees:
            self.dire("Station " + ", ".join(map(str, refusees)) + " : pas de largage sélectif.")
        self._largage_selectif()

    def station(self, bouton):
        threading.Thread(target=self._station, args=(bouton,), daemon=True).start()

    def _station(self, bouton):
        from . import cockpit
        if cockpit.basculer_station(self.export, self.cfg, self.boite, self.b, bouton) is False:
            self.dire("Négatif. Station non sélectionnée.")

    def stations_choisies(self):
        from . import cockpit
        return [(s, nom) for s, nom in self.STATIONS_LARGAGE
                if cockpit.station_choisie(self.export, self.b, s)]

    def mode_defense(self):
        modes = ["OFF", "CONSEIL", "AUTO"]
        actuel = self.cfg.get("defense", "CONSEIL")
        self.cfg["defense"] = modes[(modes.index(actuel) + 1) % 3 if actuel in modes else 1]
        try:
            from .chemins import sauver_config
            sauver_config(self.cfg)
        except OSError:
            pass
        self.dire({"OFF": "Défense coupée.", "CONSEIL": "Défense en conseil.",
                   "AUTO": "Défense automatique. Réserve de dix leurres."}[self.cfg["defense"]])

    def mode_largage(self):
        self.cfg["largage_mode"] = "RACK" if self.cfg.get("largage_mode", "STORES") == "STORES" else "STORES"
        try:
            from .chemins import sauver_config
            sauver_config(self.cfg)
        except OSError:
            pass
        self.dire("Largage des pylônes." if self.cfg["largage_mode"] == "RACK" else "Largage des charges.")

    # ------------------------------------------------------------ navigation
    def _wpt_passe(self, numero):
        if self.ex.en_cours:
            self.dire(f"Waypoint {numero} passé.")
            return
        self.nav.passe = numero
        self.ex.lancer("wpt_passe")

    def prendre_point(self, sur_avion=False, nom=""):
        """Carte F10 : le point au centre de l'ecran (le viseur). Sinon : l'avion."""
        from .navigation import Point
        x = self.export
        if x is None or not x.vivant:
            self.dire("Négatif. Lien écrans absent.")
            return None
        if sur_avion:
            pos = x.position
            if not pos:
                self.dire("Négatif. Position de l'avion inconnue.")
                return None
            p = Point(nom or self.nav.nom_libre("Marque"), pos["lat"], pos["lon"], pos.get("alt"), "position")
        else:
            vue = x.vue
            if not vue:
                self.dire("Négatif. Mets à jour la liaison DCS, puis relance la mission.")
                return None
            pos = x.position or {}
            # vue cockpit : la camera est sur l'avion, ce n'est pas la carte
            if pos and abs(vue["lat"] - pos.get("lat", 0)) < 0.002 \
                    and abs(vue["lon"] - pos.get("lon", 0)) < 0.002:
                self.dire("Ouvre la carte F10 et centre le viseur sur le point.")
                return None
            p = Point(nom or self.nav.nom_libre("Point"), vue["lat"], vue["lon"], vue.get("sol"), "carte")
        self.nav.ajouter(p)
        texte = f"{p.nom} : waypoint {p.num}, à envoyer."
        if x.position:
            from .navigation import distance_cap
            d, c = distance_cap(x.position["lat"], x.position["lon"], p.lat, p.lon)
            if d >= 0.5:
                texte += f" {d:.0f} nautiques au {round(c):03d}."
        self.dire(texte)
        self.boite.ecrire("point_pris", point=p.dict())
        return p

    def tacan_suivant(self):
        from .navigation import tacan_choisi
        liste = self.cfg.get("tacan") or []
        if not liste:
            self.dire("Aucun canal TACAN. Ajoute-les dans la fenêtre.")
            return
        self.nav.tacan = (getattr(self.nav, "tacan", 0) + 1) % len(liste)
        t = tacan_choisi(self.cfg, self.nav)
        self.dire(f"TACAN {t.get('canal')} {t.get('bande', 'X')}, {t.get('nom', '')}.")

    def radio(self, apres_menu=""):
        """Ouvre le menu radio de DCS puis enchaine des touches F (ex. "F5 F1 F1")."""
        threading.Thread(target=self._radio, args=(apres_menu,), daemon=True).start()

    def _radio(self, apres_menu):
        from . import clavier
        menu = self.cfg.get("touches", {}).get("menu_radio", "")
        if not menu or not clavier.combinaison(menu, maintien=0.1):
            self.dire("Négatif. Menu radio indisponible.")
            return
        for touche in apres_menu.replace(",", " ").split():
            time.sleep(0.5)
            if not clavier.combinaison(touche, maintien=0.1):
                self.dire(f"Négatif. Touche {touche} inconnue.")
                return

    def demander_ravito(self):
        """Au sol : equipe au sol, rearmement et plein. En vol : ravitailleur."""
        if self.a.au_sol:
            sequence = self.cfg.get("radio_sol", "F8 F1").strip()
            message = "Demande réarmement et plein."
        else:
            sequence = self.cfg.get("radio_ravito", "").strip()
            message = "Demande de ravitaillement."
        if not sequence:
            self.radio("")
            self.dire("Menu radio ouvert. Séquence ravitailleur à régler dans la fenêtre.")
            return
        self.radio(sequence)
        self.dire(message)

    def marquer(self):
        n = self.boite.marquer(self)
        self.dire(f"Marque {n}.")

    def _verifier_touches(self):
        """Refait le controle des touches a chaque entree dans le Hornet :
        tu as pu changer tes reglages DCS entre deux vols."""
        avant = dict(self.cfg.get("touches", {}))
        nouvelles, messages = touches.verifier(self.cfg)
        self.cfg["touches"] = nouvelles
        if nouvelles != avant or any("aucune touche" in m for m in messages):
            for m in messages:
                print("  - " + m, flush=True)
            manquantes = [m for m in messages if "aucune touche" in m]
            if manquantes:
                self.dire(f"{len(manquantes)} commande{'s' if len(manquantes) > 1 else ''} "
                          "de manette sans touche clavier dans DCS. Manettes à ta charge.")
            elif nouvelles != avant:
                self.dire("Touches DCS modifiées. Pris en compte.")

    # ----------------------------------------------------------- actions
    def regler(self, ident, valeur):
        self.b.envoyer(ident, valeur)

    def cycle(self, ident, nombre):
        """Passe a la position suivante d'un selecteur."""
        actuel = self.b.lire(ident) or 0
        self.b.envoyer(ident, (actuel + 1) % nombre)

    def bascule(self, ident):
        self.b.envoyer(ident, 0 if self.b.lire(ident) else 1)

    def appui_bouton(self, ident, duree=0.2):
        threading.Thread(target=self.b.appuyer, args=(ident, duree), daemon=True).start()

    # ------------------------------------------------------------ touches
    def appui(self, index):
        t = self._touches[index]
        if t is None or t.action is None:
            return
        if t.confirmer:
            cible, echeance = self._confirme
            if cible != index or time.time() > echeance:
                self._confirme = (index, time.time() + 3.0)
                return
            self._confirme = (None, 0.0)
        self.trace.action("stream deck", (t.titre or t.valeur or "").replace("\n", " "))
        try:
            t.action()
        except Exception as ex:
            self.boite.erreur("touche " + (t.titre or t.valeur).replace("\n", " "), ex)
            self.dire(f"Erreur : {ex}")

    def tick(self):
        """Appele ~6 fois par seconde : surveillance + rafraichissement."""
        maintenant = time.time()
        en_f18 = self.b.en_f18
        if en_f18 and not self._etait_en_f18:
            self.dire(random.choice(ACCUEILS))
            threading.Thread(target=self._verifier_touches, daemon=True).start()
        elif self._etait_en_f18 and not en_f18:
            self.message = "En attente de DCS."
            self.nav.sauver()
        self._etait_en_f18 = en_f18
        if maintenant - self._dernier_surv > 0.25:
            self._dernier_surv = maintenant
            try:
                self.surv.tick()
            except Exception as ex:   # la surveillance ne doit jamais arreter le copilote
                self.boite.erreur("surveillance", ex)

        if en_f18 and maintenant - self._derniere_trace > 1.0:
            self._derniere_trace = maintenant
            try:
                self.trace.tick(self)
            except Exception as ex:
                self.boite.erreur("trace", ex)

        if en_f18 and maintenant - self._dernier_suivi > 1.0 and self.export is not None:
            self._dernier_suivi = maintenant
            t = self.export.temps_modele if self.export.vivant else None
            if t is not None:
                retires = self.nav.horloge_mission(t)
                if retires:
                    self.dire(f"Nouvelle mission : {retires} waypoint{'s' if retires > 1 else ''} "
                              "de l'ancienne mission retirés du plan.")
            try:
                self.suivi_wpt.tick(self.export, self.a, self.cfg, self.dire, self._wpt_passe)
            except Exception as ex:
                self.boite.erreur("suivi waypoints", ex)

        touches = pages.composer(self)
        cible, echeance = self._confirme
        if cible is not None and maintenant > echeance:
            self._confirme = (None, 0.0)
            cible = None
        for i, t in enumerate(touches):
            self._touches[i] = t
            if i == cible:
                clair = int(maintenant * 4) % 2 == 0
                t = Touche("CONFIRMER ?", "rappuie", ROUGE if clair else (90, 10, 10))
            sig = t.signature()
            if sig != self._affiche[i]:
                self._affiche[i] = sig
                self.ecran.afficher(i, dessiner(t))
