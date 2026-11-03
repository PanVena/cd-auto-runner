#!/usr/bin/env bash
# Інсталятор CD Auto Runner (для поточного користувача, без root).
# Installer for CD Auto Runner (current user, no root).
#
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
set -euo pipefail

APP="cd-auto-runner"
SRC="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

BIN_DIR="$HOME/.local/bin"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
UNIT_DIR="$CONF_DIR/systemd/user"
APPS_DIR="$DATA_DIR/applications"
AUTOSTART_DIR="$CONF_DIR/autostart"
BIN="$BIN_DIR/$APP"
CFG="$CONF_DIR/$APP/config"

ASSUME_YES=0
SKIP_DEPS=0
CHOOSE="auto"     # auto | yes | no
MODE="auto"       # auto | systemd | autostart
UNINSTALL=0
PURGE=0
LANG_ARG=""

# shellcheck source=i18n.sh
source "$SRC/i18n.sh"
CDAR_UI_LANG="$(sed -n 's/^UI_LANG=//p' "$CFG" 2>/dev/null | tail -n1 || true)"
[[ "$CDAR_UI_LANG" == en || "$CDAR_UI_LANG" == uk ]] || CDAR_UI_LANG="$(cdar_detect_lang)"

# --------------------------------------------------------------------------
c_ok=$'\e[32m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_b=$'\e[1m'; c_0=$'\e[0m'
[[ -t 1 ]] || { c_ok=""; c_warn=""; c_err=""; c_b=""; c_0=""; }
step() { printf '\n%s==>%s %s%s%s\n' "$c_ok" "$c_0" "$c_b" "$*" "$c_0"; }
ok()   { printf '  %s✔%s %s\n' "$c_ok" "$c_0" "$*"; }
warn() { printf '  %s!%s %s\n' "$c_warn" "$c_0" "$*"; }
fail() { printf '%s%s%s %s\n' "$c_err" "$(_ 'Помилка:')" "$c_0" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

ask() {  # ask "питання" [default y|n]
  local def="${2:-y}" ans hint
  ((ASSUME_YES)) && return 0
  [[ -t 0 ]] || { [[ "$def" == y ]]; return; }
  if [[ "$CDAR_UI_LANG" == en ]]; then hint="$([[ $def == y ]] && echo '[Y/n]' || echo '[y/N]')"
  else hint="$([[ $def == y ]] && echo '[Т/н]' || echo '[т/Н]')"; fi
  read -rp "  $1 $hint " ans
  [[ -z "$ans" ]] && { [[ "$def" == y ]]; return; }
  [[ "$ans" =~ ^[тТyYтак] ]]
}

usage() {
  _ 'Інсталятор %s

Використання: ./install.sh [параметри]

  -y, --yes          відповідати «так» на всі запитання
      --lang uk|en   мова інтерфейсу (інакше — запитати)
      --no-deps      не пропонувати встановити залежності
      --choose       завжди запитати, який програвач використовувати
      --no-choose    не запитувати програвач (залишити поточний)
      --systemd      запуск через службу systemd --user (за замовч., якщо доступно)
      --autostart    запуск через XDG autostart (~/.config/autostart)
  -u, --uninstall    видалити %s
      --purge        разом з --uninstall: видалити й налаштування
  -h, --help         ця довідка
' "$APP" "$APP"
}

while (($#)); do
  case "$1" in
    -y|--yes) ASSUME_YES=1 ;;
    --lang) LANG_ARG="${2:-}"; shift ;;
    --lang=*) LANG_ARG="${1#*=}" ;;
    --no-deps) SKIP_DEPS=1 ;;
    --choose) CHOOSE=yes ;;
    --no-choose) CHOOSE=no ;;
    --systemd) MODE=systemd ;;
    --autostart) MODE=autostart ;;
    -u|--uninstall) UNINSTALL=1 ;;
    --purge) PURGE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; fail "$(_ 'невідомий параметр: %s' "$1")" ;;
  esac
  shift
done

((EUID != 0)) || fail "$(_ 'запускайте інсталятор від звичайного користувача, а не root (sudo попросимо, лише якщо треба поставити пакети).')"

if ((UNINSTALL)); then
  args=(); ((PURGE)) && args+=(--purge); ((ASSUME_YES)) && args+=(--yes)
  exec bash "$SRC/uninstall.sh" "${args[@]}"
fi

for f in "$APP" i18n.sh gui/gui.py systemd/$APP.service desktop/$APP.desktop players/_lib.sh players/_generic.sh; do
  [[ -f "$SRC/$f" ]] || fail "$(_ 'не знайдено файл %s — запускайте install.sh з теки проєкту.' "$SRC/$f")"
done

# --------------------------------------------------------------------------
# Мова / Language — найперше, щоб далі все було обраною мовою
if [[ -n "$LANG_ARG" ]]; then
  [[ "$LANG_ARG" == en || "$LANG_ARG" == uk ]] || fail "unknown language / невідома мова: $LANG_ARG (uk | en)"
  CDAR_UI_LANG="$LANG_ARG"
elif ((!ASSUME_YES)) && [[ -t 0 ]]; then
  printf '\n%s==>%s %sLanguage / Мова%s\n' "$c_ok" "$c_0" "$c_b" "$c_0"
  echo "  1) English$([[ $CDAR_UI_LANG == en ]] && echo '  *')"
  echo "  2) Українська$([[ $CDAR_UI_LANG == uk ]] && echo '  *')"
  read -rp "  [1-2, Enter — $([[ $CDAR_UI_LANG == en ]] && echo English || echo Українська)]: " n || n=""
  case "$n" in 1) CDAR_UI_LANG=en ;; 2) CDAR_UI_LANG=uk ;; esac
fi
export CDAR_UI_LANG
CDAR_UI_LANG="$CDAR_UI_LANG" bash "$SRC/$APP" lang "$CDAR_UI_LANG" >/dev/null
ok "$(_ 'Мова інтерфейсу: %s' "$([[ $CDAR_UI_LANG == en ]] && echo English || echo Українська)")"

# --------------------------------------------------------------------------
step "$(_ 'Перевірка системи')"
[[ "$(uname -s)" == Linux ]] || fail "$(_ 'підтримується лише Linux.')"
have udevadm || fail "$(_ 'немає udevadm (systemd-udev). Без нього відстежувати диски неможливо.')"
ok "$(_ 'udevadm: є')"

if [[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* ]]; then
  ok "$(_ 'Середовище: KDE Plasma %s' "$(plasmashell --version 2>/dev/null | awk '{print $2}')")"
else
  warn "$(_ 'Середовище: %s. Автозапуск працюватиме, але пункти в меню «Диски і пристрої» є лише в KDE.' "${XDG_CURRENT_DESKTOP:-?}")"
fi

drives=$(ls /dev/sr* 2>/dev/null | tr '\n' ' ' || true)
if [[ -n "$drives" ]]; then ok "$(_ 'CD/DVD-приводи: %s' "$drives")"
else warn "$(_ 'CD/DVD-привід зараз не знайдено (USB-привід можна підключити пізніше).')"
fi

# Чи може користувач читати привід
if [[ -n "$drives" ]]; then
  d=${drives%% *}
  if [[ -r "$d" ]]; then ok "$(_ 'Доступ на читання %s: є' "$d")"
  else
    g="$(stat -c %G "$d")"
    warn "$(_ 'Немає прав на читання %s. Додайте себе до групи «%s»: sudo usermod -aG %s %s (і перезайдіть).' "$d" "$g" "$g" "$USER")"
  fi
fi

# --------------------------------------------------------------------------
pkg_install() {  # pkg_install <пакет-dnf> <пакет-apt> <пакет-pacman> <пакет-zypper>
  if have dnf; then sudo dnf install -y "$1"
  elif have apt-get; then sudo apt-get install -y "$2"
  elif have pacman; then sudo pacman -S --needed --noconfirm "$3"
  elif have zypper; then sudo zypper --non-interactive install "$4"
  else return 1
  fi
}

step "$(_ 'Залежності')"
missing_req=()
have systemctl || [[ "$MODE" == autostart ]] || missing_req+=(systemd)
have flock || missing_req+=(util-linux)
((${#missing_req[@]} == 0)) || fail "$(_ "відсутні обов'язкові програми: %s" "${missing_req[*]}")"
ok "$(_ 'systemctl, flock: є')"

# mpv — рушій вбудованого програвача: ставимо без запитання (окремий процес, не
# входить до складу програми; пакет і його оновлення дає дистрибутив)
if have mpv; then ok "$(_ 'mpv: є')"
elif ((SKIP_DEPS)); then warn "$(_ 'mpv не встановлено (--no-deps) — вбудований програвач буде недоступний.')"
else
  warn "$(_ 'mpv не встановлено — він потрібен для вбудованого програвача. Встановлюю (потрібен sudo)…')"
  if pkg_install mpv mpv mpv mpv && have mpv; then ok "$(_ 'mpv встановлено')"
  else warn "$(_ 'не вдалося встановити mpv — вбудований програвач буде недоступний. Встановіть пакет mpv вручну.')"
  fi
fi

# Необов'язкові, але бажані
declare -A OPT_DESC=(
  [kdialog]="$(_ 'графічне вікно вибору програвача')"
  [notify-send]="$(_ 'сповіщення при вставлянні диска')"
  [cd-paranoia]="$(_ 'копіювання треків для Elisa, QMPlay2, Audacious і бібліотеки музики')"
  [ffmpeg]="$(_ 'кодування треків у FLAC/Opus/MP3 для бібліотеки музики')"
  [pyside6]="$(_ 'вікно програми, вбудований програвач і форма для введення назв треків')"
)
declare -A OPT_PKG=(  # dnf apt pacman zypper
  [kdialog]="kdialog kdialog kdialog kdialog"
  [notify-send]="libnotify libnotify-bin libnotify libnotify-tools"
  [cd-paranoia]="libcdio-paranoia cdparanoia cdparanoia cdparanoia"
  [ffmpeg]="ffmpeg-free ffmpeg ffmpeg ffmpeg"
  [pyside6]="python3-pyside6 python3-pyside6.qtwidgets pyside6 python3-pyside6"
)
has_tool() {
  case "$1" in
    cd-paranoia) have cd-paranoia || have cdparanoia ;;
    pyside6) python3 -c 'import PySide6.QtWidgets' 2>/dev/null ;;
    *) have "$1" ;;
  esac
}
for tool in kdialog notify-send cd-paranoia ffmpeg pyside6; do
  if has_tool "$tool"; then ok "$(_ '%s: є' "$tool")"; continue; fi
  warn "$(_ '%s не встановлено — %s' "$tool" "${OPT_DESC[$tool]}")"
  ((SKIP_DEPS)) && continue
  if ask "$(_ 'Встановити %s (потрібен sudo)?' "$tool")" y; then
    # shellcheck disable=SC2086
    if pkg_install ${OPT_PKG[$tool]} && has_tool "$tool"; then ok "$(_ '%s встановлено' "$tool")"
    else warn "$(_ 'не вдалося встановити %s — продовжую без нього' "$tool")"
    fi
  fi
done

# Аудіо-CD програвачі
found_rc=0
mapfile -t found < <(bash "$SRC/$APP" list 2>/dev/null) || true
bash "$SRC/$APP" list >/dev/null 2>&1 || found_rc=$?
if ((found_rc == 0 && ${#found[@]})); then
  ok "$(_ 'Програвачі, знайдені в системі:')"
  printf '%s\n' "${found[@]}" | cut -f2 | sed 's/^/      • /'
else
  warn "$(_ 'У системі не знайдено жодного аудіопрогравача. Можна вказати власну команду або встановити VLC.')"
  if ((!SKIP_DEPS)) && ask "$(_ 'Встановити VLC?')" y; then
    if have flatpak && ask "$(_ 'Через Flatpak (Flathub)? «ні» — з репозиторію дистрибутиву')" y; then
      flatpak install -y --user flathub org.videolan.VLC || warn "$(_ 'не вдалося встановити VLC')"
    else
      pkg_install vlc vlc vlc vlc || warn "$(_ 'не вдалося встановити VLC')"
    fi
  fi
fi

# --------------------------------------------------------------------------
step "$(_ 'Копіювання файлів')"
subst() { sed "s|@BIN@|$BIN|g" "$1" > "$2"; }

# Зупиняємо стару версію, якщо оновлюємось
if have systemctl && systemctl --user is-active --quiet "$APP.service" 2>/dev/null; then
  systemctl --user stop "$APP.service" || true
fi
pkill -u "$USER" -f "$APP watch" 2>/dev/null || true

install -Dm755 "$SRC/$APP" "$BIN";                          ok "$BIN"
install -Dm644 "$SRC/i18n.sh" "$DATA_DIR/$APP/i18n.sh";     ok "$DATA_DIR/$APP/i18n.sh"
install -Dm755 "$SRC/gui/gui.py" "$DATA_DIR/$APP/gui.py";   ok "$DATA_DIR/$APP/gui.py"
PLAYERS_DIR="$DATA_DIR/$APP/players"
rm -rf "$PLAYERS_DIR"; mkdir -p "$PLAYERS_DIR"
install -m644 "$SRC/players/_lib.sh" "$PLAYERS_DIR/"
for f in "$SRC"/players/*.sh "$SRC"/players/*.py; do [[ "$(basename "$f")" == _lib.sh ]] || install -m755 "$f" "$PLAYERS_DIR/"; done
ok "$(_ '%s (адаптерів програвачів: %s)' "$PLAYERS_DIR" "$(ls "$SRC"/players/[!_]*.sh | wc -l)")"
mkdir -p "$APPS_DIR"
subst "$SRC/desktop/$APP.desktop" "$APPS_DIR/$APP.desktop"; ok "$(_ '%s (меню програм)' "$APPS_DIR/$APP.desktop")"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$(_ '%s немає в PATH. Додайте до ~/.bashrc: %s' "$BIN_DIR" 'export PATH="$HOME/.local/bin:$PATH"')" ;;
esac

# --------------------------------------------------------------------------
step "$(_ 'Вибір програвача')"
if [[ "$CHOOSE" == auto ]]; then
  if grep -q '^PLAYER_ID=.' "$CFG" 2>/dev/null; then
    ok "$(_ 'Поточний вибір: %s' "$(grep '^PLAYER_NAME=' "$CFG" | cut -d= -f2-)")"
    if ask "$(_ 'Обрати інший програвач?')" n; then CHOOSE=yes; else CHOOSE=no; fi
  else
    CHOOSE=yes
  fi
fi
if [[ "$CHOOSE" == yes ]]; then
  if [[ -t 0 ]] || have kdialog; then
    "$BIN" choose || warn "$(_ 'програвач не обрано — зробіть це пізніше: %s choose' "$APP")"
  else
    warn "$(_ 'немає терміналу і kdialog — оберіть програвач пізніше: %s choose' "$APP")"
  fi
fi

# --------------------------------------------------------------------------
step "$(_ 'Меню «Диски і пристрої»')"
"$BIN" solid | sed 's/^/  ✔ /'

# --------------------------------------------------------------------------
step "$(_ 'Автозапуск служби')"
if [[ "$MODE" == auto ]]; then
  if have systemctl && systemctl --user show-environment >/dev/null 2>&1; then MODE=systemd; else MODE=autostart; fi
fi

rm -f "$AUTOSTART_DIR/$APP.desktop"
if [[ "$MODE" == systemd ]]; then
  mkdir -p "$UNIT_DIR"
  subst "$SRC/systemd/$APP.service" "$UNIT_DIR/$APP.service"
  systemctl --user daemon-reload
  systemctl --user enable "$APP.service" >/dev/null 2>&1
  systemctl --user restart "$APP.service"
  sleep 1
  if systemctl --user is-active --quiet "$APP.service"; then
    ok "$(_ 'Служба systemd --user увімкнена та працює (%s)' "$APP.service")"
  else
    warn "$(_ 'Служба не запустилась. Журнал: %s' "journalctl --user -u $APP -e")"
  fi
  if ! systemctl --user is-active --quiet graphical-session.target; then
    warn "$(_ 'graphical-session.target неактивний — служба запущена зараз, але після входу може не стартувати. Тоді перевстановіть з --autostart.')"
  fi
else
  if [[ -f "$UNIT_DIR/$APP.service" ]] && have systemctl; then
    systemctl --user disable --now "$APP.service" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$APP.service"; systemctl --user daemon-reload 2>/dev/null || true
  fi
  mkdir -p "$AUTOSTART_DIR"
  cat > "$AUTOSTART_DIR/$APP.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=CD Auto Runner (watcher)
Exec=$BIN watch
Icon=media-optical-audio
NoDisplay=true
X-KDE-autostart-phase=2
X-GNOME-Autostart-enabled=true
EOF
  setsid -f "$BIN" watch >/dev/null 2>&1 < /dev/null
  ok "$(_ 'XDG autostart: %s (вже запущено)' "$AUTOSTART_DIR/$APP.desktop")"
fi

# Оновлюємо кеш меню KDE
for k in kbuildsycoca6 kbuildsycoca5; do have $k && { $k >/dev/null 2>&1 || true; break; }; done || true
have update-desktop-database && update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true

# --------------------------------------------------------------------------
step "$(_ 'Готово!')"
"$BIN" status | sed 's/^/  /'
echo
_ '  Вставте аудіо-CD — обраний програвач запуститься автоматично.

  Змінити програвач:   %s choose   (або «CD Auto Runner» у меню програм,
                       або «Обрати програвач…» у меню «Диски і пристрої»)
  Інший програвач раз: %s play --player <id>   (id — з «%s list»)
  Скопіювати диск:     %s rip
  Мова:                %s lang
  Стан:                %s status
  Журнал:              journalctl --user -u %s -f
  Видалити:            ./uninstall.sh   (або ./install.sh --uninstall)
' "$APP" "$APP" "$APP" "$APP" "$APP" "$APP" "$APP"
