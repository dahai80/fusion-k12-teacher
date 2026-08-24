"""安全模块测试 — models / wordlist / age_checker / filter。"""

import logging
import os
import tempfile

from fusion_k12_teacher.safety.age_checker import AgeChecker
from fusion_k12_teacher.safety.filter import ContentFilter
from fusion_k12_teacher.safety.models import AgeRating, ContentCheckResult, FilterLevel
from fusion_k12_teacher.safety.wordlist import SensitiveWordList

# ─── Models ────────────────────────────────────────────


class TestContentCheckResult:
    def test_default_safe(self):
        r = ContentCheckResult()
        assert r.is_safe is True
        assert r.risk_level == "safe"
        assert r.flagged_words == []

    def test_to_dict_from_dict(self):
        r = ContentCheckResult(is_safe=False, risk_level="high", flagged_words=["暴力"], summary="不安全")
        d = r.to_dict()
        r2 = ContentCheckResult.from_dict(d)
        assert r2.is_safe is False
        assert r2.flagged_words == ["暴力"]

    def test_to_dict_no_llm_issues(self):
        r = ContentCheckResult(flagged_words=["暴力"])
        d = r.to_dict()
        assert "llm_issues" not in d


class TestAgeRating:
    def test_to_dict(self):
        ar = AgeRating(grade="3", max_abstraction="concrete", restricted_topics=["暴力"])
        d = ar.to_dict()
        assert d["grade"] == "3"
        assert d["restricted_topics"] == ["暴力"]


class TestFilterLevel:
    def test_default(self):
        fl = FilterLevel()
        assert fl.sensitive_words is True
        assert fl.age_check is True
        assert fl.output_check is True
        assert not hasattr(fl, "llm_review")


# ─── Wordlist ──────────────────────────────────────────


class TestSensitiveWordList:
    def test_load_default(self):
        wl = SensitiveWordList()
        assert wl.count > 0

    def test_add_and_check(self):
        wl = SensitiveWordList()
        wl.add("测试敏感词xyz")
        assert "测试敏感词xyz" in wl.list_words()
        hits = wl.check("这里包含测试敏感词xyz的内容")
        assert "测试敏感词xyz" in hits

    def test_remove(self):
        wl = SensitiveWordList()
        wl.add("临时词abc")
        wl.remove("临时词abc")
        assert "临时词abc" not in wl.list_words()

    def test_check_case_insensitive(self):
        wl = SensitiveWordList()
        wl.add("badword")
        assert len(wl.check("BADWORD here")) > 0

    def test_check_clean_text(self):
        wl = SensitiveWordList()
        hits = wl.check("这是一段正常的教学内容")
        assert hits == []

    def test_check_bypass_whitespace(self):
        wl = SensitiveWordList()
        wl.add("暴力")
        assert "暴力" in wl.check("这里暴 力描写")

    def test_check_bypass_zero_width(self):
        wl = SensitiveWordList()
        wl.add("暴力")
        assert "暴力" in wl.check("这里暴​力描写")

    def test_check_bypass_punctuation(self):
        wl = SensitiveWordList()
        wl.add("杀人")
        assert "杀人" in wl.check("这里杀-人描写")

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "words.txt")
            wl = SensitiveWordList()
            wl.add("自定义词")
            wl._path = path
            wl.save()

            wl2 = SensitiveWordList(path=path)
            assert "自定义词" in wl2.list_words()


# ─── AgeChecker ────────────────────────────────────────


class TestAgeChecker:
    def test_load_default(self):
        ac = AgeChecker()
        rating = ac.get_rating("3")
        assert rating.max_abstraction == "concrete"
        assert "暴力" in rating.restricted_topics

    def test_check_content_restricted(self):
        ac = AgeChecker()
        issues = ac.check_content("这段内容包含暴力描写", "2")
        assert len(issues) > 0
        assert any("暴力" in i for i in issues)

    def test_check_content_bypass_whitespace(self):
        ac = AgeChecker()
        issues = ac.check_content("这段内容包含暴 力描写", "2")
        assert len(issues) > 0

    def test_check_content_clean(self):
        ac = AgeChecker()
        issues = ac.check_content("今天我们学习加法", "2")
        assert issues == []

    def test_check_abstraction_ok(self):
        ac = AgeChecker()
        issues = ac.check_abstraction("concrete", "3")
        assert issues == []

    def test_check_abstraction_exceeded(self):
        ac = AgeChecker()
        issues = ac.check_abstraction("abstract", "2")
        assert len(issues) > 0

    def test_high_school_rating(self):
        ac = AgeChecker()
        rating = ac.get_rating("9")
        assert rating.max_abstraction == "abstract"

    def test_invalid_grade_warns(self, caplog):
        ac = AgeChecker()
        with caplog.at_level(logging.WARNING, logger="fusion_k12_teacher.safety.age_checker"):
            rating = ac.get_rating("幼儿园")
        assert rating.max_abstraction == "concrete"
        assert any("非法年级" in r.message for r in caplog.records)

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ratings.json")
            ac = AgeChecker()
            ac._path = path
            ac.save()

            ac2 = AgeChecker(ratings_path=path)
            assert ac2.get_rating("3").max_abstraction == "concrete"


# ─── ContentFilter ─────────────────────────────────────


class TestContentFilter:
    def test_check_text_safe(self):
        cf = ContentFilter()
        result = cf.check_text("今天学习分数加减法", "3")
        assert result.is_safe is True
        assert result.risk_level == "safe"

    def test_check_text_sensitive(self):
        cf = ContentFilter()
        result = cf.check_text("这段内容包含暴力描写", "3")
        assert result.is_safe is False
        assert result.risk_level == "high"
        assert len(result.flagged_words) > 0

    def test_check_text_age_issue(self):
        wl = SensitiveWordList()
        ac = AgeChecker()
        cf = ContentFilter(wordlist=wl, age_checker=ac)
        result = cf.check_text("这段内容包含恐怖情节", "2")
        assert result.is_safe is False
        assert len(result.age_issues) > 0

    def test_check_text_sensitive_plus_age_keeps_high(self):
        wl = SensitiveWordList()
        wl.add("暴力")
        ac = AgeChecker()
        fl = FilterLevel(sensitive_words=True, age_check=True, output_check=False)
        cf = ContentFilter(wordlist=wl, age_checker=ac, filter_level=fl)
        result = cf.check_text("暴 力恐怖情节", "2")
        assert result.is_safe is False
        assert result.risk_level == "high"

    def test_filter_sensitive(self):
        cf = ContentFilter()
        filtered = cf.filter_sensitive("这里有暴力内容需要过滤")
        assert "暴力" not in filtered
        assert "**" in filtered

    def test_filter_sensitive_bypass_whitespace(self):
        cf = ContentFilter()
        filtered = cf.filter_sensitive("这里有暴 力内容")
        assert "暴" not in filtered.replace("*", "")
        assert "*" in filtered

    def test_filter_sensitive_clean(self):
        cf = ContentFilter()
        text = "正常教学内容不需要过滤"
        assert cf.filter_sensitive(text) == text

    def test_check_output(self):
        cf = ContentFilter()
        result = cf.check_output("包含色情的内容", "5")
        assert result.is_safe is False

    def test_safety_prompt_suffix(self):
        cf = ContentFilter()
        suffix = cf.get_safety_prompt_suffix()
        assert "K-12" in suffix

    def test_no_llm_review_method(self):
        cf = ContentFilter()
        assert not hasattr(cf, "llm_review")

    def test_disabled_sensitive_check(self):
        fl = FilterLevel(sensitive_words=False, age_check=False, output_check=False)
        cf = ContentFilter(filter_level=fl)
        result = cf.check_text("包含暴力的内容", "2")
        assert result.is_safe is True
