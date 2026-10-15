// SPDX-License-Identifier: MIT
// Convert the composed HDR framebuffer to SDR using the same white level for
// every client. Hyprland 0.56.2's MRT copy instead normalizes PQ clients to
// 80 nits and SDR clients to their original white, clipping browser content.
#pragma once
#include <hyprland/src/plugins/HookSystem.hpp>
#include <hyprland/src/output/MonitorResources.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/managers/screenshare/ScreenshareManager.hpp>
#include <utility>

namespace {
CFunctionHook* copyHook = nullptr;
CFunctionHook* mirrorHook = nullptr;
CFunctionHook* settingsHook = nullptr;
CFunctionHook* windowHook = nullptr;
bool convertingCapture = false;

struct SWindowCaptureOutput {
    PHLMONITORREF monitor;
    PImageDescription description;
};
std::vector<SWindowCaptureOutput> windowCaptureOutputs;

bool captureManaged(const PHLMONITOR& monitor) {
    return monitor && monitor->m_enabled && managed(monitor) &&
        monitor->m_imageDescription && !monitor->m_imageDescription->value().icc.present &&
        monitor->m_imageDescription->value().transferFunction == CM_TRANSFER_FUNCTION_ST2084_PQ;
}

using WindowFunction = void (*)(Screenshare::CScreenshareFrame*);
void captureWindow(Screenshare::CScreenshareFrame* frame) {
    const auto monitor = g_pHyprRenderer->m_renderData.pMonitor.lock();
    const auto framebuffer = g_pHyprRenderer->m_renderData.currentFB;
    if (captureManaged(monitor) && framebuffer) {
        std::erase_if(windowCaptureOutputs, [](const auto& output) { return output.monitor.expired(); });
        auto output = std::ranges::find_if(windowCaptureOutputs, [&](const auto& output) { return output.monitor == monitor; });
        if (output == windowCaptureOutputs.end()) {
            windowCaptureOutputs.push_back({monitor, nullptr});
            output = std::prev(windowCaptureOutputs.end());
        }
        const auto white = sdrWhite(monitor);
        if (!output->description || output->description->value().luminances.reference != white ||
            output->description->value().luminances.min != monitor->m_sdrMinLuminance)
            output->description = DEFAULT_SRGB_IMAGE_DESCRIPTION->with({
                .min = monitor->m_sdrMinLuminance, .max = white, .reference = white});
        // Export protocols carry SDR pixels without an HDR image description.
        // Keep this target marked through endRender(), when the queued surface
        // passes actually run, including both SHM and DMA-BUF captures.
        framebuffer->setImageDescription(output->description);
    }
    reinterpret_cast<WindowFunction>(windowHook->m_original)(frame);
}

using CopyFunction = bool (*)(Monitor::CMonitor*);
bool captureNeedsCopy(Monitor::CMonitor* monitor) {
    if (monitor && captureManaged(monitor->m_self.lock()))
        return false;
    return reinterpret_cast<CopyFunction>(copyHook->m_original)(monitor);
}

using MirrorFunction = bool (*)(Render::GL::CHyprOpenGLImpl*, const CBox&);
bool captureMirror(Render::GL::CHyprOpenGLImpl* backend, const CBox& box) {
    const auto monitor = g_pHyprRenderer->m_renderData.pMonitor.lock();
    if (!captureManaged(monitor))
        return reinterpret_cast<MirrorFunction>(mirrorHook->m_original)(backend, box);
    const auto framebuffer = monitor->resources()->mirrorFB();
    framebuffer->setImageDescription(DEFAULT_SRGB_IMAGE_DESCRIPTION->with({
        .min = monitor->m_sdrMinLuminance,
        .max = sdrWhite(monitor),
        .reference = sdrWhite(monitor)}));
    struct Restore {
        bool value;
        ~Restore() { convertingCapture = value; }
    } restore{std::exchange(convertingCapture, true)};
    return reinterpret_cast<MirrorFunction>(mirrorHook->m_original)(backend, box);
}

using SettingsFunction = Render::SCMSettings (*)(Render::IHyprRenderer*, PImageDescription,
    PImageDescription, SP<CWLSurfaceResource>, bool, float, int, bool);
Render::SCMSettings captureSettings(Render::IHyprRenderer* renderer, PImageDescription source,
    PImageDescription target, SP<CWLSurfaceResource> surface, bool modifySDR,
    float minimum, int maximum, bool shouldUseSurface) {
    auto settings = reinterpret_cast<SettingsFunction>(settingsHook->m_original)(
        renderer, source, target, surface, modifySDR, minimum, maximum, shouldUseSurface);
    const auto monitor = renderer->m_renderData.pMonitor.lock();
    const bool windowCapture = captureManaged(monitor) && std::ranges::any_of(windowCaptureOutputs,
        [&](const auto& output) { return output.monitor == monitor && output.description == target; });
    if (convertingCapture || windowCapture) {
        settings.dstTFRange.min = monitor->m_sdrMinLuminance;
        settings.dstTFRange.max = sdrWhite(monitor);
        // Desktop recordings retain SDR white and midtones. Values brighter
        // than SDR white clip in the SDR framebuffer; the monitor keeps HDR.
        settings.needsTonemap = false;
        settings.needsSDRmod = false;
        if (windowCapture && source && (source->value().transferFunction == CM_TRANSFER_FUNCTION_SRGB ||
                source->value().transferFunction == CM_TRANSFER_FUNCTION_GAMMA22)) {
            // Relative SDR values use the desktop's white; absolute PQ values
            // use their declared luminance. Both yield the same SDR thumbnail.
            settings.srcTFRange = settings.dstTFRange;
        }
    }
    return settings;
}

void removeCaptureHooks(HANDLE handle) {
    for (auto hook : {windowHook, settingsHook, mirrorHook, copyHook})
        if (hook) HyprlandAPI::removeFunctionHook(handle, hook);
    windowHook = settingsHook = mirrorHook = copyHook = nullptr;
    convertingCapture = false;
    windowCaptureOutputs.clear();
    if (!g_pHyprRenderer) return;
    g_pHyprRenderer->clearCMSettingsCache();
    for (const auto& monitor : State::monitorState()->monitors()) {
        if (!managed(monitor)) continue;
        monitor->resources()->invalidateMirrorFB();
        if (monitor->resources()->hasMirrorFB())
            monitor->resources()->mirrorFB()->setImageDescription(DEFAULT_SRGB_IMAGE_DESCRIPTION);
        g_pHyprRenderer->damageMonitor(monitor);
    }
}

void installCaptureHooks(HANDLE handle) {
    const auto install = [&](const char* name, const char* prefix, void* replacement) {
        const auto matches = HyprlandAPI::findFunctionsByName(handle, name);
        const auto found = std::ranges::find_if(matches, [&](const auto& match) {
            return match.demangled.starts_with(prefix);
        });
        if (found == matches.end()) throw std::runtime_error(std::string("HDR capture: missing ") + name);
        auto hook = HyprlandAPI::createFunctionHook(handle, found->address, replacement);
        if (!hook || !hook->hook()) {
            if (hook) HyprlandAPI::removeFunctionHook(handle, hook);
            throw std::runtime_error(std::string("HDR capture: cannot hook ") + name);
        }
        return hook;
    };
    try {
        copyHook = install("needsUnmodifiedCopy", "Monitor::CMonitor::needsUnmodifiedCopy(", reinterpret_cast<void*>(&captureNeedsCopy));
        mirrorHook = install("saveBufferForMirror", "Render::GL::CHyprOpenGLImpl::saveBufferForMirror(", reinterpret_cast<void*>(&captureMirror));
        settingsHook = install("getCMSettings", "Render::IHyprRenderer::getCMSettings(", reinterpret_cast<void*>(&captureSettings));
        windowHook = install("renderWindow", "Screenshare::CScreenshareFrame::renderWindow(", reinterpret_cast<void*>(&captureWindow));
    } catch (...) {
        removeCaptureHooks(handle);
        throw;
    }
}
}
