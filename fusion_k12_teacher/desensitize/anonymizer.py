import copy
import hashlib
import logging
import os
import secrets

from .models import AnonymizeResult, DesensitizeConfig

logger = logging.getLogger(__name__)

_SALT_ENV = "FUSION_K12_SALT"
_SALT_FILE = os.path.expanduser("~/.fusion-k12/salt")


def _resolve_salt(explicit: str) -> str:
    # SEC-2: 去硬编码 salt — 显式 > 环境变量 > 0600 密钥文件 > 首次随机生成并持久化
    if explicit:
        return explicit
    env_salt = os.environ.get(_SALT_ENV)
    if env_salt:
        return env_salt
    try:
        with open(_SALT_FILE, encoding="utf-8") as f:
            s = f.read().strip()
            if s:
                return s
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("读取 salt 文件失败: %s", exc)
    s = secrets.token_hex(16)
    try:
        os.makedirs(os.path.dirname(_SALT_FILE), exist_ok=True)
        fd = os.open(
            _SALT_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(s)
    except OSError as exc:
        logger.warning("持久化 salt 文件失败, 使用进程内随机 salt: %s", exc)
    return s


def _hash_id(name: str, salt: str, prefix: str) -> str:
    # SEC-3: 截断 8 hex(32bit)→16 hex(64bit), 降低碰撞与爆破
    digest = hashlib.sha256(f"{salt}:{name}".encode()).hexdigest()
    return f"{prefix}{digest[:16]}"


def _mask_phone(value: str, salt: str, mask_char: str) -> str:
    # SEC-16: 末 4 位在小规模学校常唯一, 可再识别; 改全值 keyed 哈希, 不保留任何明文位
    digest = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
    return f"PH{digest[:10]}"


def _mask_email(value: str, salt: str, mask_char: str) -> str:
    # SEC-4: email 走 keyed 哈希(带 salt), 与姓名/id 路径一致, 不泄露域名
    digest = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
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
        self.salt = _resolve_salt(self.config.salt)
        self._name_map: dict[str, str] = {}
        self._reverse_map: dict[str, str] = {}

    def anonymize_name(self, name: str, seq: str = "") -> str:
        # SEC-15: 传入 seq(记录序号)时键含序号, 同名不同记录得到不同 ID, 避免合并串号;
        # 不传 seq(独立调用)保持原行为。映射键用 (name, seq) 保证可逆。
        map_key = f"{name}\x00{seq}" if seq else name
        if map_key in self._name_map:
            return self._name_map[map_key]
        if self.config.name_mode == "mask":
            # SEC-6: mask 模式不可逆, 不入反匿名表, 避免同长度掩码覆写串号
            return self.config.mask_char * len(name) or self.config.mask_char
        anon_id = _hash_id(f"{name}:{seq}" if seq else name, self.salt, self.config.id_prefix)
        self._name_map[map_key] = anon_id
        self._reverse_map[anon_id] = name
        # SEC-1: 不记录原始姓名, 仅返回掩码 ID
        return anon_id

    def deanonymize_name(self, anon_id: str) -> str:
        return self._reverse_map.get(anon_id, anon_id)

    def mask_field(self, value: str, field_name: str = "") -> str:
        # SEC-5: 非字符串 PII(int 手机号等)转 str 后脱敏, 不再原样穿透
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
        # SECb-A2: 直接返脱敏 records, 避免调用方二次遍历 export_desensitized
        anonymized = []
        masked_fields = set()
        for idx, rec in enumerate(records):
            # SEC-15: 每记录传序号, 同名不同记录得到不同 ID, 避免成绩/考勤合并
            anon_rec = self.anonymize_record(rec, seq=str(idx))
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
        # SEC-15: 同 anonymize_records, 传序号避免同名记录合并
        return [self.anonymize_record(rec, seq=str(idx)) for idx, rec in enumerate(records)]

    def get_name_map(self) -> dict[str, str]:
        logger.warning("get_name_map 被调用 — 返回可逆映射表，注意保管，勿随脱敏数据一并存储")
        return dict(self._name_map)

    def reset(self):
        self._name_map.clear()
        self._reverse_map.clear()
