"""Verification des raccourcis clavier DCS dont le copilote a besoin.

DCS garde les raccourcis par defaut de chaque avion dans son dossier
d'installation (Mods\\aircraft\\FA-18C\\Input\\FA-18C\\keyboard\\default.lua)
et tes modifications dans Saved Games\\DCS\\Config\\Input\\FA-18C_hornet\\
keyboard\\Keyboard.diff.lua. On lit les deux pour savoir quelle combinaison
de touches commande vraiment chaque manette des gaz.
"""
import glob
import os
import re

# Ce que le copilote doit savoir actionner au clavier :
# cle de config -> variantes de noms DCS (tous les mots d'une variante doivent
# apparaitre dans le nom de la commande ; la premiere variante trouvee gagne)
BESOINS = {
    "gaz_gauche_idle": [("throttle", "left", "idle"), ("engine", "start", "left")],
    "gaz_droit_idle": [("throttle", "right", "idle"), ("engine", "start", "right")],
    "gaz_gauche_off": [("throttle", "left", "off"), ("engine", "stop", "left")],
    "gaz_droit_off": [("throttle", "right", "off"), ("engine", "stop", "right")],
}

NOMS = {
    "gaz_gauche_idle": "Manette gauche sur IDLE",
    "gaz_droit_idle": "Manette droite sur IDLE",
    "gaz_gauche_off": "Manette gauche sur OFF",
    "gaz_droit_off": "Manette droite sur OFF",
}

# Noms DCS des touches -> noms utilises par copilote.clavier
_MODIFS = {"LSHIFT": "LSHIFT", "RSHIFT": "RSHIFT", "LALT": "LALT", "RALT": "RALT",
           "LCTRL": "LCTRL", "RCTRL": "RCTRL", "LWIN": "LWIN", "RWIN": "RWIN"}


# ------------------------------------------------------------ lecture Lua
class _Lecteur:
    """Lit les tables d'un fichier Lua de DCS sans executer le Lua.

    Les identifiants (iCommandX, devices.X) deviennent du texte, et _('x')
    devient 'x'. Suffit pour les fichiers de commandes de DCS.
    """

    _JETONS = re.compile(r"""
        (?P<espace>\s+)
      | (?P<comlong>--\[(?P<eg>=*)\[.*?\](?P=eg)\])
      | (?P<com>--[^\n]*)
      | (?P<chlong>\[(?P<eg2>=*)\[.*?\](?P=eg2)\])
      | (?P<ch>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
      | (?P<nb>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)
      | (?P<id>[A-Za-z_][A-Za-z0-9_]*(?:[.:][A-Za-z_][A-Za-z0-9_]*)*)
      | (?P<sym>[{}\[\]=,;()])
      | (?P<autre>.)
    """, re.S | re.X)

    def __init__(self, texte):
        self.j = []
        for m in self._JETONS.finditer(texte):
            g = m.lastgroup
            if g in ("espace", "comlong", "com", "eg", "eg2"):
                continue
            v = m.group(g)
            if g == "ch":
                v = self._chaine(v[1:-1])
            elif g == "chlong":
                v = v[v.index("[", 1) + 1: v.rindex("]", 0, len(v) - 1)]
                g = "ch"
            elif g == "nb":
                v = float(v)
            self.j.append((g, v))
        self.i = 0

    @staticmethod
    def _chaine(s):
        return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)

    def _voir(self, k=0):
        i = self.i + k
        return self.j[i] if i < len(self.j) else ("fin", None)

    def _prendre(self):
        t = self._voir()
        self.i += 1
        return t

    def tables(self):
        """Toutes les tables de premier niveau trouvees dans le fichier."""
        out = []
        while self.i < len(self.j):
            if self._voir() == ("sym", "{"):
                try:
                    out.append(self._table())
                except (IndexError, ValueError):
                    self.i += 1
            else:
                self.i += 1
        return out

    def _valeur(self):
        g, v = self._prendre()
        if (g, v) == ("sym", "{"):
            self.i -= 1
            return self._table()
        if g == "id":
            if v in ("true", "false"):
                return v == "true"
            if v == "nil":
                return None
            if self._voir() == ("sym", "("):          # appel : _('texte'), f(x, y)
                self._prendre()
                args = []
                while self._voir() not in (("sym", ")"), ("fin", None)):
                    if self._voir() == ("sym", ","):
                        self._prendre()
                        continue
                    args.append(self._valeur())
                self._prendre()
                return args[0] if len(args) == 1 else v
            return v
        if g in ("ch", "nb"):
            return v
        if g == "autre" and v == "-":                  # nombre negatif colle
            return self._valeur()
        return v

    def _table(self):
        self._prendre()  # '{'
        d, liste = {}, []
        while True:
            g, v = self._voir()
            if (g, v) == ("sym", "}"):
                self._prendre()
                break
            if g == "fin":
                raise ValueError("table non fermee")
            if (g, v) in (("sym", ","), ("sym", ";")):
                self._prendre()
                continue
            if (g, v) == ("sym", "["):
                self._prendre()
                cle = self._valeur()
                self._prendre()  # ']'
                self._prendre()  # '='
                val = self._valeur()
                if isinstance(cle, float) and cle.is_integer():
                    cle = int(cle)
                d[cle] = val
            elif g == "id" and self._voir(1) == ("sym", "="):
                self._prendre()
                self._prendre()
                d[v] = self._valeur()
            else:
                liste.append(self._valeur())
        # table "liste" Lua ([1]=..., [2]=...) -> liste Python
        if d and all(isinstance(k, int) for k in d):
            liste = [d[k] for k in sorted(d)] + liste
            d = {}
        if d and liste:
            d["_liste"] = liste
            return d
        return liste if not d else d


def _commandes(tables):
    """Parcourt les tables et renvoie toutes celles qui ont un champ 'name'."""
    trouvees = []

    def marche(x):
        if isinstance(x, dict):
            if isinstance(x.get("name"), str):
                trouvees.append(x)
            for v in x.values():
                marche(v)
        elif isinstance(x, list):
            for v in x:
                marche(v)
    marche(tables)
    return trouvees


def _liste(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return x.get("_liste", [])
    return [x]


def _combo(c):
    """{'key': 'Home', 'reformers': ['RShift']} -> 'RSHIFT+HOME'"""
    if not isinstance(c, dict) or not c.get("key"):
        return None
    modifs = sorted(str(r).upper() for r in _liste(c.get("reformers")))
    return "+".join(modifs + [str(c["key"]).upper()])


def _correspond(nom, mots):
    # une commande "OFF/IDLE" compte pour les deux
    n = nom.lower()
    return all(m in n for m in mots)


# ------------------------------------------------------ dossiers de DCS
def dossiers_saved_games():
    maison = os.path.expanduser("~")
    return sorted(d for d in glob.glob(os.path.join(maison, "Saved Games", "DCS*"))
                  if os.path.isdir(d))


def dossiers_installation():
    """Dossiers d'installation de DCS probables (registre, puis disques)."""
    trouves = []
    try:
        import winreg
        for racine, cle in ((winreg.HKEY_CURRENT_USER, r"Software\Eagle Dynamics\DCS World"),
                            (winreg.HKEY_CURRENT_USER, r"Software\Eagle Dynamics\DCS World OpenBeta"),
                            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Eagle Dynamics\DCS World")):
            try:
                with winreg.OpenKey(racine, cle) as k:
                    trouves.append(winreg.QueryValueEx(k, "Path")[0])
            except OSError:
                pass
    except ImportError:
        pass
    for lettre in "CDEFGH":
        for motif in (r"{}:\Program Files\Eagle Dynamics\DCS World*",
                      r"{}:\Eagle Dynamics\DCS World*",
                      r"{}:\DCS World*",
                      r"{}:\Program Files (x86)\Steam\steamapps\common\DCSWorld",
                      r"{}:\Program Files\Steam\steamapps\common\DCSWorld",
                      r"{}:\SteamLibrary\steamapps\common\DCSWorld",
                      r"{}:\Steam\steamapps\common\DCSWorld"):
            trouves += glob.glob(motif.format(lettre))
    vus, out = set(), []
    for d in trouves:
        d = os.path.normpath(d)
        if d.lower() in vus:
            continue
        if os.path.isdir(os.path.join(d, "Mods", "aircraft")):
            vus.add(d.lower())
            out.append(d)
    return out


def fichier_defaut_hornet(installs=None):
    for d in installs if installs is not None else dossiers_installation():
        for f in glob.glob(os.path.join(d, "Mods", "aircraft", "FA-18C*", "Input", "FA-18C*",
                                        "keyboard", "default.lua")):
            return f
    return None


def fichiers_diff_hornet(saved=None):
    out = []
    for d in saved if saved is not None else dossiers_saved_games():
        out += glob.glob(os.path.join(d, "Config", "Input", "FA-18C*", "keyboard", "*.diff.lua"))
    return out


def _lire(chemin):
    with open(chemin, encoding="utf-8", errors="replace") as f:
        return f.read()


# --------------------------------------------------------- verification
def analyser(fichier_defaut=None, fichiers_diff=None):
    """Renvoie {cle_besoin: {'combos': [...], 'commande': nom, 'source': ...}}
    et la liste des commandes de manettes trouvees (pour le diagnostic)."""
    if fichier_defaut is None:
        fichier_defaut = fichier_defaut_hornet()
    if fichiers_diff is None:
        fichiers_diff = fichiers_diff_hornet()

    liaisons = {}   # nom de commande -> set de combos
    if fichier_defaut and os.path.isfile(fichier_defaut):
        texte = _lire(fichier_defaut)
        sources_defaut = [texte]
        # le fichier de l'avion peut s'appuyer sur un profil commun de DCS
        install = fichier_defaut.split(os.sep + "Mods" + os.sep)[0]
        for ref in re.findall(r"""external_profile\(\s*["']([^"']+)["']""", texte):
            commun = os.path.join(install, *ref.split("/"))
            if os.path.isfile(commun):
                sources_defaut.insert(0, _lire(commun))
        for src in sources_defaut:
            for c in _commandes(_Lecteur(src).tables()):
                combos = {x for x in (_combo(k) for k in _liste(c.get("combos"))) if x}
                liaisons.setdefault(c["name"], set()).update(combos)

    modifiees = set()
    for chemin in fichiers_diff:
        if os.path.basename(chemin).lower() != "keyboard.diff.lua":
            continue
        for t in _Lecteur(_lire(chemin)).tables():
            diffs = t.get("keyDiffs", {}) if isinstance(t, dict) else {}
            for entree in diffs.values() if isinstance(diffs, dict) else []:
                if not isinstance(entree, dict) or not isinstance(entree.get("name"), str):
                    continue
                nom = entree["name"]
                s = liaisons.setdefault(nom, set())
                for c in _liste(entree.get("removed")):
                    s.discard(_combo(c))
                for c in _liste(entree.get("added")):
                    if _combo(c):
                        s.add(_combo(c))
                modifiees.add(nom)

    gaz = {n: sorted(c) for n, c in liaisons.items()
           if any(m in n.lower() for m in ("throttle", "engine"))}

    resultat = {}
    for besoin, variantes in BESOINS.items():
        choix = None
        for mots in variantes:
            candidats = sorted((n for n in liaisons if _correspond(n, mots)), key=len)
            # prefere une commande qui a une touche, et la plus precise
            avec = [n for n in candidats if liaisons[n]]
            if avec or candidats:
                choix = (avec or candidats)[0]
                break
        resultat[besoin] = {
            "commande": choix,
            "combos": sorted(liaisons.get(choix, ())) if choix else [],
            "modifiee": choix in modifiees if choix else False,
        }
    return resultat, gaz, {"defaut": fichier_defaut, "diff": fichiers_diff}


def verifier(cfg):
    """Compare avec config.json. Renvoie (touches a utiliser, messages)."""
    from . import clavier
    actuelles = dict(cfg.get("touches", {}))
    try:
        resultat, _gaz, sources = analyser()
    except Exception as ex:  # ne jamais bloquer le lancement
        return actuelles, [f"Vérification des touches impossible : {ex}"]
    if not sources["defaut"]:
        return actuelles, ["Touches non vérifiées : installation de DCS introuvable."]
    messages, touches = [], dict(actuelles)
    for besoin, r in resultat.items():
        utilisables = [c for c in r["combos"] if clavier.connue(c)]
        lisible = NOMS[besoin]
        if not r["commande"]:
            messages.append(f"{lisible} : commande introuvable dans les fichiers de DCS.")
        elif not r["combos"]:
            touches[besoin] = ""
            messages.append(f"{lisible} : aucune touche clavier dans DCS. "
                            f"Ajoute-en une à « {r['commande']} ».")
        elif not utilisables:
            messages.append(f"{lisible} : touche {r['combos'][0]} que je ne sais pas envoyer.")
        elif actuelles.get(besoin) not in utilisables:
            touches[besoin] = utilisables[0]
            messages.append(f"{lisible} : j'utilise {utilisables[0]}, trouvé dans tes réglages DCS.")
    return touches, messages
