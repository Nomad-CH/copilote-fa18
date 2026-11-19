"""Verifications rapides, lancees avant chaque publication."""
import json
import os
import sys
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
os.environ.setdefault("COPILOTE_DONNEES", tempfile.mkdtemp())


class Bases(unittest.TestCase):
    def test_config_par_defaut(self):
        from copilote.chemins import charger_config
        cfg = charger_config()
        self.assertIn("touches", cfg)
        self.assertIn("voix_moteur", cfg)

    def test_prononciation(self):
        from copilote.voix import prononcer
        self.assertEqual(prononcer("SA-8"), "S.A. 8")
        self.assertEqual(prononcer("F/A-18"), "F.A. 18")
        self.assertIn("G.B.U. 38", prononcer("GBU-38"))

    def test_menaces(self):
        from copilote.exportdcs import menace
        self.assertEqual(menace("8"), ("SA-8", "C"))
        self.assertEqual(menace("15", True)[0], "SA-15")
        self.assertEqual(menace("15", False)[0], "F-15")

    def test_rwr_et_pages(self):
        from copilote.exportdcs import page_ecran, symboles_rwr
        rwr = "\x1fRWR_ThreatPlacer0\n\nchildren are {\n\x1fRWR_ThreatSymbol0\n8\n}\n"
        self.assertEqual(symboles_rwr(rwr), ["8"])
        self.assertEqual(page_ecran("\x1fSTA2_Label_TYPE\nGBU-38\n"), "STORES")

    def test_identifiants_dcs_bios(self):
        """Chaque interrupteur actionne par une procedure existe dans DCS-BIOS."""
        from copilote import procedures as P
        connus = {}
        for nom in ("FA-18C_hornet", "CommonData", "MetadataStart"):
            with open(os.path.join(RACINE, "dcsbios_json", nom + ".json"), encoding="utf-8") as f:
                for cat in json.load(f).values():
                    connus.update(cat)
        manquants = []

        def parcourir(etapes):
            for e in etapes:
                if isinstance(e, (P.Regle, P.Appui)) and e.ident not in connus:
                    manquants.append(e.ident)
                elif isinstance(e, P.Si):
                    parcourir(e.etapes)
        for _t, etapes in P.PROCEDURES.values():
            parcourir(etapes)
        self.assertEqual(manquants, [])

    def test_touches_dcs(self):
        from copilote import touches
        d = tempfile.mkdtemp()
        defaut = os.path.join(d, "default.lua")
        with open(defaut, "w", encoding="utf-8") as f:
            f.write("join(res.keyCommands,{\n{combos = {{key = 'Home', reformers = {'RShift'}}}, "
                    "down = iCommandRightEngineStart, name = _('Throttle (Right) - IDLE')},\n})")
        r, _gaz, _src = touches.analyser(defaut, [])
        self.assertEqual(r["gaz_droit_idle"]["combos"], ["RSHIFT+HOME"])

    def test_phrases(self):
        from copilote.voix import phrases_connues
        self.assertGreater(len(phrases_connues()), 100)

    def test_alignement(self):
        from copilote import alignement

        class X:
            ecrans = {4: "\x1fAlignType\nGRND\n\x1fAlignQual\nQUAL: 0.5   OK\n"
                         "\x1fAlignTime\nTIME: 1:36\n\x1fSTD HDG_1__id:24\nSTD HDG\n"}
        info = alignement.lire(X)
        self.assertTrue(info["ok"])
        self.assertEqual(info["qual"], 0.5)
        self.assertEqual(info["temps"], 96)
        self.assertTrue(info["std_hdg_visible"])

    def test_clavier_ponctuation(self):
        from copilote import clavier
        self.assertTrue(clavier.connue("]"))
        self.assertTrue(clavier.connue("RSHIFT+HOME"))

    def test_import_fenetre(self):
        import copilote.interface  # noqa: F401


if __name__ == "__main__":
    unittest.main()


class Navigation(unittest.TestCase):
    def test_coordonnees(self):
        from copilote.navigation import lire_coordonnees
        for texte in ('N 41°55\'12" E 041°51\'30"', "N41 55.200 E041 51.500", "41.92, 41.858333",
                      "N 41 55 12 E 41 51 30"):
            lat, lon = lire_coordonnees(texte)
            self.assertAlmostEqual(lat, 41.92, places=3, msg=texte)
            self.assertAlmostEqual(lon, 41.858333, places=3, msg=texte)
        lat, lon = lire_coordonnees("S 33 51.5 W 070 30.0")
        self.assertLess(lat, 0)
        self.assertLess(lon, 0)
        self.assertIsNone(lire_coordonnees("bonjour"))

    def test_saisie_ufc(self):
        from copilote.navigation import saisie_ufc
        self.assertEqual(saisie_ufc(41.75, True), ("2", "4145", "0000"))
        self.assertEqual(saisie_ufc(41.7, False), ("6", "4142", "0000"))
        self.assertEqual(saisie_ufc(-120.5, False), ("4", "12030", "0000"))

    def test_page_hsi_reelle(self):
        from copilote.navigation import lire_hsi

        class X:
            vivant = True
            ecrans = {4: "\x1fHSI_Main_Root\n\n\x1fTRCData\n121°/  0.0\n\x1fWYPT_Page_Number\n0\n"
                         "\x1fGroundSpeed_TN_UP_Mode\n0G\n\x1fWYPT_1__id:13\nW\nY\nP\nT\n"}
        info = lire_hsi(X())
        self.assertEqual((info["wypt"], info["cap"], info["dist"]), (0, 121, 0.0))
        self.assertFalse(info["wypt_encadre"])


class PlanDeVol(unittest.TestCase):
    def test_nouvelle_mission(self):
        import tempfile
        import time as _t
        from copilote.navigation import Carnet, Point
        k = Carnet(os.path.join(tempfile.mkdtemp(), "plan.json"))
        k.horloge_mission(500.0)
        k.ajouter(Point("vieux", 1, 1))
        k.horloge_mission(520.0)
        _t.sleep(0.02)
        k.ajouter(Point("prepare", 2, 2))        # prepare entre deux missions
        self.assertEqual(k.horloge_mission(3.0), 1)
        self.assertEqual([p.nom for p in k.points], ["prepare"])
        self.assertIsNone(k.horloge_mission(4.0))


class Jdam(unittest.TestCase):
    def test_pages_reelles(self):
        from copilote.armement import lire_ddi, _dms
        with open(os.path.join(RACINE, "tests", "pages_jdam_15nov.json"), encoding="utf-8") as f:
            marques = json.load(f)

        class X:
            vivant = True

            def __init__(self, ecrans):
                self.ecrans = {int(k): v for k, v in ecrans.items()}
        m1, m2, m3 = (lire_ddi(X(marques[n])) for n in ("1", "2", "3"))
        self.assertTrue(m1["stores"] and not m1["jdam"])
        self.assertTrue(m2["jdam"] and m2["mode"] == "PP" and m2["fusee"] == "OFF")
        self.assertEqual(m3["mode"], "TOO")
        self.assertEqual(lire_ddi(X(marques["4"]))["fusee"], "INST")
        self.assertTrue(lire_ddi(X(marques["1"]), 3)["menu_tac"])
        self.assertEqual(_dms(41.920094, True), ("2", "415512", "34"))

    def test_page_msn_reelle(self):
        from copilote.armement import lire_ddi
        with open(os.path.join(RACINE, "tests", "pages_msn_15nov.json"), encoding="utf-8") as f:
            pages = json.load(f)

        class X:
            vivant = True

            def __init__(self, t):
                self.ecrans = {2: t}
        dsply, pp, too = (lire_ddi(X(pages[k])) for k in ("dsply", "msn1", "msn2"))
        self.assertTrue(dsply["dsply"] and not dsply["msn_page"])
        self.assertTrue(pp["msn_page"] and pp["mission"] == "PP1" and pp["station"] == 8)
        self.assertEqual(too["station"], 2)
        self.assertAlmostEqual(too["tgt_lat"], 31.509063, places=4)
        self.assertAlmostEqual(too["tgt_lon"], 65.654772, places=4)

    def test_pages_du_19_novembre(self):
        """Pages du vol du 19 nov. : sous-menu EFUZ, type encadre, types par station."""
        from copilote.armement import lire_ddi
        with open(os.path.join(RACINE, "tests", "pages_jdam_19nov.json"), encoding="utf-8") as f:
            pages = json.load(f)

        class X:
            vivant = True

            def __init__(self, t):
                self.ecrans = {2: t}
        lu = {k: lire_ddi(X(v)) for k, v in pages.items()}
        self.assertTrue(lu["stores_efuz"]["efuz_menu"])
        self.assertFalse(lu["stores_pp"]["efuz_menu"])
        self.assertEqual(lu["stores_pp"]["types_haut"], ["J-82", "J-83"])
        self.assertEqual(lu["stores_pp"]["type_encadre"], "J-82")
        self.assertEqual(lu["stores_pp"]["stations_types"], {8: "J-82", 2: "J-82", 7: "J-83", 3: "J-83"})
        self.assertEqual(lu["stores_too"]["mode"], "TOO")
        self.assertTrue(lu["dsply_msn"]["msn_option"])
        self.assertFalse(lu["dsply_sans"]["msn_option"])
        self.assertAlmostEqual(lu["msn_pp_rempli"]["tgt_lat"], 31.718889, places=4)
        self.assertAlmostEqual(lu["msn_pp_rempli"]["tgt_lon"], 64.8075, places=4)

    def test_coordonnees_comme_dans_l_avion(self):
        from copilote.navigation import Point, dms
        self.assertEqual(dms(31.718889, True), "N31°43'08\"")
        self.assertEqual(dms(64.8075, False), "E064°48'27\"")
        self.assertEqual(Point("x", -1.5, -0.5).texte(), "S01°30'00\"  W000°30'00\"")
