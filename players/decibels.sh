#!/usr/bin/env bash
# Адаптер Аудіопрогравача GNOME (Decibels): він відкриває лише один звичайний файл, не читає
# cdda://, а кілька файлів показує окремими вікнами без відтворення. Тож треки копіюються
# як завжди, а Decibels отримує весь диск одним файлом album.wav.
# cdar-desktop-ids: org.gnome.Decibels.desktop
# cdar-note: копіює треки
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

open_album() { cdar_launch -- "$1"; }

CDAR_WHOLE=1
cdar_rip_and_play open_album
