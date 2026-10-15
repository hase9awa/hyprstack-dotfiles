local home = os.getenv("HOME")
local config = os.getenv("XDG_CONFIG_HOME") or home .. "/.config"
hl.config({ input = { kb_layout = "us,ru", kb_options = "grp:alt_shift_toggle",
    numlock_by_default = true, accel_profile = "flat" } })
dofile(config .. "/hypr/display-tuning.lua")
local data = os.getenv("XDG_DATA_HOME") or home .. "/.local/share"
hl.env("HYPRSTACK_SHELL_DIR", data .. "/hyprstack-personal/shell")
-- Initialize the existing wallet and application autostart.
hl.on("hyprland.start", function()
    hl.exec_cmd(home .. "/.local/bin/caelestia-session-start")
end)
