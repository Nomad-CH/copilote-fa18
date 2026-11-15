"""Affichage des touches : Stream Deck XL reel, ou fenetre de secours a l'ecran."""
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

COLS, RANGS = 8, 4
TAILLE = 96

# Couleurs : on garde ces noms dans les pages, le style "cockpit" (vert
# phosphore sur noir) est applique au dessin, comme sur la maquette.
SOMBRE = (22, 26, 32)        # information : fond vert tres sombre, sans cadre
GRIS = (58, 64, 72)          # bouton au repos : cadre vert
VERT = (0, 112, 62)          # actif / allume : touche pleine verte
AMBRE = (196, 122, 0)        # attention : cadre et texte ambre
ROUGE = (176, 24, 24)        # danger : touche pleine rouge
ROUGE_SOMBRE = (90, 10, 10)  # danger, phase eteinte du clignotement : cadre rouge
BLEU = (24, 72, 140)         # action (procedure) : cadre vert plus marque
BLEU_VIF = (30, 110, 210)    # page affichee : touche pleine verte
NOIR = (0, 0, 0)
INACTIF = (1, 1, 1)          # fonction a venir : tout en vert eteint

_FOND = (10, 14, 11)
_PANNEAU = (17, 24, 19)
_LIGNE = (31, 92, 54)
_VERT_VIF = (61, 220, 110)
_VERT_PALE = (143, 203, 162)
_ENCRE = (6, 18, 10)
_AMBRE = (255, 176, 32)
_ROUGE = (255, 106, 92)
_ROUGE_PLEIN = (200, 30, 30)

# style : (fond, cadre, couleur du titre, couleur de la valeur)
_STYLES = {
    SOMBRE: (_PANNEAU, None, _VERT_PALE, _VERT_VIF),
    GRIS: (_FOND, _LIGNE, _VERT_PALE, _VERT_VIF),
    BLEU: (_FOND, (46, 140, 80), _VERT_VIF, _VERT_VIF),
    VERT: (_VERT_VIF, None, _ENCRE, _ENCRE),
    BLEU_VIF: (_VERT_VIF, None, _ENCRE, _ENCRE),
    AMBRE: (_FOND, _AMBRE, _AMBRE, _AMBRE),
    ROUGE: (_ROUGE_PLEIN, None, (255, 230, 225), (255, 255, 255)),
    ROUGE_SOMBRE: (_FOND, _ROUGE, _ROUGE, _ROUGE),
    INACTIF: (_FOND, (28, 40, 32), (58, 90, 68), (58, 90, 68)),
}

from .chemins import ressource
_DOSSIER_POLICES = ressource("polices")
_POLICES = [os.path.join(_DOSSIER_POLICES, "B612Mono-Bold.ttf"),
            "consolab.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
_cache_police = {}


def police(taille):
    if taille not in _cache_police:
        f = None
        for nom in _POLICES:
            try:
                f = ImageFont.truetype(nom, taille)
                break
            except OSError:
                continue
        _cache_police[taille] = f or ImageFont.load_default()
    return _cache_police[taille]


class Touche:
    """Une touche : petit titre en haut, valeur en grand, et un style."""

    def __init__(self, titre="", valeur="", fond=GRIS, action=None, confirmer=False):
        self.titre, self.valeur, self.fond = titre, valeur, fond
        self.action, self.confirmer = action, confirmer

    def signature(self):
        return (self.titre, self.valeur, self.fond)


VIDE = Touche(fond=NOIR)


def _ajuster(d, lignes, largeur, hauteur, maxi, mini=9):
    """Plus grande police avec laquelle toutes les lignes tiennent."""
    for t in range(maxi, mini - 1, -1):
        f = police(t)
        boites = [d.textbbox((0, 0), l, font=f) for l in lignes]
        w = max(b[2] - b[0] for b in boites)
        h = (t + 3) * len(lignes)
        if w <= largeur and h <= hauteur:
            return f, t
    return police(mini), mini


def dessiner(touche):
    img = Image.new("RGB", (TAILLE, TAILLE), NOIR)
    d = ImageDraw.Draw(img)
    if touche.fond == NOIR:
        return img
    fond, cadre, c_titre, c_valeur = _STYLES.get(
        touche.fond, (touche.fond, None, (220, 220, 220), (255, 255, 255)))
    d.rounded_rectangle((1, 1, TAILLE - 2, TAILLE - 2), radius=10, fill=fond,
                        outline=cadre, width=3 if cadre else 0)
    marge = 7
    haut = marge
    if touche.titre and touche.valeur:
        lignes = touche.titre.split("\n")
        f, t = _ajuster(d, lignes, TAILLE - 2 * marge, 30, 13)
        for l in lignes:
            d.text((TAILLE / 2, haut), l, font=f, fill=c_titre, anchor="ma")
            haut += t + 2
        haut += 2
    corps = touche.valeur or touche.titre
    if corps:
        lignes = corps.split("\n")
        dispo = TAILLE - haut - marge
        f, t = _ajuster(d, lignes, TAILLE - 2 * marge, dispo, 24 if touche.valeur else 17)
        total = (t + 3) * len(lignes)
        y = haut + (dispo - total) / 2
        for l in lignes:
            d.text((TAILLE / 2, y), l, font=f, fill=c_valeur if touche.valeur else c_titre,
                   anchor="ma")
            y += t + 3
    return img


def couper(texte, largeur=13, lignes=5):
    """Coupe un message en lignes courtes pour une touche."""
    mots, out, cur = texte.split(), [], ""
    for m in mots:
        if len(cur) + len(m) + (1 if cur else 0) <= largeur:
            cur = (cur + " " + m).strip()
        else:
            out.append(cur)
            cur = m
    if cur:
        out.append(cur)
    if len(out) > lignes:
        out = out[:lignes]
        out[-1] = out[-1][:largeur - 1] + "…"
    return "\n".join(out)


# ------------------------------------------------------------ Stream Deck
class StreamDeckXL:
    nom = "Stream Deck XL"

    def __init__(self, luminosite=70):
        from StreamDeck.DeviceManager import DeviceManager
        from StreamDeck.ImageHelpers import PILHelper
        self._aide = PILHelper
        trouves = [d for d in DeviceManager().enumerate() if d.key_count() == COLS * RANGS]
        if not trouves:
            raise RuntimeError("aucun Stream Deck XL détecté")
        self.d = trouves[0]
        self.d.open()
        self.d.reset()
        self.d.set_brightness(luminosite)

    def sur_appui(self, rappel):
        def cb(_deck, index, enfonce):
            if enfonce:
                rappel(index)
        self.d.set_key_callback(cb)

    def afficher(self, index, image):
        conv = getattr(self._aide, "to_native_key_format", None) or self._aide.to_native_format
        natif = conv(self.d, image)
        with self.d:
            self.d.set_key_image(index, natif)

    def fermer(self):
        try:
            with self.d:
                self.d.reset()
                self.d.close()
        except Exception:
            pass

    def boucle(self, tick, periode):
        try:
            while True:
                tick()
                time.sleep(periode)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                with self.d:
                    self.d.reset()
                    self.d.close()
            except Exception:
                pass


# ------------------------------------------------------ fenetre de secours
class Fenetre:
    """Meme grille 8 x 4 dans une fenetre : pour essayer sans Stream Deck."""
    nom = "Stream Deck virtuel"

    def __init__(self, master=None):
        import tkinter as tk
        from PIL import ImageTk
        self._tk, self._ImageTk = tk, ImageTk
        self.racine = tk.Toplevel(master) if master is not None else tk.Tk()
        self.racine.title("Copilote F/A-18 - Stream Deck virtuel")
        self.racine.configure(bg="black")
        self.racine.attributes("-topmost", True)
        self.racine.protocol("WM_DELETE_WINDOW", self.cacher)
        self._labels, self._photos, self._rappel = [], [None] * (COLS * RANGS), None
        for i in range(COLS * RANGS):
            lab = tk.Label(self.racine, bd=0, bg="black")
            lab.grid(row=i // COLS, column=i % COLS, padx=3, pady=3)
            lab.bind("<Button-1>", lambda _e, k=i: self._rappel and self._rappel(k))
            self._labels.append(lab)

    def sur_appui(self, rappel):
        self._rappel = rappel

    def afficher(self, index, image):
        ph = self._ImageTk.PhotoImage(image)
        self._photos[index] = ph
        self._labels[index].configure(image=ph)

    def cacher(self):
        self.racine.withdraw()

    def montrer(self):
        self.racine.deiconify()
        self.racine.lift()

    def fermer(self):
        try:
            self.racine.destroy()
        except Exception:
            pass

    def boucle(self, tick, periode):
        def pas():
            tick()
            self.racine.after(int(periode * 1000), pas)
        pas()
        self.racine.mainloop()


def elgato_ouvert():
    """Le logiciel Stream Deck d'Elgato tourne-t-il ? (il se dispute l'appareil)"""
    if sys.platform != "win32":
        return False
    try:
        import subprocess
        sortie = subprocess.run(["tasklist", "/FI", "IMAGENAME eq StreamDeck.exe", "/NH"],
                                capture_output=True, text=True, timeout=5,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return "streamdeck.exe" in sortie.lower()
    except Exception:
        return False


AVERTISSEMENT_ELGATO = ("Le logiciel Stream Deck d'Elgato est ouvert : il se dispute les touches "
                        "avec le copilote. Ferme-le (icône près de l'horloge, clic droit, Quitter).")


def ouvrir_stream_deck(luminosite=70, dossier_app=""):
    """Stream Deck XL si possible, sinon (None, raison)."""
    if dossier_app:  # hidapi.dll est range a cote du programme
        os.environ["PATH"] = dossier_app + os.pathsep + os.environ.get("PATH", "")
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(dossier_app)
            except OSError:
                pass
    try:
        return StreamDeckXL(luminosite), ""
    except Exception as ex:
        return None, (f"Stream Deck XL indisponible ({ex}). Ferme le logiciel Elgato "
                      "Stream Deck s'il tourne, puis relance.")


def ouvrir(forcer_fenetre=False, luminosite=70, dossier_app="", master=None):
    """Renvoie (ecran, remarque). Stream Deck XL si possible, sinon fenetre."""
    if not forcer_fenetre:
        ecran, remarque = ouvrir_stream_deck(luminosite, dossier_app)
        if ecran is not None:
            return ecran, AVERTISSEMENT_ELGATO if elgato_ouvert() else ""
        return Fenetre(master), remarque
    return Fenetre(master), ""
