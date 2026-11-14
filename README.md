# Copilote F/A-18 pour DCS World

Un copilote façon Jarvis pour le F/A-18C de DCS World : il exécute les
procédures à ta place, gère l'armement, surveille l'avion et les menaces, et te
parle. Tout se commande au **Stream Deck XL** ; une petite fenêtre au style
cockpit montre l'état et les messages, et peut se réduire en barre dans un coin.

## Installer

1. Va dans **Releases** (colonne de droite de cette page) et télécharge
   **CopiloteF18-Setup.exe** de la dernière version.
2. Lance-le. Si Windows affiche « Windows a protégé votre ordinateur », clique
   sur **Informations complémentaires**, puis **Exécuter quand même**
   (l'installateur n'est pas signé).
3. Une icône **Copilote FA-18** apparaît sur le Bureau et dans le menu Démarrer.

Rien d'autre à installer : Python, les bibliothèques et le pilote du Stream
Deck sont fournis.

**Au premier lancement**, si la liaison avec DCS manque, clique sur
**Installer la liaison avec DCS** : la fenêtre installe DCS-BIOS et le lien du
copilote dans `Saved Games\DCS` (copie de sauvegarde d'`Export.lua`).

**Avant chaque vol**, quitte le logiciel Elgato Stream Deck (clic droit sur son
icône près de l'horloge, puis Quitter) : deux programmes ne peuvent pas piloter
le Stream Deck en même temps.

## Mises à jour

L'application regarde au lancement s'il existe une version plus récente sur
GitHub. Le bouton de version passe alors en ambre : un clic, et elle se met à
jour toute seule. Tes réglages, tes voix et la boîte noire sont gardés
(`%LOCALAPPDATA%\CopiloteF18`).

## La fenêtre

- **Messages du copilote**, état de la liaison (DCS-BIOS, lien RWR/écrans,
  Stream Deck) et bandeau rouge en cas de menace.
- **Réglages** : voix ON/OFF, choix de la voix, vérification des touches DCS,
  diagnostic, mode démo, Stream Deck virtuel, mise à jour.
- **Réduire en barre** : une ligne fine toujours visible au-dessus de DCS. Clic
  dessus pour revenir. Au Stream Deck, page MISSION : **FENÊTRE** passe de
  pleine à barre à cachée, **COIN FENÊTRE** déplace la barre.

DCS doit être en **fenêtré plein écran** (et non plein écran exclusif) pour que
la barre reste visible par-dessus.

## Le Stream Deck

Quatre pages, choisies dans la colonne de droite : **VOL** (procédures),
**COMBAT** (armement, capteurs, leurres, largages), **MISSION** (points, JDAM,
TACAN… à venir, grisées pour l'instant) et **AVION** (train, volets, crosse,
feux, verrière, batterie, voix…). La colonne d'à côté est la même partout :
**MENACE**, dernier message (appui : il répète), **MASTER CAUTION** et **STOP**.

Couleurs : vert plein = allumé ou actif, contour vert = au repos, ambre =
attention, rouge = danger. Les touches dangereuses demandent un second appui.

### Procédures (le copilote fait tout)

| Touche | Ce qu'il fait |
|---|---|
| Démarrage terre / porte-avions | Batterie, APU, moteurs (manettes au ralenti au clavier, vérifiées au régime), écrans, verrière, INS avec alignement rapide STD HDG, radar, OBOGS, RWR, leurres, FCS reset, volets, trim, feux, BINGO, siège |
| Menu radio / Demande ravito | Ouvre le menu radio de DCS ; enchaîne la séquence de ravitaillement réglée dans la fenêtre (bouton RADIO RAVITO) |
| INS IFA | Passe la centrale de GND/CV sur IFA (fait aussi automatiquement à QUAL OK) |
| Avant décollage / Catapulte | Ailes, volets, trim, crosse, anti-skid, feux, barre de catapultage |
| Après décollage | Train, volets auto, phare |
| Fence in / out | Master arm, radar, RWR, leurres, brouilleur, feux |
| Ravito / Fin ravito | Perche, master arm sur sécurité |
| Atterrissage terre / Appontage | Train, pleins volets, crosse, anti-skid, hook bypass |
| Après atterrissage, Arrêt avion | Remise en configuration sol, extinction complète |

### Ce qu'il lit et annonce

- **RWR** : la menace par son nom (« MiG-29 ou Flanker au RWR »), puis
  « SA-8, nous accroche ! Paillettes ! » quand le symbole clignote, avec la
  contre-mesure conseillée par la planche RWR du Kneeboard Suite.
- **Emport réel** : « Fox un / deux / trois », « Bombe larguée », « Leurres bas » ;
  les touches de station affichent l'arme et le nombre restant.
- **Pages des DDI**, carburant, BINGO, train oublié, pannes, facteur de charge.
- **Pause DCS** : le Stream Deck affiche PAUSE et une procédure en cours attend.

## Voix

Bouton **Choisir la voix** : écoute la même phrase avec chaque voix, puis garde
celle que tu préfères.

- **Edge** (Henri, Rémy, Fabrice, Denise, Vivienne, Ariane) : voix neuronales de
  Microsoft, très naturelles. Internet est nécessaire pour les nouvelles
  phrases ; le copilote prépare d'avance toutes ses phrases connues et les
  garde, donc les alertes partent instantanément. Ce service n'est pas prévu
  officiellement pour ce genre d'usage et pourrait changer un jour.
- **Piper** (Tom, Pierre, Siwis, Jessica) : voix hors ligne, ~200 Mo à
  télécharger une fois depuis la fenêtre.
- **Windows** (Hortense) : toujours disponible, robotique ; voix de secours.

## Alignement de la centrale

Pendant le démarrage, le copilote encadre **STD HDG** sur la page HSI
(alignement en ~90 s au lieu de ~8 min). Il vérifie que l'option s'est bien
encadrée et retient le bon bouton. Dès que la page HSI affiche **QUAL OK**, il
passe la centrale sur **IFA**. Les deux se désactivent dans `config.json`
(`alignement_rapide`, `ins_auto_ifa`).

## Boîte noire, MARQUER et diagnostic

Pendant les vols, le copilote note ce qu'il ne connaît pas encore (symboles
RWR, pages de DDI, armes, erreurs) et les écrans pendant l'alignement INS. La
touche **MARQUER** enregistre tout ce qu'il voit à un instant précis. Le bouton
**Diagnostic** rassemble tout dans un zip à envoyer à Claude.

**Envoi à Claude** : avec un dépôt GitHub **privé** et une clé d'accès limitée à
ce dépôt (bouton ENVOI À CLAUDE), le diagnostic y est déposé directement, et
automatiquement après chaque vol. Claude peut alors le lire quand tu le lui
demandes.

## Ce qui reste à ta charge

- Test FCS, choix de l'arme sur la page SMS, tout ce qui est sur le manche et
  la manette (tir, TDC, zoom FLIR), le frein de parking au départ.
- Si le copilote n'arrive pas à passer une manette au ralenti au clavier, il te
  le demande à voix haute.

## Pour les curieux

- `copilote/` : le programme (Python). `procedures.py` : les procédures, une
  ligne par action. `surveillance.py` : les alertes. `pages.py` : les touches.
- `outils/CopiloteExport.lua` : le lien installé dans DCS (RWR, écrans, emport).
- `tests/` : vérifications lancées avant chaque version.
- Chaque envoi sur `main` fabrique l'installateur ; si le numéro de version
  (`copilote/__init__.py`) est nouveau, il publie la version
  (`.github/workflows/version.yml`).

## Remerciements et licences

- [DCS-BIOS](https://github.com/DCS-Skunkworks/dcs-bios) (GPL-3.0) : liaison
  avec le cockpit ; ses fichiers de définition sont copiés dans `dcsbios_json/`.
- Police [B612](https://github.com/polarsys/b612) (SIL Open Font License 1.1),
  dessinée pour les écrans de cockpit.
- Planche « RWR Threats » du *Kneeboard Suite* de DimOn : table des symboles et
  contre-mesures.
- [python-elgato-streamdeck](https://github.com/abcminiuser/python-elgato-streamdeck),
  [hidapi](https://github.com/libusb/hidapi), [edge-tts](https://github.com/rany2/edge-tts),
  [Piper](https://github.com/rhasspy/piper).
