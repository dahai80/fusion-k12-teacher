import hashlib

from fusion_k12_teacher.desensitize import AnonymizeResult, DataAnonymizer, DesensitizeConfig

# Explicit test salt — keeps tests hermetic, no dependency on the ~/.fusion-k12/salt file
_TEST_SALT = "k12-test-salt"


def _expected_id(name: str, salt: str = _TEST_SALT, prefix: str = "S", seq: str = "") -> str:
    # SEC-3: truncated to 16 hex (64bit), consistent with anonymizer._hash_id
    # SEC-15: with seq, the key includes the sequence number, consistent with anonymizer.anonymize_name(seq=)
    key = f"{name}:{seq}" if seq else name
    digest = hashlib.sha256(f"{salt}:{key}".encode()).hexdigest()
    return f"{prefix}{digest[:16]}"


def _expected_phone(value: str, salt: str = _TEST_SALT) -> str:
    # SEC-16: phone uses a full-value keyed hash, no plaintext digits kept
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
        # SEC-2: no more hardcoded default salt
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
        # SEC-17: salt never enters serialization
        assert "salt" not in d
        cfg2 = DesensitizeConfig.from_dict(d)
        assert cfg2.name_mode == "mask"
        assert cfg2.id_prefix == "X"


# i18n: user-facing (fixture data below uses Chinese sample names)
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


# i18n: user-facing (fixture data below uses Chinese sample names/addresses)
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
        # SEC-16: phone uses a full-value keyed hash, last 4 digits not kept, no re-identification
        assert anon.mask_field("13812345678", "phone") == _expected_phone("13812345678")
        assert anon.mask_field("1234", "phone") == _expected_phone("1234")
        assert anon.mask_field("13812345678", "phone").startswith("PH")

    def test_mask_field_email(self):
        anon = _anon()
        # SEC-3: domain never leaked, hashed into an irreversible pseudo-email
        masked = anon.mask_field("student@school.edu.cn", "email")
        assert masked.startswith("***@")
        assert masked.endswith(".invalid")

    def test_mask_field_id_number(self):
        anon = _anon()
        masked = anon.mask_field("110101199001011234", "id_number")
        # SEC-21: full-length HMAC, no truncation — ID + 64 hex = 66, prevents enumeration after a salt leak.
        assert masked.startswith("ID")
        assert len(masked) == 66

    def test_mask_field_generic(self):
        anon = _anon()
        # SEC-3: fixed 8-char mask, length not preserved
        assert anon.mask_field("某地址", "address") == "********"

    def test_mask_field_empty(self):
        anon = _anon()
        assert anon.mask_field("", "phone") == ""

    def test_mask_field_non_string_phone(self):
        # SEC-5: non-string PII (int phone number) is converted to str before masking, no longer passes through raw
        # SEC-16: keyed hash path
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
        # Single record has no seq, ID stays _expected_id("张三"); phone uses the SEC-16 keyed hash
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
        # SEC-18: the reverse-anonymization map never travels with results, fetch explicitly via get_name_map()
        # SEC-15: mapping keys include the sequence number (name\x00seq), same-name records stay distinguishable
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
        # SEC-15: each record passes a sequence number, same-name records get different IDs
        assert result[0]["student_name"] == _expected_id("张三", seq="0")
        assert result[1]["student_name"] == _expected_id("李四", seq="1")
        # SEC-16: phone uses a full-value keyed hash
        assert result[0]["phone"] == _expected_phone("13812345678")
        assert result[1]["phone"] == _expected_phone("13987654321")

    def test_same_name_different_seq_unique(self):
        # SEC-15: same-name records with different sequence numbers get different IDs, avoiding score/attendance merging
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
