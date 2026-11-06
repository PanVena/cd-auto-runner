#!/usr/bin/env python3
"""Перевіряє вікно GTK (gui_gtk.py) на тимчасовому дисплеї Broadway, у власному сеансі D-Bus:
бібліотека, плейлісти, вставлений диск (заглушка cd-auto-runner) і справжнє відтворення через mpv
без звуку. Без GTK 4, libadwaita або gtk4-broadwayd перевірку буде пропущено.

Checks the GTK window on a temporary Broadway display in its own D-Bus session, with a stubbed
cd-auto-runner and real mpv playback (null audio). Skipped when GTK 4, libadwaita or
gtk4-broadwayd is missing. Run: python3 tests/check_gtk.py
"""
import atexit
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISPLAY = ":77"
FAKE_SELF = r'''#!/bin/bash
case "$1" in
  --version) echo "cd-auto-runner 9.9" ;;
  list) printf 'builtin\tBuilt-in\n' ;;
  info) cat "$FAKE_DISC" ;;
  stop) ;;
  eject) echo eject >> "$FAKE_LOG"; echo 0 > "$FAKE_TRACKS" ;;
  *) echo "$*" >> "$FAKE_LOG" ;;
esac
'''


# Панель: приймає значки, як kded у KDE чи розширення AppIndicator у GNOME
FAKE_PANEL = r'''
import sys
from gi.repository import Gio, GLib
XML = """<node><interface name="org.kde.StatusNotifierWatcher">
  <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
  <method name="RegisterStatusNotifierItem"><arg direction="in" type="s"/></method>
</interface></node>"""
def call(_bus, _sender, _path, _iface, _method, args, invocation):
    with open(sys.argv[1], "a") as f:
        f.write(args.unpack()[0] + "\n")
    invocation.return_value(None)
def acquired(bus, _name):
    print("ready", flush=True)
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
bus.register_object("/StatusNotifierWatcher", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call,
                    lambda *_a: GLib.Variant("b", True), None)
Gio.bus_own_name_on_connection(bus, "org.kde.StatusNotifierWatcher", Gio.BusNameOwnerFlags.NONE, acquired, None)
GLib.MainLoop().run()
'''


def reexec():
    """Перезапуск цього самого файлу під dbus-run-session із тимчасовим дисплеєм."""
    missing = [t for t in ("gtk4-broadwayd", "dbus-run-session", "mpv", "ffmpeg", "ffprobe") if not shutil.which(t)]
    if missing:
        print(f"пропущено / skipped: {', '.join(missing)}")
        return 0
    check = 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Adw'
    if subprocess.run([sys.executable, "-c", check], capture_output=True).returncode:
        print("пропущено / skipped: GTK 4, libadwaita")
        return 0
    runtime = tempfile.mkdtemp(prefix="cdg")    # там і сокет дисплея, і сокет mpv: шлях має бути коротким
    env = dict(os.environ, XDG_RUNTIME_DIR=runtime)
    daemon = subprocess.Popen(["gtk4-broadwayd", DISPLAY], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        env.update(GDK_BACKEND="broadway", BROADWAY_DISPLAY=DISPLAY, GTK_A11Y="none", GSK_RENDERER="cairo",
                   CHECK_GTK_INSIDE="1")
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)
        return subprocess.run(["dbus-run-session", "--", sys.executable, os.path.abspath(__file__)], env=env,
                              timeout=120).returncode
    finally:
        daemon.terminate()
        shutil.rmtree(runtime, ignore_errors=True)


def tone(path):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=0.6", path], check=True)


def scenario(tmp):
    os.environ.update(XDG_CONFIG_HOME=f"{tmp}/cfg", XDG_CACHE_HOME=f"{tmp}/cache", HOME=tmp, MPV_HOME=f"{tmp}/mpv",
                      CDAR_UI_LANG="en", CDAR_SELF=f"{tmp}/self",
                      FAKE_DISC=f"{tmp}/disc", FAKE_LOG=f"{tmp}/log", FAKE_TRACKS=f"{tmp}/tracks")
    os.makedirs(f"{tmp}/mpv")
    os.makedirs(f"{tmp}/cfg/cd-auto-runner")
    with open(f"{tmp}/mpv/mpv.conf", "w") as f:
        f.write("ao=null\n")
    lib = f"{tmp}/Music"
    with open(f"{tmp}/cfg/cd-auto-runner/config", "w") as f:
        f.write(f"PLAYER_ID=builtin\nLIBRARY_DIR={lib}\n")
    with open(f"{tmp}/self", "w") as f:
        f.write(FAKE_SELF)
    os.chmod(f"{tmp}/self", 0o755)
    with open(f"{tmp}/tracks", "w") as f:
        f.write("0\n")
    album = f"{lib}/Band/Record"
    os.makedirs(album)
    for i in (1, 2):
        tone(f"{album}/0{i} - Song{i}.flac")
    cache = f"{tmp}/cache/disc"
    os.makedirs(cache)
    tone(f"{cache}/01.wav")
    with open(f"{tmp}/disc", "w") as f:
        f.write(f"DISC_ID=abc\nMB_DISCID=x\nALBUM=Live Disc\nALBUM_ARTIST=Band\nDEVICE=/dev/sr0\nCACHE_DIR={cache}\nSOURCE=none\n"
                "T\t1\tBand\tOn Disc\t1\tpending\t0\nT\t2\tBand\tNot Ripped\t1\tpending\t0\n")
    open(f"{cache}/.done-1", "w").close()
    with open(f"{cache}/.name-1", "w") as f:
        f.write("01.wav\n")

    spec = importlib.util.spec_from_file_location("gui_gtk", os.path.join(ROOT, "gui", "gui_gtk.py"))
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    import cdar_core as core
    from gi.repository import GLib, GdkPixbuf, Gtk

    def inserted(_dev="/dev/sr0"):
        with open(os.environ["FAKE_TRACKS"]) as f:
            return int(f.read())
    core.udev_audio_tracks = inserted

    check_covers(g, GdkPixbuf)
    check_icons(Gtk, g)
    app = g.Application()
    app.register(None)
    app.window = win = g.MainWindow(app)
    win.present()
    context = GLib.MainContext.default()

    def spin(sec, until=lambda: False):
        end = time.time() + sec
        while time.time() < end and not until():
            while context.pending():
                context.iteration(False)
            time.sleep(0.01)
        return until()

    # бібліотека й відтворення
    assert spin(6, lambda: win.albums), "перегляд бібліотеки"
    assert list(win.lib_list.tiles) == [album]
    win.open_tile(album)
    assert win.pages.get_visible_child_name() == "album" and win.title_label.get_text() == "Record"
    win.on_play()
    assert spin(5, lambda: win.cur == 1 and win.length > 0), "mpv грає"
    assert "Song1" in win.now.get_text()
    assert spin(5, lambda: win.cur == 2), "наступний трек"
    win.on_favorite()
    assert spin(3, lambda: win.playlists and win.playlists[0]["tracks"]) and win.p_fav.get_active(), "улюблене"
    assert spin(5, lambda: win.cur is None), "кінець альбому"

    # плейліст: порядок, перетягування, перейменування
    path = core.playlists_dir(lib) + "/Mix.m3u8"
    one, two = f"{album}/01 - Song1.flac", f"{album}/02 - Song2.flac"
    assert win.store_playlist(path, [(two, "a"), (one, "b")])
    win.open_tile(path)
    assert win.rows[0].get_title() == "Song2"
    win.tracks.select_row(win.rows[1])
    win.move_tracks(-1)
    assert [t["title"] for t in win.info["tracks"]] == ["Song1", "Song2"] and win.selected_tracks() == [1]
    assert win.rows[0].on_drag_prepare(None, 0, 0).ref_formats() is not None, "перетягування"
    spin(0.5)
    assert win.on_drop(None, "1", 0, 10_000), "скинуто в кінець"
    assert spin(2, lambda: win.info["tracks"][0]["title"] == "Song2"), "порядок після перетягування"
    new = core.playlists_dir(lib) + "/Mix2.m3u8"
    assert win.rename_entry(path, new) and win.playlist_open() == new
    win.remove_entry(new)
    assert not win.album_open()

    # наступний альбом, сортування і чорний список у вікні
    second = f"{lib}/Band/Second"
    os.makedirs(second)
    tone(f"{second}/01 - Next.flac")
    win.rescan()
    assert spin(3, lambda: second in win.lib_list.tiles), "другий альбом"
    win.lookup_action("sort").activate(GLib.Variant("s", "title"))
    assert win.sort == "title" and list(win.lib_list.tiles) == [album, second]
    win.lookup_action("sort").activate(GLib.Variant("s", "added"))
    assert win.lookup_action("sort").get_state().get_string() == "added"
    win.lookup_action("sort").activate(GLib.Variant("s", "title"))
    win.open_tile(album)
    win.on_play()
    assert spin(5, lambda: win.cur == 2), "другий трек"
    assert spin(5, lambda: win.queue.get("ALBUM_DIR") == second), "наступний альбом"
    assert win.title_label.get_text() == "Second", "показаний альбом іде за тим, що грає"
    win.stop_playback()

    # лише один виконавець: черга з усієї бібліотеки, редагувати її нема чого
    assert win.tile_artist(album) == "Band"
    win.lookup_action("play-artist").activate(GLib.Variant("s", "Band"))
    assert spin(5, lambda: win.cur == 1 and win.length > 0), "виконавець грає"
    assert win.queue["ALBUM_DIR"] == core.ARTIST_KEY + "Band" and win.info is win.queue
    assert len(win.rows) == 3 and not win.lookup_action("tag").get_enabled()
    win.stop_playback()
    win.open_tile(second)

    # відкрити всі треки виконавця, не відтворюючи
    win.lookup_action("open-artist").activate(GLib.Variant("s", "Band"))
    assert win.cur is None and win.info["ALBUM_DIR"] == core.ARTIST_KEY + "Band" and len(win.rows) == 3
    assert win.rows[0].get_subtitle() == "Record" and win.rows[2].get_subtitle() == "Second", "альбом треку"

    # продовження: mpv справді стає на паузу на збереженій позиції
    win.adopt()
    win.play_track(1, start=0.4, paused=True)
    win.open_tile(album)
    win.show_queue()                    # клік на рядку «що грає»
    assert win.info is win.queue and win.title_label.get_text() == win.queue["ALBUM"], "назад до списку"
    assert spin(1, lambda: win.get_focus() is win.rows[0]), "до поточного треку"
    assert spin(5, lambda: win.length > 0 and abs(win.pos - 0.4) < 0.1), "позиція після відкриття файла"
    assert win.is_paused and spin(0.5) is False and abs(win.pos - 0.4) < 0.1, "на паузі не грає"
    win.stop_playback()
    win.open_tile(second)
    win.toggle_album_block(second)
    assert spin(3, lambda: second in win.block_grid.tiles and second not in win.lib_list.tiles), "плитка перейшла"
    badge = win.lib_stack.get_page(win.block_grid).get_badge_number()
    assert badge == win.blocked_count() > 0, "кружок показує кількість треків"
    win.toggle_album_block(second)
    assert spin(3, lambda: second in win.lib_list.tiles and not win.block_grid.tiles)
    win.open_tile(album)
    win.toggle_block([win.track_link(1, win.info)])
    assert win.rows[0].state.get_text() == "blacklisted" and win.playable(win.info) == [2]
    win.tracks.select_row(win.rows[0])
    assert spin(3, lambda: core.blocked_path(lib) in win.block_grid.tiles), "плитка пісень"
    win.open_tile(core.blocked_path(lib))
    win.tracks.select_row(win.rows[0])
    win.block_chosen([])
    assert spin(3, lambda: not win.block_grid.tiles and not win.blocked), "список порожній"
    assert win.lib_stack.get_page(win.block_grid).get_badge_number() == 0, "порожній список без кружка"
    win.close_album()
    win.rescan()
    os.remove(f"{second}/01 - Next.flac")
    os.rmdir(second)
    win.rescan()
    assert spin(3, lambda: list(win.lib_list.tiles) == [album]), "другий альбом прибрано"

    # вставлений диск: скопійований трек грає, вийнятий диск зупиняє
    with open(os.environ["FAKE_TRACKS"], "w") as f:
        f.write("2\n")
    win.poll()
    assert spin(5, lambda: win.disc.get("tracks")), "відомості про диск"
    assert win.title_label.get_text() == "Live Disc" and "" in win.lib_list.tiles
    assert win.rows[0].state.get_text() == "ripped", win.rows[0].state.get_text()
    win.request_play()
    assert spin(5, lambda: win.cur == 1 and win.length > 0), "диск грає"
    win.eject()
    assert spin(5, lambda: not win.disc and win.cur is None), "вийнято"

    # діалоги
    win.show_preferences()
    dialog = win.get_visible_dialog()
    assert spin(5, lambda: dialog.player.get_sensitive()), "програвачі"
    dialog.close()
    spin(0.5)
    win.edit_album(album)
    editor = win.get_visible_dialog()
    assert spin(5, lambda: editor.btn_search.get_sensitive()), "теги прочитано"
    editor.f_album.set_text("Renamed")
    editor.save()
    assert core.read_album(album, lib)["ALBUM"] == "Renamed"
    spin(0.5)
    win.about()
    win.get_visible_dialog().close()
    spin(0.5)

    check_tagger(app, tmp, spin)

    # без панелі лотка немає; з'явилась — значок реєструється сам
    assert not win.tray_enabled(), "панелі ще немає"
    panel = fake_panel(tmp)
    item = TrayClient(spin, win.tray.service)
    assert spin(3, lambda: win.tray.service in panel.registered()), "значок зареєстровано"
    assert win.tray_enabled()
    check_tray(win, item, spin, album, tmp)
    panel.stop()
    assert spin(3, lambda: not win.tray.available()), "панель зникла"

    # закриття під час відтворення лише ховає вікно
    win.show_tile(album)
    win.on_play()
    assert spin(5, lambda: win.length > 0)
    if win.mpris:
        win.close()
        assert spin(1, lambda: not win.get_visible()) and win.backgrounded, "сховано"
        assert spin(8, lambda: win.shut_down), "вихід, коли музика скінчилась"

    # вікно, якого не показували (диск грає в лотку): «Вийти» з меню завершує програму
    panel = fake_panel(tmp)
    win = g.MainWindow(app)
    app.window = win
    assert spin(3, lambda: win.tray.service in panel.registered()), "значок нового вікна"
    win.state.put("play_in_tray", True)
    assert win.play_in_tray()
    win.state.put("play_in_tray", False)
    assert not win.get_realized()
    item.click(win, "Quit")
    assert spin(3, lambda: win.shut_down), "вихід із лотка"
    assert spin(3, lambda: not item.owned()), "значок прибрано"
    panel.stop()
    print("вікно GTK: гаразд / GTK window: ok")


class Panel:
    def __init__(self, process, log):
        self.process, self.log = process, log

    def registered(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().split()

    def stop(self):
        self.process.terminate()
        self.process.wait()


def fake_panel(tmp):
    log = f"{tmp}/panel"
    if os.path.exists(log):
        os.remove(log)
    process = subprocess.Popen([sys.executable, "-c", FAKE_PANEL, log], stdout=subprocess.PIPE, text=True)
    atexit.register(process.terminate)      # тест упав — панель не лишається тримати його вивід
    assert process.stdout.readline().strip() == "ready"
    return Panel(process, log)


class TrayClient:
    """Те, що робить панель: читає значок і меню, клацає."""

    def __init__(self, spin, service):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib, self.spin, self.service = Gio, GLib, spin, service
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)

    def call(self, path, iface, method, signature=None, *args):
        results = []
        params = self.GLib.Variant(f"({signature})", args) if signature else None
        self.bus.call(self.service, path, iface, method, params, None, self.Gio.DBusCallFlags.NONE, 3000, None,
                      lambda bus, res: results.append(bus.call_finish(res).unpack()))
        assert self.spin(4, lambda: results), method
        return results[0]

    def owned(self):
        results = []
        self.bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                      self.GLib.Variant("(s)", (self.service,)), None, self.Gio.DBusCallFlags.NONE, 3000, None,
                      lambda bus, res: results.append(bus.call_finish(res).unpack()[0]))
        assert self.spin(4, lambda: results)
        return results[0]

    def prop(self, name):
        return self.call("/StatusNotifierItem", "org.freedesktop.DBus.Properties", "Get", "ss",
                         "org.kde.StatusNotifierItem", name)[0]

    def activate(self, method):
        self.call("/StatusNotifierItem", "org.kde.StatusNotifierItem", method, "ii", 0, 0)

    def menu(self):
        """Пункти меню: {напис: властивості}, роздільники під номерами."""
        _revision, (_root, _props, children) = self.call("/MenuBar", "com.canonical.dbusmenu", "GetLayout",
                                                         "iias", 0, -1, [])
        return {props.get("label", number): dict(props, id=number) for number, props, _sub in children}

    def click(self, win, label):
        self.call("/MenuBar", "com.canonical.dbusmenu", "Event", "isvu", self.menu()[label]["id"], "clicked",
                  self.GLib.Variant("s", ""), 0)


def check_tray(win, item, spin, album, tmp):
    """Значок поводиться, як у Qt: меню, кліки, згортання, вихід, вимкнення в налаштуваннях."""
    assert item.prop("IconName") == win.tray.icon and item.prop("ItemIsMenu") is False
    assert item.prop("Menu") == "/MenuBar" and item.prop("IconThemePath").endswith("desktop")
    labels = [k for k in item.menu() if isinstance(k, str)]
    assert labels == ["Show / hide the window", "Play / pause", "Previous track", "Next track", "Stop playback",
                      "Eject the disc", "About", "Quit"], labels
    assert sum(1 for p in item.menu().values() if p.get("type") == "separator") == 2

    # стан пунктів і підказка йдуть за програвачем
    assert item.call("/MenuBar", "com.canonical.dbusmenu", "AboutToShow", "i", 0) in ((False,), (True,))
    assert item.menu()["Play / pause"]["enabled"] is win.p_play.get_sensitive()
    win.show_tile(album)
    win.on_play()
    assert spin(5, lambda: win.length > 0)
    assert item.menu()["Play / pause"]["enabled"] is True
    assert "Song1" in item.prop("ToolTip")[3]

    # клік ховає й показує вікно, середня кнопка — пауза
    assert win.get_visible()
    item.activate("Activate")
    assert spin(2, lambda: not win.get_visible()), "сховано кліком"
    item.activate("Activate")
    assert spin(2, lambda: win.get_visible()), "показано кліком"
    item.activate("SecondaryActivate")
    assert spin(2, lambda: win.is_paused), "пауза середньою кнопкою"
    item.activate("SecondaryActivate")
    assert spin(2, lambda: not win.is_paused)

    # закрите вікно: програма працює далі й не виходить, коли музика скінчилась
    win.close()
    assert spin(1, lambda: not win.get_visible()) and not win.backgrounded and win.state.get("tray_hint", False)
    assert spin(8, lambda: win.cur is None), "кінець альбому"
    spin(2.5)
    assert not win.shut_down, "лишається в лотку"
    item.click(win, "Show / hide the window")
    assert spin(2, lambda: win.get_visible()), "показано з меню"

    # недоступний пункт не спрацьовує
    assert item.menu()["Eject the disc"]["enabled"] is False
    item.click(win, "Eject the disc")
    assert win.last_tracks == 0

    # вимкнено в налаштуваннях: значка немає, закриття завершує програму (перевіряє головний сценарій)
    win.show_preferences()
    dialog = win.get_visible_dialog()
    assert dialog.tray.get_sensitive() and dialog.tray.get_active() and dialog.quiet.get_sensitive()
    dialog.tray.set_active(False)
    assert spin(3, lambda: not item.owned()) and not win.tray_enabled() and not dialog.quiet.get_sensitive()
    dialog.tray.set_active(True)
    assert spin(3, lambda: item.owned()) and win.tray_enabled(), "значок повернувся"
    dialog.close()
    spin(0.5)


def check_tagger(app, tmp, spin):
    """Форма назв: заповнюється з шаблону, вставлений список розбирається, результат записується."""
    spec = importlib.util.spec_from_file_location("tagger_gtk", os.path.join(ROOT, "players", "_tagger_gtk.py"))
    tagger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tagger)
    path = f"{tmp}/template"
    with open(path, "w", encoding="utf-8") as f:
        f.write("ALBUM=Old\nALBUM_ARTIST=\nYEAR=\n01=Band - One\n02=Two\n")
    form = tagger.Form(app, path, "2", "https://example.org")
    form.present()
    spin(0.3)
    assert (form.rows[0].artist.get_text(), form.rows[0].name.get_text()) == ("Band", "One")
    form.album.set_text("New")
    dialog = tagger.PasteDialog(form)
    dialog.present(form)
    dialog.text.get_buffer().set_text("1. Jay-Z - A\n\n2) B\n3. C\n")
    dialog.on_apply(None)
    spin(0.3)
    form.save()
    assert app.saved
    with open(path, encoding="utf-8") as f:
        assert f.read() == "ALBUM=New\nALBUM_ARTIST=\nYEAR=\n01=Jay-Z - A\n02=B\n"
    spin(0.3)


def check_covers(g, GdkPixbuf):
    def solid(rgba, w=256, h=256):
        pix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, w, h)
        pix.fill(rgba)
        return pix
    red, blue, green = solid(0xd02020ff), solid(0x2040d0ff), solid(0x20a040ff)
    picked = g.different_covers([("a", red), ("copy", solid(0xd02020ff)), ("none", None), ("b", blue), ("c", green)])
    assert [path for path, _pix in picked] == ["a", "b", "c"], "копія й порожні пропущені"
    assert g.mosaic([]) is None and g.mosaic([red]) is red

    def pixel(pix, x, y):
        offset = y * pix.get_rowstride() + x * pix.get_n_channels()
        return tuple(pix.get_pixels()[offset:offset + 4])
    size = g.THUMB
    image = g.mosaic([red, blue, green])
    assert pixel(image, 5, 5) == (0xd0, 0x20, 0x20, 255) and pixel(image, size - 5, 5) == (0x20, 0x40, 0xd0, 255)
    assert pixel(image, 5, size - 5) == (0x20, 0xa0, 0x40, 255) and pixel(image, size - 5, size - 5)[3] == 0, "порожня клітинка"
    image = g.mosaic([solid(0xd02020ff, 200, 100), blue])
    assert pixel(image, 5, size // 4)[0] == 0xd0 and pixel(image, size // 4, 5)[3] == 0, "вписується, а не обрізається"
    assert g.texture(red).get_width() == 256


def check_icons(Gtk, g):
    """Значки Adwaita: на чистому GNOME жоден не має лишитися порожнім."""
    if not os.path.isdir("/usr/share/icons/Adwaita"):
        return
    theme = Gtk.IconTheme.new()
    theme.set_theme_name("Adwaita")
    theme.add_search_path(os.path.join(ROOT, "desktop"))
    with open(g.__file__, encoding="utf-8") as f:
        names = set(re.findall(r'"([a-z]+(?:-[a-z]+)*-symbolic)"', f.read())) - set(g.ICONS)    # ключі — імена Breeze
    names.update(g.ICONS.values(), (g.HEART, g.HEART_ON))
    missing = sorted(n for n in names if not theme.has_icon(n))
    assert len(names) > 20 and not missing, missing


if __name__ == "__main__":
    if "CHECK_GTK_INSIDE" not in os.environ:
        sys.exit(reexec())
    with tempfile.TemporaryDirectory() as folder:
        scenario(folder)
    sys.stdout.flush()
    os._exit(0)     # потоки черг і mpv не тримають перевірку
