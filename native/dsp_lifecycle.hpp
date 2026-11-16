// Native ownership of the existing analog DSP loader and board lifecycle.
#pragma once
#include "board_media.hpp"
#include <array>
#include <algorithm>
#include <cstring>
#include <stdexcept>
namespace courier {
struct DspLifecycleState {
    uint64_t reset_asserted=1,cpu_int1=0,nmi_low=0,restarted=1;
    uint64_t loader_started=0,nmi_seen=0,destination=0,active=0,launched=0;
    uint64_t runtime_mode=0,runtime_ready=0;
    int64_t runtime_delay=0;
    uint64_t line_tx_index=0,sip_tx_index=0,audio_frames=0;
    double audio_samples_due=0;
    uint64_t match=2,last_bytes=0,last_match=2,bootstraps=0,transfers=0,checksums=0;
    uint64_t bootstrap_size=0,boot_strobes_native=0;
    uint64_t pins_seen=0,pin_sync=0;
    char error[512]{};
};
struct DspLifecycle {
    DspLifecycleState &s;
    analog::BoardMedia &media;
    C5xCore *core;
    std::array<uint8_t*,256> windows{};
    std::vector<uint8_t> bootstrap,expected;
    struct ResetRecord {int64_t frame,instructions,tx_written;};
    std::vector<ResetRecord> resets;
    uint64_t target=0;
    unsigned first=1,dispatch_cell=0x6a,nmi_entry=0x610,frame_irq=5;
    DspLifecycle(DspLifecycleState &state,analog::BoardMedia &board,C5xCore &dsp):
        s(state),media(board),core(&dsp) {}
    void bytes(const uint8_t *data,size_t size,unsigned operation) {
        if(operation==2){expected.assign(data,data+size);return;}
        if(!operation)bootstrap.clear();
        bootstrap.insert(bootstrap.end(),data,data+size);s.bootstrap_size=bootstrap.size();
    }
    void float_bus() {s.runtime_mode=s.runtime_ready=0;s.runtime_delay=0;}
    void reset(bool asserted) {
        if(asserted&&windows[first])
            s.destination=windows[first][0]|unsigned(windows[first][1])<<8;
        const bool edge=asserted&&!s.reset_asserted;
        if(edge) {
            resets.push_back({-1,media.s.board_instructions,int64_t(media.s.tx_index)});
            float_bus();core->reset();media.s.cushion_rate=0;
            media.s.tx_index=0;s.line_tx_index=s.sip_tx_index=0;
            media.s.codec_last=0;s.audio_frames=0;media.line_buffer.clear();s.audio_samples_due=0;
            core->configure_line_frame_interrupt(frame_irq,0xffff);
            s.loader_started=s.nmi_seen=0;s.restarted=1;s.launched=s.active=0;
            bootstrap.clear();s.bootstrap_size=0;s.match=2;
        }
        if(s.reset_asserted!=uint64_t(asserted))s.pin_sync=1;
        s.reset_asserted=asserted;
        if(edge)media.reset(true);
    }
    void int1(bool asserted) {
        const bool before=s.cpu_int1;s.cpu_int1=asserted;
        if(asserted&&!before&&!s.reset_asserted)core->interrupt(0);
    }
    void nmi() {
        s.loader_started=0;bootstrap.clear();s.bootstrap_size=0;s.match=2;
        core->set_io(0x58,uint16_t(s.destination));settle();core->nmi();s.nmi_seen=1;s.pin_sync=1;
    }
    bool pins(uint16_t value) {
        if(!s.pins_seen){s.pins_seen=1;s.pin_sync=1;}
        reset(!(value&2));int1(!(value&0x80));
        const bool low=!(value&8);
        if(low&&!s.nmi_low)nmi();
        if(uint64_t(low)!=s.nmi_low)s.pin_sync=1;
        s.nmi_low=low;
        return bool(s.pin_sync);
    }
    void settle() {
        if(!s.restarted)return;
        for(unsigned k=0;k<64;++k) {
            if(core->data(uint16_t(dispatch_cell))==nmi_entry){s.restarted=0;return;}
            core->run(1);
        }
        throw std::runtime_error("C51 mask ROM did not arm its NMI vector after reset");
    }
    void start_loader() {
        if(s.loader_started)return;
        s.reset_asserted=0;settle();core->set_io(0x58,uint16_t(s.destination));
        if(!s.nmi_seen){core->nmi();s.nmi_seen=1;}
        for(unsigned k=0;k<4096;++k) {
            const auto pc=core->program_counter();
            if(pc==0x638||pc==0x639||pc==0x63b){s.loader_started=1;return;}
            core->run(1);
        }
        throw std::runtime_error("C51 ROM loader did not reach its ASIC poll");
    }
    bool armed() const {
        const auto pc=core->program_counter();
        return !s.loader_started||(pc>=0x638&&pc<0x653);
    }
    void commit(unsigned strobe) {
        start_loader();
        const auto before=core->io_port_stat(0x56).writes;
        if(windows[strobe]) {
            const unsigned base=0x58+4*(strobe-first);
            for(unsigned k=0;k<4;++k)core->set_io(uint16_t(base+k),
                uint16_t(windows[strobe][2*k]|unsigned(windows[strobe][2*k+1])<<8));
        }
        core->set_io(0x56,uint16_t(strobe));
        for(unsigned k=0;k<4096;++k) {
            core->run(1);if(core->io_port_stat(0x56).writes>before)return;
        }
        throw std::runtime_error("C51 ROM loader did not acknowledge strobe "+std::to_string(strobe));
    }
    bool accept(const uint8_t *window,bool codec) {
        ++s.transfers;bytes(window,8,1);
        if(bootstrap.size()<target)return false;
        s.match=target<=expected.size()&&std::equal(bootstrap.begin(),bootstrap.begin()+target,expected.begin());
        s.last_bytes=bootstrap.size();s.last_match=s.match;s.active=1;++s.bootstraps;
        s.runtime_mode=s.runtime_ready=s.bootstraps>=2||codec;return true;
    }
};
} // namespace courier
