#!/usr/bin/env python3
"""CD Auto Runner — головне вікно для GNOME (GTK 4, libadwaita).

Рівнозначна заміна вікна Qt (gui.py): обирається під час інсталяції (параметр GUI у налаштуваннях)
і робить те саме — усе, крім вигляду, спільне з ним (cdar_core.py). Системного лотка в GTK немає,
тож під час відтворення закрите вікно лише ховається, а музикою керують елементи MPRIS.

  gui_gtk.py [--play] [ПРИСТРІЙ]   --play — одразу відтворювати диск у вбудованому програвачі

CD Auto Runner main window for GNOME (GTK 4, libadwaita). An equal alternative to the Qt window,
chosen at install time. Everything but the looks is shared with it (cdar_core.py). GTK has no
system tray: while music plays, closing the window only hides it.

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor    # у Python 3.15 атрибут модуля лінивий і в потоці не спрацьовує

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Graphene, Gsk, Gtk, Pango     # noqa: E402

sys.path.append(os.path.dirname(os.path.abspath(__file__)))     # запуск з -I: спільний модуль лежить поруч
from cdar_core import (     # noqa: E402
    APP, FAVORITES, HOMEPAGE, LANG, LOOP_MODES, PLAYLIST_EXT, THUMB, TRACK_KEY, Controller, ThumbCache, _,
    album_from_tags, album_tags, connect_mpris, embedded_cover, favorites_path, fetch_cover, fmt_time, is_playlist,
    looks_same, musicbrainz, playlist_name, playlists_dir, read_album, read_config, read_disc, read_marker, run,
    runtime_dir, safe_name, script_version, self_bin, track_label, track_seconds, write_marker,
)

APP_ID = "io.github.PanVena.CdAutoRunner"       # те саме значення — у StartupWMClass (install.sh)
STATE_FILE = "gui-gtk.json"
TILE = 148
COVER = 168

# значки, що в core названо за темою Breeze
ICONS = {
    "media-optical-audio": "media-optical-cd-audio-symbolic",
    "view-media-playlist": "view-list-symbolic",
    "emblem-ok-symbolic": "object-select-symbolic",
    "document-save": "document-save-symbolic",
    "media-record": "media-record-symbolic",
    "media-playlist-repeat": "media-playlist-repeat-symbolic",
    "media-playlist-repeat-song": "media-playlist-repeat-song-symbolic",
}
HEART = f"{APP}-heart-symbolic"
HEART_ON = f"{APP}-heart-filled-symbolic"

CSS = """
.tile { border-radius: 14px; padding: 6px; }
.tile:hover { background: alpha(currentColor, .07); }
.tile.current { background: alpha(@accent_bg_color, .18); }
.tile.current .tile-title { font-weight: 700; }
.badge { border-radius: 99px; padding: 1px 10px; font-size: .85em;
         background: alpha(@accent_bg_color, .18); color: @accent_color; }
.badge.warning { background: alpha(@warning_bg_color, .22); color: @warning_color; }
row.drop-above { box-shadow: inset 0 2px 0 0 @accent_bg_color; }
row.drop-below { box-shadow: inset 0 -2px 0 0 @accent_bg_color; }
row.playing { font-weight: 700; }
.player { padding: 6px 12px 8px 12px; }
.track-number { font-feature-settings: "tnum"; }
"""


def background(fn, *args, done=None):
    """fn(*args) у потоці; done(результат) — у головному."""
    def work():
        result = fn(*args)
        if done:
            GLib.idle_add(lambda: (done(result), GLib.SOURCE_REMOVE)[1])
    threading.Thread(target=work, daemon=True).start()


class Worker(threading.Thread):
    """Послідовна черга робіт: диск може чекати на MusicBrainz, а перегляд бібліотеки — на теку."""

    def __init__(self):
        super().__init__(daemon=True)
        self.jobs = queue.SimpleQueue()
        self.start()

    def put(self, done, fn, *args):
        self.jobs.put((done, fn, args))

    def run(self):
        while True:
            done, fn, args = self.jobs.get()
            try:
                result = fn(*args)
            except Exception:           # черга має працювати далі: це лише один перегляд теки
                traceback.print_exc()
                continue
            GLib.idle_add(lambda d=done, r=result: (d(r), GLib.SOURCE_REMOVE)[1])


# --- стан вікна: розмір, гучність тощо ---------------------------------------------------
class UiState:
    def __init__(self):
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        self.path = os.path.join(base, APP, STATE_FILE)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default):
        return self.data.get(key, default)

    def put(self, key, value):
        if self.data.get(key) == value:
            return
        self.data[key] = value
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(f"{self.path}.part", "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(f"{self.path}.part", self.path)
        except OSError:
            pass


# --- рушій вбудованого програвача: mpv у фоні, керування через JSON IPC --------------------
class Mpv:
    """mpv без вікна (--idle). Окремий процес: програма лише надсилає йому команди. Подіями
    вікна керують поля on_position, on_duration, on_paused, on_ended і on_failed."""

    def __init__(self):
        self.proc = None
        self.sock = None
        self.watch = 0
        self.buf = b""
        self.pending = []
        self.tries = 0
        self.volume = 100
        self.path = os.path.join(runtime_dir(), f"mpv-{os.getpid()}.sock")
        self.on_position = self.on_duration = self.on_paused = self.on_ended = self.on_failed = lambda *_a: None

    @staticmethod
    def available():
        return shutil.which("mpv") is not None

    def running(self):
        return self.proc is not None

    def start(self):
        if self.running():
            return
        try:
            os.remove(self.path)
        except OSError:
            pass
        self.sock, self.buf, self.tries = None, b"", 0
        argv = ["mpv", "--idle=yes", "--no-video", "--force-window=no", "--no-terminal", "--audio-display=no",
                "--input-default-bindings=no", "--gapless-audio=weak", "--title=CD Auto Runner",
                # перекриваємо налаштування mpv.conf, що заважали б переходу на наступний трек
                "--keep-open=no", "--loop-file=no", "--loop-playlist=no", "--resume-playback=no",
                "--save-position-on-quit=no",
                # без скриптів (зокрема mpv-mpris): у системі програвач показує саме вікно
                "--load-scripts=no",
                f"--volume={self.volume}", f"--input-ipc-server={self.path}"]
        try:
            self.proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_SILENCE)
        except GLib.Error:
            self.proc = None
            self.on_failed()
            return
        self.proc.wait_async(None, self._finished)
        GLib.timeout_add(100, self._connect)

    def _connect(self):
        if not self.running():
            return GLib.SOURCE_REMOVE
        sock = socket.socket(socket.AF_UNIX)
        try:
            sock.connect(self.path)
        except OSError:
            sock.close()
            self.tries += 1
            if self.tries < 100:         # до ~10 с
                return GLib.SOURCE_CONTINUE
            self.quit()
            self.on_failed()
            return GLib.SOURCE_REMOVE
        self.sock = sock
        self.watch = GLib.io_add_watch(sock.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self._read)
        for i, name in enumerate(("time-pos", "duration", "pause"), 1):
            self._write({"command": ["observe_property", i, name]})
        pending, self.pending = self.pending, []
        for cmd in pending:
            self._write(cmd)
        return GLib.SOURCE_REMOVE

    def _write(self, cmd):
        try:
            self.sock.sendall(json.dumps(cmd).encode() + b"\n")
        except OSError:
            pass

    def command(self, *args):
        cmd = {"command": list(args)}
        if self.sock:
            self._write(cmd)
        else:
            self.pending.append(cmd)
            self.start()

    def _read(self, *_a):
        try:
            data = self.sock.recv(65536) if self.sock else b""
        except OSError:
            data = b""
        if not data:
            self._close_socket(remove_watch=False)
            return GLib.SOURCE_REMOVE
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        for line in lines:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            ev = msg.get("event")
            if ev == "property-change":
                name, value = msg.get("name"), msg.get("data")
                if name == "time-pos":
                    self.on_position(float(value or 0))
                elif name == "duration":
                    self.on_duration(float(value or 0))
                elif name == "pause":
                    self.on_paused(bool(value))
            elif ev == "end-file":
                self.on_ended(msg.get("reason", ""))
        return GLib.SOURCE_CONTINUE

    def _close_socket(self, remove_watch=True):
        if self.sock:
            if remove_watch and self.watch:
                GLib.source_remove(self.watch)
            self.sock.close()
        self.sock, self.watch = None, 0

    def _finished(self, proc, result):
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        if proc is self.proc:
            self.proc = None
            self._close_socket()
            self.pending = []
            self.on_ended("quit")

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
        proc, self.proc = self.proc, None       # _finished більше не сповіщатиме вікно
        if self.sock:
            self._write({"command": ["quit"]})
        self._close_socket()
        proc.send_signal(15)
        try:
            os.remove(self.path)
        except OSError:
            pass


# --- обкладинки -------------------------------------------------------------------------
def thumbnail(path):
    """Зменшена обкладинка; GdkPixbuf можна читати у фоновому потоці."""
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, THUMB, THUMB, True)
    except GLib.Error:
        return None


def texture(pix):
    """Pixbuf → текстура для малювання (лише в головному потоці)."""
    fmt = Gdk.MemoryFormat.R8G8B8A8 if pix.get_has_alpha() else Gdk.MemoryFormat.R8G8B8
    return Gdk.MemoryTexture.new(pix.get_width(), pix.get_height(), fmt, pix.read_pixel_bytes(), pix.get_rowstride())


def load_texture(path):
    pix = thumbnail(path) if path else None
    return texture(pix) if pix else None


def fingerprint(pix):
    """Зменшена копія обкладинки: той самий малюнок може лежати в кількох теках різними файлами."""
    small = pix.scale_simple(12, 12, GdkPixbuf.InterpType.BILINEAR)
    data, stride, step = small.get_pixels(), small.get_rowstride(), small.get_n_channels()
    return bytes(b for y in range(12) for x in range(12) for b in data[y * stride + x * step:y * stride + x * step + 3])


def different_covers(covers, limit=4):
    """Перші limit обкладинок із різними малюнками; covers — пари (шлях, зображення)."""
    picked, prints = [], []
    for path, pix in covers:
        if pix is None:
            continue
        mark = fingerprint(pix)
        if not any(looks_same(mark, seen) for seen in prints):
            picked.append((path, pix))
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
    out = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, THUMB, THUMB)
    out.fill(0)
    for i, pix in enumerate(images[:4]):
        scale = min(half / pix.get_width(), half / pix.get_height())
        w, h = max(1, round(pix.get_width() * scale)), max(1, round(pix.get_height() * scale))
        x, y = (i % 2) * half + (half - w) // 2, (i // 2) * half + (half - h) // 2
        pix.composite(out, x, y, w, h, x, y, scale, scale, GdkPixbuf.InterpType.BILINEAR, 255)
    return out


def playlist_mosaic(covers):
    picked = different_covers(covers)
    return mosaic([pix for _path, pix in picked]), [path for path, _pix in picked]


class CoverArt(Gtk.Widget):
    """Обкладинка із закругленими кутами: заповнює квадрат (краї обрізаються), а без малюнка
    показує значок. Окремий віджет, бо Gtk.Picture просить місця за розміром зображення."""

    def __init__(self, size, radius=12):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.size, self.radius = size, radius
        self.path = None
        self.texture = None
        self.icon = "media-optical-cd-audio-symbolic"
        self.disc = False

    def set_art(self, tex, icon=None, disc=False):
        self.texture, self.disc = tex, disc
        if icon:
            self.icon = icon
        self.queue_draw()

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_measure(self, _orientation, _for_size):
        return self.size, self.size, -1, -1

    @staticmethod
    def circle(snap, cx, cy, r, color):
        clip = Gsk.RoundedRect()
        box = Graphene.Rect().init(cx - r, cy - r, 2 * r, 2 * r)
        clip.init_from_rect(box, r)
        snap.push_rounded_clip(clip)
        snap.append_color(color, box)
        snap.pop()

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        bounds = Graphene.Rect().init(0, 0, w, h)
        clip = Gsk.RoundedRect()
        clip.init_from_rect(bounds, self.radius)
        snap.push_rounded_clip(clip)
        if self.texture:
            tw, th = self.texture.get_width(), self.texture.get_height()
            scale = max(w / tw, h / th)
            box = Graphene.Rect().init((w - tw * scale) / 2, (h - th * scale) / 2, tw * scale, th * scale)
            snap.append_scaled_texture(self.texture, Gsk.ScalingFilter.TRILINEAR, box)
        else:
            color = self.get_color()
            fill = Gdk.RGBA()
            fill.red, fill.green, fill.blue, fill.alpha = color.red, color.green, color.blue, 0.1
            snap.append_color(fill, bounds)
            size = min(w, h) // 2
            theme = Gtk.IconTheme.get_for_display(self.get_display())
            paintable = theme.lookup_icon(self.icon, None, size, self.get_scale_factor(), Gtk.TextDirection.NONE, 0)
            snap.save()
            point = Graphene.Point()
            point.init((w - size) / 2, (h - size) / 2)
            snap.translate(point)
            paintable.snapshot_symbolic(snap, size, size, [color])
            snap.restore()
        snap.pop()
        if self.disc:               # альбом із диска: світлий диск на темному колі видно на будь-якій обкладинці
            size = max(26, self.size // 6)
            cx, cy = w - size / 2 - 5, h - size / 2 - 5
            dark, light = Gdk.RGBA(), Gdk.RGBA()
            dark.parse("rgba(0,0,0,.67)")
            light.parse("#f0f0f0")
            self.circle(snap, cx, cy, size / 2, dark)
            self.circle(snap, cx, cy, size * 0.36, light)
            self.circle(snap, cx, cy, size * 0.1, dark)


# --- дрібні помічники інтерфейсу -----------------------------------------------------------
def label(text="", classes=(), xalign=0.0, ellipsize=False, wrap=False):
    w = Gtk.Label(label=text, xalign=xalign, css_classes=list(classes))
    if ellipsize:
        w.set_ellipsize(Pango.EllipsizeMode.END)
    w.set_wrap(wrap)
    if wrap:
        w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return w


def icon_button(name, tip, handler=None, classes=("flat",), action=None, toggle=False):
    kind = Gtk.ToggleButton if toggle else Gtk.Button
    b = kind(icon_name=name, tooltip_text=tip, css_classes=list(classes), valign=Gtk.Align.CENTER)
    b.update_property([Gtk.AccessibleProperty.LABEL], [tip])
    if handler:
        b.connect("clicked", handler)
    if action:
        b.set_action_name(action)
    return b


def text_button(icon, text, classes=(), action=None):
    content = Adw.ButtonContent(icon_name=icon, label=text)
    return Gtk.Button(child=content, css_classes=list(classes), action_name=action)


def on_context(widget, handler):
    """Правий клік або довге натискання: handler(x, y)."""
    click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
    click.connect("pressed", lambda _g, _n, x, y: handler(x, y))
    widget.add_controller(click)
    hold = Gtk.GestureLongPress(touch_only=True)
    hold.connect("pressed", lambda _g, x, y: handler(x, y))
    widget.add_controller(hold)


def popup_menu(popover, model, x, y):
    popover.set_menu_model(model)
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
    popover.set_pointing_to(rect)
    popover.popup()


def make_popover(parent):
    popover = Gtk.PopoverMenu.new_from_model(None)
    popover.set_parent(parent)
    popover.set_has_arrow(False)
    popover.set_halign(Gtk.Align.START)
    return popover


def menu_item(text, action, target=None):
    item = Gio.MenuItem.new(text, None)
    item.set_action_and_target_value(action, GLib.Variant("s", target) if target is not None else None)
    return item


def alert(parent, title, body, responses, handler=None, default="cancel", extra=None):
    """Діалог: responses — пари (ідентифікатор, підпис); destructive/suggested — за ідентифікатором."""
    dialog = Adw.AlertDialog(heading=title, body=body)
    for key, text in responses:
        dialog.add_response(key, text)
        if key in ("delete",):
            dialog.set_response_appearance(key, Adw.ResponseAppearance.DESTRUCTIVE)
        elif key in ("ok", "grant", "create", "rename"):
            dialog.set_response_appearance(key, Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response(key)
    dialog.set_close_response(default)
    if extra:
        dialog.set_extra_child(extra)
    if handler:
        dialog.connect("response", lambda _d, response: handler(response))
    dialog.present(parent)
    return dialog


def image_filters():
    images = Gtk.FileFilter(name=_("Зображення"))
    images.add_pixbuf_formats()
    store = Gio.ListStore.new(Gtk.FileFilter)
    store.append(images)
    return store


def pick_image(parent, folder, callback):
    """Діалог вибору зображення: callback(шлях)."""
    dialog = Gtk.FileDialog(title=_("Вибрати обкладинку…"), filters=image_filters(),
                            initial_folder=Gio.File.new_for_path(folder))

    def done(d, result):
        try:
            callback(d.open_finish(result).get_path())
        except GLib.Error:
            pass        # скасовано
    dialog.open(parent, None, done)


def save_jpeg(source, target):
    """Зображення source → JPEG target; False — не вдалося."""
    try:
        pix = GdkPixbuf.Pixbuf.new_from_file(source)
        pix.savev(f"{target}.part", "jpeg", ["quality"], ["92"])
        os.replace(f"{target}.part", target)
        return True
    except (GLib.Error, OSError):
        return False


# --- редактор альбому ---------------------------------------------------------------------
class TrackEdit(Gtk.ListBoxRow):
    """Рядок редактора: виконавець, назва, ім'я файлу."""

    def __init__(self, editor, artist, title, name):
        super().__init__(activatable=False, selectable=False)
        self.name = name
        box = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6, margin_start=10, margin_end=6)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        row = Gtk.Box(spacing=6, homogeneous=False)
        self.artist = Gtk.Entry(text=artist, placeholder_text=_("Виконавець"), width_chars=14, hexpand=True)
        self.title = Gtk.Entry(text=title, placeholder_text=_("Назва"), width_chars=20, hexpand=True)
        row.append(self.artist)
        row.append(self.title)
        col.append(row)
        col.append(label(name, ("caption", "dim-label"), ellipsize=True))
        box.append(col)
        if not editor.from_disc:        # порядок диска задано самим диском
            box.append(icon_button("go-up-symbolic", _("Вище"), lambda _b: editor.move_row(self, -1)))
            box.append(icon_button("go-down-symbolic", _("Нижче"), lambda _b: editor.move_row(self, 1)))
        self.set_child(box)


class AlbumEditor(Adw.Dialog):
    """Відомості про альбом у бібліотеці: з тегів файлів, MusicBrainz або введені вручну.
    Зберігає лише мітку й cover.jpg — самі аудіофайли не змінюються, тож посилання плейлістів
    лишаються чинними. Альбом, скопійований із диска, зберігає нумерацію за диском."""

    def __init__(self, win, album):
        super().__init__(title=_("Редагування альбому"), content_width=760, content_height=720)
        self.win = win
        self.album = album
        self.folder = album["ALBUM_DIR"]
        self.marker = read_marker(self.folder)
        self.from_disc = bool(self.marker.get("DISCID"))
        self.mbid = self.marker.get("MBID", "")
        self.cover_path = album["COVER"]
        self.new_cover = ""         # вибрана обкладинка; запишеться в cover.jpg під час збереження
        self.tmp = tempfile.TemporaryDirectory(prefix=f"{APP}-")
        self.releases = []
        self.online = read_config().get("ONLINE", "yes") == "yes"
        self.numbers = {os.path.basename(t["path"]): t["num"] for t in album["tracks"]}

        head = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancel = Gtk.Button(label=_("Скасувати"))
        cancel.connect("clicked", lambda _b: self.close())
        save = Gtk.Button(label=_("Зберегти"), css_classes=["suggested-action"])
        save.connect("clicked", lambda _b: self.save())
        head.pack_start(cancel)
        head.pack_end(save)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=12, margin_bottom=24,
                       margin_start=12, margin_end=12)
        top = Gtk.Box(spacing=16)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.preview = CoverArt(136)
        pick = Gtk.Button(label=_("Обкладинка"), tooltip_text=_("Вибрати обкладинку…"))
        pick.connect("clicked", lambda _b: pick_image(self.win, self.folder, self.take_cover))
        col.append(self.preview)
        col.append(pick)
        top.append(col)
        group = Adw.PreferencesGroup(hexpand=True)
        self.f_album = Adw.EntryRow(title=_("Альбом:").rstrip(":"), text=album["ALBUM"])
        self.f_artist = Adw.EntryRow(title=_("Виконавець альбому:").rstrip(":"), text=album["ALBUM_ARTIST"])
        self.f_year = Adw.EntryRow(title=_("Рік:").rstrip(":"), text=album["YEAR"], max_length=4)
        for row in (self.f_album, self.f_artist, self.f_year):
            group.add(row)
        top.append(group)
        body.append(top)

        row = Gtk.Box(spacing=8)
        self.btn_search = Gtk.Button(label=_("Знайти в MusicBrainz"), sensitive=False)
        self.btn_search.connect("clicked", lambda _b: self.search())
        self.btn_apply = Gtk.Button(label=_("Застосувати"), visible=False)
        self.btn_apply.connect("clicked", lambda _b: self.apply())
        self.status = label("" if self.online else _("Вимкнено в налаштуваннях (MusicBrainz)."),
                            ("dim-label",), wrap=True)
        self.status.set_hexpand(True)
        row.append(self.btn_search)
        row.append(self.btn_apply)
        row.append(self.status)
        body.append(row)

        self.found = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.SINGLE, visible=False)
        self.found.connect("row-activated", lambda _l, _r: self.apply())
        body.append(self.found)

        self.tracks = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        for t in album["tracks"]:
            same = t["artist"] == album["ALBUM_ARTIST"]
            self.tracks.append(TrackEdit(self, "" if same else t["artist"], t["title"], os.path.basename(t["path"])))
        body.append(self.tracks)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=Adw.Clamp(child=body, maximum_size=760))
        view = Adw.ToolbarView(content=scroller)
        view.add_top_bar(head)
        self.set_child(view)
        self.connect("closed", lambda _d: self.tmp.cleanup())
        self.show_cover(self.cover_path)
        # поки читаються теги, пошук вимкнено: вони заповнюють ті самі поля
        background(album_tags, [t["path"] for t in album["tracks"]], done=self.on_tags)

    def rows(self):
        return list(self.tracks)

    def show_cover(self, path):
        self.preview.set_art(load_texture(path))

    def take_cover(self, path):
        self.new_cover = path
        self.show_cover(path)

    def on_tags(self, tags):
        """Теги файлів — якщо альбом ще не описано; обкладинка з файлу — якщо своєї немає."""
        self.btn_search.set_sensitive(self.online)
        if not tags:
            return
        if not self.cover_path and not self.new_cover:
            with_cover = next((i for i, t in enumerate(tags) if t.get("_cover")), None)
            if with_cover is not None:
                background(embedded_cover, self.album["tracks"][with_cover]["path"],
                           os.path.join(self.tmp.name, "embedded.img"), done=self.on_found_cover)
        if any(TRACK_KEY.fullmatch(k) for k in self.marker):
            return
        rows = self.rows()
        album, artist, year, data = album_from_tags(tags, [r.name for r in rows], [r.title.get_text() for r in rows])
        if album:
            self.f_album.set_text(album)
        if artist:
            self.f_artist.set_text(artist)
        if year:
            self.f_year.set_text(year)
        for row in rows:
            self.tracks.remove(row)
        for track_artist, title, name in data:
            same = track_artist == self.f_artist.get_text()
            self.tracks.append(TrackEdit(self, "" if same else track_artist, title, name))

    def on_found_cover(self, path):
        if path and not self.new_cover:
            self.take_cover(path)

    def on_mb_cover(self, path):
        if path:
            self.take_cover(path)

    def search(self):
        self.btn_search.set_sensitive(False)
        self.btn_apply.set_visible(False)
        self.found.set_visible(False)
        self.status.set_text(_("Шукаю…"))
        background(musicbrainz, "--list", self.f_artist.get_text().strip(), self.f_album.get_text().strip(),
                   str(len(self.rows())), done=self.on_found)

    def on_found(self, releases):
        self.btn_search.set_sensitive(True)
        if releases is None:
            self.status.set_text(_("Не вдалося звернутися до MusicBrainz."))
            return
        if not releases:
            self.status.set_text(_("Нічого не знайдено: уточніть назву й виконавця або заповніть усе самі."))
            return
        self.releases = releases
        self.found.remove_all()
        for r in releases:
            more = " · ".join(str(x) for x in (r["artist"], r["year"], r["country"], r["format"],
                                               _("треків: {n}", n=r["tracks"])) if x)
            self.found.append(Adw.ActionRow(title=r["title"], subtitle=more, use_markup=False, activatable=True))
        self.found.select_row(self.found.get_row_at_index(0))
        self.found.set_visible(True)
        self.btn_apply.set_visible(True)
        self.status.set_text(_("Оберіть реліз і натисніть «Застосувати». Спершу йдуть релізи з такою самою кількістю треків."))

    def apply(self):
        row = self.found.get_selected_row()
        if row is None or not self.btn_apply.get_sensitive():
            return
        self.btn_apply.set_sensitive(False)
        self.status.set_text(_("Читаю реліз…"))
        background(musicbrainz, "--release", self.releases[row.get_index()]["id"], str(len(self.rows())),
                   done=self.on_release)

    def on_release(self, release):
        self.btn_apply.set_sensitive(True)
        if release is None:
            self.status.set_text(_("Не вдалося звернутися до MusicBrainz."))
            return
        self.mbid = release["id"]
        self.f_album.set_text(release["title"])
        self.f_artist.set_text(release["artist"])
        self.f_year.set_text(release["year"])
        rows, tracks = self.rows(), release["tracks"]
        for row, t in zip(rows, tracks):
            row.artist.set_text("" if t["artist"] == release["artist"] else t["artist"])
            row.title.set_text(t["title"])
        self.status.set_text(_("Застосовано. Перевірте, чи назви відповідають файлам.") if len(tracks) == len(rows) else
                             _("У релізі треків: {a}, а в теці: {b}. Перевірте, чи назви відповідають файлам.",
                               a=len(tracks), b=len(rows)))
        if release["cover"]:
            background(fetch_cover, release["id"], os.path.join(self.tmp.name, "musicbrainz.jpg"), done=self.on_mb_cover)

    def move_row(self, row, step):
        to = row.get_index() + step
        if 0 <= to < len(self.rows()):
            self.tracks.remove(row)
            self.tracks.insert(row, to)

    def save(self):
        head = {"ALBUM": self.f_album.get_text().strip(), "ALBUM_ARTIST": self.f_artist.get_text().strip(),
                "YEAR": self.f_year.get_text().strip()}
        if self.mbid:
            head["MBID"] = self.mbid
        rows = []
        for i, row in enumerate(self.rows()):
            key = self.numbers[row.name] if self.from_disc else i + 1
            rows.append((key, "" if self.from_disc else row.name, row.artist.get_text().strip(), row.title.get_text().strip()))
        try:
            if self.new_cover and not save_jpeg(self.new_cover, os.path.join(self.folder, "cover.jpg")):
                raise OSError(_("Не вдалося зберегти обкладинку."))
            write_marker(self.folder, head, rows)
        except OSError as e:
            self.win.warn(_("Не вдалося записати зміни: {e}", e=e), parent=self)
            return
        self.win.after_edit()
        self.close()


# --- налаштування -------------------------------------------------------------------------
class Preferences(Adw.PreferencesDialog):
    FORMATS = (("flac", "FLAC — без втрат"), ("opus", "Opus 160 кбіт/с — малий розмір"),
               ("ogg", "Ogg Vorbis q6"), ("mp3", "MP3 VBR ~190 кбіт/с"), ("wav", "WAV — без перекодування"))
    LANGS = (("en", "English"), ("uk", "Українська"))

    def __init__(self, win):
        super().__init__(title=_("Налаштування"), search_enabled=False)
        self.win = win
        self.loading = True
        self.players = []           # (id, назва)
        page = Adw.PreferencesPage()

        group = Adw.PreferencesGroup(title=_("Відтворення"))
        self.player = Adw.ComboRow(title=_("Програвач:").rstrip(":"), model=Gtk.StringList(), sensitive=False)
        self.player.connect("notify::selected", self.on_player)
        self.service = Adw.SwitchRow(title=_("Автозапуск при вставлянні диска"), subtitle=_("Служба не встановлена"))
        self.service.connect("notify::active", self.on_service)
        self.notify_row = self.switch("NOTIFY", _("Сповіщення"))
        for row in (self.player, self.service, self.notify_row):
            group.add(row)
        page.add(group)

        group = Adw.PreferencesGroup(title=_("Копіювання і бібліотека"), description=_(
            "Формат і бібліотека стосуються вбудованого програвача, програвачів, яким треки копіюються (Elisa, QMPlay2, Audacious), і кнопки «Скопіювати в бібліотеку»."))
        self.fmt = Adw.ComboRow(title=_("Формат:").rstrip(":"), model=Gtk.StringList.new([_(t) for _k, t in self.FORMATS]))
        self.fmt.connect("notify::selected", self.on_format)
        self.library = self.switch("LIBRARY", _("Зберігати альбоми в бібліотеку музики"))
        self.folder = Adw.ActionRow(title=_("Тека:").rstrip(":"), use_markup=False)
        self.folder.set_subtitle_selectable(True)
        change = Gtk.Button(label=_("Змінити…"), valign=Gtk.Align.CENTER)
        change.connect("clicked", lambda _b: self.pick_folder())
        reset = Gtk.Button(label=_("Типова"), valign=Gtk.Align.CENTER, css_classes=["flat"])
        reset.connect("clicked", lambda _b: self.set_value("LIBRARY_DIR", ""))
        self.folder.add_suffix(reset)
        self.folder.add_suffix(change)
        self.online = self.switch("ONLINE", _("Брати назви й обкладинки з MusicBrainz"))
        for row in (self.fmt, self.library, self.folder, self.online):
            group.add(row)
        page.add(group)

        group = Adw.PreferencesGroup(title=_("Інтерфейс"))
        self.lang = Adw.ComboRow(title=_("Мова:").rstrip(":"), model=Gtk.StringList.new([t for _k, t in self.LANGS]))
        self.lang.set_selected(next((i for i, (k, _t) in enumerate(self.LANGS) if k == LANG), 0))
        self.lang.connect("notify::selected", self.on_lang)
        group.add(self.lang)
        page.add(group)

        self.add(page)
        self.load()
        self.update_service()
        self.timer = GLib.timeout_add_seconds(3, self.tick)
        self.connect("closed", self.on_closed)
        background(run, "list", done=self.on_players)

    def switch(self, key, title):
        row = Adw.SwitchRow(title=title, use_markup=False)
        row.connect("notify::active", lambda r, _p: self.set_value(key, "yes" if r.get_active() else "no"))
        return row

    def tick(self):
        self.update_service()
        return GLib.SOURCE_CONTINUE

    def on_closed(self, _dialog):
        GLib.source_remove(self.timer)

    def load(self):
        """Показує налаштування з файлу, не записуючи їх назад."""
        self.loading = True
        cfg = read_config()
        self.fmt.set_selected(next((i for i, (k, _t) in enumerate(self.FORMATS) if k == cfg.get("RIP_FORMAT", "flac")), 0))
        self.library.set_active(cfg.get("LIBRARY", "yes") == "yes")
        self.online.set_active(cfg.get("ONLINE", "yes") == "yes")
        self.notify_row.set_active(cfg.get("NOTIFY", "yes") == "yes")
        self.folder.set_subtitle(cfg.get("LIBRARY_DIR") or f"{self.win.library_root()}  ({_('системна тека «Музика»')})")
        self.loading = False

    def on_players(self, result):
        code, out, _err = result
        cfg = read_config()
        self.players = [tuple(line.split("\t")[:2]) for line in out.splitlines() if len(line.split("\t")) >= 2]
        if cfg.get("PLAYER_ID") == "custom":
            self.players.append(("custom", _("Власна команда")))
        self.players.append(("off", _("Нічого не запускати")))
        self.loading = True
        self.player.set_model(Gtk.StringList.new([name for _i, name in self.players]))
        self.player.set_selected(next((i for i, (k, _n) in enumerate(self.players) if k == cfg.get("PLAYER_ID", "")), 0))
        self.player.set_sensitive(True)
        self.loading = False

    def set_value(self, key, value):
        if self.loading:
            return

        def finished(result):
            code, _o, err = result
            if code:
                self.win.warn(err.strip() or _("Не вдалося виконати дію."), parent=self)
            else:
                self.add_toast(Adw.Toast(title=_("Збережено"), timeout=2))
            self.load()
            if key == "LIBRARY_DIR":
                self.win.rescan()
        background(run, "set", key, value, done=finished)

    def on_format(self, row, _param):
        self.set_value("RIP_FORMAT", self.FORMATS[row.get_selected()][0])

    def pick_folder(self):
        dialog = Gtk.FileDialog(title=_("Тека бібліотеки музики"),
                                initial_folder=Gio.File.new_for_path(self.win.library_root()))

        def done(d, result):
            try:
                self.set_value("LIBRARY_DIR", d.select_folder_finish(result).get_path())
            except GLib.Error:
                pass    # скасовано
        dialog.select_folder(self.win, None, done)

    def on_player(self, row, _param):
        if self.loading or not self.players:
            return
        pid, name = self.players[row.get_selected()]
        if pid == "custom":
            return
        if pid == "off":
            self.set_player(pid)
        else:
            background(run, "perm", pid, done=lambda result: self.check_perm(pid, name, result[1].strip()))

    def check_perm(self, pid, name, needed):
        if not needed:
            self.set_player(pid)
            return
        arg, fid = needed.split("\t", 1)

        def answered(response):
            if response == "grant":
                background(subprocess.run, ["flatpak", "override", "--user", arg, fid],
                           done=lambda _r: self.set_player(pid))
            else:
                self.set_player(pid)
        alert(self, _("Потрібен дозвіл"), _("{name} встановлено як Flatpak, і йому бракує дозволу:\n\nflatpak override --user {arg} {fid}\n\nНадати?",
                                            name=name, arg=arg, fid=fid),
              (("cancel", _("Пізніше")), ("grant", _("Надати"))), answered)

    def set_player(self, pid):
        def finished(result):
            code, _o, err = result
            if code:
                self.win.warn(err.strip(), parent=self)
            else:
                self.add_toast(Adw.Toast(title=_("Збережено"), timeout=2))
            background(run, "list", done=self.on_players)
        background(run, "set-player", pid, done=finished)

    def on_service(self, row, _param):
        if not self.loading:
            background(run, "enable" if row.get_active() else "disable", done=lambda _r: self.update_service())

    def update_service(self):
        def query():
            out = []
            for verb in ("is-enabled", "is-active"):
                try:
                    out.append(subprocess.run(["systemctl", "--user", verb, f"{APP}.service"], capture_output=True,
                                              text=True, timeout=5).stdout.strip())
                except (OSError, subprocess.TimeoutExpired):
                    out.append("")
            return out

        def show(states):
            enabled, active = states
            installed = enabled not in ("", "not-found")
            self.loading = True
            self.service.set_sensitive(installed)
            self.service.set_active(enabled == "enabled")
            self.loading = False
            if not installed:
                self.service.set_subtitle(_("Служба не встановлена"))
            else:
                self.service.set_subtitle(_("Служба працює") if active == "active" else _("Служба зупинена"))
        background(query, done=show)

    def on_lang(self, row, _param):
        lang = self.LANGS[row.get_selected()][0]
        if lang != LANG:
            self.win.change_language(lang)


# --- рядки й плитки ------------------------------------------------------------------------
class TrackRow(Adw.ActionRow):
    def __init__(self, track, album_artist, reorder):
        title = track["title"] or _("Трек {n}", n=track["n"])
        artist = track["artist"] if track["artist"] != album_artist else ""
        super().__init__(title=title, subtitle=artist, use_markup=False, activatable=True, title_lines=1, subtitle_lines=1)
        self.track = track
        self.stack = Gtk.Stack(hhomogeneous=True)
        self.number = label(f"{track.get('num', track['n']):02d}", ("dim-label", "track-number"), xalign=1.0)
        self.playing = Gtk.Image()
        self.stack.add_named(self.number, "number")
        self.stack.add_named(self.playing, "icon")
        self.stack.set_size_request(28, -1)
        self.add_prefix(self.stack)
        self.state_icon = Gtk.Image(visible=False)
        self.state = label("", ("caption", "dim-label"))
        self.time = label(fmt_time(track["sec"]) if track["sec"] else "", ("dim-label", "track-number"), xalign=1.0)
        self.add_suffix(self.state_icon)
        self.add_suffix(self.state)
        self.add_suffix(self.time)
        if track["placeholder"]:
            self.add_css_class("dim-label")
        if track.get("missing"):
            self.set_state(_("файлу немає"), "dialog-warning-symbolic")
        elif track.get("path"):
            self.set_state(_("у бібліотеці"), "emblem-ok-symbolic")
        if reorder:
            source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
            source.connect("prepare", self.on_drag_prepare)
            self.add_controller(source)

    def on_drag_prepare(self, _source, _x, _y):
        return Gdk.ContentProvider.new_for_value(GObject.Value(str, str(self.track["n"])))

    def set_state(self, text, icon):
        self.state.set_text(text)
        self.state_icon.set_visible(bool(icon))
        if icon:
            self.state_icon.set_from_icon_name(ICONS.get(icon, icon))

    def set_playing(self, icon):
        """icon — значок поточного треку; None — це не поточний трек."""
        if icon:
            self.playing.set_from_icon_name(icon)
            self.add_css_class("playing")
        else:
            self.remove_css_class("playing")
        self.stack.set_visible_child_name("icon" if icon else "number")


class Tile(Gtk.FlowBoxChild):
    """Плитка альбому: обкладинка, під нею назва й підпис в один рядок кожен."""

    def __init__(self, win, grid, row, tex):
        super().__init__(css_classes=["tile"])
        key, title, sub, _cover, more, _stamp, fallback, ripped = row
        self.key = key
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.cover = CoverArt(TILE)
        self.cover.set_art(tex, ICONS.get(fallback, fallback) or HEART, ripped)
        box.append(self.cover)
        title_label = label(title, ("tile-title",), ellipsize=True)
        title_label.set_max_width_chars(1)
        title_label.set_margin_top(4)
        sub_label = label(sub or "", ("caption", "dim-label"), ellipsize=True)
        sub_label.set_max_width_chars(1)
        box.append(title_label)
        box.append(sub_label)
        self.set_child(box)
        hint = "\n".join(x for x in (title, sub if not key or not more else "", more) if x)
        self.set_tooltip_text(f"{hint}\n{grid.hint}")
        click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        click.connect("pressed", lambda _g, n, _x, _y: n == 1 and win.open_tile(key))
        self.add_controller(click)
        on_context(self, lambda x, y: win.on_tile_menu(self, x, y))


class Grid(Gtk.Box):
    """Вкладка бібліотеки: сітка плиток або підпис, якщо їх немає."""

    def __init__(self, win, empty_text, hint):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self.hint = win, hint
        self.shown = None
        self.tiles = {}
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, activate_on_single_click=False,
                                min_children_per_line=2, max_children_per_line=12, column_spacing=4, row_spacing=4,
                                margin_top=6, margin_bottom=6, margin_start=6, margin_end=6, valign=Gtk.Align.START)
        self.flow.connect("child-activated", lambda _f, tile: win.play_tile(tile.key))
        self.empty = label(empty_text, ("dim-label",), wrap=True, xalign=0.5)
        for side in ("top", "bottom", "start", "end"):
            getattr(self.empty, f"set_margin_{side}")(18)
        self.append(self.empty)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.flow)
        self.append(self.scroller)

    def fill(self, rows, thumbs, current, allow_single):
        if rows != self.shown:
            self.shown = rows
            scroll = self.scroller.get_vadjustment().get_value()
            self.flow.remove_all()
            self.tiles = {}
            for row in rows:
                key, cover = row[0], row[3]
                pix = thumbs.get(key) if key else thumbnail(cover) if cover else None
                tile = Tile(self.win, self, row, texture(pix) if pix else None)
                self.tiles[key] = tile
                self.flow.append(tile)
            GLib.idle_add(lambda: (self.scroller.get_vadjustment().set_value(scroll), GLib.SOURCE_REMOVE)[1])
            # плейліст «Улюблене» є завжди, тож підпис потрібен, поки немає інших
            self.empty.set_visible(len(rows) < 2 if allow_single else not rows)
            self.scroller.set_visible(bool(rows))
        for key, tile in self.tiles.items():
            if key == current:
                tile.add_css_class("current")
            else:
                tile.remove_css_class("current")


# --- головне вікно -------------------------------------------------------------------------
class MainWindow(Controller, Adw.ApplicationWindow):
    def __init__(self, app, play=False):
        Adw.ApplicationWindow.__init__(self, application=app, title="CD Auto Runner")
        self.state = UiState()
        self.init_state(play)
        self.busy = False
        self.mpris = None
        self.quitting = False       # «Вийти»: закриття вікна завершує програму, а не ховає її
        self.backgrounded = False   # вікно закрито, а музика ще грає
        self.restart_lang = None    # мову змінено: main() перезапустить програму з новою мовою
        self.shut_down = False
        self.seeking = 0            # таймер відкладеного переходу на позицію
        self.rows = []
        self.menu_links = []
        self.prefs = None
        self.version = ""
        self.mpv = Mpv() if Mpv.available() else None
        self.thumbs = ThumbCache(thumbnail, playlist_mosaic)
        self.info_jobs, self.lib_jobs = Worker(), Worker()
        self.monitors = {}          # музику кладуть у теку поза програмою
        self.scan_timer = 0

        self.set_default_size(self.state.get("width", 1120), self.state.get("height", 780))
        self.set_size_request(360, 480)
        if self.state.get("maximized", False):
            self.maximize()
        self.build_actions()
        self.set_content(self.build_layout())
        self.connect("close-request", self.on_close)
        if self.mpv:
            self.mpv.volume = self.volume()
            self.mpv.on_position = self.on_position
            self.mpv.on_duration = self.on_duration
            self.mpv.on_paused = self.on_paused
            self.mpv.on_ended = self.on_ended
            self.mpv.on_failed = self.on_mpv_failed
            self.mpris = connect_mpris(self)
        self.show_empty()
        self.update_player()
        self.rescan()
        background(script_version, done=lambda v: setattr(self, "version", v))
        GLib.timeout_add_seconds(2, self.poll)
        GLib.idle_add(lambda: (self.poll(), GLib.SOURCE_REMOVE)[1])     # перший опит — коли вікно вже на екрані

    # --- те, чого потребує Controller -------------------------------------------------
    def ui_get(self, key, default):
        return self.state.get(key, default)

    def ui_put(self, key, value):
        self.state.put(key, value)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def warn(self, text, parent=None):
        alert(parent or self, _("Помилка"), text, (("cancel", _("Гаразд")),))

    def start_detached(self, program, args):
        try:
            Gio.Subprocess.new([program, *args], Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as e:         # notify-send необов'язковий
            print(e.message, file=sys.stderr)

    def played_unseen(self):
        pass        # без лотка вікно відкривається завжди

    def load_info(self):
        self.info_jobs.put(self.on_info, read_disc)

    def load_times(self, folder, paths):
        def measure():
            if not shutil.which("ffprobe"):
                return {}
            with ThreadPoolExecutor(4) as pool:
                return dict(zip(paths, pool.map(track_seconds, paths)))
        self.lib_jobs.put(lambda times: times and self.on_times(folder, times), measure)

    def current_track(self):
        chosen = self.selected_tracks()
        return chosen[0] if chosen else None

    def selected_tracks(self):
        return sorted(row.get_index() + 1 for row in self.tracks.get_selected_rows())

    def select_tracks(self, numbers):
        for n in numbers:
            self.tracks.select_row(self.rows[n - 1])

    def volume(self):
        return round(self.vol.get_value()) if hasattr(self, "vol") else int(self.state.get("volume", 100))

    def apply_volume(self, value):
        self.vol.set_value(value)

    def show_times(self):
        for row, t in zip(self.rows, self.info["tracks"]):
            if t["sec"]:
                row.time.set_text(fmt_time(t["sec"]))
        self.show_meta()

    def show_window(self):
        self.backgrounded = False
        self.set_visible(True)
        self.present()

    def quit_app(self):
        self.quitting = True
        self.close()

    # --- дії меню ------------------------------------------------------------------------
    def build_actions(self):
        plain = {
            "play": lambda: self.on_play(), "rip": lambda: self.action("rip"), "tag": self.on_tag,
            "stop-rip": lambda: self.action("stop"), "eject": self.eject, "refresh": self.reload_info,
            "clean": lambda: self.action("clean"), "open-album": lambda: self.open_dir(self.info.get("LIBRARY_DIR", "")),
            "open-library": lambda: self.open_dir(self.library_root()), "add-disc": self.add_to_musicbrainz,
            "preferences": self.show_preferences, "about": self.about, "quit": self.quit_app,
            "play-pause": self.toggle_play, "next": self.next_track, "previous": self.prev_track,
            "stop-playback": self.stop_playback, "new-playlist": lambda: self.new_playlist(),
            "tracks-play": lambda: self.start_track(self.selected_tracks()[0]),
            "tracks-new-playlist": lambda: self.new_playlist(self.menu_links),
            "tracks-favorite": lambda: self.toggle_favorite(self.menu_links),
            "tracks-up": lambda: self.move_tracks(-1), "tracks-down": lambda: self.move_tracks(1),
            "tracks-remove": self.remove_tracks,
        }
        for name, handler in plain.items():
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda _a, _p, h=handler: h())
            self.add_action(act)
        keyed = {
            "tile-play": self.play_tile, "tile-open": self.open_tile, "tile-rename": self.rename_playlist,
            "tile-cover": self.set_playlist_cover, "tile-cover-clear": self.remove_playlist_cover,
            "tile-delete": self.delete_playlist, "tile-edit": self.edit_album, "tile-folder": self.open_dir,
            "add-to": lambda path: self.add_to_playlist(path, self.menu_links),
        }
        for name, handler in keyed.items():
            act = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            act.connect("activate", lambda _a, p, h=handler: h(p.get_string()))
            self.add_action(act)

    def enable(self, name, on):
        self.lookup_action(name).set_enabled(on)

    # --- побудова вікна ------------------------------------------------------------------
    def build_layout(self):
        self.split = Adw.NavigationSplitView(min_sidebar_width=330, max_sidebar_width=520, sidebar_width_fraction=0.36)
        self.split.set_sidebar(self.build_sidebar())
        self.split.set_content(self.build_content())

        self.toasts = Adw.ToastOverlay(child=self.split)
        outer = Adw.ToolbarView(content=self.toasts, bottom_bar_style=Adw.ToolbarStyle.RAISED)
        outer.add_bottom_bar(self.build_progress())
        outer.add_bottom_bar(self.build_player())

        tablet = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 760sp"))
        tablet.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(tablet)
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 520sp"))
        narrow.add_setter(self.split, "collapsed", True)
        narrow.add_setter(self.album_top, "orientation", Gtk.Orientation.VERTICAL)
        for widget in (self.p_stop, self.p_shuffle, self.p_loop, self.p_cover):
            narrow.add_setter(widget, "visible", False)
        self.add_breakpoint(narrow)
        return outer

    def main_menu(self):
        menu = Gio.Menu()
        disc = Gio.Menu()
        disc.append(_("Оновити"), "win.refresh")
        disc.append(_("Зупинити копіювання"), "win.stop-rip")
        disc.append(_("Видалити тимчасові файли"), "win.clean")
        disc.append(_("Відкрити бібліотеку музики"), "win.open-library")
        menu.append_section(None, disc)
        app = Gio.Menu()
        app.append(_("Налаштування"), "win.preferences")
        app.append(_("Про програму"), "win.about")
        app.append(_("Вийти"), "win.quit")
        menu.append_section(None, app)
        return menu

    def build_sidebar(self):
        self.lib_stack = Adw.ViewStack()
        self.lib_list = Grid(self, _("Тут з'являтимуться скопійовані диски."),
                             _("Двічі клацніть альбом, щоб відтворити його."))
        self.list_grid = Grid(self, _("Плейлістів ще немає: створіть перший кнопкою «+» або додайте до нього треки через контекстне меню."),
                              _("Двічі клацніть плейліст, щоб відтворити його."))
        self.lib_stack.add_titled_with_icon(self.lib_list, "library", _("Бібліотека"), "folder-music-symbolic")
        self.lib_stack.add_titled_with_icon(self.list_grid, "playlists", _("Плейлісти"), "view-list-symbolic")
        self.lib_stack.set_visible_child_name(self.state.get("library_tab", "library"))
        self.lib_stack.connect("notify::visible-child-name", self.on_lib_tab)

        head = Adw.HeaderBar(title_widget=Adw.ViewSwitcher(stack=self.lib_stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.lib_add = icon_button("list-add-symbolic", "", self.on_lib_add)
        head.pack_start(self.lib_add)
        head.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=self.main_menu(),
                                     tooltip_text=_("Головне меню"), primary=True))
        self.tile_menu = make_popover(self.lib_stack)
        view = Adw.ToolbarView(content=self.lib_stack)
        view.add_top_bar(head)
        self.on_lib_tab()
        return Adw.NavigationPage(title="CD Auto Runner", tag="library", child=view)

    def on_lib_tab(self, *_a):
        tab = self.lib_stack.get_visible_child_name()
        self.state.put("library_tab", tab)
        playlists = tab == "playlists"
        self.lib_add.set_icon_name("list-add-symbolic" if playlists else "folder-open-symbolic")
        self.lib_add.set_tooltip_text(_("Новий плейліст") if playlists else
                                      _("Покладіть теку з музикою в бібліотеку — альбом з'явиться тут"))

    def on_lib_add(self, _button):
        if self.lib_stack.get_visible_child_name() == "playlists":
            self.new_playlist()
        else:
            self.open_dir(self.library_root())

    def build_content(self):
        self.page = Adw.NavigationPage(title=_("Диск"), tag="album")
        self.status = Adw.StatusPage(icon_name="media-optical-cd-audio-symbolic")

        self.cover = CoverArt(COVER)
        self.title_label = label("", ("title-1",), wrap=True)
        self.title_label.set_selectable(True)
        self.subtitle = label("", ("title-4",), ellipsize=True)
        self.meta = label("", ("dim-label",))
        self.badge = label("", ("badge",))
        self.badge.set_valign(Gtk.Align.CENTER)
        meta_row = Gtk.Box(spacing=10)
        meta_row.append(self.meta)
        meta_row.append(self.badge)
        self.btn_play = text_button("media-playback-start-symbolic", _("Відтворити"),
                                    ("suggested-action", "pill"), "win.play")
        self.btn_rip = text_button("document-save-symbolic", _("Скопіювати в бібліотеку"), ("pill",), "win.rip")
        self.btn_tag = text_button("document-edit-symbolic", _("Ввести назви"), ("pill",), "win.tag")
        buttons = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6,
                              min_children_per_line=1, max_children_per_line=3, halign=Gtk.Align.START, margin_top=8)
        for b in (self.btn_play, self.btn_rip, self.btn_tag):
            buttons.append(b)
            b.get_parent().set_focusable(False)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True, valign=Gtk.Align.CENTER)
        for w in (self.title_label, self.subtitle, meta_row, buttons):
            col.append(w)
        self.album_top = top = Gtk.Box(spacing=20)
        top.append(self.cover)
        top.append(col)

        self.tracks = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.MULTIPLE,
                                  activate_on_single_click=False)
        self.tracks.connect("row-activated", lambda _l, row: self.on_track_activated(row.get_index() + 1))
        on_context(self.tracks, self.on_tracks_menu)
        drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
        drop.connect("motion", self.on_drag_motion)
        drop.connect("leave", lambda _t: self.clear_drop())
        drop.connect("drop", self.on_drop)
        self.tracks.add_controller(drop)
        self.drop_row = None

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18, margin_bottom=18,
                       margin_start=12, margin_end=12)
        body.append(top)
        body.append(self.tracks)
        self.track_menu = make_popover(body)    # не списку: ListBox.remove_all() чіпає всіх дочірніх
        album = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                   child=Adw.Clamp(child=body, maximum_size=900, tightening_threshold=600))
        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.pages.add_named(self.status, "status")
        self.pages.add_named(album, "album")

        head = Adw.HeaderBar()
        self.album_menu = Gio.Menu()
        self.album_menu.append(_("Відкрити теку альбому"), "win.open-album")
        self.album_menu.append(_("Додати диск у MusicBrainz"), "win.add-disc")
        head.pack_end(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=self.album_menu,
                                     tooltip_text=_("Меню альбому")))
        head.pack_end(icon_button("media-eject-symbolic", _("Вийняти диск"), action="win.eject"))
        view = Adw.ToolbarView(content=self.pages)
        view.add_top_bar(head)
        self.page.set_child(view)
        return self.page

    def build_progress(self):
        box = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=4, margin_bottom=4)
        self.prog_label = label("", ("caption",), ellipsize=True)
        self.prog_label.set_hexpand(True)
        self.progress = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=140)
        self.prog_stop = icon_button("process-stop-symbolic", _("Зупинити копіювання"), action="win.stop-rip")
        for w in (self.prog_label, self.progress, self.prog_stop):
            box.append(w)
        self.prog_bar = Gtk.Revealer(child=box, reveal_child=False)
        return self.prog_bar

    def build_player(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["player"])
        row = Gtk.Box(spacing=8)
        self.t_pos = label("0:00", ("caption", "dim-label", "track-number"))
        self.t_len = label("0:00", ("caption", "dim-label", "track-number"))
        self.seek = Gtk.Scale(hexpand=True, draw_value=False, adjustment=Gtk.Adjustment(upper=0, step_increment=5))
        self.seek.connect("change-value", self.on_seek)
        self.seek.update_property([Gtk.AccessibleProperty.LABEL], [_("Час")])
        row.append(self.t_pos)
        row.append(self.seek)
        row.append(self.t_len)
        box.append(row)

        start = Gtk.Box(spacing=10)
        self.p_cover = CoverArt(44, radius=6)
        self.now = label("", ellipsize=True)
        self.now.set_hexpand(True)
        self.now.set_width_chars(6)
        start.append(self.p_cover)
        start.append(self.now)

        center = Gtk.Box(spacing=2)
        self.p_prev = icon_button("media-skip-backward-symbolic", _("Попередній трек"), lambda _b: self.prev_track())
        self.p_play = icon_button("media-playback-start-symbolic", _("Відтворити / пауза"), lambda _b: self.toggle_play(),
                                  ("circular", "suggested-action"))
        self.p_stop = icon_button("media-playback-stop-symbolic", _("Зупинити відтворення"), lambda _b: self.stop_playback())
        self.p_next = icon_button("media-skip-forward-symbolic", _("Наступний трек"), lambda _b: self.next_track())
        for b in (self.p_prev, self.p_play, self.p_stop, self.p_next):
            center.append(b)

        end = Gtk.Box(spacing=2)
        self.p_shuffle = icon_button("media-playlist-shuffle-symbolic", _("Перемішувати"), toggle=True)
        self.shuffle_id = self.p_shuffle.connect("toggled", lambda b: self.set_shuffle(b.get_active()))
        self.p_loop = icon_button("media-playlist-repeat-symbolic", "", lambda _b: self.cycle_loop(), toggle=True)
        self.p_fav = icon_button(HEART, _("Додати до улюбленого"), lambda _b: self.on_favorite(), toggle=True)
        self.vol = Gtk.Scale(orientation=Gtk.Orientation.VERTICAL, inverted=True, draw_value=False, height_request=130,
                             adjustment=Gtk.Adjustment(lower=0, upper=100, step_increment=5, page_increment=10))
        self.vol.set_value(int(self.state.get("volume", 100)))
        self.vol.connect("value-changed", self.on_volume)
        self.vol.update_property([Gtk.AccessibleProperty.LABEL], [_("Гучність")])
        self.p_vol = Gtk.MenuButton(icon_name="audio-volume-high-symbolic", tooltip_text=_("Гучність"), css_classes=["flat"],
                                    popover=Gtk.Popover(child=self.vol), valign=Gtk.Align.CENTER)
        for b in (self.p_shuffle, self.p_loop, self.p_fav, self.p_vol):
            end.append(b)

        bar = Gtk.CenterBox(start_widget=start, center_widget=center, end_widget=end)
        box.append(bar)
        return box

    # --- програвач --------------------------------------------------------------------------
    def on_track_activated(self, n):
        if self.info.get("tracks") and (self.mpv or not self.plays_here()):
            self.start_track(n)
        elif not self.album_open():
            self.action("tag", reload=True)

    def on_position(self, sec):
        self.pos = sec
        if not self.seeking:
            self.seek.set_value(sec)
        self.t_pos.set_text(fmt_time(sec))

    def on_duration(self, sec):
        self.length = sec
        self.seek.get_adjustment().set_upper(sec)
        self.t_len.set_text(fmt_time(sec))
        if self.mpris:
            self.mpris.refresh()

    def on_seek(self, _scale, _scroll, value):
        """Перетягування дає багато значень: переходимо на останнє, коли воно перестало мінятися."""
        if self.seeking:
            GLib.source_remove(self.seeking)
        self.seeking = GLib.timeout_add(150, self.finish_seek)
        self.t_pos.set_text(fmt_time(value))
        return False

    def finish_seek(self):
        self.seeking = 0
        self.seek_to(self.seek.get_value())
        return GLib.SOURCE_REMOVE

    def on_volume(self, scale):
        value = round(scale.get_value())
        self.state.put("volume", value)
        self.p_vol.set_icon_name("audio-volume-muted-symbolic" if not value else
                                 "audio-volume-low-symbolic" if value < 34 else
                                 "audio-volume-medium-symbolic" if value < 67 else "audio-volume-high-symbolic")
        if self.mpv:
            self.mpv.set_volume(value)
        if self.mpris:
            self.mpris.refresh()

    def update_player(self):
        on = self.mpv is not None and bool(self.player_info().get("tracks"))
        for b in (self.p_prev, self.p_play, self.p_stop, self.p_next, self.seek):
            b.set_sensitive(on)
        self.p_vol.set_sensitive(self.mpv is not None)
        self.p_shuffle.set_sensitive(self.mpv is not None)
        self.p_loop.set_sensitive(self.mpv is not None)
        link = self.track_link(self.cur, self.queue) if self.cur is not None else None
        favorite = link is not None and link[0] in self.favs
        self.p_fav.set_sensitive(link is not None)
        self.p_fav.set_active(favorite)
        self.p_fav.set_icon_name(HEART_ON if favorite else HEART)
        self.p_fav.set_tooltip_text(_("Прибрати з улюбленого") if favorite else _("Додати до улюбленого"))
        self.p_shuffle.handler_block(self.shuffle_id)
        self.p_shuffle.set_active(self.shuffle)
        self.p_shuffle.handler_unblock(self.shuffle_id)
        loop_icon, loop_tip = LOOP_MODES[self.loop]
        self.p_loop.set_active(self.loop != "None")
        self.p_loop.set_icon_name(ICONS[loop_icon])
        self.p_loop.set_tooltip_text(_(loop_tip))
        playing = self.cur is not None and self.want is None and not self.is_paused
        self.p_play.set_icon_name("media-playback-pause-symbolic" if playing else "media-playback-start-symbolic")
        self.now.set_text(self.now_text())
        self.now.set_tooltip_text(self.now_text())
        self.show_player_cover()
        self.mark_playing()
        if self.mpris:
            self.mpris.refresh()

    def show_player_cover(self):
        t = (self.track_title(self.cur) or {}) if self.cur is not None else {}
        path = t.get("cover") or self.queue.get("COVER", "") if self.cur is not None else ""
        if path != self.p_cover.path:
            self.p_cover.path = path
            self.p_cover.set_art(load_texture(path))

    def mark_playing(self):
        here = self.showing_queue()     # у чужому альбомі трек із тим самим номером не грає
        for i, row in enumerate(self.rows):
            if not (here and self.cur == i + 1):
                row.set_playing(None)
            elif self.want is not None:
                row.set_playing("media-record-symbolic")
            else:
                row.set_playing("media-playback-pause-symbolic" if self.is_paused else "media-playback-start-symbolic")

    # --- бібліотека --------------------------------------------------------------------------
    def rescan(self):
        self.lib_jobs.put(self.on_scanned, self.thumbs.scan, self.library_root())

    def on_scanned(self, result):
        self.albums, self.playlists, folders = result
        self.load_favorites()
        known, now = set(self.monitors), set(folders)
        for folder in known - now:
            self.monitors.pop(folder).cancel()
        for folder in now - known:
            try:
                monitor = Gio.File.new_for_path(folder).monitor_directory(Gio.FileMonitorFlags.NONE, None)
            except GLib.Error:
                continue
            monitor.connect("changed", self.on_folder_changed)
            self.monitors[folder] = monitor
        if self.playlist_open():        # обкладинка плейліста складається з його треків
            self.set_cover(self.info["COVER"], self.playlist_image())
        self.fill_library()
        self.update_player()

    def on_folder_changed(self, *_a):
        if self.scan_timer:             # копіювання теки — це багато змін поспіль
            GLib.source_remove(self.scan_timer)
        self.scan_timer = GLib.timeout_add(1500, self.scan_later)

    def scan_later(self):
        self.scan_timer = 0
        self.rescan()
        return GLib.SOURCE_REMOVE

    def fill_library(self):
        albums, playlists, current = self.library_rows()
        self.lib_list.fill(*albums, current, False)
        self.list_grid.fill(*playlists, current, True)

    def open_tile(self, key):
        """Показує плитку; у вузькому вікні — переходить до списку треків."""
        self.show_tile(key)
        self.split.set_show_content(True)

    def play_tile(self, key):
        if self.show_tile(key):
            self.split.set_show_content(True)
            self.on_play()

    def on_tile_menu(self, tile, x, y):
        key = tile.key
        if not key:
            return
        menu = Gio.Menu()
        first = Gio.Menu()
        first.append_item(menu_item(_("Відтворити"), "win.tile-play", key))
        first.append_item(menu_item(_("Відкрити"), "win.tile-open", key))
        menu.append_section(None, first)
        if is_playlist(key):
            favorites = os.path.basename(key) == FAVORITES + PLAYLIST_EXT
            edit = Gio.Menu()
            if not favorites:
                edit.append_item(menu_item(_("Перейменувати…"), "win.tile-rename", key))
            edit.append_item(menu_item(_("Вибрати обкладинку…"), "win.tile-cover", key))
            if os.path.isfile(os.path.splitext(key)[0] + ".jpg"):
                edit.append_item(menu_item(_("Прибрати обкладинку"), "win.tile-cover-clear", key))
            menu.append_section(None, edit)
            if not favorites:
                gone = Gio.Menu()
                gone.append_item(menu_item(_("Видалити плейліст…"), "win.tile-delete", key))
                menu.append_section(None, gone)
        else:
            album = next((a for a in self.albums if a["ALBUM_DIR"] == key), None)
            tracks = album["tracks"] if album else []
            self.add_menu(menu, [(os.path.normpath(t["path"]), track_label(t)) for t in tracks])
            more = Gio.Menu()
            more.append_item(menu_item(_("Редагувати альбом…"), "win.tile-edit", key))
            more.append_item(menu_item(_("Відкрити теку альбому"), "win.tile-folder", key))
            menu.append_section(None, more)
        point = tile.compute_point(self.lib_stack, Graphene.Point().init(x, y))
        popup_menu(self.tile_menu, menu, point[1].x, point[1].y)

    def add_menu(self, menu, links):
        """Підменю «Додати до плейліста» і дія улюбленого для цих треків."""
        self.menu_links = links
        section = Gio.Menu()
        sub = Gio.Menu()
        for p in self.playlists[1:]:
            sub.append_item(menu_item(p["ALBUM"], "win.add-to", p["PLAYLIST"]))
        sub.append(_("Новий плейліст…"), "win.tracks-new-playlist")
        section.append_submenu(_("Додати до плейліста"), sub)
        self.enable("tracks-new-playlist", bool(links))
        self.enable("add-to", bool(links))
        self.enable("tracks-favorite", bool(links))
        if not self.is_favorites_open():
            favorite = bool(links) and {link[0] for link in links} <= self.favs
            section.append(_("Прибрати з улюбленого") if favorite else _("Додати до улюбленого"), "win.tracks-favorite")
        menu.append_section(None, section)

    def on_tracks_menu(self, x, y):
        row = self.tracks.get_row_at_y(int(y))
        if row is None:
            return
        if not row.is_selected():
            self.tracks.unselect_all()
            self.tracks.select_row(row)
        chosen = self.selected_tracks()
        links = [link for link in (self.track_link(n, self.info) for n in chosen) if link]
        menu = Gio.Menu()
        first = Gio.Menu()
        first.append(_("Відтворити"), "win.tracks-play")
        menu.append_section(None, first)
        self.add_menu(menu, links)
        if self.playlist_open():
            more = Gio.Menu()
            more.append(_("Вище"), "win.tracks-up")
            more.append(_("Нижче"), "win.tracks-down")
            more.append(_("Прибрати з плейліста"), "win.tracks-remove")
            self.enable("tracks-up", chosen[0] > 1)
            self.enable("tracks-down", chosen[-1] < len(self.rows))
            menu.append_section(None, more)
        point = self.tracks.compute_point(self.track_menu.get_parent(), Graphene.Point().init(x, y))
        popup_menu(self.track_menu, menu, point[1].x, point[1].y)

    # --- перетягування рядків плейліста ---
    def clear_drop(self):
        if self.drop_row:
            self.drop_row.remove_css_class("drop-above")
            self.drop_row.remove_css_class("drop-below")
            self.drop_row = None

    def drop_place(self, y):
        """(рядок під курсором, вставляти перед ним); рядка немає — кінець списку."""
        row = self.tracks.get_row_at_y(int(y))
        if row is None:
            return None, False
        top = row.compute_point(self.tracks, Graphene.Point().init(0, 0))[1].y
        return row, y < top + row.get_height() / 2

    def on_drag_motion(self, _target, _x, y):
        if not self.playlist_open():
            return 0
        self.clear_drop()
        row, above = self.drop_place(y)
        if row:
            row.add_css_class("drop-above" if above else "drop-below")
            self.drop_row = row
        return Gdk.DragAction.MOVE

    def on_drop(self, _target, value, _x, y):
        self.clear_drop()
        if not self.playlist_open():
            return False
        tracks = self.info["tracks"]
        row, above = self.drop_place(y)
        dragged = int(value)
        chosen = self.selected_tracks()
        moved = chosen if dragged in chosen else [dragged]
        place = len(tracks) if row is None else row.get_index() + (0 if above else 1)
        place -= sum(1 for n in moved if n - 1 < place)
        rest = [t for t in tracks if t["n"] not in moved]
        order = rest[:place] + [tracks[n - 1] for n in moved] + rest[place:]
        if order != tracks:
            # чергою: список перебудовується вже після того, як GTK закінчить перетягування
            GLib.idle_add(lambda: (self.save_order(order, {tracks[n - 1]["path"] for n in moved}), GLib.SOURCE_REMOVE)[1])
        return True

    # --- плейлісти ---------------------------------------------------------------------------
    def ask_playlist_name(self, title, text, callback, confirm):
        """Запитує назву: callback(шлях) — лише для вільної назви."""
        entry = Gtk.Entry(text=text, activates_default=True, placeholder_text=_("Назва плейліста:").rstrip(":"))

        def answered(response):
            if response not in ("create", "rename"):
                return
            name = safe_name(entry.get_text())
            if not name:
                return
            path = os.path.join(playlists_dir(self.library_root()), name + PLAYLIST_EXT)
            if os.path.exists(path) or path == favorites_path(self.library_root()):
                self.warn(_("Плейліст із такою назвою вже є."))
            else:
                callback(path)
        key, word = confirm
        alert(self, title, "", (("cancel", _("Скасувати")), (key, word)), answered, extra=entry)

    def new_playlist(self, links=()):
        links = list(links)

        def create(path):
            if self.store_playlist(path, list({link[0]: link for link in links}.values())):
                self.lib_stack.set_visible_child_name("playlists")
        self.ask_playlist_name(_("Новий плейліст"), "", create, ("create", _("Створити")))

    def rename_playlist(self, path):
        self.ask_playlist_name(_("Перейменувати плейліст"), playlist_name(path), lambda new: self.rename_entry(path, new),
                               ("rename", _("Перейменувати")))

    def delete_playlist(self, path):
        alert(self, _("Видалити плейліст…").rstrip("…"), _("Видалити плейліст «{name}»? Самі треки залишаться в бібліотеці.",
                                                          name=playlist_name(path)),
              (("cancel", _("Скасувати")), ("delete", _("Видалити"))),
              lambda response: response == "delete" and self.remove_entry(path))

    def set_playlist_cover(self, path):
        def chosen(image):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if save_jpeg(image, os.path.splitext(path)[0] + ".jpg"):
                self.after_cover(path)
            else:
                self.warn(_("Не вдалося зберегти обкладинку."))
        pick_image(self, self.library_root(), chosen)

    def edit_album(self, folder):
        album = read_album(folder, self.library_root())
        if not album:
            self.toast(_("Не вдалося відкрити альбом."))
            self.rescan()
            return
        AlbumEditor(self, album).present(self)

    def after_edit(self):
        # назви могли змінитися й у плейлісті, що показаний або грає
        for key in {self.info.get("ALBUM_DIR"), self.queue.get("ALBUM_DIR")} - {None}:
            self.reload_entry(key)
        self.rescan()

    def on_tag(self):
        if self.album_open():
            self.edit_album(self.info["ALBUM_DIR"])
        else:
            self.action("tag", reload=True)

    # --- показане ------------------------------------------------------------------------
    def set_cover(self, path="", image=None):
        tex = texture(image) if image else load_texture(path)
        self.cover.set_art(tex)

    def update_actions(self, enabled):
        disc = enabled and not self.album_open()    # копіювати й називати можна лише диск
        self.enable("play", enabled)
        self.enable("rip", disc)
        self.enable("add-disc", disc and bool(self.info.get("MB_URL")))
        self.enable("open-album", enabled and bool(self.info.get("LIBRARY_DIR")))
        self.enable("tag", enabled and not self.playlist_open())
        self.enable("eject", self.last_tracks > 0)
        self.btn_tag.get_child().set_label(_("Редагувати альбом") if self.album_open() else _("Ввести назви"))
        self.btn_rip.set_visible(disc)

    def show_status(self, title, detail, spinner=False):
        self.status.set_title(title)
        self.status.set_description(GLib.markup_escape_text(detail or ""))
        self.status.set_child(Gtk.Spinner(spinning=True, width_request=32, height_request=32) if spinner else None)
        self.pages.set_visible_child_name("status")
        self.page.set_title(title)

    def show_empty(self, title=None, detail=None):
        self.show_status(title or _("Вставте аудіо-CD"),
                         detail or _("Обраний програвач запуститься сам, щойно ви вставите диск."))
        self.tracks.remove_all()
        self.rows = []
        self.update_actions(False)
        self.update_player()
        self.fill_library()

    def show_loading(self):
        self.show_status(_("Читаю диск…"), "", spinner=True)
        self.update_actions(False)

    def show_disc(self):
        i = self.info
        self.set_cover(i.get("COVER", ""), self.playlist_image())
        self.title_label.set_text(i.get("ALBUM", ""))
        self.page.set_title(i.get("ALBUM", "") or _("Диск"))
        sub = i.get("ALBUM_ARTIST", "")
        if i.get("YEAR"):
            sub += f"  ·  {i['YEAR']}"
        self.subtitle.set_text(sub)
        self.subtitle.set_visible(bool(sub))
        self.show_meta()
        self.badge.set_text(self.badge_text())
        if i.get("SOURCE", "none") == "none":
            self.badge.add_css_class("warning")
        else:
            self.badge.remove_css_class("warning")
        self.update_actions(True)
        self.pages.set_visible_child_name("album")
        self.fill_tracks()
        self.fill_library()

    def show_meta(self):
        tracks = self.info["tracks"]
        total = sum(t["sec"] for t in tracks)
        text = _("треків: {n}", n=len(tracks))
        self.meta.set_text(f"{text}  ·  {fmt_time(total)}" if total else text)

    def fill_tracks(self):
        self.tracks.remove_all()
        reorder = bool(self.playlist_open())
        album_artist = self.info.get("ALBUM_ARTIST", "")
        self.rows = [TrackRow(t, album_artist, reorder) for t in self.info.get("tracks", [])]
        for row in self.rows:
            self.tracks.append(row)
        self.update_states()
        self.update_player()

    # --- живе оновлення ----------------------------------------------------------------
    def update_states(self):
        """Стан копіювання вставленого диска — навіть коли показано альбом бібліотеки."""
        i = self.disc
        if not i.get("tracks"):
            self.prog_bar.set_reveal_child(False)
            return
        rows, done, ripping = self.disc_progress()
        if not self.album_open():
            for row, (state, state_icon) in zip(self.rows, rows):
                row.set_state(state, state_icon)
        total = len(i["tracks"])
        self.prog_bar.set_reveal_child(bool(ripping))
        if ripping:
            self.progress.set_fraction(done / total if total else 0)
            self.progress.set_text(f"{done}/{total}")
            self.prog_label.set_text(_("Копіюю трек {t} · {done} з {total}", t=ripping, done=done, total=total))

    def update_service(self):
        pass        # стан служби видно в налаштуваннях: вони оновлюють його самі, поки відкриті

    def poll(self):
        # вікно закрито, поки грала музика, і вона скінчилася — програма більше не потрібна
        if self.backgrounded and self.cur is None:
            self.quit_app()
            return GLib.SOURCE_REMOVE
        self.poll_disc()
        self.enable("eject", self.last_tracks > 0)
        return GLib.SOURCE_CONTINUE

    # --- дії ------------------------------------------------------------------------------
    def spawn(self, args, done):
        """Команда cd-auto-runner: done(код виходу, stderr)."""
        try:
            proc = Gio.Subprocess.new([self_bin(), *args], Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as e:
            done(1, e.message)
            return

        def finished(p, result):
            try:
                _ok, _out, err = p.communicate_utf8_finish(result)
                done(p.get_exit_status(), err or "")
            except GLib.Error as e:
                done(1, e.message)
        proc.communicate_utf8_async(None, None, finished)

    def action(self, name, reload=False, extra=()):
        if self.busy and name != "stop":
            return
        args = [name] + ([self.info["DEVICE"]] if name in ("play", "rip", "tag") and self.info.get("DEVICE") else [])
        args += extra
        quick = name in ("play", "open", "rip", "stop", "clean")   # швидкі команди — не блокують інші кнопки
        self.busy = not quick

        def finished(code, err):
            self.busy = False if not quick else self.busy
            if code:
                self.warn(err.strip() or _("Не вдалося виконати дію."))
            if reload or name == "clean":
                self.reload_info()
            self.poll_disc()
        self.spawn(args, finished)

    def eject(self):
        """Зупиняє копіювання (воно тримає привід) і виймає диск. Решту — вийнятий диск,
        кінець відтворення — зробить poll(), як і тоді, коли диск виймають кнопкою приводу."""
        dev = self.disc.get("DEVICE") or "/dev/sr0"
        if self.queue_is_disc() and not self.continue_from_library():
            self.stop_playback()
        self.write_want(None)

        def finished(code, err):
            if code:
                self.warn(err.strip() or _("Не вдалося вийняти диск."))
            self.poll_disc()
        # eject спершу відпускає привід, якщо його тримає gvfs
        self.spawn(["stop"], lambda _c, _e: self.spawn(["eject", dev], finished))

    def add_to_musicbrainz(self):
        url = self.info.get("MB_URL", "")
        if url:
            Gtk.UriLauncher.new(url).launch(self, None, None)

    def open_dir(self, path):
        if path:
            os.makedirs(path, exist_ok=True)
            Gtk.FileLauncher.new(Gio.File.new_for_path(path)).launch(self, None, None)

    def show_preferences(self):
        Preferences(self).present(self)

    def about(self):
        self.show_window()
        dialog = Adw.AboutDialog(
            application_name="CD Auto Runner", application_icon=APP, developer_name="Pan Vena",
            version=self.version or "—", website=HOMEPAGE, issue_url=f"{HOMEPAGE}/issues",
            copyright="© 2026 Pan Vena", license_type=Gtk.License.GPL_2_0_ONLY,
            comments=_("Запускає обраний програвач, щойно вставлено аудіо-CD, має власний вбудований програвач і копіює диски в бібліотеку музики з назвами треків і обкладинками."))
        dialog.present(self)

    def change_language(self, lang):
        run("lang", lang)
        self.restart_lang = lang    # main() перезапустить програму після виходу з циклу подій
        self.quit_app()

    # --- закриття -------------------------------------------------------------------------
    def save_layout(self):
        self.state.put("maximized", self.is_maximized())
        if not self.is_maximized():
            width, height = self.get_default_size()
            self.state.put("width", width)
            self.state.put("height", height)

    def on_close(self, _window):
        self.save_layout()
        if not self.quitting and self.can_background():
            self.set_visible(False)
            self.backgrounded = True
            if not self.state.get("background_hint", False) and read_config().get("NOTIFY", "yes") != "no":
                self.state.put("background_hint", True)
                self.start_detached("notify-send", [
                    "-a", "CD Auto Runner", "-i", APP, "-h", f"string:desktop-entry:{APP}", "CD Auto Runner",
                    _("Музика грає далі. Керувати нею можна з системних елементів керування музикою, а вікно відкриється з меню програм.")])
            return True
        self.shutdown()
        return False

    def shutdown(self):
        """Перед виходом із програми."""
        if self.shut_down:
            return
        self.shut_down = True
        playing = self.cur is not None
        if self.mpv:
            self.mpv.quit()
        self.write_want(None)
        if self.mpris:              # звільняємо ім'я MPRIS: нове вікно могло вже запускатися
            self.mpris.remove_from_connection()
            self.mpris = None
        # без бібліотеки треки копіюються лише для цього вікна — далі копіювати нема сенсу
        if playing and read_config().get("LIBRARY", "yes") != "yes" and self.builtin_selected():
            run("stop", timeout=10)


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        GLib.set_application_name("CD Auto Runner")
        Gtk.Window.set_default_icon_name(APP)
        display = Gdk.Display.get_default()
        here = os.path.dirname(os.path.abspath(__file__))
        theme = Gtk.IconTheme.get_for_display(display)
        for folder in (here, os.path.join(here, "..", "desktop")):     # запуск із репозиторію
            if os.path.isfile(os.path.join(folder, f"{APP}.svg")):
                theme.add_search_path(folder)
        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        for action, keys in (("win.quit", ["<Primary>q"]), ("win.preferences", ["<Primary>comma"]), ("win.refresh", ["F5"]),
                             ("win.play-pause", ["<Primary>space"]), ("win.next", ["<Alt>Right"]),
                             ("win.previous", ["<Alt>Left"]), ("window.close", ["<Primary>w"])):
            self.set_accels_for_action(action, keys)

    def do_command_line(self, command_line):
        play = "--play" in command_line.get_arguments()[1:]
        if self.window is None:
            self.window = MainWindow(self, play=play)
        elif play:
            self.window.request_play()
        self.window.show_window()
        return 0

    def do_activate(self):
        if self.window:
            self.window.show_window()


def main():
    app = Application()
    code = app.run(sys.argv)
    if app.window and app.window.restart_lang:
        # exec, а не дочірній процес: той лишився б у cgroup юніта systemd і помер би разом зі старим
        env = dict(os.environ, CDAR_UI_LANG=app.window.restart_lang)
        flags = ["-I"] if sys.flags.isolated else ["-P"] if getattr(sys.flags, "safe_path", False) else []
        os.execve(sys.executable, [sys.executable, *flags, os.path.abspath(__file__)], env)
    return code


if __name__ == "__main__":
    sys.exit(main())
