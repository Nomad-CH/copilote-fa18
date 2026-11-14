"""Mises a jour depuis GitHub (depot Nomad-CH/copilote-fa18).

Chaque version publiee sur GitHub contient un installateur CopiloteF18-Setup.exe.
L'application regarde au lancement s'il en existe une plus recente ; si tu
acceptes, elle la telecharge, la lance en mode silencieux et se ferme.
Tes donnees (%LOCALAPPDATA%\\CopiloteF18) ne sont pas touchees.
"""
import json
import os
import re
import subprocess
import tempfile
import urllib.request

from . import __version__

DEPOT = "Nomad-CH/copilote-fa18"


def _version(texte):
    return tuple(int(x) for x in re.findall(r"\d+", texte or "")[:3]) or (0,)


def derniere_version(timeout=10):
    """(version, url de l'installateur, notes) ou None si rien / pas d'Internet."""
    req = urllib.request.Request(f"https://api.github.com/repos/{DEPOT}/releases/latest",
                                 headers={"User-Agent": "copilote-fa18",
                                          "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            infos = json.loads(r.read())
    except Exception:
        return None
    url = next((a["browser_download_url"] for a in infos.get("assets", [])
                if a["name"].lower().endswith(".exe")), None)
    if not url:
        return None
    return infos.get("tag_name", ""), url, infos.get("body", "")


def plus_recente(tag):
    return _version(tag) > _version(__version__)


def installer(url, journal=print):
    """Telecharge l'installateur et le lance. L'appelant doit ensuite se fermer."""
    journal("Téléchargement de la mise à jour...")
    chemin = os.path.join(tempfile.gettempdir(), "CopiloteF18-Setup.exe")
    req = urllib.request.Request(url, headers={"User-Agent": "copilote-fa18"})
    with urllib.request.urlopen(req, timeout=300) as r, open(chemin, "wb") as f:
        f.write(r.read())
    journal("Installation : le copilote va redémarrer.")
    subprocess.Popen([chemin, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                     close_fds=True)
