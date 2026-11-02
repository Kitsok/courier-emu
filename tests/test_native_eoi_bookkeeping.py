"""Native EOI replay bookkeeping, including fallback without partial counts."""
from collections import Counter
import pytest
from courier_emu.service_native import fold_native_eois


def record(width=2, applied=1, address=0xff02):
    return address.to_bytes(4, 'little')+b'\x00\x80'+bytes((width, applied))


def test_mixed_width_native_eois_fold_once():
    counts = Counter()
    assert fold_native_eois(memoryview(record(1)+record(2)+record(2)), 3, counts)
    assert counts == {('write', 0xff02, 1): 1, ('write', 0xff02, 2): 2}


@pytest.mark.parametrize('data,count', [(record(applied=0), 1), (record(address=0xff04), 1),
                                      (record(width=4), 1), (record()+record(applied=0), 2),
                                      (record(), 2), (b'', 0)])
def test_unhandled_or_incomplete_batch_preserves_fallback(data, count):
    counts = Counter({('write', 0xff02, 2): 7})
    assert not fold_native_eois(memoryview(data), count, counts)
    assert counts == {('write', 0xff02, 2): 7}
