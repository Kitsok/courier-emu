"""ASIC codec-master scripts without modem calls."""
import copy
import pytest
from courier_emu.codec import CodecBringUp, SiliconDaa
from courier_emu.codec_native import NativeCodecBringUp


@pytest.mark.parametrize('line', [1, 2])
def test_native_master_preserves_step_order_polling_and_configuration(line):
    reference = CodecBringUp(SiliconDaa(line), rate=8228, level=0x1234, gpio_configuration=0x22)
    native = NativeCodecBringUp.adopt(copy.deepcopy(reference))
    for count in [0, 0, 1, 1, 2, 5]:
        reference.service(count);native.service(count)
        assert native.status() == reference.status()
    assert native.complete
    native.index = reference.index = 0
    for _ in range(12):
        assert native.step() == reference.step()
        native.codec.elapse();reference.codec.elapse()
        assert native.status() == reference.status()


def test_adoption_preserves_partial_master_and_device_identity():
    master = CodecBringUp(SiliconDaa())
    master.service()
    expected = copy.deepcopy(master)
    part = master.codec
    assert NativeCodecBringUp.adopt(master) is master
    assert master.codec is part
    for _ in range(4):
        master.service();expected.service()
        assert master.status() == expected.status()
