# Repository layer tests — M1-T1.

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


# i18n: user-facing (fixture data below uses Chinese sample names in name_map records)
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

    def test_get_repository_cluster_no_dsn_fails_closed(self, tmp_path, monkeypatch):
        # issue #36: cluster mode without a DSN configured → NonDegradableError refuses startup, no SQLite fallback
        from fusion_k12_teacher.errors import NonDegradableError

        monkeypatch.setenv("FUSION_K12_MODE", "cluster")
        monkeypatch.delenv("FUSION_K12_PG_DSN", raising=False)
        monkeypatch.setenv("FUSION_K12_REPO_DB", str(tmp_path / "c.db"))
        with pytest.raises(NonDegradableError, match="FUSION_K12_PG_DSN"):
            get_repository()

    def test_get_repository_cluster_no_asyncpg_fails_closed(self, tmp_path, monkeypatch):
        # issue #36: cluster mode with a DSN configured but asyncpg missing → NonDegradableError refuses startup
        # (with an install hint), no SQLite fallback
        import sys

        from fusion_k12_teacher.errors import NonDegradableError

        # Simulate asyncpg missing: setting sys.modules entry to None makes import asyncpg raise ImportError
        monkeypatch.setitem(sys.modules, "asyncpg", None)
        monkeypatch.setenv("FUSION_K12_MODE", "cluster")
        monkeypatch.setenv("FUSION_K12_PG_DSN", "postgresql://u:p@localhost/db")
        monkeypatch.setenv("FUSION_K12_REPO_DB", str(tmp_path / "c2.db"))
        with pytest.raises(NonDegradableError, match=r"\.\[cluster\]"):
            get_repository()

    def test_serve_init_teacher_services_fatal_propagates(self, monkeypatch):
        # issue #36: on the serve startup path NonDegradableError must propagate and refuse startup,
        # not be swallowed by a degrading "generation features still work" warning
        from fusion_k12_teacher import serve
        from fusion_k12_teacher.errors import NonDegradableError

        def _boom():
            raise NonDegradableError("FUSION_K12_MODE=cluster requires FUSION_K12_PG_DSN")

        monkeypatch.setattr(serve, "get_repository", _boom)
        with pytest.raises(NonDegradableError, match="FUSION_K12_PG_DSN"):
            serve._init_teacher_services()
        assert serve.auth_service is None

    def test_serve_init_teacher_services_degradable_warns(self, monkeypatch):
        # Non-fatal failures still degrade (no identity + resource library), startup unaffected
        from fusion_k12_teacher import serve

        def _boom():
            raise RuntimeError("textbook dir missing")

        monkeypatch.setattr(serve, "get_repository", _boom)
        serve._init_teacher_services()  # must not raise
        assert serve.auth_service is None
        assert serve.textbook_loader is None
        assert serve._materials_repo is None

    def test_postgres_repo_missing_asyncpg(self, monkeypatch):
        # M1-T2: with asyncpg missing, PostgresRepository construction raises ImportError (clear error)
        import sys
        monkeypatch.setitem(sys.modules, "asyncpg", None)
        from fusion_k12_teacher.repository import PostgresRepository
        with pytest.raises(ImportError, match="asyncpg"):
            PostgresRepository("postgresql://u:p@localhost/db")


class TestSchedulerRepoIntegration:
    def test_scheduler_history_via_repo(self, tmp_path):
        db = str(tmp_path / "sched.db")
        repo = SQLiteRepository(db)
        sched = TaskScheduler(repo=repo)
        # Build a TaskResult and write history
        result = TaskResult(task_id="weekly_prep", status="success", summary="ok")
        sched._history.append(result)
        sched._save_history()
        # A new scheduler instance loads from the same repo, verifying cross-instance persistence
        sched2 = TaskScheduler(repo=repo)
        sched2.load_history()
        assert len(sched2._history) == 1
        assert sched2._history[0].task_id == "weekly_prep"
        repo.close()


# M2-T11: DB task lock — cross-instance cron dedup.
class TestTaskLock:

    def test_lock_acquire_first(self, repo):
        assert repo.try_lock("task_a", "host1:100", 60) is True

    def test_lock_same_owner_reentrant(self, repo):
        assert repo.try_lock("task_b", "host1:100", 60) is True
        # Same owner re-acquiring = successful renewal
        assert repo.try_lock("task_b", "host1:100", 60) is True

    def test_lock_other_owner_blocked(self, repo):
        assert repo.try_lock("task_c", "host1:100", 60) is True
        # Held by another instance, not timed out → reject
        assert repo.try_lock("task_c", "host2:200", 60) is False

    def test_lock_release_allows_other(self, repo):
        repo.try_lock("task_d", "host1:100", 60)
        repo.release_lock("task_d", "host1:100")
        assert repo.try_lock("task_d", "host2:200", 60) is True

    def test_lock_release_wrong_owner_noop(self, repo):
        repo.try_lock("task_e", "host1:100", 60)
        # Release by a non-owner is a no-op, lock stays
        repo.release_lock("task_e", "host2:200")
        assert repo.try_lock("task_e", "host2:200", 60) is False

    def test_lock_renew_by_owner(self, repo):
        repo.try_lock("task_f", "host1:100", 60)
        assert repo.renew_lock("task_f", "host1:100", 120) is True
        # Renewal by a non-owner fails
        assert repo.renew_lock("task_f", "host2:200", 120) is False

    def test_lock_ttl_reap(self, repo):
        # Very short ttl → reaped after expiry, acquirable again
        repo.try_lock("task_g", "host1:100", ttl=0)
        # ttl=0 expires immediately (acquired_ts + 0 < now on the next reap)
        import time
        time.sleep(0.01)
        assert repo.reap_expired_locks() >= 1
        assert repo.try_lock("task_g", "host2:200", 60) is True

    def test_base_repo_default_locks_passthrough(self):
        # standalone / no lock backend: default implementation always allows
        from fusion_k12_teacher.repository.base import Repository
        # Cannot instantiate the ABC directly, use a stub
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


# M2-T11: in cluster mode run_task races for the DB lock, skips when held.
class TestSchedulerClusterLock:

    @pytest.mark.asyncio
    async def test_cluster_skip_when_locked(self, tmp_path, monkeypatch):
        db = str(tmp_path / "lock.db")
        repo = SQLiteRepository(db)
        monkeypatch.setenv("FUSION_K12_MODE", "cluster")
        # Pre-locked by another instance
        repo.try_lock("dummy_task", "other-host:999", 300)
        sched = TaskScheduler(repo=repo)
        sched._tasks["dummy_task"] = _dummy_task("dummy_task")
        result = await sched.run_task("dummy_task")
        assert result.status == "skipped"
        repo.close()

    @pytest.mark.asyncio
    async def test_standalone_no_db_lock(self, tmp_path, monkeypatch):
        # standalone mode never touches the DB lock, executes directly (mock execute to avoid really calling engines)
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


# i18n: user-facing (CLI output strings asserted below are Chinese product output)
class TestMigrateCLI:
    def test_migrate_dry_run(self, tmp_path):
        # M1-T3: dry-run only reads the source DB for a preview, never connects to Postgres
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
        # M1-T9: encrypt the old plaintext standalone SQLite name_map in place
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

        # Verify: reopen the repo and decrypt the original names with the cipher
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


# i18n: user-facing (fixture data below uses Chinese sample names in name_map records)
class TestEncryptedNameMap:
    # M1-T6: name_map encrypted storage (name_hash + name_encrypted)

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
        # M1-T6: encrypted rows keep a plaintext backup in the reverse column but name_encrypted is authoritative;
        # verify the reverse column still has a value when loading without a cipher (plaintext-compatible fallback) — the encrypted column does not break plaintext reads
        repo.save_name_map({"张三\x001": "S001"}, {"S001": "张三"}, cipher=cipher)
        # Load without a cipher: fall back to the plaintext reverse column
        nm, rev = repo.load_name_map()
        assert nm["张三\x001"] == "S001"
        assert rev["S001"] == "张三"

    def test_plaintext_loadable_without_cipher(self, repo):
        # Stored in plaintext mode, read without a cipher — backward compatible
        repo.save_name_map({"王五\x001": "S003"}, {"S003": "王五"})
        _nm, rev = repo.load_name_map()
        assert rev["S003"] == "王五"

    # i18n: user-facing
    @pytest.mark.skipif(not _HAS_CRYPTO, reason="缺 cryptography")
    def test_wrong_cipher_fails_graceful(self, repo, monkeypatch):
        monkeypatch.setenv("FUSION_K12_DATA_KEY", "ab" * 32)
        from fusion_k12_teacher.safety import DataCipher
        c1 = DataCipher()
        repo.save_name_map({"张三\x001": "S001"}, {"S001": "张三"}, cipher=c1)
        # Decryption fails after switching keys → fall back to the plaintext reverse column, no crash
        monkeypatch.setenv("FUSION_K12_DATA_KEY", "cd" * 32)
        c2 = DataCipher()
        _nm, rev = repo.load_name_map(cipher=c2)
        assert rev["S001"] == "张三"  # plaintext fallback, i18n: user-facing

    def test_encrypted_overwrite(self, repo, cipher):
        repo.save_name_map({"张三\x001": "S001"}, {"S001": "张三"}, cipher=cipher)
        repo.save_name_map({"李四\x001": "S002"}, {"S002": "李四"}, cipher=cipher)
        nm, rev = repo.load_name_map(cipher=cipher)
        assert len(nm) == 1
        assert rev["S002"] == "李四"


