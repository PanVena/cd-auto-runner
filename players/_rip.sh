#!/usr/bin/env bash
# Копіювання диска в бібліотеку музики без відтворення (cd-auto-runner rip).
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Pan Vena
# shellcheck source=_lib.sh
source "$CDAR_LIB"

noop() { :; }
cdar_rip_and_play noop rip
