"""String normalization shared by ingest and matching."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def norm_header(h: object) -> str:
    """Normalize a spreadsheet header: NBSP/line breaks -> space, lowercase, trimmed."""
    s = unicodedata.normalize("NFKC", str(h)).replace("\xa0", " ")
    return _WS.sub(" ", s).strip().lower()


def squash(s: object) -> str:
    """Lowercase with ALL whitespace removed (PDF text extraction drops spaces)."""
    return _WS.sub("", unicodedata.normalize("NFKC", str(s))).lower()


_PAREN = re.compile(r"\([^)]*\)")
_NONALNUM = re.compile(r"[^a-z0-9 ]+")


def org_key(name: object) -> str:
    """Canonical comparison key for an RSO name.

    "Graduate Women in Engineering (GWiE)" == "Graduate Women in Engineering"
    "Ramblin’ Reck Club" == "Ramblin' Reck Club"
    """
    s = unicodedata.normalize("NFKC", str(name or "")).lower()
    s = s.replace("’", "'").replace("&", " and ")
    s = _PAREN.sub(" ", s)
    s = s.replace("'", "")
    s = _NONALNUM.sub(" ", s)
    return _WS.sub(" ", s).strip()


def org_key_squashed(name: object) -> str:
    return org_key(name).replace(" ", "")
