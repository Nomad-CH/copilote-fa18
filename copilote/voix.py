"""Voix du copilote, desactivable a tout moment.

Trois moteurs au choix (config.json, cles "voix_moteur" et "voix_nom") :
  - "edge"    : voix neuronales Microsoft (Henri, Remy, Denise, Vivienne...),
                tres naturelles, demandent Internet pour les nouvelles phrases ;
  - "piper"   : voix neuronales hors ligne (siwis, tom, upmc...), installees
                par essai_voix.bat ;
  - "windows" : la voix integree a Windows (Hortense), robotique mais toujours la.

Chaque phrase generee est gardee dans voix_cache/ : la deuxieme fois elle part
tout de suite, meme sans Internet. Au lancement, le copilote prepare en
arriere-plan toutes les phrases qu'il connait d'avance (menaces, alertes,
procedures). Si le moteur choisi echoue, il repasse sur la voix Windows.
"""
import hashlib
import os
import queue
import re
import subprocess
import sys
import threading
import time

from .chemins import VOIX_CACHE as CACHE, VOIX_PIPER as PIPER

VOIX_EDGE = {
    "henri": "fr-FR-HenriNeural",
    "remy": "fr-FR-RemyMultilingualNeural",
    "denise": "fr-FR-DeniseNeural",
    "vivienne": "fr-FR-VivienneMultilingualNeural",
    "eloise": "fr-FR-EloiseNeural",
    "ariane": "fr-CH-ArianeNeural",
    "fabrice": "fr-CH-FabriceNeural",
}

# nom -> (fichier du modele, numero de locuteur ou None)
VOIX_PIPER = {
    "siwis": ("fr_FR-siwis-medium.onnx", None),
    "tom": ("fr_FR-tom-medium.onnx", None),
    "upmc-pierre": ("fr_FR-upmc-medium.onnx", 1),
    "upmc-jessica": ("fr_FR-upmc-medium.onnx", 0),
}

CANDIDATS = [
    ("edge", "henri", "Henri", "homme, France", "en ligne"),
    ("edge", "remy", "Rémy", "homme, France", "en ligne"),
    ("edge", "fabrice", "Fabrice", "homme, Suisse", "en ligne"),
    ("edge", "denise", "Denise", "femme, France", "en ligne"),
    ("edge", "vivienne", "Vivienne", "femme, France", "en ligne"),
    ("edge", "ariane", "Ariane", "femme, Suisse", "en ligne"),
    ("piper", "tom", "Tom", "homme", "hors ligne"),
    ("piper", "upmc-pierre", "Pierre", "homme", "hors ligne"),
    ("piper", "siwis", "Siwis", "femme", "hors ligne"),
    ("piper", "upmc-jessica", "Jessica", "femme", "hors ligne"),
    ("windows", "", "Hortense", "femme, voix Windows", "robotique"),
]

PHRASE_ESSAI = ("SA-8, nous accroche ! Paillettes ! Fox trois. "
                "Trois vertes, crosse sortie. Le LSO te regarde, souris.")

PIPER_EXE = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/"
MODELES_PIPER = {
    "fr_FR-tom-medium.onnx": _HF + "tom/medium/fr_FR-tom-medium.onnx",
    "fr_FR-siwis-medium.onnx": _HF + "siwis/medium/fr_FR-siwis-medium.onnx",
    "fr_FR-upmc-medium.onnx": _HF + "upmc/medium/fr_FR-upmc-medium.onnx",
}


def piper_installe():
    return os.path.isfile(os.path.join(PIPER, "piper", "piper.exe")) and all(
        os.path.isfile(os.path.join(PIPER, m)) for m in MODELES_PIPER)


def installer_piper(journal=print):
    """Telecharge Piper et ses voix francaises (~200 Mo, une seule fois)."""
    import io
    import urllib.request
    import zipfile

    def telecharger(url):
        req = urllib.request.Request(url, headers={"User-Agent": "copilote-fa18"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()
    os.makedirs(PIPER, exist_ok=True)
    if not os.path.isfile(os.path.join(PIPER, "piper", "piper.exe")):
        journal("Téléchargement de Piper (22 Mo)...")
        zipfile.ZipFile(io.BytesIO(telecharger(PIPER_EXE))).extractall(PIPER)
    for nom, url in MODELES_PIPER.items():
        chemin = os.path.join(PIPER, nom)
        if not os.path.isfile(chemin):
            journal(f"Téléchargement de la voix {nom.split('-')[1]} (~60 Mo)...")
            for suffixe in (".json", ""):
                donnees = telecharger(url + suffixe)
                with open(chemin + suffixe + ".tmp", "wb") as f:
                    f.write(donnees)
                os.replace(chemin + suffixe + ".tmp", chemin + suffixe)
    journal("Voix hors ligne installées.")


_SCRIPT_WINDOWS = r"""
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'fr*' } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.Rate = __DEBIT__
[Console]::Out.WriteLine('pret')
while (($l = [Console]::In.ReadLine()) -ne $null) {
  if ($l.StartsWith('@')) { try { $s.SetOutputToWaveFile($l.Substring(1).Split('|')[0]); $s.Speak($l.Substring(1).Split('|',2)[1]); $s.SetOutputToDefaultAudioDevice() } catch {} }
  else { try { $s.Speak($l) } catch {} }
  [Console]::Out.WriteLine('ok')
}
"""

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------- prononciation
# Ce qui est ecrit a l'ecran n'est pas toujours ce qu'il faut dire : sans aide,
# une voix lit "SA-8" comme "sa huit" et "F/A-18" comme "fa dix-huit".
_PRONONCIATION = [
    (r"\bF/A-18\b", "F.A. 18"),
    (r"\bSA-(\d+)", r"S.A. \1"),
    (r"\bGBU-(\d+)", r"G.B.U. \1"),
    (r"\bAGM-(\d+)", r"A.G.M. \1"),
    (r"\bAIM-(\d+)X\b", r"AIM \1 X"),
    (r"\bAIM-(\d+)", r"AIM \1"),
    (r"\bCBU-(\d+)", r"C.B.U. \1"),
    (r"\bMK-(\d+)", r"Mark \1"),
    (r"\bMiG-(\d+)", r"Mig \1"),
    (r"\bSu-(\d+)", r"Sou \1"),
    (r"\bHQ-(\d+)", r"H.Q. \1"),
    (r"\bJF-17\b", "J.F. 17"),
    (r"\bJ-11\b", "J 11"),
    (r"\bF-(\d+)", r"F \1"),
    (r"\bE-(\d)", r"E \1"),
    (r"\bINS\b", "I.N.S."), (r"\bIFA\b", "I.F.A."), (r"\bRWR\b", "R.W.R."),
    (r"\bAPU\b", "A.P.U."), (r"\bDDI\b", "D.D.I."), (r"\bHSI\b", "H.S.I."),
    (r"\bFCS\b", "F.C.S."), (r"\bHMD\b", "H.M.D."), (r"\bICLS\b", "I.C.L.S."),
    (r"\bLSO\b", "L.S.O."), (r"\bOK\b", "O.K."), (r"\bARM\b", "arme"),
    (r"\bBINGO\b", "bingo"), (r"\bQUAL\b", "qual"),
    (r"(\d+) %", r"\1 pour cent"),
]
_PRONONCIATION = [(re.compile(a), b) for a, b in _PRONONCIATION]


def prononcer(texte):
    for motif, rempl in _PRONONCIATION:
        texte = motif.sub(rempl, texte)
    return texte


# ------------------------------------------------------------- lecture audio
class _Lecteur:
    """Joue un fichier .mp3 ou .wav avec MCI (integre a Windows), interruptible."""

    def __init__(self, alias="voix"):
        self.alias = alias
        self.ok = sys.platform == "win32"
        if self.ok:
            import ctypes
            self._mci = ctypes.windll.winmm.mciSendStringW
            self._tampon = ctypes.create_unicode_buffer(64)

    def _cmd(self, texte):
        """Renvoie (code d'erreur, reponse). Code 0 = OK."""
        self._tampon.value = ""
        code = self._mci(texte, self._tampon, 64, 0)
        return code, self._tampon.value

    def jouer(self, chemin, interrompre):
        """Bloque jusqu'a la fin, ou jusqu'a ce que interrompre() soit vrai."""
        if not self.ok:
            return False
        self._cmd(f"close {self.alias}")
        code, _ = self._cmd(f'open "{chemin}" type mpegvideo alias {self.alias}')
        if code != 0:
            return False
        self._cmd(f"play {self.alias}")
        time.sleep(0.05)
        while self._cmd(f"status {self.alias} mode")[1] == "playing":
            if interrompre():
                self._cmd(f"stop {self.alias}")
                break
            time.sleep(0.04)
        self._cmd(f"close {self.alias}")
        return True


# ------------------------------------------------------------------ moteurs
class _MoteurWindows:
    nom = "windows"

    def __init__(self, debit=1):
        self.ok = False
        self._proc = None
        self._verrou = threading.Lock()
        if sys.platform != "win32":
            return
        try:
            self._proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 _SCRIPT_WINDOWS.replace("__DEBIT__", str(int(debit)))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
            self.ok = self._proc.stdout.readline().strip() == b"pret"
        except OSError:
            self.ok = False

    def fichier(self, texte, chemin):
        """Ecrit la phrase dans un .wav (pour passer par le meme lecteur)."""
        if not self.ok:
            return False
        with self._verrou:
            try:
                ligne = "@" + chemin + "|" + texte.replace("\n", " ") + "\n"
                self._proc.stdin.write(ligne.encode("utf-8"))
                self._proc.stdin.flush()
                self._proc.stdout.readline()
            except (OSError, ValueError):
                self.ok = False
                return False
        return os.path.isfile(chemin) and os.path.getsize(chemin) > 1000


class _MoteurEdge:
    nom = "edge"
    extension = ".mp3"

    def __init__(self, voix, debit=1):
        self.voix = VOIX_EDGE.get(voix, voix)
        self.debit = f"{'+' if debit >= 0 else ''}{int(debit) * 8}%"
        try:
            import edge_tts  # noqa: F401
            self.ok = True
        except ImportError:
            self.ok = False

    def fichier(self, texte, chemin):
        import asyncio
        import edge_tts

        async def generer():
            await edge_tts.Communicate(texte, self.voix, rate=self.debit,
                                       connect_timeout=5, receive_timeout=15).save(chemin)
        try:
            asyncio.run(generer())
        except Exception:
            try:
                os.remove(chemin)
            except OSError:
                pass
            return False
        return os.path.isfile(chemin) and os.path.getsize(chemin) > 500


class _MoteurPiper:
    nom = "piper"
    extension = ".wav"

    def __init__(self, voix, debit=1):
        self.exe = os.path.join(PIPER, "piper", "piper.exe")
        modele, self.locuteur = VOIX_PIPER.get(voix, (voix + ".onnx", None))
        self.modele = os.path.join(PIPER, modele)
        self.vitesse = max(0.6, 1.0 - 0.08 * int(debit))   # length_scale : plus petit = plus vite
        self.ok = os.path.isfile(self.exe) and os.path.isfile(self.modele)

    def fichier(self, texte, chemin):
        args = [self.exe, "--model", self.modele, "--output_file", chemin,
                "--length_scale", f"{self.vitesse:.2f}"]
        if self.locuteur is not None:
            args += ["--speaker", str(self.locuteur)]
        try:
            subprocess.run(args, input=texte.replace("\n", " ").encode("utf-8"),
                           cwd=os.path.dirname(self.exe), timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return os.path.isfile(chemin) and os.path.getsize(chemin) > 1000


_MoteurWindows.extension = ".wav"


def creer_moteur(nom_moteur, nom_voix, debit=1):
    if nom_moteur == "edge":
        return _MoteurEdge(nom_voix or "henri", debit)
    if nom_moteur == "piper":
        return _MoteurPiper(nom_voix or "tom", debit)
    return _MoteurWindows(debit)


# ------------------------------------------------------------------- la voix
class Voix:
    def __init__(self, active=True, debit=1, moteur="windows", nom_voix="", cache=CACHE):
        self.active = active
        self._file = queue.Queue()
        self._urgent = threading.Event()
        self._lecteur = _Lecteur(f"voix{id(self)}")
        self.moteur = creer_moteur(moteur, nom_voix, debit)
        self._secours = self.moteur if self.moteur.nom == "windows" else None
        self._debit = debit
        cle = f"{self.moteur.nom}_{getattr(self.moteur, 'voix', nom_voix) or 'defaut'}_{debit}"
        self.cache = os.path.join(cache, "".join(c if c.isalnum() or c in "-_" else "_" for c in cle))
        if not self.moteur.ok:
            self._secours = self._secours or _MoteurWindows(debit)
        self.disponible = self._lecteur.ok and (self.moteur.ok or bool(self._secours and self._secours.ok))
        if self.disponible:
            threading.Thread(target=self._boucle, daemon=True).start()

    @classmethod
    def depuis_config(cls, cfg):
        return cls(cfg.get("voix", True), cfg.get("voix_debit", 1),
                   cfg.get("voix_moteur", "windows"), cfg.get("voix_nom", ""))

    @property
    def description(self):
        if self.moteur.ok:
            return f"{self.moteur.nom} {getattr(self.moteur, 'voix', '')}".strip()
        return "windows (secours)"

    # ------------------------------------------------------------ commandes
    def basculer(self):
        self.active = not self.active
        if not self.active:
            self._vider()
            self._urgent.set()
        return self.active

    def dire(self, texte, urgent=False):
        if not (self.active and self.disponible):
            return
        if urgent:
            self._vider()
            self._urgent.set()
        self._file.put(prononcer(texte))

    def preparer(self, phrases):
        """Genere a l'avance les phrases connues, en arriere-plan."""
        if self.disponible and self.moteur.ok and self.moteur.nom != "windows":
            threading.Thread(target=self._preparer, args=([prononcer(p) for p in phrases],),
                             daemon=True).start()

    # -------------------------------------------------------------- interne
    def _vider(self):
        try:
            while True:
                self._file.get_nowait()
        except queue.Empty:
            pass

    def _chemin(self, texte, moteur):
        h = hashlib.sha1(texte.strip().encode("utf-8")).hexdigest()[:16]
        dossier = self.cache if moteur is self.moteur else self.cache + "_secours"
        return os.path.join(dossier, h + moteur.extension)

    def _generer(self, texte, moteur):
        chemin = self._chemin(texte, moteur)
        if os.path.isfile(chemin):
            return chemin
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        temp = chemin + ".tmp" + moteur.extension
        if moteur.fichier(texte, temp):
            os.replace(temp, chemin)
            return chemin
        return None

    def _obtenir(self, texte):
        """Fichier audio de la phrase : depuis le cache, sinon genere.
        Si le moteur choisi echoue (pas d'Internet...), voix Windows en secours."""
        if self.moteur.ok:
            chemin = self._generer(texte, self.moteur)
            if chemin:
                return chemin
        if self._secours is None:
            self._secours = _MoteurWindows(self._debit)
        if self._secours is not self.moteur and self._secours.ok:
            return self._generer(texte, self._secours)
        return None

    def _preparer(self, phrases):
        for p in phrases:
            chemin = self._chemin(p, self.moteur)
            if os.path.isfile(chemin):
                continue
            os.makedirs(os.path.dirname(chemin), exist_ok=True)
            temp = chemin + ".tmp" + self.moteur.extension
            if self.moteur.fichier(p, temp):
                os.replace(temp, chemin)
            else:
                return  # pas de reseau ou moteur en panne : on reessaiera au prochain lancement
            time.sleep(0.15)

    def _boucle(self):
        while True:
            texte = self._file.get()
            self._urgent.clear()
            if not self.active:
                continue
            chemin = self._obtenir(texte)
            if chemin and self.active:
                self._lecteur.jouer(chemin, lambda: self._urgent.is_set() or not self.active)


def phrases_connues():
    """Toutes les phrases que le copilote peut dire, connues d'avance."""
    from . import procedures, surveillance
    from .exportdcs import AMBIGUS, CONSEIL, MENACES
    out = []

    def parcourir(etapes):
        for e in etapes:
            if isinstance(e, procedures.Dit):
                out.extend(e.messages)
            elif isinstance(e, procedures.Si):
                parcourir(e.etapes)
            elif isinstance(e, (procedures.Attend, procedures.Touche)):
                for m in (getattr(e, "aide", None),):
                    if m:
                        out.append(m)
            elif isinstance(e, procedures.Exige):
                out.append(e.message)
    for _titre, etapes in procedures.PROCEDURES.values():
        parcourir(etapes)
    for _cle, _cond, phrases, _u in surveillance.ALERTES:
        out += phrases
    menaces = list(MENACES.values()) + [m for paire in AMBIGUS.values() for m in paire]
    menaces += [(f"{a[0]} ou {b[0]}", None) for a, b in AMBIGUS.values()]
    for nom, conseil in set(menaces):
        out += [f"{nom} au RWR.", (f"{nom}, nous accroche ! " + CONSEIL.get(conseil, "")).strip(),
                f"{nom} perdu."]
    out += ["Fox un.", "Fox deux.", "Fox trois.", "Magnum.", "Rifle.", "Bruiser.",
            "Bombe larguée.", "Leurres bas.", "Plus de leurres.", "Paillettes.", "Leurre.",
            "Master caution. Regarde le DDI gauche.",
            *__import__("copilote.app", fromlist=["ACCUEILS"]).ACCUEILS,
            "Une procédure est déjà en cours. STOP pour l'interrompre.",
            "Procédure interrompue."]
    # les plus urgentes d'abord
    out.sort(key=lambda p: (not p.endswith("!"), len(p)))
    vus, uniques = set(), []
    for p in out:
        if p not in vus:
            vus.add(p)
            uniques.append(p)
    return uniques
