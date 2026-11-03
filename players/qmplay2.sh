#!/usr/bin/env bash
# Адаптер QMPlay2: його модуль AudioCD у Flatpak не відтворює диск, тому треки
# копіюються у WAV. QMPlay2 приймає одну адресу за раз: перший трек — --open,
# решта — --enqueue (одразу, весь альбом).
# cdar-desktop-ids: io.github.zaps166.QMPlay2.desktop QMPlay2.desktop
# cdar-note: копіює треки
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

open_album() {
  cdar_launch --opt --open -- "$1"; shift
  # Чекаємо, поки QMPlay2 запуститься, і додаємо решту строго по черзі:
  # паралельні --enqueue перемішують порядок, а ранній ще й запускає власну копію
  cdar_wait_player 30 && [[ "$CDAR_DRY_RUN" == 1 ]] || sleep 1.5
  local f
  for f in "$@"; do
    # QMPlay2 закрили — не запускаємо його знову через --enqueue
    [[ "$CDAR_DRY_RUN" == 1 ]] || _cdar_player_alive || break
    cdar_launch --wait --opt --enqueue -- "$f"
  done
}

# QMPlay2 тримає власний буфер: перемотування на початок бере тишу з нього,
# тому після перемикання на нескопійований трек робимо Stop/Play (файл читається заново)
CDAR_RESUME=restart
cdar_rip_and_play open_album
