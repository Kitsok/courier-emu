"""Device-only comparisons; no firmware calls or performance measurements."""
import random
import sys

import pytest

from courier_emu.resample import BandLimitedResampler, PHASES, TAPS, _kernel_for
from courier_emu.resample_native import NativeResampler, library


@pytest.mark.parametrize('cutoff', [.49, .408333333333, .35, .1234567895])
def test_native_kernel_matches_every_reference_coefficient(cutoff):
    reference = [v for row in _kernel_for(cutoff) for v in row]
    native = library().courier_stream_kernel(cutoff, sys.version_info >= (3, 12))
    assert list(native[:PHASES*TAPS]) == reference


@pytest.mark.parametrize('rates', [
    [(8000, 8000)], [(9600, 8000)], [(8000, 9600)],
    [(0, 8000), (8000, 8000), (9600, 8000), (8000, 8000)],
    [(9600, 8000), (9600, 7200), (8000, 8000), (10080, 8000), (9600, 8000)],
])
def test_stream_chunking_and_retunes(rates):
    rng = random.Random(937)
    reference, native = BandLimitedResampler(), NativeResampler()
    try:
        for input_rate, output_rate in rates:
            for size in [0, 1, 7, 64, 128, 3, 193, 320, 1]:
                samples = [rng.randrange(-32768, 32768) for _ in range(size)]
                assert native.convert(samples, input_rate, output_rate) == reference.convert(
                    samples, input_rate, output_rate)
                state = native.snapshot()
                assert (state.input_rate, state.output_rate, state.converted) == (
                    reference.input_rate, reference.output_rate, reference.converted)
    finally:
        native.close()
