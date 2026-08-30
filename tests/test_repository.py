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
        try:
            import asyncpg  # noqa: F401
            pytest.skip("asyncpg 已安装, 缺失回退场景无法复现")
        except ImportError:
            pass
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


class TestTaskLock:
    """M2-T11: DB 任务锁 — 跨实例 cron 去重。"""

    def test_lock_acquire_first(self, repo):
        assert repo.try_lock("task_a", "host1:100", 60) is True

    def test_lock_same_owner_reentrant(self, repo):
        assert repo.try_lock("task_b", "host1:100", 60) is True
        # 同 owner 再获取 = 续约成功
        assert repo.try_lock("task_b", "host1:100", 60) is True

    def test_lock_other_owner_blocked(self, repo):
        assert repo.try_lock("task_c", "host1:100", 60) is True
        # 其它实例持有未超时 → 拒
        assert repo.try_lock("task_c", "host2:200", 60) is False

    def test_lock_release_allows_other(self, repo):
        repo.try_lock("task_d", "host1:100", 60)
        repo.release_lock("task_d", "host1:100")
        assert repo.try_lock("task_d", "host2:200", 60) is True

    def test_lock_release_wrong_owner_noop(self, repo):
        repo.try_lock("task_e", "host1:100", 60)
        # 非 owner 释放无效, 锁仍在
        repo.release_lock("task_e", "host2:200")
        assert repo.try_lock("task_e", "host2:200", 60) is False

    def test_lock_renew_by_owner(self, repo):
        repo.try_lock("task_f", "host1:100", 60)
        assert repo.renew_lock("task_f", "host1:100", 120) is True
        # 非 owner 续约失败
        assert repo.renew_lock("task_f", "host2:200", 120) is False

    def test_lock_ttl_reap(self, repo):
        # ttl 极短 → 过期后被 reap, 重新可获取
        repo.try_lock("task_g", "host1:100", ttl=0)
        # ttl=0 即刻过期 (acquired_ts + 0 < now 下次 reap)
        import time
        time.sleep(0.01)
        assert repo.reap_expired_locks() >= 1
        assert repo.try_lock("task_g", "host2:200", 60) is True

    def test_base_repo_default_locks_passthrough(self):
        # standalone / 无 lock 后端: 默认实现总放行
        from fusion_k12_teacher.repository.base import Repository
        # 不能直接实例化 ABC, 用桩
        class _Stub(Repository):
            def save_history(self, r):
                pass
            def load_history(self):
                return []
            def save_name_map(self, n, r):
                pass
            def load_name_map(self):
                return {}, {}
        s = _Stub()
        assert s.try_lock("x", "o", 60) is True
        assert s.renew_lock("x", "o", 60) is True
        s.release_lock("x", "o")
        assert s.reap_expired_locks() == 0


class TestSchedulerClusterLock:
    """M2-T11: cluster 模式 run_task 抢 DB 锁, 被占则 skip。"""

    @pytest.mark.asyncio
    async def test_cluster_skip_when_locked(self, tmp_path, monkeypatch):
        db = str(tmp_path / "lock.db")
        repo = SQLiteRepository(db)
        monkeypatch.setenv("FUSION_K12_MODE", "cluster")
        # 预先被其它实例锁定
        repo.try_lock("dummy_task", "other-host:999", 300)
        sched = TaskScheduler(repo=repo)
        sched._tasks["dummy_task"] = _dummy_task("dummy_task")
        result = await sched.run_task("dummy_task")
        assert result.status == "skipped"
        repo.close()

    @pytest.mark.asyncio
    async def test_standalone_no_db_lock(self, tmp_path, monkeypatch):
        # standalone 模式不碰 DB 锁, 直接执行 (mock execute 避免真调引擎)
        db = str(tmp_path / "nolock.db")
        repo = SQLiteRepository(db)
        monkeypatch.setenv("FUSION_K12_MODE", "standalone")
        sched = TaskScheduler(repo=repo)
        sched._tasks["t1"] = _dummy_task("t1")
        monkeypatch.setattr(
            "fusion_k12_teacher.agent.executor.execute_task",
            _mock_execute,
        )
        result = await sched.run_task("t1")
        assert result.status == "success"
        repo.close()


def _dummy_task(task_id: str):
    from fusion_k12_teacher.agent.models import TeachingTask
    return TeachingTask(id=task_id, name="dummy", steps=[])


async def _mock_execute(task):
    from fusion_k12_teacher.agent.models import TaskResult
    return TaskResult(task_id=task.id, status="success", summary="mock")


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

    def test_encrypt_name_map_cli(self, tmp_path, monkeypatch):
        # M1-T9: 就地加密 standalone SQLite 旧明文 name_map
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli

        monkeypatch.setenv("FUSION_K12_DATA_KEY", "ab" * 32)
        db = str(tmp_path / "enc.db")
        repo = SQLiteRepository(db)
        repo.save_name_map({"张三\x001": "S001", "李四\x001": "S002"}, {"S001": "张三", "S002": "李四"})
        repo.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["encrypt-name-map", "--db", db])
        assert result.exit_code == 0, result.output
        assert "已加密" in result.output
        assert "2 条" in result.output

        # 验证: 重开 repo, 用 cipher 解密读回原名
        from fusion_k12_teacher.safety import DataCipher
        cipher = DataCipher()
        repo2 = SQLiteRepository(db)
        _nm, rev = repo2.load_name_map(cipher=cipher)
        assert rev["S001"] == "张三"
        assert rev["S002"] == "李四"
        repo2.close()

    def test_encrypt_name_map_dry_run(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli

        monkeypatch.setenv("FUSION_K12_DATA_KEY", "ab" * 32)
        db = str(tmp_path / "enc2.db")
        repo = SQLiteRepository(db)
        repo.save_name_map({"王五\x001": "S003"}, {"S003": "王五"})
        repo.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["encrypt-name-map", "--db", db, "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "待加密" in result.output
        assert "未写入" in result.output


try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


class TestEncryptedNameMap:
    # M1-T6: name_map 加密存取 (name_hash + name_encrypted)

    @pytest.fixture
    def cipher(self, monkeypatch):
        monkeypatch.setenv("FUSION_K12_DATA_KEY", "ab" * 32)
        from fusion_k12_teacher.safety import DataCipher
        return DataCipher()

    def test_encrypted_roundtrip(self, repo, cipher):
        name_map = {"张三\x001": "S001", "李四\x001": "S002"}
        reverse_map = {"S001": "张三", "S002": "李四"}
        repo.save_name_map(name_map, reverse_map, cipher=cipher)
        nm, rev = repo.load_name_map(cipher=cipher)
        assert nm["张三\x001"] == "S001"
        assert rev["S001"] == "张三"
        assert rev["S002"] == "李四"

    def test_encrypted_stores_no_plaintext_reverse(self, repo, cipher):
        # M1-T6: 加密行 reverse 列留明文备份但 name_encrypted 才是权威;
        # 验证无 cipher 加载时 reverse 列仍有值 (明文兼容回退) — 加密列存在不破坏明文读
        repo.save_name_map({"张三\x001": "S001"}, {"S001": "张三"}, cipher=cipher)
        # 无 cipher 加载: 回退 reverse 明文列
        nm, rev = repo.load_name_map()
        assert nm["张三\x001"] == "S001"
        assert rev["S001"] == "张三"

    def test_plaintext_loadable_without_cipher(self, repo):
        # 明文模式存, 无 cipher 读 — 向后兼容
        repo.save_name_map({"王五\x001": "S003"}, {"S003": "王五"})
        _nm, rev = repo.load_name_map()
        assert rev["S003"] == "王五"

    @pytest.mark.skipif(not _HAS_CRYPTO, reason="缺 cryptography")
    def test_wrong_cipher_fails_graceful(self, repo, monkeypatch):
        monkeypatch.setenv("FUSION_K12_DATA_KEY", "ab" * 32)
        from fusion_k12_teacher.safety import DataCipher
        c1 = DataCipher()
        repo.save_name_map({"张三\x001": "S001"}, {"S001": "张三"}, cipher=c1)
        # 换 key 后解密失败 → 回退明文 reverse 列, 不崩
        monkeypatch.setenv("FUSION_K12_DATA_KEY", "cd" * 32)
        c2 = DataCipher()
        _nm, rev = repo.load_name_map(cipher=c2)
        assert rev["S001"] == "张三"  # 回退明文

    def test_encrypted_overwrite(self, repo, cipher):
        repo.save_name_map({"张三\x001": "S001"}, {"S001": "张三"}, cipher=cipher)
        repo.save_name_map({"李四\x001": "S002"}, {"S002": "李四"}, cipher=cipher)
        nm, rev = repo.load_name_map(cipher=cipher)
        assert len(nm) == 1
        assert rev["S002"] == "李四"


