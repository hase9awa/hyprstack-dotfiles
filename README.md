[English](README.en.md)

# Hyprstack dotfiles

Мои настройки [Hyprstack](https://github.com/hase9awa/hyprstack-shell) для
CachyOS, Hyprland 0.56.2 и NVIDIA RTX 3060 Ti.

| Монитор | Режим | Автозапуск |
| --- | --- | --- |
| DP-1 · P275MR+ | 2560×1440, 200 Гц, HDR | AyuGram на воркспейсе 2 |
| HDMI-A-1 · BenQ GW2406Z | 1920×1080, 75 Гц, вертикальный | Discord на воркспейсе 1 |

[home/](home/) повторяет домашний каталог: Hyprland, оформление GTK/Qt,
терминалы, Neovim, шрифты, обои, личные расширения оболочки и Studio Mic.
[system/](system/) содержит службу и EDID для 75 Гц на моём BenQ.
Первый воркспейс второго монитора имеет внутренний номер **21**.

## Восстановление

Сначала установите [основную оболочку](https://github.com/hase9awa/hyprstack-shell)
и приложения. Версии зависимостей — в [packages/versions.txt](packages/versions.txt).
HDR-модуль собирается под установленный Hyprland; нужны Make, C++23 и заголовки
его зависимостей.

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

Чтобы восстановить значки Papirus с резервной копией существующих тем:

```bash
mkdir -p "$HOME/.local/share/icons" "$dotfiles_backup/icons"
for theme in Papirus Papirus-Dark Papirus-Light; do
    if [ -e "$HOME/.local/share/icons/$theme" ] || [ -L "$HOME/.local/share/icons/$theme" ]; then
        mv -- "$HOME/.local/share/icons/$theme" "$dotfiles_backup/icons/"
    fi
done
tar -xJf assets/papirus-icons.tar.xz -C "$HOME/.local/share/icons" --no-same-owner --no-same-permissions
```

Для 75 Гц на BenQ требуется системная служба: она загружает персональный EDID
до запуска экрана входа. Этот EDID предназначен для указанного монитора.

```bash
sudo rsync -rlt --backup --backup-dir="$dotfiles_backup/system" system/ /
sudo systemctl daemon-reload
sudo systemctl enable --now hyprstack-benq-75hz.service
```

После копирования войдите в Hyprland заново. На другом компьютере измените
[monitors.lua](home/.config/hyprstack/monitors.lua) и пути `/home/hasegawa`.
Программы и аудиоплагины Studio Mic устанавливаются отдельно.

## Лицензии

[GPL-3.0](LICENSE). Отдельно сохранены лицензии
[Papirus](assets/licenses/Papirus-GPL-3.0.txt),
[Hasklug](home/.local/share/fonts/hasklug-restore/LICENSE.md) и
[Neovim](home/.config/nvim/LICENSE). Значки —
[Papirus Development Team](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme);
изображения сохраняют права своих авторов.
