"""Нормализация русского текста: общая для скрапера, индекса и поиска по людям."""

from __future__ import annotations

import re

# На сайте встречаются латинские буквы внутри русских слов (Pазумный, Cалтыкова).
_CONFUSABLES = str.maketrans(
    {
        "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
        "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
        "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    }
)

_CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")
_WORD = re.compile(r"[а-яёa-z0-9]+", re.I)


def deconfuse(text: str) -> str:
    """Чинит латиницу, затесавшуюся в кириллические слова."""
    result = []
    for token in re.split(r"(\s+)", text):
        if _CYRILLIC.search(token):
            result.append(token.translate(_CONFUSABLES))
        else:
            result.append(token)
    return "".join(result)


def fold(text: str) -> str:
    """Регистр, ё и лишние пробелы — к одному виду."""
    return re.sub(r"\s+", " ", deconfuse(text).lower().replace("ё", "е")).strip()


def tokenize(text: str) -> list[str]:
    """Токены для BM25: слова и числа, включая номера кабинетов."""
    return _WORD.findall(fold(text))


def stem(token: str) -> str:
    """Очень лёгкий стеммер: срезает частые русские окончания.

    Полноценная морфология тут избыточна — корпус маленький, а гибридный поиск
    добирает смысл векторами.
    """
    if len(token) < 5:
        return token
    for suffix in (
        "ами", "ями", "иями", "ого", "его", "ому", "ему", "ыми", "ими",
        "ый", "ий", "ой", "ей", "ая", "яя", "ые", "ие", "ов", "ев", "ам", "ям", "ах", "ях",
        "ую", "юю", "ом", "ем", "ах", "их", "ых", "у", "ю", "а", "я", "ы", "и", "е", "о",
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def search_tokens(text: str) -> list[str]:
    return [stem(token) for token in tokenize(text)]


def name_key(name: str) -> str:
    """Ключ для склейки одного и того же человека с разных страниц."""
    return fold(re.sub(r"[^\w\s-]", " ", name))
