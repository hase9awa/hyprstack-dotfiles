// SPDX-License-Identifier: MIT
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>
#include <hyprland/src/protocols/ColorManagement.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <hyprland/src/output/Monitor.hpp>
extern "C" {
#include <lua.h>
}
static void number(lua_State* L, const char* key, double v) { lua_pushnumber(L,v); lua_setfield(L,-2,key); }
static void string(lua_State* L, const char* key, const std::string& v) { lua_pushlstring(L,v.data(),v.size()); lua_setfield(L,-2,key); }
static void description(lua_State* L, const NColorManagement::SImageDescription& d) {
    number(L,"tf",d.transferFunction); number(L,"primaries",d.primariesNamed);
    number(L,"reference",d.luminances.reference); number(L,"max",d.luminances.max);
}
static int status(lua_State* L) {
    lua_newtable(L); int i=0;
    for (const auto& w:Desktop::windowState()->windows()) {
        if (!w->resource()) continue;
        lua_newtable(L); number(L,"pid",w->getPID()); string(L,"title",w->m_title);
        lua_newtable(L); int j=0;
        w->resource()->breadthfirst([&](SP<CWLSurfaceResource> s,const Vector2D&,void*) {
            lua_newtable(L); number(L,"id",s->id()); number(L,"main",s==w->resource());
            if (s->m_current.texture) number(L,"format",s->m_current.texture->m_drmFormat);
            if (s->m_colorManagement && s->m_colorManagement->hasImageDescription()) description(L,s->m_colorManagement->imageDescription());
            lua_rawseti(L,-2,++j);
        },nullptr);
        lua_setfield(L,-2,"surfaces"); lua_rawseti(L,-2,++i);
    }
    return 1;
}
APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }
APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE h) {
    if (std::string(__hyprland_api_get_hash())!=__hyprland_api_get_client_hash()) throw std::runtime_error("ABI mismatch");
    HyprlandAPI::addLuaFunction(h,"color_inspector","status",status);
    return {"color-inspector","Temporary read-only color inspector","Hyprstack","1"};
}
APICALL EXPORT void PLUGIN_EXIT() {}
