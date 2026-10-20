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

-- Preserve the current NVIDIA frame scheduler across release updates.
hl.config({ render = { new_render_scheduling = false } })

-- Personal messaging apps. With the current per-monitor banks, workspace 21
-- is HDMI-A-1's local workspace 1; workspace 2 belongs to the main DP-1.
-- Class rules also cover launchers whose child processes lose exec rules.
hl.window_rule({
    name = "personal-discord-workspace",
    match = { class = "(?i)^discord$" },
    workspace = "21 silent",
})
hl.window_rule({
    name = "personal-ayugram-workspace",
    match = { class = "^com\\.ayugram\\.desktop$" },
    workspace = "2 silent",
})

-- Start once per graphical login; a config reload does not restart the apps.
hl.on("hyprland.start", function()
    if os.getenv("HYPRSTACK_NESTED") == "1" then return end
    hl.exec_cmd("/usr/bin/discord", { workspace = "21 silent" })
    hl.exec_cmd(home .. "/.local/bin/AyuGram", { workspace = "2 silent" })
end)
