from pathlib import Path

import pytest

from courier_emu import cli
from courier_emu.nvram import IDSDL403_NVRAM
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
    assert nvram == tmp_path / "artifacts/courier-emu.nvram"
    args = cli.build_parser().parse_args(arguments)
    command = cli._worker_command(args)
    assert args.serial_link == str(tmp_path / "artifacts/courier-emu.tty")
    assert command[command.index("--sip-bind") + 1] == "0.0.0.0"
    assert command[command.index("--sip-local-port") + 1] == "5074"
    assert "--nvram-fixture" not in command
    assert cli.instruction_limit(args) == (1 << 63) - 1


@pytest.mark.parametrize("old,new", [
    ("port = 5074", "port = 65536"), ("bind = 0.0.0.0", "bind = bad"),
    ("codec = pcmu", "codec = g729"), ("profile = analog403", "profile = imodem"),
    ("target = sip:{number}@192.168.196.29", "target = sip:100@192.168.196.29"),
    ("username = courier", "username = courier\nunknown = typo"),
])
def test_invalid_configuration_fails_before_startup(tmp_path, old, new):
    with pytest.raises(ValueError):
        read_config(config_file(tmp_path, old, new))


def test_nvram_is_seeded_once_and_invalid_existing_data_is_preserved(tmp_path):
    path = tmp_path / "state/settings"
    seed_nvram(path)
    assert path.read_bytes() == IDSDL403_NVRAM
    changed = bytes([0]) * len(IDSDL403_NVRAM)
    path.write_bytes(changed)
    seed_nvram(path)
    assert path.read_bytes() == changed
    path.write_bytes(b"bad")
    with pytest.raises(ValueError):
        seed_nvram(path)
    assert path.read_bytes() == b"bad"


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
