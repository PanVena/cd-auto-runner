#!/usr/bin/env python3
"""CD Auto Runner — головне вікно (PySide6).

Вікно показує стан і викликає cd-auto-runner (CDAR_SELF): уся логіка копіювання — у скрипті.
Вбудований програвач відтворює скопійовані треки через mpv (окремий процес, керування —
JSON IPC через локальний сокет) і показує себе системі через MPRIS (віджет «Програвач»,
мультимедійні клавіші); вікно згортається в системний лоток. Картка «Бібліотека» відкриває
вже скопійовані диски замість вставленого (або коли диска немає), вкладка «Плейлісти» —
плейлісти, що посилаються на треки бібліотеки. Тексти українською; EN — англійський
переклад (CDAR_UI_LANG).

  gui.py [--play] [ПРИСТРІЙ]   --play — одразу відтворювати диск у вбудованому програвачі

CD Auto Runner main window. Ripping logic lives in the cd-auto-runner script; the built-in
player plays ripped tracks through mpv, controlled over its JSON IPC socket, and is exposed
to the desktop over MPRIS; the window hides to the system tray. The Library card opens
already ripped discs instead of the inserted one (or when there is none); its Playlists
tab holds playlists that link to library tracks.

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor    # у Python 3.15 атрибут модуля лінивий і в потоці Qt не спрацьовує

from PySide6.QtCore import (
    QFileSystemWatcher, QObject, QPoint, QProcess, QRect, QRectF, QSettings, QSize, Qt, QTemporaryDir, QThread, QTimer, QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QImage, QImageReader, QPainter, QPainterPath, QPalette, QPen, QPixmap,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSplitter, QStackedWidget,
    QStyle, QStyledItemDelegate, QSystemTrayIcon, QTabBar, QTableWidget, QTableWidgetItem, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

try:    # MPRIS — необов'язково: без dbus-python програвач просто не видно у віджеті «Програвач»
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
except ImportError:
    dbus = None

APP = "cd-auto-runner"
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
    "Відтворюю диск. Керувати ним можна зі значка в лотку або з віджета «Програвач».":
        "Playing the disc. Control it from the tray icon or the Media Player widget.",
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


def icon(*names):
    """Монохромний значок теми, перефарбований кольором тексту кнопок: білий на темній
    темі, темний на світлій (без теми Plasma Qt бере значки, намальовані для іншого тла)."""
    base = QIcon()
    for name in names:
        base = QIcon.fromTheme(name)
        if not base.isNull():
            break
    if base.isNull():
        return base
    pal = QApplication.palette()
    normal = pal.color(QPalette.Active, QPalette.ButtonText)
    disabled = QColor(normal)
    disabled.setAlpha(90)
    out = QIcon()
    for mode, color in ((QIcon.Normal, normal), (QIcon.Active, normal), (QIcon.Selected, pal.color(QPalette.HighlightedText)),
                        (QIcon.Disabled, disabled)):
        for size in (16, 20, 22, 24, 28, 32, 48):
            pix = base.pixmap(size, size)
            if pix.isNull():
                continue
            tinted = QPixmap(pix.size())
            tinted.setDevicePixelRatio(pix.devicePixelRatio())
            tinted.fill(Qt.transparent)
            p = QPainter(tinted)
            p.drawPixmap(0, 0, pix)
            p.setCompositionMode(QPainter.CompositionMode_SourceIn)
            p.fillRect(tinted.rect(), color)
            p.end()
            out.addPixmap(tinted, mode)
    return out


def heart_icon():
    """Серце «Улюбленого»: контур, а для натиснутої кнопки — заливка. Намальоване тут, бо значки
    тем різні: у Papirus це кольорова емблема на круглому тлі, і icon() зробив би з неї диск."""
    pal = QApplication.palette()
    normal = pal.color(QPalette.Active, QPalette.ButtonText)
    disabled = QColor(normal)
    disabled.setAlpha(90)
    heart = QPainterPath()
    heart.moveTo(0.5, 0.88)
    heart.cubicTo(0.2, 0.64, 0.06, 0.48, 0.06, 0.32)
    heart.cubicTo(0.06, 0.19, 0.16, 0.12, 0.28, 0.12)
    heart.cubicTo(0.37, 0.12, 0.45, 0.17, 0.5, 0.26)
    heart.cubicTo(0.55, 0.17, 0.63, 0.12, 0.72, 0.12)
    heart.cubicTo(0.84, 0.12, 0.94, 0.19, 0.94, 0.32)
    heart.cubicTo(0.94, 0.48, 0.8, 0.64, 0.5, 0.88)
    out = QIcon()
    for size in (16, 22, 24, 32, 44, 48, 128, 256):
        for mode, color in ((QIcon.Normal, normal), (QIcon.Active, normal), (QIcon.Disabled, disabled)):
            for state in (QIcon.Off, QIcon.On):
                pix = QPixmap(size, size)
                pix.fill(Qt.transparent)
                p = QPainter(pix)
                p.setRenderHint(QPainter.Antialiasing)
                p.scale(size, size)
                p.setPen(QPen(color, max(1.5 / size, 0.07)))
                p.setBrush(color if state == QIcon.On else Qt.NoBrush)
                p.drawPath(heart)
                p.end()
                out.addPixmap(pix, mode, state)
    return out


def is_dark(pal):
    return pal.color(QPalette.Window).lightness() < 128


# не лише те, що копіюється з дисків: у бібліотеці можуть лежати й цифрові альбоми
AUDIO_EXT = {".flac", ".opus", ".ogg", ".mp3", ".wav", ".m4a", ".aac", ".wma", ".ape", ".wv", ".aiff", ".aif"}

# режими повтору (як LoopStatus у MPRIS): значок і підказка; кнопка перемикає їх по колу
LOOP_MODES = {
    "None": ("media-playlist-repeat", "Повтор: вимкнено"),
    "Playlist": ("media-playlist-repeat", "Повтор: увесь диск"),
    "Track": ("media-playlist-repeat-song", "Повтор: один трек"),
}


# --- рушій вбудованого програвача: mpv у фоні, керування через JSON IPC --------------
class Mpv(QObject):
    """mpv без вікна (--idle). Окремий процес: програма лише надсилає йому команди."""
    position = Signal(float)
    duration = Signal(float)
    paused = Signal(bool)
    ended = Signal(str)         # причина: eof | stop | error | quit
    failed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self.sock = None
        self.buf = b""
        self.queue = []
        self.tries = 0
        self.volume = 100
        self.path = os.path.join(runtime_dir(), f"mpv-{os.getpid()}.sock")

    @staticmethod
    def available():
        return shutil.which("mpv") is not None

    def running(self):
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self):
        if self.running():
            return
        try:
            os.remove(self.path)
        except OSError:
            pass
        self.sock, self.buf, self.tries = None, b"", 0
        self.proc = QProcess(self)
        self.proc.setProgram("mpv")
        self.proc.setArguments([
            "--idle=yes", "--no-video", "--force-window=no", "--no-terminal", "--audio-display=no",
            "--input-default-bindings=no", "--gapless-audio=weak", "--title=CD Auto Runner",
            # перекриваємо налаштування mpv.conf, що заважали б переходу на наступний трек
            "--keep-open=no", "--loop-file=no", "--loop-playlist=no", "--resume-playback=no",
            "--save-position-on-quit=no",
            # без скриптів (зокрема mpv-mpris): у системі програвач показує саме вікно (Mpris)
            "--load-scripts=no",
            f"--volume={self.volume}", f"--input-ipc-server={self.path}",
        ])
        self.proc.setProcessChannelMode(QProcess.ForwardedErrorChannel)
        self.proc.setStandardOutputFile(QProcess.nullDevice())
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)
        self.proc.start()
        QTimer.singleShot(100, self._connect)

    def _connect(self):
        if not self.running():
            return
        sock = QLocalSocket(self)
        sock.connectToServer(self.path)
        if not sock.waitForConnected(200):
            sock.deleteLater()
            self.tries += 1
            if self.tries < 50:          # до ~10 с
                QTimer.singleShot(100, self._connect)
            else:
                self.quit()
                self.failed.emit()
            return
        sock.readyRead.connect(self._read)
        self.sock = sock
        for i, name in enumerate(("time-pos", "duration", "pause"), 1):
            self._write({"command": ["observe_property", i, name]})
        queue, self.queue = self.queue, []
        for cmd in queue:
            self._write(cmd)

    def _write(self, cmd):
        self.sock.write(json.dumps(cmd).encode() + b"\n")
        self.sock.flush()

    def command(self, *args):
        cmd = {"command": list(args)}
        if self.sock and self.sock.state() == QLocalSocket.ConnectedState:
            self._write(cmd)
        else:
            self.queue.append(cmd)
            self.start()

    def _read(self):
        self.buf += bytes(self.sock.readAll())
        *lines, self.buf = self.buf.split(b"\n")
        for line in lines:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            ev = msg.get("event")
            if ev == "property-change":
                name, data = msg.get("name"), msg.get("data")
                if name == "time-pos":
                    self.position.emit(float(data or 0))
                elif name == "duration":
                    self.duration.emit(float(data or 0))
                elif name == "pause":
                    self.paused.emit(bool(data))
            elif ev == "end-file":
                self.ended.emit(msg.get("reason", ""))

    def _error(self, err):
        if err == QProcess.FailedToStart:
            self.failed.emit()

    def _finished(self, *_a):
        self.sock = None
        self.queue = []
        self.ended.emit("quit")

    # --- команди ---
    def load(self, path):
        self.command("loadfile", path, "replace")
        self.command("set_property", "pause", False)

    def toggle(self):
        self.command("cycle", "pause")

    def seek(self, sec):
        self.command("seek", sec, "absolute")

    def set_volume(self, vol):
        self.volume = vol
        if self.running():
            self.command("set_property", "volume", vol)

    def stop(self):
        if self.running():
            self.command("stop")

    def quit(self):
        if not self.running():
            return
        proc = self.proc
        proc.finished.disconnect(self._finished)
        if self.sock and self.sock.state() == QLocalSocket.ConnectedState:
            self._write({"command": ["quit"]})
        if not proc.waitForFinished(1500):
            proc.kill()
            proc.waitForFinished(1000)
        self.sock = None
        try:
            os.remove(self.path)
        except OSError:
            pass


# --- MPRIS: вбудований програвач у віджеті «Програвач» і на мультимедійних клавішах -----
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_ROOT = "org.mpris.MediaPlayer2"
MPRIS_PLAYER = "org.mpris.MediaPlayer2.Player"
DBUS_PROPS = "org.freedesktop.DBus.Properties"
NO_TRACK = "/org/mpris/MediaPlayer2/TrackList/NoTrack"


def start_mpris(win):
    """Сервіс MPRIS у циклі подій вікна. dbus-python працює в циклі GLib, тож лише тоді,
    коли Qt сам крутить цикл GLib (типово в Linux; QT_NO_GLIB=1 його вимикає)."""
    dispatcher = QApplication.instance().eventDispatcher()
    # QEventDispatcherGlib, QPAEventDispatcherGlib (Wayland), QXcbGlibEventDispatcher (X11)
    if dbus is None or dispatcher is None or "Glib" not in dispatcher.metaObject().className():
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
                meta["mpris:artUrl"] = dbus.String(bytes(QUrl.fromLocalFile(cover).toEncoded()).decode())
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
                "Volume": dbus.Double(w.vol.value() / 100),
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
                self.win.vol.setValue(round(max(0.0, min(1.0, float(value))) * 100))
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


# --- фонове завантаження відомостей про диск ------------------------------------------
class InfoWorker(QObject):
    done = Signal(dict)

    def load(self):
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
        self.done.emit(info)


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


def fingerprint(image):
    """Зменшена копія обкладинки: той самий малюнок може лежати в кількох теках різними файлами."""
    small = image.convertToFormat(QImage.Format_RGB888).scaled(12, 12, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return bytes(small.constBits())     # рядок — рівно 36 байтів, вирівнювання нічого не додає


def looks_same(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a) < 10


def different_covers(covers, limit=4):
    """Перші limit обкладинок із різними малюнками; covers — пари (шлях, зображення)."""
    picked, prints = [], []
    for path, image in covers:
        if image is None or image.isNull():
            continue
        mark = fingerprint(image)
        if not any(looks_same(mark, seen) for seen in prints):
            picked.append((path, image))
            prints.append(mark)
            if len(picked) == limit:
                break
    return picked


def mosaic(images):
    """Обкладинка плейліста без власної: один альбом — на всю плитку, інакше сітка 2×2, де
    заповнено стільки клітинок, скільки різних альбомів. Обкладинки цілі, без обрізання."""
    if len(images) < 2:
        return images[0] if images else None
    half = THUMB // 2
    out = QImage(THUMB, THUMB, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    for i, image in enumerate(images[:4]):
        cell = QRect((i % 2) * half, (i // 2) * half, half, half)
        fitted = QRect(QPoint(0, 0), image.size().scaled(cell.size(), Qt.KeepAspectRatio))
        fitted.moveCenter(cell.center())
        p.drawImage(fitted, image)
    p.end()
    return out


def thumbnail(path):
    """Зменшена обкладинка; QImage, а не QPixmap — читається у фоновому потоці."""
    reader = QImageReader(path)
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(size.scaled(THUMB, THUMB, Qt.KeepAspectRatioByExpanding))
    return reader.read()


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


class Task(QThread):
    """Разова фонова робота діалогу. Живе в Task.alive, поки не завершиться: діалог можуть
    закрити раніше, а знищений потік, що працює, обвалив би програму."""
    done = Signal(object)
    alive = set()

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args
        Task.alive.add(self)
        self.finished.connect(self.forget)

    def forget(self):
        Task.alive.discard(self)

    def run(self):
        self.done.emit(self.fn(*self.args))


def track_seconds(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=10).stdout
        return int(float(out))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


class LibraryWorker(QObject):
    """Окремий потік: InfoWorker може чекати на диск і MusicBrainz до двох хвилин."""
    scanned = Signal(object, object, object)    # альбоми, плейлісти, усі теки бібліотеки
    timed = Signal(str, object)                 # тека альбому, {шлях: секунд}

    def __init__(self):
        super().__init__()
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
            self.thumbs[path, stamp] = thumbnail(path)
        return self.thumbs[path, stamp], stamp

    def scan(self, root):
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
                picked = different_covers((c, self.thumb(c)[0]) for c in covers)
                playlist["thumb"] = mosaic([image for _path, image in picked])
                playlist["stamp"] = [path for path, _image in picked]
        self.scanned.emit(albums, playlists, folders)

    def durations(self, folder, paths):
        if shutil.which("ffprobe"):
            with ThreadPoolExecutor(4) as pool:
                self.timed.emit(folder, dict(zip(paths, pool.map(track_seconds, paths))))


# --- вигляд ------------------------------------------------------------------------------
def rounded_pixmap(pix, size, radius=12):
    pix = pix.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pix)
    p.end()
    return out


class AlbumTile(QStyledItemDelegate):
    """Плитка альбому: обкладинка, під нею назва й виконавець в один рядок кожен."""
    COVER = 128         # найменша обкладинка; AlbumGrid збільшує її під ширину панелі
    PAD = 8
    SUBTITLE = Qt.UserRole + 1
    RIPPED = Qt.UserRole + 2

    def __init__(self, parent):
        super().__init__(parent)
        self.cover = self.COVER

    def paint_disc(self, p, cover):
        """Значок альбому з диска в куті обкладинки. Намальований тут, бо значки тем різні,
        а світлий диск на темному колі видно на будь-якій обкладинці."""
        size = max(26, self.cover // 6)
        rect = QRectF(cover.right() - size - 5, cover.bottom() - size - 5, size, size)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawEllipse(rect)
        disc = QPainterPath()
        disc.addEllipse(rect.center(), size * 0.36, size * 0.36)
        disc.addEllipse(rect.center(), size * 0.1, size * 0.1)      # отвір: заливка парна-непарна
        p.fillPath(disc, QColor(240, 240, 240))

    def size(self, metrics):
        return QSize(self.cover + 2 * self.PAD, self.cover + 2 * metrics.height() + 3 * self.PAD)

    def sizeHint(self, option, _index):
        return self.size(option.fontMetrics)

    def paint(self, p, option, index):
        option.widget.style().drawPrimitive(QStyle.PE_PanelItemViewItem, option, p, option.widget)
        selected = bool(option.state & QStyle.State_Selected)
        p.save()
        rect = option.rect.adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
        cover = QRect(rect.topLeft(), QSize(self.cover, self.cover))
        index.data(Qt.DecorationRole).paint(p, cover)
        if index.data(self.RIPPED):
            self.paint_disc(p, cover)
        p.setPen(option.palette.color(QPalette.HighlightedText if selected else QPalette.Text))
        font = index.data(Qt.FontRole) or option.font
        p.setFont(font)
        line = option.fontMetrics.height()
        top = rect.top() + self.cover + self.PAD // 2
        p.drawText(QRect(rect.left(), top, rect.width(), line), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(index.data(Qt.DisplayRole), Qt.ElideRight, rect.width()))
        p.setFont(option.font)
        p.setOpacity(0.65)
        p.drawText(QRect(rect.left(), top + line, rect.width(), line), Qt.AlignLeft | Qt.AlignVCenter,
                   option.fontMetrics.elidedText(index.data(self.SUBTITLE) or "", Qt.ElideRight, rect.width()))
        p.restore()


class AlbumGrid(QListWidget):
    """Сітка плиток: уся ширина ділиться між колонками, тож збоку не лишається порожнечі."""
    GAP = 6

    def __init__(self, hint):
        super().__init__()
        self.hint = hint            # підказка плитки
        self.shown = None           # що зараз у сітці (щоб не перебудовувати даремно)
        self.tile = AlbumTile(self)
        self.setItemDelegate(self.tile)
        self.fit_tiles()

    def resizeEvent(self, event):
        self.fit_tiles()
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentItem():
            self.itemDoubleClicked.emit(self.currentItem())
        else:
            super().keyPressEvent(event)

    def fit_tiles(self):
        # Місце під смугу прокрутки відкладаємо завжди: якби воно залежало від її видимості,
        # більші плитки вмикали б смугу, вона звужувала б плитки — і навпаки, без кінця
        # (ще 2 px: якщо плитки вміщуються впритул, Qt переносить останню на новий рядок)
        width = self.width() - self.verticalScrollBar().sizeHint().width() - 2
        padding = 2 * AlbumTile.PAD + self.GAP
        cell = width // max(1, width // (AlbumTile.COVER + padding))
        cover = min(THUMB, max(AlbumTile.COVER, cell - padding))
        if cover != self.tile.cover or self.gridSize().isEmpty():
            self.tile.cover = cover
            self.setGridSize(self.tile.size(self.fontMetrics()) + QSize(self.GAP, self.GAP))
            self.doItemsLayout()


class TrackTree(QTreeWidget):
    """Список треків; у плейлісті рядки перетягуються, moved повідомляє про новий порядок."""
    moved = Signal()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.moved.emit()


class CellDelegate(QStyledItemDelegate):
    """Як у players/_tagger.py: деякі теми (Kvantum) малюють редактор комірки прозорим, тож
    комірка на час редагування малюється без тексту."""

    def __init__(self, parent):
        super().__init__(parent)
        self.edited = None

    def createEditor(self, parent, option, index):
        self.edited = (index.row(), index.column())
        return super().createEditor(parent, option, index)

    def destroyEditor(self, editor, index):
        self.edited = None
        super().destroyEditor(editor, index)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if (index.row(), index.column()) == self.edited:
            option.text = ""


class AlbumEditor(QDialog):
    """Відомості про альбом у бібліотеці: з тегів файлів, MusicBrainz або введені вручну.
    Зберігає лише мітку й cover.jpg — самі аудіофайли не змінюються, тож посилання плейлістів
    лишаються чинними. Альбом, скопійований із диска, зберігає нумерацію за диском."""
    COVER = 136
    ARTIST, TITLE, FILE = range(3)

    def __init__(self, parent, album):
        super().__init__(parent)
        self.album = album
        self.folder = album["ALBUM_DIR"]
        self.marker = read_marker(self.folder)
        self.from_disc = bool(self.marker.get("DISCID"))
        self.mbid = self.marker.get("MBID", "")
        self.cover_path = album["COVER"]
        self.new_cover = ""         # вибрана обкладинка; запишеться в cover.jpg під час збереження
        self.tmp = QTemporaryDir()
        self.releases = []
        self.setWindowTitle(_("Редагування альбому"))
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.setSpacing(14)
        col = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(self.COVER, self.COVER)
        self.preview.setAlignment(Qt.AlignCenter)
        pick = QPushButton(icon("folder-open"), _("Обкладинка"))
        pick.setToolTip(_("Вибрати обкладинку…"))
        pick.clicked.connect(self.pick_cover)
        col.addWidget(self.preview)
        col.addWidget(pick)
        col.addStretch(1)
        top.addLayout(col)

        right = QVBoxLayout()
        form = QFormLayout()
        self.f_album = QLineEdit(album["ALBUM"])
        self.f_artist = QLineEdit(album["ALBUM_ARTIST"])
        self.f_year = QLineEdit(album["YEAR"])
        self.f_year.setMaxLength(4)
        self.f_year.setMaximumWidth(80)
        form.addRow(_("Альбом:"), self.f_album)
        form.addRow(_("Виконавець альбому:"), self.f_artist)
        form.addRow(_("Рік:"), self.f_year)
        right.addLayout(form)
        row = QHBoxLayout()
        self.btn_search = QPushButton(icon("edit-find"), _("Знайти в MusicBrainz"))
        self.btn_search.clicked.connect(self.search)
        self.online = read_config().get("ONLINE", "yes") == "yes"
        self.btn_search.setEnabled(self.online)
        self.btn_apply = QPushButton(icon("dialog-ok-apply"), _("Застосувати"))
        self.btn_apply.clicked.connect(self.apply)
        self.btn_apply.hide()
        self.status = QLabel("" if self.online else _("Вимкнено в налаштуваннях (MusicBrainz)."))
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        row.addWidget(self.btn_search)
        row.addWidget(self.btn_apply)
        row.addWidget(self.status, 1)
        right.addLayout(row)
        right.addStretch(1)
        top.addLayout(right, 1)
        lay.addLayout(top)

        self.found = QTreeWidget()
        self.found.setRootIsDecorated(False)
        self.found.setUniformRowHeights(True)
        self.found.setHeaderLabels([_("Назва"), _("Виконавець"), _("Рік"), _("Країна"), _("Носій"), _("Треків")])
        self.found.header().setStretchLastSection(False)
        self.found.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.found.setColumnWidth(1, 170)
        for c in (2, 3, 4, 5):
            self.found.header().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.found.setMaximumHeight(170)
        self.found.itemActivated.connect(lambda _item: self.apply())
        self.found.hide()
        lay.addWidget(self.found)

        self.table = QTableWidget(len(album["tracks"]), 3)
        self.table.setHorizontalHeaderLabels([_("Виконавець"), _("Назва"), _("Файл")])
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Interactive)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 190)
        self.table.setColumnWidth(2, 220)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setItemDelegate(CellDelegate(self.table))
        for r, t in enumerate(album["tracks"]):
            same = t["artist"] == album["ALBUM_ARTIST"]
            self.set_row(r, "" if same else t["artist"], t["title"], os.path.basename(t["path"]))
        self.numbers = {os.path.basename(t["path"]): t["num"] for t in album["tracks"]}
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        up = QToolButton()
        up.setIcon(icon("go-up"))
        up.setToolTip(_("Вище"))
        up.clicked.connect(lambda: self.move_row(-1))
        down = QToolButton()
        down.setIcon(icon("go-down"))
        down.setToolTip(_("Нижче"))
        down.clicked.connect(lambda: self.move_row(1))
        for b in (up, down):
            b.setVisible(not self.from_disc)    # порядок диска задано самим диском
            row.addWidget(b)
        row.addStretch(1)
        buttons = QDialogButtonBox()    # не стандартні кнопки: Qt перекладає їх наново своєю мовою
        buttons.addButton(_("Зберегти"), QDialogButtonBox.AcceptRole).setDefault(True)
        buttons.addButton(_("Скасувати"), QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)

        self.resize(860, 680)
        self.show_cover(self.cover_path)
        self.btn_search.setEnabled(False)       # поки читаються теги: вони заповнюють ті самі поля
        self.background(self.on_tags, album_tags, [t["path"] for t in album["tracks"]])

    def background(self, slot, fn, *args):
        task = Task(fn, *args)
        task.done.connect(slot)
        task.start()

    def set_row(self, row, artist, title, name):
        for column, text in ((self.ARTIST, artist), (self.TITLE, title), (self.FILE, name)):
            item = QTableWidgetItem(text)
            if column == self.FILE:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, column, item)

    def cell(self, row, column):
        return self.table.item(row, column).text().strip()

    def show_cover(self, path):
        pix = QPixmap(path) if path else QPixmap()
        if pix.isNull():
            self.preview.setPixmap(QIcon.fromTheme("media-optical-audio").pixmap(96, 96))
        else:
            self.preview.setPixmap(rounded_pixmap(pix, self.COVER))

    def take_cover(self, path):
        self.new_cover = path
        self.show_cover(path)

    def pick_cover(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Вибрати обкладинку…"), self.folder,
                                                    f"{_('Зображення')} (*.jpg *.jpeg *.png *.webp)")
        if path:
            self.take_cover(path)

    def on_tags(self, tags):
        """Теги файлів — якщо альбом ще не описано; обкладинка з файлу — якщо своєї немає."""
        self.btn_search.setEnabled(self.online)
        if not tags:
            return
        if not self.cover_path and not self.new_cover:
            with_cover = next((i for i, t in enumerate(tags) if t.get("_cover")), None)
            if with_cover is not None:
                self.background(self.on_embedded_cover, embedded_cover,
                                self.album["tracks"][with_cover]["path"], self.tmp.filePath("embedded.img"))
        if any(TRACK_KEY.fullmatch(k) for k in self.marker):
            return
        first = next((t for t in tags if t.get("album")), {})
        if first.get("album"):
            self.f_album.setText(first["album"])
        artist = first.get("album_artist") or first.get("album artist") or first.get("artist")
        if artist:
            self.f_artist.setText(artist)
        year = re.match(r"\d{4}", str(first.get("date") or first.get("year") or ""))
        if year:
            self.f_year.setText(year[0])
        names = [self.cell(r, self.FILE) for r in range(self.table.rowCount())]
        rows = [(t.get("artist", ""), t.get("title") or self.cell(r, self.TITLE), names[r]) for r, t in enumerate(tags)]
        numbers = [(tag_number(t.get("disc")) or 1, tag_number(t.get("track"))) for t in tags]
        if all(n[1] for n in numbers) and len(set(numbers)) == len(numbers):
            rows = [r for _n, r in sorted(zip(numbers, rows), key=lambda x: x[0])]
        for r, (track_artist, title, name) in enumerate(rows):
            self.set_row(r, "" if track_artist == self.f_artist.text() else track_artist, title, name)

    def on_embedded_cover(self, path):
        if path and not self.new_cover:
            self.take_cover(path)

    def search(self):
        self.btn_search.setEnabled(False)
        self.btn_apply.hide()
        self.found.hide()
        self.status.setText(_("Шукаю…"))
        self.background(self.on_found, musicbrainz, "--list", self.f_artist.text().strip(),
                        self.f_album.text().strip(), str(self.table.rowCount()))

    def on_found(self, releases):
        self.btn_search.setEnabled(True)
        if releases is None:
            self.status.setText(_("Не вдалося звернутися до MusicBrainz."))
            return
        if not releases:
            self.status.setText(_("Нічого не знайдено: уточніть назву й виконавця або заповніть усе самі."))
            return
        self.releases = releases
        self.found.clear()
        for r in releases:
            item = QTreeWidgetItem([r["title"], r["artist"], r["year"], r["country"], r["format"], str(r["tracks"])])
            item.setToolTip(0, r["title"])
            self.found.addTopLevelItem(item)
        self.found.setCurrentItem(self.found.topLevelItem(0))
        self.found.show()
        self.btn_apply.show()
        self.status.setText(_("Оберіть реліз і натисніть «Застосувати». Спершу йдуть релізи з такою самою кількістю треків."))

    def apply(self):
        item = self.found.currentItem()
        if item is None or not self.btn_apply.isEnabled():
            return
        release = self.releases[self.found.indexOfTopLevelItem(item)]
        self.btn_apply.setEnabled(False)
        self.status.setText(_("Читаю реліз…"))
        self.background(self.on_release, musicbrainz, "--release", release["id"], str(self.table.rowCount()))

    def on_release(self, release):
        self.btn_apply.setEnabled(True)
        if release is None:
            self.status.setText(_("Не вдалося звернутися до MusicBrainz."))
            return
        self.mbid = release["id"]
        self.f_album.setText(release["title"])
        self.f_artist.setText(release["artist"])
        self.f_year.setText(release["year"])
        rows, tracks = self.table.rowCount(), release["tracks"]
        for r, t in enumerate(tracks[:rows]):
            self.table.item(r, self.ARTIST).setText("" if t["artist"] == release["artist"] else t["artist"])
            self.table.item(r, self.TITLE).setText(t["title"])
        self.status.setText(_("Застосовано. Перевірте, чи назви відповідають файлам.") if len(tracks) == rows else
                            _("У релізі треків: {a}, а в теці: {b}. Перевірте, чи назви відповідають файлам.",
                              a=len(tracks), b=rows))
        if release["cover"]:
            self.background(self.on_mb_cover, fetch_cover, release["id"], self.tmp.filePath("musicbrainz.jpg"))

    def on_mb_cover(self, path):
        if path:
            self.take_cover(path)

    def move_row(self, step):
        row, to = self.table.currentRow(), self.table.currentRow() + step
        if row < 0 or not 0 <= to < self.table.rowCount():
            return
        here = [self.cell(row, c) for c in range(3)]
        self.set_row(row, *[self.cell(to, c) for c in range(3)])
        self.set_row(to, *here)
        self.table.setCurrentCell(to, self.table.currentColumn())

    def save(self):
        head = {"ALBUM": self.f_album.text().strip(), "ALBUM_ARTIST": self.f_artist.text().strip(),
                "YEAR": self.f_year.text().strip()}
        if self.mbid:
            head["MBID"] = self.mbid
        rows = []
        for r in range(self.table.rowCount()):
            name = self.cell(r, self.FILE)
            key = self.numbers[name] if self.from_disc else r + 1
            rows.append((key, "" if self.from_disc else name, self.cell(r, self.ARTIST), self.cell(r, self.TITLE)))
        try:
            if self.new_cover and not QImage(self.new_cover).save(os.path.join(self.folder, "cover.jpg"), "JPG", 92):
                raise OSError(_("Не вдалося зберегти обкладинку."))
            write_marker(self.folder, head, rows)
        except OSError as e:
            QMessageBox.warning(self, _("Помилка"), _("Не вдалося записати зміни: {e}", e=e))
            return
        self.accept()


def card():
    f = QFrame()
    f.setObjectName("card")
    return f


def section(title):
    """Картка налаштувань із жирним заголовком; повертає (картка, QFormLayout для рядків)."""
    box = card()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(16, 12, 16, 14)
    lay.setSpacing(8)
    head = QLabel(title)
    head.setObjectName("section")
    lay.addWidget(head)
    form = QFormLayout()
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(8)
    lay.addLayout(form)
    return box, form


class Combo(QComboBox):
    """Коліщатко прокручує сторінку налаштувань, а не перемикає значення під курсором."""

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()


class MainWindow(QMainWindow):
    COVER = 168
    request_info = Signal()     # виклик InfoWorker.load у фоновому потоці (queued)
    request_scan = Signal(str)              # LibraryWorker.scan
    request_times = Signal(str, list)       # LibraryWorker.durations

    def __init__(self, play=False):
        super().__init__()
        self.setWindowTitle("CD Auto Runner")
        self.setWindowIcon(QIcon.fromTheme("media-optical-audio"))
        self.resize(1120, 860)
        self.info = {}              # те, що показано: диск, альбом бібліотеки або плейліст
        self.queue = {}             # те, що грає; перегляд інших альбомів його не чіпає
        self.disc = {}              # вставлений диск (показаний він чи ні)
        self.albums = []
        self.playlists = []
        self.favs = set()           # шляхи улюблених треків
        self.lib_done = -1          # скільки треків диска скопійовано (нові файли — новий перегляд)
        self.last_tracks = -1
        self.loading = False
        self.proc = None
        self.server = None
        # вбудований програвач
        self.mpv = Mpv(self) if Mpv.available() else None
        self.cur = None             # обраний трек (грає, на паузі або чекає копіювання)
        self.want = None            # трек, який ще копіюється — відтворимо, щойно буде готовий
        self.is_paused = False
        self.length = 0.0
        self.pos = 0.0
        self.seeking = False
        gui = QSettings(APP, "gui")
        self.loop = gui.value("loop", "None")            # MPRIS LoopStatus: None | Playlist | Track
        if self.loop not in LOOP_MODES:
            self.loop = "None"
        self.shuffle = gui.value("shuffle", "false") == "true"
        self.order = []             # порядок треків (перемішаний, якщо ввімкнено «Перемішувати»)
        self.mpris = None
        self.tray = None
        self.quitting = False       # «Вийти»: закриття вікна завершує програму, а не ховає її
        self.restart_lang = None    # мову змінено: main() перезапустить програму з новою мовою
        self.shut_down = False
        self.pending_play = play    # відтворити, щойно прочитано диск
        self.rip_started = 0.0

        pal = self.palette()
        muted = pal.color(QPalette.PlaceholderText).name()
        hl = pal.color(QPalette.Highlight)
        self.setStyleSheet(f"""
            QFrame#card {{ background: palette(base); border: 1px solid palette(midlight); border-radius: 12px; }}
            QLabel#title {{ font-size: 22pt; font-weight: 600; }}
            QLabel#subtitle {{ font-size: 12pt; }}
            QLabel#muted {{ color: {muted}; }}
            QLabel#badge {{ border-radius: 10px; padding: 2px 10px;
                           background: rgba({hl.red()},{hl.green()},{hl.blue()},40); color: {hl.name()}; }}
            QLabel#warn {{ border-radius: 10px; padding: 2px 10px;
                          background: rgba(246,116,0,45); color: #f67400; }}
            QPushButton {{ padding: 7px 14px; }}
            QPushButton#primary {{ font-weight: 600; padding: 8px 22px; }}
            QLabel#section {{ font-weight: 600; }}
            QSplitter::handle {{ background: transparent; }}
        """)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 8)
        outer.setSpacing(12)
        outer.addWidget(self.build_header())

        self.split = split = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(12)
        left_lay.addWidget(self.build_tracks(), 1)
        left_lay.addWidget(self.build_player())
        split.addWidget(left)
        split.addWidget(self.build_settings())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([680, 420])
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)

        self.build_statusbar()
        self.load_settings()
        self.build_tray()
        self.restore_layout()
        if self.mpv:
            self.mpris = start_mpris(self)
            self.update_player()

        self.thread = QThread(self)
        self.worker = InfoWorker()
        self.worker.moveToThread(self.thread)
        self.worker.done.connect(self.on_info)
        self.request_info.connect(self.worker.load)
        self.thread.start()

        self.lib_thread = QThread(self)
        self.lib_worker = LibraryWorker()
        self.lib_worker.moveToThread(self.lib_thread)
        self.lib_worker.scanned.connect(self.on_scanned)
        self.lib_worker.timed.connect(self.on_times)
        self.request_scan.connect(self.lib_worker.scan)
        self.request_times.connect(self.lib_worker.durations)
        self.lib_thread.start()
        self.watcher = QFileSystemWatcher(self)     # музику кладуть у теку поза програмою
        self.scan_later = QTimer(self)
        self.scan_later.setSingleShot(True)
        self.scan_later.setInterval(1500)           # копіювання теки — це багато змін поспіль
        self.scan_later.timeout.connect(self.rescan)
        self.watcher.directoryChanged.connect(lambda _path: self.scan_later.start())
        self.rescan()

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.show_empty()
        QTimer.singleShot(0, self.poll)     # перший опит — коли вікно вже на екрані

    # --- шапка: диск і головні дії ---------------------------------------------------
    def build_header(self):
        box = card()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(20)
        self.cover = QLabel()
        self.cover.setFixedSize(self.COVER, self.COVER)
        self.cover.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.cover)

        col = QVBoxLayout()
        col.setSpacing(6)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setWordWrap(True)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("subtitle")
        self.meta = QLabel()
        self.meta.setObjectName("muted")
        self.badge = QLabel()
        self.badge.setObjectName("badge")
        meta_row = QHBoxLayout()
        meta_row.addWidget(self.meta)
        meta_row.addSpacing(8)
        meta_row.addWidget(self.badge)
        meta_row.addStretch(1)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        col.addLayout(meta_row)
        col.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_play = QPushButton(icon("media-playback-start"), _("Відтворити"))
        self.btn_play.setObjectName("primary")
        self.btn_play.setDefault(True)
        self.btn_rip = QPushButton(icon("media-import-audio-cd", "document-save"),
                                   _("Скопіювати в бібліотеку"))
        self.btn_tag = QPushButton(icon("document-edit"), _("Ввести назви"))
        self.btn_stop = QPushButton(icon("media-playback-stop"), _("Зупинити"))
        for b in (self.btn_play, self.btn_rip, self.btn_tag, self.btn_stop):
            b.setIconSize(QSize(20, 20))
            buttons.addWidget(b)
        self.btn_play.clicked.connect(self.on_play)
        self.btn_rip.clicked.connect(lambda: self.action("rip"))
        self.btn_tag.clicked.connect(self.on_tag)
        self.btn_stop.clicked.connect(lambda: self.action("stop"))

        more = QToolButton()
        more.setIcon(icon("application-menu", "open-menu-symbolic"))
        if more.icon().isNull():
            more.setText("⋯")
        more.setToolTip(_("Ще"))
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        self.act_album = menu.addAction(QIcon.fromTheme("folder-music"), _("Відкрити теку альбому"),
                                        lambda: self.open_dir(self.info.get("LIBRARY_DIR", "")))
        menu.addAction(QIcon.fromTheme("folder-music"), _("Відкрити бібліотеку музики"),
                       lambda: self.open_dir(self.library_root()))
        self.act_mb = menu.addAction(QIcon.fromTheme("internet-web-browser"), _("Додати диск у MusicBrainz"),
                                     lambda: QDesktopServices.openUrl(QUrl(self.info.get("MB_URL", ""))))
        menu.addSeparator()
        self.act_eject = menu.addAction(icon("media-eject"), _("Вийняти диск"), self.eject)
        menu.aboutToShow.connect(lambda: self.act_eject.setEnabled(self.last_tracks > 0))
        menu.addAction(icon("view-refresh"), _("Оновити"), self.reload_info)
        menu.addAction(icon("edit-clear-history"), _("Видалити тимчасові файли"),
                       lambda: self.action("clean"))
        menu.addSeparator()
        menu.addAction(icon("help-about"), _("Про програму"), self.about)
        more.setMenu(menu)
        buttons.addStretch(1)
        buttons.addWidget(more)
        col.addLayout(buttons)
        lay.addLayout(col, 1)
        return box

    # --- список треків ------------------------------------------------------------------
    def build_tracks(self):
        box = card()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(4, 4, 4, 4)
        self.tree = TrackTree()
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setDefaultDropAction(Qt.MoveAction)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_tracks_menu)
        # чергою: дані перебудовуються вже після того, як Qt закінчить перетягування
        self.tree.moved.connect(self.on_tracks_moved, Qt.QueuedConnection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setFrameShape(QFrame.NoFrame)
        self.tree.setHeaderLabels(["№", _("Виконавець"), _("Назва"), _("Час"), _("Стан")])
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tree.setColumnWidth(1, 180)
        self.tree.itemDoubleClicked.connect(self.on_track_activated)
        lay.addWidget(self.tree)
        return box

    # --- вбудований програвач ----------------------------------------------------------
    def build_player(self):
        box = card()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(4)

        def tool(name, tip, slot):
            b = QToolButton()
            b.setIcon(icon(name))
            b.setIconSize(QSize(22, 22))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b
        self.p_prev = tool("media-skip-backward", _("Попередній трек"), self.prev_track)
        self.p_play = tool("media-playback-start", _("Відтворити / пауза"), self.toggle_play)
        self.p_stop = tool("media-playback-stop", _("Зупинити відтворення"), self.stop_playback)
        self.p_next = tool("media-skip-forward", _("Наступний трек"), self.next_track)
        self.p_play.setIconSize(QSize(28, 28))
        row.addSpacing(4)
        self.p_shuffle = tool("media-playlist-shuffle", _("Перемішувати"), lambda: self.set_shuffle(not self.shuffle))
        self.p_loop = tool("media-playlist-repeat", "", self.cycle_loop)
        self.p_fav = tool("", _("Додати до улюбленого"), self.on_favorite)
        self.p_fav.setIcon(heart_icon())
        for b in (self.p_shuffle, self.p_loop, self.p_fav):
            b.setCheckable(True)
        row.addSpacing(8)
        self.now = QLabel()
        self.now.setTextFormat(Qt.PlainText)
        self.now.setMinimumWidth(80)
        row.addWidget(self.now, 1)
        vol_icon = QLabel()
        vol_icon.setPixmap(icon("audio-volume-high").pixmap(16, 16))
        vol_icon.setToolTip(_("Гучність"))
        row.addWidget(vol_icon)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setFixedWidth(110)
        self.vol.setToolTip(_("Гучність"))
        vol = QSettings(APP, "gui").value("volume", 100)
        self.vol.setValue(int(vol) if str(vol).isdigit() else 100)
        self.vol.valueChanged.connect(self.on_volume)
        row.addWidget(self.vol)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.t_pos = QLabel("0:00")
        self.t_pos.setObjectName("muted")
        self.t_len = QLabel("0:00")
        self.t_len.setObjectName("muted")
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderPressed.connect(lambda: setattr(self, "seeking", True))
        self.seek.sliderReleased.connect(self.on_seek)
        row2.addWidget(self.t_pos)
        row2.addWidget(self.seek, 1)
        row2.addWidget(self.t_len)
        lay.addLayout(row2)

        if self.mpv:
            self.mpv.volume = self.vol.value()
            self.mpv.position.connect(self.on_position)
            self.mpv.duration.connect(self.on_duration)
            self.mpv.paused.connect(self.on_paused)
            self.mpv.ended.connect(self.on_ended)
            self.mpv.failed.connect(self.on_mpv_failed)
        self.update_player()
        return box

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
            self.statusBar().showMessage(_("Запускаю {name}…", name=read_config().get("PLAYER_NAME", "")), 5000)
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
        import time
        if not self.queue.get("DEVICE") or time.monotonic() - self.rip_started < 30 or self.rip_running():
            return
        self.rip_started = time.monotonic()
        QProcess.startDetached(self_bin(), ["play", "--player", "builtin", "--no-window", self.queue["DEVICE"]])

    def play_track(self, n):
        tracks = self.queue.get("tracks", [])
        if not self.mpv or not tracks or not 1 <= n <= len(tracks):
            return
        if tracks[n - 1].get("missing"):
            self.statusBar().showMessage(_("Файлу треку {n} більше немає.", n=n), 5000)
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
            sel = self.tree.currentItem()
            if sel:
                self.start_track(self.tree.indexOfTopLevelItem(sel) + 1)
            else:
                self.adopt()
                self.start_track(self.first_track())
        elif self.want is None:
            self.mpv.toggle()

    # --- порядок відтворення: перемішування і повтор ---
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
        QSettings(APP, "gui").setValue("shuffle", "true" if self.shuffle else "false")
        self.order = self.new_order(self.playable(self.queue))
        self.update_player()

    def set_loop(self, mode):
        if mode in LOOP_MODES:
            self.loop = mode
            QSettings(APP, "gui").setValue("loop", mode)
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
        if self.want is None and self.seek.value() > 3:
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

    def on_track_activated(self, item, _col=0):
        if self.info.get("tracks") and (self.mpv or not self.plays_here()):
            self.start_track(self.tree.indexOfTopLevelItem(item) + 1)
        elif not self.album_open():
            self.action("tag", reload=True)

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
                if not self.isVisible():
                    self.announce_play()
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

    def on_position(self, sec):
        self.pos = sec
        if not self.seeking:
            self.seek.setValue(int(sec))
        self.t_pos.setText(fmt_time(sec))

    def on_duration(self, sec):
        self.length = sec
        self.seek.setRange(0, int(sec))
        self.t_len.setText(fmt_time(sec))
        if self.mpris:
            self.mpris.refresh()

    def on_paused(self, paused):
        self.is_paused = paused
        self.update_player()

    def on_seek(self):
        self.seeking = False
        self.seek_to(self.seek.value())

    def on_volume(self, value):
        QSettings(APP, "gui").setValue("volume", value)
        if self.mpv:
            self.mpv.set_volume(value)
        if self.mpris:
            self.mpris.refresh()

    def on_ended(self, reason):
        if reason == "eof" and self.cur is not None and self.want is None:
            n = self.cur if self.loop == "Track" else self.neighbor(1)
            if n is not None:
                self.play_track(n)
            else:
                self.stop_playback()
        elif reason == "error" and self.cur is not None:
            self.statusBar().showMessage(_("Не вдалося відтворити трек {n}.", n=self.cur), 5000)
            self.stop_playback()
        elif reason == "quit":
            self.stop_playback()

    def on_mpv_failed(self):
        self.stop_playback()
        QMessageBox.warning(self, _("Помилка"), _("Не вдалося запустити mpv."))

    def update_player(self):
        on = self.mpv is not None and bool(self.player_info().get("tracks"))
        for b in (self.p_prev, self.p_play, self.p_stop, self.p_next, self.seek):
            b.setEnabled(on)
        self.vol.setEnabled(self.mpv is not None)
        self.p_shuffle.setEnabled(self.mpv is not None)
        self.p_loop.setEnabled(self.mpv is not None)
        link = self.track_link(self.cur, self.queue) if self.cur is not None else None
        favorite = link is not None and link[0] in self.favs
        self.p_fav.setEnabled(link is not None)
        self.p_fav.setChecked(favorite)
        self.p_fav.setToolTip(_("Прибрати з улюбленого") if favorite else _("Додати до улюбленого"))
        self.p_shuffle.setChecked(self.shuffle)
        loop_icon, loop_tip = LOOP_MODES[self.loop]
        self.p_loop.setChecked(self.loop != "None")
        self.p_loop.setIcon(icon(loop_icon))
        self.p_loop.setToolTip(_(loop_tip))
        playing = self.cur is not None and self.want is None and not self.is_paused
        self.p_play.setIcon(icon("media-playback-pause" if playing else "media-playback-start"))
        if not self.mpv:
            self.now.setText(_("Для вбудованого програвача встановіть mpv (пакет mpv)."))
        elif self.cur is None:
            self.now.setText(_("Нічого не відтворюється"))
        elif self.want is not None:
            self.now.setText(_("Чекаю, поки скопіюється трек {n}…", n=self.want))
        else:
            t = self.track_title(self.cur) or {}
            text = f"{t.get('num', self.cur):02d}. {t.get('title', '')}"
            if t.get("artist") and t.get("artist") != self.queue.get("ALBUM_ARTIST"):
                text += f" — {t['artist']}"
            if self.is_paused:
                text += f"  ({_('Пауза')})"
            self.now.setText(text)
        self.mark_playing()
        if self.tray:
            self.tray.setToolTip(f"CD Auto Runner\n{self.now.text()}")
        if self.mpris:
            self.mpris.refresh()

    def mark_playing(self):
        bold = QFont(self.tree.font())
        bold.setBold(True)
        normal = QFont(self.tree.font())
        here = self.showing_queue()     # у чужому альбомі трек із тим самим номером не грає
        for idx in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(idx)
            current = here and self.cur == idx + 1
            for c in (0, 2, 3):
                item.setFont(c, bold if current else normal)
            if not current:
                item.setIcon(0, QIcon())
            elif self.want is not None:
                item.setIcon(0, icon("chronometer", "media-record"))
            else:
                item.setIcon(0, icon("media-playback-pause" if self.is_paused else "media-playback-start"))

    # --- налаштування ----------------------------------------------------------------------
    def build_settings(self):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        g1, f1 = section(_("Відтворення"))
        self.player = Combo()
        self.player.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.player.setMinimumContentsLength(18)
        self.player.activated.connect(self.on_player)
        f1.addRow(_("Програвач:"), self.player)
        self.chk_service = QCheckBox(_("Автозапуск при вставлянні диска"))
        self.chk_service.clicked.connect(self.on_service)
        self.chk_notify = QCheckBox(_("Сповіщення"))
        self.chk_notify.clicked.connect(lambda v: self.set_key("NOTIFY", v))
        f1.addRow(self.chk_service)
        f1.addRow(self.chk_notify)
        lay.addWidget(g1)

        g2, f2 = section(_("Копіювання і бібліотека"))
        self.fmt = Combo()
        for key, text in (("flac", "FLAC — без втрат"), ("opus", "Opus 160 кбіт/с — малий розмір"),
                          ("ogg", "Ogg Vorbis q6"), ("mp3", "MP3 VBR ~190 кбіт/с"),
                          ("wav", "WAV — без перекодування")):
            self.fmt.addItem(_(text), key)
        self.fmt.activated.connect(lambda _i: self.set_value("RIP_FORMAT", self.fmt.currentData()))
        f2.addRow(_("Формат:"), self.fmt)
        self.chk_library = QCheckBox(_("Зберігати альбоми в бібліотеку музики"))
        self.chk_library.clicked.connect(lambda v: self.set_key("LIBRARY", v))
        f2.addRow(self.chk_library)
        row = QHBoxLayout()
        self.libdir = QLabel()
        self.libdir.setObjectName("muted")
        self.libdir.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.libdir.setWordWrap(True)
        change = QPushButton(icon("folder-open"), _("Змінити…"))
        change.clicked.connect(self.on_libdir)
        reset = QPushButton(_("Типова"))
        reset.clicked.connect(lambda: self.set_value("LIBRARY_DIR", ""))
        row.addWidget(self.libdir, 1)
        row.addWidget(change)
        row.addWidget(reset)
        f2.addRow(_("Тека:"), row)
        self.chk_online = QCheckBox(_("Брати назви й обкладинки з MusicBrainz"))
        self.chk_online.clicked.connect(lambda v: self.set_key("ONLINE", v))
        f2.addRow(self.chk_online)
        note = QLabel(_("Формат і бібліотека стосуються вбудованого програвача, програвачів, яким треки копіюються (Elisa, QMPlay2, Audacious), і кнопки «Скопіювати в бібліотеку»."))
        note.setObjectName("muted")
        note.setWordWrap(True)
        f2.addRow(note)
        lay.addWidget(g2)

        g3, f3 = section(_("Інтерфейс"))
        self.lang = Combo()
        self.lang.addItem("English", "en")
        self.lang.addItem("Українська", "uk")
        self.lang.setCurrentIndex(self.lang.findData(LANG))
        self.lang.activated.connect(self.on_lang)
        f3.addRow(_("Мова:"), self.lang)
        self.chk_tray = QCheckBox(_("Згортати в системний лоток під час закриття вікна"))
        self.chk_tray.setChecked(QSettings(APP, "gui").value("tray", "true") in (True, "true"))
        self.chk_tray.setEnabled(QSystemTrayIcon.isSystemTrayAvailable())
        self.chk_tray.clicked.connect(self.on_tray_option)
        f3.addRow(self.chk_tray)
        self.chk_quiet = QCheckBox(_("Вставлений диск відтворювати у лотку, не відкриваючи вікна"))
        self.chk_quiet.setChecked(QSettings(APP, "gui").value("play_in_tray", "false") == "true")
        self.chk_quiet.setEnabled(self.chk_tray.isEnabled() and self.chk_tray.isChecked())
        self.chk_quiet.clicked.connect(lambda v: QSettings(APP, "gui").setValue("play_in_tray", "true" if v else "false"))
        f3.addRow(self.chk_quiet)
        lay.addWidget(g3)
        lay.addWidget(self.build_library(), 1)
        area.setWidget(inner)
        area.setMinimumWidth(360)
        return area

    # --- бібліотека: відкрити скопійований диск --------------------------------------------
    def album_grid(self, empty_text, hint):
        """Сторінка вкладки: сітка плиток і підпис на випадок, коли їх немає."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        grid = AlbumGrid(hint)
        grid.setFrameShape(QFrame.NoFrame)
        grid.setViewMode(QListView.IconMode)
        grid.setMovement(QListView.Static)
        grid.setResizeMode(QListView.Adjust)
        grid.setUniformItemSizes(True)
        grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        grid.setVerticalScrollMode(QListView.ScrollPerPixel)
        grid.verticalScrollBar().setSingleStep(24)
        grid.setMinimumHeight(grid.tile.size(grid.fontMetrics()).height() + 12)
        # окремо, а не itemActivated: той за налаштуванням KDE спрацьовує й від одного кліку
        grid.itemClicked.connect(lambda item: self.show_tile(item.data(Qt.UserRole)))
        grid.itemDoubleClicked.connect(self.on_library_item)
        grid.setContextMenuPolicy(Qt.CustomContextMenu)
        grid.customContextMenuRequested.connect(lambda pos: self.on_tile_menu(grid, pos))
        empty = QLabel(empty_text)
        empty.setObjectName("muted")
        empty.setWordWrap(True)
        grid.empty = empty
        lay.addWidget(empty)
        lay.addWidget(grid, 1)
        return page, grid

    def build_library(self):
        box = card()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 8, 16, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.lib_tabs = QTabBar()
        self.lib_tabs.addTab(_("Бібліотека"))
        self.lib_tabs.addTab(_("Плейлісти"))
        self.lib_tabs.setDrawBase(False)
        self.lib_tabs.setExpanding(False)
        self.lib_add = QToolButton()
        self.lib_add.setAutoRaise(True)
        self.lib_add.clicked.connect(self.on_lib_add)
        head.addWidget(self.lib_tabs)
        head.addStretch(1)
        head.addWidget(self.lib_add)
        lay.addLayout(head)
        page, self.lib_list = self.album_grid(_("Тут з'являтимуться скопійовані диски."),
                                              _("Двічі клацніть альбом, щоб відтворити його."))
        lists, self.list_grid = self.album_grid(
            _("Плейлістів ще немає: створіть перший кнопкою «+» або додайте до нього треки через контекстне меню."),
            _("Двічі клацніть плейліст, щоб відтворити його."))
        self.lib_pages = QStackedWidget()
        self.lib_pages.addWidget(page)
        self.lib_pages.addWidget(lists)
        lay.addWidget(self.lib_pages, 1)
        self.lib_tabs.currentChanged.connect(self.on_lib_tab)
        tab = QSettings(APP, "gui").value("library_tab", 0)
        self.lib_tabs.setCurrentIndex(int(tab) if str(tab).isdigit() else 0)
        self.on_lib_tab(self.lib_tabs.currentIndex())
        return box

    def on_lib_tab(self, index):
        self.lib_pages.setCurrentIndex(index)
        QSettings(APP, "gui").setValue("library_tab", index)
        if index:
            self.lib_add.setIcon(icon("list-add"))
            self.lib_add.setToolTip(_("Новий плейліст"))
        else:
            self.lib_add.setIcon(icon("folder-open"))
            self.lib_add.setToolTip(_("Покладіть теку з музикою в бібліотеку — альбом з'явиться тут"))

    def on_lib_add(self):
        if self.lib_tabs.currentIndex():
            self.new_playlist()
        else:
            self.open_dir(self.library_root())

    def rescan(self):
        self.request_scan.emit(self.library_root())

    def on_scanned(self, albums, playlists, folders):
        self.albums, self.playlists = albums, playlists
        self.load_favorites()
        known, now = set(self.watcher.directories()), set(folders)
        if known - now:
            self.watcher.removePaths(list(known - now))
        if now - known:
            self.watcher.addPaths(list(now - known))
        if self.playlist_open():        # обкладинка плейліста складається з його треків
            self.set_cover(self.info["COVER"], self.playlist_image())
        self.fill_library()
        self.update_player()

    def fill_library(self):
        """Плитки: вставлений диск (якщо є) і скопійовані альбоми; відкрите зараз — жирним."""
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
        self.fill_grid(self.lib_list, rows, thumbs, current)
        rows, thumbs = [], {}
        for p in self.playlists:
            count = _("треків: {n}", n=len(p["tracks"]))
            favorite = os.path.basename(p["PLAYLIST"]) == FAVORITES + PLAYLIST_EXT
            rows.append((p["PLAYLIST"], p["ALBUM"], count, p["COVER"], "", p["stamp"],
                         "" if favorite else "view-media-playlist", False))
            thumbs[p["PLAYLIST"]] = p["thumb"]
        self.fill_grid(self.list_grid, rows, thumbs, current)

    def fill_grid(self, grid, rows, thumbs, current):
        if (rows, current) == grid.shown:
            return
        grid.shown = (rows, current)
        bar = grid.verticalScrollBar()
        scroll = bar.value()
        grid.clear()
        bold = QFont(grid.font())
        bold.setBold(True)
        for key, title, sub, cover, more, _stamp, fallback, ripped in rows:
            item = QListWidgetItem(title)
            item.setData(AlbumTile.SUBTITLE, sub)
            item.setData(AlbumTile.RIPPED, ripped)
            image = thumbs.get(key) if key else thumbnail(cover) if cover else None
            if image and not image.isNull():
                item.setIcon(QIcon(rounded_pixmap(QPixmap.fromImage(image), THUMB, 24)))
            else:
                item.setIcon(QIcon.fromTheme(fallback) if fallback else heart_icon())
            item.setData(Qt.UserRole, key)
            hint = "\n".join(x for x in (title, sub if not key or not more else "", more) if x)
            item.setToolTip(f"{hint}\n{grid.hint}")
            if key == current:
                item.setFont(bold)
            grid.addItem(item)
        bar.setValue(scroll)
        # плейліст «Улюблене» є завжди, тож підпис потрібен, поки немає інших
        grid.empty.setVisible(len(rows) < 2 if grid is self.list_grid else not rows)
        grid.setVisible(bool(rows))

    def on_library_item(self, item):
        self.play_tile(item.data(Qt.UserRole))

    def play_tile(self, folder):
        if self.show_tile(folder):
            self.on_play()

    def open_album(self, folder):
        """Показує альбом або плейліст замість диска; диск лишається в приводі й копіюється далі,
        а те, що грає, грає далі. Альбом, який грає, відкривається тим самим об'єктом."""
        playing = self.cur is not None and self.queue.get("ALBUM_DIR") == folder
        album = self.queue if playing else read_entry(folder, self.library_root())
        if not album:
            self.statusBar().showMessage(_("Не вдалося відкрити альбом."), 5000)
            self.rescan()
            return False
        self.pending_play = False
        self.info = album
        self.show_disc()
        self.update_states()
        self.request_times.emit(folder, [t["path"] for t in album["tracks"]])
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
        self.request_times.emit(folder, [t["path"] for t in album["tracks"]])
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
            for idx, t in enumerate(self.info["tracks"]):
                item = self.tree.topLevelItem(idx)
                if item and t["sec"]:
                    item.setText(3, fmt_time(t["sec"]))
            self.show_meta()

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
                self.request_times.emit(key, [t["path"] for t in fresh["tracks"]])
        self.update_player()

    # --- плейлісти -------------------------------------------------------------------------
    def load_favorites(self):
        self.favs = {path for path, _label in read_m3u(favorites_path(self.library_root()))}

    def track_link(self, n, info):
        """(файл, підпис) треку для плейліста; None — файлу в бібліотеці немає (ще не скопійовано)."""
        t = self.track_title(n, info)
        if not t or t.get("missing"):
            return None
        path = t.get("path") or self.library_file(n, info)
        return (os.path.normpath(path), track_label(t)) if path else None

    def selected_tracks(self):
        return sorted(self.tree.indexOfTopLevelItem(i) + 1 for i in self.tree.selectedItems())

    def store_playlist(self, path, entries):
        """Записує плейліст і оновлює все, що його показує."""
        try:
            write_m3u(path, entries)
        except OSError as e:
            QMessageBox.warning(self, _("Помилка"), _("Не вдалося записати зміни: {e}", e=e))
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
            self.statusBar().showMessage(_("Ці треки вже є в плейлісті."), 4000)
        elif self.store_playlist(path, entries + new):
            self.statusBar().showMessage(_("Додано треків: {n}", n=len(new)), 4000)

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

    def ask_playlist_name(self, title, text=""):
        """Шлях для плейліста з назвою, яку ввели; None — скасовано або назва зайнята."""
        name, ok = QInputDialog.getText(self, title, _("Назва плейліста:"), text=text)
        name = safe_name(name) if ok else ""
        if not name:
            return None
        path = os.path.join(playlists_dir(self.library_root()), name + PLAYLIST_EXT)
        if os.path.exists(path) or path == favorites_path(self.library_root()):
            QMessageBox.warning(self, _("Помилка"), _("Плейліст із такою назвою вже є."))
            return None
        return path

    def new_playlist(self, links=()):
        path = self.ask_playlist_name(_("Новий плейліст"))
        if path and self.store_playlist(path, list({link[0]: link for link in links}.values())):
            self.lib_tabs.setCurrentIndex(1)

    def rename_playlist(self, path):
        new = self.ask_playlist_name(_("Перейменувати плейліст"), playlist_name(path))
        if not new:
            return
        cover = os.path.splitext(path)[0] + ".jpg"
        try:
            os.rename(path, new)
            if os.path.isfile(cover):
                os.rename(cover, os.path.splitext(new)[0] + ".jpg")
        except OSError as e:
            QMessageBox.warning(self, _("Помилка"), _("Не вдалося записати зміни: {e}", e=e))
            return
        for info in (self.info, self.queue):
            if info.get("PLAYLIST") == path:
                info["ALBUM_DIR"] = info["PLAYLIST"] = new
        self.reload_entry(new)
        self.rescan()

    def delete_playlist(self, path):
        if QMessageBox.question(self, _("Видалити плейліст…"), _("Видалити плейліст «{name}»? Самі треки залишаться в бібліотеці.",
                                                                 name=playlist_name(path))) != QMessageBox.Yes:
            return
        for file in (path, os.path.splitext(path)[0] + ".jpg"):
            try:
                os.remove(file)
            except FileNotFoundError:
                pass
            except OSError as e:
                QMessageBox.warning(self, _("Помилка"), _("Не вдалося записати зміни: {e}", e=e))
                return
        if self.queue.get("PLAYLIST") == path:
            self.stop_playback()
            self.queue = {}
        if self.playlist_open() == path:
            self.close_album()
        self.rescan()

    def set_playlist_cover(self, path):
        image, _filter = QFileDialog.getOpenFileName(self, _("Вибрати обкладинку…"), self.library_root(),
                                                     f"{_('Зображення')} (*.jpg *.jpeg *.png *.webp)")
        if not image:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not QImage(image).save(os.path.splitext(path)[0] + ".jpg", "JPG", 92):
            QMessageBox.warning(self, _("Помилка"), _("Не вдалося зберегти обкладинку."))
            return
        self.after_cover(path)

    def remove_playlist_cover(self, path):
        try:
            os.remove(os.path.splitext(path)[0] + ".jpg")
        except OSError:
            pass
        self.after_cover(path)

    def after_cover(self, path):
        self.reload_entry(path)
        self.rescan()

    def playlist_image(self):
        """Складена з треків обкладинка показаного плейліста, якщо власної немає."""
        key = self.playlist_open()
        if not key or self.info.get("COVER"):
            return None
        return next((p["thumb"] for p in self.playlists if p["PLAYLIST"] == key), None)

    def save_order(self, tracks, selected=()):
        """Новий порядок треків показаного плейліста; selected — які рядки лишити виділеними."""
        if self.store_playlist(self.playlist_open(), [(t["path"], track_label(t)) for t in tracks]):
            for t in self.info["tracks"]:
                if t["path"] in selected:
                    self.tree.topLevelItem(t["n"] - 1).setSelected(True)

    def on_tracks_moved(self):
        """Рядки перетягнули: нумерація в дереві ще стара, тож номер у рядку веде до треку."""
        tracks = self.info.get("tracks", [])
        if self.playlist_open() and self.tree.topLevelItemCount() == len(tracks):
            moved = {tracks[i.data(0, Qt.UserRole) - 1]["path"] for i in self.tree.selectedItems()}
            count = self.tree.topLevelItemCount()
            self.save_order([tracks[self.tree.topLevelItem(i).data(0, Qt.UserRole) - 1] for i in range(count)], moved)

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

    def add_menu(self, menu, links):
        """Підменю «Додати до плейліста» і дія улюбленого для цих треків."""
        names = [(p["ALBUM"], p["PLAYLIST"]) for p in self.playlists[1:]]
        sub = menu.addMenu(icon("list-add"), _("Додати до плейліста"))
        sub.setEnabled(bool(links))
        for name, path in names:
            sub.addAction(icon("view-media-playlist"), name.replace("&", "&&"),
                          lambda p=path: self.add_to_playlist(p, links))
        if names:
            sub.addSeparator()
        sub.addAction(icon("document-new"), _("Новий плейліст…"), lambda: self.new_playlist(links))
        favorite = bool(links) and {link[0] for link in links} <= self.favs
        if not self.is_favorites_open():
            act = menu.addAction(heart_icon(), _("Прибрати з улюбленого") if favorite else _("Додати до улюбленого"),
                                 lambda: self.toggle_favorite(links))
            act.setEnabled(bool(links))

    def is_favorites_open(self):
        return self.playlist_open() == favorites_path(self.library_root())

    def on_tracks_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.tree.setCurrentItem(item)
        chosen = self.selected_tracks()
        links = [link for link in (self.track_link(n, self.info) for n in chosen) if link]
        menu = QMenu(self)
        menu.addAction(icon("media-playback-start"), _("Відтворити"), lambda: self.start_track(chosen[0]))
        self.add_menu(menu, links)
        if not links:
            menu.setToolTipsVisible(True)
            menu.actions()[1].setToolTip(_("Спершу дочекайтеся, поки трек скопіюється в бібліотеку."))
        if self.playlist_open():
            menu.addSeparator()
            up = menu.addAction(icon("go-up"), _("Вище"), lambda: self.move_tracks(-1))
            down = menu.addAction(icon("go-down"), _("Нижче"), lambda: self.move_tracks(1))
            up.setEnabled(chosen[0] > 1)
            down.setEnabled(chosen[-1] < self.tree.topLevelItemCount())
            menu.addAction(icon("list-remove"), _("Прибрати з плейліста"), self.remove_tracks)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def on_tile_menu(self, grid, pos):
        item = grid.itemAt(pos)
        key = item.data(Qt.UserRole) if item else ""
        if not key:
            return
        menu = QMenu(self)
        menu.addAction(icon("media-playback-start"), _("Відтворити"), lambda: self.play_tile(key))
        menu.addAction(icon("document-open"), _("Відкрити"), lambda: self.show_tile(key))
        if is_playlist(key):
            if os.path.basename(key) != FAVORITES + PLAYLIST_EXT:
                menu.addAction(icon("edit-rename"), _("Перейменувати…"), lambda: self.rename_playlist(key))
            menu.addAction(icon("view-preview"), _("Вибрати обкладинку…"), lambda: self.set_playlist_cover(key))
            if os.path.isfile(os.path.splitext(key)[0] + ".jpg"):
                menu.addAction(icon("edit-clear"), _("Прибрати обкладинку"), lambda: self.remove_playlist_cover(key))
            if os.path.basename(key) != FAVORITES + PLAYLIST_EXT:
                menu.addSeparator()
                menu.addAction(icon("edit-delete"), _("Видалити плейліст…"), lambda: self.delete_playlist(key))
        else:
            album = next((a for a in self.albums if a["ALBUM_DIR"] == key), None)
            tracks = album["tracks"] if album else []
            self.add_menu(menu, [(os.path.normpath(t["path"]), track_label(t)) for t in tracks])
            menu.addSeparator()
            menu.addAction(icon("document-edit"), _("Редагувати альбом…"), lambda: self.edit_album(key))
            menu.addAction(QIcon.fromTheme("folder-music"), _("Відкрити теку альбому"), lambda: self.open_dir(key))
        menu.exec(grid.viewport().mapToGlobal(pos))

    def show_tile(self, key):
        """Показує плитку; те, що грає, грає далі. False — альбому вже немає."""
        if key == self.info.get("ALBUM_DIR", ""):
            return True
        if key:
            return self.open_album(key)
        self.open_disc()
        return True

    def edit_album(self, folder):
        album = read_album(folder, self.library_root())
        if not album:
            self.statusBar().showMessage(_("Не вдалося відкрити альбом."), 5000)
            self.rescan()
            return
        dialog = AlbumEditor(self, album)
        saved = dialog.exec() == QDialog.Accepted
        dialog.deleteLater()
        if saved:
            # назви могли змінитися й у плейлісті, що показаний або грає
            for key in {self.info.get("ALBUM_DIR"), self.queue.get("ALBUM_DIR")} - {None}:
                self.reload_entry(key)
            self.rescan()

    def on_tag(self):
        if self.album_open():
            self.edit_album(self.info["ALBUM_DIR"])
        else:
            self.action("tag", reload=True)

    def build_statusbar(self):
        sb = self.statusBar()
        self.svc_icon = QLabel()
        self.svc_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.setTextVisible(True)
        self.progress.hide()
        self.prog_label = QLabel()
        sb.addWidget(self.svc_icon)
        sb.addWidget(self.svc_label)
        sb.addWidget(QLabel("   "))
        sb.addWidget(self.prog_label, 1)
        sb.addPermanentWidget(self.progress)
        self.version = script_version()
        footer = QLabel(f"CD Auto Runner {self.version}")
        footer.setObjectName("muted")
        sb.addPermanentWidget(footer)

    # --- налаштування: читання й запис --------------------------------------------------
    def library_root(self):
        d = read_config().get("LIBRARY_DIR", "")
        if not d:
            try:
                d = subprocess.run(["xdg-user-dir", "MUSIC"], capture_output=True, text=True).stdout.strip()
            except OSError:
                d = ""
        return d if d and d != os.path.expanduser("~") else os.path.expanduser("~/Music")

    def load_settings(self):
        cfg = read_config()
        code, out, _err = run("list")
        self.player.blockSignals(True)
        self.player.clear()
        self.player_names = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                self.player.addItem(parts[1], parts[0])
                self.player_names[parts[0]] = parts[1]
        if cfg.get("PLAYER_ID") == "custom":
            self.player.addItem(_("Власна команда"), "custom")
        self.player.addItem(_("Нічого не запускати"), "off")
        i = self.player.findData(cfg.get("PLAYER_ID", ""))
        self.player.setCurrentIndex(max(i, 0))
        self.player.blockSignals(False)
        self.fmt.setCurrentIndex(max(self.fmt.findData(cfg.get("RIP_FORMAT", "flac")), 0))
        self.chk_library.setChecked(cfg.get("LIBRARY", "yes") == "yes")
        self.chk_online.setChecked(cfg.get("ONLINE", "yes") == "yes")
        self.chk_notify.setChecked(cfg.get("NOTIFY", "yes") == "yes")
        self.libdir.setText(cfg.get("LIBRARY_DIR") or f"{self.library_root()}  ({_('системна тека «Музика»')})")
        self.update_service()

    def set_value(self, key, value):
        code, _o, err = run("set", key, value)
        if code:
            QMessageBox.warning(self, _("Помилка"), err.strip() or _("Не вдалося виконати дію."))
        else:
            self.statusBar().showMessage(_("Збережено"), 2500)
        self.load_settings()
        if key == "LIBRARY_DIR":
            self.rescan()

    def set_key(self, key, checked):
        self.set_value(key, "yes" if checked else "no")

    def on_player(self, _index):
        pid = self.player.currentData()
        if pid not in ("off", "custom"):
            _c, out, _e = run("perm", pid)
            if out.strip():
                arg, fid = out.strip().split("\t", 1)
                name = self.player.currentText()
                if QMessageBox.question(self, _("Потрібен дозвіл"),
                                        _("{name} встановлено як Flatpak, і йому бракує дозволу:\n\nflatpak override --user {arg} {fid}\n\nНадати?",
                                          name=name, arg=arg, fid=fid)) == QMessageBox.Yes:
                    subprocess.run(["flatpak", "override", "--user", arg, fid])
        if pid != "custom":
            code, _o, err = run("set-player", pid)
            if code:
                QMessageBox.warning(self, _("Помилка"), err.strip())
            else:
                self.statusBar().showMessage(_("Збережено"), 2500)
        self.load_settings()

    def on_libdir(self):
        d = QFileDialog.getExistingDirectory(self, _("Тека бібліотеки музики"), self.library_root())
        if d:
            self.set_value("LIBRARY_DIR", d)

    def on_service(self, checked):
        run("enable" if checked else "disable")
        self.update_service()

    # --- системний лоток ----------------------------------------------------------------
    def build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon.fromTheme("media-optical-audio"), self)
        self.tray.setToolTip("CD Auto Runner")
        menu = QMenu(self)
        menu.addAction(QIcon.fromTheme("media-optical-audio"), _("Показати / сховати вікно"), self.toggle_window)
        menu.addSeparator()
        self.tray_play = [
            menu.addAction(icon("media-playback-start"), _("Відтворити / пауза"), self.toggle_play),
            menu.addAction(icon("media-skip-backward"), _("Попередній трек"), self.prev_track),
            menu.addAction(icon("media-skip-forward"), _("Наступний трек"), self.next_track),
            menu.addAction(icon("media-playback-stop"), _("Зупинити відтворення"), self.stop_playback),
        ]
        menu.addSeparator()
        self.tray_eject = menu.addAction(icon("media-eject"), _("Вийняти диск"), self.eject)
        menu.addAction(icon("help-about"), _("Про програму"), self.about)
        menu.addAction(icon("application-exit"), _("Вийти"), self.quit_app)
        menu.aboutToShow.connect(self.update_tray_menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.messageClicked.connect(self.show_window)
        self.tray.setVisible(self.chk_tray.isChecked())

    def announce_play(self):
        """Диск почав грати, а вікна не видно — сповіщення від значка в лотку (клік відкриває вікно)."""
        if not self.tray_enabled() or read_config().get("NOTIFY", "yes") == "no":
            return
        i = self.info
        title = " — ".join(x for x in (i.get("ALBUM_ARTIST", ""), i.get("ALBUM", "")) if x) or _("Аудіо-CD")
        cover = QPixmap(i["COVER"]) if i.get("COVER") else QPixmap()
        tray_icon = QIcon(rounded_pixmap(cover, 128)) if not cover.isNull() else QIcon.fromTheme("media-optical-audio")
        self.tray.showMessage(title, _("Відтворюю диск. Керувати ним можна зі значка в лотку або з віджета «Програвач»."),
                              tray_icon, 8000)

    def update_tray_menu(self):
        for a in self.tray_play:
            a.setEnabled(self.p_play.isEnabled())
        self.tray_eject.setEnabled(self.last_tracks > 0)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_window()
        elif reason == QSystemTrayIcon.MiddleClick:
            self.toggle_play()

    def on_tray_option(self, checked):
        QSettings(APP, "gui").setValue("tray", "true" if checked else "false")
        self.chk_quiet.setEnabled(checked)
        if self.tray:
            self.tray.setVisible(checked)

    def tray_enabled(self):
        return self.tray is not None and self.tray.isVisible()

    def play_in_tray(self):
        """Диск вставлено — грати, не відкриваючи вікна (якщо так налаштовано)."""
        return self.tray_enabled() and self.chk_quiet.isChecked()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toggle_window(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_window()

    def quit_app(self):
        self.quitting = True
        self.close()

    def on_lang(self, _index):
        lang = self.lang.currentData()
        if lang == LANG:
            return
        run("lang", lang)
        self.save_layout()          # нове вікно відкриється такого ж розміру
        # нове вікно не має застати старе (інакше лише передасть йому «show» і закриється)
        if self.server:
            self.server.close()
        if self.mpv:
            self.mpv.quit()
        self.cur = None             # копіювання хай триває — для нового вікна
        if self.mpris:              # звільняємо ім'я MPRIS для нового вікна
            self.mpris.remove_from_connection()
            self.mpris = None
        self.restart_lang = lang    # main() перезапустить програму після виходу з циклу подій
        QApplication.quit()

    def update_service(self):
        def q(*a):
            try:
                return subprocess.run(["systemctl", "--user", *a, f"{APP}.service"],
                                      capture_output=True, text=True, timeout=5).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                return ""
        enabled, active = q("is-enabled"), q("is-active")
        installed = enabled not in ("", "not-found")
        self.chk_service.blockSignals(True)
        self.chk_service.setEnabled(installed)
        self.chk_service.setChecked(enabled == "enabled")
        self.chk_service.blockSignals(False)
        if not installed:
            text, svc = _("Служба не встановлена"), "dialog-warning"
        elif active == "active":
            text, svc = _("Служба працює"), "emblem-ok-symbolic"
        else:
            text, svc = _("Служба зупинена"), "media-playback-pause"
        self.svc_icon.setPixmap(icon(svc).pixmap(16, 16))
        self.svc_label.setText(text)
        self.svc_label.setToolTip(f"{APP}.service: {active or '—'}")

    # --- дії ------------------------------------------------------------------------------
    def action(self, name, reload=False, extra=()):
        if self.proc and self.proc.state() != QProcess.NotRunning and name != "stop":
            return
        args = [name] + ([self.info["DEVICE"]] if name in ("play", "rip", "tag") and self.info.get("DEVICE") else [])
        args += extra
        proc = QProcess(self)
        proc.setProgram(self_bin())
        proc.setArguments(args)

        def finished(code, _status):
            if code:
                text = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
                QMessageBox.warning(self, _("Помилка"), text or _("Не вдалося виконати дію."))
            if reload or name in ("clean",):
                self.reload_info()
            self.poll()
        proc.finished.connect(finished)
        proc.start()
        if name in ("play", "open", "rip", "stop", "clean"):
            self.proc = None      # швидкі команди — не блокують інші кнопки
        else:
            self.proc = proc

    def eject(self):
        """Зупиняє копіювання (воно тримає привід) і виймає диск. Решту — вийнятий диск,
        кінець відтворення — зробить poll(), як і тоді, коли диск виймають кнопкою приводу."""
        dev = self.disc.get("DEVICE") or "/dev/sr0"
        if self.queue_is_disc() and not self.continue_from_library():
            self.stop_playback()
        self.write_want(None)
        run("stop", timeout=10)
        proc = QProcess(self)

        def finished(code, _status):
            if code:
                text = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
                QMessageBox.warning(self, _("Помилка"), text or _("Не вдалося вийняти диск."))
            self.poll()
        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda err: err == QProcess.FailedToStart and finished(1, None))
        proc.start("eject", [dev])

    def about(self):
        if not self.isVisible():        # з меню лотка: вікно діалогу без батьківського не видно
            self.show_window()
        box = QMessageBox(self)
        box.setWindowTitle(_("Про програму"))
        box.setIconPixmap(QIcon.fromTheme("media-optical-audio").pixmap(64, 64))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<h3>CD Auto Runner</h3><p>{_('Версія {v}', v=self.version or '—')}</p>")
        box.setInformativeText(
            f"<p>{_('Запускає обраний програвач, щойно вставлено аудіо-CD, має власний вбудований програвач і копіює диски в бібліотеку музики з назвами треків і обкладинками.')}</p>"
            f"<p>© 2026 Pan Vena<br>{_('Ліцензія: GNU GPL версії 2.')}</p>"
            f'<p><a href="{HOMEPAGE}">{HOMEPAGE.removeprefix("https://")}</a></p>')
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        for label in box.findChildren(QLabel):
            label.setOpenExternalLinks(True)
        box.exec()

    def restore_layout(self):
        settings = QSettings(APP, "gui")
        geometry, state = settings.value("geometry"), settings.value("splitter")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.split.restoreState(state)
        self.split.setHandleWidth(12)   # після restoreState — він повертає збережену ширину ручки

    def save_layout(self):
        settings = QSettings(APP, "gui")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("splitter", self.split.saveState())

    def open_dir(self, path):
        if path:
            os.makedirs(path, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # --- диск ---------------------------------------------------------------------------
    def reload_info(self):
        if self.loading:
            return
        self.loading = True
        if not self.album_open():
            self.show_loading()
        self.request_info.emit()

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

    def set_buttons(self, enabled):
        disc = enabled and not self.album_open()    # копіювати й називати можна лише диск
        for b in (self.btn_play, self.btn_stop):
            b.setEnabled(enabled)
        for b in (self.btn_rip, self.act_mb):
            b.setEnabled(disc)
        self.btn_tag.setEnabled(enabled and not self.playlist_open())
        self.btn_tag.setText(_("Редагувати альбом") if self.album_open() else _("Ввести назви"))
        self.act_album.setEnabled(enabled)

    def set_cover(self, path="", image=None):
        pix = QPixmap(path) if path else QPixmap.fromImage(image) if image else QPixmap()
        if pix.isNull():
            pix = QIcon.fromTheme("media-optical-audio").pixmap(128, 128)
            self.cover.setPixmap(pix)
        else:
            self.cover.setPixmap(rounded_pixmap(pix, self.COVER))

    def show_empty(self, title=None, detail=None):
        self.set_cover()
        self.title.setText(title or _("Вставте аудіо-CD"))
        self.subtitle.setText(detail or _("Обраний програвач запуститься сам, щойно ви вставите диск."))
        self.meta.setText("")
        self.badge.hide()
        self.tree.clear()
        self.set_buttons(False)
        self.btn_stop.setEnabled(True)
        self.update_player()
        self.fill_library()

    def show_loading(self):
        self.title.setText(_("Читаю диск…"))
        self.subtitle.setText("")
        self.meta.setText("")
        self.badge.hide()
        self.set_buttons(False)

    def show_disc(self):
        i = self.info
        self.set_cover(i.get("COVER", ""), self.playlist_image())
        self.title.setText(i.get("ALBUM", ""))
        sub = i.get("ALBUM_ARTIST", "")
        if i.get("YEAR"):
            sub += f"  ·  {i['YEAR']}"
        self.subtitle.setText(sub)
        self.show_meta()
        src = i.get("SOURCE", "none")
        labels = {"musicbrainz": "Назви з MusicBrainz", "cdtext": "Назви з диска (CD-TEXT)",
                  "mbsearch": "MusicBrainz (за назвою)", "library": "З бібліотеки", "playlist": "Плейліст",
                  "ripped": "Записано з диска", "digital": "Цифровий альбом",
                  "user": "Назви введено вручну", "kde": "Кеш KDE", "none": "Диска немає в базах"}
        self.badge.setText(_(labels.get(src, src)))
        self.badge.setObjectName("warn" if src == "none" else "badge")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.badge.show()
        self.set_buttons(True)
        self.fill_tracks()
        self.fill_library()

    def show_meta(self):
        tracks = self.info["tracks"]
        total = sum(t["sec"] for t in tracks)
        text = _("треків: {n}", n=len(tracks))
        self.meta.setText(f"{text}  ·  {fmt_time(total)}" if total else text)

    def fill_tracks(self):
        self.tree.clear()
        muted = self.palette().color(QPalette.PlaceholderText)
        italic = QFont(self.font())
        italic.setItalic(True)
        reorder = bool(self.playlist_open())
        self.tree.setDragEnabled(reorder)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove if reorder else QAbstractItemView.NoDragDrop)
        self.tree.setDropIndicatorShown(reorder)
        for t in self.info.get("tracks", []):
            item = QTreeWidgetItem([f"{t.get('num', t['n']):02d}", t["artist"], t["title"],
                                    fmt_time(t["sec"]) if t["sec"] else "", ""])
            if t.get("missing"):
                item.setText(4, _("файлу немає"))
                item.setIcon(4, icon("dialog-warning"))
            elif t.get("path"):
                item.setText(4, _("у бібліотеці"))
                item.setIcon(4, icon("emblem-ok-symbolic"))
            item.setData(0, Qt.UserRole, t["n"])
            if reorder:                 # рядки ставляться між іншими, а не всередину них
                item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)
            item.setTextAlignment(0, Qt.AlignRight | Qt.AlignVCenter)
            item.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
            if t["placeholder"]:
                for c in (1, 2):
                    item.setForeground(c, muted)
                    item.setFont(c, italic)
            self.tree.addTopLevelItem(item)
        self.update_states()
        self.update_player()

    # --- живе оновлення ----------------------------------------------------------------
    def ripping_track(self):
        try:
            out = subprocess.run(["pgrep", "-a", "-u", str(os.getuid()), "cd-paranoia|cdparanoia"],
                                 capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
        m = re.search(r"-d \S+ (\d+)(?: |$)", out) or re.search(r"-w (\d+)", out)
        return int(m.group(1)) if m else None

    def update_states(self):
        """Стан копіювання вставленого диска — навіть коли показано альбом бібліотеки."""
        i = self.disc
        shown = not self.album_open()
        if not i.get("tracks"):
            self.progress.hide()
            self.prog_label.setText("")
            return
        lib, cache = i.get("LIBRARY_DIR", ""), i.get("CACHE_DIR", "")
        ripping = self.ripping_track()
        done = 0
        for idx, t in enumerate(i["tracks"]):
            n = t["n"]
            if lib and glob.glob(os.path.join(glob.escape(lib), f"{n:02d} - *")):
                state, state_icon = _("у бібліотеці"), "emblem-ok-symbolic"
                done += 1
            elif cache and os.path.exists(os.path.join(cache, f".done-{n}")):
                state, state_icon = _("скопійовано"), "document-save"
                done += 1
            elif ripping == n:
                state, state_icon = _("копіюється…"), "media-record"
            else:
                state, state_icon = "", ""
            item = self.tree.topLevelItem(idx) if shown else None
            if item:
                item.setText(4, state)
                item.setIcon(4, icon(state_icon) if state_icon else QIcon())
        if done != self.lib_done:
            self.lib_done = done
            self.rescan()
        total = len(i["tracks"])
        if ripping:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.progress.setFormat(f"{done}/{total}")
            self.progress.show()
            self.prog_label.setText(_("Копіюю трек {t} · {done} з {total}", t=ripping, done=done, total=total))
        else:
            self.progress.hide()
            self.prog_label.setText(_("Скопійовано {done} з {total}", done=done, total=total) if done else "")

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

    def poll(self):
        # назви змінили не з вікна (сповіщення «Ввести назви…», термінал) — оновити
        if self.disc and not self.loading and self.titles_mtime() != getattr(self, "titles_stamp", 0):
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

    # --- один екземпляр вікна ----------------------------------------------------------
    def listen(self, server):
        self.server = server
        server.newConnection.connect(self.on_connection)

    def on_connection(self):
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self.on_message(c))
            conn.disconnected.connect(conn.deleteLater)

    def on_message(self, conn):
        show = False
        for line in bytes(conn.readAll()).decode(errors="replace").splitlines():
            if line.strip() == "play":
                self.request_play()
                show = show or not self.play_in_tray()
            elif line.strip():
                show = True
        if show:
            self.show_window()

    def closeEvent(self, event):
        self.save_layout()
        # з лотком закриття вікна лише ховає його: програвач грає далі
        if not self.quitting and self.tray_enabled():
            event.ignore()
            self.hide()
            settings = QSettings(APP, "gui")
            if settings.value("tray_hint", "false") != "true":
                settings.setValue("tray_hint", "true")
                self.tray.showMessage("CD Auto Runner", _("CD Auto Runner працює далі в системному лотку. Щоб вийти, оберіть «Вийти» в меню його значка."),
                                      QIcon.fromTheme("media-optical-audio"), 6000)
            return
        super().closeEvent(event)
        QApplication.quit()

    def shutdown(self):
        """Перед виходом з програми (QApplication.aboutToQuit)."""
        if self.shut_down:
            return
        self.shut_down = True
        if self.isVisible():
            self.save_layout()
        if self.tray:
            self.tray.hide()
        if self.mpv:
            self.mpv.quit()
        self.write_want(None)
        # без бібліотеки треки копіюються лише для цього вікна — далі копіювати нема сенсу
        if self.cur is not None and read_config().get("LIBRARY", "yes") != "yes" and self.builtin_selected():
            run("stop", timeout=10)
        for thread in (self.thread, self.lib_thread):
            thread.quit()
            thread.wait(2000)
        for task in list(Task.alive):
            task.wait(2000)


def main():
    play = "--play" in sys.argv[1:]
    app = QApplication(sys.argv[:1])
    # Без теми значків від Plasma — Breeze під колір вікна (темна тема — breeze-dark)
    paths = QIcon.themeSearchPaths()
    for d in [os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))] + \
             os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        d = os.path.join(d, "icons")
        if os.path.isdir(d) and d not in paths:
            paths.append(d)
    QIcon.setThemeSearchPaths(paths)
    if not QIcon.themeName():
        QIcon.setThemeName("breeze-dark" if is_dark(app.palette()) else "breeze")
    QIcon.setFallbackThemeName("breeze")
    app.setApplicationName(APP)
    app.setApplicationDisplayName("CD Auto Runner")
    app.setDesktopFileName(APP)
    app.setWindowIcon(QIcon.fromTheme("media-optical-audio"))

    # Вікно вже відкрите — передаємо йому команду й виходимо
    name = os.path.join(runtime_dir(), "gui.sock")
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(500):
        sock.write(b"play\n" if play else b"show\n")
        sock.flush()
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.listen(name)

    app.setQuitOnLastWindowClosed(False)   # вікно може ховатися в лоток; виходить closeEvent
    win = MainWindow(play=play)
    app.aboutToQuit.connect(win.shutdown)
    win.listen(server)
    if not (play and win.play_in_tray()):
        win.show()
    code = app.exec()
    if win.restart_lang:
        # exec, а не дочірній процес: той лишився б у cgroup юніта systemd і помер би разом зі старим
        env = dict(os.environ, CDAR_UI_LANG=win.restart_lang)
        os.execve(sys.executable, [sys.executable, "-I", os.path.abspath(__file__)], env)
    return code


if __name__ == "__main__":
    sys.exit(main())
