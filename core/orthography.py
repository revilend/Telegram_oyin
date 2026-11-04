"""O'zbek lotin yozuvini yangi harflarga o'girish.

Loyihada matnlar asosan ``o'``, ``g'``, ``sh`` va ``ch`` ko'rinishida
yozilgan.  Foydalanuvchiga ko'rinadigan matnlarda ular mos ravishda
``ö``, ``ğ``, ``ş`` va ``ç`` bo'lishi kerak.

Funksiya HTML teglarini, havolalarni, ``/buyruq``larni va ``@mention``larni
o'zgartirmaydi: aks holda tugma havolalari va bot buyruqlari ishlamay qoladi.
"""

from __future__ import annotations

import re

_CODE_RE = re.compile(r"<code>.*?</code>|<pre>.*?</pre>", re.IGNORECASE | re.DOTALL)
_TOKEN_RE = re.compile(r"https?://\S+|(?:^|\s)/[A-Za-z0-9_@]+|@[A-Za-z0-9_]+")
_TAG_RE = re.compile(r"(<[^>]+>)")
_SH_RE = re.compile(r"sh", re.IGNORECASE)
_CH_RE = re.compile(r"ch", re.IGNORECASE)


def _replace_pair(match: re.Match[str], lower: str) -> str:
    token = match.group(0)
    if token[:1].isupper():
        return lower.upper()
    return lower


def _replace_digraphs(text: str) -> str:
    text = _SH_RE.sub(lambda match: _replace_pair(match, "ş"), text)
    text = _CH_RE.sub(lambda match: _replace_pair(match, "ç"), text)
    return text


def _replace_apostrophe_letters(text: str) -> str:
    # ASCII apostrophe, typographic quotes and the modifier letter turned comma.
    text = re.sub(r"[oO][\'‘’ʻ]", lambda m: "Ö" if m.group(0)[0].isupper() else "ö", text)
    text = re.sub(r"[gG][\'‘’ʻ]", lambda m: "Ğ" if m.group(0)[0].isupper() else "ğ", text)
    return text


def _transform_segment(segment: str) -> str:
    """Matn bo'lagini o'giradi, havola va buyruqlarni vaqtincha yashiradi."""
    protected: list[str] = []

    def stash(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    segment = _TOKEN_RE.sub(stash, segment)
    segment = _replace_apostrophe_letters(segment)
    segment = _replace_digraphs(segment)
    for index, value in enumerate(protected):
        segment = segment.replace(f"\x00{index}\x00", value)
    return segment


def to_new_alphabet(text: str) -> str:
    """Matnni yangi o'zbek alifbosiga o'giradi.

    HTML teglari va ``<code>`` ichidagi buyruqlar saqlanadi.  Funksiya
    idempotent: allaqachon o'girilgan matn qayta o'zgarmaydi.
    """
    if not text:
        return text

    protected: list[str] = []

    def stash(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    value = _CODE_RE.sub(stash, text)
    parts = _TAG_RE.split(value)
    for index, part in enumerate(parts):
        if part.startswith("<") and part.endswith(">"):
            continue
        parts[index] = _transform_segment(part)
    value = "".join(parts)
    for index, item in enumerate(protected):
        value = value.replace(f"\x00{index}\x00", item)
    return value


__all__ = ["to_new_alphabet"]
