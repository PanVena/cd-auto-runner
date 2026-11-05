#!/usr/bin/env python3
"""Форма введення назв треків для cd-auto-runner (GTK 4, libadwaita).

Використання: _tagger_gtk.py ФАЙЛ [ЗАГОЛОВОК] [ПОСИЛАННЯ_MUSICBRAINZ]

Те саме, що й _tagger.py, для вікна GTK: форма заповнюється з ФАЙЛА, після «Зберегти» записує
результат у нього (код виходу 0), «Скасувати» — код 1. Мова: CDAR_UI_LANG (uk | en).

Tracklist editor for cd-auto-runner, the GTK twin of _tagger.py.

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk     # noqa: E402

sys.path.append(os.path.dirname(os.path.abspath(__file__)))     # запуск з -I: спільний модуль лежить поруч
from _tagger_common import _, parse_list, read_template, write_template     # noqa: E402


class TrackRow(Gtk.ListBoxRow):
    def __init__(self, number, artist, name):
        super().__init__(activatable=False, selectable=False)
        box = Gtk.Box(spacing=6, margin_top=4, margin_bottom=4, margin_start=10, margin_end=10)
        box.append(Gtk.Label(label=f"{number:02d}", css_classes=["dim-label"]))
        self.artist = Gtk.Entry(text=artist, placeholder_text=_("Виконавець"), hexpand=True, width_chars=14)
        self.name = Gtk.Entry(text=name, placeholder_text=_("Назва"), hexpand=True, width_chars=22)
        box.append(self.artist)
        box.append(self.name)
        self.set_child(box)


class PasteDialog(Adw.Dialog):
    def __init__(self, form):
        super().__init__(title=_("Вставити список…"), content_width=560, content_height=420)
        self.form = form
        head = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancel = Gtk.Button(label=_("Скасувати"))
        cancel.connect("clicked", lambda _b: self.close())
        apply_button = Gtk.Button(label=_("Вставити список…").rstrip("…"), css_classes=["suggested-action"])
        apply_button.connect("clicked", self.on_apply)
        head.pack_start(cancel)
        head.pack_end(apply_button)
        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=True, top_margin=8, bottom_margin=8,
                                 left_margin=8, right_margin=8)
        hint = Gtk.Label(label=_("Вставте список треків — по одному в рядку, наприклад «1. Виконавець - Назва».\n"
                                 "Номери на початку рядків і порожні рядки пропускаються."),
                         wrap=True, xalign=0, css_classes=["dim-label"], margin_start=12, margin_end=12, margin_top=6)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(hint)
        box.append(Gtk.ScrolledWindow(child=self.text, vexpand=True, has_frame=True, margin_start=12, margin_end=12, margin_bottom=12))
        view = Adw.ToolbarView(content=box)
        view.add_top_bar(head)
        self.set_child(view)
        Gdk.Display.get_default().get_clipboard().read_text_async(None, self.on_clipboard)

    def on_clipboard(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except Exception:       # у буфері не текст
            return
        if text and text.count("\n") >= 2:
            self.text.get_buffer().set_text(text)

    def on_apply(self, _button):
        buffer = self.text.get_buffer()
        self.form.fill(parse_list(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)))
        self.close()


class Form(Adw.ApplicationWindow):
    def __init__(self, app, path, title, mb_url):
        count_title = f"CD Auto Runner — {title or _('Назви треків')}"
        head_data, tracks = read_template(path)
        count = max(tracks) if tracks else 0
        super().__init__(application=app, title=count_title, default_width=720, default_height=min(300 + 52 * count, 780))
        self.app, self.path = app, path

        head = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancel = Gtk.Button(label=_("Скасувати"))
        cancel.connect("clicked", lambda _b: self.close())
        save = Gtk.Button(label=_("Зберегти"), css_classes=["suggested-action"])
        save.connect("clicked", lambda _b: self.save())
        head.pack_start(cancel)
        head.pack_end(save)

        group = Adw.PreferencesGroup()
        self.album = Adw.EntryRow(title=_("Альбом:").rstrip(":"), text=head_data.get("ALBUM", ""))
        self.album_artist = Adw.EntryRow(title=_("Виконавець альбому:").rstrip(":"), text=head_data.get("ALBUM_ARTIST", ""))
        self.year = Adw.EntryRow(title=_("Рік:").rstrip(":"), text=head_data.get("YEAR", ""), max_length=4)
        group.add(self.album)
        group.add(self.album_artist)
        group.add(self.year)
        detected = Gtk.Label(label=_("порожньо — визначиться сам (для збірки — Various Artists)"), xalign=0, wrap=True,
                             css_classes=["caption", "dim-label"])
        hint = Gtk.Label(label=_("Для збірки (диск із журналу) вкажіть виконавця кожного треку. "
                                 "Якщо виконавець той самий, що й в альбому, стовпчик можна лишити порожнім."),
                         xalign=0, wrap=True, css_classes=["dim-label"])

        self.rows = [TrackRow(n, *tracks.get(n, ("", ""))) for n in range(1, count + 1)]
        table = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        for row in self.rows:
            table.append(row)

        tools = Gtk.Box(spacing=8)
        paste = Gtk.Button(label=_("Вставити список…"))
        paste.connect("clicked", lambda _b: PasteDialog(self).present(self))
        clear = Gtk.Button(label=_("Очистити"))
        clear.connect("clicked", lambda _b: self.clear())
        tools.append(paste)
        tools.append(clear)
        if mb_url:
            tools.append(Gtk.LinkButton(uri=mb_url, label=_("Додати диск у MusicBrainz"), halign=Gtk.Align.END, hexpand=True))

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=18,
                       margin_start=12, margin_end=12)
        for w in (group, detected, hint, table, tools):
            body.append(w)
        view = Adw.ToolbarView(content=Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                                          child=Adw.Clamp(child=body, maximum_size=760)))
        view.add_top_bar(head)
        self.set_content(view)
        self.album.grab_focus()

    def fill(self, tracks):
        for row, (artist, name) in zip(self.rows, tracks):
            row.artist.set_text(artist)
            row.name.set_text(name)

    def clear(self):
        for row in self.rows:
            row.artist.set_text("")
            row.name.set_text("")

    def save(self):
        write_template(self.path, self.album.get_text(), self.album_artist.get_text(), self.year.get_text(),
                       [(row.artist.get_text(), row.name.get_text()) for row in self.rows])
        self.app.saved = True
        self.close()


class Application(Adw.Application):
    def __init__(self, args):
        super().__init__(flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.args = args
        self.saved = False

    def do_activate(self):
        Form(self, *self.args).present()


def main():
    if len(sys.argv) < 2:
        print(__doc__.splitlines()[2], file=sys.stderr)
        return 2
    args = (sys.argv + ["", ""])[1:4]
    app = Application(args)
    app.run(sys.argv[:1])
    return 0 if app.saved else 1


if __name__ == "__main__":
    sys.exit(main())
