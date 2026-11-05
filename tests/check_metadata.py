#!/usr/bin/env python3
"""Перевіряє розбір CD-TEXT і вибір релізу MusicBrainz на штучних даних, без приводу й мережі.

Checks CD-TEXT parsing and MusicBrainz release matching on synthetic data, with no
drive or network. Run: python3 tests/check_metadata.py
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "players", f"_{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cdtext = load("cdtext")
mbsearch = load("mbsearch")


def packs(kind, first, text, block=0):
    return [bytes([kind, first, i // 12, block << 4]) + text[i:i + 12].ljust(12, b"\0") + b"\0\0"
            for i in range(0, len(text), 12)]


def check_cdtext():
    # Latin-1, TAB-повтор, доповнення нулями; другий мовний блок ігнорується
    parsed = cdtext.parse(packs(0x80, 0, b"Album\0One\0Caf\xe9\0") + packs(0x81, 0, b"Various\0A\0\t\0")
                          + packs(0x80, 0, b"Other\0X\0Y\0", block=1))
    assert parsed[0x80] == {0: "Album", 1: "One", 2: "Café"}, parsed
    assert parsed[0x81] == {0: "Various", 1: "A", 2: "A"}, parsed
    assert cdtext.parse([]) == {}
    # Двобайтові кодування не розбираємо
    assert cdtext.parse([bytes([0x80, 0, 0, 0x80]) + b"x" * 14]) == {}
    assert cdtext.parse(packs(0x80, 0, b"A\0") + [bytes([0x8f, 0, 0, 0, 0x80]) + b"\0" * 13]) == {}


def check_cdtext_drive_errors():
    cdtext.RETRY_DELAY = 0
    answers = []

    def read_toc(_fd, _size):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    real_read_toc, real_open, real_close = cdtext.read_toc, cdtext.os.open, cdtext.os.close
    cdtext.read_toc = read_toc
    cdtext.os.open = lambda *_: 0
    cdtext.os.close = lambda *_: None
    busy = OSError("not ready")
    pack = bytes(range(18))
    try:
        answers[:] = [None]                            # Illegal Request: CD-TEXT немає
        assert cdtext.read_packs("dev") == []
        answers[:] = [b"\x00\x02\0\0"]                 # порожній заголовок
        assert cdtext.read_packs("dev") == []
        answers[:] = [busy, busy, b"\x00\x14\0\0", b"\x00\x14\0\0" + pack]   # привід прокинувся
        assert cdtext.read_packs("dev") == [pack]
        answers[:] = [busy] * cdtext.ATTEMPTS          # збій — не те саме, що «CD-TEXT немає»
        try:
            cdtext.read_packs("dev")
        except OSError:
            pass
        else:
            raise AssertionError("збій приводу прийнято за диск без CD-TEXT")
        answers[:] = [b"\x00\x14\0\0", None] * cdtext.ATTEMPTS  # довжину дав, дані — ні
        try:
            cdtext.read_packs("dev")
        except OSError:
            pass
        else:
            raise AssertionError("порожня відповідь прийнята за диск без CD-TEXT")
    finally:
        cdtext.read_toc, cdtext.os.open, cdtext.os.close = real_read_toc, real_open, real_close
    assert cdtext.sense_key(bytes([0x70, 0, 5] + [0] * 15)) == 5
    assert cdtext.sense_key(bytes([0x72, 5, 0] + [0] * 15)) == 5


def release(**extra):
    base = {"id": "r", "score": 100, "title": "Cult of a Dying Sun", "status": "Official",
            "artist-credit": [{"name": "UADA"}], "media": [{"format": "CD", "track-count": 2}]}
    return {**base, **extra}


def check_candidates():
    pick = lambda *rel: [r["id"] for r in mbsearch.candidates(rel, "UADA", "Cult Of A Dying Sun", 2)]
    assert pick(release()) == ["r"], "регістр і пунктуація не мають значення"
    assert pick(release(score=80)) == []
    assert pick(release(title="Djinn")) == []
    assert pick(release(**{"artist-credit": [{"name": "Other"}]})) == []
    assert pick(release(media=[{"format": "Digital Media", "track-count": 2}])) == [], "цифрове видання"
    assert pick(release(media=[{"format": "CD", "track-count": 3}])) == []
    assert pick(release(id="b", status="Bootleg"), release(id="o")) == ["o", "b"], "офіційні першими"


def check_lengths():
    tracks = [{"length": 100000}, {"recording": {"length": 200000}}]
    rel = {"media": [{"format": "CD", "tracks": tracks}]}
    assert mbsearch.matching_medium(rel, [102000, 198000]), "у межах допуску"
    assert mbsearch.matching_medium(rel, [100000, 204000]) is None, "інше видання"
    assert mbsearch.matching_medium(rel, [100000]) is None, "інша кількість треків"
    assert mbsearch.matching_medium({"media": [{"format": "CD", "tracks": [{}]}]}, [100000]) is None, "без тривалості"
    assert mbsearch.matching_medium({"media": [{"format": "Vinyl", "tracks": tracks}]}, [100000, 200000]) is None


def check_digital_search():
    """Пошук для цифрових копій: кількість треків підіймає реліз, а не відсіює його."""
    found = [release(id="more", media=[{"format": "CD", "track-count": 16}]),
             release(id="same", score=90, media=[{"format": "Digital Media", "track-count": 11}]),
             release(id="double", score=80, media=[{"format": "CD", "track-count": 11}, {"format": "CD", "track-count": 5}])]
    get, mbsearch.get = mbsearch.get, lambda *_a, **_k: {"releases": found}
    try:
        assert [r["id"] for r in mbsearch.find_releases("UADA", "Djinn", 11)] == ["same", "double", "more"]
        assert mbsearch.find_releases("", "", 11) == [], "порожній запит"
    finally:
        mbsearch.get = get
    assert mbsearch.loose('Blood [FLAC: 2011]') == "(Blood FLAC 2011)", "без синтаксису Lucene"
    assert mbsearch.release_query("", "A", mbsearch.phrase) == 'release:"A"'
    double = {"media": [{"tracks": [1, 2]}, {"tracks": [3, 4, 5]}]}
    assert mbsearch.pick_tracks(double, 3) == [3, 4, 5], "тека на один диск"
    assert mbsearch.pick_tracks(double, 4) == [1, 2, 3, 4, 5], "усі диски підряд"


for check in (check_cdtext, check_cdtext_drive_errors, check_candidates, check_lengths, check_digital_search):
    check()
print("метадані: гаразд / metadata: ok")
