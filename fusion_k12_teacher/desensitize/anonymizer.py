import copy
import logging

from .models import AnonymizeResult, DesensitizeConfig

logger = logging.getLogger(__name__)


class DataAnonymizer:
    def __init__(self, config: DesensitizeConfig | None = None):
        self.config = config or DesensitizeConfig()
        self._name_map: dict[str, str] = {}
        self._reverse_map: dict[str, str] = {}
        self._id_counter = self.config.id_counter_start

    def anonymize_name(self, name: str) -> str:
        if name in self._name_map:
            return self._name_map[name]
        if self.config.name_mode == "id":
            anon_id = f"{self.config.id_prefix}{self._id_counter:03d}"
            self._id_counter += 1
        elif self.config.name_mode == "mask":
            if len(name) <= self.config.mask_keep_chars:
                anon_id = self.config.mask_char * len(name)
            else:
                keep = name[:self.config.mask_keep_chars]
                anon_id = keep + self.config.mask_char * (len(name) - self.config.mask_keep_chars)
        else:
            anon_id = f"{self.config.id_prefix}{self._id_counter:03d}"
            self._id_counter += 1
        self._name_map[name] = anon_id
        self._reverse_map[anon_id] = name
        logger.info("anonymize_name: %s -> %s", name, anon_id)
        return anon_id

    def deanonymize_name(self, anon_id: str) -> str:
        return self._reverse_map.get(anon_id, anon_id)

    def mask_field(self, value: str) -> str:
        if not isinstance(value, str) or not value:
            return value
        k = self.config.mask_keep_chars
        if len(value) <= k:
            return self.config.mask_char * len(value)
        return value[:k] + self.config.mask_char * (len(value) - k)

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
                    result[field_name] = self.mask_field(val)
                    masked_fields.append(field_name)
        return result

    def anonymize_records(self, records: list[dict]) -> AnonymizeResult:
        anonymized = []
        masked_fields = []
        for rec in records:
            anon_rec = self.anonymize_record(rec)
            anonymized.append(anon_rec)
        if self._name_map:
            masked_fields = list(set(
                f for rec in records for f in self.config.fields_to_mask
                if f in rec
            ))
        logger.info("anonymize_records: %d -> %d records", len(records), len(anonymized))
        return AnonymizeResult(
            original_count=len(records),
            anonymized_count=len(anonymized),
            name_map=dict(self._name_map),
            masked_fields=masked_fields,
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
        return dict(self._name_map)

    def reset(self):
        self._name_map.clear()
        self._reverse_map.clear()
        self._id_counter = self.config.id_counter_start
