#!/usr/bin/env python3
"""Перевіряє роботу в різних середовищах (GNOME, KDE) на заглушках: без справжнього
приводу, діалогів і налаштувань системи. Значки — на чистій темі Adwaita, якщо вона є.

Checks behaviour across desktops (GNOME, KDE) with stubs: no real drive, dialogs or system
settings are touched. Icons are checked against plain Adwaita when it is installed.
Run: python3 tests/check_desktop.py
"""
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "cd-auto-runner")
# Без PATH-заглушки ці програми не мають потрапити до тесту
STUB_NAMES = ("zenity", "kdialog", "gsettings", "gio", "eject", "ptyxis", "konsole", "notify-send", "mpv", "python3")


def stub(folder, name, body):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'#!/bin/bash\necho "{name} $*" >> "$STUB_LOG"\n{body}\n')
    os.chmod(path, 0o755)


class Sandbox:
    """Тимчасовий HOME і PATH: спершу заглушки, далі — лише системні програми без діалогів."""

    def __init__(self, root, name, desktop, tools=()):
        self.home = os.path.join(root, name)
        self.stubs = os.path.join(self.home, "stubs")
        self.log = os.path.join(self.home, "log")
        os.makedirs(self.stubs)
        self.linked = os.path.join(self.home, "bin")
        os.makedirs(self.linked)
        for d in ("/usr/bin", "/bin"):
            for name in os.listdir(d):
                target = os.path.join(self.linked, name)
                if name not in STUB_NAMES and not name.startswith(("xdg-terminal", "kgx", "gnome-terminal")) \
                        and not os.path.lexists(target):
                    os.symlink(os.path.join(d, name), target)
        real_python = subprocess.run(["bash", "-c", "command -v python3"], capture_output=True, text=True).stdout.strip()
        os.symlink(real_python, os.path.join(self.linked, "python3"))
        for tool in tools:
            stub(self.stubs, tool, "")
        self.env = {
            "HOME": self.home, "PATH": f"{self.stubs}:{self.linked}", "STUB_LOG": self.log, "CDAR_UI_LANG": "en",
            "XDG_CURRENT_DESKTOP": desktop, "WAYLAND_DISPLAY": "wayland-test", "XDG_RUNTIME_DIR": self.home,
            "XDG_DATA_DIRS": os.path.join(self.home, "share"),
        }

    def run(self, *args):
        p = subprocess.run([BIN, *args], env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
        return p.returncode, p.stdout + p.stderr

    def calls(self):
        try:
            with open(self.log, encoding="utf-8") as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []


def check_dialogs(root):
    gnome = Sandbox(root, "dialog-gnome", "GNOME", ("zenity", "kdialog"))
    stub(gnome.stubs, "zenity", "echo uk")
    assert "Українська" in gnome.run("lang")[1]
    assert gnome.calls()[0].startswith("zenity --list --radiolist"), gnome.calls()
    assert "--print-column=2" in gnome.calls()[0]

    kde = Sandbox(root, "dialog-kde", "KDE", ("zenity", "kdialog"))
    stub(kde.stubs, "kdialog", "echo en")
    kde.run("lang")
    assert kde.calls()[0].startswith("kdialog --title"), kde.calls()

    # лише kdialog у GNOME — беремо те, що є
    only = Sandbox(root, "dialog-ubuntu", "ubuntu:GNOME", ("kdialog",))
    stub(only.stubs, "kdialog", "echo en")
    only.run("lang")
    assert only.calls()[0].startswith("kdialog"), only.calls()


def check_terminal(root):
    sb = Sandbox(root, "term-gnome", "GNOME", ("ptyxis", "konsole"))
    sb.run("choose")
    assert sb.calls() == [f"ptyxis -- {BIN} choose --tty"], sb.calls()
    kde = Sandbox(root, "term-kde", "KDE", ("ptyxis", "konsole"))
    kde.run("choose")
    assert kde.calls() == [f"konsole --hide-menubar -e {BIN} choose --tty"], kde.calls()


def check_launch(root):
    sb = Sandbox(root, "launch", "GNOME")
    cfg = os.path.join(sb.home, ".config", "cd-auto-runner")
    os.makedirs(cfg)
    with open(os.path.join(cfg, "config"), "w") as f:
        f.write("PLAYER_ID=off\n")
    code, out = sb.run("launch", "cdda://sr0/")
    assert code == 0 and "disabled" in out, out
    # другий запуск того самого диска (служба вже взяла його) мовчить
    code, out = sb.run("launch", "cdda://sr0/")
    assert code == 0 and not out, out
    # після 15 секунд це вже новий запуск
    claim = os.path.join(sb.home, "cd-auto-runner", "claim-sr0")
    old = time.time() - 60
    os.utime(claim, (old, old))
    assert sb.run("launch", "cdda:///dev/sr0")[1], "застаріла мітка має не заважати"
    code, out = sb.run("launch", "cdda://sr0;rm -rf x/")
    assert code != 0, "адреса не має ставати шляхом до пристрою"


def check_eject(root):
    sb = Sandbox(root, "eject-gnome", "GNOME", ("eject",))
    stub(sb.stubs, "gio", '[[ "$2" == -l ]] && echo "Mount(0): Disc -> cdda://sr0/"; exit 0')
    code, out = sb.run("eject", "/dev/sr0")
    assert code == 0, out
    assert sb.calls() == ["gio mount -l", "gio mount -u cdda://sr0/", "eject /dev/sr0"], sb.calls()
    # gvfs диск не тримає (KDE тощо) — одразу eject
    plain = Sandbox(root, "eject-kde", "KDE", ("eject",))
    code, out = plain.run("eject", "/dev/sr1")
    assert code == 0 and plain.calls() == ["eject /dev/sr1"], plain.calls()


GSETTINGS = r'''
f="$HOME/gs-$3"
case "$1" in
  list-keys) exit 0 ;;
  get) [[ -s "$f" ]] && cat "$f" || echo "@as []" ;;
  set) echo "$4" > "$f" ;;
esac
'''


def check_gnome_autorun(root):
    sb = Sandbox(root, "autorun-gnome", "GNOME")
    stub(sb.stubs, "gsettings", GSETTINGS)
    read = lambda key: open(os.path.join(sb.home, f"gs-{key}")).read().strip()
    start, ignore = "autorun-x-content-start-app", "autorun-x-content-ignore"
    with open(os.path.join(sb.home, f"gs-{start}"), "w") as f:
        f.write("['x-content/audio-cdda', 'x-content/unix-software']\n")
    with open(os.path.join(sb.home, f"gs-{ignore}"), "w") as f:
        f.write("['x-content/video-dvd']\n")
    assert sb.run("gnome-autorun", "on")[0] == 0
    assert read(start) == "['x-content/unix-software']", read(start)
    assert read(ignore) == "['x-content/video-dvd', 'x-content/audio-cdda']", read(ignore)
    # повторне «on» не має загубити початковий стан
    sb.run("gnome-autorun", "on")
    assert sb.run("gnome-autorun", "off")[0] == 0
    assert read(start) == "['x-content/unix-software', 'x-content/audio-cdda']", read(start)
    assert read(ignore) == "['x-content/video-dvd']", read(ignore)
    assert "not changed" in sb.run("gnome-autorun", "off")[1]
    # у KDE без схеми GNOME команда нічого не робить
    kde = Sandbox(root, "autorun-kde", "KDE")
    code, out = kde.run("gnome-autorun", "on")
    assert code == 0 and "only in GNOME" in out, out


def check_own_entry(root):
    sb = Sandbox(root, "list", "GNOME")
    apps = os.path.join(sb.home, ".local", "share", "applications")
    os.makedirs(apps)
    entry = "[Desktop Entry]\nType=Application\nName={0}\nExec={0} %U\nMimeType=x-content/audio-cdda;\n"
    with open(os.path.join(apps, "cd-auto-runner.desktop"), "w") as f:
        f.write(entry.format("own"))
    with open(os.path.join(apps, "other.desktop"), "w") as f:
        f.write(entry.format("other"))
    out = sb.run("list")[1]
    assert "other.desktop" in out and "cd-auto-runner.desktop" not in out, out


def check_icons():
    """На чистому GNOME немає Breeze: жоден значок не має лишитися порожнім."""
    if not os.path.isdir("/usr/share/icons/Adwaita"):
        print("Adwaita не встановлено — значки пропущено / Adwaita missing, icons skipped")
        return
    code = r'''
import importlib.util, os, re, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
root = sys.argv[1]
spec = importlib.util.spec_from_file_location("gui", os.path.join(root, "gui", "gui.py"))
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)
app = gui.QApplication([])
gui.QIcon.setThemeSearchPaths(["/usr/share/icons"])
gui.QIcon.setThemeName("Adwaita")
gui.QIcon.setFallbackThemeName("hicolor")
src = open(os.path.join(root, "gui", "gui.py"), encoding="utf-8").read()
src = src[src.index("def heart_icon"):]
calls = set(re.findall(r"""(?:icon|theme_icon)\(\s*((?:"[a-z-]+"(?:,\s*)?)+)""", src))
groups = {tuple(re.findall(r'"([a-z-]+)"', call)) for call in calls}      # другий і далі — запасні
groups |= {(n,) for n in re.findall(r'"([a-z]+-[a-z-]+-symbolic)"', src)} | {("media-optical-audio",), ("pan-end-symbolic",), ("pan-down-symbolic",)}
missing = sorted(str(g) for g in groups if gui.theme_icon(*g).isNull())
assert not gui.app_icon().isNull(), "немає значка програми"
assert len(groups) > 20, groups
print("\n".join(missing))
sys.exit(1 if missing else 0)
'''
    p = subprocess.run([sys.executable, "-c", code, ROOT], capture_output=True, text=True)
    assert p.returncode == 0, f"значки Adwaita: {p.stdout}{p.stderr}"


def check_sections(root):
    """Картки налаштувань типово згорнуті й пам'ятають стан; ключ не залежить від мови."""
    code = r'''
import importlib.util, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
spec = importlib.util.spec_from_file_location("gui", os.path.join(sys.argv[1], "gui", "gui.py"))
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)
app = gui.QApplication([])
box, form = gui.section("Заголовок", "test")
head = box.findChild(gui.QToolButton)
assert box.body.isHidden() and not head.isChecked(), "типово згорнута"
head.click()
assert not box.body.isHidden(), "клік розгортає"
box, form = gui.section("Title", "test")
assert not box.body.isHidden(), "стан збережено"
'''
    env = dict(os.environ, XDG_CONFIG_HOME=os.path.join(root, "sections"))
    p = subprocess.run([sys.executable, "-c", code, ROOT], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stdout + p.stderr


def main():
    with tempfile.TemporaryDirectory() as root:
        for check in (check_dialogs, check_terminal, check_launch, check_eject, check_gnome_autorun, check_own_entry,
                      check_sections):
            check(root)
            print(f"ok {check.__name__}")
    check_icons()
    print("ok check_icons")
    print("усе добре / all good")


if __name__ == "__main__":
    main()
