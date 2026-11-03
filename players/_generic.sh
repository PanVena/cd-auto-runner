#!/usr/bin/env bash
# Типовий адаптер для програм без власного: передає адресу cdda://ПРИСТРІЙ.
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

cdar_launch --urls -- "cdda://$CDAR_DEVICE"
