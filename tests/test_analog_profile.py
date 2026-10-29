"""Check profile selection without booting firmware or making calls."""
from pathlib import Path

import pytest

from courier_emu.cli import _worker_command, build_parser
from courier_emu import profiles
from courier_emu.panel import DEFAULT_BOARD_ID, DIP_PRESETS
from courier_emu.timers import SUGGESTED_TICK_MS


def parse(*arguments):
    return build_parser().parse_args(["run", *arguments])


def test_analog403_selects_real_board_and_line_path():
    args = parse("--profile", "analog403", "--serial-pty")
    command = _worker_command(args)
    assert Path(command[3]) == profiles.ROOT / profiles.ANALOG403_IMAGE
    assert "--with-dsp" in command and "--exchange" in command
    assert command[command.index("--nvram-fixture") + 1] == "idsdl403-lapm"
    assert command[command.index("--board-id") + 1] == "7"
    assert command[command.index("--tick-ms") + 1] == "5"
    assert {command[i + 1] for i, item in enumerate(command) if item == "--dip"} == set(DIP_PRESETS["default"])
    assert "--force-online" not in command
    assert "--dsp-acquisition-assist" not in command


@pytest.mark.parametrize("options", [
    ["another.rom"], ["--force-online"], ["--dsp-acquisition-assist"],
    ["--nvram-fixture", "idsdl302"], ["--board-id", "2"],
    ["--tick-ms", "10"], ["--dip-preset", "dedicated-line"],
])
def test_profile_rejects_mismatched_board_or_synthetic_connection(options):
    with pytest.raises(ValueError):
        profiles.resolve_run_profile(parse("--profile", "analog403", *options))


def test_profile_detects_missing_and_changed_firmware(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="firmware is missing"):
        profiles.resolve_run_profile(parse("--profile", "analog403"))
    image = tmp_path / profiles.ANALOG403_IMAGE
    image.parent.mkdir(parents=True)
    image.write_bytes(b"wrong firmware")
    with pytest.raises(ValueError, match="checksum mismatch"):
        profiles.resolve_run_profile(parse("--profile", "analog403"))


def test_explicit_image_keeps_original_defaults():
    args = parse("firmware.rom")
    profiles.resolve_run_profile(args)
    assert args.image == "firmware.rom"
    assert args.board_id == str(DEFAULT_BOARD_ID)
    assert args.tick_ms == SUGGESTED_TICK_MS
    assert not args.exchange


def test_missing_image_reports_usage_error():
    with pytest.raises(ValueError, match="requires IMAGE"):
        profiles.resolve_run_profile(parse())
