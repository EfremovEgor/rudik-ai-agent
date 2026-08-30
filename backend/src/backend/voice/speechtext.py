"""Подготовка текста к синтезу речи.

Синтезаторы читают сырой текст ответа буквально: «РУДН» превращается в невнятный
набор звуков, а «204» одни движки читают по-своему, другие вовсе падают. Поэтому
текст нормализуем до синтеза — правила общие для всех бэкендов и переживают
смену движка.
"""

from __future__ import annotations

import re

# Ссылки и служебные символы не озвучиваем.
_URL = re.compile(r"https?://\S+")
_MARKUP = re.compile(r"[*_`#>|]+")
_SPACES = re.compile(r"\s+")

# Как произносятся знакомые сокращения. Пополняется по мере того, как в ответах
# всплывают новые: незнакомое сокращение читается по буквам, а это звучит хуже.
ABBREVIATIONS = {
    "РУДН": "Рудээн",
    "ЕГЭ": "Егэ",
    "ОГЭ": "Огэ",
    "ГИА": "Гиа",
    "ВУЗ": "вуз",
    "СПО": "эс пэ о",
    "ФИО": "эф и о",
    "ИТ": "ай ти",
}

# Названия букв для сокращений, которых нет в словаре.
_LETTERS = {
    "А": "а",
    "Б": "бэ",
    "В": "вэ",
    "Г": "гэ",
    "Д": "дэ",
    "Е": "е",
    "Ё": "ё",
    "Ж": "жэ",
    "З": "зэ",
    "И": "и",
    "Й": "й",
    "К": "ка",
    "Л": "эль",
    "М": "эм",
    "Н": "эн",
    "О": "о",
    "П": "пэ",
    "Р": "эр",
    "С": "эс",
    "Т": "тэ",
    "У": "у",
    "Ф": "эф",
    "Х": "ха",
    "Ц": "цэ",
    "Ч": "че",
    "Ш": "ша",
    "Щ": "ща",
    "Ы": "ы",
    "Э": "э",
    "Ю": "ю",
    "Я": "я",
}

# Сокращение — два и больше заглавных подряд. Одиночная заглавная это просто
# начало предложения или инициал.
_ABBR = re.compile(r"\b[А-ЯЁ]{2,}\b")
_NUMBER = re.compile(r"\d+")

MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
# Дата требует порядкового числительного в родительном: «пятнадцатого сентября»,
# «две тысячи двадцать шестого года». Ловим число прямо перед месяцем или годом.
_DATE_NUMBER = re.compile(
    r"\b(\d{1,4})(?=\s+(?P<tail>" + "|".join(MONTHS) + r"|года|году)\b)",
    re.IGNORECASE,
)

# Длинные последовательности цифр — это телефон или год выпуска в ссылке,
# читать их одним числом бессмысленно.
MAX_SPOKEN_DIGITS = 4


def expand_abbreviations(text: str) -> str:
    """Заменяет сокращения на то, как они читаются вслух."""

    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        known = ABBREVIATIONS.get(word)
        if known:
            return known
        return " ".join(_LETTERS.get(letter, letter) for letter in word)

    return _ABBR.sub(replace, text)


# Окончания порядковых по падежам: «пятнадцатого сентября», но «в шестом году».
_ORDINAL_ENDINGS = {
    "genitive": (("ий", "ьего"), ("ый", "ого"), ("ой", "ого")),
    "prepositional": (("ий", "ьем"), ("ый", "ом"), ("ой", "ом")),
}


def _decline_ordinal(ordinal: str, case: str) -> str:
    """Склоняет порядковое: num2words этого не умеет, а без падежа дата корявая."""
    for ending, replacement in _ORDINAL_ENDINGS[case]:
        if ordinal.endswith(ending):
            return ordinal[: -len(ending)] + replacement
    return ordinal


def expand_numbers(text: str) -> str:
    """Пишет числа словами: не все движки читают цифры, а vosk на них падает."""
    try:
        from num2words import num2words
    except ImportError:  # pragma: no cover — ставится вместе с голосом
        return text

    def replace_date(match: re.Match[str]) -> str:
        try:
            ordinal = num2words(int(match.group(1)), lang="ru", to="ordinal")
        except (ValueError, NotImplementedError):
            return match.group(1)
        # «в две тысячи двадцать шестом году», но «двадцать шестого года».
        case = "prepositional" if match.group("tail").lower() == "году" else "genitive"
        return _decline_ordinal(ordinal, case)

    text = _DATE_NUMBER.sub(replace_date, text)

    def replace(match: re.Match[str]) -> str:
        digits = match.group(0)
        if len(digits) > MAX_SPOKEN_DIGITS:
            # Телефон или подобное — по цифре, иначе выйдет «сто миллиардов».
            return " ".join(_digit_word(d) for d in digits)
        try:
            return num2words(int(digits), lang="ru")
        except (ValueError, NotImplementedError):
            return digits

    return _NUMBER.sub(replace, text)


def _digit_word(digit: str) -> str:
    from num2words import num2words

    return num2words(int(digit), lang="ru")


def clean_for_speech(text: str) -> str:
    """Готовит текст ответа к синтезу: без ссылок, разметки и сокращений."""
    text = _URL.sub("", text)
    text = text.replace("//", " ")
    text = _MARKUP.sub(" ", text)
    text = text.replace("—", "-").replace("№", "номер ")
    text = expand_abbreviations(text)
    text = expand_numbers(text)
    return _SPACES.sub(" ", text).strip()
