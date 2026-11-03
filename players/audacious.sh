#!/usr/bin/env bash
# Адаптер Audacious: копіює треки й відкриває весь альбом одним списком.
# Напряму (cdda://?N) Audacious бере назви зі своєї бази CDDB, де вони бувають
# неправильні, а передати йому наші назви з командного рядка неможливо. Скопійовані
# WAV мають правильні теги, і альбом заодно зберігається в бібліотеці «Музика».
# cdar-desktop-ids: audacious.desktop org.atheme.audacious.desktop
# cdar-note: копіює треки
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

open_album() { cdar_launch -- "$@"; }

# Після перемикання на ще не скопійований трек — Stop/Play: Audacious відкриє файл заново
CDAR_RESUME=restart
cdar_rip_and_play open_album
