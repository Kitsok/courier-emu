from pathlib import Path

import pytest

from courier_emu import cli
from courier_emu.nvram import CourierNvram, IDSDL403_NVRAM, settings_checksum
from courier_emu.pty_device import PtyDevice
from courier_emu.runtime import read_config, seed_nvram
from courier_emu.sip import SipConfig, SipSession


ROOT = Path(__file__).resolve().parent.parent


def config_file(tmp_path, old=None, new=None):
    text = (ROOT / "courier-emu.ini").read_text()
    if old is not None:
        text = text.replace(old, new)
    path = tmp_path / "modem.ini"
    path.write_text(text)
    return path


def test_configuration_resolves_paths_and_network_options(tmp_path):
    arguments, nvram = read_config(config_file(tmp_path))
    assert nvram == tmp_path / "artifacts/courier-emu-v32.nvram"
    args = cli.build_parser().parse_args(arguments)
    command = cli._worker_command(args)
    assert args.serial_link == str(tmp_path / "artifacts/courier-emu.tty")
    assert command[command.index("--sip-bind") + 1] == "0.0.0.0"
    assert command[command.index("--sip-local-port") + 1] == "5074"
    assert "--nvram-fixture" not in command
    assert cli.instruction_limit(args) == (1 << 63) - 1
    assert "--sip-register" not in command
    registered = cli.build_parser().parse_args(arguments + ["--sip-register"])
    assert "--sip-register" in cli._worker_command(registered)


@pytest.mark.parametrize("old,new", [
    ("port = 5074", "port = 65536"), ("bind = 0.0.0.0", "bind = bad"),
    ("codec = pcmu", "codec = g729"), ("profile = analog403", "profile = imodem"),
    ("target = sip:{number}@192.168.196.254", "target = sip:100@192.168.196.254"),
    ("username = 201", "username = 201\nunknown = typo"),
])
def test_invalid_configuration_fails_before_startup(tmp_path, old, new):
    with pytest.raises(ValueError):
        read_config(config_file(tmp_path, old, new))


def test_nvram_seeding_and_backup_migration_preserve_other_settings(tmp_path):
    path = tmp_path / "state/settings"
    assert seed_nvram(path) is None
    assert path.read_bytes() == bytes(CourierNvram.idsl403_lapm_fixture().data)
    assert seed_nvram(path) is None
    original = bytes(IDSDL403_NVRAM)
    path.write_bytes(original)
    path.chmod(0o640)
    backup = seed_nvram(path)
    assert backup.parent == path.parent and backup.read_bytes() == original
    actual = path.read_bytes()
    assert {i for i, (a, b) in enumerate(zip(original, actual)) if a != b} == {5, 511}
    assert actual[5] == 5 and actual[-1] == settings_checksum(actual)
    assert path.stat().st_mode & 0o777 == 0o640
    assert seed_nvram(path) is None
    assert list(path.parent.glob('*.bak')) == [backup]
    # Every later firmware-written non-ARQ version gets its own backup.
    later = bytearray(actual)
    later[5], later[0x3c] = 4, 0x64
    later[-1] = settings_checksum(later)
    path.write_bytes(later)
    second = seed_nvram(path)
    assert second != backup and second.read_bytes() == later
    assert backup.read_bytes() == original
    assert path.read_bytes()[0x3c] == 0x64


@pytest.mark.parametrize('contents', [b'bad', bytes(511) + b'\x01'])
def test_invalid_existing_nvram_is_never_migrated(tmp_path, contents):
    path = tmp_path / 'settings.nvram'
    path.write_bytes(contents)
    with pytest.raises(ValueError):
        seed_nvram(path)
    assert path.read_bytes() == contents
    assert not list(tmp_path.glob('*.bak'))


def test_migration_failure_retains_original_and_completed_backup(tmp_path, monkeypatch):
    path = tmp_path / 'settings.nvram'
    original = bytes(IDSDL403_NVRAM)
    path.write_bytes(original)
    def fail(*args):
        raise OSError('cannot replace EEPROM')
    monkeypatch.setattr('courier_emu.runtime.os.replace', fail)
    with pytest.raises(OSError, match='cannot replace'):
        seed_nvram(path)
    assert path.read_bytes() == original
    backups = list(tmp_path.glob('*.bak'))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert set(tmp_path.iterdir()) == {path, backups[0]}


def test_migration_through_symlink_preserves_the_link(tmp_path):
    target = tmp_path / 'actual.nvram'
    target.write_bytes(IDSDL403_NVRAM)
    link = tmp_path / 'settings.nvram'
    link.symlink_to(target)
    backup = seed_nvram(link)
    assert link.is_symlink()
    assert target.read_bytes()[5] == 5
    assert backup.read_bytes() == IDSDL403_NVRAM


def test_new_profile_preserves_capture_except_verified_operational_settings(tmp_path):
    path = tmp_path / "settings.nvram"
    seed_nvram(path)
    actual = path.read_bytes()
    # ATS27=0S54=96&M5 followed by AT&W in the original 403 firmware produces
    # these EEPROM bytes, including the firmware's stored checksum.
    differences = {i: (old, new) for i, (old, new)
                   in enumerate(zip(IDSDL403_NVRAM, actual)) if old != new}
    assert differences == {0x05: (4, 5), 0x29: (48, 0), 0x3C: (64, 96), 0x1FF: (0xBD, 0xAE)}
    assert actual[-1] == settings_checksum(actual)
    assert bytes(CourierNvram.idsl403_fixture().data) == IDSDL403_NVRAM


def test_stable_terminal_cannot_be_stolen_and_reopens_with_new_target(tmp_path):
    path = tmp_path / "runtime/tty"
    with PtyDevice(str(path)) as first:
        first.publish("/dev/pts/123")
        with pytest.raises(ValueError, match="cannot publish terminal"):
            with PtyDevice(str(path)):
                pytest.fail("second publisher acquired an active terminal")
        assert path.readlink() == Path("/dev/pts/123")
    assert not path.is_symlink()
    with PtyDevice(str(path)) as second:
        second.publish("/dev/pts/456")
        assert path.readlink() == Path("/dev/pts/456")
    assert not path.is_symlink()


def test_terminal_refuses_regular_files_and_preserves_replacement(tmp_path):
    path = tmp_path / "tty"
    path.write_text("keep")
    with pytest.raises(ValueError, match="non-symlink"):
        with PtyDevice(str(path)):
            pass
    assert path.read_text() == "keep"
    path.unlink()
    with PtyDevice(str(path)) as publisher:
        publisher.publish("/dev/pts/123")
        path.unlink()
        path.symlink_to("/dev/pts/456")
    assert path.readlink() == Path("/dev/pts/456")


def test_bind_and_advertise_are_independent():
    session = SipSession(SipConfig(server="127.0.0.1:5060", bind="127.0.0.1",
                                   advertise="192.0.2.10"))
    try:
        assert session.socket.getsockname()[0] == "127.0.0.1"
        assert session.rtp_socket.getsockname()[0] == "127.0.0.1"
        assert session.local_ip == "192.0.2.10"
        assert b"c=IN IP4 192.0.2.10" in session._sdp()
    finally:
        session.close()


@pytest.mark.parametrize("old,new", [
    ("level = normal", "level = verbose"),
    ("level = normal", "level = normal\nunknown = yes"),
])
def test_invalid_logging_configuration_is_rejected(tmp_path, old, new):
    with pytest.raises(ValueError):
        read_config(config_file(tmp_path, old, new))


def test_optional_report_path_and_legacy_config(tmp_path):
    path = config_file(tmp_path, "report =", "report = diagnostic.json")
    arguments, _ = read_config(path)
    args = cli.build_parser().parse_args(arguments)
    assert args.log_level == "normal"
    assert args.diagnostic_report == str(tmp_path / "diagnostic.json")
    path.write_text(path.read_text().split("[logging]")[0])
    arguments, _ = read_config(path)
    assert cli.build_parser().parse_args(arguments).log_level == "normal"


@pytest.mark.parametrize('old,new', [
    ('tx_gain = 0.25','tx_gain = 0'),
    ('tx_gain = 0.25','tx_gain = 1.5'),
    ('tx_gain = 0.25','tx_gain = nan'),
    ('local_echo = false','local_echo = invalid'),
])
def test_invalid_line_model_configuration_is_rejected(tmp_path, old, new):
    with pytest.raises(ValueError):
        read_config(config_file(tmp_path, old, new))


def test_normal_sip_line_settings_are_explicit_and_legacy_cli_is_preserved(tmp_path):
    arguments,_ = read_config(config_file(tmp_path))
    args = cli.build_parser().parse_args(arguments)
    command = cli._worker_command(args)
    assert command[command.index('--sip-line-gain')+1] == '0.25'
    assert command[command.index('--sip-local-echo')+1] == 'off'
    args = cli.build_parser().parse_args(['run','--profile','analog403'])
    command = cli._worker_command(args)
    assert command[command.index('--sip-line-gain')+1] == '1.0'
    assert command[command.index('--sip-local-echo')+1] == 'on'


def test_failed_backup_never_changes_saved_settings(tmp_path, monkeypatch):
    path = tmp_path / 'settings.nvram'
    path.write_bytes(IDSDL403_NVRAM)
    def fail(**kwargs):
        raise OSError('backup unavailable')
    monkeypatch.setattr('courier_emu.runtime.tempfile.NamedTemporaryFile', fail)
    with pytest.raises(OSError, match='backup unavailable'):
        seed_nvram(path)
    assert path.read_bytes() == IDSDL403_NVRAM
    assert list(tmp_path.iterdir()) == [path]
