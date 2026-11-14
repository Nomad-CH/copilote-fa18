"""Alignement de la centrale (INS), lu sur la page HSI.

Pendant ton demarrage a froid du 14 novembre, la page HSI affichait :
  AlignType  = "GRND"
  AlignQual  = "QUAL:NO ATT", puis "QUAL:98.4" qui descend, puis "QUAL: 0.5   OK"
  AlignTime  = "TIME: 1:36"
et l'option "STD HDG" (cap memorise : alignement en ~90 s au lieu de ~8 min).
Une option encadree apparait dans le texte avec "_box" dans son nom.
"""
import re

from .exportdcs import elements

# ecran -> prefixe des boutons DCS-BIOS de cet ecran
BOUTONS = {4: "AMPCD_PB_", 3: "RIGHT_DDI_PB_", 2: "LEFT_DDI_PB_"}

# Boutons possibles pour STD HDG sur la page HSI (rangee du bas). Le bon est
# verifie a l'usage (l'option s'encadre) puis retenu dans les reglages.
CANDIDATS_STD_HDG = (20, 19)


def _secondes(texte):
    m = re.search(r"(\d+):(\d\d)", texte or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def lire(export):
    """Etat de l'alignement d'apres le premier ecran qui montre la page HSI
    en alignement, ou None."""
    if export is None:
        return None
    for ecran in (4, 3, 2):
        txt = export.ecrans.get(ecran, "")
        if "AlignQual" not in txt:
            continue
        valeurs, noms = {}, []
        for n, v in elements(txt):
            noms.append(n)
            valeurs.setdefault(n, v)
        qual_txt = valeurs.get("AlignQual", "")
        m = re.search(r"QUAL:\s*([\d.]+)", qual_txt)
        return {
            "ecran": ecran,
            "type": valeurs.get("AlignType", ""),
            "qual": float(m.group(1)) if m else None,
            "ok": bool(re.search(r"\bOK\b", qual_txt)),
            "temps": _secondes(valeurs.get("AlignTime", "")),
            "std_hdg_visible": any(n.startswith("STD HDG") for n in noms),
            "std_hdg_encadre": any(n.startswith("STD HDG") and "box" in n for n in noms),
        }
    return None
