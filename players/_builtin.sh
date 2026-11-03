#!/usr/bin/env bash
# Копіювання диска для вбудованого програвача (вікно CD Auto Runner + mpv).
# Треки копіюються в кеш (і в бібліотеку музики, якщо її ввімкнено), а вікно
# відтворює кожен трек, щойно його скопійовано. Трек, який хочуть слухати,
# вікно записує у файл .want — він копіюється першим.
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

noop() { :; }
cdar_rip_and_play noop gui
