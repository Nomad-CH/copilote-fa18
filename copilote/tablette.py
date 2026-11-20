"""Tablette : le copilote sur ta Galaxy Tab (ou ton telephone), par le Wi-Fi.

Le copilote sert une page web sur ton reseau local. Tu l'ouvres dans le
navigateur de la tablette, tu l'ajoutes a l'ecran d'accueil, et elle se
comporte comme une application. Un code a 6 chiffres (affiche dans la fenetre
du copilote) protege l'acces : personne d'autre sur ton Wi-Fi ne peut
commander l'avion.

Ce que la tablette fait : carte et plan de vol (toucher la carte = un waypoint),
JDAM par station, TACAN, etat de l'avion, menaces, defense, leurres, procedures,
journal des annonces. Toute l'intelligence reste dans le copilote.
"""

import ipaddress
import json
import mimetypes
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .chemins import ressource, sauver_config

PORT = 8787
DOSSIER = "tablette"


def adresse_locale():
    """L'adresse de ce PC sur le Wi-Fi (ex. 192.168.1.20)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def code_acces(cfg):
    code = cfg.get("tablette_code")
    if not code:
        code = f"{secrets.randbelow(1000000):06d}"
        cfg["tablette_code"] = code
        try:
            sauver_config(cfg)
        except OSError:
            pass
    return code


class Tablette:
    def __init__(self, app, cfg, port=PORT):
        self.app = app
        self.cfg = cfg
        self.port = int(cfg.get("tablette_port") or port)
        self.serveur = None
        self.erreur = ""
        self.clients = {}            # jeton -> derniere visite
        self._sols = {}              # numero de waypoint -> demande d'altitude en cours
        self._verrou = threading.Lock()
        self._faux, self._bloque_jusqua = 0, 0.0     # essais de code rates

    # ------------------------------------------------------------ demarrage
    def demarrer(self):
        if not self.cfg.get("tablette", True):
            return False
        app = self

        class Gestion(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):
                app._get(self)

            def do_POST(self):
                app._post(self)

        class Serveur(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass        # une tablette qui coupe la connexion n'est pas une erreur a journaliser
        try:
            self.serveur = Serveur(("0.0.0.0", self.port), Gestion)
        except OSError as ex:
            self.erreur = f"Port {self.port} occupé ({ex})."
            return False
        self.serveur.daemon_threads = True
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        return True

    def arreter(self):
        if self.serveur is not None:
            self.serveur.shutdown()
            self.serveur = None

    @property
    def adresse(self):
        return f"http://{adresse_locale()}:{self.port}"

    @property
    def connectee(self):
        return any(time.time() - t < 5 for t in self.clients.values())

    # ------------------------------------------------------------- HTTP
    def _repondre(self, h, code, corps, type_="application/json; charset=utf-8", entetes=None):
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps, ensure_ascii=False).encode()
        elif isinstance(corps, str):
            corps = corps.encode()
        h.send_response(code)
        h.send_header("Content-Type", type_)
        h.send_header("Content-Length", str(len(corps)))
        h.send_header("Cache-Control", "no-store")
        for k, v in (entetes or {}).items():
            h.send_header(k, v)
        h.end_headers()
        try:
            h.wfile.write(corps)
        except OSError:
            pass

    def _jeton_ok(self, h):
        jeton = h.headers.get("X-Jeton", "")
        if jeton and jeton in (self.cfg.get("tablette_jetons") or []):
            self.clients[jeton] = time.time()
            return True
        return False

    def _reseau_local(self, h):
        """Seuls les appareils du reseau de la maison (ou ce PC) sont servis."""
        try:
            ip = ipaddress.ip_address(h.client_address[0])
        except ValueError:
            return False
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        return ip.is_private or ip.is_loopback or ip.is_link_local

    def _get(self, h):
        if not self._reseau_local(h):
            return self._repondre(h, 403, "", "text/plain")
        chemin = urlparse(h.path).path
        if chemin == "/api/etat":
            if not self._jeton_ok(h):
                return self._repondre(h, 401, {"erreur": "code"})
            try:
                return self._repondre(h, 200, self.etat())
            except Exception as ex:               # ne jamais faire tomber le serveur
                self.app.boite.erreur("tablette etat", ex)
                return self._repondre(h, 500, {"erreur": str(ex)})
        if chemin.startswith("/guide/"):
            # images du guide de l'utilisateur, gardees sur son PC (jamais dans le programme)
            if not self._jeton_ok(h):
                return self._repondre(h, 401, {"erreur": "code"})
            from . import guide
            f = guide.chemin_page(chemin[len("/guide/"):].replace(".jpg", ""))
            if f is None:
                return self._repondre(h, 404, "introuvable", "text/plain")
            with open(f, "rb") as fd:
                return self._repondre(h, 200, fd.read(), "image/jpeg")
        if chemin in ("", "/"):
            chemin = "/index.html"
        nom = os.path.normpath(chemin.lstrip("/")).replace("\\", "/")
        if nom.startswith("..") or nom.startswith("/"):
            return self._repondre(h, 404, "", "text/plain")
        fichier = ressource(DOSSIER, nom)
        if nom.startswith("polices/"):
            fichier = ressource(nom)
        if not os.path.isfile(fichier):
            return self._repondre(h, 404, "introuvable", "text/plain")
        with open(fichier, "rb") as f:
            corps = f.read()
        type_ = mimetypes.guess_type(fichier)[0] or "application/octet-stream"
        if fichier.endswith(".webmanifest"):
            type_ = "application/manifest+json"
        self._repondre(h, 200, corps, type_)

    def _post(self, h):
        if not self._reseau_local(h):
            return self._repondre(h, 403, "", "text/plain")
        chemin = urlparse(h.path).path
        try:
            n = int(h.headers.get("Content-Length", "0"))
            donnees = json.loads(h.rfile.read(min(n, 100000)) or b"{}")
        except (ValueError, OSError):
            return self._repondre(h, 400, {"erreur": "requête"})
        if chemin == "/api/entrer":
            # 5 codes faux : entree fermee une minute pour tout le monde (essais au hasard)
            with self._verrou:
                if time.time() < self._bloque_jusqua:
                    return self._repondre(h, 429, {"erreur": "Trop d'essais. Attends une minute."})
            if not secrets.compare_digest(str(donnees.get("code", "")).strip(), code_acces(self.cfg)):
                with self._verrou:
                    self._faux += 1
                    if self._faux >= 5:
                        self._faux, self._bloque_jusqua = 0, time.time() + 60
                time.sleep(1.0)
                return self._repondre(h, 403, {"erreur": "Code faux."})
            with self._verrou:
                self._faux = 0
            jeton = secrets.token_hex(16)
            jetons = (self.cfg.get("tablette_jetons") or [])[-4:] + [jeton]
            self.cfg["tablette_jetons"] = jetons
            try:
                sauver_config(self.cfg)
            except OSError:
                pass
            self.app.dire("Tablette connectée.")
            return self._repondre(h, 200, {"jeton": jeton})
        if chemin == "/api/action":
            if not self._jeton_ok(h):
                return self._repondre(h, 401, {"erreur": "code"})
            try:
                rep = self.action(donnees)
            except Exception as ex:
                self.app.boite.erreur("tablette action", ex)
                rep = {"ok": False, "message": f"Erreur : {ex}"}
            return self._repondre(h, 200, rep)
        self._repondre(h, 404, {"erreur": "inconnu"})

    # -------------------------------------------------------------- etat
    def etat(self):
        from .armement import ORDRE_LARGAGE, stations_jdam
        from .exportdcs import menace
        from .navigation import lire_hsi, tacan_choisi
        from .procedures import PROCEDURES
        app, a, b, x, nav = self.app, self.app.a, self.app.b, self.app.export, self.app.nav
        self._suivre_sols()
        en_f18 = b.en_f18
        vivant = x is not None and x.vivant
        avion = {}
        if en_f18:
            avion = {
                "carburant": a.carburant, "bingo": self.cfg.get("bingo_lbs"),
                "vitesse": a.vitesse, "altitude": a.altitude, "g": round(a.g, 1),
                "au_sol": a.au_sol, "frein": a.frein_parking, "train": a.train_sorti,
                "arme": a.arme, "aa": a.allume("MASTER_MODE_AA_LT"),
                "ag": a.allume("MASTER_MODE_AG_LT"),
                "sam": a.allume("RH_ADV_SAM"), "cw": a.allume("RH_ADV_CW"),
            }
        pos = (x.position if vivant else None) or None
        menaces = []
        for sym, info in (app.surv.menaces or {}).items():
            nom, conseil = menace(sym, a.allume("RH_ADV_SAM"))
            menaces.append({"sym": sym, "nom": nom, "niveau": info.get("niveau", ""),
                            "conseil": conseil})
        hsi = lire_hsi(x) if vivant else None
        t = tacan_choisi(self.cfg, nav)
        en_cours = app.ex.en_cours
        return {
            "version": __import__("copilote").__version__,
            "en_f18": en_f18, "pause": bool(getattr(b, "en_pause", False)),
            "lien": vivant, "message": app.message,
            "annonces": [{"h": h_, "t": t_, "u": u_} for h_, t_, u_ in list(app.historique)[-25:]],
            "avion": avion,
            "position": ({"lat": pos["lat"], "lon": pos["lon"], "cap": pos.get("cap")}
                         if pos else None),
            "menaces": menaces,
            "defense": self.cfg.get("defense", "CONSEIL"),
            "leurres": list(x.leurres) if (vivant and x.leurres) else None,
            "procedure": PROCEDURES[en_cours][0] if en_cours in PROCEDURES else None,
            "etape": app.ex.etape or "",
            "avancement": list(app.ex.avancement) if en_cours else None,
            "en_attente": [PROCEDURES[k][0] for k in list(app.ex.file) if k in PROCEDURES],
            "procedures": [[k, v[0]] for k, v in PROCEDURES.items()],
            "wpt": ({"num": hsi["wypt"], "cap": hsi["cap"], "dist": hsi["dist"],
                     "tgt": "T\nG\nT" in (hsi.get("texte") or "")} if hsi else None),
            "plan": [dict(p.dict(), texte=p.texte()) for p in nav.points],
            "a_envoyer": len(nav.a_envoyer()),
            "tacan": self.cfg.get("tacan") or [],
            "tacan_choisi": nav.tacan if t is not None else None,
            "armes": self._armes(x, vivant),
            "guide": self._guide(),
            "jdam": {"stations": {str(k): v for k, v in stations_jdam(x).items()} if vivant else {},
                     "ordre": list(ORDRE_LARGAGE),
                     "choix": {str(k): (v if isinstance(v, int) else "coord")
                               for k, v in (getattr(nav, "jdam", {}) or {}).items()}},
        }

    def _guide(self):
        from . import guide
        return guide.complet()

    def _armes(self, x, vivant):
        from .armement import famille, lire_ddi
        """Emport reel, station par station, pour la vue de l'avion. L'etat (STBY, RDY...)
        n'est connu que lorsque la page STORES est affichee : on garde le dernier vu."""
        if not vivant:
            return {"stations": [], "obus": None, "stores_vu": None}
        try:
            d = lire_ddi(x)
        except Exception:
            d = None
        if d and d["stores"] and d["stations_etat"]:
            self._stores_vu = (time.time(), d["stations_etat"])
        quand, lu = getattr(self, "_stores_vu", (0, {}))
        emport = x.stations()
        out = []
        for st in range(1, 10):
            nom, n = emport.get(st, ("", 0))
            e = lu.get(st, {})
            if not n and e.get("type"):                 # pod ou autre charge vue sur la page STORES
                nom, n = e["type"], e.get("nb") or 1
            fam, court = famille(nom) if n else ("vide", "")
            if not n:
                e = {}
            out.append({"st": st, "nom": nom, "n": n, "famille": fam, "court": court,
                        "type": e.get("type"), "etat": e.get("etat"),
                        "double": bool(e.get("double")) or n > 1, "choisie": bool(e.get("choisie"))})
        return {"stations": out, "obus": (x.emport or {}).get("obus"),
                "stores_vu": round(time.time() - quand) if quand else None}

    def _suivre_sols(self):
        """Complete l'altitude des points touches sur la carte de la tablette."""
        x = self.app.export
        if x is None:
            return
        with self._verrou:
            for num, (n_dem, quand) in list(self._sols.items()):
                if n_dem in x.sols:
                    p = self.app.nav.par_numero(num)
                    if p is not None and p.alt_m is None:
                        p.alt_m = x.sols.pop(n_dem)
                        self.app.nav.sauver()
                    del self._sols[num]
                elif time.time() - quand > 10:
                    del self._sols[num]

    # ------------------------------------------------------------- actions
    def action(self, d):
        from .navigation import Point
        from .procedures import PROCEDURES
        app, nav = self.app, self.app.nav
        quoi = d.get("action")

        def proc(cle):
            if not app.b.en_f18:
                return {"ok": False, "message": "Pas de Hornet en vol."}
            if not app.ex.lancer(cle):
                return {"ok": False, "message": "Une procédure est déjà en cours."}
            return {"ok": True, "message": PROCEDURES[cle][0] + "..."}

        if quoi == "procedure" and d.get("cle") in PROCEDURES:
            return proc(d["cle"])
        if quoi == "stop":
            app.ex.stop()
            return {"ok": True, "message": "Procédure arrêtée."}
        if quoi == "leurre" and d.get("sorte") in ("chaff", "flare"):
            app.larguer(d["sorte"])
            return {"ok": True}
        if quoi == "defense" and d.get("mode") in ("OFF", "CONSEIL", "AUTO"):
            while self.cfg.get("defense", "CONSEIL") != d["mode"]:
                app.mode_defense()
            return {"ok": True}
        if quoi == "marquer":
            app.marquer()
            return {"ok": True}
        if quoi == "frein":
            app.frein_parking(bool(d.get("serrer")))
            return {"ok": True}
        if quoi == "ravito":
            app.demander_ravito()
            return {"ok": True}

        # --- plan de vol
        if quoi == "point_ajouter":
            lat, lon = float(d["lat"]), float(d["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return {"ok": False, "message": "Coordonnées hors limites."}
            num = d.get("num")
            num = int(num) if num not in (None, "") else None
            if num is not None and not 0 <= num <= 59:
                return {"ok": False, "message": "Numéro de 0 à 59."}
            nom = (str(d.get("nom") or "").strip() or nav.nom_libre("Point"))[:12]
            p = nav.ajouter(Point(nom, lat, lon, None, "tablette", num))
            if app.export is not None and app.export.ordres_possibles:
                with self._verrou:
                    self._sols[p.num] = (app.export.demander_sol(lat, lon), time.time())
            return {"ok": True, "message": f"{p.nom} : waypoint {p.num}, à envoyer."}
        if quoi == "point_ici":
            p = app.prendre_point(True, str(d.get("nom") or "")[:12])
            return {"ok": p is not None, "message": f"{p.nom} : waypoint {p.num}." if p else
                    "Position de l'avion inconnue."}
        if quoi == "point_deplacer":
            p = nav.par_numero(int(d["num"]))
            if p is None:
                return {"ok": False, "message": "Waypoint introuvable."}
            p.lat, p.lon, p.alt_m, p.sync = float(d["lat"]), float(d["lon"]), None, False
            nav.sauver()
            if app.export is not None and app.export.ordres_possibles:
                with self._verrou:
                    self._sols[p.num] = (app.export.demander_sol(p.lat, p.lon), time.time())
            return {"ok": True, "message": f"Waypoint {p.num} déplacé, à envoyer."}
        if quoi == "point_renommer":
            p = nav.par_numero(int(d["num"]))
            if p is None:
                return {"ok": False}
            p.nom = (str(d.get("nom") or "").strip() or p.nom)[:12]
            nav.sauver()
            return {"ok": True}
        if quoi == "point_supprimer":
            p = nav.par_numero(int(d["num"]))
            if p is not None:
                nav.supprimer(nav.points.index(p))
            return {"ok": True, "message": "Retiré du plan (pas de l'avion)."}
        if quoi == "plan_nouveau":
            nav.effacer()
            return {"ok": True, "message": "Plan vidé."}
        if quoi in ("envoyer_plan", "lire_avion", "retour_base", "wpt_plus", "wpt_moins"):
            return proc(quoi)
        if quoi == "aller":
            nav.cible = int(d["num"])
            return proc("aller_wpt")
        if quoi == "jettison":
            stations = [int(v) for v in (d.get("stations") or [])]
            if not stations:
                return {"ok": False, "message": "Choisis les charges à larguer."}
            app.larguer_stations(stations)
            return {"ok": True}
        if quoi == "ap_cap":
            vers = d.get("vers")
            if vers == "wpt":
                if d.get("num") in (None, ""):
                    return {"ok": False, "message": "Choisis un waypoint."}
                nav.cap_demande = ("wpt", int(d["num"]))
            elif vers == "cap":
                try:
                    cap = int(str(d.get("cap")).strip())
                except ValueError:
                    return {"ok": False, "message": "Cap de 0 à 359."}
                if not 0 <= cap <= 360:
                    return {"ok": False, "message": "Cap de 0 à 359."}
                nav.cap_demande = cap
            else:
                nav.cap_demande = None
            return proc("ap_cap")

        # --- TACAN
        if quoi == "tacan_ajouter":
            canal = int(d.get("canal") or 0)
            if not 1 <= canal <= 126:
                return {"ok": False, "message": "Canal de 1 à 126."}
            liste = self.cfg.setdefault("tacan", [])
            liste.append({"nom": str(d.get("nom") or "")[:14], "canal": canal,
                          "bande": "Y" if d.get("bande") == "Y" else "X",
                          "mode": "A/A" if d.get("mode") == "A/A" else "T/R"})
            nav.tacan = len(liste) - 1
            sauver_config(self.cfg)
            return {"ok": True}
        if quoi == "tacan_supprimer":
            liste = self.cfg.get("tacan") or []
            i = int(d.get("i", -1))
            if 0 <= i < len(liste):
                del liste[i]
                nav.tacan = max(0, min(nav.tacan, len(liste) - 1))
                sauver_config(self.cfg)
            return {"ok": True}
        if quoi == "tacan_choisir":
            nav.tacan = int(d.get("i", 0))
            return {"ok": True}
        if quoi in ("tacan", "tacan_ap"):
            if "i" in d:
                nav.tacan = int(d["i"])
            return proc(quoi)

        # --- JDAM
        if quoi == "jdam_programmer":
            plan = {}
            for st, n in (d.get("plan") or {}).items():
                if n in (None, ""):
                    continue
                if isinstance(n, dict):                     # coordonnees tapees pour cette station
                    lat, lon = float(n["lat"]), float(n["lon"])
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        return {"ok": False, "message": f"Station {st} : coordonnées hors limites."}
                    plan[int(st)] = Point("coordonnées", lat, lon, None, "tablette")
                else:
                    plan[int(st)] = int(n)
            if not plan:
                return {"ok": False, "message": "Choisis une cible pour au moins une station."}
            nav.jdam = plan
            return proc("jdam_programmer")
        if quoi == "jdam_too":
            nav.cible = int(d["num"]) if d.get("num") not in (None, "") else None
            nav.too_stations = [int(x) for x in (d.get("stations") or [])] or None
            return proc("jdam_too")
        return {"ok": False, "message": "Action inconnue."}
