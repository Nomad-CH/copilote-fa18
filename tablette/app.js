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
  $("main").classList.toggle("armes", b.dataset.onglet === "jdam");
  if (carte) setTimeout(() => carte.invalidateSize(), 80);
});
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
let jdamMode = "PP";
const XS = [26, 77, 128, 179, 230, 281, 332, 383, 434];      // stations 1 a 9

function nomArme(a) { return (a.nom || "").replace(/\(V\)\d\/B/, ""); }
function etatArme(a) {
  const e = (a.etat || "").toUpperCase();
  if (e.startsWith("RDY")) return "pret";
  if (e) return "attente";
  return "inconnu";
}
function dessinArme(a, x) {
  if (!a.n) return "";
  const un = (cx) => a.famille === "bidon"
    ? `<ellipse class="arme" cx="${cx}" cy="128" rx="7" ry="20"/>`
    : a.famille === "aa"
      ? `<rect class="arme" x="${cx - 2.5}" y="106" width="5" height="40" rx="2.5"/><path class="arme" d="M${cx - 7} 140h14l-3 6h-8z"/>`
      : a.famille === "pod"
        ? `<rect class="arme" x="${cx - 5}" y="112" width="10" height="30" rx="5"/>`
        : `<rect class="arme" x="${cx - 5}" y="108" width="10" height="34" rx="5"/><path class="arme" d="M${cx - 8} 138h16l-4 8h-8z"/>`;
  return a.n >= 2 ? un(x - 9) + un(x + 9) : un(x);
}
function rendreArmes() {
  const ar = etat.armes || { stations: [] };
  const sts = ar.stations;
  // une arme larguee ou changee sort de la selection
  const noms = new Set(Array.from(selArmes).map((st) => nomArme(sts.find((a) => a.st === st) || {})));
  Array.from(selArmes).forEach((st) => { const a = sts.find((x) => x.st === st); if (!a || !a.n) selArmes.delete(st); });
  if (noms.size > 1) selArmes.clear();
  const choisies = sts.filter((a) => selArmes.has(a.st));
  const sig = JSON.stringify([sts, Array.from(selArmes), jdamMode, etat.plan.map((p) => [p.num, p.nom])]);
  const zone = $("#avion-armes");
  if (zone.dataset.sig === sig) return;
  zone.dataset.sig = sig;

  const stations = (sts.length ? sts : XS.map((_, i) => ({ st: i + 1, n: 0, famille: "vide" }))).map((a) => {
    const x = XS[a.st - 1];
    const cls = ["st", a.famille, a.n ? "" : "vide", selArmes.has(a.st) ? "sel" : ""].join(" ");
    return `<g class="${cls}" data-st="${a.st}">
      <rect class="fond" x="${x - 23}" y="96" width="46" height="74" rx="6"/>
      ${dessinArme(a, x)}
      ${a.n ? `<circle class="pt ${etatArme(a)}" cx="${x + 16}" cy="103" r="4"/>` : ""}
      <text class="num" x="${x - 14}" y="107">${a.st}</text>
      <text x="${x}" y="182">${esc(a.court || "")}${a.n >= 2 ? " ×" + a.n : ""}</text>
    </g>`;
  }).join("");
  zone.innerHTML = `<svg viewBox="0 0 460 190" role="img" aria-label="Avion et armement">
    <path class="cellule" d="M8 84 L200 74 L260 74 L452 84 L452 90 L260 92 L200 92 L8 90 Z"/>
    <path class="cellule" d="M206 70 L176 14 L186 12 L222 62 Z M254 70 L284 14 L274 12 L238 62 Z"/>
    <path class="cellule" d="M150 80 L196 68 L196 78 Z M310 80 L264 68 L264 78 Z"/>
    <ellipse class="cellule" cx="230" cy="76" rx="26" ry="24"/>
    <ellipse class="cellule" cx="230" cy="62" rx="12" ry="13"/>
    <rect class="cellule" x="196" y="78" width="16" height="18" rx="4"/><rect class="cellule" x="248" y="78" width="16" height="18" rx="4"/>
    ${stations}</svg>`;
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

  // raccourcis : toutes les armes identiques d'un coup
  const rac = $("#armes-raccourcis");
  rac.innerHTML = "";
  const groupes = {};
  sts.filter((a) => a.n && !["bidon", "pod", "vide"].includes(a.famille)).forEach((a) => (groupes[nomArme(a)] = (groupes[nomArme(a)] || []).concat(a)));
  Object.entries(groupes).forEach(([nom, liste]) => {
    if (liste.length < 2) return;
    const b = document.createElement("button");
    b.textContent = `TOUTES LES ${liste[0].court}`;
    b.onclick = () => { selArmes.clear(); liste.forEach((a) => selArmes.add(a.st)); rendreArmes(); };
    rac.appendChild(b);
  });
  rac.hidden = !rac.children.length;

  // ce qu'on peut faire avec la selection
  const titre = $("#armes-titre"), pj = $("#p-jdam"), pa = $("#p-autre");
  titre.classList.toggle("choix", choisies.length > 0);
  if (!choisies.length) {
    titre.textContent = "Touche une arme sur l'avion. Tu peux en toucher plusieurs du même type.";
    pj.hidden = pa.hidden = true;
  } else {
    const total = choisies.reduce((n, a) => n + a.n, 0), fam = choisies[0].famille;
    titre.textContent = `${total} × ${choisies[0].court} · station${choisies.length > 1 ? "s" : ""} ${choisies.map((a) => a.st).join(", ")}`;
    pj.hidden = fam !== "jdam";
    pa.hidden = fam === "jdam";
    pa.textContent = {
      aa: "Missiles air-air : sélection et annonces de tir à venir.",
      laser: "Bombes laser : code laser et pod de ciblage à venir (prochaine étape de la feuille de route).",
      maverick: "Maverick : à venir.", harm: "HARM : à venir.", jsow: "JSOW : à venir, comme les JDAM.",
      bombe: "Bombes lisses : mode CCIP / AUTO, quantité, intervalle à venir.",
      bidon: "Bidon : pas de réglage.", pod: "Pod : à venir avec les armes laser.",
    }[fam] || "Réglages de cette arme : à venir.";
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
