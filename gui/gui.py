#!/usr/bin/env python3
"""CD Auto Runner — головне вікно (PySide6).

Вікно лише показує стан і викликає cd-auto-runner (CDAR_SELF): уся логіка — у скрипті.
Тексти українською; EN — англійський переклад (мова: CDAR_UI_LANG).

CD Auto Runner main window. All logic lives in the cd-auto-runner script; this window
only shows state and calls it.

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import glob
import os
import re
import shutil
import subprocess
import sys

from PySide6.QtCore import QObject, QProcess, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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
    "Формат і бібліотека стосуються програвачів, яким треки копіюються (Elisa, QMPlay2, Audacious), і кнопки «Скопіювати в бібліотеку».":
        "Format and library apply to players that get ripped tracks (Elisa, QMPlay2, Audacious) and to the \"Rip to library\" button.",
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
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


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

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CD Auto Runner")
        self.setWindowIcon(QIcon.fromTheme("media-optical-audio"))
        self.resize(1120, 720)
        self.info = {}
        self.last_tracks = -1
        self.loading = False
        self.proc = None

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
        split.addWidget(self.build_tracks())
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

        self.timer = QTimer(self, interval=2000, timeout=self.poll)
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
        self.btn_play = QPushButton(QIcon.fromTheme("media-playback-start"), _("Відтворити"))
        self.btn_play.setObjectName("primary")
        self.btn_play.setDefault(True)
        self.btn_rip = QPushButton(QIcon.fromTheme("media-import-audio-cd", QIcon.fromTheme("document-save")),
                                   _("Скопіювати в бібліотеку"))
        self.btn_tag = QPushButton(QIcon.fromTheme("document-edit"), _("Ввести назви"))
        self.btn_stop = QPushButton(QIcon.fromTheme("media-playback-stop"), _("Зупинити"))
        for b in (self.btn_play, self.btn_rip, self.btn_tag, self.btn_stop):
            b.setIconSize(QSize(20, 20))
            buttons.addWidget(b)
        self.btn_play.clicked.connect(lambda: self.action("play"))
        self.btn_rip.clicked.connect(lambda: self.action("rip"))
        self.btn_tag.clicked.connect(lambda: self.action("tag", reload=True))
        self.btn_stop.clicked.connect(lambda: self.action("stop"))

        more = QToolButton()
        more.setIcon(QIcon.fromTheme("application-menu", QIcon.fromTheme("open-menu-symbolic")))
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
        menu.addAction(QIcon.fromTheme("view-refresh"), _("Оновити"), self.reload_info)
        menu.addAction(QIcon.fromTheme("edit-clear-history"), _("Видалити тимчасові файли"),
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
        self.tree.itemDoubleClicked.connect(lambda *_a: self.action("tag", reload=True))
        lay.addWidget(self.tree)
        return box

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
        change = QPushButton(QIcon.fromTheme("folder-open"), _("Змінити…"))
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
        note = QLabel(_("Формат і бібліотека стосуються програвачів, яким треки копіюються (Elisa, QMPlay2, Audacious), і кнопки «Скопіювати в бібліотеку»."))
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
        self.svc_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.setTextVisible(True)
        self.progress.hide()
        self.prog_label = QLabel()
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
            text, icon = _("Служба не встановлена"), "dialog-warning"
        elif active == "active":
            text, icon = _("Служба працює"), "emblem-ok-symbolic"
        else:
            text, icon = _("Служба зупинена"), "media-playback-pause"
        self.svc_label.setText(f"  {text}")
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
            self.info = {}
            self.show_empty()
            return
        if not info.get("ok"):
            self.info = {}
            self.show_empty(_("Не вдалося прочитати диск"), info.get("error", ""))
            return
        self.info = info
        self.titles_stamp = self.titles_mtime()
        self.show_disc()

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
                state, icon = _("у бібліотеці"), "emblem-ok-symbolic"
                done += 1
            elif cache and os.path.exists(os.path.join(cache, f".done-{n}")):
                state, icon = _("скопійовано"), "document-save"
                done += 1
            elif ripping == n:
                state, icon = _("копіюється…"), "media-record"
            else:
                state, icon = "", ""
            item = self.tree.topLevelItem(idx)
            if item:
                item.setText(4, state)
                item.setIcon(4, QIcon.fromTheme(icon) if icon else QIcon())
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

    def closeEvent(self, event):
        self.thread.quit()
        self.thread.wait(2000)
        super().closeEvent(event)


def main():
    if not QIcon.themeName():
        QIcon.setThemeName("breeze")
    QIcon.setFallbackThemeName("breeze")
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP)
    app.setApplicationDisplayName("CD Auto Runner")
    app.setDesktopFileName(APP)
    app.setWindowIcon(QIcon.fromTheme("media-optical-audio"))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
