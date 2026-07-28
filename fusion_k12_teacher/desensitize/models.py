import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DesensitizeConfig:
    name_mode: str = "id"
    id_prefix: str = "S"
    fields_to_mask: List[str] = field(default_factory=lambda: [
        "student_name", "name", "phone", "email", "address", "id_number"
    ])
    mask_char: str = "*"
    mask_keep_chars: int = 1
    id_counter_start: int = 1

    def to_dict(self) -> Dict:
        return {
            "name_mode": self.name_mode,
            "id_prefix": self.id_prefix,
            "fields_to_mask": self.fields_to_mask,
            "mask_char": self.mask_char,
            "mask_keep_chars": self.mask_keep_chars,
            "id_counter_start": self.id_counter_start,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "DesensitizeConfig":
        return cls(
            name_mode=data.get("name_mode", "id"),
            id_prefix=data.get("id_prefix", "S"),
            fields_to_mask=data.get("fields_to_mask", [
                "student_name", "name", "phone", "email", "address", "id_number"
            ]),
            mask_char=data.get("mask_char", "*"),
            mask_keep_chars=data.get("mask_keep_chars", 1),
            id_counter_start=data.get("id_counter_start", 1),
        )


@dataclass
class AnonymizeResult:
    original_count: int
    anonymized_count: int
    name_map: Dict[str, str] = field(default_factory=dict)
    masked_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "original_count": self.original_count,
            "anonymized_count": self.anonymized_count,
            "name_map": self.name_map,
            "masked_fields": self.masked_fields,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "AnonymizeResult":
        return cls(
            original_count=data.get("original_count", 0),
            anonymized_count=data.get("anonymized_count", 0),
            name_map=data.get("name_map", {}),
            masked_fields=data.get("masked_fields", []),
        )
