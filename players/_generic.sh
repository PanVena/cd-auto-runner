#!/usr/bin/env bash
# Типовий адаптер для програм без власного: передає адресу cdda://ПРИСТРІЙ.
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

if cdar_files; then cdar_launch -- "${CDAR_FILE_LIST[@]}"; exit; fi
cdar_launch --urls -- "cdda://$CDAR_DEVICE"
