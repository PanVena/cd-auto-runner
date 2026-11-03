# shellcheck shell=bash
# _lib.sh — спільні функції для адаптерів програвачів cd-auto-runner.
#
# Адаптер — це bash-скрипт у теці players/, який знає, як відкрити аудіо-CD
# в одному конкретному програвачі. Його запускає cd-auto-runner зі змінними:
#
#   CDAR_DEVICE      шлях до приводу, напр. /dev/sr0
#   CDAR_TRACKS      кількість аудіотреків на диску
#   CDAR_EXEC        рядок Exec з .desktop-файлу програми (з %U/%F тощо)
#   CDAR_DESKTOP_ID  id .desktop-файлу, напр. org.kde.elisa.desktop
#   CDAR_NAME        назва програми
#   CDAR_FLATPAK     Flatpak ID (порожньо для звичайних пакетів)
#   CDAR_DRY_RUN     1 — нічого не запускати, лише вивести команди
#   CDAR_NOTIFY      yes/no — показувати сповіщення
#   CDAR_RIP_FORMAT  формат копіювання треків: flac (типово) | opus | ogg | mp3 | wav
#   CDAR_LIBRARY     yes — зберігати альбом у теку музики; no — лише кеш
#   CDAR_LIBRARY_DIR тека бібліотеки (типово — XDG MUSIC, напр. ~/Музика)
#   CDAR_ONLINE      yes — брати назви й обкладинку з MusicBrainz
#   CDAR_RESUME      seek | restart — як відновити трек після перемикання (адаптер)
#
# Заголовок адаптера (читається cd-auto-runner):
#   # cdar-desktop-ids: id1.desktop id2.desktop …
#   # cdar-note: короткий опис способу (необов'язково)
#
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena

set -uo pipefail

# Переклад (i18n.sh): CDAR_I18N передає cd-auto-runner; без нього — українською
if [[ -n "${CDAR_I18N:-}" && -f "$CDAR_I18N" ]]; then
  # shellcheck source=../i18n.sh
  source "$CDAR_I18N"
else
  _() { local s="$1"; shift; if (($#)); then printf -- "$s" "$@"; else printf '%s' "$s"; fi; }
fi

: "${CDAR_DEVICE:?}" "${CDAR_EXEC:?}"
CDAR_TRACKS="${CDAR_TRACKS:-1}"
CDAR_NAME="${CDAR_NAME:-player}"
CDAR_FLATPAK="${CDAR_FLATPAK:-}"
CDAR_DRY_RUN="${CDAR_DRY_RUN:-0}"
CDAR_NOTIFY="${CDAR_NOTIFY:-yes}"
CDAR_NOTIFY_ID=""

cdar_log() { printf '[%s] %s\n' "$CDAR_NAME" "$*" >&2; }

# Сповіщення; повторні виклики оновлюють те саме сповіщення
cdar_notify() {
  [[ "$CDAR_NOTIFY" == yes && "$CDAR_DRY_RUN" != 1 ]] || return 0
  command -v notify-send >/dev/null 2>&1 || return 0
  local args=(-a "CD Auto Runner" -i media-optical-audio -p)
  [[ -n "$CDAR_NOTIFY_ID" ]] && args+=(-r "$CDAR_NOTIFY_ID")
  local id
  id="$(notify-send "${args[@]}" "$1" "${2:-}" 2>/dev/null)" && [[ "$id" =~ ^[0-9]+$ ]] && CDAR_NOTIFY_ID="$id"
  return 0
}

_cdar_quote() {  # читабельне екранування для --dry-run
  local t out=""
  for t in "$@"; do
    if [[ "$t" =~ ^[][A-Za-z0-9_./:=@%+,{}?-]+$ ]]; then out+=" $t"
    else out+=" '${t//\'/\'\\\'\'}'"
    fi
  done
  printf '%s\n' "${out# }"
}

# Запускає програму за її рядком Exec, підставляючи аргументи замість %U/%u/%F/%f.
#
#   cdar_launch [--urls] [--opt ОПЦІЯ]… -- АРГУМЕНТ…
#
#   --urls  аргументи — адреси (cdda://…), а не файли: Flatpak-обгортку «@@ … @@»
#           (передача файлів через портал) буде прибрано
#   --opt   опція програми, що ставиться перед аргументами (перед «--», якщо він є)
#   --wait  виконати й дочекатися завершення (напр. «додати в чергу» до вже запущеної
#           програми — щоб кілька таких команд виконались строго по черзі)
cdar_launch() {
  local urls=0 wait=0
  local -a opts=() args=()
  while (($#)); do
    case "$1" in
      --urls) urls=1 ;;
      --wait) wait=1 ;;
      --opt) opts+=("$2"); shift ;;
      --) shift; args=("$@"); break ;;
      *) cdar_log "cdar_launch: unknown option $1"; return 2 ;;
    esac
    shift
  done

  # Flatpak і так бачить ці файли напряму — передаємо шляхи без порталу документів
  # (портал кешує вміст: файл, що дописується під час копіювання, читався б як тиша)
  if ((!urls)) && [[ -n "$CDAR_FLATPAK" ]] && _cdar_flatpak_reads_all "${args[@]}"; then urls=1; fi

  # Розбір Exec на слова з урахуванням лапок (xargs не виконує жодних підстановок)
  local -a w=() out=()
  mapfile -d '' w < <(printf '%s' "${CDAR_EXEC//%%/$'\x01'}" | xargs printf '%s\0')
  ((${#w[@]})) || { cdar_log "empty Exec"; return 1; }

  local i t ci=-1
  for i in "${!w[@]}"; do [[ "${w[$i]}" =~ ^%[fFuU]$ ]] && { ci=$i; break; }; done

  if ((ci >= 0)); then
    local ws=$ci we=$ci dd=-1 ins
    if ((ci > 0)) && [[ "${w[ci-1]}" == @@* && "${w[ci+1]:-}" == @@ ]]; then ws=$((ci - 1)); we=$((ci + 1)); fi
    for ((i = 0; i < ws; i++)); do [[ "${w[$i]}" == -- ]] && dd=$i; done
    ins=$ws; ((dd >= 0)) && ins=$dd
    out=("${w[@]:0:ins}" "${opts[@]}" "${w[@]:ins:ws-ins}")
    if ((urls || ws == ci)); then out+=("${args[@]}")
    elif [[ "${w[ws]}" == "@@u" ]]; then
      # Flatpak чекає тут адреси (URI), а не шляхи
      local a; out+=("@@u"); for a in "${args[@]}"; do out+=("$(_cdar_file_uri "$a")"); done; out+=("@@")
    else out+=("${w[ws]}" "${args[@]}" "@@")
    fi
    out+=("${w[@]:we+1}")
  else
    # Код вбудований у слово (напр. cdda://%f) або відсутній
    local embedded=0 t
    for t in "${w[@]}"; do
      if [[ "$t" =~ %[fFuU] ]]; then
        local code="${BASH_REMATCH[0]}"
        out+=("${t%%"$code"*}${args[0]:-}${t#*"$code"}"); embedded=1
      else
        out+=("$t")
      fi
    done
    ((embedded)) || out+=("${opts[@]}" "${args[@]}")
  fi

  # Прибираємо решту кодів (%i %c %k …) і відновлюємо «%%» → «%»
  local -a final=()
  for t in "${out[@]}"; do
    [[ "$t" =~ ^%[a-zA-Z]$ ]] && continue
    final+=("${t//$'\x01'/%}")
  done

  if [[ "$CDAR_DRY_RUN" == 1 ]]; then _cdar_quote "${final[@]}"; return 0; fi
  cdar_log "$(_ 'запуск: %s' "$(_cdar_quote "${final[@]}")")"
  if ((wait)); then
    timeout 30 "${final[@]}" >/dev/null 2>&1 < /dev/null
    return 0
  fi
  if command -v systemd-run >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    systemd-run --user --quiet --collect --unit="cd-auto-runner-app-$(date +%s%N)" \
      --description="CD Auto Runner: $CDAR_NAME" -- "${final[@]}" && return 0
  fi
  setsid -f "${final[@]}" >/dev/null 2>&1 < /dev/null
}

# Шлях → file:// URI (з відсотковим кодуванням)
_cdar_file_uri() {
  [[ "$1" == /* ]] || { printf '%s' "$1"; return; }
  if command -v python3 >/dev/null 2>&1; then
    python3 -I -c 'import sys, urllib.parse; print("file://" + urllib.parse.quote(sys.argv[1]))' "$1"
  else
    printf 'file://%s' "$(sed 's/%/%25/g; s/ /%20/g; s/#/%23/g; s/?/%3F/g' <<< "$1")"
  fi
}

# Чи має Flatpak-програма прямий доступ до всіх цих файлів (filesystems=home/host/…)
_cdar_flatpak_reads_all() {
  local perms fs f ok e path
  perms="$(flatpak info --show-permissions "$CDAR_FLATPAK" 2>/dev/null | sed -n 's/^filesystems=//p')"
  [[ -n "$perms" ]] || return 1
  for f in "$@"; do
    [[ "$f" == /* ]] || return 1
    ok=0
    local IFS=';'
    for e in $perms; do
      e="${e%%:*}"                                  # без :ro/:rw/:create
      case "$e" in
        host|host-os|host-etc) [[ "$f" != /home/* || "$e" == host ]] && ok=1 ;;
        home) [[ "$f" == "$HOME"/* && "$f" != "$HOME"/.var/app/* ]] && ok=1 ;;
        xdg-cache*) path="${XDG_CACHE_HOME:-$HOME/.cache}${e#xdg-cache}"; [[ "$f" == "$path"/* ]] && ok=1 ;;
        xdg-music*) path="$(_cdar_library_root)${e#xdg-music}"; [[ "$f" == "$path"/* ]] && ok=1 ;;
        "~/"*) [[ "$f" == "$HOME/${e#\~/}"/* ]] && ok=1 ;;
        /*) [[ "$f" == "${e%/}"/* ]] && ok=1 ;;
      esac
      ((ok)) && break
    done
    unset IFS
    ((ok)) || return 1
  done
  return 0
}

# Адреси для кожного треку: cdar_track_urls 'cdda://?' → cdda://?1 … cdda://?N
cdar_track_urls() {
  local t
  for ((t = 1; t <= CDAR_TRACKS; t++)); do printf '%s%s\0' "$1" "$t"; done
}

# Перевіряє, чи має Flatpak-програма доступ до приводу
cdar_flatpak_device_ok() {
  [[ -z "$CDAR_FLATPAK" ]] && return 0
  flatpak info --show-permissions "$CDAR_FLATPAK" 2>/dev/null | grep -q '^devices=.*all' && return 0
  cdar_notify "$(_ '%s не бачить CD-привід' "$CDAR_NAME")" \
    "$(_ 'Надайте доступ: flatpak override --user --device=all %s' "$CDAR_FLATPAK")"
  cdar_log "$(_ 'Flatpak %s не має доступу до пристроїв (--device=all)' "$CDAR_FLATPAK")"
  return 1
}


# ---------------------------------------------------------------------------
# Режим «копіювання треків» для програвачів, які не відкривають диск напряму
# (Elisa, QMPlay2), і копіювання диска в бібліотеку музики — як у Windows Media Player.
#
#   CDAR_LIBRARY=yes   треки зберігаються в ~/Музика/Виконавець/Альбом/NN - Назва.flac
#                      з тегами й обкладинкою; альбом докопіюється, навіть якщо
#                      програвач закрито. Уже скопійовані треки беруться звідти.
#   CDAR_LIBRARY=no    треки лише в кеші ~/.cache/cd-auto-runner (тільки поточний диск);
#                      копіювання зупиняється, коли програвач закрито.
#
# Перший трек відкривається через кілька секунд, ще під час копіювання.
# ---------------------------------------------------------------------------
cdar_ripper() {
  local t
  for t in cd-paranoia cdparanoia; do command -v "$t" >/dev/null 2>&1 && { echo "$t"; return 0; }; done
  return 1
}

# Читає зміст диска: CDAR_DISC_ID, CDAR_SECTORS[], CDAR_STARTS[], CDAR_MB_DISCID
# Кеш змісту диска: поки диск у приводі, зміст не змінюється, а читати його довго
# (особливо коли привід зайнятий копіюванням). Ключ — diskseq ядра (росте з кожною
# зміною носія), розмір диска й кількість аудіотреків; тож чужий зміст не підхопиться,
# навіть якщо служба не стежила за приводом.
cdar_toc_cache() {
  printf '%s/cd-auto-runner/toc-%s' "${XDG_RUNTIME_DIR:-/tmp}" "$(basename "$CDAR_DEVICE")"
}

_cdar_read_toc() {
  local toc cache audio key sys
  cache="$(cdar_toc_cache)"
  audio="$(udevadm info --query=property --name="$CDAR_DEVICE" 2>/dev/null | sed -n 's/^ID_CDROM_MEDIA_TRACK_COUNT_AUDIO=//p')"
  sys="/sys/class/block/$(basename "$(readlink -f "$CDAR_DEVICE")")"
  key="KEY=$(cat "$sys/diskseq" 2>/dev/null):$(cat "$sys/size" 2>/dev/null):$audio"
  if [[ -n "$audio" && -s "$cache" && "$(head -n1 "$cache")" == "$key" ]]; then
    toc="$(tail -n +2 "$cache")"
  else
    toc="$("$CDAR_RIPPER" -Q -d "$CDAR_DEVICE" 2>&1 | grep -E '^[[:space:]]+[0-9]+\.')"
    if [[ -n "$toc" && -n "$audio" ]]; then
      mkdir -p "$(dirname "$cache")" && { echo "$key"; printf '%s\n' "$toc"; } > "$cache"
    fi
  fi
  [[ -n "$toc" ]] || return 1
  CDAR_DISC_ID="$(md5sum <<< "$toc" | cut -c1-12)"
  mapfile -t CDAR_SECTORS < <(awk '{print $2}' <<< "$toc")
  mapfile -t CDAR_STARTS < <(awk '{print $4}' <<< "$toc")
  CDAR_MB_DISCID="$(_cdar_mb_discid "$toc")"
}

# Ідентифікатор диска MusicBrainz (той самий, яким KDE кешує дані в ~/.cddb/musicbrainz)
_cdar_mb_discid() {
  local -a num len st
  mapfile -t num < <(awk '{sub(/\./,"",$1); print $1}' <<< "$1")
  mapfile -t len < <(awk '{print $2}' <<< "$1")
  mapfile -t st < <(awk '{print $4}' <<< "$1")
  local n=${#num[@]} i s hex
  ((n)) || return 1
  s="$(printf '%02X%02X%08X' "${num[0]}" "${num[n-1]}" $(( st[n-1] + len[n-1] + 150 )))"
  for ((i = 0; i < 99; i++)); do
    if ((i < n)); then s+="$(printf '%08X' $(( st[i] + 150 )))"; else s+="00000000"; fi
  done
  hex="$(printf '%s' "$s" | sha1sum | cut -c1-40)"
  printf "$(sed 's/../\\x&/g' <<< "$hex")" | base64 | tr '+/=' '._-'
}

_cdar_safe() {  # безпечне ім'я файлу/теки
  local s="${1//\//∕}"
  s="${s//$'\n'/ }"; s="${s#.}"
  s="$(sed 's/^[[:space:]]*//; s/[[:space:]]*$//' <<< "$s")"
  printf '%s' "${s:-_}"
}

# Назви, введені вручну (cd-auto-runner tag): ~/.config/cd-auto-runner/discs/<discid>.conf
_cdar_user_disc_file() {
  printf '%s/cd-auto-runner/discs/%s.conf' "${XDG_CONFIG_HOME:-$HOME/.config}" "${CDAR_MB_DISCID:-none}"
}

# Читає файл назв (формат cd-auto-runner: ALBUM=, ALBUM_ARTIST=, YEAR=, GENRE=, NN=…)
_cdar_read_titles() {
  local k v n
  while IFS='=' read -r k v; do
    case "$k" in
      ALBUM) CDAR_ALBUM="$v" ;;
      ALBUM_ARTIST) CDAR_ALBUM_ARTIST="$v" ;;
      YEAR) CDAR_YEAR="$v" ;;
      GENRE) CDAR_GENRE="$v" ;;
      MBID) CDAR_MBID="$v" ;;
      [0-9][0-9])
        n=$((10#$k - 1))
        # «Виконавець - Назва»; пробіл може бути лише з одного боку дефіса
        # («Powerwolf -My Will Be Done»), а «Jay-Z» без пробілів не розбивається
        if [[ "$v" =~ ^(.*[^[:space:]])[[:space:]]+-[[:space:]]*([^[:space:]].*)$ \
           || "$v" =~ ^(.*[^[:space:]])[[:space:]]*-[[:space:]]+([^[:space:]].*)$ ]]; then
          CDAR_ARTISTS[n]="${BASH_REMATCH[1]}"; CDAR_TITLES[n]="${BASH_REMATCH[2]}"
        else
          CDAR_TITLES[n]="$v"
        fi ;;
    esac
  done < <(grep -v '^[[:space:]]*#' "$1")
}

# Прихована мітка в теці альбому: бібліотека сама пам'ятає, з якого диска альбом,
# тож диск розпізнається навіть після перевстановлення чи видалення налаштувань.
CDAR_MARKER=".cd-auto-runner"

_cdar_find_in_library() {
  local root; root="$(_cdar_library_root)"
  [[ -d "$root" && -n "${CDAR_MB_DISCID:-}" ]] || return 1
  find "$root" -maxdepth 4 -name "$CDAR_MARKER" -type f -exec grep -lxF "DISCID=$CDAR_MB_DISCID" {} + 2>/dev/null | head -n1
}

_cdar_write_marker() {  # _cdar_write_marker <тека альбому>
  local dir="$1" t a
  [[ -d "$dir" && -n "${CDAR_MB_DISCID:-}" ]] || return 0
  {
    echo "# cd-auto-runner: $(_ 'з якого диска цей альбом (не видаляйте — так диск розпізнається знову)')"
    echo "DISCID=$CDAR_MB_DISCID"
    echo "ALBUM=$CDAR_ALBUM"
    echo "ALBUM_ARTIST=$CDAR_ALBUM_ARTIST"
    echo "YEAR=$CDAR_YEAR"
    [[ -n "$CDAR_GENRE" ]] && echo "GENRE=$CDAR_GENRE"
    [[ -n "$CDAR_MBID" ]] && echo "MBID=$CDAR_MBID"
    for ((t = 1; t <= CDAR_TRACKS; t++)); do
      a="${CDAR_ARTISTS[t-1]}"
      if [[ -n "${CDAR_PLACEHOLDER[t-1]:-}" ]]; then printf '%02d=\n' "$t"     # назва невідома
      elif [[ "$a" != "$CDAR_ALBUM_ARTIST" ]]; then printf '%02d=%s - %s\n' "$t" "$a" "${CDAR_TITLES[t-1]}"
      else printf '%02d=%s\n' "$t" "${CDAR_TITLES[t-1]}"; fi
    done
  } > "$dir/$CDAR_MARKER"
}

# Посилання, щоб додати цей диск у MusicBrainz
_cdar_musicbrainz_url() {
  local n=${#CDAR_STARTS[@]} t toc
  ((n)) || return 1
  toc="1+$n+$(( CDAR_STARTS[n-1] + CDAR_SECTORS[n-1] + 150 ))"
  for t in "${CDAR_STARTS[@]}"; do toc+="+$((t + 150))"; done
  printf 'https://musicbrainz.org/cdtoc/attach?id=%s&tracks=%s&toc=%s' "$CDAR_MB_DISCID" "$n" "$toc"
}

# Метадані диска: CDAR_ALBUM, CDAR_ALBUM_ARTIST, CDAR_YEAR, CDAR_GENRE, CDAR_MBID,
# CDAR_TITLES[], CDAR_ARTISTS[], CDAR_META_SOURCE (user|library|kde|musicbrainz|none). Джерела:
#   1) назви, введені вручну (cd-auto-runner tag) — мають пріоритет над усім;
#   1a) мітка .cd-auto-runner у теці альбому в бібліотеці (диск уже копіювали);
#   2) кеш KDE ~/.cddb/musicbrainz/<discid> (без інтернету);
#   3) MusicBrainz (якщо CDAR_ONLINE=yes) — також дає id релізу для обкладинки;
#   4) нічого не знайдено — «Невідомий виконавець / Аудіо-CD», «Трек NN».
# Збірка різних виконавців (наприклад, диск із журналу) — виконавець альбому «Various Artists».
_cdar_metadata() {
  CDAR_ALBUM=""; CDAR_ALBUM_ARTIST=""; CDAR_YEAR=""; CDAR_GENRE=""; CDAR_MBID=""
  CDAR_TITLES=(); CDAR_ARTISTS=(); CDAR_META_SOURCE=none; CDAR_PLACEHOLDER=()
  local f k v n user found
  user="$(_cdar_user_disc_file)"
  if [[ -r "$user" ]]; then
    _cdar_read_titles "$user"
    CDAR_META_SOURCE=user
    cdar_log "$(_ 'назви, введені вручну: %s' "$user")"
  elif found="$(_cdar_find_in_library)" && [[ -n "$found" ]]; then
    _cdar_read_titles "$found"
    CDAR_META_SOURCE=library
    cdar_log "$(_ 'диск уже є в бібліотеці: %s' "$(dirname "$found")")"
  fi

  f="$HOME/.cddb/musicbrainz/${CDAR_MB_DISCID:-none}"
  if [[ "$CDAR_META_SOURCE" == none && -r "$f" ]]; then
    CDAR_META_SOURCE=kde
    while IFS='=' read -r k v; do
      case "$k" in
        DTITLE) CDAR_ALBUM_ARTIST="${v%% / *}"; CDAR_ALBUM="${v#* / }"
                [[ "$v" == *" / "* ]] || { CDAR_ALBUM="$v"; CDAR_ALBUM_ARTIST=""; } ;;
        DYEAR)  CDAR_YEAR="$v" ;;
        DGENRE) CDAR_GENRE="$v" ;;
        TTITLE[0-9]*)
          n="${k#TTITLE}"
          if [[ "$v" == *" / "* ]]; then CDAR_ARTISTS[n]="${v%% / *}"; CDAR_TITLES[n]="${v#* / }"
          else CDAR_TITLES[n]="$v"; fi ;;
      esac
    done < "$f"
    cdar_log "$(_ 'метадані з кешу KDE: %s — %s' "$CDAR_ALBUM_ARTIST" "$CDAR_ALBUM")"
  fi

  if [[ "$CDAR_META_SOURCE" != user && "$CDAR_META_SOURCE" != library && "${CDAR_ONLINE:-yes}" == yes && -n "${CDAR_MB_DISCID:-}" ]] \
     && command -v curl >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    local json line
    json="$(curl -fsS -m 15 -A 'cd-auto-runner/1.0 ( https://github.com/ )' \
      "https://musicbrainz.org/ws/2/discid/$CDAR_MB_DISCID?inc=artist-credits+recordings&fmt=json" 2>/dev/null)"
    if [[ -n "$json" ]]; then
      while IFS=$'\x1f' read -r k n v line; do
        case "$k" in
          MBID)   CDAR_MBID="$v" ;;
          ALBUM)  CDAR_ALBUM="$v" ;;
          ARTIST) CDAR_ALBUM_ARTIST="$v" ;;
          YEAR)   CDAR_YEAR="$v" ;;
          T)      CDAR_TITLES[n-1]="$v"; [[ -n "$line" ]] && CDAR_ARTISTS[n-1]="$line" ;;
        esac
      done < <(python3 -I -c '
import json, sys
d = json.loads(sys.stdin.read()); want = sys.argv[1]
def credit(ac): return "".join(a.get("name", "") + a.get("joinphrase", "") for a in ac or [])
for rel in d.get("releases", []):
    for m in rel.get("media", []):
        if any(x.get("id") == want for x in m.get("discs", [])):
            aa = credit(rel.get("artist-credit"))
            print("MBID", "", rel["id"], "", sep="\x1f")
            print("ALBUM", "", rel.get("title", ""), "", sep="\x1f")
            print("ARTIST", "", aa, "", sep="\x1f")
            print("YEAR", "", (rel.get("date") or "")[:4], "", sep="\x1f")
            for t in m.get("tracks", []):
                ta = credit(t.get("artist-credit"))
                print("T", t.get("position"), t.get("title", ""), ta if ta != aa else "", sep="\x1f")
            sys.exit(0)
' "$CDAR_MB_DISCID" <<< "$json" 2>/dev/null)
      [[ -n "$CDAR_MBID" ]] && CDAR_META_SOURCE=musicbrainz && cdar_log "$(_ 'метадані з MusicBrainz: %s — %s (%s)' "$CDAR_ALBUM_ARTIST" "$CDAR_ALBUM" "$CDAR_YEAR")"
    fi
  fi

  # Виконавець альбому не вказаний, а виконавці треків різні — це збірка
  if [[ -z "$CDAR_ALBUM_ARTIST" ]]; then
    local first="" diff=0
    for n in "${!CDAR_ARTISTS[@]}"; do
      [[ -n "${CDAR_ARTISTS[n]}" ]] || continue
      if [[ -z "$first" ]]; then first="${CDAR_ARTISTS[n]}"; elif [[ "${CDAR_ARTISTS[n]}" != "$first" ]]; then diff=1; fi
    done
    if ((diff)); then CDAR_ALBUM_ARTIST="Various Artists"; else CDAR_ALBUM_ARTIST="$first"; fi
  fi

  [[ -n "$CDAR_ALBUM_ARTIST" ]] || CDAR_ALBUM_ARTIST="$(_ 'Невідомий виконавець')"
  [[ -n "$CDAR_ALBUM" ]] || CDAR_ALBUM="$(_ 'Аудіо-CD %s' "${CDAR_DISC_ID:-}")"
  for ((n = 0; n < CDAR_TRACKS; n++)); do
    [[ -n "${CDAR_TITLES[n]:-}" ]] || { CDAR_TITLES[n]="$(_ 'Трек %02d' $((n + 1)))"; CDAR_PLACEHOLDER[n]=1; }
    [[ -n "${CDAR_ARTISTS[n]:-}" ]] || CDAR_ARTISTS[n]="$CDAR_ALBUM_ARTIST"
  done
}

# Тека бібліотеки музики (XDG MUSIC, напр. ~/Музика)
_cdar_library_root() {
  local d="${CDAR_LIBRARY_DIR:-}"
  if [[ -z "$d" ]] && command -v xdg-user-dir >/dev/null 2>&1; then d="$(xdg-user-dir MUSIC 2>/dev/null)"; fi
  [[ -z "$d" || "$d" == "$HOME" ]] && d="$HOME/Music"
  printf '%s' "$d"
}

_cdar_cover() {  # обкладинка з Cover Art Archive → cover.jpg (як Folder.jpg у WMP)
  local dir="$1"
  [[ -n "$CDAR_MBID" && ! -s "$dir/cover.jpg" && "${CDAR_ONLINE:-yes}" == yes ]] || return 0
  command -v curl >/dev/null 2>&1 || return 0
  curl -fsSL -m 10 -A 'cd-auto-runner/1.0' "https://coverartarchive.org/release/$CDAR_MBID/front-500" \
    -o "$dir/cover.jpg.part" 2>/dev/null && mv -f -- "$dir/cover.jpg.part" "$dir/cover.jpg"
  rm -f -- "$dir/cover.jpg.part"
}

# Формат: wav (без перекодування) | flac | opus | ogg | mp3
_cdar_format() {
  local f="${CDAR_RIP_FORMAT:-flac}"
  case "$f" in wav|flac|opus|ogg|mp3) ;; *) f=flac ;; esac
  [[ "$f" != wav ]] && ! command -v ffmpeg >/dev/null 2>&1 && f=wav
  echo "$f"
}

# _cdar_encode <wav> <вихідний файл> <формат> <номер> [keep — не видаляти wav]
_cdar_encode() {
  local in="$1" out="$2" fmt="$3" t="$4" keep="${5:-}"
  local -a codec meta=(
    -metadata "title=${CDAR_TITLES[t-1]}" -metadata "artist=${CDAR_ARTISTS[t-1]}"
    -metadata "album=$CDAR_ALBUM" -metadata "album_artist=$CDAR_ALBUM_ARTIST"
    -metadata "track=$t/$CDAR_TRACKS"
  )
  [[ -n "$CDAR_YEAR" ]] && meta+=(-metadata "date=$CDAR_YEAR")
  [[ -n "$CDAR_GENRE" ]] && meta+=(-metadata "genre=$CDAR_GENRE")
  [[ -n "$CDAR_MBID" ]] && meta+=(-metadata "MUSICBRAINZ_ALBUMID=$CDAR_MBID")
  [[ -n "${CDAR_MB_DISCID:-}" ]] && meta+=(-metadata "MUSICBRAINZ_DISCID=$CDAR_MB_DISCID")
  [[ "$CDAR_ALBUM_ARTIST" == "Various Artists" ]] && meta+=(-metadata "compilation=1")
  case "$fmt" in
    flac) codec=(-c:a flac -f flac) ;;
    opus) codec=(-c:a libopus -b:a 160k -f ogg) ;;
    ogg)  codec=(-c:a libvorbis -q:a 6 -f ogg) ;;
    mp3)  codec=(-c:a libmp3lame -q:a 2 -id3v2_version 3 -f mp3) ;;
    wav)  codec=(-c:a copy -f wav) ;;
  esac
  # Обкладинка всередині файлу (FLAC, MP3) — видно в будь-якому програвачі й без cover.jpg
  local -a pic=()
  if [[ -s "${CDAR_COVER:-}" && ( "$fmt" == flac || "$fmt" == mp3 ) ]]; then
    pic=(-i "$CDAR_COVER" -map 0:a -map 1:v -c:v copy -disposition:v attached_pic
         -metadata:s:v "title=Album cover" -metadata:s:v "comment=Cover (front)")
  fi
  ffmpeg -nostdin -hide_banner -loglevel error -y -i "$in" "${pic[@]}" "${meta[@]}" "${codec[@]}" "$out.part" \
    && mv -f -- "$out.part" "$out" || { rm -f -- "$out.part"; return 1; }
  [[ -n "$keep" ]] || rm -f -- "$in"
}

# Ім'я файлу треку в бібліотеці: «NN - Назва»; якщо виконавець треку інший, ніж
# виконавець альбому (збірка, журнальний диск) — «NN - Виконавець - Назва»
_cdar_track_stem() {
  local t="$1"
  if [[ "$CDAR_ALBUM_ARTIST" == "Various Artists" || "${CDAR_ARTISTS[t-1]}" != "$CDAR_ALBUM_ARTIST" ]]; then
    printf '%02d - %s - %s' "$t" "$(_cdar_safe "${CDAR_ARTISTS[t-1]}")" "$(_cdar_safe "${CDAR_TITLES[t-1]}")"
  else
    printf '%02d - %s' "$t" "$(_cdar_safe "${CDAR_TITLES[t-1]}")"
  fi
}

# Після зміни назв: переносить уже скопійовані треки зі старої теки бібліотеки в нову,
# перейменовує їх і переписує теги (без перекодування). Порожні старі теки видаляє.
_cdar_retag_library() {
  local old="$1" new="$2" t f ext out
  [[ -d "$old" ]] || return 0
  mkdir -p "$new"
  for ((t = 1; t <= CDAR_TRACKS; t++)); do
    for f in "$old/$(printf '%02d' "$t") - "*; do
      [[ -f "$f" && "$f" != *.part ]] || continue
      ext="${f##*.}"
      out="$new/$(_cdar_track_stem "$t").$ext"
      local -a meta=(
        -metadata "title=${CDAR_TITLES[t-1]}" -metadata "artist=${CDAR_ARTISTS[t-1]}"
        -metadata "album=$CDAR_ALBUM" -metadata "album_artist=$CDAR_ALBUM_ARTIST"
        -metadata "track=$t/$CDAR_TRACKS"
      )
      [[ -n "$CDAR_YEAR" ]] && meta+=(-metadata "date=$CDAR_YEAR")
      [[ "$CDAR_ALBUM_ARTIST" == "Various Artists" ]] && meta+=(-metadata "compilation=1")
      [[ -n "${CDAR_MB_DISCID:-}" ]] && meta+=(-metadata "MUSICBRAINZ_DISCID=$CDAR_MB_DISCID")
      if ffmpeg -nostdin -hide_banner -loglevel error -y -i "$f" -map 0 -c copy "${meta[@]}" \
           -f "$(case "$ext" in opus|ogg) echo ogg ;; *) echo "$ext" ;; esac)" "$out.part" \
         && mv -f -- "$out.part" "$out"; then
        [[ "$f" -ef "$out" ]] || rm -f -- "$f"
      else
        rm -f -- "$out.part"; cdar_log "$(_ 'не вдалося оновити теги: %s' "$f")"
      fi
    done
  done
  [[ -f "$old/cover.jpg" && ! -e "$new/cover.jpg" ]] && mv -- "$old/cover.jpg" "$new/"
  [[ "$old" -ef "$new" ]] || rm -f -- "$old/$CDAR_MARKER"
  _cdar_write_marker "$new"
  if [[ ! "$old" -ef "$new" ]]; then
    rmdir -- "$old" 2>/dev/null && rmdir -- "$(dirname "$old")" 2>/dev/null
  fi
  return 0
}

# Диск не знайдено в базах — сповіщення з кнопкою «Ввести назви…» (лише один раз для диска)
_cdar_offer_tagging() {
  local mark="$1"
  [[ -e "$mark" || -z "${CDAR_SELF:-}" ]] && return 0
  : > "$mark"
  # Окремий юніт systemd: якщо після введення назв копіювання (цей юніт) зупинять,
  # редактор назв має жити далі. setsid тут не допоможе — процес лишився б у тому ж юніті.
  if command -v systemd-run >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    systemd-run --user --quiet --collect --unit="cd-auto-runner-tag-$(date +%s%N)" \
      --description="CD Auto Runner: tag" -- "$CDAR_SELF" ask-tag "$CDAR_DEVICE" && return 0
  fi
  setsid -f "$CDAR_SELF" ask-tag "$CDAR_DEVICE" >/dev/null 2>&1 < /dev/null
}

# Чи працює програвач: Flatpak — за «flatpak ps», інакше — за назвою процесу з Exec
_cdar_player_alive() {
  if [[ -n "$CDAR_FLATPAK" ]]; then
    flatpak ps --columns=application 2>/dev/null | grep -qx "$CDAR_FLATPAK"; return
  fi
  local w bin=""
  while IFS= read -r w; do
    [[ "$w" == env || "$w" == *=* ]] && continue
    bin="$(basename "$w")"; break
  done < <(printf '%s' "$CDAR_EXEC" | xargs printf '%s\n' 2>/dev/null)
  [[ -n "$bin" ]] && pgrep -u "$UID" -x "${bin:0:15}" >/dev/null
}

# Чекає, поки програвач запуститься (до N секунд, типово 20)
cdar_wait_player() {
  local i
  [[ "$CDAR_DRY_RUN" == 1 ]] && return 0
  for ((i = 0; i < ${1:-20} * 4; i++)); do
    _cdar_player_alive && { CDAR_SEEN_ALIVE=1; return 0; }
    sleep 0.25
  done
  return 1
}

# 0 — програвач закрили (його вже бачили запущеним, а тепер його немає), 1 — працюємо далі.
_cdar_player_closed() {
  [[ "${CDAR_MODE:-play}" == play ]] || return 1
  if _cdar_player_alive; then CDAR_SEEN_ALIVE=1; return 1; fi
  [[ "${CDAR_SEEN_ALIVE:-0}" == 1 ]]
}


# --- WAV із тегами ---------------------------------------------------------
_cdar_le32() { printf "\\x$(printf %02x $(($1 & 255)))\\x$(printf %02x $((($1 >> 8) & 255)))\\x$(printf %02x $((($1 >> 16) & 255)))\\x$(printf %02x $((($1 >> 24) & 255)))"; }
_cdar_le16() { printf "\\x$(printf %02x $(($1 & 255)))\\x$(printf %02x $((($1 >> 8) & 255)))"; }

# Підчастина LIST/INFO: id + розмір + рядок із нулем у кінці, вирівняний до парної довжини
_cdar_info_item() {
  local id="$1" val="$2" len
  [[ -n "$val" ]] || return 0
  len=$(( $(printf '%s' "$val" | wc -c) + 1 ))
  printf '%s' "$id"; _cdar_le32 "$len"; printf '%s\0' "$val"
  ((len % 2)) && printf '\0'
  return 0
}

# _cdar_wav_prealloc <файл> <трек>: заголовок WAV з тегами (INFO) + файл повного розміру.
# Виводить довжину заголовка — з цього місця cd-paranoia дописує звук.
_cdar_wav_prealloc() {
  local out="$1" t="$2" data info hdr
  data=$(( ${CDAR_SECTORS[t-1]} * 2352 ))
  info="$(mktemp)"
  {
    printf 'INFO'
    _cdar_info_item INAM "${CDAR_TITLES[t-1]}"
    _cdar_info_item IART "${CDAR_ARTISTS[t-1]}"
    _cdar_info_item IPRD "$CDAR_ALBUM"
    _cdar_info_item ITRK "$t"
    _cdar_info_item ICRD "$CDAR_YEAR"
  } > "$info"
  local isz; isz=$(stat -c %s "$info")
  {
    printf 'RIFF'; _cdar_le32 $(( 4 + 24 + 8 + isz + 8 + data )); printf 'WAVE'
    printf 'fmt '; _cdar_le32 16; _cdar_le16 1; _cdar_le16 2; _cdar_le32 44100; _cdar_le32 176400
    _cdar_le16 4; _cdar_le16 16
    printf 'LIST'; _cdar_le32 "$isz"; cat "$info"
    printf 'data'; _cdar_le32 "$data"
  } > "$out"
  rm -f -- "$info"
  hdr=$(stat -c %s "$out")
  truncate -s $(( hdr + data )) "$out"
  echo "$hdr"
}

# Скільки байтів уже записав dd (позиція дескриптора 1)
_cdar_written() {
  local pid
  pid="$(pgrep -P "$1" -x dd | head -n1)"
  [[ -n "$pid" ]] && sed -n 's/^pos:[[:space:]]*//p' "/proc/$pid/fdinfo/1" 2>/dev/null || echo 0
}

_cdar_kill_tree() { pkill -P "$1" 2>/dev/null; kill "$1" 2>/dev/null; wait "$1" 2>/dev/null; }

# Чи є ще диск у приводі (udev)
_cdar_disc_present() {
  udevadm info --query=property --name="$CDAR_DEVICE" 2>/dev/null | grep -q '^ID_CDROM_MEDIA_TRACK_COUNT_AUDIO=[1-9]'
}

# Номер треку, який зараз грає програвач (через MPRIS), якщо це один із наших файлів.
# Шукаємо серед усіх MPRIS-програвачів: за адресою файлу (ім'я починається з «NN - »,
# файл у нашому кеші або в порталі документів Flatpak), а якщо адреси немає — за назвою.
_cdar_mpris_track() {
  command -v gdbus >/dev/null 2>&1 && command -v busctl >/dev/null 2>&1 || return 1
  local n meta url title path base i
  CDAR_MPRIS_NAME=""; CDAR_MPRIS_TRACKID=""
  while read -r n; do
    meta="$(timeout 2 gdbus call --session --dest "$n" --object-path /org/mpris/MediaPlayer2 \
      --method org.freedesktop.DBus.Properties.Get org.mpris.MediaPlayer2.Player Metadata 2>/dev/null)" || continue
    url="$(grep -o "'xesam:url': <'[^']*'>" <<< "$meta" | sed "s/^'xesam:url': <'//; s/'>$//")"
    if [[ "$url" == file://* ]]; then
      path="$(printf '%b' "$(sed 's/%\([0-9A-Fa-f][0-9A-Fa-f]\)/\\x\1/g' <<< "${url#file://}")")"
      base="$(basename "$path")"
      if [[ "$base" =~ ^([0-9]{2})\ -\ .*\.wav$ ]] \
         && [[ "$path" == *"/disc-${CDAR_DISC_ID}/"* || "$path" == /run/user/*/doc/* ]]; then
        CDAR_MPRIS_NAME="$n"; _cdar_mpris_trackid "$meta"
        echo "$((10#${BASH_REMATCH[1]}))"; return 0
      fi
    fi
    title="$(grep -o "'xesam:title': <'[^']*'>" <<< "$meta" | sed "s/^'xesam:title': <'//; s/'>$//")"
    if [[ -n "$title" ]]; then
      for i in "${!CDAR_TITLES[@]}"; do
        if [[ "$title" == "${CDAR_TITLES[i]}" || "$title" == *" - ${CDAR_TITLES[i]}" ]]; then
          CDAR_MPRIS_NAME="$n"; _cdar_mpris_trackid "$meta"
          echo "$((i + 1))"; return 0
        fi
      done
    fi
  done < <(busctl --user list --no-legend 2>/dev/null | awk '{print $1}' \
             | grep '^org\.mpris\.MediaPlayer2\.' | grep -v playerctld)
  return 1
}

_cdar_mpris_trackid() {
  CDAR_MPRIS_TRACKID="$(grep -o "'mpris:trackid': <objectpath '[^']*'>" <<< "$1" | sed "s/.*objectpath '//; s/'>$//")"
}

# Виклик методу MPRIS у програвача, знайденого _cdar_mpris_track
_cdar_mpris_call() {
  [[ -n "${CDAR_MPRIS_NAME:-}" ]] || return 1
  timeout 3 gdbus call --session --dest "$CDAR_MPRIS_NAME" --object-path /org/mpris/MediaPlayer2 \
    --method "org.mpris.MediaPlayer2.Player.$1" "${@:2}" >/dev/null 2>&1
}

# Після перемикання на ще не скопійований трек: програвач на паузі, поки не скопійовано
# початок треку; тоді — на початок треку (програвач скидає буфер із тишею) і відтворення.
#   CDAR_RESUME=seek     — перемотати на початок (типово; Elisa)
#   CDAR_RESUME=restart  — Stop і Play: програвач заново відкриває файл. Для програвачів
#                          з власним буфером (QMPlay2), де перемотування бере дані з буфера.
_cdar_resume_from_start() {
  if [[ "${CDAR_RESUME:-seek}" == restart ]]; then
    _cdar_mpris_call Stop; sleep 0.5; _cdar_mpris_call Play
    cdar_log "$(_ 'трек готовий — відтворюю з початку (Stop/Play)')"
    return 0
  fi
  if [[ -n "${CDAR_MPRIS_TRACKID:-}" ]]; then
    _cdar_mpris_call SetPosition "objectpath '$CDAR_MPRIS_TRACKID'" "int64 0" \
      || _cdar_mpris_call Seek "int64 -86400000000"
  else
    _cdar_mpris_call Seek "int64 -86400000000"
  fi
  _cdar_mpris_call Play
  cdar_log "$(_ 'трек готовий — відтворюю з початку')"
}

# Наступний трек для копіювання: спершу той, що грає (якщо ще не готовий), далі —
# наступні за ним по порядку, а пропущені на початку — наприкінці.
_cdar_next_track() {
  local cur="${1:-1}" i t
  [[ "$cur" =~ ^[0-9]+$ ]] && ((cur >= 1 && cur <= CDAR_TRACKS)) || cur=1
  for ((i = 0; i < CDAR_TRACKS; i++)); do
    t=$(( (cur - 1 + i) % CDAR_TRACKS + 1 ))
    [[ -n "${CDAR_TODO[$t]:-}" ]] && { echo "$t"; return 0; }
  done
  return 1
}

# _cdar_rip_into <трек> <файл> <довжина заголовка> [функція, коли є кілька секунд звуку]
# Пише звук у заздалегідь створений файл. Повертає:
#   0 — готово; 1 — помилка читання; 2 — програвач закрито (без бібліотеки — стоп);
#   3 — у програвачі перемкнули на інший ще не скопійований трек; 4 — диск вийнято.
_cdar_rip_into() {
  local t="$1" out="$2" hdr="$3" on_ready="${4:-}" ready=0 n=0 p k
  ( set -o pipefail
    "$CDAR_RIPPER" -q -Z -r -d "$CDAR_DEVICE" "$t" - 2>/dev/null \
      | dd of="$out" conv=notrunc seek="${hdr}B" bs=64K status=none ) &
  p=$!
  while kill -0 "$p" 2>/dev/null; do
    if [[ -n "$on_ready" ]] && ((!ready)) && (( $(_cdar_written "$p") >= hdr + ${CDAR_PREBUFFER:-1048576} )); then
      "$on_ready"; ready=1
    fi
    if (( ++n % 4 == 0 )); then
      if ! _cdar_disc_present; then _cdar_kill_tree "$p"; return 4; fi
      if _cdar_player_closed && [[ -z "${CDAR_KEEP_RIPPING:-}" ]]; then _cdar_kill_tree "$p"; return 2; fi
    fi
    if (( n % 4 == 2 )) && [[ "$CDAR_MODE" == play ]] && ((CDAR_OPENED)); then
      _cdar_mpris_track > "$CDAR_TMP_K" 2>/dev/null; k="$(cat "$CDAR_TMP_K")"
      if [[ -n "$k" && "$k" != "$t" && -n "${CDAR_TODO[$k]:-}" ]]; then
        _cdar_mpris_call Pause
        cdar_log "$(_ 'у програвачі трек %s — пауза, копіюю його першим' "$k")"
        CDAR_SWITCHED=1
        _cdar_kill_tree "$p"; return 3
      fi
    fi
    sleep 0.25
  done
  if ! wait "$p"; then _cdar_disc_present || return 4; return 1; fi
  [[ -n "$on_ready" ]] && ((!ready)) && "$on_ready"
  return 0
}

_cdar_stopped() {
  cdar_notify "$(_ 'Аудіо-CD → %s' "$CDAR_NAME")" "$(_ 'Програвач закрито — копіювання зупинено.')"
  cdar_log "$(_ 'програвач закрито, копіювання зупинено')"
}

_cdar_ejected() {
  cdar_notify "$(_ 'Аудіо-CD')" "$(_ 'Диск вийнято — копіювання призупинено. Вставте диск знову, щоб продовжити.')"
  cdar_log "$(_ 'диск вийнято, копіювання призупинено')"
}

_cdar_fail() {
  cdar_notify "$(_ 'Не вдалося скопіювати трек %s' "$1")" "$(_ 'Диск може бути подряпаним або брудним.')"
  cdar_log "$(_ 'помилка читання треку %s' "$1")"
}

# cdar_rip_and_play <функція-відкрити> [play|rip]
#
# Функція-відкрити отримує ВСІ треки альбому одним списком файлів. Файли
# створюються одразу повного розміру (WAV з тегами); програвач відкриває їх,
# щойно є кілька секунд першого треку, а треки копіюються в 5× швидше, ніж
# грають. Якщо в програвачі перемкнути на ще не скопійований трек, він
# копіюється першим. З бібліотекою кожен трек ще й кодується в теку музики.
#
# Повторне вставлення диска безпечне: скопійовані треки позначені (.done-N у кеші,
# готові файли в бібліотеці) і повторно не копіюються; обірваний трек копіюється наново.
cdar_rip_and_play() {
  local open_fn="$1" dir base t fmt rc lib="" stem
  CDAR_MODE="${2:-play}"
  if ! CDAR_RIPPER="$(cdar_ripper)"; then
    cdar_notify "$(_ 'Не можу скопіювати треки')" "$(_ 'Встановіть cd-paranoia (пакет libcdio-paranoia) або cdparanoia.')"
    cdar_log "$(_ 'не знайдено cd-paranoia/cdparanoia')"; return 1
  fi
  fmt="$(_cdar_format)"
  base="${XDG_CACHE_HOME:-$HOME/.cache}/cd-auto-runner"
  [[ "$CDAR_MODE" == rip ]] && CDAR_LIBRARY=yes

  if [[ "$CDAR_DRY_RUN" == 1 ]]; then
    local root; root="$(_cdar_library_root)"
    local -a show=()
    for ((t = 1; t <= CDAR_TRACKS; t++)); do
      echo "# $CDAR_RIPPER -q -Z -r -d $CDAR_DEVICE $t → $base/disc-ID/$(printf '%02d' "$t") - <$(_ 'Виконавець')> - <$(_ 'Назва')>.wav"
      [[ "${CDAR_LIBRARY:-yes}" == yes ]] && echo "#   → $root/<$(_ 'Виконавець')>/<$(_ 'Альбом')>/$(printf '%02d' "$t") - <$(_ 'Назва')>.$fmt"
      show+=("$base/disc-ID/$(printf '%02d' "$t").wav")
    done
    [[ "$CDAR_MODE" == play ]] && "$open_fn" "${show[@]}"
    return 0
  fi

  _cdar_read_toc || { cdar_notify "$(_ 'Не вдалося прочитати диск')" "$CDAR_DEVICE"; return 1; }
  dir="$base/disc-$CDAR_DISC_ID"
  mkdir -p "$dir"
  local old; for old in "$base"/disc-*; do [[ "$old" != "$dir" ]] && rm -rf -- "$old"; done

  # Попередній запуск для цього диска (напр. щойно вийняли й знову вставили диск)
  # може ще завершуватися — чекаємо, а не здаємося одразу
  exec 8> "$dir/.lock"
  if ! flock -w 20 8; then cdar_log "$(_ 'цей диск уже копіюється')"; return 0; fi

  _cdar_metadata
  if [[ "${CDAR_LIBRARY:-yes}" == yes ]]; then
    lib="$(_cdar_library_root)/$(_cdar_safe "$CDAR_ALBUM_ARTIST")/$(_cdar_safe "$CDAR_ALBUM")"
    mkdir -p "$lib" || { cdar_log "$(_ 'не можу створити %s' "$lib")"; lib=""; }
  fi
  # Для «cd-auto-runner tag»: як і куди копіюється цей диск
  printf '%s\n' "${CDAR_DESKTOP_ID:-rip}" > "$dir/.mode"
  printf '%s\n' "$lib" > "$dir/.library"
  [[ -n "$lib" && "$CDAR_META_SOURCE" != none ]] && _cdar_write_marker "$lib"
  [[ "$CDAR_META_SOURCE" == none ]] && _cdar_offer_tagging "$dir/.asked"
  if [[ -n "$lib" ]]; then
    CDAR_KEEP_RIPPING=1       # як у WMP: альбом докопіюється, навіть якщо програвач закрито
  fi
  # Обкладинка: у теці бібліотеки та поруч із тимчасовими файлами в кеші —
  # Elisa та інші програвачі беруть cover.jpg з теки, де лежить трек
  CDAR_COVER=""
  if [[ -n "$lib" ]]; then _cdar_cover "$lib"; [[ -s "$lib/cover.jpg" ]] && CDAR_COVER="$lib/cover.jpg"; fi
  if [[ -z "$CDAR_COVER" ]]; then _cdar_cover "$dir"; [[ -s "$dir/cover.jpg" ]] && CDAR_COVER="$dir/cover.jpg"; fi
  [[ -n "$CDAR_COVER" && ! -s "$dir/cover.jpg" ]] && cp -f -- "$CDAR_COVER" "$dir/cover.jpg"

  # Стан треків: що вже є, що копіювати (CDAR_TODO), що лише закодувати (encode)
  local -a wav final play hdr encode=()
  declare -gA CDAR_TODO=()
  for ((t = 1; t <= CDAR_TRACKS; t++)); do
    stem="$(_cdar_track_stem "$t")"
    # Ім'я тимчасового WAV фіксується при першому створенні: якщо назви потім змінять
    # (cd-auto-runner tag), файли в списку програвача лишаються на місці
    if [[ -s "$dir/.name-$t" ]]; then wav[t]="$dir/$(cat "$dir/.name-$t")"
    else
      wav[t]="$dir/$(printf '%02d' "$t") - $(_cdar_safe "${CDAR_ARTISTS[t-1]}") - $(_cdar_safe "${CDAR_TITLES[t-1]}").wav"
      basename "${wav[t]}" > "$dir/.name-$t"
    fi
    final[t]="${lib:+$lib/$stem.$fmt}"
    if [[ -n "$lib" && -s "${final[t]}" ]]; then
      play[t]="${final[t]}"                         # уже в бібліотеці
    elif [[ -f "$dir/.done-$t" && -s "${wav[t]}" ]]; then
      play[t]="${wav[t]}"                           # уже в кеші
      [[ -n "$lib" ]] && encode+=("$t")             # лишилося закодувати
    else
      rm -f -- "$dir/.done-$t"
      hdr[t]="$(_cdar_wav_prealloc "${wav[t]}" "$t")"
      play[t]="${wav[t]}"; CDAR_TODO[$t]=1
    fi
  done

  CDAR_OPENED=0
  _cdar_open_all() {
    ((CDAR_OPENED)) && return 0
    CDAR_OPENED=1
    [[ "$CDAR_MODE" == play ]] || return 0
    # Диск вийняли й вставили знову, а програвач досі грає цей альбом — не дублюємо список
    if _cdar_player_alive && _cdar_mpris_track >/dev/null; then
      CDAR_SEEN_ALIVE=1; cdar_log "$(_ 'альбом уже відкрито в програвачі — продовжую копіювання')"
      return 0
    fi
    "$open_fn" "${play[@]}"
  }
  # Якщо перший трек уже готовий — відкриваємо одразу; інакше після кількох секунд копіювання
  [[ -n "${CDAR_TODO[1]:-}" ]] || _cdar_open_all

  local total=${#CDAR_TODO[@]} cnt=0 cur=1 k_switch
  CDAR_SWITCHED=0
  CDAR_TMP_K="$dir/.mpris"
  while t="$(_cdar_next_track "$cur")"; do
    cnt=$((cnt + 1))
    local msg; msg="$(_ 'Копіюю трек %s (лишилось %s з %s)…' "$t" "$((total - cnt + 1))" "$total")"
    if [[ -n "$lib" ]]; then cdar_notify "$CDAR_ALBUM_ARTIST — $CDAR_ALBUM" "$msg"
    else cdar_notify "$(_ 'Аудіо-CD → %s' "$CDAR_NAME")" "$msg"; fi
    if ((!CDAR_OPENED)); then _cdar_rip_into "$t" "${wav[t]}" "${hdr[t]}" _cdar_open_all; rc=$?
    elif ((CDAR_SWITCHED)); then CDAR_SWITCHED=0; _cdar_rip_into "$t" "${wav[t]}" "${hdr[t]}" _cdar_resume_from_start; rc=$?
    else _cdar_rip_into "$t" "${wav[t]}" "${hdr[t]}"; rc=$?; fi
    case "$rc" in
      0) touch "$dir/.done-$t"; unset "CDAR_TODO[$t]"; cur=$((t + 1))
         if [[ -n "$lib" ]]; then
           _cdar_encode "${wav[t]}" "${final[t]}" "$fmt" "$t" keep || cdar_log "$(_ 'не вдалося закодувати трек %s' "$t")"
         fi ;;
      2) _cdar_stopped; return 0 ;;
      3) cnt=$((cnt - 1)); k_switch="$(cat "$CDAR_TMP_K" 2>/dev/null)"; cur="${k_switch:-$t}" ;;
      4) _cdar_ejected; return 0 ;;
      *) _cdar_fail "$t"; return 1 ;;
    esac
  done

  for t in "${encode[@]}"; do
    _cdar_encode "${wav[t]}" "${final[t]}" "$fmt" "$t" keep || cdar_log "$(_ 'не вдалося закодувати трек %s' "$t")"
  done
  _cdar_open_all
  wait 2>/dev/null
  if [[ -n "$lib" ]]; then
    cdar_notify "$CDAR_ALBUM_ARTIST — $CDAR_ALBUM" "$(_ 'Альбом скопійовано: %s' "$lib")"
    cdar_log "$(_ 'альбом у бібліотеці: %s' "$lib")"
  else
    cdar_notify "$(_ 'Аудіо-CD → %s' "$CDAR_NAME")" "$(_ 'Диск скопійовано.')"
  fi
}
