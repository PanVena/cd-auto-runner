#!/usr/bin/env python3
"""CD Auto Runner — головне вікно (PySide6).

Вікно показує стан і викликає cd-auto-runner (CDAR_SELF): уся логіка копіювання — у скрипті.
Вбудований програвач відтворює скопійовані треки через mpv (окремий процес, керування —
JSON IPC через локальний сокет) і показує себе системі через MPRIS (елементи керування музикою,
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
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor    # у Python 3.15 атрибут модуля лінивий і в потоці Qt не спрацьовує

from PySide6.QtCore import (
    QFileSystemWatcher, QObject, QPoint, QProcess, QRect, QRectF, QSettings, QSize, Qt, QTemporaryDir, QThread, QTimer, QUrl,
    Signal,
)
from PySide6.QtGui import (
    QActionGroup,
    QColor, QDesktopServices, QFont, QIcon, QImage, QImageReader, QPainter, QPainterPath, QPalette, QPen, QPixmap,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter, QStackedWidget,
    QStyle, QStyledItemDelegate, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

try:    # окремий модуль, а в деяких дистрибутивах і окремий пакет
    from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage, QDBusVariant
except ImportError:
    QDBusConnection = None
sys.path.append(os.path.dirname(os.path.abspath(__file__)))     # запуск з -I: спільний модуль лежить поруч
from cdar_core import (     # noqa: E402
    ALBUM_SORTS, is_artist, is_blocked_list,
    APP, ARTIST_KEY, FAVORITES, GNOME, HOMEPAGE, LANG, LOOP_MODES, PLAYLIST_EXT, THUMB, TRACK_KEY, Controller, ThumbCache, _,
    album_from_tags, album_tags, connect_mpris, embedded_cover, favorites_path, fetch_cover, fmt_time, is_playlist,
    looks_same, musicbrainz, playlist_name, playlists_dir, read_album, read_config, read_disc, read_marker, run,
    runtime_dir, safe_name, script_version, self_bin, track_label, track_seconds, write_marker,
)

# Значки Breeze, яких немає в Adwaita (тема GNOME): чим їх замінити
ICON_ALIASES = {
    "application-menu": "open-menu-symbolic",
    "dialog-cancel": "action-unavailable-symbolic",
    "dialog-ok-apply": "object-select-symbolic",
    "edit-clear-history": "edit-clear-all-symbolic",
    "edit-rename": "document-edit-symbolic",
    "emblem-ok-symbolic": "object-select-symbolic",
    "internet-web-browser": "web-browser-symbolic",
    "media-import-audio-cd": "document-save-symbolic",
    "view-media-playlist": "view-list-symbolic",
    "view-preview": "image-x-generic-symbolic",
}


def app_icon():
    """Значок програми: зі встановленої теми, поруч зі скриптом (запуск із репозиторію) або значок CD."""
    if QIcon.hasThemeIcon(APP):
        return QIcon.fromTheme(APP)
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, f"{APP}.svg"), os.path.join(here, "..", "desktop", f"{APP}.svg")):
        if os.path.isfile(path):
            return QIcon(path)
    return QIcon.fromTheme("media-optical-audio")


def theme_icon(*names):
    """Перший значок із тих, що є в темі: сам, його символьний варіант або замінник."""
    for name in names:
        for candidate in (name, f"{name}-symbolic", ICON_ALIASES.get(name)):
            if candidate and QIcon.hasThemeIcon(candidate):
                return QIcon.fromTheme(candidate)
    return app_icon() if "media-optical-audio" in names else QIcon()


def icon(*names):
    """Монохромний значок теми, перефарбований кольором тексту кнопок: білий на темній
    темі, темний на світлій (без теми Plasma Qt бере значки, намальовані для іншого тла)."""
    base = theme_icon(*names)
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


def portal_color_scheme():
    """Вибір користувача зі стандартного порталу: 1 темна, 2 світла, 0 — немає вибору.
    Працює незалежно від того, чи дійшла ця настройка до самого Qt."""
    if QDBusConnection is None:
        return 0
    call = QDBusMessage.createMethodCall("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                                         "org.freedesktop.portal.Settings", "ReadOne")
    call.setArguments(["org.freedesktop.appearance", "color-scheme"])
    reply = QDBusConnection.sessionBus().call(call, QDBus.Block, 300)
    if reply.type() != QDBusMessage.ReplyMessage or not reply.arguments():
        return 0
    value = reply.arguments()[0]
    value = value.variant() if isinstance(value, QDBusVariant) else value
    return value if value in (1, 2) else 0


def follow_color_scheme(app):
    """Плазма сама передає Qt тему; поза нею беремо схему з порталу (потрібен Qt 6.8+)."""
    if "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":"):
        return 0
    scheme = portal_color_scheme()
    if scheme and hasattr(app.styleHints(), "setColorScheme"):
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if scheme == 1 else Qt.ColorScheme.Light)
    return scheme


def is_dark(pal):
    return pal.color(QPalette.Window).lightness() < 128


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
        self.start_at = 0.0

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
            elif ev == "file-loaded" and self.start_at:
                self.seek(self.start_at)
                self.start_at = 0.0
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
    def load(self, path, start=0.0, paused=False):
        """start — позиція в секундах; перейти на неї можна, лише коли файл відкриється.
        Пауза ставиться до відкриття, щоб під час запуску не прозвучало ні звуку."""
        self.start_at = start
        if paused:
            self.command("set_property", "pause", True)
        self.command("loadfile", path, "replace")
        if not paused:
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


def start_mpris(win):
    """Сервіс MPRIS у циклі подій вікна. dbus-python працює в циклі GLib, тож лише тоді,
    коли Qt сам крутить цикл GLib (типово в Linux; QT_NO_GLIB=1 його вимикає)."""
    dispatcher = QApplication.instance().eventDispatcher()
    # QEventDispatcherGlib, QPAEventDispatcherGlib (Wayland), QXcbGlibEventDispatcher (X11)
    if dispatcher is None or "Glib" not in dispatcher.metaObject().className():
        return None
    return connect_mpris(win)


# --- фонове завантаження відомостей про диск ------------------------------------------
class InfoWorker(QObject):
    done = Signal(dict)

    def load(self):
        self.done.emit(read_disc())


def fingerprint(image):
    """Зменшена копія обкладинки: той самий малюнок може лежати в кількох теках різними файлами."""
    small = image.convertToFormat(QImage.Format_RGB888).scaled(12, 12, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return bytes(small.constBits())     # рядок — рівно 36 байтів, вирівнювання нічого не додає


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


def playlist_mosaic(covers):
    """Складена обкладинка плейліста і різні обкладинки, з яких вона складена."""
    picked = different_covers(covers)
    return mosaic([image for _path, image in picked]), [path for path, _image in picked]


def thumbnail(path):
    """Зменшена обкладинка; QImage, а не QPixmap — читається у фоновому потоці."""
    reader = QImageReader(path)
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(size.scaled(THUMB, THUMB, Qt.KeepAspectRatioByExpanding))
    return reader.read()


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


class LibraryWorker(QObject):
    """Окремий потік: InfoWorker може чекати на диск і MusicBrainz до двох хвилин."""
    scanned = Signal(object, object, object, object)    # альбоми, плейлісти, чорний список, усі теки
    timed = Signal(str, object)                 # тека альбому, {шлях: секунд}

    def __init__(self):
        super().__init__()
        self.thumbs = ThumbCache(thumbnail, playlist_mosaic)

    def scan(self, root):
        self.scanned.emit(*self.thumbs.scan(root))

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


class ClickLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()


class TabBadge(QLabel):
    """Кружок із кількістю на вкладці; для довгих чисел витягується в капсулу."""
    SIZE = 16

    def __init__(self, parent):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(self.SIZE)
        self.setMinimumWidth(self.SIZE)
        self.setStyleSheet(f"background: palette(mid); color: palette(window-text); font-size: 7pt; "
                           f"font-weight: bold; padding: 0 4px; border-radius: {self.SIZE // 2}px;")
        self.hide()

    def show_count(self, count):
        self.setText("999+" if count > 999 else str(count))
        self.adjustSize()
        self.setVisible(count > 0)


class TabButton(QToolButton):
    """Вкладка: значок над підписом, кружок — на правому верхньому куті значка."""

    def __init__(self, text, names):
        super().__init__()
        self.setObjectName("libtab")
        self.setText(text)
        self.setIcon(icon(*names))
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setCheckable(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.badge = TabBadge(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.badge.move(self.width() // 2 + 3, 2)


class LibTabs(QWidget):
    """Перемикач під сіткою альбомів, як AdwViewSwitcherBar у GNOME."""
    currentChanged = Signal(int)

    def __init__(self, tabs):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.group = QButtonGroup(self)
        for index, (text, names) in enumerate(tabs):
            button = TabButton(text, names)
            self.group.addButton(button, index)
            lay.addWidget(button, 1)
        self.group.button(0).setChecked(True)
        self.group.idToggled.connect(lambda index, on: on and self.currentChanged.emit(index))

    def currentIndex(self):
        return self.group.checkedId()

    def setCurrentIndex(self, index):
        button = self.group.button(index)
        if button:
            button.setChecked(True)

    def set_counts(self, counts):
        for index, count in enumerate(counts):
            self.group.button(index).badge.show_count(count)


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
        # (ще 2 px: якщо плитки вміщуються впритул, Qt переносить останню на новий рядок).
        # Резерв той самий, що в QListView: смуга за метрикою стилю, а в Kvantum — ще й рамка довкола вмісту
        style, bar = self.style(), self.verticalScrollBar()
        extent = max(bar.sizeHint().width(), style.pixelMetric(QStyle.PM_ScrollBarExtent, None, bar))
        if style.styleHint(QStyle.SH_ScrollView_FrameOnlyAroundContents, None, self):
            extent += 2 * style.pixelMetric(QStyle.PM_DefaultFrameWidth, None, self)
        width = self.maximumViewportSize().width() - extent - 2
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
            self.preview.setPixmap(app_icon().pixmap(96, 96))
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
        names = [self.cell(r, self.FILE) for r in range(self.table.rowCount())]
        titles = [self.cell(r, self.TITLE) for r in range(self.table.rowCount())]
        album, artist, year, rows = album_from_tags(tags, names, titles)
        if album:
            self.f_album.setText(album)
        if artist:
            self.f_artist.setText(artist)
        if year:
            self.f_year.setText(year)
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
    """Картка налаштувань із заголовком. Повертає (картка, QFormLayout для рядків)."""
    box = card()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(16, 12, 16, 14)
    lay.setSpacing(8)
    head = QLabel(title)
    head.setObjectName("section")
    lay.addWidget(head)
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
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


class MainWindow(Controller, QMainWindow):
    COVER = 132
    request_info = Signal()     # виклик InfoWorker.load у фоновому потоці (queued)
    request_scan = Signal(str)              # LibraryWorker.scan
    request_times = Signal(str, list)       # LibraryWorker.durations

    def __init__(self, play=False):
        super().__init__()
        self.setWindowTitle("CD Auto Runner")
        self.setWindowIcon(app_icon())
        # не більше за екран: на ноутбуці 1536×864 логічних точок вікно 860 заввишки зайняло б його весь
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1120, int(screen.width() * 0.85)), min(860, int(screen.height() * 0.85)))
        self.init_state(play)
        self.proc = None
        self.server = None
        # вбудований програвач
        self.mpv = Mpv(self) if Mpv.available() else None
        self.seeking = False
        self.mpris = None
        self.tray = None
        self.quitting = False       # «Вийти»: закриття вікна завершує програму, а не ховає її
        self.backgrounded = False   # вікно закрито без лотка, а музика ще грає
        self.scheme = 0             # схема кольорів із порталу, з якою побудовано вікно
        self.restart_lang = None    # мову змінено: main() перезапустить програму з новою мовою
        self.shut_down = False

        pal = self.palette()
        muted = pal.color(QPalette.PlaceholderText).name()
        hl = pal.color(QPalette.Highlight)
        self.setStyleSheet(f"""
            QFrame#card {{ background: palette(base); border: 1px solid palette(midlight); border-radius: 12px; }}
            QLabel#title {{ font-size: {17 if GNOME else 22}pt; font-weight: 600; }}
            QLabel#subtitle {{ font-size: {11 if GNOME else 12}pt; }}
            QLabel#muted {{ color: {muted}; }}
            QLabel#badge {{ border-radius: 10px; padding: 2px 10px;
                           background: rgba({hl.red()},{hl.green()},{hl.blue()},40); color: {hl.name()}; }}
            QLabel#warn {{ border-radius: 10px; padding: 2px 10px;
                          background: rgba(246,116,0,45); color: #f67400; }}
            QPushButton {{ padding: {"5px 10px" if GNOME else "7px 14px"}; }}
            QPushButton#primary {{ font-weight: 600; padding: {"6px 16px" if GNOME else "8px 22px"}; }}
            QLabel#section {{ font-weight: 600; }}
            QToolButton#libtab {{ border: none; border-radius: 8px; padding: 6px 4px 4px 4px; font-weight: 600; }}
            QToolButton#libtab:hover {{ background: palette(alternate-base); }}
            QToolButton#libtab:checked {{ background: palette(midlight); }}
            QSplitter::handle {{ background: transparent; }}
        """)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 8)
        outer.setSpacing(12)

        self.split = split = QSplitter(Qt.Horizontal)
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(12)
        right_lay.addWidget(self.build_header())
        right_lay.addWidget(self.build_tracks(), 1)
        split.addWidget(self.build_library())
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([420, 680])
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        outer.addWidget(self.build_player())

        self.prefs = self.build_settings()
        self.build_statusbar()
        self.load_settings()
        self.build_tray()
        self.restore_layout()
        self.tree.setFocus()
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

    # --- те, чого потребує Controller -------------------------------------------------
    def ui_get(self, key, default):
        return QSettings(APP, "gui").value(key, default)

    def ui_put(self, key, value):
        QSettings(APP, "gui").setValue(key, value)

    def toast(self, text):
        self.statusBar().showMessage(text, 5000)

    def warn(self, text):
        QMessageBox.warning(self, _("Помилка"), text)

    def start_detached(self, program, args):
        QProcess.startDetached(program, args)

    def played_unseen(self):
        if not self.isVisible():
            self.announce_play()

    def load_info(self):
        self.request_info.emit()

    def load_times(self, folder, paths):
        self.request_times.emit(folder, paths)

    def current_track(self):
        sel = self.tree.currentItem()
        return self.tree.indexOfTopLevelItem(sel) + 1 if sel else None

    def reveal_track(self, n):
        self.tree.scrollToItem(self.tree.topLevelItem(n - 1), QAbstractItemView.PositionAtCenter)

    def select_tracks(self, numbers):
        for n in numbers:
            self.tree.topLevelItem(n - 1).setSelected(True)

    def volume(self):
        return self.vol.value()

    def apply_volume(self, value):
        self.vol.setValue(value)

    def show_times(self):
        for idx, t in enumerate(self.info["tracks"]):
            item = self.tree.topLevelItem(idx)
            if item and t["sec"]:
                item.setText(3, fmt_time(t["sec"]))
        self.show_meta()

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
        for b in (self.btn_play, self.btn_rip, self.btn_tag):
            b.setIconSize(QSize(20, 20))
            buttons.addWidget(b)
        self.btn_play.clicked.connect(self.on_play)
        self.btn_rip.clicked.connect(lambda: self.action("rip"))
        self.btn_tag.clicked.connect(self.on_tag)

        more = QToolButton()
        more.setIcon(icon("application-menu", "open-menu-symbolic"))
        if more.icon().isNull():
            more.setText("⋯")
        more.setToolTip(_("Ще"))
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        self.act_album = menu.addAction(theme_icon("folder-music"), _("Відкрити теку альбому"),
                                        lambda: self.open_dir(self.info.get("LIBRARY_DIR", "")))
        self.act_mb = menu.addAction(theme_icon("internet-web-browser"), _("Додати диск у MusicBrainz"),
                                     lambda: QDesktopServices.openUrl(QUrl(self.info.get("MB_URL", ""))))
        menu.addSeparator()
        self.act_eject = menu.addAction(icon("media-eject"), _("Вийняти диск"), self.eject)
        menu.aboutToShow.connect(lambda: self.act_eject.setEnabled(self.last_tracks > 0))
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
        self.tree.setHeaderLabels(["№", _("Виконавець"), _("Назва"), _("Час"), _("Стан"), _("Альбом")])
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.Interactive)
        h.moveSection(5, 3)             # одразу після назви; є лише там, де треки з різних альбомів
        self.tree.setColumnWidth(1, 180)
        self.tree.setColumnWidth(5, 180)
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
        self.now = ClickLabel()
        self.now.setTextFormat(Qt.PlainText)
        self.now.clicked.connect(self.show_queue)
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

    # --- порядок відтворення: перемішування і повтор ---
    def on_track_activated(self, item, _col=0):
        if self.info.get("tracks") and (self.mpv or not self.plays_here()):
            self.start_track(self.tree.indexOfTopLevelItem(item) + 1)
        elif not self.album_open():
            self.action("tag", reload=True)

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

    def on_seek(self):
        self.seeking = False
        self.seek_to(self.seek.value())

    def on_volume(self, value):
        QSettings(APP, "gui").setValue("volume", value)
        if self.mpv:
            self.mpv.set_volume(value)
        if self.mpris:
            self.mpris.refresh()

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
        self.now.setText(self.now_text())
        self.now.setCursor(Qt.ArrowCursor if self.cur is None else Qt.PointingHandCursor)
        self.now.setToolTip("" if self.cur is None else _("Перейти до списку, що грає"))
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
        dialog = QDialog(self)
        dialog.setWindowTitle(_("Налаштування"))
        dialog.setWindowModality(Qt.WindowModal)
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(0, 0, 0, 0)
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
        if not self.chk_tray.isEnabled() and GNOME:
            self.chk_tray.setToolTip(_("У GNOME для значка в лотку потрібне розширення AppIndicator (пакет gnome-shell-extension-appindicator)."))
        self.chk_tray.clicked.connect(self.on_tray_option)
        f3.addRow(self.chk_tray)
        self.chk_quiet = QCheckBox(_("Вставлений диск відтворювати у лотку, не відкриваючи вікна"))
        self.chk_quiet.setChecked(QSettings(APP, "gui").value("play_in_tray", "false") == "true")
        self.chk_quiet.setEnabled(self.chk_tray.isEnabled() and self.chk_tray.isChecked())
        self.chk_quiet.clicked.connect(lambda v: QSettings(APP, "gui").setValue("play_in_tray", "true" if v else "false"))
        f3.addRow(self.chk_quiet)
        lay.addWidget(g3)
        lay.addStretch(1)
        lay.setContentsMargins(14, 14, 14, 14)
        area.setWidget(inner)
        outer.addWidget(area)
        # ширина за найдовшим рядком: прапорці не переносяться, а шрифт GNOME ширший за KDE
        inner.ensurePolished()
        width = inner.minimumSizeHint().width() + area.verticalScrollBar().sizeHint().width()
        screen = QApplication.primaryScreen().availableGeometry()
        dialog.resize(min(max(560, width), screen.width()), min(720, int(screen.height() * 0.85)))
        return dialog

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
        self.lib_add = QToolButton()
        self.lib_add.setAutoRaise(True)
        self.lib_add.clicked.connect(self.on_lib_add)
        self.lib_sort = QToolButton()
        self.lib_sort.setAutoRaise(True)
        self.lib_sort.setIcon(icon("view-sort-ascending"))
        self.lib_sort.setToolTip(_("Сортування"))
        self.lib_sort.setPopupMode(QToolButton.InstantPopup)
        self.lib_sort.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        menu, group = QMenu(self.lib_sort), QActionGroup(self.lib_sort)
        for mode, text in ALBUM_SORTS.items():
            act = group.addAction(_(text))
            act.setCheckable(True)
            act.setChecked(mode == self.sort)
            act.triggered.connect(lambda _on=False, m=mode: self.set_sort(m))
            menu.addAction(act)
        self.lib_sort.setMenu(menu)
        head.addWidget(self.lib_add)
        head.addWidget(self.lib_sort)
        head.addStretch(1)
        head.addWidget(self.build_main_menu())
        lay.addLayout(head)
        page, self.lib_list = self.album_grid(_("Тут з'являтимуться скопійовані диски."),
                                              _("Двічі клацніть альбом, щоб відтворити його."))
        lists, self.list_grid = self.album_grid(
            _("Плейлістів ще немає: створіть перший кнопкою «+» або додайте до нього треки через контекстне меню."),
            _("Двічі клацніть плейліст, щоб відтворити його."))
        blocked, self.block_grid = self.album_grid(
            _("Тут будуть альбоми й пісні з чорного списку: альбоми зникають із бібліотеки, а пісні пропускаються."),
            _("Двічі клацніть альбом, щоб відтворити його."))
        self.lib_pages = QStackedWidget()
        self.lib_pages.addWidget(page)
        self.lib_pages.addWidget(lists)
        self.lib_pages.addWidget(blocked)
        lay.addWidget(self.lib_pages, 1)
        self.lib_tabs = LibTabs(((_("Бібліотека"), ("folder-music-symbolic", "folder-music")),
                                 (_("Плейлісти"), ("view-list-symbolic", "view-media-playlist")),
                                 (_("Чорний список"), ("action-unavailable-symbolic", "dialog-cancel"))))
        lay.addWidget(self.lib_tabs)
        self.lib_tabs.currentChanged.connect(self.on_lib_tab)
        tab = QSettings(APP, "gui").value("library_tab", 0)
        self.lib_tabs.setCurrentIndex(int(tab) if str(tab).isdigit() else 0)
        self.on_lib_tab(self.lib_tabs.currentIndex())
        box.setMinimumWidth(360)        # дві колонки плиток
        return box

    def build_main_menu(self):
        button = QToolButton()
        button.setAutoRaise(True)
        button.setIcon(icon("open-menu-symbolic", "application-menu"))
        if button.icon().isNull():
            button.setText("⋯")
        button.setToolTip(_("Головне меню"))
        button.setPopupMode(QToolButton.InstantPopup)
        button.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        menu = QMenu(button)
        menu.addAction(icon("view-refresh"), _("Оновити"), self.reload_info)
        self.act_stop = menu.addAction(icon("media-playback-stop"), _("Зупинити копіювання"), lambda: self.action("stop"))
        menu.addAction(icon("edit-clear-history"), _("Видалити тимчасові файли"), lambda: self.action("clean"))
        menu.addSeparator()
        menu.addAction(icon("configure", "preferences-system"), _("Налаштування"), self.show_preferences)
        menu.addAction(icon("help-about"), _("Про програму"), self.about)
        menu.addAction(icon("application-exit"), _("Вийти"), self.quit_app)
        button.setMenu(menu)
        return button

    def show_preferences(self):
        self.prefs.show()
        self.prefs.raise_()

    def on_lib_tab(self, index):
        self.lib_pages.setCurrentIndex(index)
        QSettings(APP, "gui").setValue("library_tab", index)
        self.lib_sort.setVisible(index == 0)
        self.lib_add.setVisible(index < 2)
        if index:
            self.lib_add.setIcon(icon("list-add"))
            self.lib_add.setToolTip(_("Новий плейліст"))
        else:
            self.lib_add.setIcon(icon("folder-open"))
            self.lib_add.setToolTip(_("Покладіть теку з музикою в бібліотеку — альбом з'явиться тут"))

    def on_lib_add(self):
        if self.lib_tabs.currentIndex() == 1:
            self.new_playlist()
        else:
            self.open_dir(self.library_root())

    def rescan(self):
        self.request_scan.emit(self.library_root())

    def on_scanned(self, albums, playlists, blocked, folders):
        self.take_scan(albums, playlists, blocked)
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
        albums, playlists, blocked, current = self.library_rows()
        self.fill_grid(self.lib_list, *albums, current)
        self.fill_grid(self.list_grid, *playlists, current)
        self.fill_grid(self.block_grid, *blocked, current)
        self.lib_tabs.set_counts((len(albums[0]), len(playlists[0]), self.blocked_count()))

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
                item.setIcon(theme_icon(fallback) if fallback else heart_icon())
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

    # --- плейлісти -------------------------------------------------------------------------
    def selected_tracks(self):
        return sorted(self.tree.indexOfTopLevelItem(i) + 1 for i in self.tree.selectedItems())

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
        if new:
            self.rename_entry(path, new)

    def delete_playlist(self, path):
        if QMessageBox.question(self, _("Видалити плейліст…"), _("Видалити плейліст «{name}»? Самі треки залишаться в бібліотеці.",
                                                                 name=playlist_name(path))) != QMessageBox.Yes:
            return
        self.remove_entry(path)

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

    def on_tracks_moved(self):
        """Рядки перетягнули: нумерація в дереві ще стара, тож номер у рядку веде до треку."""
        tracks = self.info.get("tracks", [])
        if self.playlist_open() and self.tree.topLevelItemCount() == len(tracks):
            moved = {tracks[i.data(0, Qt.UserRole) - 1]["path"] for i in self.tree.selectedItems()}
            count = self.tree.topLevelItemCount()
            self.save_order([tracks[self.tree.topLevelItem(i).data(0, Qt.UserRole) - 1] for i in range(count)], moved)

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

    def add_artist_items(self, menu, artist):
        if artist:
            menu.addAction(icon("media-playback-start"), _("Відтворити лише {artist}", artist=artist),
                           lambda: self.play_artist(artist))
            menu.addAction(icon("document-open"), _("Усі треки: {artist}", artist=artist),
                           lambda: self.show_tile(ARTIST_KEY + artist))

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
        self.add_artist_items(menu, self.track_artist(chosen))
        first = len(menu.actions())
        self.add_menu(menu, links)
        if not links:
            menu.setToolTipsVisible(True)
            menu.actions()[first].setToolTip(_("Спершу дочекайтеся, поки трек скопіюється в бібліотеку."))
        block = menu.addAction(icon("dialog-cancel"), self.block_label(links), lambda: self.block_chosen(links))
        block.setEnabled(self.can_block(links))
        if self.playlist_open() and not self.is_blocked_open():
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
        if is_blocked_list(key):
            menu.addAction(icon("document-open"), _("Відкрити"), lambda: self.show_tile(key))
            menu.exec(grid.viewport().mapToGlobal(pos))
            return
        menu.addAction(icon("media-playback-start"), _("Відтворити"), lambda: self.play_tile(key))
        menu.addAction(icon("document-open"), _("Відкрити"), lambda: self.show_tile(key))
        self.add_artist_items(menu, self.tile_artist(key))
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
            menu.addAction(theme_icon("folder-music"), _("Відкрити теку альбому"), lambda: self.open_dir(key))
            menu.addSeparator()
            menu.addAction(icon("dialog-cancel"), self.album_block_label(key), lambda: self.toggle_album_block(key))
        menu.exec(grid.viewport().mapToGlobal(pos))

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
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("CD Auto Runner")
        menu = QMenu(self)
        menu.addAction(app_icon(), _("Показати / сховати вікно"), self.toggle_window)
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
        tray_icon = QIcon(rounded_pixmap(cover, 128)) if not cover.isNull() else app_icon()
        self.tray.showMessage(title, _("Відтворюю диск. Керувати ним можна зі значка в лотку або з системних елементів керування музикою."),
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
        proc.start(self_bin(), ["eject", dev])     # спершу відпускає привід, якщо його тримає gvfs

    def about(self):
        if not self.isVisible():        # з меню лотка: вікно діалогу без батьківського не видно
            self.show_window()
        box = QMessageBox(self)
        box.setWindowTitle(_("Про програму"))
        box.setIconPixmap(app_icon().pixmap(64, 64))
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
        geometry, state = settings.value("geometry"), settings.value("sidebar_split")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.split.restoreState(state)
        self.split.setHandleWidth(12)   # після restoreState — він повертає збережену ширину ручки

    def save_layout(self):
        settings = QSettings(APP, "gui")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("sidebar_split", self.split.saveState())

    def open_dir(self, path):
        if path:
            os.makedirs(path, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # --- диск ---------------------------------------------------------------------------
    def set_buttons(self, enabled):
        disc = enabled and not self.album_open()    # копіювати й називати можна лише диск
        for b in (self.btn_play, self.act_stop):
            b.setEnabled(enabled)
        for b in (self.btn_rip, self.act_mb):
            b.setEnabled(disc)
        self.btn_tag.setEnabled(enabled and self.can_edit())
        self.btn_tag.setText(_("Редагувати альбом") if self.album_open() else _("Ввести назви"))
        self.act_album.setEnabled(enabled and bool(self.info.get("LIBRARY_DIR")))

    def set_cover(self, path="", image=None):
        pix = QPixmap(path) if path else QPixmap.fromImage(image) if image else QPixmap()
        if pix.isNull():
            pix = app_icon().pixmap(128, 128)
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
        self.act_stop.setEnabled(True)
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
        self.badge.setText(self.badge_text())
        self.badge.setObjectName("warn" if i.get("SOURCE", "none") == "none" else "badge")
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
        self.tree.setColumnHidden(1, is_artist(self.info.get("ALBUM_DIR", "")))
        self.tree.setColumnHidden(5, not any(t.get("album") for t in self.info.get("tracks", [])))
        for t in self.info.get("tracks", []):
            item = QTreeWidgetItem([f"{t.get('num', t['n']):02d}", t["artist"], t["title"],
                                    fmt_time(t["sec"]) if t["sec"] else "", "", t.get("album", "")])
            blocked = self.track_blocked(t, self.info)
            if t.get("missing"):
                item.setText(4, _("файлу немає"))
                item.setIcon(4, icon("dialog-warning"))
            elif blocked:
                item.setText(4, _("у чорному списку"))
                item.setIcon(4, icon("dialog-cancel"))
            elif t.get("path"):
                item.setText(4, _("у бібліотеці"))
                item.setIcon(4, icon("emblem-ok-symbolic"))
            item.setData(0, Qt.UserRole, t["n"])
            if reorder:                 # рядки ставляться між іншими, а не всередину них
                item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)
            item.setTextAlignment(0, Qt.AlignRight | Qt.AlignVCenter)
            item.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
            if t["placeholder"] or blocked:
                for c in (1, 2, 5):
                    item.setForeground(c, muted)
                    item.setFont(c, italic)
            self.tree.addTopLevelItem(item)
        self.update_states()
        self.update_player()

    # --- живе оновлення ----------------------------------------------------------------
    def update_states(self):
        """Стан копіювання вставленого диска — навіть коли показано альбом бібліотеки."""
        i = self.disc
        shown = not self.album_open()
        if not i.get("tracks"):
            self.progress.hide()
            self.prog_label.setText("")
            return
        rows, done, ripping = self.disc_progress()
        for idx, (state, state_icon) in enumerate(rows):
            item = self.tree.topLevelItem(idx) if shown else None
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

    def can_background(self):
        """Лотка немає зовсім (GNOME без розширення), але музикою можна керувати через MPRIS."""
        return super().can_background() and not QSystemTrayIcon.isSystemTrayAvailable()

    def follow_scheme(self):
        """Тему змінили в системі: кольори вікна й значків задано під час побудови, тож вікно
        будуємо заново, як і зі зміною мови. Музику й відкриті діалоги не перериваємо."""
        if self.scheme and self.isVisible() and self.cur is None and not QApplication.activeModalWidget() \
                and portal_color_scheme() not in (0, self.scheme):
            self.restart_lang = LANG
            self.quit_app()

    def poll(self):
        self.follow_scheme()
        # вікно закрито, поки грала музика, і вона скінчилася — програма більше не потрібна
        if self.backgrounded and self.cur is None and not self.isVisible():
            self.quitting = True
            self.close()
            return
        self.poll_disc()

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
            words = line.split()
            if words[:1] == ["play"]:
                self.request_play()
                show = show or not self.play_in_tray()
            elif words:
                show = True
            if len(words) > 1:      # Wayland: фокус дає лише дозвіл, виданий запуску другого екземпляра
                os.environ["XDG_ACTIVATION_TOKEN"] = words[1]
        if show:
            self.backgrounded = False
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
                                      app_icon(), 6000)
            return
        if not self.quitting and self.can_background():
            event.ignore()
            self.hide()
            self.backgrounded = True
            settings = QSettings(APP, "gui")
            if settings.value("background_hint", "false") != "true" and read_config().get("NOTIFY", "yes") != "no":
                settings.setValue("background_hint", "true")
                QProcess.startDetached("notify-send", ["-a", "CD Auto Runner", "-i", APP,
                                                       "-h", f"string:desktop-entry:{APP}", "CD Auto Runner",
                                                       _("Музика грає далі. Керувати нею можна з системних елементів керування музикою, а вікно відкриється з меню програм.")])
            return
        super().closeEvent(event)
        QApplication.quit()

    def shutdown(self):
        """Перед виходом з програми (QApplication.aboutToQuit)."""
        if self.shut_down:
            return
        self.shut_down = True
        self.save_resume()
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
    scheme = follow_color_scheme(app)
    if GNOME and app.font().pointSizeF() >= 11:     # 11 pt GNOME щільний у GTK, а не у віджетах Qt
        font = app.font()
        font.setPointSizeF(font.pointSizeF() - 1)
        app.setFont(font)
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
    app.setWindowIcon(app_icon())

    # Вікно вже відкрите — передаємо йому команду й виходимо
    name = os.path.join(runtime_dir(), "gui.sock")
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(500):
        token = os.environ.get("XDG_ACTIVATION_TOKEN", "")
        sock.write(f"{'play' if play else 'show'} {token}\n".encode())
        sock.flush()
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.listen(name)

    app.setQuitOnLastWindowClosed(False)   # вікно може ховатися в лоток; виходить closeEvent
    win = MainWindow(play=play)
    win.scheme = scheme
    app.aboutToQuit.connect(win.shutdown)
    win.listen(server)
    if not (play and win.play_in_tray()):
        win.show()
    code = app.exec()
    if win.restart_lang:
        # exec, а не дочірній процес: той лишився б у cgroup юніта systemd і помер би разом зі старим
        env = dict(os.environ, CDAR_UI_LANG=win.restart_lang)
        flags = ["-I"] if sys.flags.isolated else ["-P"] if getattr(sys.flags, "safe_path", False) else []
        os.execve(sys.executable, [sys.executable, *flags, os.path.abspath(__file__)], env)
    return code


if __name__ == "__main__":
    sys.exit(main())
