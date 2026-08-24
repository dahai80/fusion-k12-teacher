import copy
import hashlib
import logging

from .models import AnonymizeResult, DesensitizeConfig

logger = logging.getLogger(__name__)


def _hash_id(name: str, salt: str, prefix: str) -> str:
    digest = hashlib.sha256(f"{salt}:{name}".encode()).hexdigest()
    return f"{prefix}{digest[:8]}"


def _mask_phone(value: str, mask_char: str) -> str:
    # SEC-3: 不保留长度, 仅留末 4 位 + 固定掩码, 避免位数泄露
    digits = "".join(c for c in value if c.isdigit())
    if len(digits) <= 4:
        return mask_char * 8
    return mask_char * 4 + digits[-4:]


def _mask_email(value: str, mask_char: str) -> str:
    # SEC-3: 不泄露域名, 整体哈希成不可逆伪邮箱
    digest = hashlib.sha256(value.encode()).hexdigest()
    return f"{mask_char * 3}@{digest[:8]}.invalid"


def _mask_id_number(value: str, salt: str, mask_char: str) -> str:
    digest = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
    return f"ID{digest[:10]}"


def _mask_generic(value: str, mask_char: str) -> str:
    # SEC-3: 不保留长度, 固定掩码长度
    if not value:
        return value
    return mask_char * 8


class DataAnonymizer:
    def __init__(self, config: DesensitizeConfig | None = None):
        self.config = config or DesensitizeConfig()
        self._name_map: dict[str, str] = {}
        self._reverse_map: dict[str, str] = {}

    def anonymize_name(self, name: str) -> str:
        if name in self._name_map:
            return self._name_map[name]
        if self.config.name_mode == "mask":
            anon_id = self.config.mask_char * len(name)
            if not anon_id:
                anon_id = self.config.mask_char
        else:
            anon_id = _hash_id(name, self.config.salt, self.config.id_prefix)
        self._name_map[name] = anon_id
        self._reverse_map[anon_id] = name
        logger.info("anonymize_name: %s -> %s", name, anon_id)
        return anon_id

    def deanonymize_name(self, anon_id: str) -> str:
        return self._reverse_map.get(anon_id, anon_id)

    def mask_field(self, value: str, field_name: str = "") -> str:
        if not isinstance(value, str) or not value:
            return value
        mc = self.config.mask_char
        if field_name == "phone":
            return _mask_phone(value, mc)
        if field_name == "email":
            return _mask_email(value, mc)
        if field_name == "id_number":
            return _mask_id_number(value, self.config.salt, mc)
        return _mask_generic(value, mc)

    def anonymize_record(self, record: dict) -> dict:
        result = copy.deepcopy(record)
        masked_fields = []
        for field_name in self.config.fields_to_mask:
            if field_name not in result:
                continue
            val = result[field_name]
            if field_name in ("student_name", "name"):
                if isinstance(val, str):
                    result[field_name] = self.anonymize_name(val)
                    masked_fields.append(field_name)
            else:
                if isinstance(val, str):
                    result[field_name] = self.mask_field(val, field_name)
                    masked_fields.append(field_name)
        return result

    def anonymize_records(self, records: list[dict]) -> AnonymizeResult:
        # SECb-A2: 直接返脱敏 records, 避免调用方二次遍历 export_desensitized
        anonymized = []
        masked_fields = set()
        for rec in records:
            anon_rec = self.anonymize_record(rec)
            anonymized.append(anon_rec)
            for f in self.config.fields_to_mask:
                if f in rec:
                    masked_fields.add(f)
        logger.info(
            "anonymize_records: %d -> %d records", len(records), len(anonymized)
        )
        return AnonymizeResult(
            original_count=len(records),
            anonymized_count=len(anonymized),
            name_map=dict(self._name_map),
            masked_fields=sorted(masked_fields),
            records=anonymized,
        )

    def deanonymize_record(self, record: dict) -> dict:
        result = copy.deepcopy(record)
        for field_name in ("student_name", "name"):
            if field_name in result and isinstance(result[field_name], str):
                result[field_name] = self.deanonymize_name(result[field_name])
        return result

    def export_desensitized(self, records: list[dict]) -> list[dict]:
        return [self.anonymize_record(rec) for rec in records]

    def get_name_map(self) -> dict[str, str]:
        logger.warning("get_name_map 被调用 — 返回可逆映射表，注意保管，勿随脱敏数据一并存储")
        return dict(self._name_map)

    def reset(self):
        self._name_map.clear()
        self._reverse_map.clear()
