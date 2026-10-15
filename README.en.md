[Русский](README.md)

# Hyprstack dotfiles

My personal [Hyprstack](https://github.com/hase9awa/hyprstack-shell) desktop
configuration: appearance, displays, shortcuts, applications and hardware
settings. Snapshot taken on **15 October 2026**.

Install the shell from [hyprstack-shell](https://github.com/hase9awa/hyprstack-shell)
first, then apply this personal profile.

## Contents

[`home/`](home/) mirrors the home directory. It includes Hyprland and Hyprstack
settings, per-monitor preferences, HDR and brightness extensions, NVIDIA and
session services, wallpapers, the active colour scheme, Hasklug Nerd Font Mono,
GTK/Qt appearance, Kitty, Neovim, Fish, Alacritty, Fastfetch, Thunar, file
associations, launchers and the Studio Mic audio setup.

The locally installed Papirus themes are preserved in
[`assets/papirus-icons.tar.xz`](assets/papirus-icons.tar.xz), including relative
links. [`SNAPSHOT.json`](SNAPSHOT.json) records the exported files and checksums;
[`packages/versions.txt`](packages/versions.txt) records related package versions.

## Hardware

This profile targets CachyOS with **Hyprland 0.56.2**, an AMD Ryzen 5 5600X,
NVIDIA GeForce RTX 3060 Ti (driver 615.78.08), a P275MR+ 2560×1440 200 Hz HDR
display with 350-nit SDR white, and a portrait BenQ GW2406Z 1920×1080 60 Hz display.
Adapt monitor rules, HDR/brightness settings and audio routes for other hardware.

## Restore

### 1. Install Hyprstack and dependencies

Follow the [shell installation guide](https://github.com/hase9awa/hyprstack-shell/blob/main/INSTALL.en.md).
Use Hyprland 0.56.2 with compatible Qt and Quickshell. The commands below also
need Git, Python, rsync, tar, xz, Make, a C++23 compiler and Hyprland development
headers with their dependencies.

### 2. Clone and build the personal HDR plugin

```bash
git clone https://github.com/hase9awa/hyprstack-dotfiles.git
cd hyprstack-dotfiles
make -C home/.local/share/hyprstack-personal/native/hdr-reference
```

Compiled `.so` files are excluded. Build the plugin against the installed
Hyprland. The exported `titlebars.json` selects the shell's standard rebuilt
`hyprstack-bars.so` instead of a temporary test binary; other saved preferences
are unchanged.

### 3. Copy files and back up replaced versions

Run from the cloned repository:

```bash
dotfiles_backup="$HOME/hyprstack-dotfiles-backup.$(date +%Y%m%d-%H%M%S)"
umask 077
rsync -rlt --omit-dir-times \
    --backup --backup-dir="$dotfiles_backup" \
    home/ "$HOME/"
```

Replaced files go to `$dotfiles_backup`. Existing directory permissions are
preserved. The plugin built in the previous step is copied with the configuration.
The personal shell contains local overrides and relative links to the installed
common shell, so the common shell must already exist.

### 4. Restore icons and refresh fonts

```bash
mkdir -p "$HOME/.local/share/icons" "$dotfiles_backup/.local/share/icons"
for theme_name in Papirus Papirus-Dark Papirus-Light; do
    if [ -e "$HOME/.local/share/icons/$theme_name" ] || [ -L "$HOME/.local/share/icons/$theme_name" ]; then
        mv -- "$HOME/.local/share/icons/$theme_name" "$dotfiles_backup/.local/share/icons/"
    fi
done
tar --extract --xz --file=assets/papirus-icons.tar.xz \
    --directory="$HOME/.local/share/icons" --no-same-owner --no-same-permissions
fc-cache -f
```

Fonts were copied with `home/`. Generated icon caches are excluded.
Hyprland selects `sweet-cursors`, whose files were absent from the source
environment. GTK selects `Bibata-Original-Classic` from `bibata-cursor-theme`.

### 5. Check paths and audio plugins

Some paths contain `/home/hasegawa`. For another username, edit `shell.json`,
`titlebars.json`, the Carla project, Studio Mic services, desktop launchers and
`~/.local/state/hyprstack/wallpaper/path.txt`.

Studio Mic needs Carla, PipeWire, yabridge/Wine, **TDR Nova, TDR Molotok,
TDR VOS SlickEQ, U78 Saturator, LSP Expander Stereo, LSP Deesser Stereo and
LSP Limiter Stereo**. Their settings and routes are included; the applications
and plugins must be installed separately before starting the audio services.

### 6. Reload user units and log in

```bash
systemctl --user daemon-reload
```

Log out and back into Hyprland. The personal shell is selected by the session
service drop-in. The NVIDIA helper starts with the session; Studio Mic enablement
links are preserved in `default.target.wants/`.

## Excluded data

No SSH/GPG keys, wallets, tokens, cookies, browser profiles, notification or
application-use history, logs, traces, PIDs, GPU client state, build products,
retired experiments, assistant materials or demonstration recordings are included.

## Licences

Personal changes and Hyprstack code use [GPL-3.0](LICENSE). Papirus retains its
[licence](assets/licenses/Papirus-GPL-3.0.txt) and
[upstream attribution](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme).
The [font licence](home/.local/share/fonts/hasklug-restore/LICENSE.md) and Neovim
starter licence are included alongside their files. Images retain their original
authors' rights; the code licence does not relicense them.
