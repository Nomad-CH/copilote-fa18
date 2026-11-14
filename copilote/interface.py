"""La fenetre de l'application, au style cockpit (vert phosphore sur noir).

Trois formes, a choisir aussi depuis le Stream Deck (touche FENETRE) :
  - pleine  : etat, messages, liaison avec DCS, reglages ;
  - barre   : une ligne fine dans un coin, toujours visible par-dessus DCS ;
  - cachee  : rien a l'ecran, le copilote continue de tourner.
"""
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

from . import __version__, bios as bios_mod, deck, diagnostic, envoi, exportdcs, installation, maj, touches
from .app import Copilote
from .chemins import DONNEES, PROGRAMME, RESSOURCES, ressource, sauver_config
from .exportdcs import SYMBOLES

FOND = "#0A0E0B"
PANNEAU = "#111813"
LIGNE = "#1F5C36"
VERT = "#3DDC6E"
PALE = "#8FCBA2"
ENCRE = "#06120A"
AMBRE = "#FFB020"
ROUGE = "#FF6A5C"
ROUGE_PLEIN = "#C81E1E"
GRIS = "#4E6B58"

COINS = ("haut-droite", "haut-gauche", "bas-gauche", "bas-droite")


def _charger_police():
    """Charge B612 Mono pour ce programme seulement (rien n'est installe dans Windows)."""
    chemin = ressource("polices", "B612Mono-Bold.ttf")
    if sys.platform == "win32" and os.path.isfile(chemin):
        try:
            import ctypes
            ctypes.windll.gdi32.AddFontResourceExW(chemin, 0x10, 0)      # FR_PRIVATE
            ctypes.windll.gdi32.AddFontResourceExW(
                ressource("polices", "B612Mono-Regular.ttf"), 0x10, 0)
            return "B612 Mono"
        except Exception:
            pass
    return "Consolas" if sys.platform == "win32" else "DejaVu Sans Mono"


class Bouton(tk.Label):
    """Bouton plat, cadre vert : comme une touche du Stream Deck."""

    def __init__(self, parent, texte, action, police, couleur=VERT, **kw):
        super().__init__(parent, text=texte, bg=FOND, fg=couleur, font=police, cursor="hand2",
                         highlightthickness=2, highlightbackground=LIGNE, highlightcolor=LIGNE,
                         padx=8, pady=7, **kw)
        self.action = action
        self.bind("<Button-1>", lambda _e: self.action())
        self.bind("<Enter>", lambda _e: self.configure(bg=PANNEAU))
        self.bind("<Leave>", lambda _e: self.configure(bg=FOND))

    def couleur(self, c):
        self.configure(fg=c, highlightbackground=c if c != VERT else LIGNE)


class Interface:
    def __init__(self, cfg):
        self.cfg = cfg
        self.racine = tk.Tk()
        self.racine.title(f"Copilote F/A-18  {__version__}")
        self.racine.configure(bg=FOND)
        self.racine.geometry("470x760")
        self.racine.minsize(420, 600)
        try:
            self.racine.iconbitmap(ressource("icone.ico"))
        except Exception:
            pass
        self.racine.protocol("WM_DELETE_WINDOW", self.quitter)
        famille = _charger_police()
        self.p_titre = (famille, 13, "bold")
        self.p_texte = (famille, 10)
        self.p_petit = (famille, 9)
        self.p_bouton = (famille, 10, "bold")
        self._taches = queue.Queue()   # actions a faire dans le fil de la fenetre
        self.mode = "pleine"
        self.coin = 0
        self.maj_dispo = None
        self.demo_stop = None
        self._vus = 0

        self._construire()
        self._demarrer_copilote()
        self._construire_barre()
        threading.Thread(target=self._verifier_maj, daemon=True).start()
        self.racine.after(150, self._boucle)

    # ================================================================ fenetre
    def _construire(self):
        r = self.racine
        haut = tk.Frame(r, bg=PANNEAU)
        haut.pack(fill="x")
        tk.Label(haut, text="COPILOTE F/A-18", bg=PANNEAU, fg=VERT, font=self.p_titre,
                 padx=14, pady=10).pack(side="left")
        self.l_etat = tk.Label(haut, text="DÉMARRAGE", bg=GRIS, fg=ENCRE, font=self.p_petit,
                               padx=8, pady=2)
        self.l_etat.pack(side="right", padx=12)
        tk.Frame(r, bg=LIGNE, height=2).pack(fill="x")

        self.l_menace = tk.Label(r, text="", bg=ROUGE_PLEIN, fg="white", font=self.p_titre, pady=6)

        self.cadre_corps = tk.Frame(r, bg=FOND)
        self.cadre_corps.pack(fill="both", expand=True, padx=14, pady=10)
        c = self.cadre_corps

        self._titre(c, "MESSAGES DU COPILOTE")
        self.t_messages = tk.Text(c, height=11, bg=PANNEAU, fg=VERT, font=self.p_texte,
                                  relief="flat", wrap="word", padx=8, pady=6,
                                  highlightthickness=1, highlightbackground=LIGNE)
        self.t_messages.tag_configure("heure", foreground=GRIS)
        self.t_messages.tag_configure("urgent", foreground=ROUGE)
        self.t_messages.configure(state="disabled")
        self.t_messages.pack(fill="x", pady=(0, 10))

        self._titre(c, "LIAISON")
        self.l_liaison = {}
        for cle, texte in (("dcs", "DCS (DCS-BIOS)"), ("lien", "Lien RWR / écrans"),
                           ("deck", "Stream Deck XL")):
            ligne = tk.Frame(c, bg=FOND)
            ligne.pack(fill="x")
            tk.Label(ligne, text=texte, bg=FOND, fg=PALE, font=self.p_texte).pack(side="left")
            lab = tk.Label(ligne, text="...", bg=FOND, fg=GRIS, font=self.p_texte)
            lab.pack(side="right")
            self.l_liaison[cle] = lab
        self.b_reparer = Bouton(c, "INSTALLER LA LIAISON AVEC DCS", self.reparer_liaison,
                                self.p_bouton, AMBRE)
        tk.Frame(c, bg=FOND, height=10).pack()

        self._titre(c, "RÉGLAGES")
        grille = tk.Frame(c, bg=FOND)
        grille.pack(fill="x")
        grille.columnconfigure(0, weight=1, uniform="b")
        grille.columnconfigure(1, weight=1, uniform="b")
        self.b_voix = Bouton(grille, "VOIX : ON", self.basculer_voix, self.p_bouton)
        self.b_choix = Bouton(grille, "CHOISIR LA VOIX", self.choisir_voix, self.p_bouton)
        self.b_touches = Bouton(grille, "VÉRIFIER LES TOUCHES", self.verifier_touches, self.p_bouton)
        self.b_diag = Bouton(grille, "DIAGNOSTIC", self.faire_diagnostic, self.p_bouton)
        self.b_demo = Bouton(grille, "MODE DÉMO", self.basculer_demo, self.p_bouton)
        self.b_virtuel = Bouton(grille, "STREAM DECK VIRTUEL", self.montrer_virtuel, self.p_bouton)
        self.b_maj = Bouton(grille, f"VERSION {__version__}", self.mettre_a_jour, self.p_bouton,
                            PALE)
        self.b_reduire = Bouton(grille, "RÉDUIRE EN BARRE", lambda: self.changer_mode("barre"),
                                self.p_bouton)
        self.b_ravito = Bouton(grille, "RADIO RAVITO", self.regler_ravito, self.p_bouton)
        self.b_envoi = Bouton(grille, "ENVOI À CLAUDE", self.regler_envoi, self.p_bouton)
        for i, b in enumerate((self.b_voix, self.b_choix, self.b_touches, self.b_diag,
                               self.b_demo, self.b_virtuel, self.b_ravito, self.b_envoi,
                               self.b_maj, self.b_reduire)):
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)

        bas = tk.Label(r, text="Dossier de tes données", bg=FOND, fg=GRIS, font=self.p_petit,
                       cursor="hand2", pady=6)
        bas.pack(side="bottom")
        bas.bind("<Button-1>", lambda _e: self._ouvrir_dossier(DONNEES))

    def _titre(self, parent, texte):
        tk.Label(parent, text=texte, bg=FOND, fg=PALE, font=self.p_petit,
                 anchor="w").pack(fill="x", pady=(0, 3))

    def _construire_barre(self):
        """Barre compacte : toujours au-dessus, sans bordure."""
        b = self.barre = tk.Toplevel(self.racine)
        b.overrideredirect(True)
        b.attributes("-topmost", True)
        b.configure(bg=FOND, highlightthickness=2, highlightbackground=LIGNE)
        self.bl_etat = tk.Label(b, text="", bg=GRIS, fg=ENCRE, font=self.p_petit, padx=6)
        self.bl_etat.pack(side="left", padx=8, pady=8)
        self.bl_message = tk.Label(b, text="", bg=FOND, fg=VERT, font=self.p_texte, anchor="w")
        self.bl_message.pack(side="left", fill="x", expand=True, padx=(0, 8))
        for w in (b, self.bl_message):
            w.bind("<Button-1>", lambda _e: self.changer_mode("pleine"))
        b.withdraw()

    def _placer_barre(self):
        largeur, hauteur = 560, 40
        ecran_l, ecran_h = self.racine.winfo_screenwidth(), self.racine.winfo_screenheight()
        coin = COINS[self.coin]
        x = 20 if "gauche" in coin else ecran_l - largeur - 20
        y = 20 if "haut" in coin else ecran_h - hauteur - 70
        self.barre.geometry(f"{largeur}x{hauteur}+{x}+{y}")

    def changer_mode(self, mode):
        self.mode = mode
        self.app.mode_fenetre = mode
        if mode == "pleine":
            self.barre.withdraw()
            self.racine.deiconify()
            self.racine.lift()
        elif mode == "barre":
            self.racine.withdraw()
            self._placer_barre()
            self.barre.deiconify()
        else:
            self.racine.withdraw()
            self.barre.withdraw()

    # ============================================================== copilote
    def _demarrer_copilote(self):
        cfg = self.cfg
        cfg["touches"], messages_touches = touches.verifier(cfg)
        dossier_json = bios_mod.trouver_dossier_json(cfg.get("dcs_bios_json", ""))
        self.dossier_json = dossier_json
        self.b = bios_mod.Bios(dossier_json, cfg.get("dcs_bios_hote", "127.0.0.1"),
                               int(cfg.get("dcs_bios_port", 7778)))
        self.export = exportdcs.ExportDCS(int(cfg.get("export_port", 7790)))
        for dossier in (RESSOURCES, PROGRAMME):      # hidapi.dll est livre avec le programme
            ecran, remarque = deck.ouvrir_stream_deck(int(cfg.get("luminosite", 70)), dossier)
            if ecran is not None:
                break
        self.deck_physique = ecran is not None
        self.virtuel = deck.Fenetre(self.racine)
        if ecran is None:
            ecran = self.virtuel
        else:
            self.virtuel.cacher()
            # le virtuel montre la meme chose que le vrai
            ecran = _Double(ecran, self.virtuel)
        self.app = Copilote(self.b, cfg, ecran, self.export)
        self.app.mode_fenetre = self.mode
        self.export.demarrer()
        self.b.demarrer()
        if remarque:
            self.app.dire(remarque)
        for m in messages_touches:
            self.app.dire(m)
        try:
            if installation.mettre_lien_a_jour():
                self.app.dire("Lien RWR / écrans mis à jour : redémarre DCS s'il est ouvert.")
        except OSError:
            pass
        if not installation.tout_va_bien():
            self.app.dire("La liaison avec DCS n'est pas installée : bouton "
                          "« Installer la liaison avec DCS ».")

    def _boucle(self):
        try:
            self.app.tick()
            while not self.app.demandes_fenetre.empty():
                action = self.app.demandes_fenetre.get_nowait()
                if action == "suivante":
                    suivant = {"pleine": "barre", "barre": "cachee", "cachee": "pleine"}
                    self.changer_mode(suivant[self.mode])
                elif action == "coin":
                    self.coin = (self.coin + 1) % len(COINS)
                    if self.mode != "barre":
                        self.changer_mode("barre")
                    self._placer_barre()
            while not self._taches.empty():
                self._taches.get_nowait()()
            self._fin_de_vol()
            self._rafraichir()
        except Exception as ex:
            self.app.boite.erreur("fenêtre", ex)
        self.racine.after(150, self._boucle)

    def _etat_texte(self):
        b = self.b
        if self.app.surv.menaces:
            m = self.app.surv.menaces
            sym = sorted(m, key=lambda s: (m[s]["niveau"] != "clignote", s))[0]
            nom = SYMBOLES.get(sym, sym)
            return ("MENACE", ROUGE_PLEIN if m[sym]["niveau"] == "clignote" else AMBRE, nom)
        if b.en_pause:
            return ("PAUSE", AMBRE, None)
        if b.en_f18:
            return ("EN LIGNE", VERT, None)
        if b.connecte:
            return ("PAS UN F/A-18", AMBRE, None)
        return ("EN ATTENTE DE DCS", GRIS, None)

    def _fin_de_vol(self):
        """Quand tu quittes le Hornet : envoi automatique de la boite noire."""
        en_f18 = self.b.en_f18
        if getattr(self, "_etait_en_vol", False) and not en_f18 and envoi.configure(self.cfg) \
                and self.cfg.get("envoi_auto", True) and not self.demo_stop:
            threading.Thread(target=self._envoyer_diagnostic, daemon=True).start()
        self._etait_en_vol = en_f18

    def _rafraichir(self):
        texte, couleur, menace = self._etat_texte()
        fg = "white" if couleur == ROUGE_PLEIN else ENCRE
        self.l_etat.configure(text=texte, bg=couleur, fg=fg)
        self.bl_etat.configure(text=texte, bg=couleur, fg=fg)
        if menace:
            niveau = "NOUS ACCROCHE" if couleur == ROUGE_PLEIN else "AU RWR"
            self.l_menace.configure(text=f"{menace}  {niveau}",
                                    bg=couleur, fg=fg)
            if not self.l_menace.winfo_ismapped():
                self.l_menace.pack(fill="x", before=self.cadre_corps)
        elif self.l_menace.winfo_ismapped():
            self.l_menace.pack_forget()
        self.bl_message.configure(text=(f"{menace}  |  " if menace else "") + self.app.message)

        # messages : on n'ajoute que les nouveaux
        hist = list(self.app.historique)
        n_nouveaux = min(self.app.nb_messages - self._vus, len(hist))
        nouveaux = hist[len(hist) - n_nouveaux:] if n_nouveaux > 0 else []
        if nouveaux:
            self.t_messages.configure(state="normal")
            for heure, texte_m, urgent in nouveaux:
                self.t_messages.insert("1.0", texte_m + "\n", ("urgent",) if urgent else ())
                self.t_messages.insert("1.0", heure + "  ", ("heure",))
            self.t_messages.delete("60.0", "end")
            self.t_messages.configure(state="disabled")
        self._vus = self.app.nb_messages

        # liaison (toutes les 2 s environ)
        if int(time.time() * 10) % 20 == 0:
            etat = installation.etat()
            ok_bios = bool(etat) and all(x["dcs_bios"] for x in etat)
            ok_lien = bool(etat) and all(x["lien"] for x in etat)
            self._marque("dcs", ("CONNECTÉ" if self.b.connecte else "INSTALLÉ") if ok_bios
                         else "ABSENT", ok_bios)
            self._marque("lien", ("REÇU" if self.export.vivant else "INSTALLÉ") if ok_lien
                         else "ABSENT", ok_lien)
            self._marque("deck", "BRANCHÉ" if self.deck_physique else "VIRTUEL",
                         self.deck_physique)
            if ok_bios and ok_lien:
                self.b_reparer.pack_forget()
            elif not self.b_reparer.winfo_ismapped():
                self.b_reparer.pack(fill="x", pady=(6, 0))
        voix = self.app.voix
        self.b_voix.configure(text=f"VOIX : {'ON' if voix.active else 'OFF'}")
        if self.maj_dispo:
            self.b_maj.configure(text=f"MISE À JOUR {self.maj_dispo[0]}")
            self.b_maj.couleur(AMBRE)
        self.b_demo.configure(text="ARRÊTER LA DÉMO" if self.demo_stop else "MODE DÉMO")

    def _marque(self, cle, texte, ok):
        self.l_liaison[cle].configure(text=texte, fg=VERT if ok else AMBRE)

    # =============================================================== actions
    def basculer_voix(self):
        actif = self.app.voix.basculer()
        self.cfg["voix"] = actif
        sauver_config(self.cfg)

    def choisir_voix(self):
        ChoixVoix(self)

    def verifier_touches(self):
        nouvelles, messages = touches.verifier(self.cfg)
        self.cfg["touches"] = nouvelles
        if messages:
            messagebox.showinfo("Touches DCS", "\n\n".join(messages), parent=self.racine)
        else:
            messagebox.showinfo("Touches DCS", "Tout est bon : je trouve les quatre "
                                "commandes des manettes des gaz dans tes réglages DCS.",
                                parent=self.racine)

    def faire_diagnostic(self):
        if envoi.configure(self.cfg):
            self.app.dire("Diagnostic en cours d'envoi.")
            threading.Thread(target=self._envoyer_diagnostic, args=(True,), daemon=True).start()
            return

        def travail():
            try:
                chemin = diagnostic.creer_zip(self.app)
            except Exception as ex:
                erreur = str(ex)
                self._taches.put(lambda: messagebox.showerror(
                    "Diagnostic", f"Impossible de créer le diagnostic : {erreur}",
                    parent=self.racine))
                return

            def fini():
                messagebox.showinfo("Diagnostic", "Fichier prêt. Envoie-le à Claude dans "
                                    "la conversation :\n\n" + chemin, parent=self.racine)
                self._ouvrir_dossier(chemin, selection=True)
            self._taches.put(fini)
        self.app.dire("Je prépare le diagnostic.")
        threading.Thread(target=travail, daemon=True).start()

    def _envoyer_diagnostic(self, signaler=False):
        try:
            chemin = diagnostic.creer_zip(self.app)
            envoi.envoyer(chemin, self.cfg)
            self.app.dire("Diagnostic transmis.")
        except Exception as ex:
            self.app.dire(f"Négatif, envoi du diagnostic impossible : {ex}")
            self.app.boite.erreur("envoi diagnostic", ex)

    def regler_ravito(self):
        from tkinter import simpledialog
        actuelle = self.cfg.get("radio_ravito", "")
        rep = simpledialog.askstring(
            "Radio : demande de ravitaillement",
            "Touches F à enchaîner après l'ouverture du menu radio de DCS,\n"
            "dans l'ordre où tu les presses pour demander le ravitaillement.\n"
            "Exemple : F5 F1 F1   (laisser vide = ouvrir seulement le menu)",
            initialvalue=actuelle, parent=self.racine)
        if rep is None:
            return
        self.cfg["radio_ravito"] = " ".join(rep.upper().replace(",", " ").split())
        sauver_config(self.cfg)
        self.app.dire("Séquence ravitaillement enregistrée.")

    def regler_envoi(self):
        ReglageEnvoi(self)

    def basculer_demo(self):
        from . import demo
        if self.demo_stop:
            self.demo_stop.set()
            self.demo_stop = None
            self.app.dire("Démo arrêtée.")
            return
        if self.b.connecte:
            messagebox.showinfo("Mode démo", "DCS est connecté : ferme DCS avant de lancer "
                                "la démo.", parent=self.racine)
            return
        self.demo_stop = threading.Event()
        demo.lancer(self.dossier_json, self.demo_stop)
        self.app.dire("Démo : un Hornet simulé au sol. MiG-29 au RWR vers 15 secondes, "
                      "SA-8 vers 30 secondes.")

    def montrer_virtuel(self):
        self.virtuel.montrer()

    def reparer_liaison(self):
        if not messagebox.askyesno(
                "Liaison avec DCS",
                "Je vais installer DCS-BIOS et le lien du copilote dans ton dossier "
                "Saved Games\\DCS, et ajouter deux lignes à Export.lua (l'ancienne version "
                "est gardée en copie).\n\nD'accord ?", parent=self.racine):
            return

        def travail():
            try:
                installation.reparer(journal=self.app.dire)
            except Exception as ex:
                self.app.dire(f"Installation impossible : {ex}")
        threading.Thread(target=travail, daemon=True).start()

    def _verifier_maj(self):
        info = maj.derniere_version()
        if info and maj.plus_recente(info[0]):
            self.maj_dispo = info
            self.app.dire(f"Une nouvelle version du copilote est disponible : {info[0]}.")

    def mettre_a_jour(self):
        if not self.maj_dispo:
            threading.Thread(target=self._verifier_maj, daemon=True).start()
            messagebox.showinfo("Mise à jour", f"Tu as la version {__version__}. Je vérifie "
                                "s'il y a plus récent ; si oui, ce bouton passe en ambre.",
                                parent=self.racine)
            return
        version, url, notes = self.maj_dispo
        if not messagebox.askyesno("Mise à jour", f"Installer la version {version} ?\n\n"
                                   f"{(notes or '')[:600]}\n\nLe copilote va se fermer puis "
                                   "redémarrer.", parent=self.racine):
            return
        try:
            maj.installer(url, journal=self.app.dire)
        except Exception as ex:
            messagebox.showerror("Mise à jour", f"Échec : {ex}", parent=self.racine)
            return
        self.quitter(demander=False)

    def _ouvrir_dossier(self, chemin, selection=False):
        os.makedirs(DONNEES, exist_ok=True)
        if sys.platform == "win32":
            if selection:
                subprocess.Popen(["explorer", "/select,", chemin])
            else:
                os.startfile(chemin)  # noqa: S606

    def quitter(self, demander=True):
        if demander and self.b.en_f18 and not messagebox.askyesno(
                "Quitter", "Tu es en vol. Fermer le copilote ?", parent=self.racine):
            return
        try:
            self.app.ecran.fermer()
        except Exception:
            pass
        self.b.arreter()
        self.export.arreter()
        self.racine.destroy()

    def lancer(self):
        self.racine.mainloop()


class _Double:
    """Affiche sur le vrai Stream Deck et sur le virtuel en meme temps."""

    def __init__(self, vrai, virtuel):
        self.vrai, self.virtuel = vrai, virtuel
        self.nom = vrai.nom

    def sur_appui(self, rappel):
        self.vrai.sur_appui(rappel)
        self.virtuel.sur_appui(rappel)

    def afficher(self, index, image):
        self.vrai.afficher(index, image)
        self.virtuel.afficher(index, image)

    def fermer(self):
        self.vrai.fermer()


class ChoixVoix:
    """Ecouter et choisir la voix du copilote."""

    def __init__(self, ui):
        from . import voix as V
        self.ui, self.V = ui, V
        f = self.f = tk.Toplevel(ui.racine)
        f.title("Voix du copilote")
        f.configure(bg=FOND)
        f.transient(ui.racine)
        tk.Label(f, text="CHOISIR LA VOIX", bg=FOND, fg=VERT, font=ui.p_titre).pack(pady=(12, 2))
        tk.Label(f, text="ÉCOUTER pour entendre une phrase, CHOISIR pour la garder.",
                 bg=FOND, fg=PALE, font=ui.p_petit).pack(pady=(0, 8))
        self.l_info = tk.Label(f, text="", bg=FOND, fg=AMBRE, font=ui.p_petit)
        self.l_info.pack()
        liste = tk.Frame(f, bg=FOND)
        liste.pack(padx=14, pady=6)
        actuel = (ui.cfg.get("voix_moteur"), ui.cfg.get("voix_nom") or "")
        self.essai = None
        piper = V.piper_installe()
        for i, (moteur, nom, titre, qui, type_) in enumerate(V.CANDIDATS):
            dispo = moteur != "piper" or piper
            couleur = VERT if (moteur, nom) == actuel else (PALE if dispo else GRIS)
            marque = "► " if (moteur, nom) == actuel else "  "
            tk.Label(liste, text=f"{marque}{titre}", bg=FOND, fg=couleur, font=ui.p_bouton,
                     width=12, anchor="w").grid(row=i, column=0, sticky="w")
            tk.Label(liste, text=f"{qui}, {type_}", bg=FOND, fg=GRIS, font=ui.p_petit,
                     anchor="w").grid(row=i, column=1, sticky="w", padx=6)
            if dispo:
                Bouton(liste, "ÉCOUTER", lambda m=moteur, n=nom: self.ecouter(m, n),
                       ui.p_petit).grid(row=i, column=2, padx=3, pady=2)
                Bouton(liste, "CHOISIR", lambda m=moteur, n=nom, t=titre: self.choisir(m, n, t),
                       ui.p_petit).grid(row=i, column=3, padx=3, pady=2)
        if not piper:
            Bouton(f, "TÉLÉCHARGER LES VOIX HORS LIGNE (PIPER, ~200 MO)", self.telecharger,
                   ui.p_petit, AMBRE).pack(fill="x", padx=14, pady=(4, 12))

    def ecouter(self, moteur, nom):
        from .chemins import VOIX_CACHE
        self.l_info.configure(text="Préparation de la phrase...")
        self.essai = self.V.Voix(True, 1, moteur, nom, cache=os.path.join(VOIX_CACHE, "essai"))
        if not self.essai.moteur.ok:
            self.l_info.configure(text="Cette voix n'est pas disponible sur ce PC.")
            return
        self.essai.dire(self.V.PHRASE_ESSAI)
        self.f.after(4000, lambda: self.l_info.configure(text=""))

    def choisir(self, moteur, nom, titre):
        ui = self.ui
        ui.cfg["voix_moteur"], ui.cfg["voix_nom"] = moteur, nom
        sauver_config(ui.cfg)
        actif = ui.app.voix.active
        ui.app.voix.active = False
        ui.app.voix = self.V.Voix.depuis_config(ui.cfg)
        ui.app.voix.active = actif
        ui.app.voix.preparer(self.V.phrases_connues())
        ui.app.dire(f"Voix {titre}. En ligne.")
        self.f.destroy()

    def telecharger(self):
        def travail():
            try:
                self.V.installer_piper(journal=lambda t: self.ui._taches.put(
                    lambda: self.l_info.configure(text=t)))
                self.ui._taches.put(lambda: (self.f.destroy(), ChoixVoix(self.ui)))
            except Exception as ex:
                erreur = str(ex)
                self.ui._taches.put(lambda: self.l_info.configure(
                    text=f"Téléchargement impossible : {erreur}"))
        threading.Thread(target=travail, daemon=True).start()


class ReglageEnvoi:
    """Depot prive + cle GitHub pour envoyer les diagnostics a Claude."""

    def __init__(self, ui):
        self.ui = ui
        f = self.f = tk.Toplevel(ui.racine)
        f.title("Envoi des diagnostics à Claude")
        f.configure(bg=FOND)
        f.transient(ui.racine)
        tk.Label(f, text="ENVOI DES DIAGNOSTICS", bg=FOND, fg=VERT, font=ui.p_titre).pack(pady=(12, 4))
        tk.Label(f, text="Dépôt GitHub PRIVÉ, puis clé d'accès limitée à ce dépôt.\n"
                 "La clé reste sur ce PC.", bg=FOND, fg=PALE, font=ui.p_petit,
                 justify="center").pack(pady=(0, 8))
        self.v_depot = tk.StringVar(value=ui.cfg.get("diag_depot") or "Nomad-CH/copilote-fa18-diagnostics")
        self.v_cle = tk.StringVar(value=ui.cfg.get("diag_cle", ""))
        self.v_auto = tk.BooleanVar(value=ui.cfg.get("envoi_auto", True))
        for texte, var, cache in (("Dépôt", self.v_depot, False), ("Clé", self.v_cle, True)):
            ligne = tk.Frame(f, bg=FOND)
            ligne.pack(fill="x", padx=14, pady=3)
            tk.Label(ligne, text=texte, bg=FOND, fg=PALE, font=ui.p_texte, width=7,
                     anchor="w").pack(side="left")
            tk.Entry(ligne, textvariable=var, show="•" if cache else "", width=44, bg=PANNEAU,
                     fg=VERT, insertbackground=VERT, relief="flat", font=ui.p_texte,
                     highlightthickness=1, highlightbackground=LIGNE).pack(side="left", fill="x")
        tk.Checkbutton(f, text="Envoyer automatiquement après chaque vol", variable=self.v_auto,
                       bg=FOND, fg=PALE, selectcolor=PANNEAU, activebackground=FOND,
                       activeforeground=VERT, font=ui.p_petit).pack(pady=6)
        self.l_info = tk.Label(f, text="", bg=FOND, fg=AMBRE, font=ui.p_petit, wraplength=420)
        self.l_info.pack(pady=4)
        boutons = tk.Frame(f, bg=FOND)
        boutons.pack(pady=(4, 14))
        Bouton(boutons, "TESTER", self.tester, ui.p_bouton).pack(side="left", padx=4)
        Bouton(boutons, "ENREGISTRER", self.enregistrer, ui.p_bouton).pack(side="left", padx=4)

    def tester(self):
        self.l_info.configure(text="Test en cours...", fg=PALE)

        def travail():
            ok, msg = envoi.tester(self.v_depot.get().strip(), self.v_cle.get().strip())
            self.ui._taches.put(lambda: self.l_info.configure(text=msg, fg=VERT if ok else AMBRE))
        threading.Thread(target=travail, daemon=True).start()

    def enregistrer(self):
        cfg = self.ui.cfg
        cfg["diag_depot"] = self.v_depot.get().strip()
        cfg["diag_cle"] = self.v_cle.get().strip()
        cfg["envoi_auto"] = bool(self.v_auto.get())
        sauver_config(cfg)
        self.ui.app.dire("Envoi des diagnostics configuré.")
        self.f.destroy()
