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
  if (b.dataset.onglet === "plan" && carte) setTimeout(() => carte.invalidateSize(), 50);
});
$$("[data-act]").forEach((b) => b.onclick = () => agir(b.dataset.act));
$$("[data-mode]").forEach((b) => b.onclick = () => agir("defense", { mode: b.dataset.mode }));
$("#b-chaff").onclick = () => agir("leurre", { sorte: "chaff" });
$("#b-flare").onclick = () => agir("leurre", { sorte: "flare" });
$("#b-ici").onclick = () => agir("point_ici");
$("#b-nouveau").onclick = () => { if (confirm("Vider le plan du copilote ? (pas les waypoints de l'avion)")) agir("plan_nouveau"); };
$("#b-ajouter-coord").onclick = () => {
  const c = lireCoord($("#s-coord").value);
  if (!c) { toast("Coordonnées non comprises."); return; }
  agir("point_ajouter", { lat: c[0], lon: c[1], nom: $("#s-nom").value, num: $("#s-num").value });
  ["#s-coord", "#s-nom", "#s-num"].forEach((s) => ($(s).value = ""));
};
$("#b-frein").onclick = () => agir("frein", { serrer: !(etat && etat.avion && etat.avion.frein) });
$("#b-ravito").onclick = () => agir("ravito");
$("#b-marquer").onclick = () => agir("marquer");
$("#b-stop").onclick = () => agir("stop");
$$("[data-proc]").forEach((b) => b.onclick = () => agir("procedure", { cle: b.dataset.proc }));
$("#b-tacan").onclick = () => agir("tacan", tacanChoisi === null ? {} : { i: tacanChoisi });
$("#b-tacan-ap").onclick = () => agir("tacan_ap", tacanChoisi === null ? {} : { i: tacanChoisi });
$("#b-tacan-ajouter").onclick = () => {
  agir("tacan_ajouter", { nom: $("#t-nom").value, canal: $("#t-canal").value, bande: $("#t-bande").value, mode: $("#t-mode").value });
  $("#t-nom").value = ""; $("#t-canal").value = "";
};
$("#b-jdam-prog").onclick = () => {
  const plan = {};
  $$("#jdam-stations select").forEach((s) => { if (s.value !== "") plan[s.dataset.st] = s.value; });
  agir("jdam_programmer", { plan });
};
$("#b-jdam-too").onclick = () => agir("jdam_too", { num: $("#jdam-too-wpt").value });

// coordonnees tapees : N41 55.200 E041 51.500  /  N 41°55'12" E 41°51'30"  /  41.92, 41.86
function lireCoord(t) {
  t = t.toUpperCase().replace(/,/g, " ").trim();
  const une = (s, hem) => {
    let signe = 1;
    const m = s.match(new RegExp(`^([${hem}])`));
    if (m) { if ("SW".includes(m[1])) signe = -1; s = s.slice(1); }
    const n = (s.match(/\d+(\.\d+)?/g) || []).map(Number);
    if (!n.length || n.length > 3) return null;
    return signe * (n[0] + (n[1] || 0) / 60 + (n[2] || 0) / 3600);
  };
  let m = t.match(/^([NS].*?)\s+([EWO].*)$/);
  if (m) { const a = une(m[1], "NS"), b = une(m[2].replace("O", "W"), "EW"); return a === null || b === null ? null : [a, b]; }
  m = t.split(/\s+/);
  if (m.length === 2) return [Number(m[0]), Number(m[1])].some(isNaN) ? null : [Number(m[0]), Number(m[1])];
  return null;
}

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

  $("#b-envoyer").textContent = e.a_envoyer ? `ENVOYER À L'AVION (${e.a_envoyer})` : "ENVOYER À L'AVION";
  rendrePlan(); rendreJdam(); rendreTacan(); rendreAvion(); rendreJournal();
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

function rendreJdam() {
  const j = etat.jdam, div = $("#jdam-stations");
  const stations = j.ordre.filter((s) => j.stations[s]);
  const liste = stations.length ? stations : j.ordre;
  const sig = JSON.stringify([liste, j.stations, etat.plan.map((p) => [p.num, p.nom])]);
  if (div.dataset.sig !== sig) {
    const avant = {};
    $$("#jdam-stations select").forEach((s) => (avant[s.dataset.st] = s.value));
    div.dataset.sig = sig;
    div.innerHTML = "";
    liste.forEach((st) => {
      const ligne = document.createElement("div");
      ligne.className = "station";
      const nom = (j.stations[st] || "JDAM").replace("(V)1/B", "").replace("(V)2/B", "");
      const val = avant[st] ?? j.choix[st] ?? "";
      ligne.innerHTML = `<span class="lib">STA ${st}<br><small>${esc(nom)}</small></span>
        <select data-st="${st}">${optionsWpt(val)}</select>`;
      div.appendChild(ligne);
    });
    if (!stations.length) div.insertAdjacentHTML("beforeend", '<div class="aide">Pas de JDAM vues à bord (stations par défaut).</div>');
    const too = $("#jdam-too-wpt"), v = too.value;
    too.innerHTML = optionsWpt(v || choisi || "");
  }
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
