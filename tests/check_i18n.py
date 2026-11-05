#!/usr/bin/env python3
"""Перевіряє, що кожен текст у _ '…' має англійський переклад у i18n.sh
і що кількість параметрів printf (%s, %02d) у перекладі збігається з оригіналом.

Checks that every _ '…' string has an English translation in i18n.sh and that
the printf placeholders match. Run: python3 tests/check_i18n.py
"""
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["cd-auto-runner", "install.sh", "uninstall.sh"] + sorted(glob.glob(os.path.join(ROOT, "players", "*.sh")))
CALL = re.compile(r"""(?:^|[\s(;{])_ (?:'([^']*)'|"((?:[^"\\]|\\.)*)")""", re.S)
PLACEHOLDER = re.compile(r"%[-0-9]*[sd]")


def used_strings():
    found = []
    for name in FILES:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            for m in CALL.finditer(f.read()):
                text = m.group(1) if m.group(1) is not None else m.group(2)
                if text not in found:
                    found.append(text)
    return found


def translations():
    script = 'source "$1"; for k in "${!CDAR_EN[@]}"; do printf "%s\\0%s\\0" "$k" "${CDAR_EN[$k]}"; done'
    out = subprocess.run(["bash", "-c", script, "_", os.path.join(ROOT, "i18n.sh")],
                         capture_output=True, text=True, check=True).stdout.split("\0")
    return dict(zip(out[0::2], out[1::2]))


# У файлах із власним словником EN він у самому файлі; вікна беруть його зі спільного cdar_core.py
SHARED_EN = os.path.join(ROOT, "gui", "cdar_core.py")
TAGGER_EN = os.path.join(ROOT, "players", "_tagger_common.py")
PY_FILES = [SHARED_EN, os.path.join(ROOT, "gui", "gui.py"), os.path.join(ROOT, "gui", "gui_gtk.py"),
            TAGGER_EN, os.path.join(ROOT, "players", "_tagger.py"), os.path.join(ROOT, "players", "_tagger_gtk.py")]
PY_CALL = re.compile(r"""\b_\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)""")


def check_python():
    """Кожен _("…") має бути в словнику EN: власному або спільному."""
    import ast

    def dictionary(tree):
        return next((ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                     and any(getattr(t, "id", "") == "EN" for t in n.targets)), {})
    def shared(path):
        with open(path, encoding="utf-8") as f:
            return dictionary(ast.parse(f.read()))
    errors = []
    for path in PY_FILES:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        en = shared(TAGGER_EN if "tagger" in os.path.basename(path) else SHARED_EN)
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_" and node.args \
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                used.add(node.args[0].value)
        # тексти, що перекладаються через змінну (_(text), _(labels[...]))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict) and node is not None:
                for v in node.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value in en:
                        used.add(v.value)
        for text in sorted(used - set(en)):
            if re.search(r"[\u0400-\u04FF]", text):
                errors.append(f"{os.path.basename(path)}: немає перекладу / missing translation: {text!r}")
    return errors


def main():
    used, en = used_strings(), translations()
    errors = []
    for text in used:
        if text not in en:
            errors.append(f"немає перекладу / missing translation: {text!r}")
        elif PLACEHOLDER.findall(text) != PLACEHOLDER.findall(en[text]):
            errors.append(f"параметри не збігаються / placeholders differ: {text!r}")
    for text in en:
        if text not in used:
            print(f"не використовується / unused: {text!r}")
    errors += check_python()
    for e in errors:
        print(e, file=sys.stderr)
    print(f"{len(used)} рядків, помилок: {len(errors)} / {len(used)} strings, errors: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
