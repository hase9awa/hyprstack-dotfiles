-- Personal HDR/SDR handling; output modes and SDR white are in hyprstack/monitors.lua.
local data = os.getenv("XDG_DATA_HOME") or os.getenv("HOME") .. "/.local/share"
dofile(data .. "/hyprstack-personal/shell/assets/hyprland/dimming.lua")

-- Hyprland 0.56.2 otherwise advertises 203-nit SDR white to HDR-aware clients,
-- independently of the global SDR controls. Synchronize the effective white
-- from sdr_max_luminance * sdrbrightness and normalize SDR window/screen captures
-- to that same white. HDR output gamut and peak stay with Hyprland.
pcall(hl.plugin.load, data .. "/hyprstack-personal/native/hdr-reference/hdr-reference.so")
local ok, sync = pcall(function()
	return hl.plugin.hdr_reference.sync
end)
if ok and type(sync) == "function" then
	sync("desc:Beihai Century Joint Innovation Technology Co.Ltd P275MR+ 0000000000000")
end

-- Chromium 151 renders SDR pages into 8-bit PQ when HDR feedback is used.
-- Prefer sRGB for the current Thorium session; the launch flags retain SDR
-- after a restart. HDR video inside Thorium is consequently displayed in SDR.
pcall(function()
	hl.plugin.hdr_reference.sdr_client("thorium-browser")
end)
