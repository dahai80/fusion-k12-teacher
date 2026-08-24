import hashlib

from fusion_k12_teacher.desensitize import AnonymizeResult, DataAnonymizer, DesensitizeConfig


def _expected_id(name: str, salt: str = "fusion-k12", prefix: str = "S") -> str:
    digest = hashlib.sha256(f"{salt}:{name}".encode()).hexdigest()
    return f"{prefix}{digest[:8]}"


class TestDesensitizeConfig:
    def test_defaults(self):
        cfg = DesensitizeConfig()
        assert cfg.name_mode == "id"
        assert cfg.id_prefix == "S"
        assert cfg.mask_char == "*"
        assert cfg.salt == "fusion-k12"
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
        anon = DataAnonymizer()
        expected = _expected_id("张三")
        assert anon.anonymize_name("张三") == expected
        assert anon.anonymize_name("张三") == expected

    def test_anonymize_name_id_mode_unique(self):
        anon = DataAnonymizer()
        a1 = anon.anonymize_name("张三")
        a2 = anon.anonymize_name("李四")
        assert a1 != a2
        assert a1.startswith("S")
        assert a2.startswith("S")

    def test_anonymize_name_cross_instance_stable(self):
        anon1 = DataAnonymizer()
        anon2 = DataAnonymizer()
        assert anon1.anonymize_name("张三") == anon2.anonymize_name("张三")

    def test_anonymize_name_mask_mode_full_mask(self):
        cfg = DesensitizeConfig(name_mode="mask")
        anon = DataAnonymizer(cfg)
        result = anon.anonymize_name("张三")
        assert result == "**"

    def test_anonymize_name_mask_mode_short(self):
        cfg = DesensitizeConfig(name_mode="mask")
        anon = DataAnonymizer(cfg)
        assert anon.anonymize_name("王") == "*"

    def test_deanonymize_name(self):
        anon = DataAnonymizer()
        anon_id = anon.anonymize_name("张三")
        assert anon.deanonymize_name(anon_id) == "张三"
        assert anon.deanonymize_name("UNKNOWN") == "UNKNOWN"

    def test_mask_field_phone(self):
        anon = DataAnonymizer()
        # SEC-3: 不保留长度, 固定掩码 + 末 4 位
        assert anon.mask_field("13812345678", "phone") == "****5678"
        assert anon.mask_field("1234", "phone") == "********"

    def test_mask_field_email(self):
        anon = DataAnonymizer()
        # SEC-3: 不泄露域名, 哈希成不可逆伪邮箱
        masked = anon.mask_field("student@school.edu.cn", "email")
        assert masked.startswith("***@")
        assert masked.endswith(".invalid")

    def test_mask_field_id_number(self):
        anon = DataAnonymizer()
        masked = anon.mask_field("110101199001011234", "id_number")
        assert masked.startswith("ID")
        assert len(masked) == 12

    def test_mask_field_generic(self):
        anon = DataAnonymizer()
        # SEC-3: 固定 8 位掩码, 不保留长度
        assert anon.mask_field("某地址", "address") == "********"

    def test_mask_field_empty(self):
        anon = DataAnonymizer()
        assert anon.mask_field("", "phone") == ""
        assert anon.mask_field(123, "phone") == 123

    def test_anonymize_record(self):
        anon = DataAnonymizer()
        record = {
            "student_name": "张三",
            "phone": "13812345678",
            "score": 85,
        }
        result = anon.anonymize_record(record)
        assert result["student_name"] == _expected_id("张三")
        assert result["phone"] == "****5678"
        assert result["score"] == 85

    def test_anonymize_record_preserves_original(self):
        anon = DataAnonymizer()
        record = {"name": "张三"}
        result = anon.anonymize_record(record)
        assert record["name"] == "张三"
        assert result["name"] == _expected_id("张三")

    def test_anonymize_records(self):
        anon = DataAnonymizer()
        records = [
            {"student_name": "张三", "score": 85},
            {"student_name": "李四", "score": 90},
        ]
        result = anon.anonymize_records(records)
        assert result.original_count == 2
        assert result.anonymized_count == 2
        assert "张三" in result.name_map
        assert "李四" in result.name_map

    def test_deanonymize_record(self):
        anon = DataAnonymizer()
        anon_id = anon.anonymize_name("张三")
        record = {"name": anon_id, "score": 85}
        result = anon.deanonymize_record(record)
        assert result["name"] == "张三"
        assert result["score"] == 85

    def test_export_desensitized(self):
        anon = DataAnonymizer()
        records = [
            {"student_name": "张三", "phone": "13812345678"},
            {"student_name": "李四", "phone": "13987654321"},
        ]
        result = anon.export_desensitized(records)
        assert result[0]["student_name"] == _expected_id("张三")
        assert result[1]["student_name"] == _expected_id("李四")
        assert result[0]["phone"] == "****5678"
        assert result[1]["phone"] == "****4321"

    def test_get_name_map(self):
        anon = DataAnonymizer()
        anon.anonymize_name("张三")
        anon.anonymize_name("李四")
        m = anon.get_name_map()
        assert m == {"张三": _expected_id("张三"), "李四": _expected_id("李四")}

    def test_reset(self):
        anon = DataAnonymizer()
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
