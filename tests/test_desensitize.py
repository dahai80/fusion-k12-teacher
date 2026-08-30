import hashlib

from fusion_k12_teacher.desensitize import AnonymizeResult, DataAnonymizer, DesensitizeConfig

# 测试用显式 salt — 保证 hermetic, 不依赖 ~/.fusion-k12/salt 文件
_TEST_SALT = "k12-test-salt"


def _expected_id(name: str, salt: str = _TEST_SALT, prefix: str = "S", seq: str = "") -> str:
    # SEC-3: 截断 16 hex(64bit), 与 anonymizer._hash_id 一致
    # SEC-15: 传 seq 时键含序号, 与 anonymizer.anonymize_name(seq=) 一致
    key = f"{name}:{seq}" if seq else name
    digest = hashlib.sha256(f"{salt}:{key}".encode()).hexdigest()
    return f"{prefix}{digest[:16]}"


def _expected_phone(value: str, salt: str = _TEST_SALT) -> str:
    # SEC-16: phone 全值 keyed 哈希, 不保留明文位
    digest = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
    return f"PH{digest[:10]}"


def _anon(**kw) -> DataAnonymizer:
    cfg = DesensitizeConfig(salt=_TEST_SALT, **kw)
    return DataAnonymizer(cfg)


class TestDesensitizeConfig:
    def test_defaults(self):
        cfg = DesensitizeConfig()
        assert cfg.name_mode == "id"
        assert cfg.id_prefix == "S"
        assert cfg.mask_char == "*"
        # SEC-2: 不再硬编码默认 salt
        assert cfg.salt == ""
        assert "student_name" in cfg.fields_to_mask
        assert "name" in cfg.fields_to_mask

    def test_custom(self):
        cfg = DesensitizeConfig(name_mode="mask", id_prefix="T", mask_char="#")
        assert cfg.name_mode == "mask"
        assert cfg.id_prefix == "T"
        assert cfg.mask_char == "#"

    def test_to_dict_from_dict(self):
        cfg = DesensitizeConfig(name_mode="mask", id_prefix="X")
        d = cfg.to_dict()
        # SEC-17: salt 不进序列化
        assert "salt" not in d
        cfg2 = DesensitizeConfig.from_dict(d)
        assert cfg2.name_mode == "mask"
        assert cfg2.id_prefix == "X"


class TestAnonymizeResult:
    def test_create(self):
        r = AnonymizeResult(original_count=5, anonymized_count=5)
        assert r.original_count == 5
        assert r.anonymized_count == 5
        assert r.name_map == {}

    def test_to_dict_omits_name_map_by_default(self):
        r = AnonymizeResult(
            original_count=3, anonymized_count=3,
            name_map={"张三": "S001"}, masked_fields=["name"],
        )
        d = r.to_dict()
        assert "name_map" not in d
        assert d["masked_fields"] == ["name"]

    def test_to_dict_include_map(self):
        r = AnonymizeResult(
            original_count=3, anonymized_count=3,
            name_map={"张三": "S001"},
        )
        d = r.to_dict(include_map=True)
        assert d["name_map"] == {"张三": "S001"}

    def test_from_dict_reads_name_map(self):
        r = AnonymizeResult.from_dict({
            "original_count": 2, "anonymized_count": 2,
            "name_map": {"张三": "S001"},
        })
        assert r.name_map == {"张三": "S001"}


class TestDataAnonymizer:
    def test_anonymize_name_id_mode_deterministic(self):
        anon = _anon()
        expected = _expected_id("张三")
        assert anon.anonymize_name("张三") == expected
        assert anon.anonymize_name("张三") == expected

    def test_anonymize_name_id_mode_unique(self):
        anon = _anon()
        a1 = anon.anonymize_name("张三")
        a2 = anon.anonymize_name("李四")
        assert a1 != a2
        assert a1.startswith("S")
        assert a2.startswith("S")

    def test_anonymize_name_cross_instance_stable(self):
        anon1 = _anon()
        anon2 = _anon()
        assert anon1.anonymize_name("张三") == anon2.anonymize_name("张三")

    def test_anonymize_name_mask_mode_full_mask(self):
        anon = _anon(name_mode="mask")
        result = anon.anonymize_name("张三")
        assert result == "**"

    def test_anonymize_name_mask_mode_short(self):
        anon = _anon(name_mode="mask")
        assert anon.anonymize_name("王") == "*"

    def test_deanonymize_name(self):
        anon = _anon()
        anon_id = anon.anonymize_name("张三")
        assert anon.deanonymize_name(anon_id) == "张三"
        assert anon.deanonymize_name("UNKNOWN") == "UNKNOWN"

    def test_mask_field_phone(self):
        anon = _anon()
        # SEC-16: phone 全值 keyed 哈希, 不保留末 4 位, 不可再识别
        assert anon.mask_field("13812345678", "phone") == _expected_phone("13812345678")
        assert anon.mask_field("1234", "phone") == _expected_phone("1234")
        assert anon.mask_field("13812345678", "phone").startswith("PH")

    def test_mask_field_email(self):
        anon = _anon()
        # SEC-3: 不泄露域名, 哈希成不可逆伪邮箱
        masked = anon.mask_field("student@school.edu.cn", "email")
        assert masked.startswith("***@")
        assert masked.endswith(".invalid")

    def test_mask_field_id_number(self):
        anon = _anon()
        masked = anon.mask_field("110101199001011234", "id_number")
        assert masked.startswith("ID")
        assert len(masked) == 12

    def test_mask_field_generic(self):
        anon = _anon()
        # SEC-3: 固定 8 位掩码, 不保留长度
        assert anon.mask_field("某地址", "address") == "********"

    def test_mask_field_empty(self):
        anon = _anon()
        assert anon.mask_field("", "phone") == ""

    def test_mask_field_non_string_phone(self):
        # SEC-5: 非字符串 PII(int 手机号)转 str 后脱敏, 不再原样穿透
        # SEC-16: 走 keyed 哈希
        anon = _anon()
        assert anon.mask_field(123, "phone") == _expected_phone("123")
        assert anon.mask_field(13812345678, "phone") == _expected_phone("13812345678")

    def test_anonymize_record(self):
        anon = _anon()
        record = {
            "student_name": "张三",
            "phone": "13812345678",
            "score": 85,
        }
        result = anon.anonymize_record(record)
        # 单记录无 seq, ID 保持 _expected_id("张三"); phone 走 SEC-16 keyed 哈希
        assert result["student_name"] == _expected_id("张三")
        assert result["phone"] == _expected_phone("13812345678")
        assert result["score"] == 85

    def test_anonymize_record_preserves_original(self):
        anon = _anon()
        record = {"name": "张三"}
        result = anon.anonymize_record(record)
        assert record["name"] == "张三"
        assert result["name"] == _expected_id("张三")

    def test_anonymize_records(self):
        anon = _anon()
        records = [
            {"student_name": "张三", "score": 85},
            {"student_name": "李四", "score": 90},
        ]
        result = anon.anonymize_records(records)
        assert result.original_count == 2
        assert result.anonymized_count == 2
        # SEC-18: 反匿名表不随结果流转, 经 get_name_map() 显式取
        # SEC-15: 映射键含序号 (name\x00seq), 同名不同记录可区分
        name_map = anon.get_name_map()
        assert "张三\x000" in name_map
        assert "李四\x001" in name_map
        assert name_map["张三\x000"] == _expected_id("张三", seq="0")
        assert name_map["李四\x001"] == _expected_id("李四", seq="1")

    def test_deanonymize_record(self):
        anon = _anon()
        anon_id = anon.anonymize_name("张三")
        record = {"name": anon_id, "score": 85}
        result = anon.deanonymize_record(record)
        assert result["name"] == "张三"
        assert result["score"] == 85

    def test_export_desensitized(self):
        anon = _anon()
        records = [
            {"student_name": "张三", "phone": "13812345678"},
            {"student_name": "李四", "phone": "13987654321"},
        ]
        result = anon.export_desensitized(records)
        # SEC-15: 每记录传序号, 同名不同记录不同 ID
        assert result[0]["student_name"] == _expected_id("张三", seq="0")
        assert result[1]["student_name"] == _expected_id("李四", seq="1")
        # SEC-16: phone 全值 keyed 哈希
        assert result[0]["phone"] == _expected_phone("13812345678")
        assert result[1]["phone"] == _expected_phone("13987654321")

    def test_same_name_different_seq_unique(self):
        # SEC-15: 同名不同记录序号得不同 ID, 避免成绩/考勤合并
        anon = _anon()
        records = [
            {"student_name": "张三", "score": 85},
            {"student_name": "张三", "score": 90},
        ]
        result = anon.export_desensitized(records)
        assert result[0]["student_name"] != result[1]["student_name"]

    def test_get_name_map(self):
        anon = _anon()
        anon.anonymize_name("张三")
        anon.anonymize_name("李四")
        m = anon.get_name_map()
        assert m == {"张三": _expected_id("张三"), "李四": _expected_id("李四")}

    def test_reset(self):
        anon = _anon()
        anon.anonymize_name("张三")
        anon.reset()
        assert anon.get_name_map() == {}
        assert anon.anonymize_name("张三") == _expected_id("张三")

    def test_custom_prefix_and_salt(self):
        cfg = DesensitizeConfig(id_prefix="T", salt="mysalt")
        anon = DataAnonymizer(cfg)
        expected = _expected_id("张三", salt="mysalt", prefix="T")
        assert anon.anonymize_name("张三") == expected
        assert anon.anonymize_name("张三").startswith("T")
