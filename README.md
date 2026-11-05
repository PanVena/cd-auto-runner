# CD Auto Runner

**English** · [Українська](README.uk.md)

Automatically starts **the player of your choice** as soon as an **audio CD** is inserted.
Made for KDE Plasma 6 and GNOME; works in any Linux desktop with udev and systemd.

Tested on Fedora 44 and 45 with GNOME 50 and KDE Plasma 6.7 and 6.8.

## Features

- A built-in player, or any installed one, including Flatpak and Snap.
- Rips discs to your Music folder (FLAC, Opus, Ogg, MP3, WAV) with tags and cover art.
- Track titles from MusicBrainz, CD-TEXT or entered by hand.
- Library, playlists and your own albums from digital copies.
- Disc actions in Disks & Devices (Plasma) and the app icon menu (GNOME).
- Media keys and desktop media controls (MPRIS).
- English and Ukrainian interface.

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/PanVena/cd-auto-runner/main/install.sh | bash
```

The installer asks for the language, the app window and the player. There are three window options:

| `--gui` | Window |
|---|---|
| `qt` | Qt (PySide6), with a tray icon |
| `gtk` | GTK 4 (libadwaita), native to GNOME |
| `none` | No window: just starts the chosen player, no built-in player |

To change your choice, run the installer again. For other options, see `./install.sh --help`; with `curl`, pass them after `bash -s --`.

## Usage

```text
cd-auto-runner settings        the app window
cd-auto-runner choose          choose a player
cd-auto-runner play [/dev/sr0] start the player manually
cd-auto-runner rip             rip the disc to the library
cd-auto-runner tag             enter track titles
cd-auto-runner eject           eject the disc
cd-auto-runner status          settings and service state
cd-auto-runner --help          all commands
```

Settings: `~/.config/cd-auto-runner/config`.

## Players

VLC and mpv play the disc directly. The built-in player, Audacious, Elisa and QMPlay2 get ripped tracks. GNOME Audio Player (Decibels) opens only one file, so it gets the whole disc as one track, with no skipping between songs. Any other player gets `cdda://`.

To add a player, copy an adapter from `players/` to `~/.config/cd-auto-runner/players/` and edit it.

## Known issues

- Flatpak players need extra permissions; `choose` offers to grant them.
- To read the drive, you need access to `/dev/sr0` (usually the `cdrom` group or the active session).

## Uninstall

```bash
~/.local/share/cd-auto-runner/uninstall.sh   # --purge also removes the settings
```

Ripped albums are kept.

## License

[GPL-2.0-only](LICENSE)
