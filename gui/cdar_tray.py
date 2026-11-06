"""CD Auto Runner — значок у системному лотку для вікна GTK.

GTK 4 не має лотка, а AppIndicator потребує GTK 3, який не завантажиться поруч із GTK 4. Тому значок
говорить із панеллю напряму через D-Bus: StatusNotifierItem (сам значок) і com.canonical.dbusmenu
(його меню). Те саме робить QSystemTrayIcon у Qt, тож у KDE і в GNOME з розширенням AppIndicator
обидва вікна мають однаковий значок. Викликати лише з головного циклу GLib.

System tray icon for the GTK window: StatusNotifierItem and dbusmenu spoken directly over D-Bus,
as GTK 4 has no tray and AppIndicator needs GTK 3. Main loop only.

SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Pan Vena
"""
import os
import sys

from gi.repository import Gio, GLib

WATCHER = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_IFACE = "org.kde.StatusNotifierItem"
ITEM_PATH = "/StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"
MENU_PATH = "/MenuBar"
NOTIFY = "org.freedesktop.Notifications"
NOTIFY_PATH = "/org/freedesktop/Notifications"

ITEM_XML = f"""<node><interface name="{ITEM_IFACE}">
  <property name="Category" type="s" access="read"/>
  <property name="Id" type="s" access="read"/>
  <property name="Title" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="WindowId" type="i" access="read"/>
  <property name="IconName" type="s" access="read"/>
  <property name="IconPixmap" type="a(iiay)" access="read"/>
  <property name="IconThemePath" type="s" access="read"/>
  <property name="OverlayIconName" type="s" access="read"/>
  <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
  <property name="AttentionIconName" type="s" access="read"/>
  <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
  <property name="AttentionMovieName" type="s" access="read"/>
  <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
  <property name="ItemIsMenu" type="b" access="read"/>
  <property name="Menu" type="o" access="read"/>
  <method name="ContextMenu"><arg name="x" type="i"/><arg name="y" type="i"/></method>
  <method name="Activate"><arg name="x" type="i"/><arg name="y" type="i"/></method>
  <method name="SecondaryActivate"><arg name="x" type="i"/><arg name="y" type="i"/></method>
  <method name="Scroll"><arg name="delta" type="i"/><arg name="orientation" type="s"/></method>
  <method name="ProvideXdgActivationToken"><arg name="token" type="s"/></method>
  <signal name="NewTitle"/>
  <signal name="NewIcon"/>
  <signal name="NewAttentionIcon"/>
  <signal name="NewOverlayIcon"/>
  <signal name="NewToolTip"/>
  <signal name="NewStatus"><arg name="status" type="s"/></signal>
</interface></node>"""

MENU_XML = f"""<node><interface name="{MENU_IFACE}">
  <property name="Version" type="u" access="read"/>
  <property name="TextDirection" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="IconThemePath" type="as" access="read"/>
  <method name="GetLayout">
    <arg direction="in" type="i"/><arg direction="in" type="i"/><arg direction="in" type="as"/>
    <arg direction="out" type="u"/><arg direction="out" type="(ia{{sv}}av)"/>
  </method>
  <method name="GetGroupProperties">
    <arg direction="in" type="ai"/><arg direction="in" type="as"/><arg direction="out" type="a(ia{{sv}})"/>
  </method>
  <method name="GetProperty">
    <arg direction="in" type="i"/><arg direction="in" type="s"/><arg direction="out" type="v"/>
  </method>
  <method name="Event">
    <arg direction="in" type="i"/><arg direction="in" type="s"/><arg direction="in" type="v"/><arg direction="in" type="u"/>
  </method>
  <method name="EventGroup">
    <arg direction="in" type="a(isvu)"/><arg direction="out" type="ai"/>
  </method>
  <method name="AboutToShow">
    <arg direction="in" type="i"/><arg direction="out" type="b"/>
  </method>
  <method name="AboutToShowGroup">
    <arg direction="in" type="ai"/><arg direction="out" type="ai"/><arg direction="out" type="ai"/>
  </method>
  <signal name="ItemsPropertiesUpdated"><arg type="a(ia{{sv}})"/><arg type="a(ias)"/></signal>
  <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
  <signal name="ItemActivationRequested"><arg type="i"/><arg type="u"/></signal>
</interface></node>"""


def s(text):
    return GLib.Variant("s", text)


def bus_error(error):
    print(f"cdar_tray: {error.message}", file=sys.stderr)


class Tray:
    """Значок із меню. menu() щоразу повертає пункти: None (роздільник) або (напис, значок, доступний,
    дія); кількість пунктів незмінна. activate — клік, secondary — середня кнопка, token — маркер
    xdg-activation перед показом вікна (Wayland), clicked — клік по сповіщенню з notify()."""

    def __init__(self, item_id, title, icon, theme_path, menu, activate, secondary, token, clicked):
        self.item_id, self.title, self.icon, self.theme_path = item_id, title, icon, theme_path
        self.menu, self.activate, self.secondary, self.token, self.clicked = menu, activate, secondary, token, clicked
        self.service = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self.tooltip = ""
        self.wanted = False         # чи має значок бути на панелі
        self.owner = 0              # ідентифікатор володіння service
        self.objects = []
        self.watch = self.subscription = 0
        self.revision = 1
        self.seen = None            # меню, яке панель уже отримала
        self.notes = set()          # сповіщення, клік по яких відкриває вікно
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        except GLib.Error as e:
            bus_error(e)
            self.bus = None
            return
        self.watch = Gio.bus_watch_name_on_connection(
            self.bus, WATCHER, Gio.BusNameWatcherFlags.NONE, lambda *_a: self.register(), None)
        self.subscription = self.bus.signal_subscribe(
            NOTIFY, NOTIFY, "ActionInvoked", NOTIFY_PATH, None, Gio.DBusSignalFlags.NONE, self.on_note_action)

    # --- стан -----------------------------------------------------------------------------
    def available(self):
        """Панель, що показує значки, є саме зараз (у GNOME — лише з розширенням AppIndicator)."""
        if not self.bus:
            return False
        try:
            reply = self.bus.call_sync(WATCHER, WATCHER_PATH, "org.freedesktop.DBus.Properties", "Get",
                                       GLib.Variant("(ss)", (WATCHER, "IsStatusNotifierHostRegistered")),
                                       GLib.VariantType("(v)"), Gio.DBusCallFlags.NO_AUTO_START, 500, None)
        except GLib.Error:
            return False
        return bool(reply.unpack()[0])

    def shown(self):
        return self.wanted and self.available()

    def set_visible(self, on):
        self.wanted = on and self.bus is not None
        if self.wanted and not self.owner:
            for path, xml, call, prop in ((ITEM_PATH, ITEM_XML, self.on_item_call, self.item_property),
                                          (MENU_PATH, MENU_XML, self.on_menu_call, self.menu_property)):
                info = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
                self.objects.append(self.bus.register_object(path, info, call, prop, None))
            self.owner = Gio.bus_own_name_on_connection(
                self.bus, self.service, Gio.BusNameOwnerFlags.NONE, lambda *_a: self.register(), None)
        elif not self.wanted and self.owner:    # панель прибирає значок, щойно зникає його ім'я
            Gio.bus_unown_name(self.owner)
            self.owner = 0
            while self.objects:
                self.bus.unregister_object(self.objects.pop())

    def register(self):
        if self.owner:
            self.bus.call(WATCHER, WATCHER_PATH, WATCHER, "RegisterStatusNotifierItem",
                          GLib.Variant("(s)", (self.service,)), None, Gio.DBusCallFlags.NO_AUTO_START, -1, None,
                          self.on_registered)

    def on_registered(self, bus, result):
        try:
            bus.call_finish(result)
        except GLib.Error:      # панелі немає (GNOME без розширення): з'явиться — зареєструємось
            pass

    def close(self):
        self.set_visible(False)
        if self.watch:
            Gio.bus_unwatch_name(self.watch)
            self.bus.signal_unsubscribe(self.subscription)
            self.watch = 0

    def set_tooltip(self, text):
        if text != self.tooltip:
            self.tooltip = text
            if self.owner:
                self.bus.emit_signal(None, ITEM_PATH, ITEM_IFACE, "NewToolTip", None)

    def refresh(self):
        """Доступність пунктів змінилась — панель перечитає меню."""
        if self.owner and self.stale():
            self.bus.emit_signal(None, MENU_PATH, MENU_IFACE, "LayoutUpdated",
                                 GLib.Variant("(ui)", (self.revision, 0)))

    def stale(self):
        now = [item and item[:3] for item in self.menu()]
        if now == self.seen:
            return False
        self.seen = now
        self.revision += 1
        return True

    def notify(self, title, text, image, timeout):
        """Сповіщення з кліком, як у QSystemTrayIcon.showMessage."""
        hints = {"desktop-entry": s(self.icon)}
        if image:
            hints["image-path"] = s(image)
        self.bus.call(NOTIFY, NOTIFY_PATH, NOTIFY, "Notify",
                      GLib.Variant("(susssasa{sv}i)", (self.title, 0, self.icon, title, text, ["default", self.title], hints, timeout)),
                      GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, -1, None, self.on_notified)

    def on_notified(self, bus, result):
        try:
            self.notes.add(bus.call_finish(result).unpack()[0])
        except GLib.Error as e:         # сповіщення необов'язкові
            bus_error(e)

    def on_note_action(self, _bus, _sender, _path, _iface, _signal, args):
        note, _action = args.unpack()
        if note in self.notes:
            self.notes.discard(note)
            self.clicked()

    # --- StatusNotifierItem ----------------------------------------------------------------
    def item_property(self, _bus, _sender, _path, _iface, name):
        strings = {"Category": "ApplicationStatus", "Id": self.item_id, "Title": self.title, "Status": "Active",
                   "IconName": self.icon, "IconThemePath": self.theme_path, "OverlayIconName": "",
                   "AttentionIconName": "", "AttentionMovieName": ""}
        if name in strings:
            return s(strings[name])
        if name == "WindowId":
            return GLib.Variant("i", 0)
        if name == "ItemIsMenu":
            return GLib.Variant("b", False)
        if name == "Menu":
            return GLib.Variant("o", MENU_PATH)
        if name == "ToolTip":
            return GLib.Variant("(sa(iiay)ss)", (self.icon, [], self.title, self.tooltip))
        return GLib.Variant("a(iiay)", [])

    def on_item_call(self, _bus, _sender, _path, _iface, method, args, invocation):
        invocation.return_value(None)
        if method == "Activate":
            self.activate()
        elif method == "SecondaryActivate":
            self.secondary()
        elif method == "ProvideXdgActivationToken":
            self.token(args.unpack()[0])

    # --- dbusmenu --------------------------------------------------------------------------
    def menu_property(self, _bus, _sender, _path, _iface, name):
        return {"Version": GLib.Variant("u", 3), "TextDirection": s("ltr"), "Status": s("normal"),
                "IconThemePath": GLib.Variant("as", [self.theme_path] if self.theme_path else [])}[name]

    def properties(self, item):
        if item is None:
            return {"type": s("separator")}
        label, icon, enabled, _action = item
        return {"label": s(label), "icon-name": s(icon), "enabled": GLib.Variant("b", enabled)}

    def layout(self):
        items = [GLib.Variant("(ia{sv}av)", (number, self.properties(item), []))
                 for number, item in enumerate(self.menu(), 1)]
        return 0, {"children-display": s("submenu")}, items

    def on_menu_call(self, _bus, _sender, _path, _iface, method, args, invocation):
        reply, click = None, None
        if method == "GetLayout":
            self.stale()        # панель отримає свіжі пункти, сигнал про них уже зайвий
            reply = GLib.Variant("(u(ia{sv}av))", (self.revision, self.layout()))
        elif method == "GetGroupProperties":
            ids, _names = args.unpack()
            items = list(enumerate(self.menu(), 1))
            reply = GLib.Variant("(a(ia{sv}))", ([(n, self.properties(i)) for n, i in items if n in ids or not ids],))
        elif method == "GetProperty":
            number, name = args.unpack()
            value = self.properties(self.menu()[number - 1]).get(name, s("")) if number else s("")
            reply = GLib.Variant("(v)", (value,))
        elif method == "Event":
            number, event = args.unpack()[:2]
            click = number if event == "clicked" else None
        elif method == "EventGroup":
            click = next((e[0] for e in args.unpack()[0] if e[1] == "clicked"), None)
            reply = GLib.Variant("(ai)", ([],))
        elif method == "AboutToShow":
            reply = GLib.Variant("(b)", (self.stale(),))
        elif method == "AboutToShowGroup":
            reply = GLib.Variant("(aiai)", ([0] if self.stale() else [], []))
        invocation.return_value(reply)
        if click:
            items = self.menu()
            if 0 < click <= len(items) and items[click - 1] and items[click - 1][2]:
                items[click - 1][3]()
