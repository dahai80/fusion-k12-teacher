import json
import pytest
from fusion_k12_teacher.desensitize import DataAnonymizer, DesensitizeConfig, AnonymizeResult


class TestDesensitizeConfig:
    def test_defaults(self):
        cfg = DesensitizeConfig()
        assert cfg.name_mode == "id"
        assert cfg.id_prefix == "S"
        assert cfg.mask_char == "*"
        assert cfg.mask_keep_chars == 1
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

    def test_to_dict_from_dict(self):
        r = AnonymizeResult(
            original_count=3, anonymized_count=3,
            name_map={"张三": "S001"}, masked_fields=["name"]
        )
        d = r.to_dict()
        r2 = AnonymizeResult.from_dict(d)
        assert r2.name_map == {"张三": "S001"}
        assert r2.masked_fields == ["name"]


class TestDataAnonymizer:
    def test_anonymize_name_id_mode(self):
        anon = DataAnonymizer()
        assert anon.anonymize_name("张三") == "S001"
        assert anon.anonymize_name("李四") == "S002"
        assert anon.anonymize_name("张三") == "S001"

    def test_anonymize_name_mask_mode(self):
        cfg = DesensitizeConfig(name_mode="mask", mask_keep_chars=1)
        anon = DataAnonymizer(cfg)
        result = anon.anonymize_name("张三")
        assert result == "张*"

    def test_anonymize_name_mask_short(self):
        cfg = DesensitizeConfig(name_mode="mask", mask_keep_chars=1)
        anon = DataAnonymizer(cfg)
        result = anon.anonymize_name("王")
        assert result == "*"

    def test_deanonymize_name(self):
        anon = DataAnonymizer()
        anon.anonymize_name("张三")
        assert anon.deanonymize_name("S001") == "张三"
        assert anon.deanonymize_name("UNKNOWN") == "UNKNOWN"

    def test_mask_field(self):
        anon = DataAnonymizer()
        assert anon.mask_field("13812345678") == "1**********"
        assert anon.mask_field("a") == "*"

    def test_mask_field_empty(self):
        anon = DataAnonymizer()
        assert anon.mask_field("") == ""
        assert anon.mask_field(123) == 123

    def test_anonymize_record(self):
        anon = DataAnonymizer()
        record = {
            "student_name": "张三",
            "phone": "13812345678",
            "score": 85,
        }
        result = anon.anonymize_record(record)
        assert result["student_name"] == "S001"
        assert result["phone"] == "1**********"
        assert result["score"] == 85

    def test_anonymize_record_preserves_original(self):
        anon = DataAnonymizer()
        record = {"name": "张三"}
        result = anon.anonymize_record(record)
        assert record["name"] == "张三"
        assert result["name"] == "S001"

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
        anon.anonymize_name("张三")
        record = {"name": "S001", "score": 85}
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
        assert result[0]["student_name"] == "S001"
        assert result[1]["student_name"] == "S002"
        assert result[0]["phone"] == "1**********"

    def test_get_name_map(self):
        anon = DataAnonymizer()
        anon.anonymize_name("张三")
        anon.anonymize_name("李四")
        m = anon.get_name_map()
        assert m == {"张三": "S001", "李四": "S002"}

    def test_reset(self):
        anon = DataAnonymizer()
        anon.anonymize_name("张三")
        anon.reset()
        assert anon.get_name_map() == {}
        assert anon.anonymize_name("张三") == "S001"

    def test_custom_prefix(self):
        cfg = DesensitizeConfig(id_prefix="T", id_counter_start=10)
        anon = DataAnonymizer(cfg)
        assert anon.anonymize_name("张三") == "T010"
        assert anon.anonymize_name("李四") == "T011"
