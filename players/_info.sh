#!/usr/bin/env bash
# Відомості про вставлений диск для графічного вікна (cd-auto-runner info).
# Вивід: рядки КЛЮЧ=значення, далі по рядку на трек:
#   T<TAB>номер<TAB>виконавець<TAB>назва<TAB>секунд<TAB>стан<TAB>назва_невідома(0|1)
# стан: library — є в бібліотеці; ripped — скопійовано в кеш; pending — ще ні.
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

if ! CDAR_RIPPER="$(cdar_ripper)"; then echo "ERROR=no-ripper"; exit 1; fi
_cdar_read_toc || { echo "ERROR=toc"; exit 1; }
_cdar_metadata 2>/dev/null

cache="${XDG_CACHE_HOME:-$HOME/.cache}/cd-auto-runner/disc-$CDAR_DISC_ID"
lib="$(cat "$cache/.library" 2>/dev/null)"
[[ -n "$lib" ]] || lib="$(_cdar_library_root)/$(_cdar_safe "$CDAR_ALBUM_ARTIST")/$(_cdar_safe "$CDAR_ALBUM")"

# Обкладинка: з бібліотеки, з кешу, або завантажити в кеш (якщо відомий реліз MusicBrainz)
cover=""
if [[ -s "$lib/cover.jpg" ]]; then cover="$lib/cover.jpg"
elif [[ -s "$cache/cover.jpg" ]]; then cover="$cache/cover.jpg"
elif [[ -n "$CDAR_MBID" ]]; then
  mkdir -p "$cache" && _cdar_cover "$cache"
  [[ -s "$cache/cover.jpg" ]] && cover="$cache/cover.jpg"
fi

clean() { printf '%s' "${1//[$'\t\n']/ }"; }
echo "DEVICE=$CDAR_DEVICE"
echo "TRACKS=$CDAR_TRACKS"
echo "DISC_ID=$CDAR_DISC_ID"
echo "MB_DISCID=$CDAR_MB_DISCID"
echo "SOURCE=$CDAR_META_SOURCE"
echo "ALBUM=$(clean "$CDAR_ALBUM")"
echo "ALBUM_ARTIST=$(clean "$CDAR_ALBUM_ARTIST")"
echo "YEAR=$CDAR_YEAR"
echo "LIBRARY_DIR=$lib"
echo "CACHE_DIR=$cache"
echo "COVER=$cover"
echo "MB_URL=$(_cdar_musicbrainz_url)"
for ((t = 1; t <= CDAR_TRACKS; t++)); do
  state=pending
  if compgen -G "$lib/$(printf '%02d' "$t") - *" >/dev/null 2>&1; then state=library
  elif [[ -f "$cache/.done-$t" ]]; then state=ripped
  fi
  printf 'T\t%d\t%s\t%s\t%d\t%s\t%d\n' "$t" "$(clean "${CDAR_ARTISTS[t-1]}")" "$(clean "${CDAR_TITLES[t-1]}")" \
    $(( CDAR_SECTORS[t-1] / 75 )) "$state" "$([[ -n "${CDAR_PLACEHOLDER[t-1]:-}" ]] && echo 1 || echo 0)"
done
