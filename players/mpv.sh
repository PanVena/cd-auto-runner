#!/usr/bin/env bash
# Адаптер mpv: відтворює диск напряму (cdda://, треки — як розділи, PgUp/PgDn).
# Пристрій задається --cdda-device; у старих версіях mpv параметр звався --cdrom-device.
# Щоб замість чорного вікна було щось видно, показуємо обкладинку альбому
# (з бібліотеки або Cover Art Archive), а якщо її немає — спектрограму звуку.
# cdar-desktop-ids: mpv.desktop io.mpv.Mpv.desktop
# cdar-note: відтворює диск напряму
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

opt="--cdda-device"
if [[ -z "$CDAR_FLATPAK" ]] && command -v mpv >/dev/null 2>&1; then
  opts="$(mpv --list-options 2>/dev/null)"
  [[ "$opts" == *"--cdda-device"* || -z "$opts" ]] || opt="--cdrom-device"
fi

extra=()
cover=""
if [[ "$CDAR_DRY_RUN" != 1 ]] && CDAR_RIPPER="$(cdar_ripper)" && _cdar_read_toc && _cdar_metadata; then
  extra+=("--force-media-title=$CDAR_ALBUM_ARTIST — $CDAR_ALBUM")
  libcover="$(_cdar_library_root)/$(_cdar_safe "$CDAR_ALBUM_ARTIST")/$(_cdar_safe "$CDAR_ALBUM")/cover.jpg"
  if [[ -s "$libcover" ]]; then
    cover="$libcover"
  else
    cache="${XDG_CACHE_HOME:-$HOME/.cache}/cd-auto-runner/disc-$CDAR_DISC_ID"
    mkdir -p "$cache" && _cdar_cover "$cache"
    [[ -s "$cache/cover.jpg" ]] && cover="$cache/cover.jpg"
  fi
fi

# Розділи з назвами треків (позиції — зі змісту диска, 75 секторів = 1 с)
if [[ -n "${CDAR_DISC_ID:-}" && -n "${CDAR_TITLES[0]:-}" ]]; then
  chap="${XDG_CACHE_HOME:-$HOME/.cache}/cd-auto-runner/disc-$CDAR_DISC_ID/chapters.txt"
  mkdir -p "$(dirname "$chap")"
  {
    echo ";FFMETADATA1"
    for ((t = 1; t <= CDAR_TRACKS; t++)); do
      s=$(( CDAR_STARTS[t-1] - CDAR_STARTS[0] ))
      title="$(sed 's/[=;#\\]/\\&/g' <<< "${CDAR_TITLES[t-1]}")"
      printf '[CHAPTER]\nTIMEBASE=1/75\nSTART=%d\nEND=%d\ntitle=%02d. %s\n' \
        "$s" $(( s + CDAR_SECTORS[t-1] )) "$t" "$title"
    done
  } > "$chap"
  extra+=("--chapters-file=$chap")
fi

if [[ -n "$cover" ]]; then
  extra+=("--cover-art-files=$cover")
else
  extra+=("--lavfi-complex=[aid1]asplit[ao][a];[a]showcqt=s=1280x720[vo]")
fi

args=(--opt "$opt=$CDAR_DEVICE")
for e in "${extra[@]}"; do args+=(--opt "$e"); done
cdar_launch --urls "${args[@]}" -- "cdda://"
