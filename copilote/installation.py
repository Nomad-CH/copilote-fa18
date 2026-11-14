"""Liaison avec DCS : installation et verification de DCS-BIOS et du lien du copilote.

L'application appelle etat() au lancement et propose reparer() si quelque
chose manque. Rien n'est modifie dans DCS sans ton accord (la fenetre demande).
"""
import glob
import io
import json
import os
import shutil
import urllib.request
import zipfile

from .chemins import ressource

BIOS_API = "https://api.github.com/repos/DCS-Skunkworks/dcs-bios/releases/latest"
BIOS_SECOURS = "https://github.com/DCS-Skunkworks/dcs-bios/releases/download/v0.11.9/DCS-BIOS_v0.11.9.zip"
LIGNE_BIOS = "dofile(lfs.writedir() .. [[Scripts\\DCS-BIOS\\BIOS.lua]])"
LIGNE_COPILOTE = "dofile(lfs.writedir() .. [[Scripts\\CopiloteExport.lua]])"
SCRIPT_LIEN = ressource("outils", "CopiloteExport.lua")


def telecharger(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "copilote-fa18"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def dossiers_dcs():
    """Dossiers 'Saved Games\\DCS*' (le plus recemment utilise d'abord)."""
    maison = os.path.expanduser("~")
    d = [x for x in glob.glob(os.path.join(maison, "Saved Games", "DCS*")) if os.path.isdir(x)]
    return sorted(d, key=os.path.getmtime, reverse=True)


def _lire(chemin):
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def etat():
    """Ce qui est en place, pour l'affichage. Une entree par dossier DCS."""
    out = []
    for d in dossiers_dcs():
        scripts = os.path.join(d, "Scripts")
        export = _lire(os.path.join(scripts, "Export.lua"))
        lien = os.path.join(scripts, "CopiloteExport.lua")
        out.append({
            "dossier": d,
            "dcs_bios": os.path.isfile(os.path.join(scripts, "DCS-BIOS", "BIOS.lua"))
            and "BIOS.lua" in export,
            "lien": "CopiloteExport.lua" in export and os.path.isfile(lien),
            "lien_a_jour": _lire(lien) == _lire(SCRIPT_LIEN),
        })
    return out


def tout_va_bien():
    e = etat()
    return bool(e) and all(x["dcs_bios"] and x["lien"] for x in e)


def mettre_lien_a_jour():
    """Le lien du copilote change avec les mises a jour : on le recopie seul,
    seulement la ou il est deja installe. Renvoie True si un fichier a change."""
    change = False
    for x in etat():
        if x["lien"] and not x["lien_a_jour"]:
            shutil.copyfile(SCRIPT_LIEN, os.path.join(x["dossier"], "Scripts", "CopiloteExport.lua"))
            change = True
    return change


def _url_dcs_bios():
    try:
        infos = json.loads(telecharger(BIOS_API, 20))
        for a in infos.get("assets", []):
            if a["name"].startswith("DCS-BIOS_") and a["name"].endswith(".zip"):
                return a["browser_download_url"], infos.get("tag_name", "")
    except Exception:
        pass
    return BIOS_SECOURS, "v0.11.9"


def reparer(journal=print):
    """Installe ce qui manque dans chaque dossier DCS. journal(texte) affiche l'avancement."""
    dossiers = dossiers_dcs()
    if not dossiers:
        journal("Dossier 'Saved Games\\DCS' introuvable : lance DCS une fois, puis recommence.")
        return False
    archive = None
    for d in dossiers:
        scripts = os.path.join(d, "Scripts")
        os.makedirs(scripts, exist_ok=True)
        if not os.path.isfile(os.path.join(scripts, "DCS-BIOS", "BIOS.lua")):
            if archive is None:
                url, version = _url_dcs_bios()
                journal(f"Téléchargement de DCS-BIOS {version}...")
                archive = zipfile.ZipFile(io.BytesIO(telecharger(url)))
            for nom in archive.namelist():
                if nom.startswith("DCS-BIOS/"):
                    archive.extract(nom, scripts)
            journal(f"DCS-BIOS installé dans {os.path.basename(d)}.")
        shutil.copyfile(SCRIPT_LIEN, os.path.join(scripts, "CopiloteExport.lua"))
        export = os.path.join(scripts, "Export.lua")
        contenu = _lire(export)
        a_ajouter = []
        if not ("DCS-BIOS" in contenu and "BIOS.lua" in contenu):
            a_ajouter.append(LIGNE_BIOS)
        if "CopiloteExport.lua" not in contenu:
            a_ajouter.append(LIGNE_COPILOTE)
        if a_ajouter:
            if contenu:
                shutil.copyfile(export, export + ".sauvegarde")
            with open(export, "a", encoding="utf-8") as f:
                f.write(("\n" if contenu and not contenu.endswith("\n") else "")
                        + "\n".join(a_ajouter) + "\n")
            journal(f"Export.lua de {os.path.basename(d)} complété"
                    + (" (ancienne version gardée en .sauvegarde)." if contenu else "."))
    journal("Liaison avec DCS en place. Redémarre DCS s'il est ouvert.")
    return True
