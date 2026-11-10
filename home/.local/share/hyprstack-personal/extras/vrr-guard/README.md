# Static-desktop VRR guard (personal workstation)

Restored for Hyprland 0.57 on 2026-10-31. The previously working guard had
been archived, and its service was absent. The compositor again presents about
199.9 frames/s on the static DP-1 desktop. HDR, 10-bit, 200 Hz and VRR remain
configured as before; normal damage tracking stays enabled.

`pixel.c` adapts DonFlymoor/FlickrFree commit
3356907523ade96db948ed99fd9774a73c3b6e77 (MIT; see LICENSE.flickrfree).
It damages a completely transparent 1×1 layer, with an empty input region and
no keyboard focus, paced by Wayland frame callbacks. It never changes output
modes or monitor brightness. Keeping the display presenting costs more GPU
power than a completely idle desktop.

`guard.py` follows compositor socket events and starts workers only on enabled
VRR outputs. Exclusive fullscreen games/players pause the worker on their own
output; static fullscreen browsers remain protected. The 0.57 monitor IPC uses
workspace addresses/names, while client IPC also exposes numeric IDs; the guard
matches both formats. It does not poll IPC on an idle desktop.

The systemd unit is enabled under hyprstack-session.service, with PartOf and
BindsTo relationships. It follows shell restarts, exits on compositor socket
EOF, and removes its workers when stopped. Source, binary and unit are outside
the public installation ledger and survive release updates. The no-animation
layer rule and cursor settings are retained in ~/.config/hypr/display-tuning.lua.
Backups are under ~/.local/state/hyprstack-vrr-guard/backups/.

Build and policy/lifecycle verification (10 tests):

```sh
cd ~/.local/share/hyprstack-personal/extras/vrr-guard
make
python3 test_guard.py
systemctl --user status hyprstack-vrr-guard.service
journalctl --user -u hyprstack-vrr-guard.service -n 10
```

To disable the guard: `systemctl --user disable --now hyprstack-vrr-guard.service`.
Its physical effect should be checked on the monitor: frame callbacks prove
that the worker is active, while the panel's refresh display and perceived
flicker need visual confirmation.
