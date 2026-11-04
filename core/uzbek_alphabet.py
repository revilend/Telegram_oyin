"""Yangi o'zbek lotin yozuvidagi ko'rinadigan matnlarni normallashtirish."""
from __future__ import annotations

import re

_APOSTROPHES = "'ʻʼ’‘"
_O_RE = re.compile(r"o[" + re.escape(_APOSTROPHES) + r"]", re.IGNORECASE)
_G_RE = re.compile(r"g[" + re.escape(_APOSTROPHES) + r"]", re.IGNORECASE)
_SH_RE = re.compile(r"sh", re.IGNORECASE)
_CH_RE = re.compile(r"ch", re.IGNORECASE)


def _case_letter(match: re.Match[str], lower: str, upper: str) -> str:
    token = match.group(0)
    return upper if token[0].isupper() else lower


def new_uzbek_latin(text: str) -> str:
    """Oʻ/oʻ→Ö/ö, Gʻ/gʻ→Ğ/ğ, Sh/sh→Ş/ş, Ch/ch→Ç/ç."""
    value = str(text)
    value = _O_RE.sub(lambda m: _case_letter(m, "ö", "Ö"), value)
    value = _G_RE.sub(lambda m: _case_letter(m, "ğ", "Ğ"), value)
    value = _SH_RE.sub(lambda m: _case_letter(m, "ş", "Ş"), value)
    value = _CH_RE.sub(lambda m: _case_letter(m, "ç", "Ç"), value)
    return value
