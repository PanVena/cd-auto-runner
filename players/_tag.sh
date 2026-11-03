#!/usr/bin/env bash
# Введення назв треків для диска, якого немає в базах (cd-auto-runner tag).
# Назви зберігаються в ~/.config/cd-auto-runner/discs/<discid>.conf і мають пріоритет
# над іншими джерелами. Уже скопійовані в бібліотеку треки переносяться під нові
# назви й отримують нові теги; копіювання решти треків продовжується з новими назвами.
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

CDAR_RIPPER="$(cdar_ripper)" || { cdar_log "$(_ 'не знайдено cd-paranoia/cdparanoia')"; exit 1; }
_cdar_read_toc || { cdar_log "$(_ 'Не вдалося прочитати диск')"; exit 1; }
_cdar_metadata

base="${XDG_CACHE_HOME:-$HOME/.cache}/cd-auto-runner/disc-$CDAR_DISC_ID"
old_lib="$(cat "$base/.library" 2>/dev/null)"
mode="$(cat "$base/.mode" 2>/dev/null)"
user="$(_cdar_user_disc_file)"

# --- шаблон для редагування -------------------------------------------------
if [[ -n "${CDAR_TAG_APPLY:-}" ]]; then SKIP_EDIT=1; else SKIP_EDIT=0; fi
if ((!SKIP_EDIT)); then
tmp="$(mktemp --suffix=.txt)"
trap 'rm -f -- "$tmp"' EXIT
{
  echo "# $(_ 'Назви треків для цього диска. Рядки, що починаються з #, ігноруються.')"
  echo "# $(_ 'Трек: «Виконавець - Назва» (для збірки) або просто «Назва».')"
  echo "# $(_ 'ALBUM_ARTIST порожній — визначиться сам (для збірки — Various Artists).')"
  echo "# $(_ 'Додати диск у MusicBrainz, щоб його розпізнавали всі:')"
  echo "#   $(_cdar_musicbrainz_url)"
  echo
  if [[ "$CDAR_META_SOURCE" == none ]]; then
    echo "ALBUM="; echo "ALBUM_ARTIST="; echo "YEAR="
  else
    echo "ALBUM=$CDAR_ALBUM"
    echo "ALBUM_ARTIST=$([[ "$CDAR_ALBUM_ARTIST" == "Various Artists" ]] || echo "$CDAR_ALBUM_ARTIST")"
    echo "YEAR=$CDAR_YEAR"
  fi
  echo
  for ((t = 1; t <= CDAR_TRACKS; t++)); do
    if [[ "$CDAR_META_SOURCE" == none || -n "${CDAR_PLACEHOLDER[t-1]:-}" ]]; then
      printf '%02d=\n' "$t"
    elif [[ "${CDAR_ARTISTS[t-1]}" != "$CDAR_ALBUM_ARTIST" || "$CDAR_ALBUM_ARTIST" == "Various Artists" ]]; then
      printf '%02d=%s - %s\n' "$t" "${CDAR_ARTISTS[t-1]}" "${CDAR_TITLES[t-1]}"
    else
      printf '%02d=%s\n' "$t" "${CDAR_TITLES[t-1]}"
    fi
  done
} > "$tmp"

# --- редагування ------------------------------------------------------------
title="$(_ 'Назви треків (на диску: %s)' "$CDAR_TRACKS")"
gui=0; [[ "${CDAR_TTY:-0}" != 1 && -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]] && gui=1
tagger="$(dirname "$CDAR_LIB")/_tagger.py"
if ((gui)) && [[ -f "$tagger" ]] && python3 -c 'import PySide6.QtWidgets' 2>/dev/null; then
  # Форма з полями й таблицею треків (PySide6)
  python3 -I "$tagger" "$tmp" "$title" "$(_cdar_musicbrainz_url)" || { cdar_log "$(_ 'Скасовано.')"; exit 0; }
elif ((gui)) && command -v kdialog >/dev/null 2>&1; then
  edited="$(kdialog --title "CD Auto Runner" --textinputbox "$title" "$(cat "$tmp")" 720 640)" || {
    cdar_log "$(_ 'Скасовано.')"; exit 0; }
  printf '%s\n' "$edited" > "$tmp"
else
  ed="${VISUAL:-${EDITOR:-}}"
  [[ -n "$ed" ]] || for ed in nano vim vi; do command -v "$ed" >/dev/null && break; done
  echo "$title"
  "$ed" "$tmp" || { cdar_log "$(_ 'Скасовано.')"; exit 0; }
fi

# Порожні назви — нічого не зберігаємо
if ! grep -qE '^(ALBUM|[0-9][0-9])=.+' "$tmp"; then
  cdar_log "$(_ 'Нічого не введено — назви не змінено.')"; exit 0
fi

mkdir -p "$(dirname "$user")"
{
  echo "# cd-auto-runner: $CDAR_MB_DISCID ($CDAR_TRACKS)"
  grep -E '^(ALBUM|ALBUM_ARTIST|YEAR|GENRE|[0-9][0-9])=' "$tmp"
} > "$user"
cdar_log "$(_ 'назви збережено: %s' "$user")"
fi

# --- застосування -----------------------------------------------------------
# Якщо цей процес сам живе в юніті копіювання (cd-auto-runner-play-*), зупинка копіювання
# вбила б і його — тоді застосовуємо зміни з окремого юніта.
if grep -q 'cd-auto-runner-play-' /proc/self/cgroup 2>/dev/null && [[ -z "${CDAR_TAG_APPLY:-}" ]] \
   && command -v systemd-run >/dev/null 2>&1; then
  exec systemd-run --user --quiet --collect --unit="cd-auto-runner-tag-$(date +%s%N)" \
    --setenv=CDAR_TAG_APPLY=1 --setenv=CDAR_LIB="$CDAR_LIB" --setenv=CDAR_DEVICE="$CDAR_DEVICE" \
    --setenv=CDAR_TRACKS="$CDAR_TRACKS" --setenv=CDAR_EXEC=true --setenv=CDAR_NAME="$CDAR_NAME" \
    --setenv=CDAR_NOTIFY="$CDAR_NOTIFY" --setenv=CDAR_LIBRARY="${CDAR_LIBRARY:-yes}" \
    --setenv=CDAR_LIBRARY_DIR="${CDAR_LIBRARY_DIR:-}" --setenv=CDAR_ONLINE="${CDAR_ONLINE:-yes}" \
    --setenv=CDAR_UI_LANG="${CDAR_UI_LANG:-uk}" --setenv=CDAR_I18N="${CDAR_I18N:-}" \
    --setenv=CDAR_SELF="$CDAR_SELF" --setenv=CDAR_RIP_FORMAT="${CDAR_RIP_FORMAT:-flac}" \
    -- bash "$0"
fi
# Фонове копіювання цього диска зупиняємо, оновлюємо скопійоване й запускаємо знову
running=0
if [[ -n "$(systemctl --user list-units 'cd-auto-runner-play-*' --no-legend --plain 2>/dev/null)" ]]; then
  running=1; "$CDAR_SELF" stop >/dev/null
fi

_cdar_metadata
new_lib="$(_cdar_library_root)/$(_cdar_safe "$CDAR_ALBUM_ARTIST")/$(_cdar_safe "$CDAR_ALBUM")"
if [[ -n "$old_lib" ]]; then
  _cdar_retag_library "$old_lib" "$new_lib"      # переносить треки й пише мітку
  printf '%s\n' "$new_lib" > "$base/.library"
elif [[ "${CDAR_LIBRARY:-yes}" == yes ]]; then
  mkdir -p "$new_lib" && _cdar_write_marker "$new_lib"
fi
cdar_notify "$CDAR_ALBUM_ARTIST — $CDAR_ALBUM" "$(_ 'Назви збережено.')"

if ((running)); then
  if [[ "$mode" == rip || -z "$mode" ]]; then "$CDAR_SELF" rip "$CDAR_DEVICE"
  elif [[ "$mode" == builtin ]]; then "$CDAR_SELF" play --player builtin --no-window "$CDAR_DEVICE"
  else "$CDAR_SELF" play --player "$mode" "$CDAR_DEVICE"
  fi
fi
