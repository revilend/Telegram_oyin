#!/usr/bin/env python3
"""Uch tillilik auditi: UZ / RU / EN hamma joyda to'liqmi.

Tekshiradi:
* ``core/i18n.py`` — ``STRINGS`` va ``BUTTONS`` kalitlarida uch til ham bor;
* ``webapp/js/i18n.js`` — uch til bloklarida kalitlar to'plami bir xil;
* ``webapp/js/i18n-phrases.js`` — har qator 3 ustun va bo'sh emas;
* ``webapp/index.html`` — barcha ``tr("kalit")`` lar lug'atda mavjud,
  o'yin kartalari (``game_<slug>_name/_desc``) ham tarjima qilingan;
* ``bot/`` — ``t()`` dan o'tmagan o'zbekcha matnlar (ogohlantirish).

Strukturaviy xato bo'lsa ``exit 1`` (CI uchun).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

LANGS: tuple[str, ...] = ("uz", "ru", "en")
# Mini App'dagi o'yin kartalari shu sluglar bo'yicha tarjima qilinadi.
GAME_SLUGS: tuple[str, ...] = ("bunker", "mafia", "spyfall", "alias", "bomb")

WEBAPP_I18N = ROOT / "webapp" / "js" / "i18n.js"
WEBAPP_PHRASES = ROOT / "webapp" / "js" / "i18n-phrases.js"
WEBAPP_INDEX = ROOT / "webapp" / "index.html"
BOT_DIR = ROOT / "bot"

_STRING_RE = re.compile(r'^\s{6}([A-Za-z0-9_]+):\s*"((?:[^"\\]|\\.)*)"', re.M)
_PHRASE_ROW_RE = re.compile(r"^\s*\[(.*?)\],?\s*$", re.M)
_QUOTED_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
_UZ_LETTERS = re.compile(r"[öğışçÖĞİŞÇ]")
_T_CALLS = ("t(", "default_label(", "label(", "BUTTONS", "LANGUAGE_NAMES")


def _python_dicts() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core.i18n import BUTTONS, STRINGS

    return STRINGS, BUTTONS


def parse_webapp_translations(text: str | None = None) -> dict[str, dict[str, str]]:
    text = text if text is not None else WEBAPP_I18N.read_text(encoding="utf-8")
    body = text[text.index("var translations = {"):]
    result: dict[str, dict[str, str]] = {}
    for lang in LANGS:
        match = re.search(
            rf"\n\s{{4}}{lang}: \{{(.*?)\n\s{{4}}\}}[,]?\n", body, re.S
        )
        block: dict[str, str] = {}
        if match:
            for key, value in _STRING_RE.findall(match.group(1)):
                block[key] = value
        result[lang] = block
    return result


def parse_phrases(text: str | None = None) -> list[list[str]]:
    text = text if text is not None else WEBAPP_PHRASES.read_text(encoding="utf-8")
    rows: list[list[str]] = []
    for raw in _PHRASE_ROW_RE.findall(text):
        rows.append([item[1:-1] for item in _QUOTED_RE.findall(raw)])
    return rows


def tr_keys(text: str | None = None) -> list[str]:
    text = text if text is not None else WEBAPP_INDEX.read_text(encoding="utf-8")
    # Dinamik yig'indi (``tr("game_" + slug + "_name")``) alohida tekshiriladi,
    # shuning uchun faqat to'liq yopilgan kalitlar olinadi.
    return sorted(set(re.findall(r'tr\(\s*"([a-z0-9_]+)"\s*[,)]', text)))


def bot_literals() -> dict[str, int]:
    """``t()`` dan o'tmagan o'zbekcha matnlar (fayl bo'yicha)."""
    per_file: dict[str, int] = {}
    for path in sorted(BOT_DIR.rglob("*.py")):
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            if any(call in line for call in _T_CALLS):
                continue
            for match in re.finditer(r'"([^"\n]{8,120})"', line):
                if _UZ_LETTERS.search(match.group(1)):
                    count += 1
        if count:
            per_file[str(path.relative_to(ROOT))] = count
    return per_file


def audit() -> dict[str, Any]:
    strings, buttons = _python_dicts()
    web = parse_webapp_translations()
    phrases = parse_phrases()
    keys = tr_keys()

    missing: list[str] = []
    empty: list[str] = []
    for name, data in (("STRINGS", strings), ("BUTTONS", buttons)):
        for key, row in data.items():
            for lang in LANGS:
                if lang not in row:
                    missing.append(f"{name}:{key}/{lang}")
                elif not str(row[lang]).strip():
                    empty.append(f"{name}:{key}/{lang}")

    web_missing = {
        lang: sorted(set(web.get("uz", {})) - set(web.get(lang, {})))
        for lang in LANGS
    }
    web_empty = [
        f"{key}/{lang}"
        for lang in LANGS
        for key, value in web.get(lang, {}).items()
        if not value.strip()
    ]
    bad_phrases = [
        index
        for index, parts in enumerate(phrases)
        if len(parts) != 3 or any(not part.strip() for part in parts)
    ]
    missing_tr = [key for key in keys if key not in web.get("uz", {})]
    missing_game_cards = [
        f"game_{slug}_{suffix}"
        for slug in GAME_SLUGS
        for suffix in ("name", "desc")
        if f"game_{slug}_{suffix}" not in web.get("uz", {})
    ]
    literals = bot_literals()

    return {
        "strings": {"total": len(strings), "missing": missing, "empty": empty},
        "buttons": {"total": len(buttons)},
        "missing": missing,
        "empty": empty,
        "webapp": {
            "counts": {lang: len(web.get(lang, {})) for lang in LANGS},
            "missing": web_missing,
            "empty": web_empty,
        },
        "phrases": {"rows": len(phrases), "bad": bad_phrases},
        "tr_keys": {"used": len(keys), "missing": missing_tr},
        "game_cards": {"missing": missing_game_cards},
        "bot_literals": {
            "total": sum(literals.values()),
            "files": dict(sorted(literals.items(), key=lambda item: -item[1])),
        },
    }


def problems(result: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if result["missing"]:
        issues.append(f"lug'atda yetishmayotgan til: {result['missing'][:10]}")
    if result["empty"]:
        issues.append(f"lug'atda bo'sh matn: {result['empty'][:10]}")
    for lang, keys in result["webapp"]["missing"].items():
        if keys:
            issues.append(f"i18n.js: {lang} da yo'q kalitlar: {keys[:10]}")
    if result["webapp"]["empty"]:
        issues.append(f"i18n.js: bo'sh matn: {result['webapp']['empty'][:10]}")
    if result["phrases"]["bad"]:
        issues.append(f"i18n-phrases.js: 3 ustunli bo'lmagan qatorlar: {result['phrases']['bad'][:10]}")
    if result["tr_keys"]["missing"]:
        issues.append(f"tr() kalitlari lug'atda yo'q: {result['tr_keys']['missing'][:10]}")
    if result["game_cards"]["missing"]:
        issues.append(f"o'yin kartalari tarjimasi yo'q: {result['game_cards']['missing'][:10]}")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UZ/RU/EN qamrov auditi")
    parser.add_argument(
        "--show-bot-files", type=int, default=10, help="nechta bot faylini ko'rsatish"
    )
    args = parser.parse_args(argv)
    result = audit()

    print("=" * 68)
    print("UCH TILLILIK AUDITI (uz / ru / en)")
    print("=" * 68)
    print(f"core/i18n.py STRINGS: {result['strings']['total']} kalit")
    print(f"core/i18n.py BUTTONS: {result['buttons']['total']} kalit")
    print(
        "webapp/js/i18n.js: "
        + ", ".join(f"{lang}={count}" for lang, count in result["webapp"]["counts"].items())
    )
    print(f"webapp/js/i18n-phrases.js: {result['phrases']['rows']} qator x 3 ustun")
    print(f"tr() chaqiruvlari: {result['tr_keys']['used']} ta kalit")
    print(
        "bot/ tarjima qilinmagan matnlar: "
        f"{result['bot_literals']['total']} ta, {len(result['bot_literals']['files'])} fayl"
    )
    for path, count in list(result["bot_literals"]["files"].items())[: args.show_bot_files]:
        print(f"    {count:4d}  {path}")

    issues = problems(result)
    if issues:
        print("\nXATOLAR:")
        for issue in issues:
            print("  -", issue)
        return 1
    print("\nStrukturaviy xato yo'q: barcha lug'atlar, kalitlar va jadvallar uch tilda.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
