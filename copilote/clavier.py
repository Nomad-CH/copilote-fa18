"""Envoi de raccourcis clavier a DCS (Windows uniquement).

Sert uniquement pour ce que DCS-BIOS ne sait pas actionner sur le F/A-18 :
le passage des manettes des gaz de OFF a IDLE (et retour). Les raccourcis
sont ceux par defaut de DCS et se changent dans config.json.
"""
import sys
import time

# Codes "scan" du clavier ; True = touche etendue. Noms en majuscules,
# comme DCS les ecrit (Home, End, RShift...).
TOUCHES = {
    "LSHIFT": (0x2A, False), "RSHIFT": (0x36, False),
    "LALT": (0x38, False), "RALT": (0x38, True),
    "LCTRL": (0x1D, False), "RCTRL": (0x1D, True),
    "LWIN": (0x5B, True), "RWIN": (0x5C, True),
    "HOME": (0x47, True), "END": (0x4F, True),
    "PAGEUP": (0x49, True), "PAGEDOWN": (0x51, True),
    "INSERT": (0x52, True), "DELETE": (0x53, True),
    "UP": (0x48, True), "DOWN": (0x50, True), "LEFT": (0x4B, True), "RIGHT": (0x4D, True),
    "SPACE": (0x39, False), "ENTER": (0x1C, False), "TAB": (0x0F, False),
    "BACK": (0x0E, False), "ESC": (0x01, False),
    "NUMENTER": (0x1C, True), "NUM*": (0x37, False), "NUM-": (0x4A, False),
    "NUM+": (0x4E, False), "NUM/": (0x35, True), "NUM.": (0x53, False),
}
# ponctuation, par position physique (noms DCS = clavier QWERTY americain)
TOUCHES.update({"`": (0x29, False), "-": (0x0C, False), "=": (0x0D, False),
                "[": (0x1A, False), "]": (0x1B, False), "\\": (0x2B, False),
                ";": (0x27, False), "'": (0x28, False), ",": (0x33, False),
                ".": (0x34, False), "/": (0x35, False)})
for _i, _c in enumerate("1234567890"):
    TOUCHES[_c] = (0x02 + _i, False)
for _rang, _lettres in ((0x10, "QWERTYUIOP"), (0x1E, "ASDFGHJKL"), (0x2C, "ZXCVBNM")):
    for _i, _c in enumerate(_lettres):
        TOUCHES[_c] = (_rang + _i, False)
for _i in range(1, 11):
    TOUCHES[f"F{_i}"] = (0x3A + _i, False)
TOUCHES["F11"], TOUCHES["F12"] = (0x57, False), (0x58, False)
for _c, _code in zip("7894561230", (0x47, 0x48, 0x49, 0x4B, 0x4C, 0x4D, 0x4F, 0x50, 0x51, 0x52)):
    TOUCHES["NUM" + _c] = (_code, False)
# Les lettres sont donnees par leur position physique (clavier QWERTY), comme
# DCS les enregistre : sur un clavier AZERTY, 'A' de DCS est la touche Q.


def _noms(texte):
    return [n.strip().upper() for n in texte.split("+") if n.strip()]


def connue(texte):
    """Vrai si on sait envoyer cette combinaison."""
    noms = _noms(texte or "")
    return bool(noms) and all(n in TOUCHES for n in noms)


def disponible():
    return sys.platform == "win32"


def trouver_fenetre_dcs():
    """Fenetre principale de DCS : par le nom du programme (DCS.exe), sinon par le titre."""
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    k.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD))
    trouvees = []

    def nom_programme(h):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        p = k.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not p:
            return ""
        try:
            tampon = ctypes.create_unicode_buffer(520)
            taille = wintypes.DWORD(520)
            if k.QueryFullProcessImageNameW(p, 0, tampon, ctypes.byref(taille)):
                return tampon.value.rsplit("\\", 1)[-1].lower()
            return ""
        finally:
            k.CloseHandle(p)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def chaque(h, _l):
        if u.IsWindowVisible(h):
            titre = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(h, titre, 256)
            if nom_programme(h) == "dcs.exe" or "Digital Combat Simulator" in titre.value:
                trouvees.append(h)
        return True
    u.EnumWindows(chaque, 0)
    return trouvees[0] if trouvees else None


def dcs_au_premier_plan():
    """Donne la main a DCS. Windows l'interdit souvent a un programme en
    arriere-plan : on utilise les astuces habituelles (Alt, AttachThreadInput).
    Renvoie (fenetre DCS trouvee, DCS est bien au premier plan)."""
    import ctypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    h = trouver_fenetre_dcs()
    if not h:
        return False, False
    if u.GetForegroundWindow() == h:
        return True, True
    if u.IsIconic(h):
        u.ShowWindow(h, 9)                     # SW_RESTORE
    devant = u.GetForegroundWindow()
    fil_devant = u.GetWindowThreadProcessId(devant, None)
    fil_moi = k.GetCurrentThreadId()
    u.keybd_event(0x12, 0, 0, 0)               # Alt enfonce...
    u.keybd_event(0x12, 0, 2, 0)               # ...et relache : debloque SetForegroundWindow
    attache = fil_devant and fil_devant != fil_moi and u.AttachThreadInput(fil_moi, fil_devant, True)
    try:
        u.BringWindowToTop(h)
        u.SetForegroundWindow(h)
    finally:
        if attache:
            u.AttachThreadInput(fil_moi, fil_devant, False)
    time.sleep(0.25)
    return True, u.GetForegroundWindow() == h



dernier_essai = {}   # pour la boite noire : DCS trouve ? au premier plan ?


def combinaison(texte, maintien=0.25):
    """Ex. combinaison('RSHIFT+HOME'). Renvoie False si impossible."""
    if not disponible():
        return False
    import ctypes
    from ctypes import wintypes

    if not connue(texte):
        return False
    noms = _noms(texte)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class MOUSEINPUT(ctypes.Structure):  # donne la bonne taille a l'union
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def envoi(nom, relache):
        code, etendue = TOUCHES[nom]
        drapeaux = 0x0008 | (0x0001 if etendue else 0) | (0x0002 if relache else 0)
        i = INPUT(type=1, u=_U(ki=KEYBDINPUT(0, code, drapeaux, 0, None)))
        ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))

    trouvee, devant = dcs_au_premier_plan()
    dernier_essai.update(fenetre_dcs=trouvee, au_premier_plan=devant)
    if not trouvee:
        return False   # pas de DCS : on n'envoie pas de touches au hasard dans une autre fenetre
    for n in noms:
        envoi(n, False)
        time.sleep(0.03)
    time.sleep(maintien)
    for n in reversed(noms):
        envoi(n, True)
        time.sleep(0.03)
    return True
