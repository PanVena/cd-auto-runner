#!/usr/bin/env python3
"""CD Auto Runner — спільна частина вікон програми, без залежності від інструментарію.

Тут те, що однакове для вікна Qt (gui.py) і вікна GTK (gui_gtk.py): переклад, налаштування,
бібліотека, плейлісти, MPRIS і логіка програвача (Controller). Модуль не імпортує ні Qt, ні GTK.

Toolkit-free code shared by the Qt window (gui.py) and the GTK window (gui_gtk.py): translation,
settings, the library, playlists, MPRIS and the player logic (Controller).

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import glob
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor    # у Python 3.15 атрибут модуля лінивий і в потоці Qt не спрацьовує

try:    # MPRIS — необов'язково: без dbus-python програвача не видно в елементах керування музикою
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
except ImportError:
    dbus = None

APP = "cd-auto-runner"


GNOME = "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")


HOMEPAGE = "https://github.com/PanVena/cd-auto-runner"


LANG = os.environ.get("CDAR_UI_LANG", "uk")


EN = {
    "Вставте аудіо-CD": "Insert an audio CD",
    "Обраний програвач запуститься сам, щойно ви вставите диск.":
        "Your chosen player starts by itself as soon as you insert a disc.",
    "Читаю диск…": "Reading the disc…",
    "Не вдалося прочитати диск": "Failed to read the disc",
    "Відтворити": "Play",
    "Скопіювати в бібліотеку": "Rip to library",
    "Ввести назви": "Enter titles",
    "Зупинити": "Stop",
    "Ще": "More",
    "Відкрити теку альбому": "Open the album folder",
    "Відкрити бібліотеку музики": "Open the music library",
    "Додати диск у MusicBrainz": "Add the disc to MusicBrainz",
    "Видалити тимчасові файли": "Remove temporary files",
    "Оновити": "Refresh",
    "треків: {n}": "{n} tracks",
    "Назви з MusicBrainz": "Titles from MusicBrainz",
    "Назви з диска (CD-TEXT)": "Titles from the disc (CD-TEXT)",
    "MusicBrainz (за назвою)": "MusicBrainz (by name)",
    "З бібліотеки": "From the library",
    "Назви введено вручну": "Titles entered by hand",
    "Кеш KDE": "KDE cache",
    "Диска немає в базах": "Disc not in any database",
    "Виконавець": "Artist",
    "Назва": "Title",
    "Час": "Time",
    "Стан": "Status",
    "у бібліотеці": "in library",
    "скопійовано": "ripped",
    "копіюється…": "ripping…",
    "Відтворення": "Playback",
    "Програвач:": "Player:",
    "Нічого не запускати": "Do nothing",
    "Власна команда": "Custom command",
    "Автозапуск при вставлянні диска": "Autoplay when a disc is inserted",
    "Сповіщення": "Notifications",
    "Копіювання і бібліотека": "Ripping and library",
    "Формат:": "Format:",
    "FLAC — без втрат": "FLAC — lossless",
    "Opus 160 кбіт/с — малий розмір": "Opus 160 kbps — small size",
    "Ogg Vorbis q6": "Ogg Vorbis q6",
    "MP3 VBR ~190 кбіт/с": "MP3 VBR ~190 kbps",
    "WAV — без перекодування": "WAV — no encoding",
    "Зберігати альбоми в бібліотеку музики": "Save albums to the music library",
    "Тека:": "Folder:",
    "Змінити…": "Change…",
    "Типова": "Default",
    "системна тека «Музика»": "the system Music folder",
    "Брати назви й обкладинки з MusicBrainz": "Get titles and cover art from MusicBrainz",
    "Інтерфейс": "Interface",
    "Мова:": "Language:",
    "Формат і бібліотека стосуються вбудованого програвача, програвачів, яким треки копіюються (Elisa, QMPlay2, Audacious), і кнопки «Скопіювати в бібліотеку».":
        "Format and library apply to the built-in player, to players that get ripped tracks (Elisa, QMPlay2, Audacious) and to the \"Rip to library\" button.",
    "Служба працює": "Service running",
    "Служба зупинена": "Service stopped",
    "Служба не встановлена": "Service not installed",
    "Копіюю трек {t} · {done} з {total}": "Ripping track {t} · {done} of {total}",
    "Скопійовано {done} з {total}": "Ripped {done} of {total}",
    "Збережено": "Saved",
    "Потрібен дозвіл": "Permission needed",
    "{name} встановлено як Flatpak, і йому бракує дозволу:\n\nflatpak override --user {arg} {fid}\n\nНадати?":
        "{name} is installed as a Flatpak and lacks a permission:\n\nflatpak override --user {arg} {fid}\n\nGrant it?",
    "Помилка": "Error",
    "Не вдалося виконати дію.": "The action failed.",
    "Мову змінено. Вікно перезапуститься.": "Language changed. The window will restart.",
    "Тека бібліотеки музики": "Music library folder",
    "Привід порожній": "The drive is empty",
    "Попередній трек": "Previous track",
    "Відтворити / пауза": "Play / pause",
    "Зупинити відтворення": "Stop playback",
    "Наступний трек": "Next track",
    "Гучність": "Volume",
    "Нічого не відтворюється": "Nothing is playing",
    "Чекаю, поки скопіюється трек {n}…": "Waiting for track {n} to be ripped…",
    "Пауза": "Paused",
    "Для вбудованого програвача встановіть mpv (пакет mpv).": "Install mpv (the mpv package) to use the built-in player.",
    "Не вдалося запустити mpv.": "Failed to start mpv.",
    "Не вдалося відтворити трек {n}.": "Failed to play track {n}.",
    "Згортати в системний лоток під час закриття вікна": "Hide to the system tray when the window is closed",
    "Показати / сховати вікно": "Show / hide the window",
    "Вийти": "Quit",
    "CD Auto Runner працює далі в системному лотку. Щоб вийти, оберіть «Вийти» в меню його значка.":
        "CD Auto Runner keeps running in the system tray. To quit, choose \"Quit\" in its icon menu.",
    "Трек {n}": "Track {n}",
    "Перемішувати": "Shuffle",
    "Повтор: вимкнено": "Repeat: off",
    "Повтор: увесь диск": "Repeat: whole disc",
    "Повтор: один трек": "Repeat: one track",
    "Вставлений диск відтворювати у лотку, не відкриваючи вікна": "Play an inserted disc in the tray without opening the window",
    "Вийняти диск": "Eject the disc",
    "Не вдалося вийняти диск.": "Failed to eject the disc.",
    "Аудіо-CD": "Audio CD",
    "Про програму": "About",
    "Версія {v}": "Version {v}",
    "Запускає обраний програвач, щойно вставлено аудіо-CD, має власний вбудований програвач і копіює диски в бібліотеку музики з назвами треків і обкладинками.":
        "Starts the player of your choice as soon as an audio CD is inserted, has its own built-in player and rips discs to your music library with track titles and cover art.",
    "Ліцензія: GNU GPL версії 2.": "License: GNU GPL version 2.",
    "Відтворюю диск. Керувати ним можна зі значка в лотку або з системних елементів керування музикою.":
        "Playing the disc. Control it from the tray icon or your desktop's media controls.",
    "Музика грає далі. Керувати нею можна з системних елементів керування музикою, а вікно відкриється з меню програм.":
        "The music keeps playing. Control it from your desktop's media controls; the app menu brings the window back.",
    "У GNOME для значка в лотку потрібне розширення AppIndicator (пакет gnome-shell-extension-appindicator).":
        "In GNOME, the tray icon needs the AppIndicator extension (package gnome-shell-extension-appindicator).",
    "Бібліотека": "Library",
    "Диск у приводі": "Disc in the drive",
    "Тут з'являтимуться скопійовані диски.": "Ripped discs will appear here.",
    "Двічі клацніть альбом, щоб відтворити його.": "Double-click an album to play it.",
    "Не вдалося відкрити альбом.": "Failed to open the album.",
    "Запускаю {name}…": "Starting {name}…",
    "Записано з диска": "Ripped from a disc",
    "Цифровий альбом": "Digital album",
    "Плейлісти": "Playlists",
    "Улюблене": "Favorites",
    "Плейліст": "Playlist",
    "Плейлістів ще немає: створіть перший кнопкою «+» або додайте до нього треки через контекстне меню.":
        "No playlists yet: create one with the \"+\" button or add tracks to one from the context menu.",
    "Двічі клацніть плейліст, щоб відтворити його.": "Double-click a playlist to play it.",
    "Покладіть теку з музикою в бібліотеку — альбом з'явиться тут":
        "Put a folder with music into the library and the album will appear here",
    "Новий плейліст": "New playlist",
    "Новий плейліст…": "New playlist…",
    "Назва плейліста:": "Playlist name:",
    "Плейліст із такою назвою вже є.": "A playlist with this name already exists.",
    "Перейменувати плейліст": "Rename the playlist",
    "Перейменувати…": "Rename…",
    "Вибрати обкладинку…": "Choose a cover…",
    "Прибрати обкладинку": "Remove the cover",
    "Видалити плейліст…": "Delete the playlist…",
    "Видалити плейліст «{name}»? Самі треки залишаться в бібліотеці.":
        "Delete the playlist \"{name}\"? The tracks themselves stay in the library.",
    "Відкрити": "Open",
    "Додати до плейліста": "Add to playlist",
    "Додати до улюбленого": "Add to Favorites",
    "Прибрати з улюбленого": "Remove from Favorites",
    "Прибрати з плейліста": "Remove from the playlist",
    "Вище": "Move up",
    "Нижче": "Move down",
    "Додано треків: {n}": "Tracks added: {n}",
    "Ці треки вже є в плейлісті.": "These tracks are already in the playlist.",
    "Спершу дочекайтеся, поки трек скопіюється в бібліотеку.": "Wait until the track is ripped to the library first.",
    "файлу немає": "file missing",
    "Файлу треку {n} більше немає.": "The file of track {n} no longer exists.",
    "Редагувати альбом": "Edit album",
    "Редагувати альбом…": "Edit album…",
    "Редагування альбому": "Edit album",
    "Альбом:": "Album:",
    "Виконавець альбому:": "Album artist:",
    "Рік:": "Year:",
    "Файл": "File",
    "Знайти в MusicBrainz": "Search MusicBrainz",
    "Застосувати": "Apply",
    "Шукаю…": "Searching…",
    "Читаю реліз…": "Reading the release…",
    "Завантажую обкладинку…": "Downloading the cover…",
    "Обкладинку не знайдено.": "No cover was found.",
    "Вимкнено в налаштуваннях (MusicBrainz).": "Turned off in the settings (MusicBrainz).",
    "Не вдалося звернутися до MusicBrainz.": "Failed to reach MusicBrainz.",
    "Нічого не знайдено: уточніть назву й виконавця або заповніть усе самі.":
        "Nothing found: refine the album and artist, or fill everything in yourself.",
    "Оберіть реліз і натисніть «Застосувати». Спершу йдуть релізи з такою самою кількістю треків.":
        "Pick a release and press Apply. Releases with the same number of tracks come first.",
    "Застосовано. Перевірте, чи назви відповідають файлам.": "Applied. Check that the titles match the files.",
    "У релізі треків: {a}, а в теці: {b}. Перевірте, чи назви відповідають файлам.":
        "The release has {a} tracks and the folder has {b}. Check that the titles match the files.",
    "Рік": "Year",
    "Країна": "Country",
    "Носій": "Medium",
    "Треків": "Tracks",
    "Обкладинка": "Cover",
    "Зображення": "Images",
    "Не вдалося зберегти обкладинку.": "Failed to save the cover.",
    "Не вдалося записати зміни: {e}": "Failed to save the changes: {e}",
    "Зберегти": "Save",
    "Скасувати": "Cancel",
    "Налаштування": "Preferences",
    "Зупинити копіювання": "Stop ripping",
    "Меню альбому": "Album menu",
    "Головне меню": "Main menu",
    "Видалити": "Delete",
    "Перейменувати": "Rename",
    "Створити": "Create",
    "Надати": "Grant",
    "Пізніше": "Not now",
    "Гаразд": "OK",
    "Диск": "Disc",
}


def _(text, **values):
    if LANG == "en":
        text = EN.get(text, text)
    return text.format(**values) if values else text


def self_bin():
    for path in (os.environ.get("CDAR_SELF", ""), shutil.which(APP) or "",
                 os.path.expanduser(f"~/.local/bin/{APP}")):
        if path and os.access(path, os.X_OK):
            return path
    return APP


def script_version():
    code, out, _err = run("--version", timeout=10)
    return out.split()[-1] if code == 0 and out.split() else ""


def config_path():
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), APP, "config")


def read_config():
    cfg = {}
    try:
        with open(config_path(), encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.rstrip("\n").split("=", 1)
                    cfg[k] = v
    except OSError:
        pass
    return cfg


def run(*args, timeout=60):
    try:
        p = subprocess.run([self_bin(), *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def udev_audio_tracks(dev="/dev/sr0"):
    try:
        out = subprocess.run(["udevadm", "info", "--query=property", f"--name={dev}"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0
    m = re.search(r"^ID_CDROM_MEDIA_TRACK_COUNT_AUDIO=(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def fmt_time(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def runtime_dir():
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/{APP}-{os.getuid()}", APP)
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


# не лише те, що копіюється з дисків: у бібліотеці можуть лежати й цифрові альбоми
AUDIO_EXT = {".flac", ".opus", ".ogg", ".mp3", ".wav", ".m4a", ".aac", ".wma", ".ape", ".wv", ".aiff", ".aif"}


# режими повтору (як LoopStatus у MPRIS): значок і підказка; кнопка перемикає їх по колу
LOOP_MODES = {
    "None": ("media-playlist-repeat", "Повтор: вимкнено"),
    "Playlist": ("media-playlist-repeat", "Повтор: увесь диск"),
    "Track": ("media-playlist-repeat-song", "Повтор: один трек"),
}


# --- MPRIS: вбудований програвач в елементах керування музикою і на мультимедійних клавішах
MPRIS_PATH = "/org/mpris/MediaPlayer2"


MPRIS_ROOT = "org.mpris.MediaPlayer2"


MPRIS_PLAYER = "org.mpris.MediaPlayer2.Player"


DBUS_PROPS = "org.freedesktop.DBus.Properties"


NO_TRACK = "/org/mpris/MediaPlayer2/TrackList/NoTrack"


def connect_mpris(win):
    """Сервіс MPRIS. dbus-python працює в циклі GLib, тож викликати лише з нього."""
    if dbus is None:
        return None
    try:
        DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        name = dbus.service.BusName(f"{MPRIS_ROOT}.cd_auto_runner", bus)
        return Mpris(win, bus, name)
    except dbus.exceptions.DBusException:
        return None


if dbus is not None:
    def _strings(*items):
        return dbus.Array([i for i in items if i], signature="s")

    class Mpris(dbus.service.Object):
        """org.mpris.MediaPlayer2 і .Player для вбудованого програвача. Стан бере з вікна,
        команди передає йому; виклики приходять у головному потоці (цикл GLib = цикл Qt)."""

        def __init__(self, win, bus, name):
            super().__init__(bus, MPRIS_PATH)
            self.win = win
            self.bus_name = name        # ім'я на шині тримається, доки живе цей об'єкт
            self.last = {}

        # --- стан ---
        def track_id(self, n):
            return dbus.ObjectPath(f"/org/cd_auto_runner/track/{n}")

        def metadata(self):
            w = self.win
            n = w.cur
            if n is None:
                return dbus.Dictionary({"mpris:trackid": dbus.ObjectPath(NO_TRACK)}, signature="sv")
            t = w.track_title(n) or {}
            info = w.player_info()
            meta = {"mpris:trackid": self.track_id(n), "xesam:trackNumber": dbus.Int32(t.get("num", n)),
                    "xesam:title": dbus.String(t.get("title") or _("Трек {n}", n=n))}
            sec = w.length if w.want is None and w.length > 0 else t.get("sec", 0)
            if sec:
                meta["mpris:length"] = dbus.Int64(int(sec * 1_000_000))
            if t.get("artist") or info.get("ALBUM_ARTIST"):
                meta["xesam:artist"] = _strings(t.get("artist") or info.get("ALBUM_ARTIST"))
            if info.get("ALBUM_ARTIST"):
                meta["xesam:albumArtist"] = _strings(info["ALBUM_ARTIST"])
            album, cover = t.get("album") or info.get("ALBUM"), t.get("cover") or info.get("COVER")
            if album:
                meta["xesam:album"] = dbus.String(album)
            if cover and os.path.isfile(cover):
                meta["mpris:artUrl"] = dbus.String(pathlib.Path(cover).as_uri())
            return dbus.Dictionary(meta, signature="sv")

        def player_props(self):
            w = self.win
            n = w.cur
            tracks = len(w.player_info().get("tracks", []))
            if n is None:
                status = "Stopped"
            elif w.is_paused and w.want is None:
                status = "Paused"
            else:
                status = "Playing"      # грає або чекає, поки скопіюється трек
            ready = w.mpv is not None and tracks > 0
            playing = n is not None and w.want is None
            return {
                "PlaybackStatus": dbus.String(status),
                "Rate": dbus.Double(1.0), "MinimumRate": dbus.Double(1.0), "MaximumRate": dbus.Double(1.0),
                "Metadata": self.metadata(),
                "Volume": dbus.Double(w.volume() / 100),
                "Position": dbus.Int64(int(w.pos * 1_000_000) if playing else 0),
                "LoopStatus": dbus.String(w.loop), "Shuffle": dbus.Boolean(w.shuffle),
                "CanGoNext": dbus.Boolean(w.neighbor(1) is not None),
                "CanGoPrevious": dbus.Boolean(n is not None),
                "CanPlay": dbus.Boolean(ready), "CanPause": dbus.Boolean(ready),
                "CanSeek": dbus.Boolean(playing), "CanControl": dbus.Boolean(True),
            }

        def root_props(self):
            return {
                "CanQuit": dbus.Boolean(True), "CanRaise": dbus.Boolean(True),
                "HasTrackList": dbus.Boolean(False), "Identity": dbus.String("CD Auto Runner"),
                "DesktopEntry": dbus.String(APP),
                "SupportedUriSchemes": _strings(), "SupportedMimeTypes": _strings(),
            }

        def refresh(self):
            """Сповіщає клієнтів про змінені властивості (позицію вони рахують самі)."""
            props = self.player_props()
            del props["Position"]
            changed = {k: v for k, v in props.items() if self.last.get(k) != v}
            self.last = props
            if changed:
                self.PropertiesChanged(MPRIS_PLAYER, dbus.Dictionary(changed, signature="sv"), _strings())

        # --- org.freedesktop.DBus.Properties ---
        @dbus.service.method(DBUS_PROPS, in_signature="ss", out_signature="v")
        def Get(self, iface, prop):
            props = self.GetAll(iface)
            if prop not in props:
                raise dbus.exceptions.DBusException(f"No such property: {prop}",
                                                    name="org.freedesktop.DBus.Error.UnknownProperty")
            return props[prop]

        @dbus.service.method(DBUS_PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface):
            if iface == MPRIS_ROOT:
                return self.root_props()
            if iface == MPRIS_PLAYER:
                return self.player_props()
            raise dbus.exceptions.DBusException(f"No such interface: {iface}",
                                                name="org.freedesktop.DBus.Error.UnknownInterface")

        @dbus.service.method(DBUS_PROPS, in_signature="ssv")
        def Set(self, iface, prop, value):
            if iface == MPRIS_PLAYER and prop == "Volume":
                self.win.apply_volume(round(max(0.0, min(1.0, float(value))) * 100))
            elif iface == MPRIS_PLAYER and prop == "LoopStatus" and str(value) in LOOP_MODES:
                self.win.set_loop(str(value))
            elif iface == MPRIS_PLAYER and prop == "Shuffle":
                self.win.set_shuffle(bool(value))
            else:
                raise dbus.exceptions.DBusException(f"Read-only property: {prop}",
                                                    name="org.freedesktop.DBus.Error.PropertyReadOnly")

        @dbus.service.signal(DBUS_PROPS, signature="sa{sv}as")
        def PropertiesChanged(self, iface, changed, invalidated):
            pass

        # --- org.mpris.MediaPlayer2 ---
        @dbus.service.method(MPRIS_ROOT)
        def Raise(self):
            self.win.show_window()

        @dbus.service.method(MPRIS_ROOT)
        def Quit(self):
            self.win.quit_app()

        # --- org.mpris.MediaPlayer2.Player ---
        @dbus.service.method(MPRIS_PLAYER)
        def Next(self):
            self.win.next_track()

        @dbus.service.method(MPRIS_PLAYER)
        def Previous(self):
            self.win.prev_track()

        @dbus.service.method(MPRIS_PLAYER)
        def Pause(self):
            w = self.win
            if w.cur is not None and w.want is None and not w.is_paused:
                w.mpv.toggle()

        @dbus.service.method(MPRIS_PLAYER)
        def Play(self):
            w = self.win
            if w.cur is None:
                w.toggle_play()
            elif w.want is None and w.is_paused:
                w.mpv.toggle()

        @dbus.service.method(MPRIS_PLAYER)
        def PlayPause(self):
            self.win.toggle_play()

        @dbus.service.method(MPRIS_PLAYER)
        def Stop(self):
            self.win.stop_playback()

        @dbus.service.method(MPRIS_PLAYER, in_signature="x")
        def Seek(self, offset):
            w = self.win
            if w.cur is not None and w.want is None:
                w.seek_to(w.pos + offset / 1_000_000)

        @dbus.service.method(MPRIS_PLAYER, in_signature="ox")
        def SetPosition(self, track_id, position):
            w = self.win
            if w.cur is not None and w.want is None and track_id == self.track_id(w.cur) and position >= 0:
                w.seek_to(position / 1_000_000)

        @dbus.service.method(MPRIS_PLAYER, in_signature="s")
        def OpenUri(self, _uri):
            pass

        @dbus.service.signal(MPRIS_PLAYER, signature="x")
        def Seeked(self, position):
            pass


# --- бібліотека: скопійовані диски --------------------------------------------------------
MARKER = ".cd-auto-runner"


COVER_NAMES = ("cover.jpg", "cover.png", "folder.jpg", "Folder.jpg", "front.jpg")


THUMB = 256         # обкладинка плитки, із запасом для HiDPI


TRACK_FILE = re.compile(r"(\d{1,3})\s*(?:[-._]\s*|\s)(.+)")


# «Виконавець - Назва»: як у _cdar_read_titles (players/_lib.sh)
ARTIST_TITLE = (re.compile(r"(.*\S)\s+-\s*(\S.*)"), re.compile(r"(.*\S)\s*-\s+(\S.*)"))


# у мітці: «NN=назва» і, для цифрових альбомів, «FNN=файл» — який файл цей трек
TRACK_KEY = re.compile(r"F?\d{2,}")


PLAYLIST_DIR = "Playlists"      # те саме ім'я в _cdar_relink_playlists (players/_lib.sh)


PLAYLIST_EXT = ".m3u8"


FAVORITES = "Favorites"


def read_disc():
    """Відомості про вставлений диск (cd-auto-runner info); може чекати на MusicBrainz до двох хвилин."""
    code, out, err = run("info", timeout=120)
    info = {"tracks": [], "ok": code == 0}
    for line in out.splitlines():
        if line.startswith("T\t"):
            _t, n, artist, title, sec, state, ph = (line.split("\t") + [""] * 7)[:7]
            info["tracks"].append({"n": int(n), "artist": artist, "title": title,
                                   "sec": int(sec or 0), "state": state, "placeholder": ph == "1"})
        elif "=" in line:
            k, v = line.split("=", 1)
            info[k] = v
    if not info["ok"]:
        info["error"] = (err or out).strip()
    return info


def read_marker(folder):
    """Мітка альбому (players/_lib.sh, _cdar_write_marker): відомості й назви треків."""
    meta = {}
    try:
        with open(os.path.join(folder, MARKER), encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.rstrip("\n").split("=", 1)
                    meta[k] = v
    except (OSError, UnicodeDecodeError):
        pass
    return meta


def read_album(folder, root):
    """Тека бібліотеки як альбом — у тому ж вигляді, що й відомості про диск (InfoWorker).
    Треки — файли, що справді є в теці; мітка дає лише назви (й порядок файлів без номера
    в імені), тож теки без неї теж відкриваються. n — позиція в альбомі, num — номер на
    диску. None, якщо аудіо немає."""
    try:
        names = [e.name for e in os.scandir(folder)
                 if os.path.splitext(e.name)[1].lower() in AUDIO_EXT and e.is_file()]
    except OSError:
        return None
    if not names:
        return None
    meta = read_marker(folder)
    parent = os.path.dirname(folder)
    artist = meta.get("ALBUM_ARTIST") or (os.path.basename(parent) if parent != root else "")
    order = {v: int(k[1:]) for k, v in meta.items() if k[0] == "F" and TRACK_KEY.fullmatch(k)}
    files = []
    for name in names:
        stem = os.path.splitext(name)[0]
        m = TRACK_FILE.fullmatch(stem)
        num = int(m[1]) if m and not order else 10 ** 6     # новий файл — після збережених
        files.append((order.get(name, num), name, m[2] if m else stem))
    tracks = []
    for pos, (num, name, title) in enumerate(sorted(files), 1):
        num = pos if num == 10 ** 6 else num
        track_artist, line = artist, meta.get(f"{num:02d}", "")
        for pattern in ARTIST_TITLE:
            m = pattern.fullmatch(line)
            if m:
                track_artist, line = m[1], m[2]
                break
        tracks.append({"n": pos, "num": num, "artist": track_artist, "title": line or title, "sec": 0,
                       "state": "library", "placeholder": False, "path": os.path.join(folder, name)})
    cover = next((p for p in (os.path.join(folder, c) for c in COVER_NAMES) if os.path.isfile(p)), "")
    # DISCID пише лише копіювання диска, тож він і відрізняє такі альбоми від цифрових
    return {"ALBUM_DIR": folder, "LIBRARY_DIR": folder, "SOURCE": "ripped" if meta.get("DISCID") else "digital",
            "COVER": cover,
            "ALBUM": meta.get("ALBUM") or os.path.basename(folder), "ALBUM_ARTIST": artist,
            "YEAR": meta.get("YEAR", ""), "tracks": tracks}


def write_marker(folder, head, rows):
    """Оновлює мітку: head — відомості про альбом, rows — (ключ NN, файл або "", виконавець,
    назва). Решта рядків мітки (DISCID: з якого диска альбом) лишається."""
    kept = {k: v for k, v in read_marker(folder).items() if k not in head and not TRACK_KEY.fullmatch(k)}
    lines = ["# cd-auto-runner"] + [f"{k}={v}" for k, v in {**kept, **head}.items()]
    for key, name, artist, title in rows:
        if name:
            lines.append(f"F{key:02d}={name}")
        same = not artist or artist == head.get("ALBUM_ARTIST")
        lines.append(f"{key:02d}=" + (title if same else f"{artist} - {title}"))
    path = os.path.join(folder, MARKER)
    with open(f"{path}.part", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(f"{path}.part", path)


def scan_library(root, seen=None):
    """Альбоми бібліотеки: теки з аудіо до трьох рівнів углиб (Виконавець/Альбом/Диск 1).
    У seen (якщо є) дописує всі переглянуті теки."""
    albums = []
    root = root.rstrip(os.sep)
    for folder, dirs, _files in os.walk(root):
        if seen is not None:
            seen.append(folder)
        depth = folder[len(root):].count(os.sep)
        dirs[:] = [d for d in dirs if not d.startswith(".")] if depth < 3 else []
        album = read_album(folder, root) if depth else None
        if album:
            albums.append(album)
    albums.sort(key=lambda a: (a["ALBUM_ARTIST"].casefold(), a["ALBUM"].casefold()))
    return albums


# --- плейлісти: файли .m3u8 у теці бібліотеки, шляхи до треків — відносні ----------------
def playlists_dir(root):
    return os.path.join(root, PLAYLIST_DIR)


def favorites_path(root):
    return os.path.join(playlists_dir(root), FAVORITES + PLAYLIST_EXT)


def playlist_name(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return _("Улюблене") if stem == FAVORITES else stem


def is_playlist(path):
    return path.endswith(PLAYLIST_EXT)


def safe_name(name):
    """Назва плейліста як ім'я файлу."""
    return re.sub(r'[/\\\0-\x1f]', "-", name).strip().lstrip(".")


def track_label(track):
    return " - ".join(x for x in (track.get("artist"), track.get("title")) if x)


def read_m3u(path):
    """Записи плейліста: (повний шлях, підпис з #EXTINF — лишається, навіть якщо файл зник)."""
    entries, label = [], ""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#EXTINF:"):
                    label = line.partition(",")[2]
                elif line and not line.startswith("#"):
                    entries.append((os.path.normpath(os.path.join(os.path.dirname(path), line)), label))
                    label = ""
    except OSError:
        pass
    return entries


def write_m3u(path, entries):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    lines = ["#EXTM3U"]
    for file, label in entries:
        lines += [f"#EXTINF:-1,{label}", os.path.relpath(file, folder)]
    with open(f"{path}.part", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(f"{path}.part", path)


def read_playlist(path, root):
    """Плейліст як альбом (read_album): назви й обкладинки — з тих альбомів, де лежать треки."""
    albums, tracks = {}, []
    for pos, (file, label) in enumerate(read_m3u(path), 1):
        folder = os.path.dirname(file)
        if folder not in albums:
            albums[folder] = read_album(folder, root)
        album = albums[folder]
        found = next((t for t in album["tracks"] if t["path"] == file), None) if album else None
        if found:
            tracks.append({**found, "n": pos, "num": pos, "album": album["ALBUM"], "cover": album["COVER"]})
        else:
            artist, title = "", label or os.path.splitext(os.path.basename(file))[0]
            for pattern in ARTIST_TITLE:
                m = pattern.fullmatch(title)
                if m:
                    artist, title = m[1], m[2]
                    break
            tracks.append({"n": pos, "num": pos, "artist": artist, "title": title, "sec": 0, "state": "library",
                           "placeholder": True, "path": file, "missing": True})
    cover = os.path.splitext(path)[0] + ".jpg"
    return {"ALBUM_DIR": path, "LIBRARY_DIR": os.path.dirname(path), "PLAYLIST": path, "SOURCE": "playlist",
            "COVER": cover if os.path.isfile(cover) else "", "ALBUM": playlist_name(path), "ALBUM_ARTIST": "",
            "YEAR": "", "tracks": tracks}


def list_playlists(root):
    """Усі плейлісти за назвою; «Улюблене» є завжди й стоїть першим, навіть без файлу."""
    folder, favorites = playlists_dir(root), favorites_path(root)
    try:
        paths = [e.path for e in os.scandir(folder) if is_playlist(e.name) and e.is_file()]
    except OSError:
        paths = []
    paths = sorted((p for p in paths if p != favorites), key=str.casefold)
    return [read_playlist(p, root) for p in [favorites, *paths]]


def entry_key(info):
    """Чим є показане чи те, що грає: тека альбому, файл плейліста або ідентифікатор диска."""
    return info.get("ALBUM_DIR") or info.get("DISC_ID")


def read_entry(key, root):
    """Плитка бібліотеки чи плейліста: альбом або None."""
    return read_playlist(key, root) if is_playlist(key) else read_album(key, root)


def looks_same(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a) < 10


class ThumbCache:
    """Зменшені обкладинки перегляду бібліотеки; read і mosaic — від інструментарію вікна.
    read(шлях) → зображення; mosaic(пари (шлях, зображення)) → (зображення, мітка плитки)."""

    def __init__(self, read, mosaic):
        self.read, self.mosaic = read, mosaic
        self.thumbs = {}            # бібліотека переглядається часто, обкладинки змінюються рідко

    def thumb(self, path):
        """(зменшена обкладинка, час зміни файлу) — другий елемент оновлює плитку."""
        try:
            stamp = os.path.getmtime(path) if path else 0
        except OSError:
            stamp = 0
        if not stamp:
            return None, 0
        if (path, stamp) not in self.thumbs:
            self.thumbs[path, stamp] = self.read(path)
        return self.thumbs[path, stamp], stamp

    def scan(self, root):
        """(альбоми, плейлісти, усі теки бібліотеки) з обкладинками."""
        folders = []
        albums = scan_library(root, folders)
        for album in albums:
            album["thumb"], album["stamp"] = self.thumb(album["COVER"])
        playlists = list_playlists(root)
        for playlist in playlists:
            if playlist["COVER"]:
                playlist["thumb"], playlist["stamp"] = self.thumb(playlist["COVER"])
            else:
                covers = dict.fromkeys(t["cover"] for t in playlist["tracks"] if t.get("cover"))
                playlist["thumb"], playlist["stamp"] = self.mosaic((c, self.thumb(c)[0]) for c in covers)
        return albums, playlists, folders


def read_tags(path):
    """Теги файлу (ключі малими літерами), "_cover" — чи є обкладинка всередині."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format_tags:stream_tags:stream_disposition=attached_pic", "-of", "json", path],
                             capture_output=True, text=True, timeout=10).stdout
        data = json.loads(out)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    streams = data.get("streams") or []
    tags = {}
    for source in (*streams, data.get("format") or {}):     # Ogg тримає теги в потоці, решта — у файлі
        tags.update({k.lower(): v for k, v in (source.get("tags") or {}).items()})
    tags["_cover"] = any((s.get("disposition") or {}).get("attached_pic") for s in streams)
    return tags


def album_tags(paths):
    if not shutil.which("ffprobe"):
        return []
    with ThreadPoolExecutor(4) as pool:
        return list(pool.map(read_tags, paths))


def tag_number(value):
    """«3/12» → 3; нема номера — None."""
    m = re.match(r"\s*(\d+)", str(value or ""))
    return int(m[1]) if m else None


def album_from_tags(tags, names, titles):
    """Альбом за тегами файлів: (назва, виконавець, рік, [(виконавець, назва, файл)]).
    Порядок — за номерами диска й треку, якщо вони є в усіх файлах і не повторюються."""
    first = next((t for t in tags if t.get("album")), {})
    artist = first.get("album_artist") or first.get("album artist") or first.get("artist") or ""
    year = re.match(r"\d{4}", str(first.get("date") or first.get("year") or ""))
    rows = [(t.get("artist", ""), t.get("title") or titles[i], names[i]) for i, t in enumerate(tags)]
    numbers = [(tag_number(t.get("disc")) or 1, tag_number(t.get("track"))) for t in tags]
    if all(n[1] for n in numbers) and len(set(numbers)) == len(numbers):
        rows = [r for _n, r in sorted(zip(numbers, rows), key=lambda x: x[0])]
    return first.get("album", ""), artist, year[0] if year else "", rows


def embedded_cover(audio, path):
    """Обкладинка з аудіофайлу → path; порожньо, якщо не вийшло."""
    try:
        code = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", audio, "-an", "-c:v", "copy",
                               "-frames:v", "1", "-f", "image2", path], capture_output=True, timeout=20).returncode
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return path if code == 0 else ""


def musicbrainz(*args):
    """Запит редактора альбому (players/_mbsearch.py): дані або None, якщо мережа недоступна."""
    code, out, _err = run("musicbrainz", *args, timeout=60)
    try:
        return json.loads(out) if code == 0 else None
    except ValueError:
        return None


def fetch_cover(mbid, path):
    return path if run("musicbrainz", "--cover", mbid, path, timeout=30)[0] == 0 else ""


def track_seconds(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=10).stdout
        return int(float(out))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


class Controller:
    """Логіка програвача й бібліотеки — домішка до головного вікна.

    Вікно дає: mpv, mpris; update_player, on_position, on_duration, show_disc, show_empty,
    show_loading, show_times, show_meta, fill_library, fill_tracks, update_states, update_service,
    action, rescan (перегляд бібліотеки), load_info (InfoWorker), load_times, current_track,
    selected_tracks, select_tracks, toast, warn, start_detached, played_unseen, ui_get, ui_put."""

    def init_state(self, play=False):
        self.info = {}              # те, що показано: диск, альбом бібліотеки або плейліст
        self.queue = {}             # те, що грає; перегляд інших альбомів його не чіпає
        self.disc = {}              # вставлений диск (показаний він чи ні)
        self.albums = []
        self.playlists = []
        self.favs = set()           # шляхи улюблених треків
        self.lib_done = -1          # скільки треків диска скопійовано (нові файли — новий перегляд)
        self.last_tracks = -1
        self.loading = False
        self.cur = None             # обраний трек (грає, на паузі або чекає копіювання)
        self.want = None            # трек, який ще копіюється — відтворимо, щойно буде готовий
        self.is_paused = False
        self.length = 0.0
        self.pos = 0.0
        self.loop = self.ui_get("loop", "None")          # MPRIS LoopStatus: None | Playlist | Track
        if self.loop not in LOOP_MODES:
            self.loop = "None"
        self.shuffle = self.ui_get("shuffle", "false") == "true"
        self.order = []             # порядок треків (перемішаний, якщо ввімкнено «Перемішувати»)
        self.pending_play = play    # відтворити, щойно прочитано диск
        self.rip_started = 0.0
        self.titles_stamp = 0

    def builtin_selected(self):
        """Обрано вбудований програвач — явно або як типовий (програвач ще не обирали)."""
        pid = read_config().get("PLAYER_ID", "")
        return pid == "builtin" or (pid == "" and self.mpv is not None)

    def plays_here(self):
        """Показане зараз грає у цьому вікні, а не в обраному зовнішньому програвачі.
        Альбом — це файли: власна команда отримує лише привід, тож він грає тут."""
        if self.album_open():
            return read_config().get("PLAYER_ID", "") in ("", "builtin", "custom", "off")
        return self.builtin_selected() and self.mpv is not None

    def start_track(self, n):
        """Відтворює трек n там, де обрано; зовнішній програвач отримує альбом із цього треку."""
        if self.plays_here():
            self.adopt()
            self.play_track(n)
            return
        self.stop_playback()            # щоб не грали обидва
        if self.album_open():
            self.toast(_("Запускаю {name}…", name=read_config().get("PLAYER_NAME", "")))
            self.action("open", extra=[t["path"] for t in self.info["tracks"][n - 1:] if not t.get("missing")])
        else:
            self.action("play")

    def player_info(self):
        """Те, чим зараз зайнятий програвач; якщо нічим — те, що він запустить."""
        return self.queue if self.cur is not None else self.info

    def adopt(self):
        """Програвач береться за показане; інше, що грало, зупиняється."""
        if entry_key(self.info) != entry_key(self.queue):
            self.stop_playback()
            self.order = []
        self.queue = self.info

    def showing_queue(self):
        return self.cur is not None and entry_key(self.info) == entry_key(self.queue)

    def queue_is_disc(self):
        return bool(self.queue.get("DISC_ID")) and not self.queue.get("ALBUM_DIR")

    def track_title(self, n, info=None):
        for t in (info if info is not None else self.player_info()).get("tracks", []):
            if t["n"] == n:
                return t
        return None

    def album_open(self):
        """Показано альбом бібліотеки, а не вставлений диск."""
        return bool(self.info.get("ALBUM_DIR"))

    def playlist_open(self):
        return self.info.get("PLAYLIST", "")

    def library_file(self, n, info):
        """Файл треку вставленого диска в бібліотеці, якщо його вже скопійовано."""
        lib = info.get("LIBRARY_DIR", "")
        if lib:
            for f in sorted(glob.glob(os.path.join(glob.escape(lib), f"{n:02d} - *"))):
                if os.path.splitext(f)[1].lower() in AUDIO_EXT and os.path.isfile(f):
                    return f
        return None

    def track_file(self, n):
        """Готовий файл треку: у бібліотеці (закодований) або скопійований WAV у кеші."""
        if self.queue.get("ALBUM_DIR"):
            return self.track_title(n, self.queue)["path"]
        lib = self.library_file(n, self.queue)
        if lib:
            return lib
        cache = self.queue.get("CACHE_DIR", "")
        if cache and os.path.exists(os.path.join(cache, f".done-{n}")):
            try:
                with open(os.path.join(cache, f".name-{n}"), encoding="utf-8") as f:
                    path = os.path.join(cache, f.read().strip())
            except OSError:
                return None
            if os.path.isfile(path):
                return path
        return None

    def write_want(self, n):
        """Трек, який хочуть слухати: копіювання (players/_builtin.sh) бере його першим."""
        cache = self.queue.get("CACHE_DIR", "")
        if not cache:
            return
        path = os.path.join(cache, ".want")
        try:
            if n is None:
                if os.path.exists(path):
                    os.remove(path)
            else:
                os.makedirs(cache, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"{n}\n")
        except OSError:
            pass

    def rip_running(self):
        try:
            out = subprocess.run(["systemctl", "--user", "list-units", f"{APP}-play-*", "--no-legend", "--plain"],
                                 capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        return bool(out.strip()) or self.ripping_track() is not None

    def ensure_ripping(self):
        """Запускає копіювання для вбудованого програвача, якщо воно ще не йде."""
        if not self.queue.get("DEVICE") or time.monotonic() - self.rip_started < 30 or self.rip_running():
            return
        self.rip_started = time.monotonic()
        self.start_detached(self_bin(), ["play", "--player", "builtin", "--no-window", self.queue["DEVICE"]])

    def play_track(self, n):
        tracks = self.queue.get("tracks", [])
        if not self.mpv or not tracks or not 1 <= n <= len(tracks):
            return
        if tracks[n - 1].get("missing"):
            self.toast(_("Файлу треку {n} більше немає.", n=n))
            return
        self.cur = n
        self.pos = 0.0
        path = self.track_file(n)
        if path:
            self.want = None
            self.write_want(None)
            self.length = 0.0
            self.mpv.load(path)
        else:
            self.want = n
            self.mpv.stop()
            self.write_want(n)
            self.ensure_ripping()
        self.is_paused = False
        self.update_player()

    def stop_playback(self):
        if self.mpv:
            self.mpv.stop()
        self.cur = self.want = None
        self.is_paused = False
        self.write_want(None)
        self.on_position(0)
        self.on_duration(0)
        self.update_player()

    def toggle_play(self):
        if not self.mpv:
            return
        if self.cur is None:
            sel = self.current_track()
            if sel:
                self.start_track(sel)
            else:
                self.adopt()
                self.start_track(self.first_track())
        elif self.want is None:
            self.mpv.toggle()

    def playable(self, info):
        """Номери треків, які можна грати: у плейлісті файл треку міг зникнути."""
        return [t["n"] for t in info.get("tracks", []) if not t.get("missing")]

    def play_order(self):
        tracks = self.playable(self.queue)
        if sorted(self.order) != tracks:
            self.order = self.new_order(tracks)
        return self.order

    def new_order(self, tracks):
        order = list(tracks)
        if self.shuffle:
            random.shuffle(order)
            if self.cur in order:           # поточний трек — першим, щоб «далі» не повторювало вже чуте
                order.remove(self.cur)
                order.insert(0, self.cur)
        return order

    def neighbor(self, step):
        """Трек, що йде за поточним (step=1) або перед ним (step=-1), з урахуванням повтору диска."""
        order = self.play_order()
        if self.cur is None or self.cur not in order:
            return None
        i = order.index(self.cur) + step
        if 0 <= i < len(order):
            return order[i]
        return order[i % len(order)] if self.loop == "Playlist" else None

    def set_shuffle(self, on):
        self.shuffle = bool(on)
        self.ui_put("shuffle", "true" if self.shuffle else "false")
        self.order = self.new_order(self.playable(self.queue))
        self.update_player()

    def set_loop(self, mode):
        if mode in LOOP_MODES:
            self.loop = mode
            self.ui_put("loop", mode)
            self.update_player()

    def cycle_loop(self):
        modes = list(LOOP_MODES)
        self.set_loop(modes[(modes.index(self.loop) + 1) % len(modes)])

    def first_track(self):
        order = self.play_order()
        return order[0] if order else 1

    def prev_track(self):
        if self.cur is None:
            return
        if self.want is None and self.pos > 3:
            self.seek_to(0)
        else:
            n = self.neighbor(-1)
            if n is not None:
                self.play_track(n)

    def next_track(self):
        n = self.neighbor(1)
        if n is not None:
            self.play_track(n)

    def on_play(self):
        """Кнопка «Відтворити»: вбудований програвач — у цьому вікні, інакше — обраний програвач."""
        tracks = self.playable(self.info)
        if not tracks:
            return                      # порожній плейліст
        if not self.plays_here():
            self.start_track(tracks[0])
        elif not self.showing_queue():  # показане інше, ніж грає: тепер гратиме показане
            self.adopt()
            self.play_track(self.first_track())
        elif self.is_paused:
            self.mpv.toggle()

    def request_play(self):
        """--play або повідомлення від іншого запуску: відтворити диск з початку.
        Вставлений диск важливіший за відкритий альбом: альбом поступається йому."""
        if self.disc.get("tracks") and not self.loading:
            self.pending_play = False
            if self.album_open():
                self.open_disc()
            self.adopt()
            if self.cur is None:
                self.play_track(self.first_track())
                self.played_unseen()
        else:
            self.pending_play = True

    def seek_to(self, sec):
        if not self.mpv or self.cur is None or self.want is not None:
            return
        sec = max(0.0, sec)
        if self.length and sec >= self.length:
            self.next_track()
            return
        self.mpv.seek(sec)
        self.pos = sec
        self.on_position(sec)
        if self.mpris:
            self.mpris.Seeked(dbus.Int64(int(sec * 1_000_000)))

    def on_paused(self, paused):
        self.is_paused = paused
        self.update_player()

    def on_ended(self, reason):
        if reason == "eof" and self.cur is not None and self.want is None:
            n = self.cur if self.loop == "Track" else self.neighbor(1)
            if n is not None:
                self.play_track(n)
            else:
                self.stop_playback()
        elif reason == "error" and self.cur is not None:
            self.toast(_("Не вдалося відтворити трек {n}.", n=self.cur))
            self.stop_playback()
        elif reason == "quit":
            self.stop_playback()

    def on_mpv_failed(self):
        self.stop_playback()
        self.warn(_("Не вдалося запустити mpv."))

    def open_album(self, folder):
        """Показує альбом або плейліст замість диска; диск лишається в приводі й копіюється далі,
        а те, що грає, грає далі. Альбом, який грає, відкривається тим самим об'єктом."""
        playing = self.cur is not None and self.queue.get("ALBUM_DIR") == folder
        album = self.queue if playing else read_entry(folder, self.library_root())
        if not album:
            self.toast(_("Не вдалося відкрити альбом."))
            self.rescan()
            return False
        self.pending_play = False
        self.info = album
        self.show_disc()
        self.update_states()
        self.load_times(folder, [t["path"] for t in album["tracks"]])
        return True

    def continue_from_library(self):
        """Диск вийнято, а поточний трек уже є в бібліотеці: файлу диск не потрібен, тож програвач
        переходить на альбом і відтворення не уривається. False — грати далі нема чого."""
        folder = self.queue.get("LIBRARY_DIR")
        if self.cur is None or self.want is not None or not folder:
            return False
        album = read_album(folder, self.library_root())
        track = next((t for t in album["tracks"] if t["num"] == self.cur), None) if album else None
        if track is None:
            return False
        shown = self.showing_queue()
        self.queue, self.cur, self.order = album, track["n"], []
        if shown:
            self.info = album
            self.show_disc()
            self.update_states()
        self.load_times(folder, [t["path"] for t in album["tracks"]])
        return True

    def disc_gone(self):
        """Диска більше немає: те, що грало з нього, переходить на бібліотеку або зупиняється;
        показаний альбом лишається, а замість показаного диска — порожнє вікно."""
        if self.queue_is_disc() and not self.continue_from_library():
            self.stop_playback()
        if self.album_open():
            self.fill_library()
        else:
            self.info = {}
            self.show_empty()

    def open_disc(self):
        self.info = self.disc
        self.show_disc()
        self.update_states()

    def close_album(self):
        """Показаного більше немає (видалений плейліст): назад до диска або порожнього вікна."""
        if self.disc:
            self.open_disc()
        else:
            self.info = {}
            self.show_empty()

    def on_times(self, folder, times):
        """Тривалості треків альбому: файлів багато, тож вони приходять уже після відкриття."""
        for info in (self.info, self.queue):
            if info.get("ALBUM_DIR") == folder:
                for t in info["tracks"]:
                    t["sec"] = times.get(t["path"], 0)
        if self.info.get("ALBUM_DIR") == folder:
            self.show_times()

    def reload_entry(self, key):
        """Альбом або плейліст змінився: оновлює показане й те, що грає, не перериваючи звук."""
        shown, queued = self.info.get("ALBUM_DIR") == key, self.queue.get("ALBUM_DIR") == key
        if not shown and not queued:
            return
        old = self.queue if queued else self.info
        fresh = read_entry(key, self.library_root())
        if fresh:
            times = {t["path"]: t["sec"] for t in old["tracks"]}
            for t in fresh["tracks"]:
                t["sec"] = times.get(t["path"], 0)
        if queued:
            found = None
            if self.cur is not None and fresh:
                playing = self.track_title(self.cur, self.queue)["path"]
                found = next((t["n"] for t in fresh["tracks"] if t["path"] == playing and not t.get("missing")), None)
            if found is None:
                self.stop_playback()
            self.queue, self.order, self.cur = fresh or {}, [], found
        if shown and not fresh:
            self.close_album()
        elif shown:
            self.info = fresh
            self.show_disc()
            self.update_states()
            if not all(t["sec"] for t in fresh["tracks"]):
                self.load_times(key, [t["path"] for t in fresh["tracks"]])
        self.update_player()

    def load_favorites(self):
        self.favs = {path for path, _label in read_m3u(favorites_path(self.library_root()))}

    def track_link(self, n, info):
        """(файл, підпис) треку для плейліста; None — файлу в бібліотеці немає (ще не скопійовано)."""
        t = self.track_title(n, info)
        if not t or t.get("missing"):
            return None
        path = t.get("path") or self.library_file(n, info)
        return (os.path.normpath(path), track_label(t)) if path else None

    def store_playlist(self, path, entries):
        """Записує плейліст і оновлює все, що його показує."""
        try:
            write_m3u(path, entries)
        except OSError as e:
            self.warn(_("Не вдалося записати зміни: {e}", e=e))
            return False
        self.load_favorites()
        self.reload_entry(path)
        self.update_player()
        self.rescan()
        return True

    def add_to_playlist(self, path, links):
        entries = read_m3u(path)
        known = {file for file, _label in entries}
        new = list({link[0]: link for link in links if link[0] not in known}.values())
        if not new:
            self.toast(_("Ці треки вже є в плейлісті."))
        elif self.store_playlist(path, entries + new):
            self.toast(_("Додано треків: {n}", n=len(new)))

    def toggle_favorite(self, links):
        path = favorites_path(self.library_root())
        files = {link[0] for link in links}
        if files <= self.favs:
            self.store_playlist(path, [e for e in read_m3u(path) if e[0] not in files])
        else:
            self.add_to_playlist(path, links)

    def on_favorite(self):
        link = self.track_link(self.cur, self.queue) if self.cur is not None else None
        if link:
            self.toggle_favorite([link])
        self.update_player()            # кнопка перемикається сама — повертаємо справжній стан

    def playlist_image(self):
        """Складена з треків обкладинка показаного плейліста, якщо власної немає."""
        key = self.playlist_open()
        if not key or self.info.get("COVER"):
            return None
        return next((p["thumb"] for p in self.playlists if p["PLAYLIST"] == key), None)

    def save_order(self, tracks, selected=()):
        """Новий порядок треків показаного плейліста; selected — які рядки лишити виділеними."""
        if self.store_playlist(self.playlist_open(), [(t["path"], track_label(t)) for t in tracks]):
            self.select_tracks([t["n"] for t in self.info["tracks"] if t["path"] in selected])

    def move_tracks(self, step):
        tracks = list(self.info["tracks"])
        chosen = [n - 1 for n in self.selected_tracks()]
        moved = {tracks[i]["path"] for i in chosen}
        taken = set(chosen)
        for i in sorted(chosen, reverse=step > 0):
            to = i + step
            if 0 <= to < len(tracks) and to not in taken:
                tracks[i], tracks[to] = tracks[to], tracks[i]
                taken.discard(i)
                taken.add(to)
        self.save_order(tracks, moved)

    def remove_tracks(self):
        chosen = set(self.selected_tracks())
        self.save_order([t for t in self.info["tracks"] if t["n"] not in chosen])

    def is_favorites_open(self):
        return self.playlist_open() == favorites_path(self.library_root())

    def show_tile(self, key):
        """Показує плитку; те, що грає, грає далі. False — альбому вже немає."""
        if key == self.info.get("ALBUM_DIR", ""):
            return True
        if key:
            return self.open_album(key)
        self.open_disc()
        return True

    def library_root(self):
        d = read_config().get("LIBRARY_DIR", "")
        if not d:
            try:
                d = subprocess.run(["xdg-user-dir", "MUSIC"], capture_output=True, text=True).stdout.strip()
            except OSError:
                d = ""
        return d if d and d != os.path.expanduser("~") else os.path.expanduser("~/Music")

    def reload_info(self):
        if self.loading:
            return
        self.loading = True
        if not self.album_open():
            self.show_loading()
        self.load_info()

    def on_info(self, info):
        self.loading = False
        self.rescan()
        inserted = udev_audio_tracks() != 0
        self.disc = info if inserted and info.get("ok") else {}
        self.titles_stamp = self.titles_mtime()
        if self.disc and self.queue_is_disc():
            if self.disc.get("DISC_ID") == self.queue.get("DISC_ID"):
                self.queue = self.disc  # той самий диск, свіжі назви
            else:
                self.stop_playback()    # інший диск
                self.order = []
        if not inserted:
            self.disc_gone()
            return
        # відкритий альбом лишається, поки диск не почнуть відтворювати
        if self.album_open() and not (self.disc and self.pending_play):
            self.fill_library()
            return
        if not info.get("ok"):
            if self.queue_is_disc():
                self.stop_playback()
            self.info = {}
            self.show_empty(_("Не вдалося прочитати диск"), info.get("error", ""))
            return
        self.info = info
        self.show_disc()
        if self.pending_play:
            self.request_play()

    def ripping_track(self):
        try:
            out = subprocess.run(["pgrep", "-a", "-u", str(os.getuid()), "cd-paranoia|cdparanoia"],
                                 capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
        m = re.search(r"-d \S+ (\d+)(?: |$)", out) or re.search(r"-w (\d+)", out)
        return int(m.group(1)) if m else None

    def titles_mtime(self):
        """Час зміни файлів із назвами цього диска: введених вручну й мітки в бібліотеці."""
        i, stamp = self.disc, 0.0
        cfg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        for path in (os.path.join(cfg, APP, "discs", f"{i.get('MB_DISCID', '')}.conf"),
                     os.path.join(i.get("LIBRARY_DIR", ""), ".cd-auto-runner")):
            try:
                stamp = max(stamp, os.path.getmtime(path))
            except OSError:
                pass
        return stamp

    def library_rows(self):
        """Плитки для вікна: ((рядки, обкладинки) альбомів, те саме для плейлістів, відкрите зараз).
        Рядок: ключ, назва, підпис, обкладинка, докладно, мітка часу, запасний значок, з диска."""
        rows = []
        if self.disc.get("tracks"):
            d = self.disc
            rows.append(("", d.get("ALBUM") or _("Аудіо-CD"), _("Диск у приводі"), d.get("COVER", ""),
                         d.get("ALBUM_ARTIST", ""), 0, "media-optical-audio", True))
        thumbs = {}
        current = self.info.get("ALBUM_DIR", "") if self.info else None
        # вставлений диск уже є плиткою; його альбом лишається, лише якщо зараз відкритий
        same = os.path.normpath(self.disc["LIBRARY_DIR"]) if self.disc.get("LIBRARY_DIR") else None
        for a in self.albums:
            if a["ALBUM_DIR"] == same and same != current:
                continue
            ripped = a["SOURCE"] == "ripped"
            kind = _("Записано з диска") if ripped else _("Цифровий альбом")
            more = " · ".join(x for x in (a["ALBUM_ARTIST"], a["YEAR"], _("треків: {n}", n=len(a["tracks"])), kind) if x)
            rows.append((a["ALBUM_DIR"], a["ALBUM"], a["ALBUM_ARTIST"] or a["YEAR"], a["COVER"], more, a["stamp"],
                         "media-optical-audio", ripped))
            thumbs[a["ALBUM_DIR"]] = a["thumb"]
        albums = (rows, thumbs)
        rows, thumbs = [], {}
        for p in self.playlists:
            count = _("треків: {n}", n=len(p["tracks"]))
            favorite = os.path.basename(p["PLAYLIST"]) == FAVORITES + PLAYLIST_EXT
            rows.append((p["PLAYLIST"], p["ALBUM"], count, p["COVER"], "", p["stamp"],
                         "" if favorite else "view-media-playlist", False))
            thumbs[p["PLAYLIST"]] = p["thumb"]
        return albums, (rows, thumbs), current

    def now_text(self):
        """Рядок «що грає» під елементами керування."""
        if not self.mpv:
            return _("Для вбудованого програвача встановіть mpv (пакет mpv).")
        if self.cur is None:
            return _("Нічого не відтворюється")
        if self.want is not None:
            return _("Чекаю, поки скопіюється трек {n}…", n=self.want)
        t = self.track_title(self.cur) or {}
        text = f"{t.get('num', self.cur):02d}. {t.get('title', '')}"
        if t.get("artist") and t.get("artist") != self.queue.get("ALBUM_ARTIST"):
            text += f" — {t['artist']}"
        if self.is_paused:
            text += f"  ({_('Пауза')})"
        return text

    def badge_text(self):
        src = self.info.get("SOURCE", "none")
        labels = {"musicbrainz": "Назви з MusicBrainz", "cdtext": "Назви з диска (CD-TEXT)",
                  "mbsearch": "MusicBrainz (за назвою)", "library": "З бібліотеки", "playlist": "Плейліст",
                  "ripped": "Записано з диска", "digital": "Цифровий альбом",
                  "user": "Назви введено вручну", "kde": "Кеш KDE", "none": "Диска немає в базах"}
        return _(labels.get(src, src))

    def disc_progress(self):
        """Стан копіювання вставленого диска: ([(стан, значок) на трек], скопійовано, що копіюється)."""
        i = self.disc
        lib, cache = i.get("LIBRARY_DIR", ""), i.get("CACHE_DIR", "")
        ripping = self.ripping_track()
        rows, done = [], 0
        for t in i.get("tracks", []):
            n = t["n"]
            if lib and glob.glob(os.path.join(glob.escape(lib), f"{n:02d} - *")):
                rows.append((_("у бібліотеці"), "emblem-ok-symbolic"))
                done += 1
            elif cache and os.path.exists(os.path.join(cache, f".done-{n}")):
                rows.append((_("скопійовано"), "document-save"))
                done += 1
            elif ripping == n:
                rows.append((_("копіюється…"), "media-record"))
            else:
                rows.append(("", ""))
        if done != self.lib_done:
            self.lib_done = done
            self.rescan()
        return rows, done, ripping

    def rename_entry(self, path, new):
        """Перейменовує файл плейліста з його обкладинкою; False — не вдалося."""
        cover = os.path.splitext(path)[0] + ".jpg"
        try:
            os.rename(path, new)
            if os.path.isfile(cover):
                os.rename(cover, os.path.splitext(new)[0] + ".jpg")
        except OSError as e:
            self.warn(_("Не вдалося записати зміни: {e}", e=e))
            return False
        for info in (self.info, self.queue):
            if info.get("PLAYLIST") == path:
                info["ALBUM_DIR"] = info["PLAYLIST"] = new
        self.reload_entry(new)
        self.rescan()
        return True

    def remove_entry(self, path):
        """Видаляє файл плейліста й обкладинку (підтвердження — у вікні)."""
        for file in (path, os.path.splitext(path)[0] + ".jpg"):
            try:
                os.remove(file)
            except FileNotFoundError:
                pass
            except OSError as e:
                self.warn(_("Не вдалося записати зміни: {e}", e=e))
                return
        if self.queue.get("PLAYLIST") == path:
            self.stop_playback()
            self.queue = {}
        if self.playlist_open() == path:
            self.close_album()
        self.rescan()

    def remove_playlist_cover(self, path):
        try:
            os.remove(os.path.splitext(path)[0] + ".jpg")
        except OSError:
            pass
        self.after_cover(path)

    def after_cover(self, path):
        self.reload_entry(path)
        self.rescan()

    def can_background(self):
        """Вікно можна закрити, а музику лишити: керуватимуть нею елементи MPRIS."""
        return self.mpris is not None and self.cur is not None and not self.is_paused

    def poll_disc(self):
        """Періодична перевірка: вставлений чи вийнятий диск, нові назви, стан копіювання."""
        # назви змінили не з вікна (сповіщення «Ввести назви…», термінал) — оновити
        if self.disc and not self.loading and self.titles_mtime() != self.titles_stamp:
            self.reload_info()
        tracks = udev_audio_tracks()
        if tracks != self.last_tracks:
            self.last_tracks = tracks
            if tracks:
                self.reload_info()
            else:
                self.disc = {}
                self.disc_gone()
                # диск вийнято — кеш змісту диска більше не чинний
                runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
                for f in glob.glob(os.path.join(runtime, APP, "toc-*")):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
        self.update_states()
        self.update_service()
        # трек, якого чекаємо, скопійовано — відтворюємо; копіювання не йде — запускаємо
        if self.want is not None and self.queue.get("tracks"):
            if self.track_file(self.want):
                self.play_track(self.want)
            else:
                self.ensure_ripping()
