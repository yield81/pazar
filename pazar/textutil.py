"""Съпоставяне на текст: нормализация, транслитерация и оценка на съвпадение."""

from __future__ import annotations

import re
import unicodedata

# Латински букви, които при кирилизиран текст се пишат на кирилица.
_SIMPLE = {
    "a": "а", "b": "б", "c": "с", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "х", "i": "и", "j": "й", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в",
    "z": "з",
}
# Нееднозначни букви — пробваме по един вариант за всеки запис.
_AMBIGUOUS = {"y": ("й", "я", "и"), "w": ("в",), "q": ("к",), "x": ("кс",)}

_CURRENCY = "лв"

# Опростена кирилица → латиница (я→a, ю→u, й/ь/ъ отпадат).
_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "",
    "ь": "", "ю": "u", "я": "a",
}


def loose(text: str) -> str:
    """Опростен ключ за сравнение: кирилица/латиница, без й, ь, ъ, y и j."""
    out = []
    for ch in base_norm(text):
        if ch in _CYR_TO_LAT:
            out.append(_CYR_TO_LAT[ch])
        elif ch.isalnum():
            out.append(ch)
    return "".join(out).replace("y", "").replace("j", "")


def base_norm(text: str) -> str:
    """Малки букви, без пунктуация, единични интервали."""
    text = unicodedata.normalize("NFC", text or "")
    text = text.lower().replace("_", " ")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _translit(text: str, y_variant: str) -> str:
    out = []
    for ch in text:
        if ch in _SIMPLE:
            out.append(_SIMPLE[ch])
        elif ch == "y":
            out.append(y_variant)
        elif ch in _AMBIGUOUS:
            out.append(_AMBIGUOUS[ch][0])
        else:
            out.append(ch)
    return "".join(out)


def variants(text: str) -> set[str]:
    """Всички нормализирани форми на текста (кирилица + транслитерация + без интервали)."""
    base = base_norm(text)
    if not base:
        return {""}
    out = {base}
    for y_variant in ("й", "я", "и"):
        v = _translit(base, y_variant)
        out.add(v)
        out.add(v.replace(" ", ""))
    return out


def match_score(query: str, name: str, keywords=()) -> int:
    """0 = няма съвпадение, 100 = точно име. По-високото е по-добро."""
    q_vars = [v for v in variants(query) if len(v) >= 2]
    if not q_vars:
        return 0
    n_vars = [v for v in variants(name) if v]
    k_vars: set[str] = set()
    for kw in keywords or ():
        k_vars |= {v for v in variants(kw) if v}
    if not n_vars:
        return 0

    best = 0
    for q in q_vars:
        for n in n_vars:
            if q == n:
                best = max(best, 100)
            elif n.startswith(q):
                best = max(best, 80)
            elif q in n:
                best = max(best, 60)
            elif len(n) >= 3 and n in q:
                best = max(best, 55)
        for k in k_vars:
            if q == k:
                best = max(best, 90)
            elif q in k:
                best = max(best, 50)

    # Опростено сравнение: намира „мляко“ и през латиница (mlako, mljako).
    q_loose = loose(query)
    n_loose = loose(name)
    if len(q_loose) >= 2:
        if q_loose == n_loose:
            best = max(best, 85)
        elif n_loose.startswith(q_loose):
            best = max(best, 75)
        elif q_loose in n_loose:
            best = max(best, 55)

    # Всички думи от заявката се срещат в името.
    tokens = [t for t in base_norm(query).split() if len(t) >= 2]
    if len(tokens) > 1 and best < 70:
        if all(any(tv in n for tv in variants(t) for n in n_vars) for t in tokens):
            best = 70
    return best


def parse_qty_spec(spec: str) -> tuple[str, float]:
    """'мляко*2' -> ('мляко', 2.0). Поддържа x, * и ×."""
    spec = (spec or "").strip()
    m = re.match(r"^(.*?)\s*[x*×]\s*(\d+(?:[.,]\d+)?)$", spec, flags=re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip(), float(m.group(2).replace(",", "."))
    return spec, 1.0


def to_number(value) -> float:
    """'2,49' / '2.49' / '2 лв' -> 2.49"""
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d,.\-]", "", str(value or "")).replace(",", ".")
    if not text:
        raise ValueError("празна стойност")
    return float(text)


def money(value: float) -> str:
    return f"{float(value):.2f} {_CURRENCY}"


def qty(value: float) -> str:
    value = float(value)
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
