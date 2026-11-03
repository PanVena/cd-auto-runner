#!/usr/bin/env bash
# Адаптер VLC: відтворює диск напряму.
# Кожен трек передається окремим елементом списку (cdda://… :cdda-track=N):
# якщо дати VLC лише cdda:///dev/sr0, він сам розгортає диск і може почати
# не з першого треку. Назви й виконавця беремо з метаданих диска (кеш KDE / MusicBrainz).
# cdar-desktop-ids: org.videolan.VLC.desktop org.videolan.VLC-opencda.desktop vlc.desktop vlc-opencda.desktop
# cdar-note: відтворює диск напряму
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

# «VLC (Audio CD)» має в Exec «cdda://%f» — замінюємо на звичайний список аргументів
CDAR_EXEC="${CDAR_EXEC/cdda:\/\/%f/%U}"

meta=0
if [[ "$CDAR_DRY_RUN" != 1 ]] && CDAR_RIPPER="$(cdar_ripper)" && _cdar_read_toc; then
  _cdar_metadata && meta=1
fi

args=()
for ((t = 1; t <= CDAR_TRACKS; t++)); do
  args+=("cdda://$CDAR_DEVICE" ":cdda-track=$t")
  if ((meta)); then
    args+=(":meta-title=${CDAR_TITLES[t-1]}" ":meta-artist=${CDAR_ARTISTS[t-1]}")
    [[ -n "$CDAR_YEAR" ]] && args+=(":meta-date=$CDAR_YEAR")
  fi
done

# --no-random: у VLC може бути ввімкнено випадковий порядок — альбом граємо по черзі
cdar_launch --urls --opt --no-random -- "${args[@]}"
