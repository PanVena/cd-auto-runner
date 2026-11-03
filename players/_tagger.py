#!/usr/bin/env python3
"""Форма введення назв треків для cd-auto-runner (PySide6).

Використання: _tagger.py ФАЙЛ [ЗАГОЛОВОК] [ПОСИЛАННЯ_MUSICBRAINZ]

ФАЙЛ — шаблон у форматі cd-auto-runner (ALBUM=, ALBUM_ARTIST=, YEAR=, 01=Виконавець - Назва …).
Форма заповнюється з нього, а після «Зберегти» записує результат у той самий файл
(код виходу 0). «Скасувати» — код 1. Мова: CDAR_UI_LANG (uk | en).

Tracklist editor for cd-auto-runner. Texts are Ukrainian; EN holds the English translation.

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import os
import re
import sys

from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

LANG = os.environ.get("CDAR_UI_LANG", "uk")
EN = {
    "Назви треків": "Track titles",
    "Альбом:": "Album:",
    "Виконавець альбому:": "Album artist:",
    "Рік:": "Year:",
    "порожньо — визначиться сам (для збірки — Various Artists)":
        "empty — detected automatically (Various Artists for a compilation)",
    "Виконавець": "Artist",
    "Назва": "Title",
    "Вставити список…": "Paste tracklist…",
    "Очистити": "Clear",
    "Додати диск у MusicBrainz": "Add the disc to MusicBrainz",
    "Зберегти": "Save",
    "Скасувати": "Cancel",
    "Вставте список треків — по одному в рядку, наприклад «1. Виконавець - Назва».\n"
    "Номери на початку рядків і порожні рядки пропускаються.":
        "Paste the tracklist — one track per line, e.g. \"1. Artist - Title\".\n"
        "Leading numbers and empty lines are skipped.",
    "Для збірки (диск із журналу) вкажіть виконавця кожного треку. "
    "Якщо виконавець той самий, що й в альбому, стовпчик можна лишити порожнім.":
        "For a compilation (e.g. a magazine CD) enter the artist of every track. "
        "If it's the same as the album artist, the column can stay empty.",
}


def _(text):
    return EN.get(text, text) if LANG == "en" else text


# «Виконавець - Назва»; пробіл може бути лише з одного боку дефіса, «Jay-Z» не розбивається
SPLIT = (re.compile(r"^(.*\S)\s+-\s*(\S.*)$"), re.compile(r"^(.*\S)\s*-\s+(\S.*)$"))
LEADING_NUMBER = re.compile(r"^\s*(?:\d{1,3}\s*[.):\-–]?\s+|\d{1,3}[.)]\s*)")


def split_track(value):
    value = value.strip()
    for rx in SPLIT:
        m = rx.match(value)
        if m:
            return m.group(1), m.group(2)
    return "", value


def read_template(path):
    head, tracks = {}, {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if re.fullmatch(r"\d\d", key):
                tracks[int(key)] = split_track(value)
            else:
                head[key] = value
    return head, tracks


class PasteDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(_("Вставити список…"))
        layout = QVBoxLayout(self)
        hint = QLabel(_("Вставте список треків — по одному в рядку, наприклад «1. Виконавець - Назва».\n"
                        "Номери на початку рядків і порожні рядки пропускаються."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.text = QPlainTextEdit()
        clip = QApplication.clipboard().text()
        if clip.count("\n") >= 2:
            self.text.setPlainText(clip)
        layout.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText(_("Скасувати"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(560, 420)

    def tracks(self):
        result = []
        for line in self.text.toPlainText().splitlines():
            line = LEADING_NUMBER.sub("", line).strip()
            if line:
                result.append(split_track(line))
        return result


class Tagger(QDialog):
    def __init__(self, path, title, mb_url):
        super().__init__()
        self.path = path
        head, tracks = read_template(path)
        count = max(tracks) if tracks else 0

        self.setWindowTitle(f"CD Auto Runner — {title or _('Назви треків')}")
        self.setWindowIcon(QIcon.fromTheme("media-optical-audio"))
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.album = QLineEdit(head.get("ALBUM", ""))
        self.album_artist = QLineEdit(head.get("ALBUM_ARTIST", ""))
        self.album_artist.setPlaceholderText(_("порожньо — визначиться сам (для збірки — Various Artists)"))
        self.year = QLineEdit(head.get("YEAR", ""))
        self.year.setMaxLength(4)
        self.year.setMaximumWidth(80)
        form.addRow(_("Альбом:"), self.album)
        form.addRow(_("Виконавець альбому:"), self.album_artist)
        form.addRow(_("Рік:"), self.year)
        layout.addLayout(form)

        hint = QLabel(_("Для збірки (диск із журналу) вкажіть виконавця кожного треку. "
                        "Якщо виконавець той самий, що й в альбому, стовпчик можна лишити порожнім."))
        hint.setWordWrap(True)
        hint.setEnabled(False)
        layout.addWidget(hint)

        self.table = QTableWidget(count, 2)
        self.table.setHorizontalHeaderLabels([_("Виконавець"), _("Назва")])
        self.table.setVerticalHeaderLabels([f"{n:02d}" for n in range(1, count + 1)])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 220)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        for n in range(1, count + 1):
            artist, name = tracks.get(n, ("", ""))
            self.table.setItem(n - 1, 0, QTableWidgetItem(artist))
            self.table.setItem(n - 1, 1, QTableWidgetItem(name))
        layout.addWidget(self.table)

        row = QHBoxLayout()
        paste = QPushButton(QIcon.fromTheme("edit-paste"), _("Вставити список…"))
        paste.clicked.connect(self.paste_list)
        clear = QPushButton(QIcon.fromTheme("edit-clear"), _("Очистити"))
        clear.clicked.connect(self.clear)
        row.addWidget(paste)
        row.addWidget(clear)
        row.addStretch(1)
        if mb_url:
            link = QLabel(f'<a href="{mb_url}">{_("Додати диск у MusicBrainz")}</a>')
            link.setOpenExternalLinks(True)
            row.addWidget(link)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(_("Зберегти"))
        buttons.button(QDialogButtonBox.Cancel).setText(_("Скасувати"))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        save_shortcut = QShortcut(QKeySequence.Save, self)
        save_shortcut.activated.connect(self.save)

        self.resize(720, min(220 + 32 * count, 760))
        self.album.setFocus()

    def paste_list(self):
        dialog = PasteDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        for i, (artist, name) in enumerate(dialog.tracks()[: self.table.rowCount()]):
            self.table.item(i, 0).setText(artist)
            self.table.item(i, 1).setText(name)

    def clear(self):
        for r in range(self.table.rowCount()):
            for c in range(2):
                self.table.item(r, c).setText("")

    def save(self):
        lines = [
            f"ALBUM={self.album.text().strip()}",
            f"ALBUM_ARTIST={self.album_artist.text().strip()}",
            f"YEAR={self.year.text().strip()}",
        ]
        for r in range(self.table.rowCount()):
            artist = self.table.item(r, 0).text().strip()
            name = self.table.item(r, 1).text().strip()
            lines.append(f"{r + 1:02d}=" + (f"{artist} - {name}" if artist and name else name or artist))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.accept()


def main():
    if len(sys.argv) < 2:
        print(__doc__.splitlines()[2], file=sys.stderr)
        return 2
    app = QApplication(sys.argv[:1])
    app.setApplicationName("cd-auto-runner")
    app.setDesktopFileName("cd-auto-runner")
    dialog = Tagger(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "",
                    sys.argv[3] if len(sys.argv) > 3 else "")
    return 0 if dialog.exec() == QDialog.Accepted else 1


if __name__ == "__main__":
    sys.exit(main())
