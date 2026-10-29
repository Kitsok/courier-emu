from pathlib import Path

import pytest

from courier_emu import build, dsp, x86_native


def test_missing_dependencies_explains_packages(tmp_path, monkeypatch):
    monkeypatch.setattr(build.shutil, "which", lambda _: None)
    monkeypatch.setattr(build.sysconfig, "get_path", lambda _: str(tmp_path))
    missing = build.missing_dependencies()
    assert any("build-essential" in message for message in missing)
    assert any("python3-dev" in message for message in missing)


@pytest.mark.parametrize("component", ["cpu", "dsp", "runner"])
def test_runtime_never_builds_missing_components(component, tmp_path, monkeypatch):
    monkeypatch.setenv("COURIER_EMU_NO_BUILD", "1")
    monkeypatch.delenv("COURIER_C5X_LIBRARY", raising=False)
    monkeypatch.setattr(x86_native, "LIBRARY", tmp_path / "cpu.so")
    monkeypatch.setattr(dsp, "LIBRARY", tmp_path / "dsp.so")
    monkeypatch.setattr(dsp, "RUNNER", tmp_path / "runner")
    def forbidden(*args, **kwargs):
        pytest.fail("runtime attempted to launch a compiler")
    monkeypatch.setattr(build.subprocess, "run", forbidden)
    function = {"cpu": x86_native.build_library, "dsp": dsp.build_library,
                "runner": dsp.build_runner}[component]
    with pytest.raises(RuntimeError, match=r"run ./build.sh"):
        function()


def test_check_only_does_not_compile(monkeypatch, capsys):
    monkeypatch.setattr(build, "missing_dependencies", lambda: [])
    monkeypatch.setattr(build, "check_firmware", lambda: None)
    monkeypatch.setattr(x86_native, "build_library", lambda: pytest.fail("compiled during check"))
    assert build.main(["--check-only"]) == 0
    assert "prerequisites and firmware: OK" in capsys.readouterr().out
