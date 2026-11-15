"""Boite noire : le copilote note ce qu'il ne connait pas encore.

Pendant chaque vol, il ecrit dans le dossier boite_noire/ :
  - les symboles RWR qu'il ne sait pas nommer ;
  - les pages de DDI qu'il ne reconnait pas (contenu complet, une fois par page) ;
  - les armes qu'il ne sait pas annoncer ;
  - les erreurs du programme ;
  - un instantane complet a chaque appui sur MARQUER.
diagnostic.bat rassemble ces fichiers pour les envoyer a Claude.
"""
import hashlib
import json
import os
import threading
import time
import traceback

from .chemins import BOITE_NOIRE as DOSSIER
TAILLE_MAX = 30 * 1024 * 1024   # par jour


class BoiteNoire:
    def __init__(self, dossier=DOSSIER):
        self.dossier = dossier
        self._verrou = threading.Lock()
        self._connu_chemin = os.path.join(dossier, "deja_vu.json")
        self.deja_vu = {"rwr": [], "pages": [], "armes": [], "erreurs": []}
        try:
            with open(self._connu_chemin, encoding="utf-8") as f:
                self.deja_vu.update(json.load(f))
        except (OSError, ValueError):
            pass
        self.nb_marques = 0

    # ---------------------------------------------------------- ecriture
    def _fichier(self):
        return os.path.join(self.dossier, "decouvertes_" + time.strftime("%Y%m%d") + ".jsonl")

    def ecrire(self, _sorte, **donnees):
        sorte = _sorte
        try:
            os.makedirs(self.dossier, exist_ok=True)
            chemin = self._fichier()
            if os.path.isfile(chemin) and os.path.getsize(chemin) > TAILLE_MAX:
                return
            ligne = json.dumps({"quand": time.strftime("%Y-%m-%d %H:%M:%S"), "sorte": sorte,
                                **donnees}, ensure_ascii=False, default=str)
            with self._verrou, open(chemin, "a", encoding="utf-8") as f:
                f.write(ligne + "\n")
        except OSError:
            pass   # la boite noire ne doit jamais gener le vol

    def _nouveau(self, categorie, cle):
        if cle in self.deja_vu[categorie]:
            return False
        self.deja_vu[categorie].append(cle)
        try:
            os.makedirs(self.dossier, exist_ok=True)
            with self._verrou, open(self._connu_chemin, "w", encoding="utf-8") as f:
                json.dump(self.deja_vu, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
        return True

    # ------------------------------------------------------- decouvertes
    def symbole_rwr(self, symbole, texte_rwr):
        from .exportdcs import SYMBOLES
        if symbole not in SYMBOLES and self._nouveau("rwr", symbole):
            self.ecrire("symbole_rwr_inconnu", symbole=symbole, rwr=texte_rwr)

    def page(self, numero, texte):
        """Page de DDI non reconnue : on garde son contenu, une fois par 'forme'."""
        from .exportdcs import elements, page_ecran
        if page_ecran(texte) != "AUTRE":
            return
        noms = sorted({n for n, _v in elements(texte)})
        empreinte = hashlib.sha1("|".join(noms[:60]).encode()).hexdigest()[:12]
        if self._nouveau("pages", empreinte):
            self.ecrire("page_inconnue", ecran=numero, empreinte=empreinte, texte=texte)

    def alignement(self, ecrans, position_ins):
        """Pendant l'alignement de la centrale : on garde les ecrans toutes les
        10 s, pour apprendre a lire QUAL / OK et trouver STD HDG."""
        maintenant = time.time()
        if maintenant - getattr(self, "_dernier_alignement", 0) < 10:
            return
        self._dernier_alignement = maintenant
        self._n_alignement = getattr(self, "_n_alignement", 0) + 1
        if self._n_alignement > 60:
            return
        self.ecrire("alignement_ins", position_ins=position_ins,
                    ecrans={k: v for k, v in ecrans.items() if k in (2, 3, 4)})

    def arme(self, nom):
        if nom and self._nouveau("armes", nom):
            self.ecrire("arme_sans_annonce", arme=nom)

    def erreur(self, ou, ex):
        texte = "".join(traceback.format_exception(type(ex), ex, ex.__traceback__))[-3000:]
        cle = f"{ou}:{type(ex).__name__}:{ex}"[:200]
        if self._nouveau("erreurs", cle):
            self.ecrire("erreur", ou=ou, detail=texte)

    def marquer(self, app):
        """Instantane complet de ce que le copilote voit."""
        self.nb_marques += 1
        b = app.b
        bios = {}
        for ident in b.sorties:
            try:
                bios[ident] = b.lire(ident)
            except Exception:
                continue
        x = app.export
        self.ecrire(
            "marque", numero=self.nb_marques, page_stream_deck=app.page,
            message=app.message, procedure=app.ex.en_cours,
            menaces=app.surv.menaces, alertes=app.surv.actives,
            lien_dcs=bool(x and x.vivant),
            ecrans=dict(x.ecrans) if x else {}, emport=x.emport if x else None,
            leurres=x.leurres if x else None, dcs_bios=bios,
        )
        return self.nb_marques
