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
import sys

from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget,
    QStyledItemDelegate, QTableWidgetItem, QVBoxLayout,
)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))     # запуск з -I: спільний модуль лежить поруч
from _tagger_common import _, parse_list, read_template, write_template     # noqa: E402

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
        return parse_list(self.text.toPlainText())


class CellDelegate(QStyledItemDelegate):
    """Деякі теми (Kvantum) малюють редактор комірки прозорим, тож під новою назвою видно
    стару. Кольори такої теми не перебити, тому комірка на час редагування малюється без тексту."""

    def __init__(self, parent):
        super().__init__(parent)
        self.edited = None

    def createEditor(self, parent, option, index):
        self.edited = (index.row(), index.column())
        return super().createEditor(parent, option, index)

    def destroyEditor(self, editor, index):
        self.edited = None
        super().destroyEditor(editor, index)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if (index.row(), index.column()) == self.edited:
            option.text = ""


class Tagger(QDialog):
    def __init__(self, path, title, mb_url):
        super().__init__()
        self.path = path
        head, tracks = read_template(path)
        count = max(tracks) if tracks else 0

        self.setWindowTitle(f"CD Auto Runner — {title or _('Назви треків')}")
        self.setWindowIcon(QIcon.fromTheme("cd-auto-runner", QIcon.fromTheme("media-optical-audio")))
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
        self.table.setItemDelegate(CellDelegate(self.table))
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
        rows = [(self.table.item(r, 0).text(), self.table.item(r, 1).text()) for r in range(self.table.rowCount())]
        write_template(self.path, self.album.text(), self.album_artist.text(), self.year.text(), rows)
        self.accept()


def main():
    if len(sys.argv) < 2:
        print(__doc__.splitlines()[2], file=sys.stderr)
        return 2
    app = QApplication(sys.argv[:1])
    app.setApplicationName("cd-auto-runner")
    app.setDesktopFileName("cd-auto-runner")
    if "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":") and app.font().pointSizeF() >= 11:
        font = app.font()       # той самий розмір, що й у головному вікні
        font.setPointSizeF(font.pointSizeF() - 1)
        app.setFont(font)
    dialog = Tagger(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "",
                    sys.argv[3] if len(sys.argv) > 3 else "")
    return 0 if dialog.exec() == QDialog.Accepted else 1


if __name__ == "__main__":
    sys.exit(main())
