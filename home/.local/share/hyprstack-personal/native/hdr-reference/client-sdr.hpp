// SPDX-License-Identifier: MIT
// Keep selected desktop clients in sRGB. Chromium 151 encodes even SDR pages
// to 8-bit PQ when given the HDR output's preferred image description. Its
// per-surface feedback overrides the high-precision output format selection.
#pragma once
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>

namespace {
CFunctionHook* preferredHook = nullptr;
std::vector<std::string> sdrClients;
struct SPreferredOutput {
    PHLMONITORREF monitor;
    uint32_t white = 0;
    PImageDescription preferred;
};
std::vector<SPreferredOutput> preferredOutputs;

bool clientNeedsSDR(wl_client* client) {
    return std::ranges::any_of(Desktop::windowState()->windows(), [&](const auto& window) {
        return window->resource() && window->resource()->client() == client &&
            std::ranges::find(sdrClients, window->m_class) != sdrClients.end();
    });
}

using PreferredFunction = PImageDescription (*)(CWLSurfaceResource*);
PImageDescription preferredDescription(CWLSurfaceResource* surface) {
    const auto source = reinterpret_cast<PreferredFunction>(preferredHook->m_original)(surface);
    if (!surface || !clientNeedsSDR(surface->client())) return source;
    const auto monitors = State::monitorState()->monitors();
    const auto found = std::ranges::find_if(monitors, [&](const auto& monitor) {
        return captureManaged(monitor) && source == monitor->m_imageDescription;
    });
    if (found == monitors.end()) return source;
    const auto monitor = *found;
    std::erase_if(preferredOutputs, [](const auto& output) { return output.monitor.expired(); });
    auto output = std::ranges::find_if(preferredOutputs, [&](const auto& output) { return output.monitor == monitor; });
    if (output == preferredOutputs.end()) {
        preferredOutputs.push_back({monitor, 0, nullptr});
        output = std::prev(preferredOutputs.end());
    }
    const auto white = sdrWhite(monitor);
    if (output->white != white) {
        auto description = DEFAULT_SRGB_IMAGE_DESCRIPTION->value();
        description.luminances = {.min = 0, .max = white, .reference = white};
        description.masteringLuminances = {.min = 0, .max = white};
        description.masteringPrimaries = description.primaries;
        description.maxCLL = description.maxFALL = white;
        output->white = white;
        output->preferred = CImageDescription::from(description);
    }
    // Only the preferred client encoding changes. Monitor gamut, HDR peak and
    // 10-bit scanout remain HDR; relative SDR follows the compositor controls.
    return output->preferred;
}

int sdrClientLua(lua_State* L) {
    const std::string app = luaL_checkstring(L, 1);
    if (app.empty()) return luaL_error(L, "A Wayland application ID is required");
    const bool enabled = lua_isnoneornil(L, 2) || lua_toboolean(L, 2);
    if (enabled && std::ranges::find(sdrClients, app) == sdrClients.end())
        sdrClients.push_back(app);
    else if (!enabled)
        std::erase(sdrClients, app);
    for (const auto& monitor : State::monitorState()->monitors())
        if (captureManaged(monitor)) notify(monitor);
    return 0;
}

void installPreferredHook(HANDLE handle) {
    const auto matches = HyprlandAPI::findFunctionsByName(handle, "getPreferredImageDescription");
    const auto found = std::ranges::find_if(matches, [](const auto& match) {
        return match.demangled.starts_with("CWLSurfaceResource::getPreferredImageDescription(");
    });
    if (found == matches.end()) throw std::runtime_error("HDR client encoding: missing surface feedback function");
    preferredHook = HyprlandAPI::createFunctionHook(handle, found->address, reinterpret_cast<void*>(&preferredDescription));
    if (!preferredHook || !preferredHook->hook()) {
        if (preferredHook) HyprlandAPI::removeFunctionHook(handle, preferredHook);
        preferredHook = nullptr;
        throw std::runtime_error("HDR client encoding: cannot hook surface feedback");
    }
    HyprlandAPI::addLuaFunction(handle, "hdr_reference", "sdr_client", sdrClientLua);
}
void removePreferredHook(HANDLE handle) {
    if (preferredHook) HyprlandAPI::removeFunctionHook(handle, preferredHook);
    preferredHook = nullptr;
    preferredOutputs.clear();
    sdrClients.clear();
    for (const auto& monitor : State::monitorState()->monitors())
        if (captureManaged(monitor)) notify(monitor);
}
}
