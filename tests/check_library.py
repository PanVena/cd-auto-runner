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
spec = importlib.util.spec_from_file_location("gui", os.path.join(ROOT, "gui", "gui.py"))
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


def touch(folder, *names):
    os.makedirs(folder, exist_ok=True)
    for name in names:
        open(os.path.join(folder, name), "w").close()


def check_digital_album(root):
    folder = os.path.join(root, "Artist", "Digital")
    touch(folder, "b side.m4a", "a side.m4a", "cover.txt")
    album = gui.read_album(folder, root)
    assert [t["title"] for t in album["tracks"]] == ["a side", "b side"], "формати цифрових копій"
    assert album["ALBUM_ARTIST"] == "Artist", "виконавець — батьківська тека"
    assert album["SOURCE"] == "digital"

    # порядок і назви з мітки, файли з номера не беруться
    gui.write_marker(folder, {"ALBUM": "Named", "ALBUM_ARTIST": "Artist", "YEAR": "2001"},
                     [(1, "b side.m4a", "", "First"), (2, "a side.m4a", "Guest", "Second")])
    album = gui.read_album(folder, root)
    assert (album["ALBUM"], album["YEAR"]) == ("Named", "2001")
    assert [(t["artist"], t["title"]) for t in album["tracks"]] == [("Artist", "First"), ("Guest", "Second")]
    assert os.path.basename(album["tracks"][0]["path"]) == "b side.m4a"

    # файл, доданий пізніше, — у кінець; збережені назви не з'їжджають
    touch(folder, "a new.m4a")
    tracks = gui.read_album(folder, root)["tracks"]
    assert [t["title"] for t in tracks] == ["First", "Second", "a new"], tracks


def check_ripped_album(root):
    folder = os.path.join(root, "Artist", "Ripped")
    touch(folder, "01 - One.flac", "03 - Three.flac")
    with open(os.path.join(folder, gui.MARKER), "w", encoding="utf-8") as f:
        f.write("# cd-auto-runner\nDISCID=abc\nALBUM=Ripped\nALBUM_ARTIST=Artist\n01=One\n03=Three\n")
    assert [t["num"] for t in gui.read_album(folder, root)["tracks"]] == [1, 3], "нумерація диска"
    assert gui.read_album(folder, root)["SOURCE"] == "ripped"
    gui.write_marker(folder, {"ALBUM": "New", "ALBUM_ARTIST": "Artist", "YEAR": ""},
                     [(1, "", "", "Uno"), (3, "", "", "Tres")])
    meta = gui.read_marker(folder)
    assert meta["DISCID"] == "abc", "мітка не втрачає диск"
    assert gui.read_album(folder, root)["SOURCE"] == "ripped", "редагування не робить альбом цифровим"
    assert [t["title"] for t in gui.read_album(folder, root)["tracks"]] == ["Uno", "Tres"]
    assert not any(k.startswith("F") for k in meta), "у диска порядок задано номерами"


def check_playlist(root):
    folder = os.path.join(root, "Artist", "Ripped")
    one, three = os.path.join(folder, "01 - One.flac"), os.path.join(folder, "03 - Three.flac")
    path = os.path.join(gui.playlists_dir(root), "Mix" + gui.PLAYLIST_EXT)
    gui.write_m3u(path, [(three, "x"), (one, "y")])
    with open(path, encoding="utf-8") as f:
        assert "../Artist/Ripped/03 - Three.flac" in f.read().splitlines(), "шляхи відносні"
    assert gui.read_m3u(path) == [(three, "x"), (one, "y")], "порядок зберігається"

    entry = gui.read_entry(path, root)
    assert [t["title"] for t in entry["tracks"]] == ["Tres", "Uno"], "назви з альбому, порядок — плейліста"
    assert [(t["n"], t["num"]) for t in entry["tracks"]] == [(1, 1), (2, 2)]
    assert entry["tracks"][0]["album"] == "New"
    assert entry["ALBUM"] == "Mix"

    # трек зник — лишається в списку під своїм підписом
    gui.write_m3u(path, [(os.path.join(folder, "gone.flac"), "Old Band - Old Song"), (one, "y")])
    missing, present = gui.read_playlist(path, root)["tracks"]
    assert missing.get("missing") and (missing["artist"], missing["title"]) == ("Old Band", "Old Song")
    assert "missing" not in present

    # плейліст не стає альбомом, «Улюблене» є без файлу й іде першим
    assert all(a["ALBUM_DIR"] != gui.playlists_dir(root) for a in gui.scan_library(root))
    names = [p["PLAYLIST"] for p in gui.list_playlists(root)]
    assert names == [gui.favorites_path(root), path], names
    assert gui.read_playlist(gui.favorites_path(root), root)["tracks"] == []
    assert gui.safe_name(" ../a\\b ") == "-a-b", "назва — це ім'я файлу"


def check_relink(root):
    """_cdar_relink_playlists: перейменований під час «Ввести назви» трек не губиться з плейлістів."""
    path = os.path.join(gui.playlists_dir(root), "Relink" + gui.PLAYLIST_EXT)
    old, new = os.path.join(root, "Old [x]", "01 - A.flac"), os.path.join(root, "New", "01 - B.flac")
    other = os.path.join(root, "Keep", "02 - C.flac")
    gui.write_m3u(path, [(old, "a"), (other, "c")])
    subprocess.run(["bash", "-c", 'source "$1"; _cdar_relink_playlists "$2" "$3"', "_",
                    os.path.join(ROOT, "players", "_lib.sh"), old, new], check=True,
                   env=dict(os.environ, CDAR_LIBRARY_DIR=root, CDAR_EXEC="true", CDAR_DEVICE="/dev/null",
                            CDAR_TRACKS="1", CDAR_NAME="test"))
    assert [e[0] for e in gui.read_m3u(path)] == [new, other]
    assert not os.path.exists(path + ".part")


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
check_mosaic()
print("бібліотека: гаразд / library: ok")
