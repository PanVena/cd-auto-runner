#!/usr/bin/env python3
"""Пошук релізу в MusicBrainz за виконавцем, альбомом і тривалістю треків.

Для дисків, чий ідентифікатор не прив'язаний до MusicBrainz, але назви відомі
(CD-TEXT, ручне введення): реліз дає обкладинку й рік. Тривалості треків мають
збігтися із змістом диска — так інше видання з тією самою назвою не пройде.

Використання: _mbsearch.py ВИКОНАВЕЦЬ АЛЬБОМ СЕКТОРІВ_ТРЕКУ_1 [СЕКТОРІВ_ТРЕКУ_2 …]
Вивід — поля через \\x1f, як у _lib.sh (MBID, ALBUM, ARTIST, YEAR, T); нічого не
знайдено — порожній вивід. Код 1 — мережа недоступна (результат не кешувати).

Пошук для редактора альбому (цифрові копії, тож без змісту диска); вивід — JSON:
  _mbsearch.py --list ВИКОНАВЕЦЬ АЛЬБОМ ТРЕКІВ    релізи, спершу з такою кількістю треків
  _mbsearch.py --release MBID ТРЕКІВ              назви треків релізу
  _mbsearch.py --cover MBID ФАЙЛ                  передня обкладинка

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://musicbrainz.org/ws/2"
USER_AGENT = "cd-auto-runner/1.0 ( https://github.com/ )"
TIMEOUT = 10
RATE_LIMIT = 1.1                # MusicBrainz: не частіше одного запиту на секунду
MIN_SCORE = 95
MAX_LOOKUPS = 3
TOLERANCE_MS = 3000
SECTORS_PER_SECOND = 75


def normalize(text):
    """Для порівняння назв: регістр і пунктуація в різних джерелах різняться."""
    return "".join(c for c in text.casefold() if c.isalnum())


def credit(artist_credit):
    return "".join(a.get("name", "") + a.get("joinphrase", "") for a in artist_credit or [])


def is_cd(medium):
    return "CD" in (medium.get("format") or "")


def candidates(releases, artist, album, tracks):
    """Релізи з пошуку, що можуть бути цим диском; офіційні — першими."""
    found = [r for r in releases
             if r.get("score", 0) >= MIN_SCORE
             and normalize(r.get("title", "")) == normalize(album)
             and normalize(credit(r.get("artist-credit"))) == normalize(artist)
             and any(is_cd(m) and m.get("track-count") == tracks for m in r.get("media", []))]
    return sorted(found, key=lambda r: r.get("status") != "Official")


def track_length(track):
    return track.get("length") or (track.get("recording") or {}).get("length")


def matching_medium(release, lengths_ms):
    """Носій релізу, чиї треки збігаються з диском за тривалістю, або None."""
    for medium in release.get("media", []):
        tracks = medium.get("tracks") or []
        if is_cd(medium) and len(tracks) == len(lengths_ms) and all(
                track_length(t) and abs(track_length(t) - want) <= TOLERANCE_MS
                for t, want in zip(tracks, lengths_ms)):
            return medium
    return None


def get(path, params, retry=True):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code != 503 or not retry:      # 503 — MusicBrainz просить зачекати (обмеження частоти)
            raise
    time.sleep(2 * RATE_LIMIT)
    return get(path, params, retry=False)


def phrase(text):
    return '"' + re.sub(r'([\\"])', r"\\\1", text) + '"'


def search(artist, album, lengths_ms):
    query = (f"release:{phrase(album)} AND artist:{phrase(artist)} "
             f"AND tracksmedium:{len(lengths_ms)} AND format:CD")
    releases = get("release", {"query": query, "fmt": "json", "limit": 10}).get("releases", [])
    fallback = None
    for found in candidates(releases, artist, album, len(lengths_ms))[:MAX_LOOKUPS]:
        time.sleep(RATE_LIMIT)
        release = get(f"release/{found['id']}", {"inc": "artist-credits recordings", "fmt": "json"})
        medium = matching_medium(release, lengths_ms)
        if medium is None:
            continue
        if (release.get("cover-art-archive") or {}).get("front"):
            return release, medium
        fallback = fallback or (release, medium)   # збіг є, але без обкладинки — шукаємо кращий
    return fallback or (None, None)


def loose(text):
    """Слова без синтаксису запиту Lucene: якщо точної фрази немає, шукаємо за словами."""
    return "(" + " ".join(re.findall(r"\w+", text)) + ")"


def release_query(artist, album, quote):
    parts = [f"release:{quote(album)}"] if album.strip() else []
    if artist.strip():
        parts.append(f"artist:{quote(artist)}")
    return " AND ".join(parts)


def summary(release, wanted):
    media = release.get("media") or []
    counts = [m.get("track-count") or 0 for m in media]
    return {"id": release["id"], "title": release.get("title", ""), "artist": credit(release.get("artist-credit")),
            "year": (release.get("date") or "")[:4], "country": release.get("country", ""),
            "format": " + ".join(sorted({m.get("format") or "?" for m in media})), "tracks": sum(counts),
            "match": wanted in counts or sum(counts) == wanted, "score": release.get("score", 0)}


def find_releases(artist, album, wanted):
    """Реліз для теки з файлами. Кількість треків лише підіймає варіант угору, а не
    відсіює: у цифровій копії може бракувати бонус-треків чи бути зайві."""
    found = []
    for attempt, quote in enumerate((phrase, loose)):
        query = release_query(artist, album, quote)
        if not query:
            return []
        if attempt:
            time.sleep(RATE_LIMIT)
        found = get("release", {"query": query, "fmt": "json", "limit": 25}).get("releases", [])
        if found:
            break
    return sorted((summary(r, wanted) for r in found), key=lambda r: (not r["match"], -r["score"]))


def pick_tracks(release, wanted):
    """Треки релізу: носій, що збігається з текою (тека на диск із 2CD), інакше всі підряд."""
    media = release.get("media") or []
    same = [m for m in media if len(m.get("tracks") or []) == wanted]
    return (same[0]["tracks"] if same else [t for m in media for t in m.get("tracks") or []])


def release_details(mbid, wanted):
    release = get(f"release/{urllib.parse.quote(mbid)}", {"inc": "artist-credits recordings", "fmt": "json"})
    return {"id": release["id"], "title": release.get("title", ""), "artist": credit(release.get("artist-credit")),
            "year": (release.get("date") or "")[:4],
            "cover": bool((release.get("cover-art-archive") or {}).get("front")),
            "tracks": [{"title": t.get("title", ""), "artist": credit(t.get("artist-credit"))}
                       for t in pick_tracks(release, wanted)]}


def save_cover(mbid, path):
    url = f"https://coverartarchive.org/release/{urllib.parse.quote(mbid)}/front-500"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, open(f"{path}.part", "wb") as f:
        f.write(response.read())
    os.replace(f"{path}.part", path)


def interactive(mode, args):
    """Запити редактора альбому. Код 1 — мережа недоступна або реліз не віддав даних."""
    try:
        if mode == "--list" and len(args) == 3:
            print(json.dumps(find_releases(args[0], args[1], int(args[2]))))
        elif mode == "--release" and len(args) == 2:
            print(json.dumps(release_details(args[0], int(args[1]))))
        elif mode == "--cover" and len(args) == 2:
            save_cover(*args)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except (OSError, ValueError, KeyError):
        return 1
    return 0


def field(*parts):
    return "\x1f".join(str(p).replace("\x1f", " ") for p in parts)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--list", "--release", "--cover"):
        return interactive(sys.argv[1], sys.argv[2:])
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    artist, album = sys.argv[1:3]
    lengths_ms = [int(s) * 1000 // SECTORS_PER_SECOND for s in sys.argv[3:]]
    try:
        release, medium = search(artist, album, lengths_ms)
    except (OSError, ValueError):
        return 1
    if release is None:
        return 0
    album_artist = credit(release.get("artist-credit"))
    print(field("MBID", "", release["id"], ""))
    print(field("ALBUM", "", medium.get("title") or release.get("title", ""), ""))
    print(field("ARTIST", "", album_artist, ""))
    print(field("YEAR", "", (release.get("date") or "")[:4], ""))
    for track in medium["tracks"]:
        artist = credit(track.get("artist-credit"))
        print(field("T", track.get("position"), track.get("title", ""),
                    artist if artist != album_artist else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
