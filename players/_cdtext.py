#!/usr/bin/env python3
"""CD-TEXT аудіодиска: назви, записані на самому диску.

Читає lead-in диска командою READ TOC і не потребує зовнішніх програм. Привід
щоразу перечитує lead-in із самого диска (10 с на запит), тому _lib.sh кешує
результат.

Використання: _cdtext.py ПРИСТРІЙ
Вивід (поля розділені \\x1f, як у запиті до MusicBrainz в _lib.sh):
    ALBUM <> <> назва      ARTIST <> <> виконавець      T <> номер <> назва <> виконавець
Диск без CD-TEXT — порожній вивід. Код 1 — привід не відповів (щойно вставлений
диск ще не готовий): це не означає, що CD-TEXT немає, тож результат не кешується.

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import ctypes
import fcntl
import os
import sys
import time

SG_IO = 0x2285
SG_DXFER_FROM_DEV = -3
READ_TOC, FORMAT_CD_TEXT = 0x43, 5
TIMEOUT_MS = 30000
SENSE_ILLEGAL_REQUEST = 5       # привід не має цих даних: на диску немає CD-TEXT
ATTEMPTS = 6
RETRY_DELAY = 3                 # с; щойно вставлений диск розкручується кілька секунд

PACK_SIZE = 18
PACK_TITLE, PACK_PERFORMER, PACK_SIZE_INFO = 0x80, 0x81, 0x8f
CHARSETS = {0x00: "latin-1", 0x01: "ascii"}


class SgIoHdr(ctypes.Structure):
    _fields_ = [("interface_id", ctypes.c_int), ("dxfer_direction", ctypes.c_int),
                ("cmd_len", ctypes.c_ubyte), ("mx_sb_len", ctypes.c_ubyte),
                ("iovec_count", ctypes.c_ushort), ("dxfer_len", ctypes.c_uint),
                ("dxferp", ctypes.c_void_p), ("cmdp", ctypes.c_void_p), ("sbp", ctypes.c_void_p),
                ("timeout", ctypes.c_uint), ("flags", ctypes.c_uint), ("pack_id", ctypes.c_int),
                ("usr_ptr", ctypes.c_void_p), ("status", ctypes.c_ubyte),
                ("masked_status", ctypes.c_ubyte), ("msg_status", ctypes.c_ubyte),
                ("sb_len_wr", ctypes.c_ubyte), ("host_status", ctypes.c_ushort),
                ("driver_status", ctypes.c_ushort), ("resid", ctypes.c_int),
                ("duration", ctypes.c_uint), ("info", ctypes.c_uint)]


def sense_key(sense):
    return (sense[1] if sense[0] & 0x7f in (0x72, 0x73) else sense[2]) & 0xf


def read_toc(fd, size):
    """READ TOC, формат CD-TEXT. Байти; None — CD-TEXT немає; OSError — привід не відповів."""
    cdb = (ctypes.c_ubyte * 10)(READ_TOC, 0, FORMAT_CD_TEXT, 0, 0, 0, 0, size >> 8, size & 0xff, 0)
    data = ctypes.create_string_buffer(size)
    sense = ctypes.create_string_buffer(32)
    hdr = SgIoHdr(interface_id=ord("S"), dxfer_direction=SG_DXFER_FROM_DEV, cmd_len=len(cdb),
                  mx_sb_len=len(sense), dxfer_len=size, dxferp=ctypes.addressof(data),
                  cmdp=ctypes.addressof(cdb), sbp=ctypes.addressof(sense), timeout=TIMEOUT_MS)
    fcntl.ioctl(fd, SG_IO, hdr)
    if hdr.status or hdr.host_status or hdr.driver_status:
        if sense_key(sense.raw) == SENSE_ILLEGAL_REQUEST:
            return None
        raise OSError(f"READ TOC: status {hdr.status}, sense {sense.raw[:18].hex()}")
    return data.raw[:size - hdr.resid]


def fetch(fd):
    head = read_toc(fd, 4)             # спершу довжина: не всі приводи приймають довгий запит
    if head is None:
        return []
    if len(head) < 4:
        raise OSError("READ TOC: short header")
    size = int.from_bytes(head[:2], "big") + 2
    if size <= 4:
        return []
    data = read_toc(fd, min(size, 0xffff))
    if not data:
        raise OSError("READ TOC: no data")
    return [data[i:i + PACK_SIZE] for i in range(4, len(data) - PACK_SIZE + 1, PACK_SIZE)]


def read_packs(device):
    """Сирі 18-байтові пакети CD-TEXT із приводу. OSError — привід так і не відповів."""
    fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    try:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return fetch(fd)
            except OSError:
                if attempt == ATTEMPTS:
                    raise
                time.sleep(RETRY_DELAY)
    finally:
        os.close(fd)


def parse(packs):
    """Текст першого мовного блоку: {тип пакета: {номер треку (0 — диск): рядок}}."""
    packs = [p for p in packs if not (p[3] >> 4) & 7]  # лише блок 0: решта — переклади
    info = next((p for p in packs if p[0] == PACK_SIZE_INFO and p[1] == 0), None)
    # Двобайтові кодування (японські диски) не підтримуємо
    charset = CHARSETS.get(info[4] if info else 0)
    if charset is None or any(p[3] & 0x80 for p in packs):
        return {}
    result = {}
    for kind in (PACK_TITLE, PACK_PERFORMER):
        chunks = [p for p in packs if p[0] == kind]
        if not chunks:
            continue
        track, strings, prev = chunks[0][1] & 0x7f, {}, ""
        for raw in b"".join(p[4:16] for p in chunks).split(b"\0")[:-1]:
            # TAB — «те саме, що в попереднього треку»
            text = prev if raw == b"\t" else raw.decode(charset, "replace").strip()
            if text:                   # порожні рядки — доповнення нулями в кінці пакета
                strings[track] = text
            prev = text
            track += 1
        result[kind] = strings
    return result


def clean(text):
    return text.replace("\x1f", " ")


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        text = parse(read_packs(sys.argv[1]))
    except OSError:
        return 1
    titles = text.get(PACK_TITLE, {})
    performers = text.get(PACK_PERFORMER, {})
    album_artist = performers.get(0, "")
    if titles.get(0):
        print("ALBUM", "", clean(titles[0]), "", sep="\x1f")
    if album_artist:
        print("ARTIST", "", clean(album_artist), "", sep="\x1f")
    for track in sorted(set(titles) | set(performers)):
        artist = performers.get(track, "")
        if track and (titles.get(track) or artist):
            print("T", track, clean(titles.get(track, "")),
                  clean(artist) if artist != album_artist else "", sep="\x1f")
    return 0


if __name__ == "__main__":
    sys.exit(main())
