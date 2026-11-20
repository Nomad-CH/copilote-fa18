// Copilote F/A-18 — page tablette. Parle au copilote par /api/etat et /api/action.
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
let jeton = null;
try { jeton = localStorage.getItem("jeton"); } catch (e) { jeton = null; }
let etat = null;
let carte = null, coucheWpt = null, route = null, avionMarq = null, suivreAvion = true;
let choisi = null;          // waypoint choisi (numero)
let tacanChoisi = null;

// ------------------------------------------------------------------ reseau
async function api(chemin, donnees) {
  const opts = { headers: { "X-Jeton": jeton || "" } };
  if (donnees !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(donnees);
  }
  const r = await fetch(chemin, opts);
  if (r.status === 401) { montrerEntree(); throw new Error("code"); }
  return r.json();
}

async function agir(action, extra) {
  try {
    const rep = await api("/api/action", Object.assign({ action }, extra || {}));
    if (rep && rep.message) toast(rep.message);
    rafraichir();
    return rep;
  } catch (e) { if (e.message !== "code") toast("Copilote injoignable."); }
}

function toast(t) {
  const el = $("#toast");
  el.textContent = t; el.hidden = false;
  clearTimeout(toast.minuterie);
  toast.minuterie = setTimeout(() => (el.hidden = true), 3500);
}

// ------------------------------------------------------------------ entree
function montrerEntree() {
  $("#appli").hidden = true; $("#entree").hidden = false;
  setTimeout(() => $("#code").focus(), 100);
}
$("#b-entrer").onclick = async () => {
  const code = $("#code").value.trim();
  try {
    const r = await fetch("/api/entrer", { method: "POST", headers: { "Content-Type": "application/json" },
                                           body: JSON.stringify({ code }) });
    const d = await r.json();
    if (!r.ok) { $("#entree-msg").textContent = d.erreur || "Code refusé."; return; }
    jeton = d.jeton;
    try { localStorage.setItem("jeton", jeton); } catch (e) {}
    demarrer();
  } catch (e) { $("#entree-msg").textContent = "Copilote injoignable (même Wi-Fi ?)."; }
};
$("#code").addEventListener("keyup", (e) => { if (e.key === "Enter") $("#b-entrer").click(); });

// ------------------------------------------------------------------ carte
function initCarte() {
  carte = L.map("carte", { zoomControl: false, attributionControl: true }).setView([42.0, 42.0], 7);
  const plan = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 18, attribution: "© OpenStreetMap" });
  const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 18, attribution: "© Esri" });
  plan.addTo(carte);
  L.control.layers({ "Carte": plan, "Satellite": sat }, {}, { position: "bottomright" }).addTo(carte);
  L.control.zoom({ position: "bottomleft" }).addTo(carte);
  coucheWpt = L.layerGroup().addTo(carte);
  route = L.polyline([], { color: "#3DDC6E", weight: 2, dashArray: "6 6" }).addTo(carte);

  const boutons = L.DomUtil.create("div", "carte-boutons");
  boutons.innerHTML = '<button id="b-suivre">SUIVRE L\'AVION</button>';
  $("#carte").appendChild(boutons);
  L.DomEvent.disableClickPropagation(boutons);
  $("#b-suivre").onclick = () => { suivreAvion = true; centrerAvion(); };
  carte.on("dragstart", () => { suivreAvion = false; });

  carte.on("click", (e) => {
    const { lat, lng } = e.latlng;
    const html = `<div><b>Nouveau waypoint</b><br><small>${ddm(lat, true)}<br>${ddm(lng, false)}</small>
      <input id="p-nom" placeholder="Nom (facultatif)" maxlength="12">
      <button id="p-ok" class="principal">AJOUTER AU PLAN</button></div>`;
    const pop = L.popup().setLatLng(e.latlng).setContent(html).openOn(carte);
    setTimeout(() => {
      const ok = document.getElementById("p-ok");
      if (ok) ok.onclick = () => {
        agir("point_ajouter", { lat, lon: lng, nom: document.getElementById("p-nom").value });
        carte.closePopup(pop);
      };
    }, 50);
  });
}

function ddm(v, lat) {
  const h = lat ? (v >= 0 ? "N" : "S") : (v >= 0 ? "E" : "W");
  const a = Math.abs(v), d = Math.floor(a), m = (a - d) * 60;
  return `${h} ${String(d).padStart(lat ? 2 : 3, "0")}°${m.toFixed(3).padStart(6, "0")}'`;
}

function iconeAvion(capRad) {
  const deg = (capRad || 0) * 180 / Math.PI;
  return L.divIcon({ className: "avion-icone", iconSize: [36, 36], iconAnchor: [18, 18],
    html: `<svg viewBox="0 0 36 36" width="36" height="36" style="transform:rotate(${deg}deg)">
      <path d="M18 2 L21 14 L33 20 L33 23 L21 20 L20 29 L24 32 L24 34 L18 32 L12 34 L12 32 L16 29 L15 20 L3 23 L3 20 L15 14 Z"
        fill="#3DDC6E" stroke="#06120A" stroke-width="1"/></svg>` });
}

function centrerAvion() {
  if (etat && etat.position) carte.setView([etat.position.lat, etat.position.lon], Math.max(carte.getZoom(), 9));
}

let signaturePlan = "";
function dessinerCarte() {
  if (!carte || !etat) return;
  if (etat.position) {
    const ll = [etat.position.lat, etat.position.lon];
    if (!avionMarq) avionMarq = L.marker(ll, { icon: iconeAvion(etat.position.cap), zIndexOffset: 1000 }).addTo(carte);
    else { avionMarq.setLatLng(ll); avionMarq.setIcon(iconeAvion(etat.position.cap)); }
    if (suivreAvion && !dessinerCarte.centre) { centrerAvion(); dessinerCarte.centre = true; }
    if (suivreAvion) carte.panTo(ll, { animate: false });
  }
  const actif = etat.wpt ? etat.wpt.num : null;
  const sig = JSON.stringify([etat.plan.map((p) => [p.num, p.lat, p.lon, p.sync, p.nom]), actif]);
  if (sig === signaturePlan) return;
  signaturePlan = sig;
  coucheWpt.clearLayers();
  const pts = [];
  etat.plan.forEach((p) => {
    if (p.num === null) return;
    const cl = "wpt-icone" + (p.sync ? "" : " a-envoyer") + (p.num === actif ? " actif" : "");
    const m = L.marker([p.lat, p.lon], { draggable: true,
      icon: L.divIcon({ className: "", html: `<div class="${cl}">${p.num}</div>`, iconSize: [30, 30], iconAnchor: [15, 15] }) });
    m.on("click", () => ouvrirWpt(p, m));
    m.on("dragend", (e) => {
      const ll = e.target.getLatLng();
      agir("point_deplacer", { num: p.num, lat: ll.lat, lon: ll.lng });
    });
    m.addTo(coucheWpt);
    pts.push([p.lat, p.lon]);
  });
  route.setLatLngs(pts);
  if (!etat.position && pts.length && !dessinerCarte.centrePlan) {
    carte.fitBounds(pts, { padding: [40, 40], maxZoom: 10 }); dessinerCarte.centrePlan = true;
  }
}

function ouvrirWpt(p, marqueur) {
  choisi = p.num;
  const alt = p.alt_m === null ? "altitude en cours…" : `${Math.round(p.alt_m * 3.28084)} ft`;
  const html = `<div><b>WPT ${p.num} — ${esc(p.nom)}</b><br><small>${esc(p.texte)}<br>${alt} · ${p.sync ? "dans l'avion" : "À ENVOYER"}</small>
    <button id="w-aller" class="principal">Y ALLER</button>
    <button id="w-too">JDAM SUR CE WAYPOINT</button>
    <input id="w-nom" placeholder="Nouveau nom" maxlength="12">
    <button id="w-renommer">RENOMMER</button>
    <button id="w-suppr" class="rouge">RETIRER DU PLAN</button></div>`;
  marqueur.bindPopup(html).openPopup();
  setTimeout(() => {
    const g = (id) => document.getElementById(id);
    if (!g("w-aller")) return;
    g("w-aller").onclick = () => { agir("aller", { num: p.num }); carte.closePopup(); };
    g("w-too").onclick = () => { agir("jdam_too", { num: p.num }); carte.closePopup(); };
    g("w-renommer").onclick = () => { agir("point_renommer", { num: p.num, nom: g("w-nom").value }); carte.closePopup(); };
    g("w-suppr").onclick = () => { agir("point_supprimer", { num: p.num }); carte.closePopup(); };
  }, 50);
  rendrePlan();
}

function esc(t) { return String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// ------------------------------------------------------------------ panneaux
$$("#onglets button").forEach((b) => b.onclick = () => {
  $$("#onglets button").forEach((x) => x.classList.toggle("actif", x === b));
  $$(".onglet").forEach((o) => (o.hidden = o.id !== "o-" + b.dataset.onglet));
  $("main").classList.toggle("sans-carte", b.dataset.onglet !== "plan");     // la carte : onglet PLAN seulement
  if (carte) setTimeout(() => carte.invalidateSize(), 80);
});
// plein ecran, et ecran qui ne s'eteint pas (verrou d'ecran si le navigateur le permet,
// sinon une petite video muette qui tourne en boucle)
let verrouEcran = null;
async function garderAllume() {
  try {
    if (navigator.wakeLock) { verrouEcran = await navigator.wakeLock.request("screen"); return; }
  } catch (e) { /* pas permis : on passe a la video */ }
  try { const v = $("#veille"); v.hidden = false; v.volume = 0.01; await v.play(); } catch (e) { /* rien */ }
}
$("#b-plein").onclick = async () => {
  const racine = document.documentElement;
  try {
    if (!document.fullscreenElement) await (racine.requestFullscreen || racine.webkitRequestFullscreen).call(racine);
    else await document.exitFullscreen();
  } catch (e) { toast("Plein écran refusé par le navigateur."); }
  garderAllume();
};
document.addEventListener("fullscreenchange", () => ($("#b-plein").textContent = document.fullscreenElement ? "QUITTER" : "PLEIN ÉCRAN"));
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && (verrouEcran || !$("#veille").paused)) garderAllume(); });
$$("[data-act]").forEach((b) => b.onclick = () => agir(b.dataset.act));
$$("[data-mode]").forEach((b) => b.onclick = () => agir("defense", { mode: b.dataset.mode }));
$("#b-chaff").onclick = () => agir("leurre", { sorte: "chaff" });
$("#b-flare").onclick = () => agir("leurre", { sorte: "flare" });
$("#b-ici").onclick = () => agir("point_ici");
$("#b-nouveau").onclick = () => { if (confirm("Vider le plan du copilote ? (pas les waypoints de l'avion)")) agir("plan_nouveau"); };
$("#b-ajouter-coord").onclick = () => {
  const c = lireCoord($("#s-coord"));
  if (!c) { toast("Coordonnées incomplètes : degrés, minutes, secondes."); return; }
  agir("point_ajouter", { lat: c[0], lon: c[1], nom: $("#s-nom").value, num: $("#s-num").value });
  ["#s-nom", "#s-num"].forEach((s) => ($(s).value = ""));
  monterCoord($("#s-coord"));
};
$("#b-frein").onclick = () => agir("frein", { serrer: !(etat && etat.avion && etat.avion.frein) });
$("#b-ravito").onclick = () => agir("ravito");
$("#b-marquer").onclick = () => agir("marquer");
$("#b-stop").onclick = () => agir("stop");
$("#b-stop-bande").onclick = () => agir("stop");
$$("[data-proc]").forEach((b) => b.onclick = () => agir("procedure", { cle: b.dataset.proc }));
$("#b-tacan").onclick = () => agir("tacan", tacanChoisi === null ? {} : { i: tacanChoisi });
$("#b-tacan-ap").onclick = () => agir("tacan_ap", tacanChoisi === null ? {} : { i: tacanChoisi });
$("#b-tacan-ajouter").onclick = () => {
  agir("tacan_ajouter", { nom: $("#t-nom").value, canal: $("#t-canal").value, bande: $("#t-bande").value, mode: $("#t-mode").value });
  $("#t-nom").value = ""; $("#t-canal").value = "";
};
$("#b-jdam-prog").onclick = () => {
  const plan = {};
  let faux = null;
  $$("#jdam-stations select").forEach((s) => {
    if (s.value === "") return;
    if (s.value !== "coord") { plan[s.dataset.st] = s.value; return; }
    const c = lireCoord(s.parentElement.querySelector(".coord"));
    if (!c) faux = s.dataset.st; else plan[s.dataset.st] = { lat: c[0], lon: c[1] };
  });
  if (faux) { toast(`Station ${faux} : coordonnées incomplètes.`); return; }
  agir("jdam_programmer", { plan });
};
$("#b-ap-cap").onclick = () => agir("ap_cap", { vers: "actuel" });
$("#b-ap-wpt").onclick = () => agir("ap_cap", { vers: "wpt", num: $("#ap-wpt").value });
$("#b-ap-deg").onclick = () => agir("ap_cap", { vers: "cap", cap: $("#ap-deg").value });
$("#b-jettison").onclick = () => {
  const b = $("#b-jettison");
  if (!jettisonPret) {
    jettisonPret = true;
    b.textContent = "CONFIRMER LE LARGAGE";
    setTimeout(() => { jettisonPret = false; b.textContent = "LARGUER (JETTISON)"; }, 4000);
    return;
  }
  jettisonPret = false;
  b.textContent = "LARGUER (JETTISON)";
  agir("jettison", { stations: Array.from(selArmes) });
};
$("#b-jdam-too").onclick = () => agir("jdam_too", { num: $("#jdam-too-wpt").value, stations: Array.from(selArmes) });
$$("#jdam-mode button").forEach((b) => (b.onclick = () => { jdamMode = b.dataset.m; $("#avion-armes").dataset.sig = ""; rendreArmes(); }));

// ---------------------------------------------- saisie de coordonnees
// Comme sur les ecrans du Hornet : N 31°43'08"  E 064°48'27". On ne tape que des
// chiffres ; N/S et E/W se choisissent par bouton, et on passe seul a la case suivante.
function hemiDefaut() {
  const p = etat && etat.position;
  return [p && p.lat < 0 ? "S" : "N", p && p.lon < 0 ? "W" : "E"];
}
function monterCoord(el, valeurs) {
  const v = valeurs || {};
  const [hLat, hLon] = hemiDefaut();
  const ligne = (axe, hems, hem, deg) => `<div class="ligne" data-axe="${axe}">
      <div class="hemi">${hems.map((h) => `<button type="button" data-h="${h}" class="${h === hem ? "actif" : ""}">${h}</button>`).join("")}</div>
      <input data-c="d" inputmode="numeric" maxlength="${deg}" placeholder="${deg === 2 ? "31" : "064"}" value="${v[axe + "d"] || ""}"><span class="u">°</span>
      <input data-c="m" inputmode="numeric" maxlength="2" placeholder="00" value="${v[axe + "m"] || ""}"><span class="u">'</span>
      <input data-c="s" inputmode="numeric" maxlength="2" placeholder="00" value="${v[axe + "s"] || ""}"><span class="u">"</span>
    </div>`;
  el.innerHTML = ligne("lat", ["N", "S"], v.lath || hLat, 2) + ligne("lon", ["E", "W"], v.lonh || hLon, 3);
  const champs = Array.from(el.querySelectorAll("input"));
  champs.forEach((c, i) => {
    c.oninput = () => {
      c.value = c.value.replace(/\D/g, "");
      if (c.value.length >= c.maxLength && champs[i + 1]) champs[i + 1].focus();
      if (el.onchange) el.onchange();
    };
  });
  el.querySelectorAll(".hemi button").forEach((b) => {
    b.onclick = () => {
      b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("actif", x === b));
      if (el.onchange) el.onchange();
    };
  });
}
function valeursCoord(el) {
  const out = {};
  el.querySelectorAll(".ligne").forEach((l) => {
    const axe = l.dataset.axe;
    out[axe + "h"] = l.querySelector(".hemi .actif").dataset.h;
    l.querySelectorAll("input").forEach((c) => (out[axe + c.dataset.c] = c.value));
  });
  return out;
}
function lireCoord(el) {
  const v = valeursCoord(el);
  const une = (axe, max) => {
    if (v[axe + "d"] === "") return null;
    const d = Number(v[axe + "d"]), m = Number(v[axe + "m"] || 0), sec = Number(v[axe + "s"] || 0);
    if (d > max || m > 59 || sec > 59) return null;
    return ("SW".includes(v[axe + "h"]) ? -1 : 1) * (d + m / 60 + sec / 3600);
  };
  const lat = une("lat", 90), lon = une("lon", 180);
  return lat === null || lon === null ? null : [lat, lon];
}
monterCoord($("#s-coord"));
const jdamCoord = {};          // station -> ce qui est tape dans ses cases

// ------------------------------------------------------------------ rendu
function rendre() {
  const e = etat, a = e.avion || {};
  const pas = $("#etat-lien");
  pas.textContent = !e.en_f18 ? "EN ATTENTE DE DCS" : e.pause ? "PAUSE" : "EN LIGNE";
  pas.className = "pastille " + (!e.en_f18 ? "" : e.pause ? "pause" : "ok");
  $("#i-carbu").textContent = a.carburant != null ? Math.round(a.carburant) : "—";
  $("#i-carbu").parentElement.classList.toggle("bas", a.carburant != null && a.bingo && a.carburant < a.bingo);
  $("#i-alt").textContent = a.altitude != null ? Math.round(a.altitude) : "—";
  $("#i-vit").textContent = a.vitesse != null ? Math.round(a.vitesse) : "—";
  $("#i-wpt").textContent = e.wpt && e.wpt.num != null
    ? `${e.wpt.num}${e.wpt.tgt ? " TGT" : ""}${e.wpt.dist != null ? " · " + Math.round(e.wpt.dist) + "NM" : ""}` : "—";
  $$("[data-mode]").forEach((b) => b.classList.toggle("actif", b.dataset.mode === e.defense));
  $("#n-chaff").textContent = e.leurres ? e.leurres[0] : "";
  $("#n-flare").textContent = e.leurres ? e.leurres[1] : "";

  const m = $("#menace");
  const accroche = e.menaces.filter((x) => x.niveau === "clignote");
  if (a.sam || a.cw) { m.hidden = false; m.className = ""; m.textContent = "TIR ! " + (accroche[0] ? accroche[0].nom : "missile"); }
  else if (accroche.length) { m.hidden = false; m.className = ""; m.textContent = accroche.map((x) => x.nom).join(", ") + " — NOUS ACCROCHE"; }
  else if (e.menaces.length) { m.hidden = false; m.className = "calme"; m.textContent = "RWR : " + e.menaces.map((x) => x.nom).join(", "); }
  else m.hidden = true;

  // procedure en cours : visible sur tous les onglets, avec STOP
  const pb = $("#proc-bande");
  pb.hidden = !e.procedure;
  if (e.procedure) {
    const av = e.avancement ? ` ${e.avancement[0]}/${e.avancement[1]}` : "";
    const att = e.en_attente && e.en_attente.length ? ` · ensuite : ${e.en_attente.join(", ")}` : "";
    $("#proc-texte").textContent = `${e.procedure}${av}${e.etape ? " — " + e.etape : ""}${att}`;
  }
  $("#version").textContent = e.version ? "Copilote version " + e.version : "";
  $("#b-envoyer").textContent = e.a_envoyer ? `ENVOYER À L'AVION (${e.a_envoyer})` : "ENVOYER À L'AVION";
  rendrePlan(); rendreArmes(); rendreTacan(); rendreAvion(); rendreJournal();
  dessinerCarte();
}

function rendrePlan() {
  if (!etat) return;
  const ul = $("#liste-plan");
  const sig = JSON.stringify([etat.plan, choisi, etat.wpt && etat.wpt.num]);
  if (ul.dataset.sig === sig) return;
  ul.dataset.sig = sig;
  ul.innerHTML = "";
  if (!etat.plan.length) { ul.innerHTML = '<li class="aide">Plan vide. Touche la carte, ou LIRE L\'AVION.</li>'; return; }
  etat.plan.forEach((p) => {
    const li = document.createElement("li");
    li.className = (p.sync ? "" : "a-envoyer") + (p.num === choisi ? " choisi" : "");
    const alt = p.alt_m === null ? "" : ` · ${Math.round(p.alt_m * 3.28084)} ft`;
    li.innerHTML = `<span class="num">${p.num ?? "—"}</span>
      <span class="txt">${esc(p.nom)}<br><small>${esc(p.texte)}${alt}</small></span>
      <span class="etat">${p.sync ? "AVION" : "À ENVOYER"}</span>
      <button>Y ALLER</button>`;
    li.querySelector("button").onclick = (ev) => { ev.stopPropagation(); agir("aller", { num: p.num }); };
    li.onclick = () => { choisi = p.num; carte.setView([p.lat, p.lon], Math.max(carte.getZoom(), 9)); suivreAvion = false; rendrePlan(); };
    ul.appendChild(li);
  });
}

function optionsWpt(valeur) {
  return '<option value="">—</option>' + etat.plan.filter((p) => p.num !== null)
    .map((p) => `<option value="${p.num}" ${String(valeur) === String(p.num) ? "selected" : ""}>${p.num} ${esc(p.nom)}</option>`).join("");
}

// ------------------------------------------------------------- ARMES
// Vue de l'avion (aile gauche a gauche, comme sur la page STORES). On touche une
// arme pour la choisir ; plusieurs armes identiques peuvent etre choisies ensemble.
const selArmes = new Set();
let jettisonPret = false;       // le largage demande deux appuis
let jdamMode = "PP";
// Vue de face : l'aile gauche de l'avion (station 1) est a droite de l'image.
const XS = [434, 383, 332, 281, 230, 179, 128, 77, 26];      // stations 1 a 9

function nomArme(a) { return (a.nom || "").replace(/\(V\)\d\/B/, ""); }
function etatArme(a) {
  const e = (a.etat || "").toUpperCase();
  if (e.startsWith("RDY")) return "pret";
  if (e) return "attente";
  return "inconnu";
}
// ---------------------------------------------------------------- dessins
// Rien n'est invente : chaque arme est tracee d'apres ses vraies dimensions (metres) :
// L longueur, D diametre, ailettes (position depuis le nez, corde, demi-envergure).
// La vue de face et le profil sortent de la meme fiche, tous a la meme echelle.
const ARMES_DIM = {
  aim9:    { nom: "Sidewinder", guidage: "infrarouge", L: 2.85, D: 0.127, nez: "dome", ail: [{ pos: 0.25, c: 0.2, h: 0.19, f: "delta" }, { pos: 2.25, c: 0.55, h: 0.315, f: "trap" }], face: [{ a0: 45, h: 0.315 }] },
  aim120:  { nom: "AMRAAM", guidage: "radar actif", L: 3.66, D: 0.178, nez: "ogive", ail: [{ pos: 1.72, c: 0.4, h: 0.265, f: "delta" }, { pos: 3.3, c: 0.34, h: 0.3, f: "trap" }], face: [{ a0: 45, h: 0.3 }] },
  aim7:    { nom: "Sparrow", guidage: "radar semi-actif", L: 3.66, D: 0.203, nez: "ogive", ail: [{ pos: 1.5, c: 0.65, h: 0.51, f: "delta" }, { pos: 3.2, c: 0.42, h: 0.4, f: "delta" }], face: [{ a0: 45, h: 0.51 }] },
  mk82:    { nom: "bombe 500 lb", guidage: "non guidée", L: 2.21, D: 0.273, nez: "bombe", queue: 0.3, ail: [{ pos: 1.72, c: 0.46, h: 0.19, f: "trap" }], face: [{ a0: 45, h: 0.19 }] },
  mk83:    { nom: "bombe 1000 lb", guidage: "non guidée", L: 3.0, D: 0.357, nez: "bombe", queue: 0.3, ail: [{ pos: 2.35, c: 0.6, h: 0.25, f: "trap" }], face: [{ a0: 45, h: 0.25 }] },
  mk84:    { nom: "bombe 2000 lb", guidage: "non guidée", L: 3.28, D: 0.457, nez: "bombe", queue: 0.3, ail: [{ pos: 2.6, c: 0.64, h: 0.32, f: "trap" }], face: [{ a0: 45, h: 0.32 }] },
  gbu38:   { nom: "JDAM 500 lb", guidage: "GPS", L: 2.35, D: 0.273, nez: "bombe", kit: 0.24, ail: [{ pos: 0.72, c: 0.55, h: 0.175, f: "trap" }, { pos: 1.98, c: 0.34, h: 0.25, f: "trap" }], face: [{ a0: 45, h: 0.25 }, { a0: 0, h: 0.175, n: 2 }] },
  gbu32:   { nom: "JDAM 1000 lb", guidage: "GPS", L: 3.04, D: 0.357, nez: "bombe", kit: 0.22, ail: [{ pos: 0.95, c: 0.7, h: 0.22, f: "trap" }, { pos: 2.6, c: 0.4, h: 0.32, f: "trap" }], face: [{ a0: 45, h: 0.32 }, { a0: 0, h: 0.22, n: 2 }] },
  gbu31:   { nom: "JDAM 2000 lb", guidage: "GPS", L: 3.88, D: 0.457, nez: "bombe", kit: 0.2, ail: [{ pos: 1.2, c: 0.9, h: 0.28, f: "trap" }, { pos: 3.38, c: 0.46, h: 0.4, f: "trap" }], face: [{ a0: 45, h: 0.4 }, { a0: 0, h: 0.28, n: 2 }] },
  gbu12:   { nom: "Paveway II 500 lb", guidage: "laser", L: 3.33, D: 0.273, nez: "tete", ail: [{ pos: 0.5, c: 0.22, h: 0.22, f: "delta" }, { pos: 2.62, c: 0.68, h: 0.3, f: "trap" }], face: [{ a0: 45, h: 0.3 }, { a0: 0, h: 0.22 }] },
  gbu16:   { nom: "Paveway II 1000 lb", guidage: "laser", L: 3.7, D: 0.357, nez: "tete", ail: [{ pos: 0.55, c: 0.25, h: 0.27, f: "delta" }, { pos: 2.9, c: 0.75, h: 0.36, f: "trap" }], face: [{ a0: 45, h: 0.36 }, { a0: 0, h: 0.27 }] },
  gbu10:   { nom: "Paveway II 2000 lb", guidage: "laser", L: 4.32, D: 0.457, nez: "tete", ail: [{ pos: 0.6, c: 0.28, h: 0.32, f: "delta" }, { pos: 3.45, c: 0.82, h: 0.42, f: "trap" }], face: [{ a0: 45, h: 0.42 }, { a0: 0, h: 0.32 }] },
  agm65:   { nom: "Maverick", guidage: "laser (E) ou infrarouge (F)", L: 2.49, D: 0.305, nez: "dome", ail: [{ pos: 0.95, c: 1.25, h: 0.36, f: "delta" }, { pos: 2.25, c: 0.2, h: 0.36, f: "trap" }], face: [{ a0: 45, h: 0.36 }] },
  agm88:   { nom: "HARM", guidage: "antiradar", L: 4.17, D: 0.254, nez: "ogive", ail: [{ pos: 1.55, c: 0.75, h: 0.565, f: "delta" }, { pos: 3.75, c: 0.38, h: 0.32, f: "trap" }], face: [{ a0: 45, h: 0.565 }] },
  agm84:   { nom: "Harpoon / SLAM", guidage: "antinavire", L: 3.85, D: 0.343, nez: "dome", ail: [{ pos: 1.6, c: 0.45, h: 0.455, f: "trap" }, { pos: 3.45, c: 0.3, h: 0.4, f: "trap" }], face: [{ a0: 45, h: 0.455 }] },
  agm62:   { nom: "Walleye II", guidage: "télévision", L: 4.04, D: 0.457, nez: "dome", ail: [{ pos: 1.9, c: 1.6, h: 0.65, f: "delta" }], face: [{ a0: 45, h: 0.65 }] },
  agm154:  { nom: "JSOW", guidage: "GPS, planante", L: 4.06, D: 0.34, nez: "bombe", boite: [0.34, 0.44], ail: [{ pos: 3.6, c: 0.4, h: 0.3, f: "trap" }], face: [{ a0: 45, h: 0.3 }] },
  adm141:  { nom: "TALD", guidage: "leurre", L: 2.34, D: 0.25, nez: "bombe", boite: [0.25, 0.25], ail: [{ pos: 1.0, c: 0.4, h: 0.4, f: "trap" }], face: [{ a0: 0, h: 0.4, n: 2 }] },
  bidon:   { nom: "bidon 330 gallons", guidage: "carburant", L: 4.5, D: 0.66, nez: "fuseau", queue: 0.3, ail: [{ pos: 3.75, c: 0.5, h: 0.42, f: "trap" }], face: [{ a0: 0, h: 0.42, n: 2 }] },
  atflir:  { nom: "pod de ciblage", guidage: "infrarouge et laser", L: 1.83, D: 0.33, nez: "dome", ail: [], face: [], optique: true },
  lau:     { nom: "panier de roquettes", guidage: "non guidées", L: 2.0, D: 0.4, nez: "dome", ail: [], face: [], tubes: true },
};
function ficheArme(a) {
  const n = ((a.nom || "") + " " + (a.court || "") + " " + (a.type || "")).toUpperCase();
  const t = [[/AIM-?9|\b9[MXL]\b/, "aim9"], [/AIM-?120|\bA[MB]\b/, "aim120"], [/AIM-?7|\b7[MFP]/, "aim7"],
    [/GBU-?38|J-82/, "gbu38"], [/GBU-?32|J-83/, "gbu32"], [/GBU-?31|J-84|J-109/, "gbu31"],
    [/GBU-?12/, "gbu12"], [/GBU-?16/, "gbu16"], [/GBU-?(10|24)/, "gbu10"],
    [/AGM-?65|MAV/, "agm65"], [/AGM-?88|HARM/, "agm88"], [/AGM-?84|HARPOON|SLAM/, "agm84"],
    [/AGM-?62|WALLEYE/, "agm62"], [/AGM-?154|JSOW/, "agm154"], [/ADM-?141|TALD/, "adm141"],
    [/MK[-_ ]?84/, "mk84"], [/MK[-_ ]?83/, "mk83"], [/MK|BDU|CBU|ROCKEYE/, "mk82"],
    [/LAU|ZUNI|HYDRA|ROQ/, "lau"], [/FPU|FUEL|BIDON/, "bidon"], [/FLIR|LITENING|POD|AAQ|ASQ/, "atflir"]];
  for (const [re, cle] of t) if (re.test(n)) return ARMES_DIM[cle];
  return ARMES_DIM[{ aa: "aim120", jdam: "gbu38", laser: "gbu12", bidon: "bidon", pod: "atflir" }[a.famille] || "mk82"];
}
const f1 = (v) => Math.round(v * 10) / 10;
// Vue de face : le corps (rond ou caisson) et ses ailettes, a l'echelle k (pixels par metre).
function vueFace(d, k) {
  const r = (d.D / 2) * k;
  let out = "";
  (d.face || []).forEach((jeu) => {
    const n = jeu.n || 4;
    for (let i = 0; i < n; i++) {
      const ang = ((jeu.a0 + (360 / n) * i) * Math.PI) / 180, c = Math.cos(ang), s2 = Math.sin(ang);
      const w = Math.max(0.7, r * 0.22), h = jeu.h * k;
      const p = (dist, lat) => `${f1(c * dist - s2 * lat)} ${f1(s2 * dist + c * lat)}`;
      out += `<path class="ail" d="M${p(r * 0.85, -w)} L${p(h, -w * 0.35)} L${p(h, w * 0.35)} L${p(r * 0.85, w)} Z"/>`;
    }
  });
  if (d.boite) {
    const [w, h] = [d.boite[0] * k, d.boite[1] * k];
    out += `<rect class="corps" x="${f1(-w / 2)}" y="${f1(-h / 2)}" width="${f1(w)}" height="${f1(h)}" rx="${f1(w * 0.18)}"/>`;
  } else {
    out += `<circle class="corps" r="${f1(r)}"/>`;
  }
  if (d.tubes) {
    for (let i = 0; i < 6; i++) out += `<circle class="detail" cx="${f1(Math.cos(i * 1.047) * r * 0.58)}" cy="${f1(Math.sin(i * 1.047) * r * 0.58)}" r="${f1(r * 0.2)}"/>`;
    out += `<circle class="detail" r="${f1(r * 0.2)}"/>`;
  } else if (d.optique) {
    out += `<circle class="detail" r="${f1(r * 0.62)}"/><circle class="detail" cx="${f1(-r * 0.15)}" cy="${f1(r * 0.1)}" r="${f1(r * 0.3)}"/>`;
  } else {
    out += `<circle class="detail" r="${f1(Math.max(0.5, r * 0.5))}"/><circle class="point" r="${f1(Math.max(0.35, r * 0.12))}"/>`;
  }
  return out;
}
// Profil, nez a gauche, a l'echelle k.
function vueProfil(d, k) {
  const r = (d.D / 2) * k, L = d.L * k;
  const nl = { dome: r * 1.1, ogive: d.D * 2.4 * k, bombe: d.D * 1.7 * k, tete: d.D * 1.2 * k, fuseau: d.D * 2.6 * k }[d.nez] || r;
  const xq = d.queue ? L * (1 - d.queue) : L, rq = d.queue ? r * (d.nez === "fuseau" ? 0.12 : 0.42) : r;
  const rk = d.kit ? r * 0.82 : r, xk = d.kit ? L * (1 - d.kit) : L;
  let out = "";
  (d.ail || []).forEach((a) => {
    const x0 = a.pos * k, x1 = (a.pos + a.c) * k, h = a.h * k, xt = a.f === "delta" ? x0 + (x1 - x0) * 0.78 : x0 + (x1 - x0) * 0.42;
    [-1, 1].forEach((s2) => (out += `<path class="ail" d="M${f1(x0)} ${f1(s2 * r * 0.8)} L${f1(xt)} ${f1(s2 * h)} L${f1(x1)} ${f1(s2 * h)} L${f1(x1)} ${f1(s2 * r * 0.8)} Z"/>`));
  });
  if (d.nez === "tete") {      // tete chercheuse laser : petit corps et sa bague, devant la bombe
    out += `<path class="corps" d="M0 ${f1(-r * 0.3)} H${f1(nl * 0.5)} L${f1(nl)} ${f1(-r * 0.62)} V${f1(r * 0.62)} L${f1(nl * 0.5)} ${f1(r * 0.3)} H0 Z"/>
      <rect class="ail" x="${f1(nl * 0.08)}" y="${f1(-r * 0.62)}" width="${f1(nl * 0.14)}" height="${f1(r * 1.24)}"/>
      <path class="corps" d="M${f1(nl)} ${f1(-r * 0.62)} Q${f1(nl * 1.6)} ${f1(-r)} ${f1(nl * 2.2)} ${f1(-r)} H${f1(L * 0.8)} L${f1(L)} ${f1(-r * 0.5)} V${f1(r * 0.5)} L${f1(L * 0.8)} ${f1(r)} H${f1(nl * 2.2)} Q${f1(nl * 1.6)} ${f1(r)} ${f1(nl)} ${f1(r * 0.62)} Z"/>`;
  } else {
    out += `<path class="corps" d="M0 0 Q${f1(nl * 0.35)} ${f1(-r)} ${f1(nl)} ${f1(-r)} H${f1(Math.min(xq, xk))}
      ${d.kit ? `L${f1(xk + r * 0.3)} ${f1(-rk)} H${f1(L)} V${f1(rk)} H${f1(xk + r * 0.3)} L${f1(xk)} ${f1(r)}` : `L${f1(L)} ${f1(-rq)} V${f1(rq)} L${f1(xq)} ${f1(r)}`}
      H${f1(nl)} Q${f1(nl * 0.35)} ${f1(r)} 0 0 Z"/>`;
  }
  // l'ailette qui nous fait face, et les jonctions du corps
  (d.ail || []).forEach((a) => (out += `<path class="detail" d="M${f1((a.pos + a.c * 0.2) * k)} 0 H${f1((a.pos + a.c) * k)}"/>`));
  out += `<path class="detail" d="M${f1(nl)} ${f1(-r)} V${f1(r)}${d.kit ? ` M${f1(xk)} ${f1(-r)} V${f1(r)}` : ""}${d.queue ? ` M${f1(xq)} ${f1(-r)} V${f1(r)}` : ""}"/>`;
  if (d.optique) out += `<circle class="detail" cx="${f1(r * 0.9)}" cy="0" r="${f1(r * 0.6)}"/>`;
  return out;
}
// ------------------------------------------------- images du guide de l'utilisateur
// Si l'utilisateur a installe son guide de reference sur le PC, on affiche SES images
// (l'avion et les armes), redessinees en vert. Elles ne sont pas dans le programme :
// on ne garde ici que l'endroit ou elles se trouvent sur les pages (guide v35).
const GUIDE_BOITES = {
  86: { avion: [90, 773, 1531, 1227] },
  88: { aim7: [560, 131, 1126, 224], aim9: [560, 512, 1126, 589], aim120: [560, 840, 1126, 924],
        adm141: [560, 1197, 1126, 1286], agm62: [560, 1440, 1126, 1526], agm65: [560, 1679, 1126, 1765] },
  89: { agm84: [560, 128, 1130, 221], agm88: [560, 533, 1130, 614], agm154: [560, 770, 1130, 867],
        hydra: [576, 1141, 1552, 1243], zuni: [576, 1486, 1552, 1654] },
  90: { bdu: [573, 128, 1552, 246], cbu: [573, 518, 1552, 646], gbu: [573, 792, 1552, 912], mk: [573, 1565, 1552, 1696] },
  91: { litening: [576, 136, 1552, 272], atflir: [576, 421, 1552, 552], aww: [576, 947, 1552, 1058], bidon: [806, 1446, 1552, 1574] },
};
const GUIDE_CLE = { aim9: "aim9", aim120: "aim120", aim7: "aim7", mk82: "mk", mk83: "mk", mk84: "mk",
  gbu12: "gbu", gbu16: "gbu", gbu10: "gbu", agm65: "agm65", agm88: "agm88", agm84: "agm84", agm62: "agm62",
  agm154: "agm154", adm141: "adm141", bidon: "bidon", atflir: "atflir", lau: "hydra" };
const imgGuide = {};           // cle -> { url, w, h }
let guideDemande = false;
function enVert(bitmap, boite, epaissir) {
  const [x1, y1, x2, y2] = boite, w = x2 - x1, h = y2 - y1;
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const g = c.getContext("2d", { willReadFrequently: true });
  g.drawImage(bitmap, x1, y1, w, h, 0, 0, w, h);
  const im = g.getImageData(0, 0, w, h), d = im.data;
  const f0 = [d[4 * (3 * w + 3)], d[4 * (3 * w + 3) + 1], d[4 * (3 * w + 3) + 2]];   // couleur du fond
  let gx = w, gy = h, dx = 0, dy = 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = 4 * (y * w + x);
    const ecart = Math.abs(d[i] - f0[0]) + Math.abs(d[i + 1] - f0[1]) + Math.abs(d[i + 2] - f0[2]);
    const alpha = ecart < 60 ? 0 : Math.min(255, ecart * 1.8);
    d[i] = 61; d[i + 1] = 220; d[i + 2] = 110; d[i + 3] = alpha;       // le vert de l'application
    if (alpha > 90) { if (x < gx) gx = x; if (x > dx) dx = x; if (y < gy) gy = y; if (y > dy) dy = y; }
  }
  g.putImageData(im, 0, 0);
  if (dx <= gx || dy <= gy) return null;
  const r = document.createElement("canvas");            // rogne au dessin
  r.width = dx - gx + 1; r.height = dy - gy + 1;
  const gr = r.getContext("2d");
  // les petits dessins ont des traits tres fins : on les epaissit d'un pixel pour qu'ils restent lisibles
  (epaissir ? [[0, 0], [1, 0], [-1, 0], [0, 1], [0, -1]] : [[0, 0]]).forEach(([ox, oy]) =>
    gr.drawImage(c, gx, gy, r.width, r.height, ox, oy, r.width, r.height));
  return { url: r.toDataURL("image/png"), w: r.width, h: r.height };
}
async function chargerGuide() {
  if (guideDemande || !etat || !etat.guide) return;
  guideDemande = true;
  for (const [page, boites] of Object.entries(GUIDE_BOITES)) {
    try {
      const rep = await fetch(`/guide/${page}.jpg`, { headers: { "X-Jeton": jeton } });
      if (!rep.ok) continue;
      const bitmap = await createImageBitmap(await rep.blob());
      for (const [cle, boite] of Object.entries(boites)) {
        const res = enVert(bitmap, boite, cle !== "avion");
        if (res) imgGuide[cle] = res;
      }
    } catch (e) { /* page absente ou illisible : on garde les dessins du copilote */ }
  }
  $("#avion-armes").dataset.sig = "";
  rendreArmes();
}
function imageArme(a) {
  const d = ficheArme(a), n = ((a.nom || "") + " " + (a.type || "")).toUpperCase();
  const cle = Object.keys(ARMES_DIM).find((k) => ARMES_DIM[k] === d);
  if (/LITENING|AAQ/.test(n) && imgGuide.litening) return imgGuide.litening;
  if (/ZUNI|LAU-10/.test(n) && imgGuide.zuni) return imgGuide.zuni;
  if (/CBU|ROCKEYE|MK[-_ ]?20/.test(n) && imgGuide.cbu) return imgGuide.cbu;
  if (/BDU/.test(n) && imgGuide.bdu) return imgGuide.bdu;
  if (/AWW/.test(n) && imgGuide.aww) return imgGuide.aww;
  return imgGuide[GUIDE_CLE[cle]] || null;
}
// Profil d'une arme, nez en haut, dans une case : l'image du guide, sinon le trace du copilote.
function profilDebout(a, cx, cy, longMax, largMax) {
  const im = imageArme(a), d = ficheArme(a);
  if (im) {
    const L = Math.min(longMax, largMax * (im.w / im.h)), T = (L * im.h) / im.w;
    return `<g transform="translate(${cx},${cy}) rotate(90)"><image href="${im.url}" x="${f1(-L / 2)}" y="${f1(-T / 2)}" width="${f1(L)}" height="${f1(T)}"/></g>`;
  }
  const demi = Math.max(d.D / 2, ...(d.ail || []).map((j) => j.h));
  const k = Math.min(longMax / d.L, largMax / (2 * demi));
  return `<g transform="translate(${cx},${f1(cy - (d.L * k) / 2)}) rotate(90)">${vueProfil(d, k)}</g>`;
}
// Emplacement des points d'emport sur le dessin du guide (mesure sur l'image), stations 1 a 9.
const GUIDE_PYL = [[0.994, 0.803], [0.797, 0.919], [0.697, 0.907], [0.548, 0.955], [0.5, 0.993], [0.452, 0.955], [0.303, 0.907], [0.203, 0.919], [0.006, 0.803]];
function pylonesActifs() {
  const im = imgGuide.avion;
  if (!im) return PYLONES.map(([x, y]) => [x, y - 6]);
  const W = 416, H = (W * im.h) / im.w;
  return GUIDE_PYL.map(([fx, fy]) => [f1(22 + fx * W), f1(2 + fy * H)]);
}
function chargesSousAvion(sts, pyl) {
  return sts.map((a) => {
    if (!a.n) return "";
    const [px, py] = pyl[a.st - 1], d = ficheArme(a), r = (d.D / 2) * ECH;
    const bas = d.boite ? (d.boite[1] / 2) * ECH : r;
    const un = (cx) => `<g transform="translate(${cx},${f1(py + bas + 0.8)})">${vueFace(d, ECH)}</g>`;
    const ecart = Math.max(r, 3.2) + 1.6;
    return a.n >= 2 ? `<path class="rack" d="M${f1(px - ecart)} ${py} H${f1(px + ecart)}"/>` + un(f1(px - ecart)) + un(f1(px + ecart)) : un(px);
  }).join("");
}
function avionDuGuide(sts, pyl) {
  const im = imgGuide.avion, W = 416, H = (W * im.h) / im.w;
  return `<image href="${im.url}" x="22" y="2" width="${W}" height="${f1(H)}"/>${chargesSousAvion(sts, pyl)}`;
}
function dessinArme(a, x) {
  if (!a.n) return "";
  if (imgGuide.avion) {                                   // guide installe : profils, nez en haut
    if (a.n >= 2) return profilDebout(a, x - 10.5, 168, 64, 17) + profilDebout(a, x + 10.5, 168, 64, 17);
    return profilDebout(a, x, 168, 66, 36);
  }
  const d = ficheArme(a), demi = Math.max(d.D / 2, ...(d.face || []).map((j) => j.h), d.boite ? d.boite[1] / 2 : 0);
  const deux = a.n >= 2, place = deux ? 10.5 : 21;
  const k = Math.min(62, place / demi);                 // meme echelle pour toutes, reduite si l'arme deborde
  const un = (cx) => `<g transform="translate(${cx},166)">${vueFace(d, k)}</g>`;
  if (!deux) return un(x);
  return `<path class="rack" d="M${x - 11} 141 H${x + 11} L${x + 9} 146 H${x - 9} Z M${x} 136 V141"/>` + un(x - 11) + un(x + 11);
}
// Le Hornet vu de face, trace d'apres ses cotes : 35 pixels par metre, plan de l'aile a y = 100.
// Envergure 11,43 m, derives inclinees de 20 degres, aile a 3 degres de diedre negatif,
// pylones a 2,24 m et 3,35 m de l'axe.
const ECH = 35;
const PYLONES = [[430, 106], [347, 120], [308, 120], [262, 131], [230, 134], [198, 131], [152, 120], [113, 120], [30, 106]];
function hornetDeFace(sts) {
  const charges = sts.map((a) => {
    if (!a.n) return "";
    const [px, py] = PYLONES[a.st - 1], d = ficheArme(a), r = (d.D / 2) * ECH;
    const bas = d.boite ? (d.boite[1] / 2) * ECH : r;
    const un = (cx) => `<g transform="translate(${cx},${f1(py + bas + 0.8)})">${vueFace(d, ECH)}</g>`;
    const ecart = Math.max(r, 3.2) + 1.6;
    return a.n >= 2 ? `<path class="rack" d="M${f1(px - ecart)} ${py} H${f1(px + ecart)}"/>` + un(f1(px - ecart)) + un(f1(px + ecart)) : un(px);
  }).join("");
  const miroir = (d, cls) => `<path class="${cls}" d="${d}"/><path class="${cls}" transform="translate(460,0) scale(-1,1)" d="${d}"/>`;
  return `<g class="hornet">
    ${miroir("M199 104.5 L115 109.6 L115 111 L199 108.5 Z", "trait")}
    ${miroir("M198.5 84 L173.5 14 L176.5 13 L203.5 82 Z", "trait")}
    ${miroir("M196 80 L176 22", "fin")}
    ${miroir("M195 95 L36 103 L36 105.5 L195 103.5 Z", "trait")}
    ${miroir("M190 97.2 L60 103.4 M152 99 V103.8 M113 100.9 V104", "fin")}
    ${miroir("M24 101.5 H36 V107 H24 Z", "trait")}
    ${miroir("M150.5 104 H153.5 L153 120 H151 Z M111.5 104.5 H114.5 L114 120 H112 Z", "trait")}
    <path class="trait plein" d="M215 84 C208 85 199 89 195 95 L195 103.5 C187 106 184.5 116 188 124 C192 133.5 206 136 214 130 C217 127.5 219 126 222 126 L238 126 C241 126 243 127.5 246 130 C254 136 268 133.5 272 124 C275.5 116 273 106 265 103.5 L265 95 C261 89 252 85 245 84 Z"/>
    ${miroir("M191 117 C191 110 195 106 201 106.5 C206 107 209.5 110.5 210 116 C210.5 123 207 129 201.5 129.5 C195.5 130 191 124 191 117 Z", "trait sombre")}
    ${miroir("M194 117 C194 112 197 109.3 201 109.6 C204.5 110 207 112.6 207.2 116.6 C207.5 121.6 205 126 201.3 126.4 C197 126.8 194 122.5 194 117 Z", "fin")}
    <circle class="trait plein" cx="230" cy="109" r="14.7"/>
    <circle class="fin" cx="230" cy="109" r="9.2"/><circle class="point" cx="230" cy="109" r="1.3"/>
    <path class="trait verre" d="M215.3 84.5 C215.3 67 222 57 230 57 C238 57 244.7 67 244.7 84.5 C240 81 220 81 215.3 84.5 Z"/>
    <path class="fin" d="M219 82.4 C219.6 70 224.5 62.5 230 62.5 C235.5 62.5 240.4 70 241 82.4 M230 57 V62.5"/>
    <path class="fin" d="M222 126 L224.5 131.5 H235.5 L238 126"/>
    ${charges}</g>`;
}
function rendreArmes() {
  const ar = etat.armes || { stations: [] };
  const sts = ar.stations;
  // une arme larguee ou changee sort de la selection
  const noms = new Set(Array.from(selArmes).map((st) => nomArme(sts.find((a) => a.st === st) || {})));
  Array.from(selArmes).forEach((st) => { const a = sts.find((x) => x.st === st); if (!a || !a.n) selArmes.delete(st); });
  if (noms.size > 1) selArmes.clear();
  const choisies = sts.filter((a) => selArmes.has(a.st));
  chargerGuide();
  const sig = JSON.stringify([sts, Array.from(selArmes), jdamMode, etat.plan.map((p) => [p.num, p.nom]), Object.keys(imgGuide).length]);
  const zone = $("#avion-armes");
  if (zone.dataset.sig === sig) return;
  zone.dataset.sig = sig;

  const toutes = sts.length ? sts : XS.map((_, i) => ({ st: i + 1, n: 0, famille: "vide" }));
  const stations = toutes.map((a) => {
    const x = XS[a.st - 1], [px, py] = PYLONES[a.st - 1];
    const cls = ["st", a.famille, a.n ? "" : "vide", selArmes.has(a.st) ? "sel" : ""].join(" ");
    return `<g class="${cls}" data-st="${a.st}">
      <rect class="fond" x="${x - 23}" y="124" width="46" height="84" rx="6"/>
      ${dessinArme(a, x)}
      ${a.n ? `<circle class="pt ${etatArme(a)}" cx="${x + 16}" cy="131" r="4"/>` : ""}
      <text class="num" x="${x - 15}" y="135">${a.st}</text>
      ${a.n >= 2 ? `<text class="nb" x="${x}" y="202">×${a.n}</text>` : ""}
      <text x="${x}" y="220">${esc((a.court || "").replace(/^(AIM-120)\w$/, "$1"))}</text>
    </g>`;
  }).join("");
  // l'avion occupe le haut (charges a leur vraie place et a l'echelle), les cases sont dessous
  // un trait relie chaque point d'emport a sa case
  const pyl = pylonesActifs();
  const fils = toutes.map((a) => {
    const x = XS[a.st - 1], [px, py] = pyl[a.st - 1], d = a.n ? ficheArme(a) : null;
    const bas = d ? Math.max(d.D, d.boite ? d.boite[1] : 0) * ECH + 5 : 3;
    const cls = "fil" + (a.n ? "" : " vide") + (selArmes.has(a.st) ? " sel" : "");
    return `<path class="${cls}" d="M${px} ${f1(py + bas)} L${px} ${f1(Math.max(py + bas, 146))} L${x} 154 V158"/>`;
  }).join("");
  zone.innerHTML = `<svg viewBox="0 0 460 262" role="img" aria-label="Avion vu de face et armement">
    ${imgGuide.avion ? avionDuGuide(toutes, pyl) : `<g transform="translate(0,-6)">${hornetDeFace(toutes)}</g>`}
    ${fils}<g transform="translate(0,34)">${stations}</g></svg>`;
  zone.querySelectorAll("g.st").forEach((g) => {
    g.onclick = () => {
      const st = Number(g.dataset.st), a = sts.find((x) => x.st === st);
      if (!a || !a.n) return;
      const deja = sts.find((x) => selArmes.has(x.st));
      if (deja && nomArme(deja) !== nomArme(a)) selArmes.clear();      // un seul type a la fois
      selArmes.has(st) ? selArmes.delete(st) : selArmes.add(st);
      rendreArmes();
    };
  });
  $("#armes-vu").textContent = ar.stores_vu === null || ar.stores_vu === undefined
    ? "· affiche la page STORES pour lire l'état" : ar.stores_vu > 20 ? `· état lu il y a ${ar.stores_vu} s` : "";

  // raccourci : les autres armes identiques a celle qui est choisie, d'un coup
  const rac = $("#armes-raccourcis");
  rac.innerHTML = "";
  if (choisies.length) {
    const pareilles = sts.filter((a) => a.n && nomArme(a) === nomArme(choisies[0]));
    if (pareilles.length > choisies.length) {
      const feminin = ["jdam", "laser", "bombe", "roquette", "walleye"].includes(choisies[0].famille);
      const b = document.createElement("button");
      b.textContent = `${feminin ? "TOUTES" : "TOUS"} LES ${choisies[0].court}`;
      b.onclick = () => { pareilles.forEach((a) => selArmes.add(a.st)); rendreArmes(); };
      rac.appendChild(b);
    }
  }
  rac.hidden = !rac.children.length;

  // ce qu'on peut faire avec la selection : seulement ce qui existe, plus le largage
  const titre = $("#armes-titre"), pj = $("#p-jdam"), jet = $("#armes-jettison");
  titre.classList.toggle("choix", choisies.length > 0);
  $("#armes-profil").hidden = !choisies.length;
  jet.hidden = !choisies.length;
  jettisonPret = false;
  $("#b-jettison").textContent = "LARGUER (JETTISON)";
  if (!choisies.length) {
    titre.textContent = "Touche une arme sur l'avion. Tu peux en toucher plusieurs du même type.";
    pj.hidden = true;
  } else {
    const total = choisies.reduce((n, a) => n + a.n, 0), fam = choisies[0].famille;
    const d = ficheArme(choisies[0]), im = imageArme(choisies[0]);
    titre.textContent = `${total} × ${choisies[0].court} · station${choisies.length > 1 ? "s" : ""} ${choisies.map((a) => a.st).join(", ")}`;
    const dessin = im
      ? `<image href="${im.url}" x="${f1(170 - Math.min(300, 64 * (im.w / im.h)) / 2)}" y="${f1(42 - Math.min(64, 300 * (im.h / im.w)) / 2)}" width="${f1(Math.min(300, 64 * (im.w / im.h)))}" height="${f1(Math.min(64, 300 * (im.h / im.w)))}"/>`
      : `<g transform="translate(${f1((340 - d.L * 70) / 2)},42)">${vueProfil(d, 70)}</g>`;
    $("#armes-profil").innerHTML = `<svg viewBox="0 0 340 96" role="img" aria-label="Profil de l'arme">
      ${dessin}<text x="170" y="92">${esc(d.nom)} · ${esc(d.guidage)} · ${String(d.L).replace(".", ",")} m</text></svg>`;
    pj.hidden = fam !== "jdam";
  }
  if (!pj.hidden) rendreJdam(choisies);
  const ap = $("#ap-wpt"), va = ap.value;
  if (document.activeElement !== ap) ap.innerHTML = optionsWpt(va || "");
}

function rendreJdam(choisies) {
  $$("#jdam-mode button").forEach((b) => b.classList.toggle("actif", b.dataset.m === jdamMode));
  $("#jdam-pp").hidden = jdamMode !== "PP";
  $("#jdam-too").hidden = jdamMode !== "TOO";
  const div = $("#jdam-stations"), avant = {};
  $$("#jdam-stations select").forEach((s) => (avant[s.dataset.st] = s.value));
  div.innerHTML = "";
  choisies.forEach((a) => {
    const st = a.st, ligne = document.createElement("div");
    ligne.className = "station";
    const val = avant[st] ?? etat.jdam.choix[st] ?? "";
    ligne.innerHTML = `<span class="lib">STA ${st}<br><small>${esc(a.court)}${a.n >= 2 ? " ×" + a.n : ""}</small></span>
      <select data-st="${st}">${optionsWpt(val)}<option value="coord" ${val === "coord" ? "selected" : ""}>Coordonnées…</option></select>
      <div class="coord" ${val === "coord" ? "" : "hidden"}></div>`;
    const zone = ligne.querySelector(".coord"), sel = ligne.querySelector("select");
    monterCoord(zone, jdamCoord[st]);
    zone.onchange = () => (jdamCoord[st] = valeursCoord(zone));
    sel.onchange = () => (zone.hidden = sel.value !== "coord");
    div.appendChild(ligne);
  });
  const too = $("#jdam-too-wpt"), v = too.value;
  too.innerHTML = optionsWpt(v || choisi || "");
}

function rendreTacan() {
  const ul = $("#liste-tacan");
  if (tacanChoisi === null && etat.tacan_choisi !== null) tacanChoisi = etat.tacan_choisi;
  const sig = JSON.stringify([etat.tacan, tacanChoisi]);
  if (ul.dataset.sig === sig) return;
  ul.dataset.sig = sig;
  ul.innerHTML = etat.tacan.length ? "" : '<li class="aide">Aucun canal. Ajoute-les ci-dessous.</li>';
  etat.tacan.forEach((t, i) => {
    const li = document.createElement("li");
    li.className = i === tacanChoisi ? "choisi" : "";
    li.innerHTML = `<span class="num">${t.canal}${t.bande}</span><span class="txt">${esc(t.nom)}<br><small>${t.mode}</small></span><button class="rouge">✕</button>`;
    li.onclick = () => { tacanChoisi = i; agir("tacan_choisir", { i }); };
    li.querySelector("button").onclick = (ev) => {
      ev.stopPropagation();
      if (confirm(`Supprimer le canal ${t.canal}${t.bande} ${t.nom} ?`)) { agir("tacan_supprimer", { i }); tacanChoisi = null; }
    };
    ul.appendChild(li);
  });
}

const PROCS = ["demarrage_terre", "demarrage_pa", "avant_decollage", "catapulte", "apres_decollage",
  "fence_in", "fence_out", "air_air", "air_sol", "securite", "ravitaillement", "fin_ravitaillement",
  "atterrissage", "appontage", "apres_atterrissage", "arret"];
function rendreAvion() {
  const g = $("#grille-proc");
  if (!g.childElementCount && etat.procedures) {
    const titres = Object.fromEntries(etat.procedures);
    PROCS.filter((k) => titres[k]).forEach((k) => {
      const b = document.createElement("button");
      b.textContent = titres[k].toUpperCase();
      if (k === "arret") b.className = "rouge";
      b.onclick = () => {
        if (k === "arret" && !confirm("Lancer l'arrêt de l'avion ?")) return;
        agir("procedure", { cle: k });
      };
      g.appendChild(b);
    });
  }
  const pc = $("#proc-en-cours");
  pc.hidden = !etat.procedure;
  pc.textContent = etat.procedure ? "En cours : " + etat.procedure : "";
  const a = etat.avion || {};
  $("#b-frein").textContent = a.frein ? "FREIN PARK : SERRÉ" : "FREIN PARK : LIBRE";
}

function rendreJournal() {
  const ul = $("#journal");
  const sig = JSON.stringify(etat.annonces.slice(-1));
  if (ul.dataset.sig === sig) return;
  ul.dataset.sig = sig;
  ul.innerHTML = etat.annonces.slice().reverse()
    .map((x) => `<li class="${x.u ? "urgent" : ""}"><span class="h">${x.h}</span><span class="txt">${esc(x.t)}</span></li>`).join("");
}

// ------------------------------------------------------------------ boucle
async function rafraichir() {
  try {
    etat = await api("/api/etat");
    rendre();
  } catch (e) {
    if (e.message !== "code") { const p = $("#etat-lien"); p.textContent = "COPILOTE INJOIGNABLE"; p.className = "pastille"; }
  }
}

function demarrer() {
  $("#entree").hidden = true; $("#appli").hidden = false;
  if (!carte) initCarte();
  setTimeout(() => carte.invalidateSize(), 100);
  rafraichir();
  if (!demarrer.boucle) demarrer.boucle = setInterval(rafraichir, 800);
}

if (jeton) demarrer(); else montrerEntree();
