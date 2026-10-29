import struct
import time
from pathlib import Path

from courier_emu.audio_monitor import AudioMonitor
from courier_emu import cli
from courier_emu.runtime import read_config
import pytest


def wait_for(predicate):
    deadline = time.monotonic()+3
    while time.monotonic()<deadline:
        if predicate():
            return
        time.sleep(.01)
    assert predicate()


def test_pcm_playback_is_gated_and_mixed_without_touching_modem_samples(tmp_path):
    capture = tmp_path/'speaker.pcm'
    player = tmp_path/'player'
    player.write_text('#!/usr/bin/python3\nimport os,sys\n'
                      f'out=open({str(capture)!r},"ab",buffering=0)\n'
                      'while True:\n b=os.read(0,320)\n if not b:break\n out.write(b)\n')
    player.chmod(0o755)
    monitor = AudioMonitor(.25, player=str(player))
    tx, rx = [1000]*160, [3000]*160
    try:
        monitor.feed(tx, rx, enabled=False)
        time.sleep(.05)
        assert not capture.exists()
        monitor.feed(tx, rx, enabled=True)
        wait_for(lambda: capture.exists() and len(capture.read_bytes())==320)
        assert capture.read_bytes() == struct.pack('<160h', *([1000]*160))
        monitor.feed(tx, rx, enabled=False)
        time.sleep(.1)
        assert len(capture.read_bytes()) == 320
        assert tx == [1000]*160 and rx == [3000]*160
    finally:
        monitor.close()
    assert not monitor.thread.is_alive()


def test_missing_player_disables_monitor_without_stopping_producer(tmp_path):
    monitor = AudioMonitor(player=str(tmp_path/'missing-player'))
    try:
        monitor.feed([1]*800, [1]*800, enabled=True)
        wait_for(lambda: monitor.disabled)
        for _ in range(1000):
            monitor.feed([1]*800, [1]*800, enabled=True)
        assert monitor.frames.qsize() <= 10
    finally:
        monitor.close()


@pytest.mark.parametrize('setting', ['volume = 2', 'volume = nan', 'enabled = invalid'])
def test_audio_configuration_is_validated(tmp_path, setting):
    root = Path(__file__).resolve().parent.parent
    text = (root/'courier-emu.ini').read_text()
    text = text.replace('volume = 0.25', setting) if setting.startswith('volume') else text.replace('enabled = false', setting)
    path = tmp_path/'modem.ini';path.write_text(text)
    with pytest.raises(ValueError):
        read_config(path)


def test_audio_settings_reach_worker(tmp_path):
    root = Path(__file__).resolve().parent.parent
    path = tmp_path/'modem.ini'
    path.write_text((root/'courier-emu.ini').read_text().replace('enabled = false', 'enabled = true'))
    arguments, _ = read_config(path)
    args = cli.build_parser().parse_args(arguments)
    command = cli._worker_command(args)
    assert '--audio-monitor' in command
    assert command[command.index('--audio-volume')+1] == '0.25'
