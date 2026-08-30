"""Repository 层测试 — M1-T1。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.agent.models import TaskResult
from fusion_k12_teacher.agent.scheduler import TaskScheduler
from fusion_k12_teacher.repository import SQLiteRepository, get_repository


@pytest.fixture
def repo(tmp_path):
    db = str(tmp_path / "k12.db")
    r = SQLiteRepository(db)
    yield r
    r.close()


class TestSQLiteRepository:
    def test_history_roundtrip(self, repo):
        records = [
            {"task_id": "weekly_prep", "status": "success", "ts": "2026-08-30T10:00"},
            {"task_id": "daily_homework_review", "status": "error", "ts": "2026-08-30T11:00"},
        ]
        repo.save_history(records)
        loaded = repo.load_history()
        assert len(loaded) == 2
        assert loaded[0]["task_id"] == "weekly_prep"
        assert loaded[1]["status"] == "error"

    def test_history_overwrite(self, repo):
        repo.save_history([{"task_id": "a", "ts": "1"}])
        repo.save_history([{"task_id": "b", "ts": "2"}])
        loaded = repo.load_history()
        assert len(loaded) == 1
        assert loaded[0]["task_id"] == "b"

    def test_name_map_roundtrip(self, repo):
        name_map = {"张三\x001": "S001", "李四\x001": "S002"}
        reverse_map = {"S001": "张三", "S002": "李四"}
        repo.save_name_map(name_map, reverse_map)
        nm, _rev = repo.load_name_map()
        assert nm["张三\x001"] == "S001"
        assert _rev["S002"] == "李四"

    def test_name_map_overwrite(self, repo):
        repo.save_name_map({"张三\x001": "S001"}, {"S001": "张三"})
        repo.save_name_map({"李四\x001": "S002"}, {"S002": "李四"})
        nm, _rev = repo.load_name_map()
        assert len(nm) == 1
        assert "张三\x001" not in nm

    def test_health(self, repo):
        assert repo.health() is True

    def test_empty_load(self, repo):
        assert repo.load_history() == []
        nm, rev = repo.load_name_map()
        assert nm == {} and rev == {}


class TestFactory:
    def test_get_repository_standalone(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FUSION_K12_MODE", "standalone")
        monkeypatch.setenv("FUSION_K12_REPO_DB", str(tmp_path / "f.db"))
        r = get_repository()
        assert isinstance(r, SQLiteRepository)
        assert r.health() is True
        r.close()

    def test_get_repository_cluster_fallback(self, tmp_path, monkeypatch):
        # M1-T2: cluster 模式 DSN 未配 → 回退 SQLite
        monkeypatch.setenv("FUSION_K12_MODE", "cluster")
        monkeypatch.delenv("FUSION_K12_PG_DSN", raising=False)
        monkeypatch.setenv("FUSION_K12_REPO_DB", str(tmp_path / "c.db"))
        r = get_repository()
        assert isinstance(r, SQLiteRepository)
        r.close()

    def test_get_repository_cluster_dsn_no_asyncpg(self, tmp_path, monkeypatch):
        # M1-T2: cluster 模式配了 DSN 但 asyncpg 缺失 → 回退 SQLite
        monkeypatch.setenv("FUSION_K12_MODE", "cluster")
        monkeypatch.setenv("FUSION_K12_PG_DSN", "postgresql://u:p@localhost/db")
        monkeypatch.setenv("FUSION_K12_REPO_DB", str(tmp_path / "c2.db"))
        # asyncpg 未安装 (CI 无 cluster extras), 工厂应捕获回退不崩
        r = get_repository()
        assert isinstance(r, SQLiteRepository)
        r.close()

    def test_postgres_repo_missing_asyncpg(self):
        # M1-T2: asyncpg 缺失时 PostgresRepository 构造抛 ImportError (清晰错误)
        try:
            import asyncpg  # noqa: F401
            pytest.skip("asyncpg 已安装, 跳过缺失场景")
        except ImportError:
            from fusion_k12_teacher.repository import PostgresRepository
            with pytest.raises(ImportError, match="asyncpg"):
                PostgresRepository("postgresql://u:p@localhost/db")


class TestSchedulerRepoIntegration:
    def test_scheduler_history_via_repo(self, tmp_path):
        db = str(tmp_path / "sched.db")
        repo = SQLiteRepository(db)
        sched = TaskScheduler(repo=repo)
        # 构造 TaskResult 写历史
        result = TaskResult(task_id="weekly_prep", status="success", summary="ok")
        sched._history.append(result)
        sched._save_history()
        # 新 scheduler 实例从同一 repo 加载, 验证跨实例持久化
        sched2 = TaskScheduler(repo=repo)
        sched2.load_history()
        assert len(sched2._history) == 1
        assert sched2._history[0].task_id == "weekly_prep"
        repo.close()


class TestMigrateCLI:
    def test_migrate_dry_run(self, tmp_path):
        # M1-T3: dry-run 仅读源库预览, 不连 Postgres
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli

        db = str(tmp_path / "src.db")
        repo = SQLiteRepository(db)
        repo.save_history([{"task_id": "t1", "ts": "1"}, {"task_id": "t2", "ts": "2"}])
        repo.save_name_map({"张三\x001": "S001"}, {"S001": "张三"})
        repo.close()

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["migrate", "--from-db", db, "--to-dsn", "postgresql://u:p@localhost/db", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert "历史 2 条" in result.output
        assert "脱敏映射 1 条" in result.output
        assert "未写入" in result.output

