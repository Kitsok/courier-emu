"""Silicon register scripts; no modem firmware or calls."""
import random

import pytest

from courier_emu.codec import SiliconDaa, CodecBringUp, RESET_VALUES, CHIP_ID, EXTENDED_ID
from courier_emu.silicon_native import NativeSiliconDaa


@pytest.mark.parametrize('line', [1, 2])
def test_random_register_and_line_scripts_match_reference(line):
    reference = SiliconDaa(line)
    native = NativeSiliconDaa.adopt(SiliconDaa(line))
    rng = random.Random(3014)
    addresses = list(RESET_VALUES) + [CHIP_ID, EXTENDED_ID, 0x55]
    for _ in range(2000):
        action = rng.randrange(6)
        if action == 0:
            address, value = rng.choice(addresses), rng.randrange(65536)
            for device in (reference, native):
                if address == 0x55:
                    with pytest.raises(ValueError):device.write(address, value)
                else:device.write(address, value)
        elif action == 1:
            address = rng.choice(addresses)
            if address == 0x55:
                for device in (reference, native):
                    with pytest.raises(ValueError):device.read(address)
            else:assert native.read(address) == reference.read(address)
        elif action == 2:
            frames = rng.randrange(-2, 8)
            reference.elapse(frames);native.elapse(frames)
        elif action == 3:
            connected, hook = bool(rng.randrange(2)), bool(rng.randrange(2))
            for device in (reference, native):device.line_connected = connected;device.set_hook(hook)
        elif action == 4:
            positive, negative = bool(rng.randrange(2)), bool(rng.randrange(2))
            reference.set_ring(positive, negative);native.set_ring(positive, negative)
        else:
            reference.reset();native.reset()
        assert native.status() == reference.status()
        assert native._settling == reference._settling
        assert native._sticky_status == reference._sticky_status


@pytest.mark.parametrize('line', [1, 2])
def test_asic_bringup_with_native_device_matches_reference(line):
    original = SiliconDaa(line)
    assert NativeSiliconDaa.adopt(original) is original
    reference, native = CodecBringUp(SiliconDaa(line)), CodecBringUp(original)
    for count in (0, 1, 1, 2, 5):
        reference.service(count);native.service(count)
        assert native.status() == reference.status()
