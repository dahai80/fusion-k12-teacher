import copy
import hashlib
import json
import logging
import os

from ..safety.salt_provider import get_salt_provider
from .models import AnonymizeResult, DesensitizeConfig

logger = logging.getLogger(__name__)

_SALT_ENV = "FUSION_K12_SALT"
# A4: salt file path can uniformly point to a shared mount across nodes (env override), not per-node local random.
_SALT_FILE_ENV = "FUSION_K12_SALT_FILE"
_SALT_FILE = os.environ.get(_SALT_FILE_ENV, os.path.expanduser("~/.fusion-k12/salt"))


def _hash_id(name: str, salt: str, prefix: str) -> str:
    # SEC-3: truncated 8 hex (32bit) -> 16 hex (64bit), reduces collisions and brute force
    digest = hashlib.sha256(f"{salt}:{name}".encode()).hexdigest()
    return f"{prefix}{digest[:16]}"


def _mask_phone(value: str, salt: str, mask_char: str) -> str:
    # SEC-16: last 4 digits are often unique in small schools, re-identifiable; switched to full-value keyed hash, no plaintext bits kept
    digest = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
    return f"PH{digest[:10]}"


def _mask_email(value: str, salt: str, mask_char: str) -> str:
    # SEC-4: email uses keyed hash (with salt), consistent with name/id path, no domain leak
    digest = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
    return f"{mask_char * 3}@{digest[:8]}.invalid"


def _mask_id_number(value: str, salt: str, mask_char: str) -> str:
    # SEC-21: full-length HMAC without truncation — ID card structure is strong (region 6 + birth 8 + order 3 + check 1),
    # truncating to 10 hex (40bit) is enumerable after a salt leak; full 256bit rules out enumeration.
    digest = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
    return f"ID{digest}"


def _mask_generic(value: str, mask_char: str) -> str:
    # SEC-3: no length preserved, fixed mask length
    if not value:
        return value
    return mask_char * 8


class DataAnonymizer:
    # A5: deanonymization map persistence path env override — multi-node points to shared mount, so the map survives process restarts.
    _MAP_FILE_ENV = "FUSION_K12_NAME_MAP_FILE"
    _DEFAULT_MAP_FILE = os.path.expanduser("~/.fusion-k12/name_map.json")

    def __init__(
        self,
        config: DesensitizeConfig | None = None,
        map_file: str | None = None,
    ):
        self.config = config or DesensitizeConfig()
        # M1-T7: salt source abstracted as SaltProvider, replacing the inline _resolve_salt.
        self._salt_provider = get_salt_provider(self.config.salt)
        self.salt = self._salt_provider.get_salt()
        self._name_map: dict[str, str] = {}
        self._reverse_map: dict[str, str] = {}
        # A5: deanonymization map persistence file — persisted only with an explicit map_file or env (reversible scenario).
        # Not written to disk by default: upload/one-way desensitization (R6) does not pollute home dir;
        # pass a path or set the env explicitly when persistence is needed.
        self._map_file = map_file or os.environ.get(self._MAP_FILE_ENV) or None

    def _load_map(self) -> None:
        # A5: load the persisted map on startup/before deanonymization, so it survives restarts.
        # The map holds bidirectional name->ID entries; the file must be 0600-protected and kept apart from desensitized data.
        if not self._map_file:
            return
        try:
            with open(self._map_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # name_map: {name\x00seq: id}, reverse_map: {id: name}
                nm = data.get("name_map", {})
                rv = data.get("reverse_map", {})
                if isinstance(nm, dict) and isinstance(rv, dict):
                    self._name_map.update(nm)
                    self._reverse_map.update(rv)
                    logger.info("loaded deanonymization map: %d entries", len(rv))
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("failed to load deanonymization map: %s", exc)

    def _save_map(self) -> None:
        # A5: atomic write of the deanonymization map (tmp+os.replace), 0600 permission, lifecycle bound to the desensitized data.
        if not self._map_file:
            return
        try:
            os.makedirs(os.path.dirname(self._map_file), exist_ok=True)
            tmp = self._map_file + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    {"name_map": self._name_map, "reverse_map": self._reverse_map},
                    f, ensure_ascii=False,
                )
            os.replace(tmp, self._map_file)
        except OSError as exc:
            logger.warning("failed to persist deanonymization map: %s", exc)

    def anonymize_name(self, name: str, seq: str = "") -> str:
        # SEC-15: when seq (record index) is given, the key includes it so same-name records in different
        # positions get different IDs, avoiding cross-merging; without seq (standalone call) behavior is unchanged.
        # The map key uses (name, seq) to guarantee reversibility.
        map_key = f"{name}\x00{seq}" if seq else name
        if map_key in self._name_map:
            return self._name_map[map_key]
        if self.config.name_mode == "mask":
            # SEC-6: mask mode is irreversible, not entered into the map, avoiding same-length mask overwrite cross-merging
            return self.config.mask_char * len(name) or self.config.mask_char
        anon_id = _hash_id(f"{name}:{seq}" if seq else name, self.salt, self.config.id_prefix)
        self._name_map[map_key] = anon_id
        self._reverse_map[anon_id] = name
        # A5: persist on every new mapping, preventing map loss on process restart.
        self._save_map()
        # SEC-1: never log the original name, return the masked ID only
        return anon_id

    def deanonymize_name(self, anon_id: str) -> str:
        # A5: lazily load the persisted map before deanonymization — even a fresh process instance can restore historical IDs.
        # SEC-20: unknown ID returns the original value with a warning — the caller learns the deanonymization is incomplete.
        if not self._reverse_map:
            self._load_map()
        if anon_id in self._reverse_map:
            return self._reverse_map[anon_id]
        logger.warning("deanonymize unknown ID, mapping missing (map may have been lost): %s", anon_id)
        return anon_id

    def mask_field(self, value: str, field_name: str = "") -> str:
        # SEC-5: non-string PII (int phone numbers etc.) converted to str before masking, no longer passed through as-is
        if value is None:
            return value
        if not isinstance(value, str):
            value = str(value)
        if not value:
            return value
        mc = self.config.mask_char
        if field_name == "phone":
            return _mask_phone(value, self.salt, mc)
        if field_name == "email":
            return _mask_email(value, self.salt, mc)
        if field_name == "id_number":
            return _mask_id_number(value, self.salt, mc)
        return _mask_generic(value, mc)

    def anonymize_record(self, record: dict, seq: str = "") -> dict:
        result = copy.deepcopy(record)
        masked_fields = []
        for field_name in self.config.fields_to_mask:
            if field_name not in result:
                continue
            val = result[field_name]
            if field_name in ("student_name", "name"):
                if val is not None:
                    result[field_name] = self.anonymize_name(str(val), seq)
                    masked_fields.append(field_name)
            else:
                if val is not None:
                    result[field_name] = self.mask_field(val, field_name)
                    masked_fields.append(field_name)
        return result

    def anonymize_records(self, records: list[dict]) -> AnonymizeResult:
        # SECb-A2: return the desensitized records directly, so callers skip a second pass over export_desensitized
        anonymized = []
        masked_fields = set()
        for idx, rec in enumerate(records):
            # SEC-15: pass a per-record index, so same-name records in different positions get different IDs, avoiding grade/attendance merging
            anon_rec = self.anonymize_record(rec, seq=str(idx))
            anonymized.append(anon_rec)
            for f in self.config.fields_to_mask:
                if f in rec:
                    masked_fields.add(f)
        logger.info(
            "anonymize_records: %d -> %d records", len(records), len(anonymized)
        )
        # SEC-18: the deanonymization map never travels with results, only via explicit get_name_map(); results carry counts/masked fields only
        return AnonymizeResult(
            original_count=len(records),
            anonymized_count=len(anonymized),
            masked_fields=sorted(masked_fields),
            records=anonymized,
        )

    def deanonymize_record(self, record: dict) -> dict:
        result = copy.deepcopy(record)
        for field_name in ("student_name", "name"):
            if field_name in result and isinstance(result[field_name], str):
                result[field_name] = self.deanonymize_name(result[field_name])
        return result

    def export_desensitized(self, records: list[dict], reversible: bool = False) -> list[dict]:
        # SEC-15: same as anonymize_records, pass an index to avoid same-name record merging
        # SEC-19: one-way desensitization (reversible=False) does not keep the map in memory by default
        out = [self.anonymize_record(rec, seq=str(idx)) for idx, rec in enumerate(records)]
        if not reversible:
            logger.info("export_desensitized: one-way mode, clearing the in-memory deanonymization map")
            self.reset()
        return out

    def get_name_map(self, name: str = "") -> dict[str, str]:
        # P2: by default still returns everything (backward compatible) with a loud warning; passing name
        # returns a single entry only, avoiding exposing the whole deanonymization table at once.
        if name:
            anon = self._name_map.get(name)
            return {name: anon} if anon else {}
        logger.warning("get_name_map called — returns the reversible mapping table, keep it safe, never store it alongside desensitized data")
        return dict(self._name_map)

    def reset(self):
        self._name_map.clear()
        self._reverse_map.clear()
