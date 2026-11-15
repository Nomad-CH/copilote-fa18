"""Lancement du copilote : python -m copilote (ou l'application installee)."""
import os
import socket
import sys
import time

from .chemins import DONNEES, GELE, JOURNAL, charger_config


def _journal():
    """Dans l'application installee il n'y a pas de console : tout part dans
    %LOCALAPPDATA%\\CopiloteF18\\journal.txt (inclus dans le diagnostic)."""
    os.makedirs(DONNEES, exist_ok=True)
    try:
        if os.path.getsize(JOURNAL) > 2_000_000:
            os.replace(JOURNAL, JOURNAL + ".ancien")
    except OSError:
        pass
    f = open(JOURNAL, "a", encoding="utf-8", buffering=1)
    f.write(f"\n===== lancement {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    sys.stdout = sys.stderr = f
    # plantage brutal (pas d'exception Python) : la pile part quand meme au journal
    try:
        import faulthandler
        faulthandler.enable(file=f, all_threads=True)
    except Exception:
        pass


def _deja_lance():
    """Un seul copilote a la fois (sinon ils se disputent le Stream Deck)."""
    global _VERROU
    _VERROU = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _VERROU.bind(("127.0.0.1", 7789))
        return False
    except OSError:
        return True


def main():
    if GELE or "--journal" in sys.argv:
        _journal()
    if _deja_lance():
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo("Copilote F/A-18", "Le copilote est déjà ouvert.")
        return
    from .interface import Interface
    Interface(charger_config()).lancer()


if __name__ == "__main__":
    main()
