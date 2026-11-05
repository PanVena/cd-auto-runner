#!/usr/bin/env python3
"""Спільне для форм введення назв треків: Qt (_tagger.py) і GTK (_tagger_gtk.py).

Shared by the tracklist editors: Qt (_tagger.py) and GTK (_tagger_gtk.py).

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import os
import re

LANG = os.environ.get("CDAR_UI_LANG", "uk")
EN = {
    "Назви треків": "Track titles",
    "Альбом:": "Album:",
    "Виконавець альбому:": "Album artist:",
    "Рік:": "Year:",
    "порожньо — визначиться сам (для збірки — Various Artists)":
        "empty — detected automatically (Various Artists for a compilation)",
    "Виконавець": "Artist",
    "Назва": "Title",
    "Вставити список…": "Paste tracklist…",
    "Очистити": "Clear",
    "Додати диск у MusicBrainz": "Add the disc to MusicBrainz",
    "Зберегти": "Save",
    "Скасувати": "Cancel",
    "Вставте список треків — по одному в рядку, наприклад «1. Виконавець - Назва».\n"
    "Номери на початку рядків і порожні рядки пропускаються.":
        "Paste the tracklist — one track per line, e.g. \"1. Artist - Title\".\n"
        "Leading numbers and empty lines are skipped.",
    "Для збірки (диск із журналу) вкажіть виконавця кожного треку. "
    "Якщо виконавець той самий, що й в альбому, стовпчик можна лишити порожнім.":
        "For a compilation (e.g. a magazine CD) enter the artist of every track. "
        "If it's the same as the album artist, the column can stay empty.",
}


def _(text):
    return EN.get(text, text) if LANG == "en" else text


# «Виконавець - Назва»; пробіл може бути лише з одного боку дефіса, «Jay-Z» не розбивається
SPLIT = (re.compile(r"^(.*\S)\s+-\s*(\S.*)$"), re.compile(r"^(.*\S)\s*-\s+(\S.*)$"))
LEADING_NUMBER = re.compile(r"^\s*(?:\d{1,3}\s*[.):\-–]?\s+|\d{1,3}[.)]\s*)")


def split_track(value):
    value = value.strip()
    for rx in SPLIT:
        m = rx.match(value)
        if m:
            return m.group(1), m.group(2)
    return "", value


def read_template(path):
    head, tracks = {}, {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if re.fullmatch(r"\d\d", key):
                tracks[int(key)] = split_track(value)
            else:
                head[key] = value
    return head, tracks


def parse_list(text):
    """Вставлений список треків: (виконавець, назва) на рядок; номери й порожні рядки пропускаються."""
    result = []
    for line in text.splitlines():
        line = LEADING_NUMBER.sub("", line).strip()
        if line:
            result.append(split_track(line))
    return result


def write_template(path, album, album_artist, year, rows):
    """Результат форми: rows — пари (виконавець, назва) по порядку треків."""
    lines = [f"ALBUM={album.strip()}", f"ALBUM_ARTIST={album_artist.strip()}", f"YEAR={year.strip()}"]
    for n, (artist, name) in enumerate(rows, 1):
        artist, name = artist.strip(), name.strip()
        lines.append(f"{n:02d}=" + (f"{artist} - {name}" if artist and name else name or artist))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
