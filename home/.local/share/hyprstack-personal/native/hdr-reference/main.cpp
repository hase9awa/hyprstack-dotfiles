// SPDX-License-Identifier: MIT
// Hyprland 0.56.2: use global SDR white for HDR-aware clients and SDR captures.
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <hyprland/src/protocols/ColorManagement.hpp>
#include <hyprland/src/managers/ProtocolManager.hpp>
#include <hyprland/src/render/Renderer.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

extern "C" {
#include <lua.h>
#include <lauxlib.h>
}

using namespace NColorManagement;

namespace {
struct SAdjustedOutput {
    PHLMONITORREF monitor;
    PImageDescription original;
    PImageDescription adjusted;
};

std::vector<std::string> selectors;
std::vector<SAdjustedOutput> adjustedOutputs;
CHyprSignalListener renderListener;

uint32_t sdrWhite(const PHLMONITOR& monitor) {
    // The compositor multiplies relative SDR content in linear light. PQ
    // clients encode absolute luminance and must receive this same white.
    const auto multiplier = monitor->m_sdrBrightness > 0 ? monitor->m_sdrBrightness : 1.0f;
    return static_cast<uint32_t>(std::clamp(std::lround(monitor->m_sdrMaxLuminance * multiplier), 1L,
        std::max(1L, static_cast<long>(monitor->m_imageDescription->value().luminances.max))));
}

bool managed(const PHLMONITOR& monitor) {
    return std::ranges::any_of(selectors, [&](const auto& selector) {
        if (!selector.starts_with("desc:"))
            return selector == monitor->m_name;
        const auto description = std::string_view(selector).substr(5);
        return monitor->m_shortDescription.starts_with(description) || monitor->m_description.starts_with(description);
    });
}

void notify(const PHLMONITOR& monitor) {
    if (PROTO::colorManagement)
        PROTO::colorManagement->onMonitorImageDescriptionChanged(monitor);
    monitor->m_blurFBDirty = true;
    if (g_pHyprRenderer)
        g_pHyprRenderer->damageMonitor(monitor);
}

bool sync(const PHLMONITOR& monitor) {
    if (!monitor || !monitor->m_enabled || !managed(monitor))
        return false;
    const auto description = monitor->m_imageDescription;
    if (!description || description->value().icc.present ||
        description->value().transferFunction != CM_TRANSFER_FUNCTION_ST2084_PQ)
        return false;

    auto luminances = description->value().luminances;
    const auto white = sdrWhite(monitor);
    if (luminances.reference == white)
        return true;

    std::erase_if(adjustedOutputs, [](const auto& output) { return output.monitor.expired(); });
    auto state = std::ranges::find_if(adjustedOutputs, [&](const auto& output) { return output.monitor == monitor; });
    if (state == adjustedOutputs.end()) {
        adjustedOutputs.push_back({monitor, description, {}});
        state = std::prev(adjustedOutputs.end());
    } else if (description != state->adjusted) {
        state->original = description;
    }
    luminances.reference = white;
    state->adjusted = description->with(luminances);
    monitor->m_imageDescription = state->adjusted;
    notify(monitor);
    return true;
}

int syncLua(lua_State* L) {
    const std::string selector = luaL_checkstring(L, 1);
    if (selector.empty())
        return luaL_error(L, "An output selector is required");
    if (std::ranges::find(selectors, selector) == selectors.end())
        selectors.push_back(selector);
    bool applied = false;
    for (const auto& monitor : State::monitorState()->monitors())
        applied = sync(monitor) || applied;
    lua_pushboolean(L, applied);
    return 1;
}

int modesLua(lua_State* L) {
    lua_newtable(L);
    for (const auto& monitor : State::monitorState()->monitors()) {
        if (!monitor || !monitor->m_enabled || !monitor->m_imageDescription)
            continue;
        // The configured preset in IPC can remain srgb during automatic HDR.
        const auto tf = monitor->m_imageDescription->value().transferFunction;
        lua_pushstring(L, tf == CM_TRANSFER_FUNCTION_ST2084_PQ || tf == CM_TRANSFER_FUNCTION_HLG ? "hdr" : "srgb");
        lua_setfield(L, -2, monitor->m_name.c_str());
    }
    return 1;
}
}

#include "capture.hpp"
#include "client-sdr.hpp"

namespace { HANDLE pluginHandle = nullptr; }

APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash())
        throw std::runtime_error("HDR reference: compositor/header ABI mismatch");
    pluginHandle = handle;
    installCaptureHooks(handle);
    try {
        installPreferredHook(handle);
    } catch (...) {
        removeCaptureHooks(handle);
        throw;
    }
    HyprlandAPI::addLuaFunction(handle, "hdr_reference", "sync", syncLua);
    HyprlandAPI::addLuaFunction(handle, "hdr_reference", "modes", modesLua);
    renderListener = Event::bus()->m_events.render.pre.listen([](const PHLMONITOR& monitor) { sync(monitor); });
    return {"hyprstack-hdr-reference", "Global SDR white, precise SDR clients and consistent HDR capture", "Personal setup", "1.2"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    renderListener.reset();
    removePreferredHook(pluginHandle);
    removeCaptureHooks(pluginHandle);
    for (const auto& output : adjustedOutputs) {
        const auto monitor = output.monitor.lock();
        if (monitor && monitor->m_imageDescription == output.adjusted && output.original) {
            monitor->m_imageDescription = output.original;
            notify(monitor);
        }
    }
    adjustedOutputs.clear();
    selectors.clear();
}
