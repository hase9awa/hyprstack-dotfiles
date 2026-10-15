-- Temporary idle dim state for this setup's hardware/software brightness service.
-- Display modes, transfer functions and luminance metadata stay with Hyprland.
local json = require("utils.json")
local path = os.getenv("XDG_RUNTIME_DIR") .. "/hyprstack-brightness-"
    .. os.getenv("HYPRLAND_INSTANCE_SIGNATURE") .. ".json"
local dimmed = false
local file = io.open(path, "r")
if file then
    local ok, state = pcall(json.decode, file:read("*a"))
    file:close()
    dimmed = ok and type(state) == "table" and state.dimmed == true
end

local function publish()
    local file = assert(io.open(path .. ".tmp", "w"))
    file:write(json.encode({ dimmed = dimmed }), "\n")
    file:close()
    assert(os.rename(path .. ".tmp", path))
end

hyprstack_brightness = {}
function hyprstack_brightness.dim()
    if dimmed then return end
    dimmed = true
    publish()
end
function hyprstack_brightness.restore()
    if not dimmed then return end
    dimmed = false
    publish()
end
hl.layer_rule({ match = { namespace = "^hyprstack-brightness$" }, no_anim = true })
publish()
