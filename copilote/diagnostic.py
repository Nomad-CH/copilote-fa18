"""Diagnostic : rassemble dans un zip ce qu'il faut a Claude pour comprendre
ce qui se passe (etat du PC, de DCS, des touches, boite noire, journal)."""
import glob
import os
import platform
import sys
import time
import zipfile

from . import __version__, installation, touches
from .chemins import BOITE_NOIRE, DONNEES, JOURNAL


def _lire(chemin, fin=None):
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            t = f.read()
    except OSError:
        return ""
    return t[-fin:] if fin else t


def rapport(app=None):
    lignes = [f"Copilote F/A-18 version {__version__}", f"Date : {time.strftime('%Y-%m-%d %H:%M')}",
              f"Windows : {platform.platform()}", f"Python : {sys.version.split()[0]}",
              f"Données : {DONNEES}", ""]
    if app is not None:
        lignes += [f"Affichage : {app.ecran.nom}", f"Voix : {app.voix.description}",
                   f"Liaison DCS-BIOS : {'oui' if app.b.connecte else 'non'}",
                   f"Lien RWR/écrans : {'oui' if app.export and app.export.vivant else 'non'}", ""]
    for x in installation.etat():
        lignes.append(f"DCS : {x['dossier']}  DCS-BIOS={x['dcs_bios']}  lien={x['lien']}  "
                      f"à jour={x['lien_a_jour']}")
    try:
        resultat, gaz, sources = touches.analyser()
        lignes += ["", f"Touches (défaut : {sources['defaut']})"]
        for besoin, r in resultat.items():
            lignes.append(f"  {touches.NOMS[besoin]} : {', '.join(r['combos']) or 'AUCUNE'}"
                          f"  <- {r['commande']}")
    except Exception as ex:
        lignes.append(f"Touches : lecture impossible ({ex})")
    return "\n".join(lignes)


def creer_zip(app=None):
    """Cree le zip dans le dossier de donnees et renvoie son chemin."""
    sortie = os.path.join(DONNEES, f"diagnostic_copilote_{time.strftime('%Y%m%d_%H%M')}.zip")
    os.makedirs(DONNEES, exist_ok=True)
    limite = time.time() - 3 * 86400          # les 3 derniers jours suffisent (zip plus leger)
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("rapport.txt", rapport(app))
        z.writestr("journal.txt", _lire(JOURNAL, 300000))
        for f in glob.glob(os.path.join(BOITE_NOIRE, "*")):
            if os.path.getmtime(f) >= limite:
                z.write(f, "boite_noire/" + os.path.basename(f))
        for d in installation.dossiers_dcs():
            nom = os.path.basename(d)
            z.writestr(f"{nom}/Export.lua", _lire(os.path.join(d, "Scripts", "Export.lua")))
            log = _lire(os.path.join(d, "Logs", "dcs.log"))
            # seulement ce qui concerne les scripts : les erreurs de textures ou de mission
            # de DCS ne nous apprennent rien
            garde = [l for l in log.splitlines() if any(m in l for m in (
                "Export", "BIOS", "Copilote", "LuaExport", "LUA", "Lua", "SCRIPTING"))]
            z.writestr(f"{nom}/dcs_log_extrait.txt", "\n".join(garde[-400:]))
            for f in touches.fichiers_diff_hornet([d]):
                z.write(f, f"{nom}/touches/" + os.path.basename(f))
    return sortie
