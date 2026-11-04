#!/usr/bin/env python3
"""Пошук релізу в MusicBrainz за виконавцем, альбомом і тривалістю треків.

Для дисків, чий ідентифікатор не прив'язаний до MusicBrainz, але назви відомі
(CD-TEXT, ручне введення): реліз дає обкладинку й рік. Тривалості треків мають
збігтися із змістом диска — так інше видання з тією самою назвою не пройде.

Використання: _mbsearch.py ВИКОНАВЕЦЬ АЛЬБОМ СЕКТОРІВ_ТРЕКУ_1 [СЕКТОРІВ_ТРЕКУ_2 …]
Вивід — поля через \\x1f, як у _lib.sh (MBID, ALBUM, ARTIST, YEAR, T); нічого не
знайдено — порожній вивід. Код 1 — мережа недоступна (результат не кешувати).

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import json
import re
import sys
import time
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


def get(path, params):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


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


def field(*parts):
    return "\x1f".join(str(p).replace("\x1f", " ") for p in parts)


def main():
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
