#!/usr/bin/env bash
# Видалення CD Auto Runner. / Uninstall CD Auto Runner.
#
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
set -uo pipefail

APP="cd-auto-runner"
SRC="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
PURGE=0; ASSUME_YES=0

for CDAR_I18N in "$SRC/i18n.sh" "$DATA_DIR/$APP/i18n.sh" ""; do
  [[ -z "$CDAR_I18N" || -f "$CDAR_I18N" ]] && break
done
if [[ -n "$CDAR_I18N" ]]; then
  # shellcheck source=i18n.sh
  source "$CDAR_I18N"
  CDAR_UI_LANG="$(sed -n 's/^UI_LANG=//p' "$CONF_DIR/$APP/config" 2>/dev/null | tail -n1)"
  [[ "$CDAR_UI_LANG" == en || "$CDAR_UI_LANG" == uk ]] || CDAR_UI_LANG="$(cdar_detect_lang)"
else
  _() { local s="$1"; shift; if (($#)); then printf -- "$s" "$@"; else printf '%s' "$s"; fi; }
fi

for a in "$@"; do
  case "$a" in
    --purge) PURGE=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help) _ 'Використання: ./uninstall.sh [--purge] [-y]   (--purge — видалити й налаштування)'; echo; exit 0 ;;
    *) _ 'Невідомий параметр: %s' "$a" >&2; echo >&2; exit 2 ;;
  esac
done

_ '==> Видалення %s' "$APP"; echo
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now "$APP.service" >/dev/null 2>&1 || true
  # фонове копіювання треків
  while read -r u _x; do [[ -n "$u" ]] && systemctl --user stop "$u" 2>/dev/null; done \
    < <(systemctl --user list-units "$APP-play-*" --no-legend --plain 2>/dev/null)
fi
pkill -u "$USER" -f "$APP watch" 2>/dev/null || true

# Повертаємо GNOME реакцію на аудіо-CD, поки програма ще на місці
[[ -x "$HOME/.local/bin/$APP" ]] && "$HOME/.local/bin/$APP" gnome-autorun off 2>/dev/null | sed 's/^/  /'

for f in \
  "$HOME/.local/bin/$APP" \
  "$CONF_DIR/systemd/user/$APP.service" \
  "$DATA_DIR/solid/actions/$APP.desktop" \
  "$DATA_DIR/applications/$APP.desktop" \
  "$DATA_DIR/icons/hicolor/scalable/apps/$APP.svg" \
  "$DATA_DIR/icons/hicolor/symbolic/apps/$APP-heart-symbolic.svg" \
  "$DATA_DIR/icons/hicolor/symbolic/apps/$APP-heart-filled-symbolic.svg" \
  "$CONF_DIR/autostart/$APP.desktop"; do
  [[ -e "$f" ]] && rm -f "$f" && { _ '  видалено %s' "$f"; echo; }
done
for d in "$DATA_DIR/$APP" "${XDG_CACHE_HOME:-$HOME/.cache}/$APP"; do
  [[ -d "$d" ]] && rm -rf "$d" && { _ '  видалено %s' "$d"; echo; }
done
systemctl --user daemon-reload >/dev/null 2>&1 || true
for k in kbuildsycoca6 kbuildsycoca5; do command -v $k >/dev/null && { $k >/dev/null 2>&1; break; }; done
command -v update-desktop-database >/dev/null && update-desktop-database "$DATA_DIR/applications" >/dev/null 2>&1

if [[ -d "$CONF_DIR/$APP" ]]; then
  if ((PURGE)); then
    rm -rf "$CONF_DIR/$APP" && { _ '  видалено %s' "$CONF_DIR/$APP"; echo; }
  elif ((ASSUME_YES == 0)) && [[ -t 0 ]] \
       && read -rp "$(_ '  Видалити налаштування і власні адаптери (%s)? [т/Н] ' "$CONF_DIR/$APP")" a \
       && [[ "$a" =~ ^[тТyY] ]]; then
    # Назви треків, які ви вводили (discs/), лишаються — їх видаляє лише --purge
    find "$CONF_DIR/$APP" -mindepth 1 -maxdepth 1 ! -name discs -exec rm -rf {} +
    _ '  видалено налаштування; введені назви треків залишено: %s' "$CONF_DIR/$APP/discs"; echo
  else
    _ '  налаштування залишено: %s' "$CONF_DIR/$APP"; echo
  fi
fi
_ '  Скопійовані альбоми в теці «Музика» залишено.'; echo
_ 'Готово.'; echo
