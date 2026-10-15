local home = os.getenv("HOME")
local config = os.getenv("XDG_CONFIG_HOME") or home .. "/.config"
local data = os.getenv("XDG_DATA_HOME") or home .. "/.local/share"
dofile(data .. "/hyprstack/shell/assets/hyprland/layouts.lua")
for _, name in ipairs({ "monitors.lua", "local.lua" }) do
    local path = config .. "/hyprstack/" .. name
    local file = io.open(path)
    if file then file:close(); dofile(path) end
end
