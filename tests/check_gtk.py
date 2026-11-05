#!/usr/bin/env python3
"""Перевіряє вікно GTK (gui_gtk.py) на тимчасовому дисплеї Broadway, у власному сеансі D-Bus:
бібліотека, плейлісти, вставлений диск (заглушка cd-auto-runner) і справжнє відтворення через mpv
без звуку. Без GTK 4, libadwaita або gtk4-broadwayd перевірку буде пропущено.

Checks the GTK window on a temporary Broadway display in its own D-Bus session, with a stubbed
cd-auto-runner and real mpv playback (null audio). Skipped when GTK 4, libadwaita or
gtk4-broadwayd is missing. Run: python3 tests/check_gtk.py
"""
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

    # закриття під час відтворення лише ховає вікно
    win.show_tile(album)
    win.on_play()
    assert spin(5, lambda: win.length > 0)
    if win.mpris:
        win.close()
        assert spin(1, lambda: not win.get_visible()) and win.backgrounded, "сховано"
        assert spin(8, lambda: win.shut_down), "вихід, коли музика скінчилась"
    print("вікно GTK: гаразд / GTK window: ok")


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
