"""Mode demo : simule un F/A-18C (DCS-BIOS + lien RWR) pour essayer le copilote sans DCS.

Usage : python outils/faux_dcs.py [dossier_json] [--vol]
Ecoute sur le port 7778, comme DCS-BIOS. Un Hornet simplifie repond aux
commandes : l'APU demarre, les moteurs montent en regime, le train sort...
"""
import socket
import sys
import threading
import time

from .bios import Bios, trouver_dossier_json  # noqa: E402


class FauxHornet:
    def __init__(self, dossier_json, en_vol=False):
        self.ref = Bios(dossier_json)          # sert de table d'adresses
        self.mem = self.ref.mem
        self.verrou = threading.Lock()
        self.rpm = {"L": 0.0, "R": 0.0}
        self.gaz_idle = {"L": False, "R": False}
        self.apu_depuis = None
        self.carbu = 10800
        self.bingo = 0
        self.train = 1.0                        # 1 = sorti
        self.verriere = 1.0                     # 1 = ouverte
        self.recu = []
        self.txt("_ACFT_NAME", "FA-18C_hornet")
        self.int("GEAR_LEVER", 0)
        self.int("BATTERY_SW", 1)
        self.int("ENGINE_CRANK_SW", 1)
        self.int("FLAP_SW", 2)
        self.int("HOOK_LEVER", 1)
        self.int("PROBE_SW", 1)
        self.int("CANOPY_SW", 1)
        self.int("EJECTION_SEAT_ARMED", 1)
        self.int("SEL_JETT_KNOB", 1)
        self.int("EMERGENCY_PARKING_BRAKE_ROTATE", 2)
        self.int("EMERGENCY_PARKING_BRAKE_PULL", 1)
        self.int("STROBE_SW", 1)
        if en_vol:
            self.rpm = {"L": 85.0, "R": 85.0}
            self.gaz_idle = {"L": True, "R": True}
            self.train, self.verriere = 0.0, 0.0
            for i, v in (("GEAR_LEVER", 1), ("BATTERY_SW", 2), ("IAS_US_INT", 320),
                         ("ALT_MSL_FT", 15000), ("EMERGENCY_PARKING_BRAKE_ROTATE", 1),
                         ("EMERGENCY_PARKING_BRAKE_PULL", 0),
                         ("EJECTION_SEAT_ARMED", 0), ("RADAR_SW", 2), ("INS_SW", 4)):
                self.int(i, v)

    # ecriture dans la memoire simulee
    def int(self, ident, valeur):
        s = self.ref.sorties[ident]
        a = s["address"]
        mot = self.mem[a] | (self.mem[a + 1] << 8)
        mot = (mot & ~s["mask"]) | ((int(valeur) << s["shift_by"]) & s["mask"])
        self.mem[a], self.mem[a + 1] = mot & 0xFF, mot >> 8

    def txt(self, ident, texte):
        s = self.ref.sorties[ident]
        brut = texte.encode("latin-1")[:s["max_length"]].ljust(s["max_length"], b"\x00")
        self.mem[s["address"]:s["address"] + s["max_length"]] = brut

    def lire(self, ident):
        return self.ref.lire(ident)

    # commandes recues du copilote
    def commande(self, ident, arg):
        self.recu.append((ident, arg))
        try:
            v = int(arg)
        except ValueError:
            return
        if ident == "IFEI_UP_BTN":
            if v == 1:
                self.bingo += 100
            return
        if ident == "EMERGENCY_PARKING_BRAKE_ROTATE":
            self.int(ident, 2 if v == 2 else 1)   # entree 2 = serrer -> sortie 2
            return
        if ident == "RWR_POWER_BTN":
            if v == 1:
                self.int("RWR_LOWER_LT", 0 if self.lire("RWR_LOWER_LT") else 1)
            return
        for bouton, voyant in (("MASTER_MODE_AA", "MASTER_MODE_AA_LT"),
                               ("MASTER_MODE_AG", "MASTER_MODE_AG_LT"),
                               ("SJ_CTR", "SJ_CTR_LT"), ("SJ_LI", "SJ_LI_LT"),
                               ("SJ_LO", "SJ_LO_LT"), ("SJ_RI", "SJ_RI_LT"),
                               ("SJ_RO", "SJ_RO_LT")):
            if ident == bouton:
                if v == 1:
                    self.int(voyant, 0 if self.lire(voyant) else 1)
                return
        s = self.ref.sorties.get(ident)
        if s and s["type"] == "integer":
            self.int(ident, v)

    def pas(self, dt):
        batt = self.lire("BATTERY_SW") != 1
        # APU : pret 4 s apres la mise en route
        if self.lire("APU_CONTROL_SW") and batt:
            self.apu_depuis = self.apu_depuis or time.time()
            self.int("APU_READY_LT", 1 if time.time() - self.apu_depuis > 4 else 0)
        else:
            self.apu_depuis = None
            self.int("APU_READY_LT", 0)
        # moteurs : le demarreur monte a 25 %, puis ralenti a 64 % (on simule
        # le pilote ou le raccourci clavier qui passe la manette sur IDLE)
        lance = self.lire("ENGINE_CRANK_SW")
        for cote, pos in (("R", 2), ("L", 0)):
            r = self.rpm[cote]
            if not self.gaz_idle[cote]:
                if lance == pos and self.lire("APU_READY_LT"):
                    r = min(25.0, r + 8 * dt)
                    if r >= 25.0:
                        self.gaz_idle[cote] = True
                        self.int("ENGINE_CRANK_SW", 1)
                else:
                    r = max(0.0, r - 10 * dt)
            elif r < 64:
                r = min(64.0, r + 12 * dt)
            self.rpm[cote] = r
        self.txt("IFEI_RPM_L", f"{int(self.rpm['L']):3d}")
        self.txt("IFEI_RPM_R", f"{int(self.rpm['R']):3d}")
        if batt:
            self.txt("IFEI_FUEL_UP", f"{self.carbu}T")
            self.txt("IFEI_BINGO", str(self.bingo))
        else:
            self.txt("IFEI_FUEL_UP", "")
            self.txt("IFEI_BINGO", "")
        # train
        cible = 0.0 if self.lire("GEAR_LEVER") == 1 else 1.0
        self.train += max(-dt / 3, min(dt / 3, cible - self.train))
        for v in ("FLP_LG_NOSE_GEAR_LT", "FLP_LG_LEFT_GEAR_LT", "FLP_LG_RIGHT_GEAR_LT"):
            self.int(v, 1 if self.train >= 0.999 else 0)
        # verriere
        sw = self.lire("CANOPY_SW")
        if sw == 0:
            self.verriere = max(0.0, self.verriere - dt / 3)
        elif sw == 2:
            self.verriere = min(1.0, self.verriere + dt / 3)
        self.int("CANOPY_POS", int(self.verriere * 65535))
        self.txt("G_LOAD", " 1.0")
        # feux exterieurs : interrupteur de la manette + variateurs
        maitre = self.lire("THROTTLE_EXT_L_SW") == 1
        self.int("EXT_POSITION_LIGHT_LEFT", 1 if maitre and (self.lire("POSITION_DIMMER") or 0) > 0 else 0)
        self.int("EXT_STROBE_LIGHTS", 1 if maitre and self.lire("STROBE_SW") == 2 else 0)

    def trame(self):
        m = bytes(self.mem)
        out = b"\x55\x55\x55\x55"
        for debut in (0, 0x8000):
            out += debut.to_bytes(2, "little") + (0x8000).to_bytes(2, "little") + m[debut:debut + 0x8000]
        return out


def servir(hornet, port=7778, stop=None):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    srv.settimeout(0.5)
    while not (stop and stop.is_set()):
        try:
            c, _ = srv.accept()
        except socket.timeout:
            continue
        c.settimeout(0.02)
        tampon = b""
        dernier = time.time()
        try:
            while not (stop and stop.is_set()):
                try:
                    d = c.recv(4096)
                    if not d:
                        break
                    tampon += d
                    while b"\n" in tampon:
                        ligne, tampon = tampon.split(b"\n", 1)
                        morceaux = ligne.decode("ascii", "ignore").split()
                        if len(morceaux) == 2:
                            with hornet.verrou:
                                hornet.commande(*morceaux)
                except socket.timeout:
                    pass
                t = time.time()
                if getattr(hornet, "pause", False):
                    dernier = t
                    continue
                if t - dernier >= 0.1:
                    with hornet.verrou:
                        hornet.pas(t - dernier)
                        trame = hornet.trame()
                    dernier = t
                    c.settimeout(2.0)
                    c.sendall(trame)
                    c.settimeout(0.02)
        except OSError:
            pass
        finally:
            c.close()
    srv.close()


def _rwr(symbole=None):
    t = "\x1fRWR_PrioritySetting\nN\n\x1fRWR_BitFailures\n\n"
    if symbole:
        t += ("\x1fRWR_ThreatPlacer0\n\nchildren are {\n\x1fRWR_ThreatFlasher0\n\n"
              "children are {\n\x1fRWR_ThreatSymbol0\n" + symbole + "\n}\n}\n")
    return t


def scenario_menaces(port=7790, stop=None):
    """Imite le lien CopiloteExport : emport, puis un MiG-29 et un SA-8 qui accroche.
    Le scenario dure 60 s et recommence."""
    import json
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    emport = {"courante": 0, "obus": 578, "stations": [
        {"st": i, "nom": n, "n": c} for i, n, c in (
            (1, "AIM-9X", 1), (2, "AIM-120C", 1), (3, "GBU-38(V)1/B", 2), (5, "FPU_8A", 1),
            (7, "GBU-38(V)1/B", 2), (8, "AIM-120C", 1), (9, "AIM-9X", 1))]}
    debut = time.time()
    while not (stop and stop.is_set()):
        t = (time.time() - debut) % 60
        if 15 <= t < 25:
            rwr = _rwr("29")
        elif 30 <= t < 42:
            rwr = _rwr("8") if int(t * 2) % 2 == 0 else _rwr()   # clignote
        else:
            rwr = _rwr()
        e = json.loads(json.dumps(emport))
        if t >= 22:
            e["stations"][1]["n"] = 0          # Fox trois sur le MiG
        if t >= 38:
            e["stations"][2]["n"] = 1          # une GBU-38 sur le SA-8
        paquet = {"k": "etat", "t": t, "avion": "FA-18C_hornet", "rwr": rwr,
                  "emport": e, "leurres": [60, 60] if t < 35 else [8, 52]}
        s.sendto(json.dumps(paquet).encode(), ("127.0.0.1", port))
        time.sleep(0.1)


def _page_hsi(qual_txt, temps, std_encadre):
    t = "\x1fHSI_Main_Root\n\n\x1fAlignType\nGRND\n\x1fAlignQual\n" + qual_txt + "\n"
    t += f"\x1fAlignTime\nTIME: {temps // 60}:{temps % 60:02d}\n"
    t += "\x1fSTD HDG_1__id:24\nSTD HDG\n"
    if std_encadre:
        t += "\x1fSTD HDG_1_box__id:25\n\n"
    return t


def scenario_alignement(hornet, port=7790, stop=None, bouton_std_hdg="AMPCD_PB_20"):
    """Imite la page HSI pendant l'alignement (comme pendant ton vol du 14 nov.)."""
    import json
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    debut = rapide = None
    while not (stop and stop.is_set()):
        with hornet.verrou:
            ins = hornet.lire("INS_SW")
            appuye = any(c == (bouton_std_hdg, "1") for c in hornet.recu)
        if ins in (1, 2):
            debut = debut or time.time()
            if appuye and rapide is None:
                rapide = time.time()
            t = int(time.time() - (rapide or debut))
            if rapide:
                qual = max(0.5, 99.0 - 12 * t)
            else:
                qual = None if t < 8 else max(0.5, 99.0 - 0.2 * (t - 8))
            texte = "QUAL:NO ATT" if qual is None else (
                "QUAL: 0.5   OK" if qual <= 0.5 else f"QUAL:{qual:4.1f}")
            page = _page_hsi(texte, t, rapide is not None)
        else:
            debut = rapide = None
            page = "\x1fHSI_Main_Root\n\n"
        s.sendto(json.dumps({"k": "ecran", "i": 4, "txt": page}).encode(), ("127.0.0.1", port))
        time.sleep(0.5)


class FausseNav:
    """HSI + UFC simules pour essayer la navigation sans DCS (boutons comme
    dans ton cockpit : AMPCD 12/13 waypoint +/-, 11 WYPT, 5 TCN, 10 DATA, 19 PRECISE)."""

    def __init__(self, hornet, lat=41.6, lon=41.6):
        self.h = hornet
        self.lu = 0
        self.wypt, self.wypt_box, self.tcn_box = 1, False, False
        self.data, self.precise = False, False
        self.points = {0: (41.61, 41.60), 1: (41.80, 41.90), 2: (42.0, 42.2)}
        self.avion = [lat, lon]
        self.ufc_mode, self.cue = "", set()
        self.saisie, self.champ, self.tacan_on, self.canal = "", None, False, ""
        self.entrees = []      # ce qui a ete tape (pour les essais)
        self.iff_on = self.dl_on = False
        self.frein = [1.0, 0.666]               # tiree, tournee (frein serre au depart)
        self.stations = {152: 0.0, 154: 0.0, 156: 0.0, 158: 0.0, 160: 0.0}
        self.ddi = "hud"                        # DDI gauche : hud, menu, stores, jdam, efuz, dsply, msn
        self.jdam_mode, self.fusee, self.pp, self.tgt = "PP", "OFF", 1, False
        self.pp_saisies = []
        try:
            import json as _j
            import os as _o
            with open(_o.path.join(_o.path.dirname(__file__), "..", "tests",
                                   "pages_jdam_15nov.json"), encoding="utf-8") as f:
                self.pages = _j.load(f)
            with open(_o.path.join(_o.path.dirname(__file__), "..", "tests",
                                   "pages_msn_15nov.json"), encoding="utf-8") as f:
                self.pages_msn = _j.load(f)
            self.sta, self.cibles = 8, {}
        except OSError:
            self.pages = None
        self.options("")

    def options(self, mode):
        self.ufc_mode = mode
        self.cue = set()
        opts = {"AP": ["ATTH", "BALT", "RALT", "HSEL", "CPL"],
                "TCN": ["T/R", "RCV", "A/A", "X", "Y"],
                "POSN": ["POSN", "", "ELEV", "", ""], "ELEV": ["FEET", "", "METR", "", ""],
                }.get(mode, ["", "", "", "", ""])
        self.opts = opts
        for i, o in enumerate(opts, 1):
            self.h.txt(f"UFC_OPTION_DISPLAY_{i}", o)
            self.h.txt(f"UFC_OPTION_CUEING_{i}", "")
        marche = {"TCN": self.tacan_on, "IFF": self.iff_on, "DL": self.dl_on}.get(mode)
        self.h.txt("UFC_SCRATCHPAD_STRING_1_DISPLAY", "" if marche is None else ("ON" if marche else "OF"))
        self.h.txt("UFC_SCRATCHPAD_STRING_2_DISPLAY", "" if marche is None or marche else "F")

    def traiter(self):
        nouv = self.h.recu[self.lu:]
        self.lu = len(self.h.recu)
        for ident, arg in nouv:
            if arg != "1":
                continue
            if ident.startswith("LEFT_DDI_PB_"):
                self._ddi(int(ident[-2:]))
                continue
            if ident == "AMPCD_PB_14" and not self.data:
                self.tgt = True
                continue
            if ident.startswith("AMPCD_PB_"):
                pb = int(ident[-2:])
                if self.data:
                    if pb == 19:
                        self.precise = not self.precise
                    elif pb in (12, 13):
                        self.wypt = max(0, self.wypt + (1 if pb == 12 else -1))
                    elif pb == 10:
                        self.data = False
                        self.options("")
                else:
                    if pb in (12, 13):
                        self.wypt = max(0, self.wypt + (1 if pb == 12 else -1))
                    elif pb == 11:
                        self.wypt_box, self.tcn_box = True, False
                    elif pb == 5 and self.tacan_on:
                        self.tcn_box, self.wypt_box = True, False
                    elif pb == 10:
                        self.data = True
                        self.options("POSN")
            elif ident == "UFC_AP":
                self.options("AP")
            elif ident in ("UFC_TCN", "UFC_IFF", "UFC_DL"):
                self.options(ident[4:])
            elif ident == "UFC_ONOFF" and self.ufc_mode in ("TCN", "IFF", "DL"):
                if self.ufc_mode == "TCN":
                    self.tacan_on = not self.tacan_on
                elif self.ufc_mode == "IFF":
                    self.iff_on = not self.iff_on
                else:
                    self.dl_on = not self.dl_on
                self.options(self.ufc_mode)
            elif ident.startswith("UFC_OS"):
                i = int(ident[-1])
                o = self.opts[i - 1]
                if self.ufc_mode == "POSN" and o == "POSN":
                    self.champ = "lat"
                elif self.ufc_mode == "POSN" and o == "ELEV":
                    self.options("ELEV")
                elif self.ufc_mode == "ELEV" and o == "FEET":
                    self.champ = "elev"
                elif o:
                    self.h.txt(f"UFC_OPTION_CUEING_{i}", ":")
            elif ident == "UFC_CLR":
                self.saisie = ""
                s = self.pp_saisies
                if self.ddi == "msn" and len(s) >= 4:
                    try:
                        lat = int(s[-4][1:3]) + int(s[-4][3:5]) / 60 + (int(s[-4][5:7]) + int(s[-3]) / 100) / 3600
                        lo = s[-2][1:]
                        lon = int(lo[:-4]) + int(lo[-4:-2]) / 60 + (int(lo[-2:]) + int(s[-1]) / 100) / 3600
                        self.cibles[self.sta] = (lat, lon)
                    except (ValueError, IndexError):
                        pass
                    self.pp_saisies = []
                if self.data:
                    self.options("POSN")
            elif ident == "UFC_ENT":
                if self.ufc_mode == "TGT":
                    self.pp_saisies.append(self.saisie)
                self.entrees.append(self.saisie)
                if self.ufc_mode == "TCN":
                    self.canal = self.saisie
                    self.h.txt("UFC_SCRATCHPAD_NUMBER_DISPLAY", self.saisie)
                self.saisie = ""
                self._maj_point()
            elif ident.startswith("UFC_") and ident[4:].isdigit():
                self.saisie += ident[4:]

    def _ddi(self, pb):
        p = self.ddi
        if pb == 18:
            self.ddi = "menu"
        elif p == "menu" and pb == 5:
            self.ddi = "stores"
        elif p == "stores" and pb == 6:
            self.ddi = "jdam"
        elif p == "jdam" and pb == 5:
            self.jdam_mode = "TOO" if self.jdam_mode == "PP" else "PP"
        elif p == "jdam" and pb == 4:
            self.ddi = "efuz"
        elif p == "efuz" and pb == 3:
            self.fusee, self.ddi = "INST", "jdam"
        elif p == "jdam" and pb == 11:
            self.ddi = "dsply"
        elif p == "dsply" and pb == 4:
            self.ddi = "msn"
        elif p == "msn" and pb == 13:
            ordre = [8, 2, 7, 3]
            self.sta = ordre[(ordre.index(self.sta) + 1) % 4]
        elif p == "msn" and 6 <= pb <= 11:
            self.pp = pb - 5
        elif p == "msn" and pb == 14:
            self.ufc_mode = "TGT"
            self.opts = ["POSN", "", "ELEV", "", ""]
            for i, o in enumerate(self.opts, 1):
                self.h.txt(f"UFC_OPTION_DISPLAY_{i}", o)
        elif p == "msn" and pb == 19:
            self.ddi = "jdam"

    def page_ddi(self):
        pg = self.pages or {}
        if self.ddi == "menu":
            return pg.get("1", {}).get("3", "")
        if self.ddi == "stores":
            return pg.get("1", {}).get("2", "")
        if self.ddi == "jdam":
            t = pg.get("2" if self.jdam_mode == "PP" else "3", {}).get("2", "")
            return t.replace("JDAM_EFUZ_Val\nOFF", "JDAM_EFUZ_Val\n" + self.fusee)
        if self.ddi == "efuz":
            return "\x1fOFF_1__id:5\nOFF\n\x1fINST_1__id:3\nINST\n"
        if self.ddi == "dsply":
            return self.pages_msn["dsply"]
        if self.ddi == "msn":
            t = self.pages_msn["msn1"].replace("CurrStation_JDAM\n8", "CurrStation_JDAM\n%d" % self.sta)
            c = self.cibles.get(self.sta)
            if c:
                def dms(v):
                    dd = int(v); mm = int((v - dd) * 60); ss = ((v - dd) * 60 - mm) * 60
                    return "%d° %02d' %05.2f\"" % (dd, mm, ss)
                t += "\x1fLAT_N_S\nN\n\x1fLAT_Val\n%s\n\x1fLONG_W_E\nE\n\x1fLONG_Val\n%s\n" % (dms(c[0]), dms(c[1]))
            return t
        return "\x1fHUD_Main\n\n"

    def clic(self, appareil, commande, valeur):
        """Clic direct (lien version 3) : frein de parking et stations."""
        if appareil == 5 and commande == 3006 and valeur == 1:
            self.frein[1] = 0.666
        elif appareil == 5 and commande == 3005 and valeur == 1:
            if self.frein[0] > 0.5:
                self.frein = [0.5, 0.0]          # repoussee : elle revient a l'horizontale
            elif self.frein[1] > 0.66:
                self.frein = [1.0, 0.666]
        elif appareil == 23 and valeur == 1:
            arg = {3005: 152, 3006: 154, 3007: 156, 3008: 158, 3009: 160}.get(commande)
            if arg:
                self.stations[arg] = 0.0 if self.stations[arg] else 1.0

    def _maj_point(self):
        e = self.entrees
        # hemisphere+DDMM, decimales, hemisphere+DDDMM, decimales
        if (len(e) >= 4 and self.data and e[-4][:1] in "28" and len(e[-4]) == 5
                and e[-2][:1] in "64" and len(e[-2]) >= 5):
            try:
                la, lo = e[-4], e[-2]
                lat = int(la[1:3]) + (int(la[3:5]) + int(e[-3]) / 10000) / 60
                lon = int(lo[1:-2]) + (int(lo[-2:]) + int(e[-1]) / 10000) / 60
                self.points[self.wypt] = (lat if la[0] == "2" else -lat, lon if lo[0] == "6" else -lon)
            except (ValueError, IndexError):
                pass

    def page(self):
        if self.data:
            lat, lon = self.points.get(self.wypt, (0.0, 0.0))
            # comme dans DCS : un waypoint vide n'affiche meme pas son numero
            vide = self.wypt not in self.points
            t = ("\x1fWYPT_Number\n\n" if vide else "\x1fWYPT_Number\nWYPT %d\n" % self.wypt)
            t += "\x1fPRECISE_1__id:25\nPRECISE\n"
            if self.precise:
                t += "\x1fPRECISE_1_box__id:26\n\n"
            if self.wypt in self.points:
                t += "\x1fWYPT_Latitude\nN %d°%07.4f'\n" % (int(lat), (lat - int(lat)) * 60)
                t += "\x1fWYPT_Longitude\nE %d°%07.4f'\n" % (int(lon), (lon - int(lon)) * 60)
                t += "\x1fWYPT_Elev\n120FT\n"
            t += "\x1fWYPT_SequenceData\n%s\n" % ("" if vide else "0- 1- 2")
            return t
        from .navigation import distance_cap
        lat, lon = self.points.get(self.wypt, (0.0, 0.0))
        dist, cap = distance_cap(self.avion[0], self.avion[1], lat, lon)
        t = "\x1fHSI_Main_Root\n\n\x1fWYPT_Page_Number\n%d\n" % self.wypt
        t += "\x1fTRCData\n%03d°/ %5.1f\n\x1fGroundSpeed_TN_UP_Mode\n420G\n" % (cap, dist)
        t += "\x1fWYPT_1__id:13\n%s\n" % ("T\nG\nT" if self.tgt else "W\nY\nP\nT")
        if self.wypt_box:
            t += "\x1fWYPT_1_box__id:14\n\n"
        t += "\x1fTCN_1__id:6\nT\nC\nN\n"
        if self.tcn_box:
            t += "\x1fTCN_1_box__id:7\n\n"
        return t


def scenario_navigation(hornet, port=7790, stop=None, nav=None, port_ordres=None):
    import json
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ordres = None
    if port_ordres:
        ordres = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ordres.bind(("127.0.0.1", port_ordres))
        ordres.settimeout(0.0)
    nav = nav or FausseNav(hornet)
    while not (stop and stop.is_set()):
        with hornet.verrou:
            nav.traiter()
        while ordres is not None:
            try:
                msg = ordres.recv(2048).decode()
            except (BlockingIOError, socket.timeout, OSError):
                break
            m = msg.split()
            if len(m) == 4 and m[0] == "clic":
                nav.clic(int(m[1]), int(m[2]), float(m[3]))
        paquet = {"k": "etat", "t": 0, "avion": "FA-18C_hornet", "rwr": "",
                  "pos": {"lat": nav.avion[0], "lon": nav.avion[1], "alt": 3000, "cap": 0},
                  "vue": {"lat": 41.75, "lon": 41.70, "sol": 120.0, "haut": 20000},
                  "args": {"240": nav.frein[0], "241": nav.frein[1], "276": 0.9, "277": 1.0, "216": 0.8,
                           **{str(k): v for k, v in nav.stations.items()}}}
        s.sendto(json.dumps(paquet).encode(), ("127.0.0.1", port))
        s.sendto(json.dumps({"k": "ecran", "i": 4, "txt": nav.page()}).encode(), ("127.0.0.1", port))
        s.sendto(json.dumps({"k": "ecran", "i": 2, "txt": nav.page_ddi()}).encode(), ("127.0.0.1", port))
        time.sleep(0.1)


def lancer(dossier_json, stop):
    """Demarre la demo en arriere-plan : avion au sol, menaces en boucle."""
    hornet = FauxHornet(dossier_json, False)
    threading.Thread(target=servir, args=(hornet, 7778, stop), daemon=True).start()
    threading.Thread(target=scenario_menaces, args=(7790, stop), daemon=True).start()
    threading.Thread(target=scenario_alignement, args=(hornet, 7790, stop), daemon=True).start()
    return hornet


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dossier = trouver_dossier_json(args[0] if args else "")
    if not dossier:
        sys.exit("Dossier json de DCS-BIOS introuvable.")
    print("Faux DCS en écoute sur le port 7778 (Ctrl+C pour arrêter).")
    print("Scénario : MiG-29 au RWR vers 15 s, SA-8 qui accroche vers 30 s, puis on recommence.")
    threading.Thread(target=scenario_menaces, daemon=True).start()
    try:
        servir(FauxHornet(dossier, "--vol" in sys.argv))
    except KeyboardInterrupt:
        pass
