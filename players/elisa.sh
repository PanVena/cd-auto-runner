#!/usr/bin/env bash
# Адаптер Elisa: Elisa не відкриває cdda:// чи audiocd:/ з командного рядка,
# тому треки копіюються у WAV, і Elisa одразу отримує весь альбом одним списком.
# cdar-desktop-ids: org.kde.elisa.desktop elisa.desktop
# cdar-note: копіює треки
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

open_album() { cdar_launch -- "$@"; }

cdar_rip_and_play open_album
