# Salt rotation + versioning tests — M1-T8.

from __future__ import annotations

from fusion_k12_teacher.safety.salt_provider import VersionedSaltProvider


class TestVersionedSaltProvider:
    def test_initial_generates(self, tmp_path):
        p = VersionedSaltProvider(str(tmp_path / "salt"))
        s = p.get_salt()
        assert len(s) == 32

    def test_persist_across_instances(self, tmp_path):
        path = str(tmp_path / "salt")
        s1 = VersionedSaltProvider(path).get_salt()
        s2 = VersionedSaltProvider(path).get_salt()
        assert s1 == s2

    def test_rotate_changes_salt(self, tmp_path):
        path = str(tmp_path / "salt")
        p = VersionedSaltProvider(path)
        old = p.get_salt()
        new_ver, new = p.rotate()
        assert new != old
        assert new_ver == 2  # initial v1, new current after rotation is v2

    def test_rotate_archives_old(self, tmp_path):
        path = str(tmp_path / "salt")
        p = VersionedSaltProvider(path)
        old = p.get_salt()
        p.rotate()
        # old salt should be archived as v1
        archived = p.get_salt_for_version(1)
        assert archived == old

    def test_list_versions(self, tmp_path):
        path = str(tmp_path / "salt")
        p = VersionedSaltProvider(path)
        p.get_salt()
        p.rotate()
        p.rotate()
        versions = p.list_versions()
        vers = [v for v, _ in versions]
        assert vers == [1, 2, 3]

    def test_get_salt_for_version_missing(self, tmp_path):
        path = str(tmp_path / "salt")
        p = VersionedSaltProvider(path)
        p.get_salt()
        # missing version falls back to current
        assert p.get_salt_for_version(999) == p.get_salt()

    def test_current_version(self, tmp_path):
        path = str(tmp_path / "salt")
        p = VersionedSaltProvider(path)
        p.get_salt()
        assert p.current_version() == 1
        p.rotate()
        assert p.current_version() == 2

    def test_multiple_rotations_unique_salts(self, tmp_path):
        path = str(tmp_path / "salt")
        p = VersionedSaltProvider(path)
        salts = [p.get_salt()]
        for _ in range(3):
            _, s = p.rotate()
            salts.append(s)
        assert len(set(salts)) == 4  # all distinct


class TestRotateSaltCLI:
    def test_rotate_cli(self, tmp_path):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli

        salt_file = str(tmp_path / "salt")
        runner = CliRunner()
        result = runner.invoke(cli, ["rotate-salt", "--salt-file", salt_file])
        assert result.exit_code == 0, result.output
        # i18n: user-facing (asserts CLI output text owned by cli.py)
        assert "已轮换" in result.output
        assert "v2" in result.output  # initial v1, new current v2 after rotate
        # verify the file was written
        from fusion_k12_teacher.safety.salt_provider import VersionedSaltProvider
        assert VersionedSaltProvider(salt_file).get_salt()

    def test_show_versions_cli(self, tmp_path):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli

        salt_file = str(tmp_path / "salt")
        # rotate twice first to produce multiple versions
        runner = CliRunner()
        runner.invoke(cli, ["rotate-salt", "--salt-file", salt_file])
        runner.invoke(cli, ["rotate-salt", "--salt-file", salt_file])
        result = runner.invoke(cli, ["rotate-salt", "--salt-file", salt_file, "--show-versions"])
        assert result.exit_code == 0, result.output
        # i18n: user-facing (asserts CLI output text owned by cli.py)
        assert "salt 版本" in result.output
        assert "v1" in result.output
