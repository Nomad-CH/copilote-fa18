"""Le copilote : relie DCS, les procedures, la surveillance, la voix et les touches."""
import collections
import queue
import random
import threading
import time

from . import pages
from . import touches
from .boite_noire import DOSSIER as DOSSIER_BOITE, BoiteNoire
from .avion import Avion
from .deck import COLS, RANGS, ROUGE, Touche, dessiner
from .procedures import Executeur
from .surveillance import Surveillance
from .voix import Voix


ACCUEILS = (
    "F/A-18 détecté. Je suis en place arrière, façon de parler.",
    "Bonjour Lucas. Hornet en ligne, et moi aussi.",
    "Connexion établie. Prêt à faire tout le travail, comme d'habitude.",
)


class Copilote:
    def __init__(self, bios, cfg, ecran, export=None):
        self.b, self.cfg, self.ecran = bios, cfg, ecran
        self.export = export
        self.a = Avion(bios)
        self.voix = Voix.depuis_config(cfg)
        try:
            from .voix import phrases_connues
            self.voix.preparer(phrases_connues())
        except Exception as ex:
            print(f"Préparation des phrases impossible : {ex}")
        self.boite = BoiteNoire(cfg.get("boite_noire_dossier") or DOSSIER_BOITE)
        self.ex = Executeur(bios, self.a, cfg, self.dire)
        self.ex.boite = self.boite
        self.surv = Surveillance(self.a, self.dire, self.ex, export, self.boite)
        self.page = "vol"
        self.historique = collections.deque(maxlen=40)
        self.nb_messages = 0
        # demandes pour la fenetre (venant du Stream Deck, donc d'un autre fil)
        self.demandes_fenetre = queue.Queue()
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

    def larguer(self, sorte):
        """sorte = 'chaff' (paillettes) ou 'flare' (leurre IR)."""
        threading.Thread(target=self._larguer, args=(sorte,), daemon=True).start()

    def _larguer(self, sorte):
        from .avion import POS
        b, x = self.b, self.export
        if b.lire("CMSD_DISPENSE_SW") != POS["CMSD_DISPENSE_SW"]["ON"]:
            b.envoyer("CMSD_DISPENSE_SW", POS["CMSD_DISPENSE_SW"]["ON"])
            time.sleep(0.4)
        avant = x.leurres if (x is not None and x.vivant) else None
        # interrupteur de la manette : 2 = avant (paillettes), 0 = arriere (leurres IR)
        b.envoyer("THROTTLE_DISP_SW", 2 if sorte == "chaff" else 0)
        time.sleep(0.25)
        b.envoyer("THROTTLE_DISP_SW", 1)
        if avant is None:
            return
        time.sleep(1.2)
        apres = x.leurres or avant
        paillettes, ir = avant[0] - apres[0], avant[1] - apres[1]
        if paillettes > 0 and ir > 0:
            self.dire("Paillettes et leurres partis.")
        elif paillettes > 0:
            self.dire("Paillettes." if sorte == "chaff" else "Attention : ce sont des paillettes qui sont parties.")
        elif ir > 0:
            self.dire("Leurre." if sorte == "flare" else "Attention : c'est un leurre IR qui est parti.")
        else:
            self.dire("Rien n'est parti. Vérifie l'interrupteur DISPENSER et le programme de leurres.")
            self.boite.ecrire("largage_sans_effet", sorte=sorte, leurres=avant,
                              dispenser=b.lire("CMSD_DISPENSE_SW"))

    def fenetre(self, action):
        """action : 'suivante' (pleine -> barre -> cachee) ou 'coin'."""
        self.demandes_fenetre.put(action)

    def marquer(self):
        n = self.boite.marquer(self)
        self.dire(f"Marque {n} enregistrée.")

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
                          "de manette sans touche clavier dans DCS. Je te demanderai "
                          "de le faire toi-même.")
            elif nouvelles != avant:
                self.dire("Tes touches DCS ont changé, j'ai suivi.")

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
        self._etait_en_f18 = en_f18
        if maintenant - self._dernier_surv > 0.25:
            self._dernier_surv = maintenant
            try:
                self.surv.tick()
            except Exception as ex:   # la surveillance ne doit jamais arreter le copilote
                self.boite.erreur("surveillance", ex)

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
