# CD Auto Runner

**English** · [Українська](README.uk.md)

Automatically starts **the player of your choice** as soon as an **audio CD** is inserted.
Made for KDE Plasma 6, but works in any Linux desktop with udev and systemd.

## Features

- Has its own **built-in player**: it rips the disc first and plays each track from the window as soon as it is ripped.
- Picks up players installed on your system (including Flatpak and Snap) and preselects your default music player.
- Rips the disc to your Music folder while it plays (FLAC, Opus, Ogg, MP3 or WAV), with tags and cover art.
- Gets track titles from MusicBrainz or from the disc itself (CD-TEXT); if neither has them, lets you enter them yourself. A disc MusicBrainz doesn't know by its ID is looked up by name and track lengths, for the cover and the year.
- Adds actions to Plasma's **Disks & Devices** menu: play, play in another player, rip, enter titles.
- App window with the disc, its tracks, playback controls and all settings (PySide6; falls back to `kdialog` or the terminal). It hides to the system tray when closed (an inserted disc can also play straight in the tray, without opening the window), the player has shuffle and repeat, and the built-in player shows up in Plasma's Media Player widget and responds to media keys (MPRIS, needs dbus-python).
- Works as a regular player too: the **Library** card lists albums you've ripped, and one opens in your chosen player, in place of the inserted disc or with no disc in the drive at all (a custom command can't take files, so with it albums play in the window). Inserting a disc that autoplays takes over from the album.
- **Playlists** are a separate tab next to the library: they look just like albums but only link to tracks, so they take no extra disk space. The cover is combined from up to four different albums in the playlist, or you can choose your own. The Favorites playlist is always there, and the heart button in the player adds the current track to it. Reorder tracks by dragging rows or with Move up / Move down; add tracks from the track or album context menu (right click). Playlists live in the library's `Playlists` folder as `.m3u8` files with relative paths, so other players can read them too.
- **Your own albums from digital copies**: put a folder of music into the library (FLAC, MP3, Opus, Ogg, M4A, WMA, APE, WavPack, WAV, AIFF) and the album appears in the window by itself. "Edit album" reads the file tags, finds the release on MusicBrainz with its year and cover art, or lets you fill everything in by hand and arrange the tracks. Tiles of albums ripped from a disc carry a small disc mark; digital albums do not. Changes are stored in the hidden `.cd-auto-runner` file and `cover.jpg` in the album folder: the audio files stay untouched.
- Browsing does not interrupt the music: a single click opens an album or playlist while the current track keeps playing; a double click or the Play button starts what is shown.
- English and Ukrainian interface.

## Installation

```bash
git clone https://github.com/PanVena/cd-auto-runner.git
cd cd-auto-runner
./install.sh
```

The installer asks for the language and the player, installs `mpv` (the engine of the built-in player), offers to install optional dependencies (`kdialog`, `notify-send`, `cd-paranoia`, `ffmpeg`, PySide6, dbus-python) and starts the service. Everything is installed for the current user; `sudo` is needed only for the dependencies. Run `./install.sh --help` for options.

## Usage

```text
cd-auto-runner settings        the app window (and the built-in player)
cd-auto-runner choose          choose a player
cd-auto-runner play [/dev/sr0] start the player manually
cd-auto-runner open FILE...    open files in the chosen player
cd-auto-runner rip             rip the disc to the music library without playing
cd-auto-runner tag             enter track titles
cd-auto-runner stop            stop ripping
cd-auto-runner status          settings, service and drive state
cd-auto-runner lang [uk|en]    interface language
cd-auto-runner enable|disable  enable/disable the service
```

Settings are stored in `~/.config/cd-auto-runner/config`. A custom player command can use `{dev}` for the drive path, e.g. `vlc cdda://{dev}`.

## Supported players

The built-in player (CD Auto Runner itself) rips the tracks and plays them in its window through mpv, which runs as a separate process; double-click a track to play it, and if it isn't ripped yet, it is ripped first. VLC and mpv play the disc directly. Audacious, Elisa and QMPlay2 get ripped tracks: playback starts in a few seconds, and if you skip to a track that isn't ripped yet, it is ripped first. Any other player gets `cdda://`.

To add a player, copy an adapter from `players/` to `~/.config/cd-auto-runner/players/` and edit it. Test it with `cd-auto-runner play -n -p <desktop-id>`. Pull requests are welcome.

## Known issues

- Flatpak players need extra permissions; `choose` offers to grant them.
- To read the drive, you must have access to `/dev/sr0` (usually the `cdrom` group or the active session).
- While ripping, the drive is busy for other apps.

## Uninstall

```bash
./uninstall.sh          # --purge also removes the settings
```

Ripped albums in your Music folder are kept.

## License

[GPL-2.0-only](LICENSE)
