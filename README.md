[English](README.en.md)

# Hyprstack dotfiles

Моя личная конфигурация рабочего окружения
[Hyprstack](https://github.com/hase9awa/hyprstack-shell): оформление, мониторы,
клавиши, приложения и настройки оборудования. Снимок от **15 октября 2026 года**.

Исходники и установка самой оболочки находятся в
[hyprstack-shell](https://github.com/hase9awa/hyprstack-shell). Этот репозиторий
содержит мой профиль, который накладывается поверх установленной оболочки.

## Состав

Папка [`home/`](home/) повторяет структуру домашнего каталога.

| Путь | Содержимое |
| --- | --- |
| [`home/.config/hypr/`](home/.config/hypr/) | Конфигурация Hyprland, клавиши, правила окон, палитра и настройка HDR |
| [`home/.config/hyprstack/`](home/.config/hyprstack/) | Панели, дашборд, темы, погода, раскладки, яркость и настройки отдельных мониторов |
| [`home/.local/share/hyprstack-personal/`](home/.local/share/hyprstack-personal/) | Личные расширения яркости, экранного индикатора и HDR, исходники нативного модуля |
| [`home/.config/systemd/user/`](home/.config/systemd/user/) | Службы сеанса, NVIDIA, диагностики запуска и Studio Mic |
| [`home/.local/bin/`](home/.local/bin/) | Затемнение в простое, запуск сеанса и маршрутизация звука |
| [`home/.local/state/hyprstack/`](home/.local/state/hyprstack/) | Выбранная цветовая схема и текущие обои |
| [`home/Pictures/wallpapers/`](home/Pictures/wallpapers/) | Мои текущие обои |
| [`home/.local/share/fonts/`](home/.local/share/fonts/) | Локальные Hasklug Nerd Font Mono и их лицензия |
| [`assets/papirus-icons.tar.xz`](assets/papirus-icons.tar.xz) | Локальные темы Papirus, Papirus-Dark и Papirus-Light, включая относительные ссылки |
| [`home/.config/kitty/`](home/.config/kitty/), [`nvim/`](home/.config/nvim/), [`fish/`](home/.config/fish/) | Терминал, редактор, оболочка командной строки и зафиксированные версии плагинов Neovim |
| [`home/.config/gtk-3.0/`](home/.config/gtk-3.0/), [`gtk-4.0/`](home/.config/gtk-4.0/), [`kdeglobals`](home/.config/kdeglobals) | Оформление GTK и Qt, значки и шрифты |
| [`home/.config/studio-mic/`](home/.config/studio-mic/), [`pipewire/`](home/.config/pipewire/), [`home/.local/share/studio-mic/`](home/.local/share/studio-mic/) | Маршруты PipeWire и проект обработки микрофона Carla |
| [`packages/versions.txt`](packages/versions.txt) | Версии связанных пакетов на момент снимка |
| [`SNAPSHOT.json`](SNAPSHOT.json) | Перечень файлов, контрольные суммы, зависимости и изменения при экспорте |

Также сохранены Alacritty, Fastfetch, Thunar, Fontconfig, EasyEffects,
ассоциации файлов, пользовательские ярлыки, параметры ввода, профили экранов
и флаги запуска Thorium. Старый фоновый рисунок и помощник NVIDIA находятся
в `home/.local/share/hyprstack/shell/assets/`.

## Моя система

| Компонент | Конфигурация |
| --- | --- |
| Дистрибутив | CachyOS |
| Hyprland | 0.56.2 |
| Процессор | AMD Ryzen 5 5600X |
| Видеокарта | NVIDIA GeForce RTX 3060 Ti, драйвер 615.78.08 |
| Основной экран | P275MR+, 2560×1440, 200 Гц, HDR, SDR white 350 нит |
| Второй экран | BenQ GW2406Z, 1920×1080, 60 Гц, вертикальный |

Правила экранов, HDR, яркости и звука соответствуют именно этому оборудованию.
При переносе на другой компьютер сначала измените
[`monitors.lua`](home/.config/hyprstack/monitors.lua),
[`display-tuning.lua`](home/.config/hypr/display-tuning.lua), настройки яркости
и маршруты Studio Mic.

## Восстановление

### 1. Установить оболочку и зависимости

Сначала установите Hyprstack по
[основной инструкции](https://github.com/hase9awa/hyprstack-shell/blob/main/INSTALL.md).
Нужен **Hyprland 0.56.2** и совместимый набор Qt/Quickshell. Версии остальных
компонентов моего окружения перечислены в `packages/versions.txt`.
Для команд ниже нужны Git, Python, rsync, tar, xz, Make, компилятор C++23
и заголовки Hyprland с зависимостями.

### 2. Скачать конфигурацию и собрать HDR-модуль

```bash
git clone https://github.com/hase9awa/hyprstack-dotfiles.git
cd hyprstack-dotfiles
make -C home/.local/share/hyprstack-personal/native/hdr-reference
```

Готовые `.so` не хранятся в репозитории: модуль собирается под локальный
Hyprland. В экспортированном `titlebars.json` временное имя тестовой сборки
заменено на стандартный `hyprstack-bars.so`, который устанавливает основная
оболочка. Другие сохранённые пользовательские настройки не менялись.

### 3. Скопировать файлы с резервной копией

Выполняйте из каталога клонированного репозитория:

```bash
dotfiles_backup="$HOME/hyprstack-dotfiles-backup.$(date +%Y%m%d-%H%M%S)"
umask 077
rsync -rlt --omit-dir-times \
    --backup --backup-dir="$dotfiles_backup" \
    home/ "$HOME/"
```

Заменяемые файлы сохраняются в `$dotfiles_backup`. Команда переносит только
содержимое `home/`, сохраняет символические ссылки и не меняет права уже
существующих каталогов. Собранный на предыдущем шаге HDR-модуль копируется
вместе с конфигурацией.

Личный каталог `hyprstack-personal/shell` содержит собственные файлы и
относительные ссылки на установленный `hyprstack/shell`. Поэтому основная
оболочка должна быть установлена до копирования.

### 4. Восстановить значки и шрифты

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

Шрифты уже перенесены на предыдущем шаге. Сгенерированный кэш значков
не включён в архив. В Hyprland выбран `sweet-cursors`, но локальных файлов
этой темы в исходном окружении нет; GTK использует `Bibata-Original-Classic`
из пакета `bibata-cursor-theme`.

### 5. Проверить личные пути и звуковой тракт

Часть сохранённых путей содержит `/home/hasegawa`. Для другого имени
пользователя измените пути в `shell.json`, `titlebars.json`, проекте Carla,
службах Studio Mic, ярлыках приложений и файле
`~/.local/state/hyprstack/wallpaper/path.txt`.

Studio Mic использует Carla, PipeWire, yabridge/Wine и плагины **TDR Nova,
TDR Molotok, TDR VOS SlickEQ, U78 Saturator, LSP Expander Stereo,
LSP Deesser Stereo и LSP Limiter Stereo**. Настройки и маршруты сохранены;
сами плагины и программы устанавливаются отдельно. Подготовьте их перед
запуском служб `studio-mic-carla` и `studio-mic-router`.

### 6. Перечитать службы и войти в Hyprland

```bash
systemctl --user daemon-reload
```

Затем выйдите из сеанса и войдите в Hyprland. Личный профиль загрузится
через `hyprstack-session.service.d/10-personal-shell.conf`; помощник NVIDIA
запускается вместе с сеансом. Ссылки включения служб Studio Mic сохранены
в `default.target.wants/`.

## Что исключено

В снимке нет SSH/GPG-ключей, кошельков, токенов, cookies и профилей браузеров,
истории уведомлений и запуска приложений, журналов, трассировок, PID,
временных состояний GPU, сборочных файлов и старых экспериментов.
Служебные материалы разработки и записи демонстраций сюда не входят.

## Лицензии

Собственные изменения и код Hyprstack распространяются под [GPL-3.0](LICENSE).
Papirus сохраняет [свою лицензию](assets/licenses/Papirus-GPL-3.0.txt) и
[авторство проекта](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme).
Лицензия шрифтов находится
[рядом с файлами Hasklug](home/.local/share/fonts/hasklug-restore/LICENSE.md).
Лицензия стартовой конфигурации Neovim сохранена в её каталоге.
Изображения сохраняют права исходных авторов; лицензия кода не меняет их условия.
