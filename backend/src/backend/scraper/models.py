"""Структурированные сущности, которые Рудик достаёт с сайта академии."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _clean_list(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        item = item.strip()
        if item and item not in seen:
            seen.append(item)
    return seen


@dataclass
class Person:
    name: str
    position: str = ""
    unit: str = ""
    address: str = ""
    rooms: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    profile_url: str = ""
    photo_url: str = ""
    source_url: str = ""
    # Учёная степень и звание — их спрашивают о преподавателях чаще всего.
    degree: str = ""
    academic_title: str = ""
    # Преподаваемые дисциплины из сведений об образовательной организации.
    subjects: list[str] = field(default_factory=list)
    # Откуда человек: "academy" — Инженерная академия, "university" — весь РУДН.
    # По этому признаку поиск отдаёт предпочтение своим сотрудникам.
    scope: str = "academy"

    def merge(self, other: Person) -> None:
        """Дополняет запись данными из другой карточки того же человека."""
        self.position = self.position or other.position
        self.unit = self.unit or other.unit
        self.address = self.address or other.address
        self.rooms = _clean_list(self.rooms + other.rooms)
        self.phones = _clean_list(self.phones + other.phones)
        self.emails = _clean_list(self.emails + other.emails)
        self.profile_url = self.profile_url or other.profile_url
        self.photo_url = self.photo_url or other.photo_url
        self.degree = self.degree or other.degree
        self.academic_title = self.academic_title or other.academic_title
        self.subjects = _clean_list(self.subjects + other.subjects)
        # Сотрудник академии остаётся сотрудником академии, даже если его
        # карточка нашлась ещё и в общеуниверситетском списке.
        if self.scope != "academy":
            self.scope = other.scope

    def to_text(self) -> str:
        lines = [f"{self.name}"]
        if self.position:
            lines.append(f"Должность: {self.position}")
        if self.unit:
            lines.append(f"Подразделение: {self.unit}")
        if self.degree:
            lines.append(f"Учёная степень: {self.degree}")
        if self.academic_title:
            lines.append(f"Учёное звание: {self.academic_title}")
        if self.rooms:
            lines.append(f"Кабинет: {', '.join(self.rooms)}")
        if self.address:
            lines.append(f"Адрес: {self.address}")
        if self.phones:
            lines.append(f"Телефон: {', '.join(self.phones)}")
        if self.emails:
            lines.append(f"Email: {', '.join(self.emails)}")
        if self.subjects:
            lines.append(f"Преподаёт: {'; '.join(self.subjects)}")
        return "\n".join(lines)

    def dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Department:
    name: str
    url: str = ""
    slug: str = ""
    description: str = ""
    head: str = ""
    head_position: str = ""
    contacts: list[str] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [f"Кафедра: {self.name}"]
        if self.head:
            lines.append(
                f"Заведующий: {self.head} ({self.head_position})".replace(" ()", "")
            )
        if self.description:
            lines.append(self.description)
        if self.programs:
            lines.append("Направления подготовки: " + "; ".join(self.programs))
        if self.contacts:
            lines.append("Контакты: " + "; ".join(self.contacts))
        return "\n".join(lines)

    def dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsItem:
    title: str
    url: str
    date: str = ""
    tags: list[str] = field(default_factory=list)
    body: str = ""

    def to_text(self) -> str:
        head = (
            f"Новость от {self.date}: {self.title}"
            if self.date
            else f"Новость: {self.title}"
        )
        parts = [head]
        if self.tags:
            parts.append("Теги: " + ", ".join(self.tags))
        if self.body:
            parts.append(self.body)
        return "\n".join(parts)

    def dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Program:
    title: str
    url: str = ""
    level: str = ""
    code: str = ""
    language: str = "ru"
    department: str = ""
    description: str = ""

    def to_text(self) -> str:
        head = " ".join(x for x in (self.code, self.title) if x)
        lines = [f"Направление подготовки ({self.level}): {head}"]
        if self.department:
            lines.append(f"Кафедра: {self.department}")
        if self.description:
            lines.append(self.description)
        return "\n".join(lines)

    def dict(self) -> dict[str, Any]:
        return asdict(self)
