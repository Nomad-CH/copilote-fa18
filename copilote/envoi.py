"""Envoi des diagnostics sur un depot GitHub prive, pour que Claude les lise.

Il faut un depot prive (ex. Nomad-CH/copilote-fa18-diagnostics) et une cle
d'acces GitHub limitee a ce depot (droit "Contents" en lecture/ecriture). La cle
reste sur ce PC, dans tes reglages (%LOCALAPPDATA%\\CopiloteF18\\config.json).
"""
import base64
import json
import os
import urllib.error
import urllib.request

API = "https://api.github.com/repos/"


def _requete(url, cle, donnees=None, methode="GET"):
    req = urllib.request.Request(url, data=donnees, method=methode, headers={
        "Authorization": f"Bearer {cle}", "Accept": "application/vnd.github+json",
        "User-Agent": "copilote-fa18", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def configure(cfg):
    return bool(cfg.get("diag_depot") and cfg.get("diag_cle"))


def tester(depot, cle):
    """Renvoie (ok, message lisible)."""
    try:
        infos = _requete(API + depot, cle)
    except urllib.error.HTTPError as ex:
        if ex.code in (401, 403):
            return False, "Clé refusée par GitHub (vérifie qu'elle est copiée en entier)."
        if ex.code == 404:
            return False, "Dépôt introuvable avec cette clé (nom du dépôt, ou accès de la clé)."
        return False, f"Erreur GitHub {ex.code}."
    except OSError as ex:
        return False, f"Pas de connexion : {ex}"
    if not infos.get("private"):
        return False, "Ce dépôt est PUBLIC : utilise un dépôt privé pour les diagnostics."
    if not infos.get("permissions", {}).get("push", True):
        return False, "La clé ne permet pas d'écrire dans ce dépôt (droit Contents : Read and write)."
    return True, "Connexion OK : dépôt privé accessible en écriture."


def envoyer(chemin, cfg):
    """Depose le fichier dans diagnostics/ du depot. Renvoie l'adresse web du fichier."""
    nom = os.path.basename(chemin)
    with open(chemin, "rb") as f:
        contenu = base64.b64encode(f.read()).decode()
    donnees = json.dumps({"message": f"Diagnostic {nom}", "content": contenu}).encode()
    reponse = _requete(f"{API}{cfg['diag_depot']}/contents/diagnostics/{nom}", cfg["diag_cle"],
                       donnees, "PUT")
    return reponse.get("content", {}).get("html_url", "")
