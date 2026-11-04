"""Departments a message can be routed to: the single source of truth for target addresses."""

from enum import StrEnum


class Department(StrEnum):
    """A target department. The agent picks one of these; it never sees raw addresses."""

    PERSONNEL = "kadry"
    HUMAN_RESOURCES = "human_resources"
    HELP_DESK = "help_desk"
    IT = "it"
    OTHER = "other"

    @property
    def address(self) -> str:
        return _ADDRESSES[self]


_ADDRESSES: dict[Department, str] = {
    Department.PERSONNEL: "kadry@example.com",
    Department.HUMAN_RESOURCES: "human-resources@example.com",
    Department.HELP_DESK: "help-desk@example.com",
    Department.IT: "it@example.com",
    Department.OTHER: "other@example.com",
}

FALLBACK_DEPARTMENT = Department.OTHER
