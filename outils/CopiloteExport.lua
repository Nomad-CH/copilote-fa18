-- Lien entre DCS et le copilote F/A-18 (version 3).
-- Charge par Export.lua. Envoie au copilote, sur cet ordinateur uniquement
-- (127.0.0.1, port UDP 7790) : le texte du RWR, le texte des ecrans du
-- cockpit, l'emport, la position de l'avion et celle du centre de la vue
-- (carte F10 : sert a prendre un point sur la carte), et la position de
-- quelques commandes du cockpit.
-- Recoit du copilote (127.0.0.1, port UDP 7791, cet ordinateur seulement) des
-- clics de commandes du cockpit, pour celles que DCS-BIOS manoeuvre mal
-- (poignee de frein, boutons de largage selectif...). Rien d'autre.

local CE = {
	port = 7790,
	periode_rwr = 0.1,     -- RWR et emport : 10 fois par seconde
	periode_ecrans = 0.5,  -- ecrans : 2 fois par seconde, seulement s'ils changent
	ecrans = { 1, 2, 3, 4, 5, 6 },
	taille_max = 60000,
	port_ordres = 7791,
	-- commandes du cockpit dont on renvoie la position (numeros d'argument DCS)
	suivis = { 240, 241, 276, 277, 488, 517, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161 },
}

package.path = package.path .. ";.\\LuaSocket\\?.lua"
package.cpath = package.cpath .. ";.\\LuaSocket\\?.dll"

local SEP = ("%-"):rep(41) .. "\n"

-- petit encodeur JSON (DCS n'en fournit pas dans l'export)
local function json(v)
	local t = type(v)
	if t == "string" then
		return '"' .. v:gsub('[%c"\\]', function(c)
			if c == '"' then return '\\"' end
			if c == "\\" then return "\\\\" end
			if c == "\n" then return "\\n" end
			return string.format("\\u%04x", c:byte())
		end) .. '"'
	elseif t == "number" then
		if v ~= v or v == math.huge or v == -math.huge then return "null" end
		return string.format("%.10g", v)
	elseif t == "boolean" then
		return tostring(v)
	elseif t == "table" then
		if #v > 0 or next(v) == nil then
			local out = {}
			for i = 1, #v do out[i] = json(v[i]) end
			return "[" .. table.concat(out, ",") .. "]"
		end
		local out = {}
		for k, val in pairs(v) do out[#out + 1] = json(tostring(k)) .. ":" .. json(val) end
		return "{" .. table.concat(out, ",") .. "}"
	end
	return "null"
end

local function appel(nom, ...)
	local f = _G[nom]
	if type(f) ~= "function" then return nil end
	local ok, r = pcall(f, ...)
	if ok then return r end
	return nil
end

local function ecran(i)
	local ok, txt = pcall(list_indication, i)
	if not ok or type(txt) ~= "string" then return "" end
	-- les lignes de tirets sont remplacees par un seul caractere (0x1F)
	return (txt:gsub(SEP, "\31"))
end

local function emport()
	local p = appel("LoGetPayloadInfo")
	if type(p) ~= "table" then return nil end
	local stations = {}
	if type(p.Stations) == "table" then
		for i, s in pairs(p.Stations) do
			if type(s) == "table" then
				local w = s.weapon or {}
				local nom = ""
				if (w.level1 or 0) ~= 0 then
					nom = appel("LoGetNameByType", w.level1, w.level2, w.level3, w.level4) or ""
				end
				stations[#stations + 1] = { st = tonumber(i) or 0, nom = nom, n = s.count or 0 }
			end
		end
	end
	return { courante = p.CurrentStation or 0, stations = stations,
		obus = type(p.Cannon) == "table" and p.Cannon.shells or 0 }
end

-- Position de l'avion, et point vise par la camera : sur la carte F10,
-- c'est le centre de l'ecran (le viseur du copilote).
local function positions()
	local av, vue
	local s = appel("LoGetSelfData")
	if type(s) == "table" and type(s.LatLongAlt) == "table" then
		av = { lat = s.LatLongAlt.Lat, lon = s.LatLongAlt.Long, alt = s.LatLongAlt.Alt,
			cap = s.Heading }
	end
	local cam = appel("LoGetCameraPosition")
	if type(cam) == "table" and type(cam.p) == "table" then
		local g = appel("LoLoCoordinatesToGeoCoordinates", cam.p.x, cam.p.z)
		if type(g) == "table" then
			vue = { lat = g.latitude, lon = g.longitude, haut = cam.p.y,
				sol = appel("LoGetAltitude", cam.p.x, cam.p.z) }
		end
	end
	return av, vue
end

local function envoyer(paquet)
	local msg = json(paquet)
	if #msg <= CE.taille_max then
		CE.udp:sendto(msg, "127.0.0.1", CE.port)
	end
end

local function arguments()
	local dev = appel("GetDevice", 0)
	if not dev then return nil end
	local r = {}
	for _, n in ipairs(CE.suivis) do
		local ok, v = pcall(dev.get_argument_value, dev, n)
		if ok and type(v) == "number" then r[tostring(n)] = v end
	end
	return r
end

-- Ordres du copilote : "clic <appareil> <commande> <valeur>" (un par ligne),
-- ou "suivre <arg> <arg> ..." pour choisir les commandes dont on renvoie la position.
local function ordres()
	if not CE.ordres then return end
	for _ = 1, 30 do
		local msg = CE.ordres:receive()
		if not msg then return end
		for ligne in msg:gmatch("[^\n]+") do
			local d, c, v = ligne:match("^clic%s+(%d+)%s+(%d+)%s+(%-?[%d%.]+)%s*$")
			if d then
				local dev = appel("GetDevice", tonumber(d))
				if dev then pcall(dev.performClickableAction, dev, tonumber(c), tonumber(v)) end
			elseif ligne:match("^suivre") then
				local liste = {}
				for n in ligne:gmatch("(%d+)") do liste[#liste + 1] = tonumber(n) end
				if #liste > 0 and #liste <= 64 then CE.suivis = liste end
			end
		end
	end
end

local function debut()
	local socket = require("socket")
	CE.udp = socket.udp()
	CE.udp:settimeout(0)
	local o = socket.udp()
	if o and o:setsockname("127.0.0.1", CE.port_ordres) then
		o:settimeout(0)
		CE.ordres = o
	end
	CE.prochain_rwr, CE.prochains_ecrans, CE.derniers = 0, 0, {}
end

local function image()
	if not CE.udp then return end
	pcall(ordres)
	local t = appel("LoGetModelTime")
	if type(t) ~= "number" then return end
	if t >= CE.prochain_rwr then
		CE.prochain_rwr = t + CE.periode_rwr
		local self = appel("LoGetSelfData")
		local leurres = appel("LoGetSnares")
		local av, vue = positions()
		envoyer({
			pos = av, vue = vue, args = arguments(),
			k = "etat", t = t,
			avion = type(self) == "table" and self.Name or "",
			rwr = ecran(7),
			emport = emport(),
			leurres = type(leurres) == "table" and { leurres.chaff or 0, leurres.flare or 0 } or nil,
		})
	end
	if t >= CE.prochains_ecrans then
		CE.prochains_ecrans = t + CE.periode_ecrans
		for _, i in ipairs(CE.ecrans) do
			local txt = ecran(i)
			-- renvoye aussi toutes les 5 s, au cas ou le copilote demarre en cours de vol
			if txt ~= CE.derniers[i] or (CE.rappel or 0) <= t then
				CE.derniers[i] = txt
				envoyer({ k = "ecran", t = t, i = i, txt = txt:sub(1, CE.taille_max - 200) })
			end
		end
		if (CE.rappel or 0) <= t then CE.rappel = t + 5 end
	end
end

local function fin()
	if CE.udp then
		pcall(envoyer, { k = "fin" })
		CE.udp:close()
		CE.udp = nil
	end
	if CE.ordres then
		CE.ordres:close()
		CE.ordres = nil
	end
end

-- On s'accroche aux fonctions d'export sans casser DCS-BIOS ni les autres scripts.
local prec_debut, prec_image, prec_fin = LuaExportStart, LuaExportAfterNextFrame, LuaExportStop

function LuaExportStart()
	pcall(debut)
	if prec_debut then prec_debut() end
end

function LuaExportAfterNextFrame()
	pcall(image)
	if prec_image then prec_image() end
end

function LuaExportStop()
	pcall(fin)
	if prec_fin then prec_fin() end
end
