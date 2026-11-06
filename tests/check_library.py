#!/usr/bin/env python3
"""Перевіряє плейлісти (.m3u8) і мітки альбомів на штучній бібліотеці, без вікна, мережі й аудіо.

Checks playlists (.m3u8) and album markers on a synthetic library, with no window, network
or audio. Run: python3 tests/check_library.py
"""
import importlib.util
import os
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "gui", f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load("cdar_core")


def touch(folder, *names):
    os.makedirs(folder, exist_ok=True)
    for name in names:
        open(os.path.join(folder, name), "w").close()


def check_digital_album(root):
    folder = os.path.join(root, "Artist", "Digital")
    touch(folder, "b side.m4a", "a side.m4a", "cover.txt")
    album = core.read_album(folder, root)
    assert [t["title"] for t in album["tracks"]] == ["a side", "b side"], "формати цифрових копій"
    assert album["ALBUM_ARTIST"] == "Artist", "виконавець — батьківська тека"
    assert album["SOURCE"] == "digital"

    # порядок і назви з мітки, файли з номера не беруться
    core.write_marker(folder, {"ALBUM": "Named", "ALBUM_ARTIST": "Artist", "YEAR": "2001"},
                     [(1, "b side.m4a", "", "First"), (2, "a side.m4a", "Guest", "Second")])
    album = core.read_album(folder, root)
    assert (album["ALBUM"], album["YEAR"]) == ("Named", "2001")
    assert [(t["artist"], t["title"]) for t in album["tracks"]] == [("Artist", "First"), ("Guest", "Second")]
    assert os.path.basename(album["tracks"][0]["path"]) == "b side.m4a"

    # файл, доданий пізніше, — у кінець; збережені назви не з'їжджають
    touch(folder, "a new.m4a")
    tracks = core.read_album(folder, root)["tracks"]
    assert [t["title"] for t in tracks] == ["First", "Second", "a new"], tracks


def check_ripped_album(root):
    folder = os.path.join(root, "Artist", "Ripped")
    touch(folder, "01 - One.flac", "03 - Three.flac")
    with open(os.path.join(folder, core.MARKER), "w", encoding="utf-8") as f:
        f.write("# cd-auto-runner\nDISCID=abc\nALBUM=Ripped\nALBUM_ARTIST=Artist\n01=One\n03=Three\n")
    assert [t["num"] for t in core.read_album(folder, root)["tracks"]] == [1, 3], "нумерація диска"
    assert core.read_album(folder, root)["SOURCE"] == "ripped"
    core.write_marker(folder, {"ALBUM": "New", "ALBUM_ARTIST": "Artist", "YEAR": ""},
                     [(1, "", "", "Uno"), (3, "", "", "Tres")])
    meta = core.read_marker(folder)
    assert meta["DISCID"] == "abc", "мітка не втрачає диск"
    assert core.read_album(folder, root)["SOURCE"] == "ripped", "редагування не робить альбом цифровим"
    assert [t["title"] for t in core.read_album(folder, root)["tracks"]] == ["Uno", "Tres"]
    assert not any(k.startswith("F") for k in meta), "у диска порядок задано номерами"


def check_playlist(root):
    folder = os.path.join(root, "Artist", "Ripped")
    one, three = os.path.join(folder, "01 - One.flac"), os.path.join(folder, "03 - Three.flac")
    path = os.path.join(core.playlists_dir(root), "Mix" + core.PLAYLIST_EXT)
    core.write_m3u(path, [(three, "x"), (one, "y")])
    with open(path, encoding="utf-8") as f:
        assert "../Artist/Ripped/03 - Three.flac" in f.read().splitlines(), "шляхи відносні"
    assert core.read_m3u(path) == [(three, "x"), (one, "y")], "порядок зберігається"

    entry = core.read_entry(path, root)
    assert [t["title"] for t in entry["tracks"]] == ["Tres", "Uno"], "назви з альбому, порядок — плейліста"
    assert [(t["n"], t["num"]) for t in entry["tracks"]] == [(1, 1), (2, 2)]
    assert entry["tracks"][0]["album"] == "New"
    assert entry["ALBUM"] == "Mix"

    # трек зник — лишається в списку під своїм підписом
    core.write_m3u(path, [(os.path.join(folder, "gone.flac"), "Old Band - Old Song"), (one, "y")])
    missing, present = core.read_playlist(path, root)["tracks"]
    assert missing.get("missing") and (missing["artist"], missing["title"]) == ("Old Band", "Old Song")
    assert "missing" not in present

    # плейліст не стає альбомом, «Улюблене» є без файлу й іде першим
    assert all(a["ALBUM_DIR"] != core.playlists_dir(root) for a in core.scan_library(root))
    names = [p["PLAYLIST"] for p in core.list_playlists(root)]
    assert names == [core.favorites_path(root), path], names
    assert core.read_playlist(core.favorites_path(root), root)["tracks"] == []
    assert core.safe_name(" ../a\\b ") == "-a-b", "назва — це ім'я файлу"


def check_sort():
    def album(artist, name, year="", added=0):
        return {"ALBUM_ARTIST": artist, "ALBUM": name, "YEAR": year, "ADDED": added, "tracks": []}
    names = lambda mode, items: [a["ALBUM"] for a in core.sort_albums(items, mode)]
    items = [album("Б", "Я", "1999", 5), album("А", "Ґ", "2004", 1), album("В", "Д", "", 9), album("В", "Г", "2004", 2)]
    assert names("artist", items) == ["Ґ", "Я", "Г", "Д"]
    assert names("title", items) == ["Г", "Ґ", "Д", "Я"], "ґ — одразу за г"
    assert names("added", items) == ["Д", "Я", "Г", "Ґ"], "новіші першими"
    assert names("year", items) == ["Ґ", "Г", "Я", "Д"], "без року — вкінці"
    words = ["яблуко", "їжак", "йод", "іній", "ирій", "єнот", "дім", "ґанок", "гора", "Жук"]
    assert sorted(words, key=core.sort_key) == ["гора", "ґанок", "дім", "єнот", "Жук", "ирій", "іній", "їжак", "йод", "яблуко"]


class Player(core.Controller):
    """Логіка програвача без вікна: mpv — заглушка, що запам'ятовує файли."""

    class Mpv:
        def __init__(self):
            self.played = []

        def load(self, path):
            self.played.append(os.path.basename(path))

        def stop(self):
            pass

    def __init__(self, root):
        self.root, self.store, self.toasts = root, {}, []
        self.mpv, self.mpris = self.Mpv(), None
        self.init_state()
        self.rescan()

    def library_root(self):
        return self.root

    def ui_get(self, key, default):
        return self.store.get(key, default)

    def ui_put(self, key, value):
        self.store[key] = value

    def rescan(self):
        albums = core.scan_library(self.root)
        for a in albums:
            a["thumb"], a["stamp"] = None, 0
        blocked = core.read_playlist(core.blocked_path(self.root), self.root)
        blocked["thumb"], blocked["stamp"] = None, 0
        self.take_scan(albums, [], blocked)

    def toast(self, text):
        self.toasts.append(text)

    def on_position(self, _sec):
        pass

    on_duration = on_position

    def nothing(self, *_a):
        pass

    update_player = show_disc = update_states = fill_library = fill_tracks = load_times = nothing
    select_tracks = write_want = nothing


def end_track(player):
    player.on_ended("eof")
    return player.mpv.played[-1] if player.cur is not None else None


def check_player(root):
    """Наступний альбом, повтор і чорний список — на тих самих об'єктах, що й у вікнах."""
    def album(name, *tracks):
        touch(os.path.join(root, name), *tracks)
        return os.path.join(root, name)
    a = album("A", "01 - a1.flac", "02 - a2.flac")
    b = album("B", "01 - b1.flac")
    c = album("C", "01 - c1.flac", "02 - c2.flac")
    d = album("D", "01 - d1.flac")
    player = Player(root)
    player.set_sort("title")

    def start(folder, n=1):
        assert player.open_album(folder)
        player.adopt()
        player.play_track(n)

    # кінець альбому — наступний у порядку бібліотеки; показаний альбом іде слідом
    start(a, 2)
    assert end_track(player) == "01 - b1.flac" and player.info["ALBUM_DIR"] == b
    assert player.queue["ALBUM_DIR"] == b and player.cur == 1

    # переглядають інший альбом — він лишається показаним
    player.open_album(a)
    assert end_track(player) == "01 - c1.flac"
    assert player.queue["ALBUM_DIR"] == c and player.info["ALBUM_DIR"] == a
    player.stop_playback()

    # повтор: альбом не змінюється
    player.set_loop("Playlist")
    start(a, 2)
    assert end_track(player) == "01 - a1.flac" and player.queue["ALBUM_DIR"] == a
    player.set_loop("Track")
    start(a, 2)
    assert end_track(player) == "02 - a2.flac" and player.next_album() is None
    player.set_loop("None")

    # «Далі» на останньому треку теж веде до наступного альбому
    start(a, 2)
    player.next_track()
    assert player.queue["ALBUM_DIR"] == b and player.mpv.played[-1] == "01 - b1.flac"

    # інший порядок бібліотеки — інший наступний альбом; останній альбом — кінець
    player.set_sort("added")
    os.utime(os.path.join(a, "01 - a1.flac"), (3000, 3000))
    os.utime(os.path.join(a, "02 - a2.flac"), (3000, 3000))
    os.utime(os.path.join(b, "01 - b1.flac"), (2000, 2000))
    os.utime(os.path.join(c, "01 - c1.flac"), (1000, 1000))
    os.utime(os.path.join(d, "01 - d1.flac"), (4000, 4000))
    player.rescan()
    assert [x["ALBUM_DIR"] for x in player.albums if x["ALBUM_DIR"] in (a, b, c, d)][:4] == [d, a, b, c]
    player.set_sort("title")
    start(d)
    assert end_track(player) is None, "після останнього альбому — зупинка"

    # плейліст закінчується сам
    mix = os.path.join(core.playlists_dir(root), "Mix" + core.PLAYLIST_EXT)
    core.write_m3u(mix, [(os.path.join(a, "01 - a1.flac"), "a1")])
    start(mix)
    assert end_track(player) is None, "плейліст не переходить на альбом"

    # чорний список: альбом зникає з плиток і пропускається, але не грає далі сам
    player.toggle_album_block(b)
    assert core.read_m3u(core.blocked_albums_path(root))[0][0] == b
    albums, _lists, blocked, _cur = player.library_rows()
    assert b not in [r[0] for r in albums[0]] and [r[0] for r in blocked[0]] == [b]
    in_album = len(next(x for x in player.albums if x["ALBUM_DIR"] == b)["tracks"])
    assert player.blocked_count() == in_album, "лічильник рахує треки альбому"
    start(a, 2)
    assert end_track(player) == "01 - c1.flac", "заблокований альбом пропущено"
    assert end_track(player) == "02 - c2.flac"
    player.stop_playback()
    player.toggle_album_block(b)
    assert not player.blocked_albums and b in [r[0] for r in player.library_rows()[0][0]]

    # чорний список: пісня пропускається, поточна — змінюється одразу
    link = player.track_link(2, core.read_album(c, root))
    player.open_album(c)
    player.toggle_block([link])
    assert player.playable(player.info) == [1]
    start(c, 2)
    assert player.cur is None and any("чорному" in t or "blacklist" in t for t in player.toasts), "трек не грає"
    start(a, 2)
    assert end_track(player) == "01 - b1.flac"
    assert end_track(player) == "01 - c1.flac"
    assert end_track(player) == "01 - d1.flac", "заблокований трек пропущено"
    player.stop_playback()
    player.open_album(c)
    player.toggle_block([link])
    assert not player.blocked and player.playable(player.info) == [1, 2]

    start(a, 1)
    player.toggle_block([player.track_link(1, player.info)])
    assert player.cur == 2 and player.mpv.played[-1] == "02 - a2.flac", "поточний трек у списку — наступний"
    player.toggle_block([player.track_link(2, player.info)])
    assert player.queue["ALBUM_DIR"] == b, "альбом скінчився — наступний альбом"
    player.stop_playback()

    # пісня, заблокована прямо з плейліста, потрапляє до списку пісень
    one, two = os.path.join(c, "01 - c1.flac"), os.path.join(d, "01 - d1.flac")
    list_b = os.path.join(core.playlists_dir(root), "Blocked" + core.PLAYLIST_EXT)
    core.write_m3u(list_b, [(one, "c1"), (two, "d1"), (os.path.join(b, "01 - b1.flac"), "b1")])
    start(list_b)
    assert player.playable(player.info) == [1, 2, 3]
    player.toggle_block([player.track_link(1, player.info)])
    assert one in {e[0] for e in core.read_m3u(core.blocked_path(root))}, "пісня з плейліста в списку"
    assert player.cur == 2 and player.mpv.played[-1] == "01 - d1.flac"
    assert one in [t["path"] for t in player.blocked_list["tracks"]]
    assert player.blocked_count() == 3, "дві пісні з альбому A і одна зі щойно доданих"
    player.toggle_album_block(a)
    assert player.blocked_count() == 3, "пісня з заблокованого альбому не рахується двічі"
    player.toggle_album_block(a)
    player.toggle_block([player.track_link(1, player.info)])
    assert one not in player.blocked

    # трек заблокованого альбому в плейлісті заблокований теж; сам альбом можна відтворити
    player.toggle_album_block(d)
    assert player.playable(player.info) == [1, 3], "трек альбому з чорного списку не грає"
    assert player.cur == 3 and player.mpv.played[-1] == "01 - b1.flac", "поточний трек змінився"
    link = player.track_link(2, player.info)
    assert player.block_label([link]) == core._("Прибрати з чорного списку") and not player.can_block([link])
    assert player.can_block([link, player.track_link(1, player.info)])
    player.stop_playback()
    start(d)
    assert player.cur == 1 and player.mpv.played[-1] == "01 - d1.flac", "альбом вручну"
    player.stop_playback()
    player.open_album(list_b)
    player.toggle_album_block(d)
    assert player.playable(player.info) == [1, 2, 3] and player.can_block([link])
    os.remove(list_b)

    # список пісень — плитка, але не плейліст
    player.rescan()
    albums, _lists, blocked, _cur = player.library_rows()
    assert blocked[0][0][0] == core.blocked_path(root) and blocked[0][0][1]
    assert core.blocked_path(root) not in [p["PLAYLIST"] for p in core.list_playlists(root)]
    assert not any(core.is_blocked_list(p["PLAYLIST"]) for p in core.list_playlists(root))
    player.show_tile(core.blocked_path(root))
    assert player.is_blocked_open() and not player.playable(player.info)

    # вилучення зі списку пісень, навіть якщо файл зник
    player.selected_tracks = lambda: [1, 2]
    player.block_chosen([])
    assert core.read_m3u(core.blocked_path(root)) == [] and not player.blocked


def check_relink(root):
    """_cdar_relink_playlists: перейменований під час «Ввести назви» трек не губиться з плейлістів."""
    path = os.path.join(core.playlists_dir(root), "Relink" + core.PLAYLIST_EXT)
    old, new = os.path.join(root, "Old [x]", "01 - A.flac"), os.path.join(root, "New", "01 - B.flac")
    other = os.path.join(root, "Keep", "02 - C.flac")
    core.write_m3u(path, [(old, "a"), (other, "c")])
    subprocess.run(["bash", "-c", 'source "$1"; _cdar_relink_playlists "$2" "$3"', "_",
                    os.path.join(ROOT, "players", "_lib.sh"), old, new], check=True,
                   env=dict(os.environ, CDAR_LIBRARY_DIR=root, CDAR_EXEC="true", CDAR_DEVICE="/dev/null",
                            CDAR_TRACKS="1", CDAR_NAME="test"))
    assert [e[0] for e in core.read_m3u(path)] == [new, other]
    assert not os.path.exists(path + ".part")

    # теки альбомів у прихованому чорному списку теж оновлюються
    albums = core.blocked_albums_path(root)
    core.write_m3u(albums, [(os.path.dirname(old), "x")])
    subprocess.run(["bash", "-c", 'source "$1"; _cdar_relink_playlists "$2" "$3"', "_",
                    os.path.join(ROOT, "players", "_lib.sh"), os.path.dirname(old), os.path.dirname(new)], check=True,
                   env=dict(os.environ, CDAR_LIBRARY_DIR=root, CDAR_EXEC="true", CDAR_DEVICE="/dev/null",
                            CDAR_TRACKS="1", CDAR_NAME="test"))
    assert [e[0] for e in core.read_m3u(albums)] == [os.path.dirname(new)]
    os.remove(albums)


def check_mosaic():
    """Обкладинка плейліста: лише різні малюнки, копія в іншій теці не рахується."""
    def solid(name):
        image = gui.QImage(256, 256, gui.QImage.Format_RGB32)
        image.fill(gui.QColor(name))
        return image
    red, blue, green, white, black = map(solid, ("#d02020", "#2040d0", "#20a040", "#f0f0f0", "#101010"))
    covers = [("a", red), ("copy", solid("#d02020")), ("broken", gui.QImage()), ("none", None), ("b", blue),
              ("c", green), ("d", white), ("e", black)]
    assert [p for p, _i in gui.different_covers(covers)] == ["a", "b", "c", "d"], "копія й биті пропущені"
    assert [p for p, _i in gui.different_covers(covers[:2])] == ["a"], "одна й та сама обкладинка"

    size = gui.THUMB
    def corners(image):
        points = ((5, 5), (size - 5, 5), (5, size - 5), (size - 5, size - 5))
        return [image.pixelColor(*p).name() for p in points]
    r, b, g, w, empty = "#d02020", "#2040d0", "#20a040", "#f0f0f0", "#00000000"
    def cells(image):
        return [c if a else empty for c, a in zip(corners(image), alpha(image))]
    def alpha(image):
        points = ((5, 5), (size - 5, 5), (5, size - 5), (size - 5, size - 5))
        return [image.pixelColor(*p).alpha() for p in points]
    assert gui.mosaic([]) is None
    assert cells(gui.mosaic([red])) == [r] * 4, "один альбом — на всю плитку"
    assert cells(gui.mosaic([red, blue])) == [r, b, empty, empty], "два — дві клітинки з чотирьох"
    assert cells(gui.mosaic([red, blue, green])) == [r, b, g, empty], "три — три клітинки"
    assert cells(gui.mosaic([red, blue, green, white])) == [r, b, g, w], "чотири — квадрат"

    # неквадратна обкладинка вписується в клітинку, а не обрізається
    wide = gui.QImage(200, 100, gui.QImage.Format_RGB32)
    wide.fill(gui.QColor(r))
    image = gui.mosaic([wide, blue])
    assert image.pixelColor(5, size // 4).name() == r, "ширина ціла"
    assert image.pixelColor(size // 4, 5).alpha() == 0, "поля зверху, а не обрізані краї"


with tempfile.TemporaryDirectory() as tmp:
    library = os.path.join(tmp, "Музика")
    for check in (check_digital_album, check_ripped_album, check_playlist, check_relink):
        check(library)
    check_sort()
    check_player(os.path.join(tmp, "Плеєр"))
gui = load("gui")
check_mosaic()
print("бібліотека: гаразд / library: ok")
