"""One definition of 'this host can run that arch'."""

from kivyforge.host import host_machine, host_runs_natively


class TestHostRunsNatively:
    def test_matching_arch_is_native(self):
        assert host_runs_natively("x86_64", host_machine="x86_64")
        assert host_runs_natively("arm64", host_machine="arm64")
        assert host_runs_natively("amd64", host_machine="amd64")

    def test_foreign_arch_is_cross(self):
        assert not host_runs_natively("aarch64", host_machine="x86_64")
        assert not host_runs_natively("x86_64", host_machine="aarch64")

    def test_comparison_is_case_insensitive(self):
        assert host_runs_natively("X86_64", host_machine="x86_64")

    def test_host_machine_matches_platform(self, monkeypatch):
        monkeypatch.setattr("kivyforge.host.platform.machine", lambda: "x86_64")
        assert host_machine() == "x86_64"
        assert host_runs_natively("x86_64")
        assert not host_runs_natively("aarch64")
