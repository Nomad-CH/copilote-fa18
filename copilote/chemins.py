"""Ou sont les choses.

RESSOURCES : fichiers livres avec le programme (police, script Lua, reglages
             par defaut). Dans l'application installee, ils sont dans le .exe.
PROGRAMME  : dossier du programme (hidapi.dll y est range).
DONNEES    : tes donnees, qui survivent aux mises a jour :
             %LOCALAPPDATA%\\CopiloteF18 (reglages, voix, boite noire, journal).
"""
import json
import os
import sys

GELE = getattr(sys, "frozen", False)
RESSOURCES = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRAMME = os.path.dirname(sys.executable) if GELE else RESSOURCES
DONNEES = os.environ.get("COPILOTE_DONNEES") or os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share"), "CopiloteF18")

CONFIG = os.path.join(DONNEES, "config.json")
BOITE_NOIRE = os.path.join(DONNEES, "boite_noire")
VOIX_CACHE = os.path.join(DONNEES, "voix_cache")
VOIX_PIPER = os.path.join(DONNEES, "voix_piper")
JOURNAL = os.path.join(DONNEES, "journal.txt")


def ressource(*morceaux):
    return os.path.join(RESSOURCES, *morceaux)


def charger_config():
    """Reglages par defaut, completes par les tiens (les nouveaux reglages
    d'une mise a jour s'ajoutent sans effacer les tiens)."""
    with open(ressource("config_defaut.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            perso = json.load(f)
        touches = {**cfg.get("touches", {}), **perso.get("touches", {})}
        cfg.update(perso)
        cfg["touches"] = touches
    except (OSError, ValueError):
        pass
    return cfg


def sauver_config(cfg):
    """N'enregistre que ce qui differe des reglages par defaut."""
    with open(ressource("config_defaut.json"), encoding="utf-8") as f:
        defaut = json.load(f)
    perso = {k: v for k, v in cfg.items() if defaut.get(k) != v and not k.startswith("_")}
    os.makedirs(DONNEES, exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(perso, f, ensure_ascii=False, indent=2)
