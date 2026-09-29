from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TeacherProfile:
    id: str = ""
    username: str = ""
    name: str = ""
    school: str = ""
    region: str = ""
    default_edition: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "school": self.school,
            "region": self.region,
            "default_edition": self.default_edition,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeacherProfile:
        return cls(
            id=data.get("id", ""),
            username=data.get("username", ""),
            name=data.get("name", ""),
            school=data.get("school", ""),
            region=data.get("region", ""),
            default_edition=data.get("default_edition", ""),
            created_at=data.get("created_at", ""),
        )
