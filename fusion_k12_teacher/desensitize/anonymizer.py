import copy
import hashlib
import json
import logging
import os
import secrets

from .models import AnonymizeResult, DesensitizeConfig

logger = logging.getLogger(__name__)

_SALT_ENV = "FUSION_K12_SALT"
# A4: salt 文件路径可跨节点统一指向共享挂载点 (env 覆盖), 非每节点本地随机。
_SALT_FILE_ENV = "FUSION_K12_SALT_FILE"
_SALT_FILE = os.environ.get(_SALT_FILE_ENV, os.path.expanduser("~/.fusion-k12/salt"))


def _resolve_salt(explicit: str) -> str:
    # A4: salt 必须跨节点统一分发 — 显式 > 环境变量 > 共享 0600 密钥文件。
    # 末位随机回退仅单机可用, 多节点部署会致同一学生跨节点得不同 ID (PII 断链)。
    # 回退时显式告警, 运维须据日志分发统一 salt, 不可静默每节点独立生成。
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
    # A4: 随机回退 = 单机模式, 多节点场景 PII 跨节点断链。loud warning 告知运维。
    logger.error(
        "脱敏 salt 未显式配置(FUSION_K12_SALT/FUSION_K12_SALT_FILE), "
        "回退到本节点随机 salt。多节点部署将致同一学生跨节点 ID 不一致, "
        "须分发统一 salt 文件或设环境变量。"
    )
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
    # SEC-21: 全长 HMAC 不截断 — 身份证结构强(地域6+生辰8+序3+校1),
    # 截断 10 hex(40bit) 在 salt 泄露后可枚举; 全长 256bit 杜绝枚举。
    digest = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
    return f"ID{digest}"


def _mask_generic(value: str, mask_char: str) -> str:
    # SEC-3: 不保留长度, 固定掩码长度
    if not value:
        return value
    return mask_char * 8


class DataAnonymizer:
    # A5: 反匿名表持久化路径 env 覆盖 — 多节点指向共享挂载, 反匿名不随进程重启丢失。
    _MAP_FILE_ENV = "FUSION_K12_NAME_MAP_FILE"
    _DEFAULT_MAP_FILE = os.path.expanduser("~/.fusion-k12/name_map.json")

    def __init__(
        self,
        config: DesensitizeConfig | None = None,
        map_file: str | None = None,
    ):
        self.config = config or DesensitizeConfig()
        self.salt = _resolve_salt(self.config.salt)
        self._name_map: dict[str, str] = {}
        self._reverse_map: dict[str, str] = {}
        # A5: 反匿名表持久化文件 — 显式 map_file 或 env 设置才持久化 (可逆场景)。
        # 默认不落盘: 上传/单向脱敏 (R6) 不污染 home dir; 需反匿名持久化时显式传路径或设 env。
        self._map_file = map_file or os.environ.get(self._MAP_FILE_ENV) or None

    def _load_map(self) -> None:
        # A5: 启动/反匿名前从持久化文件加载反匿名表, 重启后仍可还原。
        # 反匿名表含 name->ID 双向, 文件须 0600 保护, 不与脱敏数据同处存放。
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
                    logger.info("加载反匿名表: %d 条", len(rv))
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("加载反匿名表失败: %s", exc)

    def _save_map(self) -> None:
        # A5: 反匿名表原子写盘 (tmp+os.replace), 0600 权限, 与脱敏数据生命周期绑定。
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
            logger.warning("持久化反匿名表失败: %s", exc)

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
        # A5: 每次新增映射即持久化, 防进程重启丢反匿名表。
        self._save_map()
        # SEC-1: 不记录原始姓名, 仅返回掩码 ID
        return anon_id

    def deanonymize_name(self, anon_id: str) -> str:
        # A5: 反匿名前懒加载持久化表 — 即使新进程实例也能还原历史脱敏 ID。
        # SEC-20: 未知 ID 返原值并告警 — 调用方知反匿名不完整。
        if not self._reverse_map:
            self._load_map()
        if anon_id in self._reverse_map:
            return self._reverse_map[anon_id]
        logger.warning("deanonymize 未知 ID, 映射缺失(可能映射已丢失): %s", anon_id)
        return anon_id

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
        # SEC-18: 反匿名表不随结果流转, 仅经 get_name_map() 显式取; 结果只返计数/掩码字段
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
        # SEC-15: 同 anonymize_records, 传序号避免同名记录合并
        # SEC-19: 单向脱敏(reversible=False)默认不在内存驻留反匿名表
        out = [self.anonymize_record(rec, seq=str(idx)) for idx, rec in enumerate(records)]
        if not reversible:
            logger.info("export_desensitized: 单向模式, 清理内存中的反匿名表")
            self.reset()
        return out

    def get_name_map(self, name: str = "") -> dict[str, str]:
        # P2: 默认仍返全量(向后兼容)但 loud warning; 传 name 则仅返单条, 避免一次性暴露整张反匿名表。
        if name:
            anon = self._name_map.get(name)
            return {name: anon} if anon else {}
        logger.warning("get_name_map 被调用 — 返回可逆映射表，注意保管，勿随脱敏数据一并存储")
        return dict(self._name_map)

    def reset(self):
        self._name_map.clear()
        self._reverse_map.clear()
