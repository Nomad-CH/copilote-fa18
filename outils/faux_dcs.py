"""Faux DCS pour les essais (voir copilote/demo.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from copilote.demo import *  # noqa: E402,F401,F403
from copilote.demo import FauxHornet, scenario_menaces, servir, trouver_dossier_json  # noqa: E402,F401

if __name__ == "__main__":
    import runpy
    runpy.run_module("copilote.demo", run_name="__main__")
