// Integrated 80C186EB UART; preserves the existing board model's semantics.
#pragma once
#include <cstdint>
#include "interrupts186.hpp"

namespace courier {
struct Serial186 {
    uint64_t control=0, baud_compare=0, baud_count=0, receive_holding=0;
    uint64_t transmitted=0, received=0, holding=0, receive_ready=0, clear_to_send=0;

    uint64_t native_reads=0, native_writes=0, read_counts[5][2]{}, read_mask=0;

    static void request(MachineServiceState &irqs, uint64_t vector) {
        for (uint64_t i=0; i<irqs.serial_count; ++i)
            if (irqs.serial_pending[i]==vector) return;
        if (irqs.serial_count<2) irqs.serial_pending[irqs.serial_count++]=vector;
        irqs.refresh_pending();
    }
    // The legacy model consumes its CTS stand-in and RI on status reads.
    // TX is immediately ready; framing, overrun and RI reporting remain
    // unmodelled. Migration must not silently change those assumptions.
    uint32_t read(uint32_t address) {
        switch (address) {
        case 0xff60:return uint32_t(baud_compare);
        case 0xff62:return uint32_t(baud_count);
        case 0xff64:return uint32_t(control);
        case 0xff66: {
            const uint32_t value=8 | (clear_to_send?2:0);
            receive_ready=clear_to_send=0;return value;
        }
        case 0xff68:return uint32_t(receive_holding);
        default:return UINT32_MAX;
        }
    }
    int write(uint32_t address, uint64_t value, MachineServiceState &irqs) {
        switch (address) {
        case 0xff60:baud_compare=value;break;
        case 0xff62:baud_count=value;break;
        case 0xff64:control=value;break;
        case 0xff6a:++transmitted;request(irqs,0x15);return int(value&255);
        }
        return -1;
    }
    void deliver(uint8_t byte, MachineServiceState &irqs) {
        receive_holding=byte;receive_ready=clear_to_send=1;
        ++received;request(irqs,0x14);
    }
};
} // namespace courier
