"""materials 资源库测试 — 保存/列表/详情/删除。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.repository.sqlite_repo import SQLiteRepository


@pytest.fixture
def repo(tmp_path):
    r = SQLiteRepository(str(tmp_path / "mat.db"))
    yield r
    r.close()


def _make_material(teacher_id: str, mtype: str = "lesson_plan", title: str = "测试教案", mid: str = "mat_test1") -> dict:
    return {
        "id": mid,
        "teacher_id": teacher_id,
        "edition": "renjiao",
        "subject": "数学",
        "grade": "3",
        "lesson_id": "7-1",
        "unit_title": "分数的初步认识",
        "lesson_title": "认识几分之一",
        "type": mtype,
        "title": title,
        "payload": '{"title": "测试"}',
        "created_at": "2026-09-24 10:00:00",
    }


class TestSaveMaterial:
    def test_save_and_get(self, repo):
        m = _make_material("t_a")
        rid = repo.save_material(m)
        assert rid == "mat_test1"
        got = repo.get_material("mat_test1")
        assert got is not None
        assert got["title"] == "测试教案"
        assert got["teacher_id"] == "t_a"

    def test_list_by_teacher(self, repo):
        repo.save_material(_make_material("t_a", title="A1", mid="m1"))
        repo.save_material(_make_material("t_a", title="A2", mtype="quiz", mid="m2"))
        repo.save_material(_make_material("t_b", title="B1", mid="m3"))
        items = repo.list_materials("t_a")
        assert len(items) == 2
        assert all(i["teacher_id"] == "t_a" for i in items)

    def test_list_filter_type(self, repo):
        repo.save_material(_make_material("t_a", title="p1", mtype="lesson_plan", mid="m1"))
        repo.save_material(_make_material("t_a", title="q1", mtype="quiz", mid="m2"))
        items = repo.list_materials("t_a", type="quiz")
        assert len(items) == 1
        assert items[0]["type"] == "quiz"

    def test_list_filter_subject(self, repo):
        repo.save_material(_make_material("t_a", title="m1", mid="m1"))
        m2 = _make_material("t_a", title="y1", mid="m2")
        m2["subject"] = "语文"
        repo.save_material(m2)
        items = repo.list_materials("t_a", subject="数学")
        assert len(items) == 1
        assert items[0]["subject"] == "数学"


class TestDeleteMaterial:
    def test_delete_by_owner(self, repo):
        repo.save_material(_make_material("t_a", mid="m1"))
        assert repo.delete_material("m1", "t_a") is True
        assert repo.get_material("m1") is None

    def test_delete_by_non_owner(self, repo):
        repo.save_material(_make_material("t_a", mid="m1"))
        assert repo.delete_material("m1", "t_b") is False
        assert repo.get_material("m1") is not None

    def test_delete_unknown(self, repo):
        assert repo.delete_material("ghost", "t_a") is False


class TestPurgeMaterials:
    """issue #17: 资源保留策略 — 按天数 + 每教师上限清理。"""

    def test_purge_by_age(self, repo):
        repo.save_material(_make_material("t_a", mid="old1", title="旧"))
        old = _make_material("t_a", mid="old2", title="更旧")
        old["created_at"] = "2020-01-01 00:00:00"
        repo.save_material(old)
        deleted = repo.purge_old_materials(before_ts="2025-01-01 00:00:00")
        assert deleted == 1
        assert repo.get_material("old2") is None
        assert repo.get_material("old1") is not None

    def test_purge_by_max_per_teacher(self, repo):
        for i in range(10):
            repo.save_material(_make_material("t_a", mid=f"m{i:02d}"))
        deleted = repo.purge_old_materials(max_per_teacher=3)
        assert deleted == 7
        remaining = repo.list_materials("t_a", limit=100)
        assert len(remaining) == 3

    def test_purge_noop_when_under_limit(self, repo):
        repo.save_material(_make_material("t_a", mid="m1"))
        deleted = repo.purge_old_materials(max_per_teacher=500)
        assert deleted == 0

    def test_purge_multi_teacher(self, repo):
        for i in range(5):
            repo.save_material(_make_material("t_a", mid=f"a{i}"))
        for i in range(3):
            repo.save_material(_make_material("t_b", mid=f"b{i}"))
        deleted = repo.purge_old_materials(max_per_teacher=2)
        assert deleted == 4
        assert len(repo.list_materials("t_a", limit=100)) == 2
        assert len(repo.list_materials("t_b", limit=100)) == 2
