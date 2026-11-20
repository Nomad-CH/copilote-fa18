"""Images du guide de reference de l'utilisateur (DCS Reference Guide v35).

Ces images appartiennent a leur auteur : elles ne sont PAS livrees avec le programme.
L'utilisateur indique son propre fichier du guide ; on en copie les pages du Hornet
dans son dossier de donnees, sur son PC, et la tablette les affiche a partir de la.
"""
import os
import re
import shutil
import zipfile

from .chemins import DONNEES

DOSSIER = os.path.join(DONNEES, "guide")
PAGES = ("86", "88", "89", "90", "91")      # couverture (vue de face) et pages d'armement
_MOTIF = re.compile(r"FA-18C_Hornet[/\\]DCS_ReferenceGuide_v35(\d+)\.jpg$", re.I)


def pages_presentes():
    return [p for p in PAGES if os.path.isfile(os.path.join(DOSSIER, p + ".jpg"))]


def complet():
    return len(pages_presentes()) == len(PAGES)


def chemin_page(numero):
    if numero not in PAGES:
        return None
    f = os.path.join(DOSSIER, numero + ".jpg")
    return f if os.path.isfile(f) else None


def importer(source):
    """source : le .zip du guide, ou un dossier qui contient Kneeboards/FA-18C_Hornet.
    -> nombre de pages copiees."""
    os.makedirs(DOSSIER, exist_ok=True)
    n = 0
    if os.path.isdir(source):
        for racine, _, fichiers in os.walk(source):
            for nom in fichiers:
                m = _MOTIF.search(os.path.join(racine, nom))
                if m and m.group(1) in PAGES:
                    shutil.copyfile(os.path.join(racine, nom), os.path.join(DOSSIER, m.group(1) + ".jpg"))
                    n += 1
        return n
    with zipfile.ZipFile(source) as z:
        for info in z.infolist():
            m = _MOTIF.search(info.filename)
            if m and m.group(1) in PAGES and info.file_size < 5_000_000:
                with z.open(info) as src, open(os.path.join(DOSSIER, m.group(1) + ".jpg"), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                n += 1
    return n
