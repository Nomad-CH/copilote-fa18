-- Lien entre DCS et le copilote F/A-18 (version 1).
-- Charge par Export.lua. Envoie au copilote, sur cet ordinateur uniquement
-- (127.0.0.1, port UDP 7790) : le texte du RWR, le texte des ecrans du
-- cockpit et l'emport. Ne commande rien dans l'avion.

local CE = {
	port = 7790,
	periode_rwr = 0.1,     -- RWR et emport : 10 fois par seconde
	periode_ecrans = 0.5,  -- ecrans : 2 fois par seconde, seulement s'ils changent
	ecrans = { 1, 2, 3, 4, 5, 6 },
	taille_max = 60000,
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
		return string.format("%.6g", v)
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

local function envoyer(paquet)
	local msg = json(paquet)
	if #msg <= CE.taille_max then
		CE.udp:sendto(msg, "127.0.0.1", CE.port)
	end
end

local function debut()
	local socket = require("socket")
	CE.udp = socket.udp()
	CE.udp:settimeout(0)
	CE.prochain_rwr, CE.prochains_ecrans, CE.derniers = 0, 0, {}
end

local function image()
	if not CE.udp then return end
	local t = appel("LoGetModelTime")
	if type(t) ~= "number" then return end
	if t >= CE.prochain_rwr then
		CE.prochain_rwr = t + CE.periode_rwr
		local self = appel("LoGetSelfData")
		local leurres = appel("LoGetSnares")
		envoyer({
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
