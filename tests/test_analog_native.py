"""Device-only comparisons; no modem call, SIP peer or wall-clock benchmark."""
import copy
from dataclasses import fields
import math
import random

import pytest

from courier_emu.analog_native import NativeDaa, NativeLineExchange
from courier_emu.daa import CourierDaa, DAA_LINE_STATES
from courier_emu.exchange import LineExchange, DtmfDecoder, DTMF_KEYS


def compare_exchange(a, b):
    assert a.status() == b.status()
    for field in fields(LineExchange):
        if field.name in ('router', 'peer_audio', 'decoder'):
            continue
        assert getattr(a, field.name) == getattr(b, field.name), field.name
    for field in fields(DtmfDecoder):
        assert getattr(a.decoder, field.name) == getattr(b.decoder, field.name), field.name


def tone(key, count):
    rows, columns = (697, 770, 852, 941), (1209, 1336, 1477, 1633)
    index = DTMF_KEYS.index(key)
    return [round(3000 * math.sin(2*math.pi*rows[index//4]*k/8000)
                  + 3000 * math.sin(2*math.pi*columns[index%4]*k/8000)) for k in range(count)]


def test_native_daa_random_script_and_live_identity():
    rng = random.Random(405)
    reference = CourierDaa('quiet')
    native = copy.deepcopy(reference)
    assert NativeDaa.adopt(native) is native
    for _ in range(1000):
        action = rng.randrange(6)
        if action == 0:
            state = rng.choice(DAA_LINE_STATES)
            reference.line_state = native.line_state = state
        elif action == 1:
            mode = rng.choice(('originate', 'answer', 'dialing'))
            reference.seize(mode);native.seize(mode)
        elif action == 2:
            reference.release();native.release()
        elif action == 3:
            state = rng.choice(('trying', 'ringing', 'connected', 'failed', 'idle'))
            reference.set_call_progress(state);native.set_call_progress(state)
        elif action == 4:
            count = rng.choice((0, 1, 80, 800))
            reference.observe(count);native.observe(count)
        else:
            count = rng.choice((0, 1, 7, 80, 800))
            assert reference.render(count) == native.render(count)
        assert reference.status() == native.status()
    independent = copy.deepcopy(native)
    independent.seize()
    independent.qualified_samples += 1
    assert independent.qualified_samples != native.qualified_samples


@pytest.mark.parametrize('outcome', ['answer', 'busy', 'reorder', 'no-answer'])
@pytest.mark.parametrize('dial_tone', [(350, 440), (400,), (425,)])
def test_native_exchange_complete_dial_timing_and_tones(outcome, dial_tone):
    reference = LineExchange(default_outcome=outcome, dial_tone=dial_tone,
                             answer_after_rings=1, no_answer_rings=1,
                             first_digit_ms=200, interdigit_ms=100, routing_ms=10,
                             answer_tone_ms=50)
    native = NativeLineExchange.adopt(copy.deepcopy(reference))
    script = [(True, [0]*80, 80)]*3
    for key in '100#':
        script += [(True, tone(key, 400), 400), (True, [0]*160, 160)]
    script += [(True, [], 800)]*90 + [(False, [], 1600)]*2
    for hook, data, count in script:
        assert reference.service(hook, data, count) == native.service(hook, data, count)
        compare_exchange(reference, native)


def test_native_decoder_every_key_and_fragmented_buffers():
    reference = LineExchange()
    native = NativeLineExchange.adopt(copy.deepcopy(reference))
    rng = random.Random(54)
    for key in DTMF_KEYS:
        data = tone(key, 560) + [0]*160
        while data:
            count = rng.randrange(1, 130)
            part, data = data[:count], data[count:]
            assert reference.decoder.feed(part) == native.decoder.feed(part)
            compare_exchange(reference, native)
    assert reference.decoder.digits == DTMF_KEYS


def test_native_exchange_router_continuation_and_peer_callback_order():
    reference = LineExchange(directory={'1': 'answer'}, answer_tone_ms=0, routing_ms=0)
    native = NativeLineExchange.adopt(copy.deepcopy(reference))
    calls = [[], []]
    for index, device in enumerate((reference, native)):
        def route(number, device=device, index=index):
            calls[index].append(('route', number, device.state, device.elapsed))
            return 'answer'
        def peer(count, tx, device=device, index=index):
            calls[index].append(('peer', count, tuple(tx), device.elapsed))
            return list(range(count//2))
        device.router, device.peer_audio = route, peer
    for hook, tx, count in [(True, tone('1', 480), 480), (True, [], 900),
                             (True, list(range(120)), 73), (False, [], 800)]:
        assert reference.service(hook, tx, count) == native.service(hook, tx, count)
        assert calls[0] == calls[1]
        compare_exchange(reference, native)


def test_native_exchange_incoming_release_and_pulse_scripts():
    reference = LineExchange(ring_on_ms=100, ring_off_ms=200, incoming_rings=2)
    native = NativeLineExchange.adopt(copy.deepcopy(reference))
    for device in (reference, native):
        device.ring('caller')
    for hook, count in [(False, 800), (False, 1600), (True, 800), (False, 800),
                         (True, 80), (False, 400), (True, 80), (False, 400),
                         (True, 3200), (False, 10000), (True, 800)]:
        assert reference.service(hook, [], count) == native.service(hook, [], count)
        compare_exchange(reference, native)
    reference.release();native.release()
    compare_exchange(reference, native)


def test_native_exchange_independent_copies_and_directory_mutation():
    reference = LineExchange(directory={'12': 'busy'})
    native = NativeLineExchange.adopt(copy.deepcopy(reference))
    for device in (reference, native):
        device.directory['1'] = 'reorder'
        del device.directory['12']
    for device in (reference, native):
        device._observe_hook(True)
        device._accept_digit('1')
    compare_exchange(reference, native)
    independent = copy.deepcopy(native)
    compare_exchange(native, independent)
    independent.directory['2'] = 'answer'
    independent.elapsed += 1
    assert '2' not in native.directory and native.elapsed != independent.elapsed


def test_native_exchange_random_hook_ring_and_outcome_script():
    rng = random.Random(103)
    reference = LineExchange(first_digit_ms=300, interdigit_ms=100, routing_ms=25,
                             ring_on_ms=100, ring_off_ms=100)
    native = NativeLineExchange.adopt(copy.deepcopy(reference))
    for _ in range(500):
        action = rng.randrange(7)
        if action == 0:
            for device in (reference, native):device.ring('incoming')
        elif action == 1:
            reference.release();native.release()
        elif action == 2:
            reference.answer();native.answer()
        elif action == 3:
            outcome = rng.choice(('answer', 'no-answer', 'busy', 'reorder'))
            reference.set_outcome(outcome);native.set_outcome(outcome)
        else:
            count = rng.choice((1, 7, 80, 101, 800, 1600))
            data = [rng.randrange(-16000, 16000) for _ in range(rng.choice((0, count, count+7)))]
            hook = bool(rng.randrange(2))
            assert reference.service(hook, data, count) == native.service(hook, data, count)
        compare_exchange(reference, native)


def test_native_receiver_replacement_updates_the_owned_receiver():
    reference = LineExchange()
    native = NativeLineExchange.adopt(copy.deepcopy(reference))
    for device in (reference, native):
        device.decoder = DtmfDecoder(accept_blocks=2)
    for part in (tone('5', 160), [0]*160):
        assert reference.decoder.feed(part) == native.decoder.feed(part)
        compare_exchange(reference, native)
