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
