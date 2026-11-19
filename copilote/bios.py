"""Liaison avec DCS-BIOS : lecture de l'etat du cockpit et envoi de commandes.

DCS-BIOS ouvre un port TCP (7778 par defaut). On y recoit le flux d'export
(memoire du cockpit) et on y envoie les commandes sous forme de texte
"IDENTIFIANT VALEUR\n".
"""
import glob
import json
import os
import socket
import threading
import time

AVION = "FA-18C_hornet"


def trouver_dossier_json(chemin_config=""):
    """Cherche le dossier doc/json de DCS-BIOS dans Saved Games."""
    candidats = []
    if chemin_config:
        candidats.append(chemin_config)
    maison = os.path.expanduser("~")
    for base in glob.glob(os.path.join(maison, "Saved Games", "DCS*")):
        candidats.append(os.path.join(base, "Scripts", "DCS-BIOS", "doc", "json"))
    # copie livree avec le programme : sert si DCS-BIOS n'est pas (encore) installe
    from .chemins import ressource
    candidats.append(ressource("dcsbios_json"))
    for c in candidats:
        if os.path.isfile(os.path.join(c, AVION + ".json")):
            return c
    return None


class Bios:
    def __init__(self, dossier_json, hote="127.0.0.1", port=7778):
        self.hote, self.port = hote, port
        self.mem = bytearray(65536)
        self.sorties = {}   # identifiant -> description de la sortie
        self.entrees = {}   # identifiant -> liste des interfaces d'entree
        self.connecte = False
        self.derniere_trame = 0.0
        self.journal = None  # fonction(str) optionnelle
        self._sock = None
        self._verrou = threading.Lock()
        self._stop = False
        for nom in ("MetadataStart", "CommonData", AVION):
            self._charger(os.path.join(dossier_json, nom + ".json"))

    # ---------------------------------------------------------------- JSON
    def _charger(self, chemin):
        with open(chemin, encoding="utf-8") as f:
            data = json.load(f)
        for categorie in data.values():
            for ident, c in categorie.items():
                self.entrees[ident] = [e["interface"] for e in c.get("inputs", [])]
                if c.get("outputs"):
                    self.sorties[ident] = c["outputs"][0]

    def connait(self, ident):
        return ident in self.sorties or ident in self.entrees

    # ------------------------------------------------------------- lecture
    def lire(self, ident):
        """Valeur actuelle : entier, texte, ou None si inconnu."""
        s = self.sorties.get(ident)
        if s is None:
            return None
        a = s["address"]
        if s["type"] == "string":
            brut = bytes(self.mem[a:a + s["max_length"]]).split(b"\x00")[0]
            return brut.decode("latin-1")
        mot = self.mem[a] | (self.mem[a + 1] << 8)
        return (mot & s["mask"]) >> s["shift_by"]

    def nombre(self, ident, defaut=None):
        """Extrait un nombre d'un afficheur texte (ex. IFEI ' 64' -> 64)."""
        v = self.lire(ident)
        if isinstance(v, int):
            return v
        chiffres = "".join(ch for ch in (v or "") if ch.isdigit())
        return int(chiffres) if chiffres else defaut

    @property
    def avion(self):
        return self.lire("_ACFT_NAME") or ""

    @property
    def vivant(self):
        """Vrai si DCS envoie des donnees en ce moment."""
        return self.connecte and time.time() - self.derniere_trame < 2.0

    @property
    def en_f18(self):
        # liaison ouverte et F/A-18 : vrai aussi quand DCS est en pause
        return self.connecte and self.derniere_trame > 0 and self.avion == AVION

    @property
    def en_pause(self):
        """DCS en pause (menu Echap) : la liaison reste ouverte mais plus rien n'arrive."""
        return self.en_f18 and not self.vivant

    # --------------------------------------------------------------- envoi
    def envoyer(self, ident, valeur):
        ligne = f"{ident} {valeur}\n".encode("ascii")
        with self._verrou:
            if self._sock is None:
                return False
            try:
                self._sock.sendall(ligne)
                return True
            except OSError:
                return False

    def appuyer(self, ident, duree=0.15):
        """Appui bref sur un bouton poussoir."""
        self.envoyer(ident, 1)
        time.sleep(duree)
        self.envoyer(ident, 0)

    # ------------------------------------------------------------ reception
    def demarrer(self):
        threading.Thread(target=self._boucle, daemon=True).start()

    def arreter(self):
        self._stop = True

    def _boucle(self):
        while not self._stop:
            try:
                s = socket.create_connection((self.hote, self.port), timeout=3)
                s.settimeout(2.0)
                with self._verrou:
                    self._sock = s
                self.connecte = True
                analyseur = _Analyseur(self.mem)
                while not self._stop:
                    try:
                        bloc = s.recv(8192)
                    except socket.timeout:
                        continue
                    if not bloc:
                        break
                    analyseur.traiter(bloc)
                    self.derniere_trame = time.time()
            except OSError:
                pass
            finally:
                self.connecte = False
                self.derniere_trame = 0.0
                self.mem[:] = bytes(len(self.mem))      # plus de liaison : on oublie l'ancien avion
                with self._verrou:
                    if self._sock is not None:
                        try:
                            self._sock.close()
                        except OSError:
                            pass
                    self._sock = None
            time.sleep(2.0)


class _Analyseur:
    """Decode le protocole d'export DCS-BIOS.

    Trame : 0x55 0x55 0x55 0x55, puis des blocs
    [adresse u16][longueur u16][donnees...], en petit-boutiste.
    """

    def __init__(self, mem):
        self.mem = mem
        self.etat = "SYNC"
        self.sync = 0
        self.adresse = 0
        self.reste = 0
        self.tmp = 0

    def traiter(self, bloc):
        mem = self.mem
        for b in bloc:
            e = self.etat
            if e == "SYNC":
                pass
            elif e == "A_BAS":
                self.tmp = b
                self.etat = "A_HAUT"
            elif e == "A_HAUT":
                self.adresse = self.tmp | (b << 8)
                self.etat = "SYNC" if self.adresse == 0x5555 else "L_BAS"
            elif e == "L_BAS":
                self.tmp = b
                self.etat = "L_HAUT"
            elif e == "L_HAUT":
                self.reste = self.tmp | (b << 8)
                self.etat = "DONNEE" if self.reste else "A_BAS"
            elif e == "DONNEE":
                mem[self.adresse & 0xFFFF] = b
                self.adresse += 1
                self.reste -= 1
                if self.reste == 0:
                    self.etat = "A_BAS"
            # detection de la synchro, dans tous les etats
            if b == 0x55:
                self.sync += 1
                if self.sync == 4:
                    self.etat = "A_BAS"
                    self.sync = 0
            else:
                self.sync = 0
