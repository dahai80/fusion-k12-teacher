import logging
from dataclasses import dataclass, field

from .._coerce import coerce_dict, coerce_int, coerce_str, coerce_str_list

logger = logging.getLogger(__name__)

DEFAULT_MASK_FIELDS = [
    "student_name", "name", "phone", "email", "address", "id_number"
]


@dataclass
class DesensitizeConfig:
    name_mode: str = "id"
    id_prefix: str = "S"
    fields_to_mask: list[str] = field(default_factory=lambda: list(DEFAULT_MASK_FIELDS))
    mask_char: str = "*"
    mask_keep_chars: int = 1
    # SEC-2/SEC-17: 不再硬编码默认 salt; 空串由 DataAnonymizer._resolve_salt 解析
    salt: str = ""

    def to_dict(self) -> dict:
        # SEC-17: salt 不随配置序列化, 避免与脱敏数据同存导致保护失效
        return {
            "name_mode": self.name_mode,
            "id_prefix": self.id_prefix,
            "fields_to_mask": self.fields_to_mask,
            "mask_char": self.mask_char,
            "mask_keep_chars": self.mask_keep_chars,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DesensitizeConfig":
        return cls(
            name_mode=coerce_str(data.get("name_mode", "id")),
            id_prefix=coerce_str(data.get("id_prefix", "S")),
            fields_to_mask=coerce_str_list(data.get("fields_to_mask", list(DEFAULT_MASK_FIELDS))),
            mask_char=coerce_str(data.get("mask_char", "*")),
            mask_keep_chars=coerce_int(data.get("mask_keep_chars", 1), 1),
            salt=coerce_str(data.get("salt", "")),
        )


@dataclass
class AnonymizeResult:
    original_count: int
    anonymized_count: int
    name_map: dict[str, str] = field(default_factory=dict)
    masked_fields: list[str] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)

    def to_dict(self, include_map: bool = False, include_records: bool = False) -> dict:
        data = {
            "original_count": self.original_count,
            "anonymized_count": self.anonymized_count,
            "masked_fields": self.masked_fields,
        }
        if include_map:
            data["name_map"] = self.name_map
        if include_records:
            data["records"] = self.records
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "AnonymizeResult":
        return cls(
            original_count=coerce_int(data.get("original_count", 0), 0),
            anonymized_count=coerce_int(data.get("anonymized_count", 0), 0),
            name_map=coerce_dict(data.get("name_map", {})),
            masked_fields=coerce_str_list(data.get("masked_fields", [])),
            records=data.get("records", []),
        )
