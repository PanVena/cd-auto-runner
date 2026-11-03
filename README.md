# CD Auto Runner

**English** · [Українська](README.uk.md)

Automatically starts **the player of your choice** as soon as an **audio CD** is inserted.
Made for KDE Plasma 6, but works in any Linux desktop with udev and systemd.

## How it works

- A small `systemd --user` service watches `udev` events for CD/DVD drives.
- When a disc with audio tracks appears, it starts the player you chose.
- **The list of players comes from your system**, not from the code: the script reads the `.desktop` files of installed apps, including Flatpak and Snap.
  1. First come the apps that have an adapter (see below) or declare Audio CD support (`MimeType=x-content/audio-cdda`).
  2. Then other audio players, marked "no declared CD support".
  3. The default player is marked ★ and preselected. It is the app set for Audio CD (`x-content/audio-cdda`), or else your **Music player** from *System Settings → Default Applications* (`mimeapps.list`), but only if it can actually play Audio CDs.
- **Every player opens a disc in its own way**, so each one has its own adapter script in `players/`.
- Plasma's **Disks & Devices** menu (Device Notifier) gets these actions:
  - "Play in <chosen player>";
  - "Play in …" for every other player that can play CDs;
  - "Rip to music library";
  - "Enter track titles…";
  - "Open CD Auto Runner…" (the app window).
- **App window (PySide6).** The "CD Auto Runner" entry in the app menu opens the main window:
  - at the top — the inserted disc: cover art, album, artist, year, length and a badge showing where the titles came from;
  - "Play", "Rip to library", "Enter titles", "Stop" buttons;
  - a track table with each track's state ("in library", "ripped", "ripping…"), updated live;
  - on the right — every setting: player, autoplay, notifications, format, library and its folder, MusicBrainz, language;
  - at the bottom — the service state and a rip progress bar.

  The window notices by itself when a disc is inserted or ejected. Without PySide6 a `kdialog` menu opens instead, and without that — terminal controls.
- The interface is available in English and Ukrainian: the installer asks for the language first, and you can change it later with `cd-auto-runner lang`.

## Installation

```bash
git clone https://github.com/<your-login>/cd-auto-runner.git
cd cd-auto-runner
./install.sh
```

The installer:

1. Asks for the interface language: English or Ukrainian. The system language is suggested by default.
2. Checks the system: udev, systemd, whether a drive exists and whether you can read it.
3. Offers to install optional dependencies: `kdialog` (windows), `notify-send` (notifications), `cd-paranoia` and `ffmpeg` (track ripping and the music library), PySide6 (the app window and the track titles form). You don't need to install anything yourself — just answer "yes". Supports dnf, apt, pacman and zypper. `sudo` is needed only for this step.
4. Installs everything for the current user, without root:

   | File | Purpose |
   |---|---|
   | `~/.local/bin/cd-auto-runner` | the main script |
   | `~/.local/share/cd-auto-runner/players/` | player adapters |
   | `~/.local/share/cd-auto-runner/i18n.sh` | interface translation |
   | `~/.config/systemd/user/cd-auto-runner.service` | the service |
   | `~/.local/share/solid/actions/cd-auto-runner.desktop` | Disks & Devices menu actions (generated) |
   | `~/.local/share/applications/cd-auto-runner.desktop` | "CD Auto Runner" entry in the app menu |

5. Asks which player to use.
6. Enables and starts the service. If a systemd session isn't available, it uses XDG autostart.

Installer options:

| Option | Action |
|---|---|
| `-y`, `--yes` | answer "yes" to every question |
| `--lang uk\|en` | interface language, without asking |
| `--no-deps` | don't offer to install packages |
| `--choose` / `--no-choose` | always / never ask for a player |
| `--systemd` / `--autostart` | how to start the service |
| `-u`, `--uninstall [--purge]` | uninstall (with `--purge` — also the settings) |

## Usage

```text
cd-auto-runner settings        the app window (same as "CD Auto Runner" in the app menu)
cd-auto-runner choose          choose a player (kdialog or terminal; --tty — terminal only)
cd-auto-runner play [/dev/sr0] start the player manually (-n — only print the command)
cd-auto-runner play -p org.kde.elisa.desktop   open the disc in another player once
cd-auto-runner status          settings, service and drive state
cd-auto-runner list            players found on the system and their adapters
cd-auto-runner solid           refresh the Disks & Devices menu actions
cd-auto-runner rip             rip the disc to the music library without playing
cd-auto-runner tag             enter track titles (for discs that aren't in MusicBrainz)
cd-auto-runner stop            stop ripping tracks
cd-auto-runner clean           remove ripped tracks (~/.cache/cd-auto-runner)
cd-auto-runner lang [uk|en]    interface language
cd-auto-runner enable|disable  enable/disable the service
journalctl --user -u cd-auto-runner -f   log
```

Settings are stored in `~/.config/cd-auto-runner/config`. The service rereads them on every disc insertion, so you don't need to restart it after `choose`.

### Custom command

The "Custom command…" option lets you set any command. `{dev}` is replaced with the drive path:

```text
vlc cdda://{dev}
mpv --cdda-device={dev} cdda://
kioclient exec audiocd:/?device={dev}
```

## Player adapters

There is no universal way to open an audio CD, so every player has its own script in `players/`:

| Adapter | Player | Method |
|---|---|---|
| `vlc.sh` | VLC | directly: every track separately (`cdda:///dev/sr0 :cdda-track=N`), with titles; `--no-random` |
| `mpv.sh` | mpv | directly: `--cdda-device=/dev/sr0 cdda://`, chapters with track titles, cover art (or a spectrogram) |
| `audacious.sh` | Audacious | **rips tracks** and opens the whole album (directly, Audacious shows wrong titles from its own CDDB database) |
| `elisa.sh` | Elisa | **rips tracks** and opens the whole album |
| `qmplay2.sh` | QMPlay2 | **rips tracks**: the first via `--open`, the rest right away via `--enqueue` |
| `_generic.sh` | any other | `cdda:///dev/sr0` |

**Ripping tracks.** Elisa and the Flatpak version of QMPlay2 can't open a disc from the command line, and Audacious shows wrong titles from its own CDDB database when reading the disc directly. So the adapter:

1. Immediately creates full-size files for **all** tracks in `~/.cache/cd-auto-runner/`. Each track's length is known from the disc's table of contents, and the WAV header holds the title, artist, album and track number.
2. About 5 seconds later, once the start of the first track is ripped, opens **the whole album as one playlist** in the player.
3. Rips the tracks one by one with `cd-paranoia`, about 5 times faster than they play. So every track is ready before playback reaches it.
4. **Switching tracks.** If you switch to a track that isn't ripped yet, the script notices it via MPRIS (D-Bus), pauses the player, rips that track first, then plays it from the start. The tracks after it are ripped next.
5. **Player closed.** Without the music library, ripping stops. You can stop it manually with `cd-auto-runner stop`.
6. **Reinserting the disc doesn't break anything:**
   - Finished tracks are marked (`.done-N` in the cache or a finished file in the library) and aren't ripped again. An interrupted track is ripped from scratch.
   - If the disc is ejected while ripping, you get a "Disc ejected — insert it again to continue" notification.
   - A new run waits for the previous one to finish.
   - If the player is still playing this album, the album isn't added to the playlist a second time.

Why not the FLAC/Ogg/MP3 folders from `audiocd:/`? There are no encoded files on the disc, only PCM audio. Those folders are virtual: the KIO `audiocd` worker reads the audio and encodes it on the fly, just like this script. Besides, it is unreliable from a background script: it often answers "no permission to read" even when the drive is free. So the script rips with `cd-paranoia` and encodes with `ffmpeg`.

### Music library (like Windows Media Player)

By default (`LIBRARY=yes`) ripped tracks are saved to your system Music folder:

```text
~/Music/The Legacy/Solitude/
├── 01 - Ghost Town.flac
├── 02 - Black Ice.flac
├── …
└── cover.jpg
```

- **Tags:** title, artist, album, year, track number and MusicBrainz ID. Elisa and other players show the album in their collection right away.
- **Where titles come from:**
  1. titles you entered yourself (`cd-auto-runner tag`);
  2. the library: every album folder holds a hidden `.cd-auto-runner` file with the disc ID and titles, so a disc you already ripped is recognised even after reinstalling or removing the settings;
  3. KDE's cache `~/.cddb/musicbrainz/` (works offline);
  4. MusicBrainz, by the disc ID;
  5. if nothing is found — "Unknown Artist / Audio CD …", "Track NN".
- **The disc isn't in any database** (for example, a magazine cover CD). A notification with an "Enter titles…" button appears. You don't have to press it — the music plays anyway. You can also enter titles later with `cd-auto-runner tag` or the "Enter track titles…" action in the Disks & Devices menu.
  - A form opens with "Album", "Album artist", "Year" fields and an "Artist · Title" track table. "Paste tracklist…" spreads a tracklist pasted as one block (e.g. copied from the magazine's website: `1. Artist - Title`) over the table rows. Without PySide6, a text window with `01=Artist - Title` lines opens instead.
  - Titles are saved to `~/.config/cd-auto-runner/discs/<discid>.conf`, so next time the disc is recognised automatically.
  - Tracks that are already ripped are moved to the new folder and retagged. A various-artists compilation goes to `Various Artists/<Album>/NN - Artist - Title.flac` with the `compilation=1` tag.
  - The editor includes a link to add the disc to MusicBrainz if you like, so everyone can recognise it.
- **Cover art** comes from the Cover Art Archive and is saved as `cover.jpg` in the album folder and next to the temporary files, so Elisa shows it while ripping. FLAC and MP3 files also get it embedded in their tags, so any player shows it.
- **Reinserting** the same disc opens the tracks from the library right away, without ripping.
- **If you close the player**, the album is still ripped to the end. Stop it with `cd-auto-runner stop`.
- `cd-auto-runner rip` or the "Rip to music library" menu action rips the disc without playing it.

Settings in `~/.config/cd-auto-runner/config`:

| Setting | Value |
|---|---|
| `LIBRARY` | `yes` — the library; `no` — only a temporary cache, ripping stops together with the player |
| `LIBRARY_DIR` | a different library folder (empty — the system Music folder) |
| `ONLINE` | `no` — don't contact MusicBrainz and the Cover Art Archive |
| `UI_LANG` | interface language: `uk` or `en` (same as `cd-auto-runner lang`) |

**The rip format** is chosen together with the player, or set with `RIP_FORMAT` in the settings:

| Format | Description | ~2.5 min of audio |
|---|---|---|
| `flac` (default) | lossless | 18 MB |
| `opus` | 160 kbps | 3 MB |
| `ogg` | Vorbis q6 | ≈4 MB |
| `mp3` | VBR ≈190 kbps | 3.6 MB |
| `wav` | no encoding, no tags | 26 MB |

`ffmpeg` does the encoding. Title, artist, album and year are written to the tags, so your player shows the real names.

The temporary cache (`~/.cache/cd-auto-runner/`) is kept only for the current disc. Clear it with `cd-auto-runner clean`. That command doesn't touch the music library.

### Your own adapter

Copy any adapter to `~/.config/cd-auto-runner/players/`. Adapters there take priority over the installed ones. A minimal example:

```bash
#!/usr/bin/env bash
# cdar-desktop-ids: org.example.Player.desktop
# cdar-note: відтворює диск напряму
source "$CDAR_LIB"

cdar_launch --urls -- "cdda://$CDAR_DEVICE"
```

`cdar-note` is an internal marker: `відтворює диск напряму` (plays the disc directly) or `копіює треки` (rips tracks).

An adapter gets the variables `CDAR_DEVICE`, `CDAR_TRACKS`, `CDAR_EXEC` (the `Exec` line from the `.desktop` file), `CDAR_NAME` and `CDAR_FLATPAK`. Functions from `players/_lib.sh`:

| Function | What it does |
|---|---|
| `cdar_launch [--urls] [--wait] [--opt X] -- ARGUMENTS` | starts the app using its `Exec` line, so it works for Flatpak too |
| `cdar_track_urls PREFIX` | prints an address for every track |
| `cdar_rip_and_play OPEN` | track ripping mode; the `OPEN` function gets all album files |
| `cdar_notify TITLE TEXT` | a notification |

`CDAR_RESUME=restart` makes the adapter use Stop/Play instead of seeking after a track switch — for players with their own buffer (QMPlay2, Audacious).

Test an adapter with `cd-auto-runner play -n -p <desktop-id>`. Pull requests with adapters for other players are welcome.

### Translation

Strings in the code are written in Ukrainian, and the English translation lives in the `CDAR_EN` dictionary in `i18n.sh`. The function `_ 'text %s' value` returns the translation for the current language. After adding a new string, run the check: it lists strings without a translation.

```bash
python3 tests/check_i18n.py
```

## Known issues

- **Flatpak apps** need permissions, and `choose` offers to grant them:
  - players that read the disc directly (VLC, mpv) need access to the drive (`--device=all`);
  - players that get ripped tracks need read access to the `~/.cache/cd-auto-runner` folder only (`--filesystem=xdg-cache/cd-auto-runner:ro`). Without it, files go through the document portal, which caches their content. Then a track you switched to before it was ripped would play as silence.
- **Player and ripping at the same time.** A new `play` or `rip` stops the previous background rip; otherwise two processes would read the disc at once and the sound would stutter. The album is finished next time.
- **QMPlay2 (Flatpak)** doesn't play audio CDs with its AudioCD module, so it uses track ripping.
- **Elisa** ignores `cdda://` and `audiocd:/` addresses on the command line, so it uses track ripping too.
- While ripping, the drive is busy, so other apps may temporarily be unable to read it.
- To read the drive, you must be in the group that owns `/dev/sr0` (usually `cdrom`). On most distributions systemd-logind already grants drive access to the active session.

## Uninstall

```bash
./uninstall.sh          # or ./install.sh --uninstall
./uninstall.sh --purge  # also remove the settings
```

Ripped albums in your Music folder are kept. Track titles you entered (`~/.config/cd-auto-runner/discs/`) are kept too, even when you remove the settings; only `--purge` deletes them.

## License

[GPL-2.0-only](LICENSE)
