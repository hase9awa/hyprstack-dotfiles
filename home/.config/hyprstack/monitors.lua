-- Personal outputs. The release leaves this file empty.
-- Match KDE's saved SDR white (350 nits), sRGB desktop gamut and fixed refresh.
-- HDR uses the BT.2020 wire gamut; the monitor's mastering gamut comes from EDID.
hl.monitor({
	output = "desc:Beihai Century Joint Innovation Technology Co.Ltd P275MR+ 0000000000000",
	mode = "2560x1440@200",
	position = "1920x0",
	scale = 1,
	bitdepth = 10,
	cm = "hdr",
	vrr = 0,
	sdr_min_luminance = 0,
	sdr_max_luminance = 350,
	sdrbrightness = 1.0,
})

-- This 75 Hz timing is advertised by the personal EDID loaded at boot by
-- hyprstack-benq-75hz.service; the stock EDID only advertises 1080p at 60 Hz.
hl.monitor({
	output = "desc:BNQ BenQ GW2406Z P4H0067101Q",
	mode = "modeline 165.000 1920 1928 1960 2000 1080 1083 1088 1100 +hsync +vsync",
	position = "840x0",
	scale = 1,
	transform = 3,
})

hl.monitor({
	output = "desc:Hisense Electric Co. Ltd. HISENSE 0x00000001",
	disabled = true,
})
