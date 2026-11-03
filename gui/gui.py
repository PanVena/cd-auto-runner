#!/usr/bin/env python3
"""CD Auto Runner — головне вікно (PySide6).

Вікно показує стан і викликає cd-auto-runner (CDAR_SELF): уся логіка копіювання — у скрипті.
Вбудований програвач відтворює скопійовані треки через mpv (окремий процес, керування —
JSON IPC через локальний сокет). Тексти українською; EN — англійський переклад (CDAR_UI_LANG).

  gui.py [--play] [ПРИСТРІЙ]   --play — одразу відтворювати диск у вбудованому програвачі

CD Auto Runner main window. Ripping logic lives in the cd-auto-runner script; the built-in
player plays ripped tracks through mpv, controlled over its JSON IPC socket.

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

from PySide6.QtCore import QObject, QProcess, QRectF, QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSlider, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

APP = "cd-auto-runner"
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


def is_dark(pal):
    return pal.color(QPalette.Window).lightness() < 128


AUDIO_EXT = {".flac", ".opus", ".ogg", ".mp3", ".wav"}


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


def card():
    f = QFrame()
    f.setObjectName("card")
    return f


class MainWindow(QMainWindow):
    COVER = 168
    request_info = Signal()     # виклик InfoWorker.load у фоновому потоці (queued)

    def __init__(self, play=False):
        super().__init__()
        self.setWindowTitle("CD Auto Runner")
        self.setWindowIcon(QIcon.fromTheme("media-optical-audio"))
        self.resize(1120, 760)
        self.info = {}
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
        self.seeking = False
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
            QGroupBox {{ font-weight: 600; }}
        """)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 8)
        outer.setSpacing(12)
        outer.addWidget(self.build_header())

        split = QSplitter(Qt.Horizontal)
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

        self.thread = QThread(self)
        self.worker = InfoWorker()
        self.worker.moveToThread(self.thread)
        self.worker.done.connect(self.on_info)
        self.request_info.connect(self.worker.load)
        self.thread.start()

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
        self.btn_tag.clicked.connect(lambda: self.action("tag", reload=True))
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
        menu.addAction(icon("view-refresh"), _("Оновити"), self.reload_info)
        menu.addAction(icon("edit-clear-history"), _("Видалити тимчасові файли"),
                       lambda: self.action("clean"))
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
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
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

    def track_title(self, n):
        for t in self.info.get("tracks", []):
            if t["n"] == n:
                return t
        return None

    def track_file(self, n):
        """Готовий файл треку: у бібліотеці (закодований) або скопійований WAV у кеші."""
        lib, cache = self.info.get("LIBRARY_DIR", ""), self.info.get("CACHE_DIR", "")
        if lib:
            for f in sorted(glob.glob(os.path.join(glob.escape(lib), f"{n:02d} - *"))):
                if os.path.splitext(f)[1].lower() in AUDIO_EXT and os.path.isfile(f):
                    return f
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
        cache = self.info.get("CACHE_DIR", "")
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
        if not self.info.get("DEVICE") or time.monotonic() - self.rip_started < 30 or self.rip_running():
            return
        self.rip_started = time.monotonic()
        QProcess.startDetached(self_bin(), ["play", "--player", "builtin", "--no-window", self.info["DEVICE"]])

    def play_track(self, n):
        tracks = self.info.get("tracks", [])
        if not self.mpv or not tracks or not 1 <= n <= len(tracks):
            return
        self.cur = n
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
            self.play_track(self.tree.indexOfTopLevelItem(sel) + 1 if sel else 1)
        elif self.want is None:
            self.mpv.toggle()

    def prev_track(self):
        if self.cur is None:
            return
        if self.want is None and self.seek.value() > 3:
            self.mpv.seek(0)
        elif self.cur > 1:
            self.play_track(self.cur - 1)

    def next_track(self):
        if self.cur is not None and self.cur < len(self.info.get("tracks", [])):
            self.play_track(self.cur + 1)

    def on_play(self):
        """Кнопка «Відтворити»: вбудований програвач — у цьому вікні, інакше — обраний програвач."""
        if self.builtin_selected() and self.mpv:
            if self.cur is None:
                self.play_track(1)
            elif self.is_paused:
                self.mpv.toggle()
        else:
            self.action("play")

    def on_track_activated(self, item, _col=0):
        if self.mpv and self.info.get("tracks"):
            self.play_track(self.tree.indexOfTopLevelItem(item) + 1)
        else:
            self.action("tag", reload=True)

    def request_play(self):
        """--play або повідомлення від іншого запуску: відтворити диск з початку."""
        if self.info.get("tracks") and not self.loading:
            self.pending_play = False
            if self.cur is None:
                self.play_track(1)
        else:
            self.pending_play = True

    def on_position(self, sec):
        if not self.seeking:
            self.seek.setValue(int(sec))
        self.t_pos.setText(fmt_time(sec))

    def on_duration(self, sec):
        self.length = sec
        self.seek.setRange(0, int(sec))
        self.t_len.setText(fmt_time(sec))

    def on_paused(self, paused):
        self.is_paused = paused
        self.update_player()

    def on_seek(self):
        self.seeking = False
        if self.mpv and self.cur is not None and self.want is None:
            self.mpv.seek(self.seek.value())

    def on_volume(self, value):
        QSettings(APP, "gui").setValue("volume", value)
        if self.mpv:
            self.mpv.set_volume(value)

    def on_ended(self, reason):
        if reason == "eof" and self.cur is not None and self.want is None:
            if self.cur < len(self.info.get("tracks", [])):
                self.play_track(self.cur + 1)
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
        on = self.mpv is not None and bool(self.info.get("tracks"))
        for b in (self.p_prev, self.p_play, self.p_stop, self.p_next, self.seek):
            b.setEnabled(on)
        self.vol.setEnabled(self.mpv is not None)
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
            text = f"{self.cur:02d}. {t.get('title', '')}"
            if t.get("artist") and t.get("artist") != self.info.get("ALBUM_ARTIST"):
                text += f" — {t['artist']}"
            if self.is_paused:
                text += f"  ({_('Пауза')})"
            self.now.setText(text)
        self.mark_playing()

    def mark_playing(self):
        bold = QFont(self.tree.font())
        bold.setBold(True)
        normal = QFont(self.tree.font())
        for idx in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(idx)
            current = self.cur == idx + 1
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

        g1 = QGroupBox(_("Відтворення"))
        f1 = QFormLayout(g1)
        self.player = QComboBox()
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

        g2 = QGroupBox(_("Копіювання і бібліотека"))
        f2 = QFormLayout(g2)
        self.fmt = QComboBox()
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

        g3 = QGroupBox(_("Інтерфейс"))
        f3 = QFormLayout(g3)
        self.lang = QComboBox()
        self.lang.addItem("English", "en")
        self.lang.addItem("Українська", "uk")
        self.lang.setCurrentIndex(self.lang.findData(LANG))
        self.lang.activated.connect(self.on_lang)
        f3.addRow(_("Мова:"), self.lang)
        lay.addWidget(g3)
        lay.addStretch(1)
        area.setWidget(inner)
        area.setMinimumWidth(360)
        return area

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
        footer = QLabel(f"CD Auto Runner {script_version()}")
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

    def on_lang(self, _index):
        lang = self.lang.currentData()
        if lang == LANG:
            return
        run("lang", lang)
        # нове вікно не має застати старе (інакше лише передасть йому «show» і закриється)
        if self.server:
            self.server.close()
        if self.mpv:
            self.mpv.quit()
        env = dict(os.environ, CDAR_UI_LANG=lang)
        subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__)], env=env, start_new_session=True)
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
    def action(self, name, reload=False):
        if self.proc and self.proc.state() != QProcess.NotRunning and name != "stop":
            return
        args = [name] + ([self.info["DEVICE"]] if name in ("play", "rip", "tag") and self.info.get("DEVICE") else [])
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
        if name in ("play", "rip", "stop", "clean"):
            self.proc = None      # швидкі команди — не блокують інші кнопки
        else:
            self.proc = proc

    def open_dir(self, path):
        if path:
            os.makedirs(path, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # --- диск ---------------------------------------------------------------------------
    def reload_info(self):
        if self.loading:
            return
        self.loading = True
        self.show_loading()
        self.request_info.emit()

    def on_info(self, info):
        self.loading = False
        if udev_audio_tracks() == 0:
            self.stop_playback()
            self.info = {}
            self.show_empty()
            return
        if not info.get("ok"):
            self.stop_playback()
            self.info = {}
            self.show_empty(_("Не вдалося прочитати диск"), info.get("error", ""))
            return
        if self.cur is not None and info.get("DISC_ID") != self.info.get("DISC_ID"):
            self.stop_playback()        # інший диск
        self.info = info
        self.titles_stamp = self.titles_mtime()
        self.show_disc()
        if self.pending_play:
            self.request_play()

    def set_buttons(self, enabled):
        for b in (self.btn_play, self.btn_rip, self.btn_tag, self.btn_stop):
            b.setEnabled(enabled)
        self.act_album.setEnabled(enabled)
        self.act_mb.setEnabled(enabled)

    def set_cover(self, path=""):
        pix = QPixmap(path) if path else QPixmap()
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

    def show_loading(self):
        self.title.setText(_("Читаю диск…"))
        self.subtitle.setText("")
        self.meta.setText("")
        self.badge.hide()
        self.set_buttons(False)

    def show_disc(self):
        i = self.info
        self.set_cover(i.get("COVER", ""))
        self.title.setText(i.get("ALBUM", ""))
        sub = i.get("ALBUM_ARTIST", "")
        if i.get("YEAR"):
            sub += f"  ·  {i['YEAR']}"
        self.subtitle.setText(sub)
        total = sum(t["sec"] for t in i["tracks"])
        self.meta.setText(f"{_('треків: {n}', n=len(i['tracks']))}  ·  {fmt_time(total)}")
        src = i.get("SOURCE", "none")
        labels = {"musicbrainz": "Назви з MusicBrainz", "library": "З бібліотеки",
                  "user": "Назви введено вручну", "kde": "Кеш KDE", "none": "Диска немає в базах"}
        self.badge.setText(_(labels.get(src, src)))
        self.badge.setObjectName("warn" if src == "none" else "badge")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.badge.show()
        self.btn_tag.setText(_("Ввести назви"))
        self.set_buttons(True)
        self.fill_tracks()

    def fill_tracks(self):
        self.tree.clear()
        muted = self.palette().color(QPalette.PlaceholderText)
        italic = QFont(self.font())
        italic.setItalic(True)
        for t in self.info.get("tracks", []):
            item = QTreeWidgetItem([f"{t['n']:02d}", t["artist"], t["title"], fmt_time(t["sec"]), ""])
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
        i = self.info
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
            item = self.tree.topLevelItem(idx)
            if item:
                item.setText(4, state)
                item.setIcon(4, icon(state_icon) if state_icon else QIcon())
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
        i, stamp = self.info, 0.0
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
        if self.info and not self.loading and self.titles_mtime() != getattr(self, "titles_stamp", 0):
            self.reload_info()
        tracks = udev_audio_tracks()
        if tracks != self.last_tracks:
            self.last_tracks = tracks
            if tracks:
                self.reload_info()
            else:
                self.stop_playback()
                self.info = {}
                self.show_empty()
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
        if self.want is not None and self.info.get("tracks"):
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
        for line in bytes(conn.readAll()).decode(errors="replace").splitlines():
            if line.strip() == "play":
                self.request_play()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.mpv:
            self.mpv.quit()
        self.write_want(None)
        # без бібліотеки треки копіюються лише для цього вікна — далі копіювати нема сенсу
        if self.cur is not None and read_config().get("LIBRARY", "yes") != "yes" and self.builtin_selected():
            run("stop", timeout=10)
        self.thread.quit()
        self.thread.wait(2000)
        super().closeEvent(event)


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

    win = MainWindow(play=play)
    win.listen(server)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
