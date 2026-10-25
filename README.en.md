[Русский](README.md)

# Hyprstack dotfiles

My [Hyprstack](https://github.com/hase9awa/hyprstack-shell) configuration for
CachyOS, Hyprland 0.56.2 and an NVIDIA RTX 3060 Ti.

Snapshot updated on **2026-10-25** for **Hyprstack 1.2.1**.

| Display | Mode | Autostart |
| --- | --- | --- |
| DP-1 · P275MR+ | 2560×1440, 200 Hz, HDR | AyuGram on workspace 2 |
| HDMI-A-1 · BenQ GW2406Z | 1920×1080, 75 Hz, portrait | Discord on workspace 1 |

[home/](home/) mirrors the home directory: Hyprland, GTK/Qt appearance,
terminals, Neovim, fonts, wallpapers, personal shell extensions and Studio Mic.
[system/](system/) contains the EDID and boot service for my BenQ's 75 Hz mode.
The second display's first workspace has the internal ID **21**.

The main taskbar VPN icon and VPN quick action are enabled. Profiles,
subscriptions, passwords and network cores are excluded: import your profiles
after restoring through **Settings → Network → VPN settings**. EasyEffects and
Discord wait for the tray through `wait-for-tray` during autostart so their
icons are available after login.

## Restore

Install the [base shell](https://github.com/hase9awa/hyprstack-shell) **1.2.0** or newer
and applications first. Dependency versions are listed in [packages/versions.txt](packages/versions.txt).
The HDR plugin requires Make, C++23 and development headers matching the installed
Hyprland and its dependencies.

```bash
git clone https://github.com/hase9awa/hyprstack-dotfiles.git
cd hyprstack-dotfiles
make -C home/.local/share/hyprstack-personal/native/hdr-reference

dotfiles_backup="$HOME/hyprstack-dotfiles-backup.$(date +%Y%m%d-%H%M%S)"
umask 077
rsync -rlt --omit-dir-times --backup --backup-dir="$dotfiles_backup/home" home/ "$HOME/"
systemctl --user daemon-reload
fc-cache -f
```

Restore Papirus icons, backing up existing themes:

```bash
mkdir -p "$HOME/.local/share/icons" "$dotfiles_backup/icons"
for theme in Papirus Papirus-Dark Papirus-Light; do
    if [ -e "$HOME/.local/share/icons/$theme" ] || [ -L "$HOME/.local/share/icons/$theme" ]; then
        mv -- "$HOME/.local/share/icons/$theme" "$dotfiles_backup/icons/"
    fi
done
tar -xJf assets/papirus-icons.tar.xz -C "$HOME/.local/share/icons" --no-same-owner --no-same-permissions
```

The BenQ's 75 Hz mode needs a system service that loads its personal EDID before
the login manager starts. This EDID is specific to the display listed above.

```bash
sudo rsync -rlt --backup --backup-dir="$dotfiles_backup/system" system/ /
sudo systemctl daemon-reload
sudo systemctl enable --now hyprstack-benq-75hz.service
```

Log out and back into Hyprland. On another machine, adjust
[monitors.lua](home/.config/hyprstack/monitors.lua) and `/home/hasegawa` paths.
Studio Mic applications and audio plugins are installed separately.

The local Quickshell build and compiled HDR plugin are excluded. The tray
discovery patch and Quickshell build notes are available in the
[base repository](https://github.com/hase9awa/hyprstack-shell/blob/main/MAINTENANCE.md#диагностика).

## Licences

[GPL-3.0](LICENSE). Separate licences are included for
[Papirus](assets/licenses/Papirus-GPL-3.0.txt),
[Hasklug](home/.local/share/fonts/hasklug-restore/LICENSE.md) and
[Neovim](home/.config/nvim/LICENSE). Icons are by
[Papirus Development Team](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme).
Images retain their authors' rights.
