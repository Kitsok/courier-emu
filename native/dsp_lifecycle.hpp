// Native ownership of the existing analog DSP loader and board lifecycle.
#pragma once
#include "board_media.hpp"
#include "mailbox_observer.hpp"
#include <array>
#include <deque>
#include <map>
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
    uint64_t runtime_header=0,runtime_data=0,pending_header=0,pending_data=0,pending_valid=0;
    uint64_t inbound_seen=0,inbound_count=0,host_delivered=0,messages_taken=0,stream_acks=0;
    uint64_t overlay_status=7,overlay_pending=0,overlay_mark=0,overlay_write_mark=0;
    uint64_t overlay_halves=0,overlay_strobes=0,overlay_verified=0,overlay_unreadable=0;
    uint64_t overlay_downloads=0,overlay_id=~uint64_t(0),overlay_match=2,overlay_waits=0;
    uint64_t asic_started=0,v8_armed=0,call_resume=0,call_overlay_active=0;
    uint64_t asic_commits=0,asic_register_commits=0,detector_replies=0,rate_trace=0;
    uint64_t audio_only=0,has_overlay=0,has_exchange=0;
    uint64_t asic_registers[256]{},asic_valid[256]{},asic_writes[256]{};
    MailboxObserverState observer;
    char error[512]{};
};
struct DspLifecycle {
    DspLifecycleState &s;
    analog::BoardMedia &media;
    C5xCore *core;
    uint32_t *cpu_registers=nullptr;
    MailboxObserver observer;
    std::array<uint8_t*,256> windows{};
    std::vector<uint8_t> bootstrap,expected;
    struct ResetRecord {int64_t frame,instructions,tx_written;};
    std::vector<ResetRecord> resets;
    std::deque<std::pair<uint16_t,uint16_t>> inbound;
    std::map<uint32_t,uint64_t> delivered;
    struct Overlay {unsigned index;bool entry;std::vector<uint8_t> data;};
    struct Group {uint16_t base;std::array<uint8_t,8> data;};
    std::vector<Overlay> overlays;
    std::vector<uint8_t> overlay_buffer;
    std::vector<Group> overlay_groups;
    std::vector<std::array<uint8_t,8>> overlay_heads;
    std::vector<uint16_t> overlay_destinations;
    int overlay_target=-1;
    unsigned tag_cell=0x5e,word_cell=0x58,status_cell=0x57,stream_cell=0x59;
    uint64_t target=0;
    unsigned first=1,dispatch_cell=0x6a,nmi_entry=0x610,frame_irq=5;
    DspLifecycle(DspLifecycleState &state,analog::BoardMedia &board,C5xCore &dsp):
        s(state),media(board),core(&dsp),observer(s.observer) {}
    void bytes(const uint8_t *data,size_t size,unsigned operation) {
        if(operation==2){expected.assign(data,data+size);return;}
        if(!operation)bootstrap.clear();
        bootstrap.insert(bootstrap.end(),data,data+size);s.bootstrap_size=bootstrap.size();
    }
    void queue(uint16_t header,uint16_t data) {
        inbound.emplace_back(header,data);s.inbound_count=inbound.size();
    }
    uint64_t message(size_t index,bool consume=false) {
        if(index>=inbound.size())return uint64_t(1)<<32;
        const auto value=inbound[index];
        if(consume){inbound.pop_front();s.inbound_count=inbound.size();}
        return uint64_t(value.first)<<16|value.second;
    }
    bool deliver(uint16_t header,uint16_t data) {
        if(!s.active)return false;
        core->set_io(uint16_t(tag_cell),header);core->set_io(uint16_t(word_cell),data);
        core->set_io(uint16_t(status_cell),uint16_t(core->io(uint16_t(status_cell))|1));
        ++s.host_delivered;return true;
    }
    void reply(uint16_t header,uint16_t data) {if(!s.audio_only)queue(header,data);}
    void start_asic() {
        auto *daa=media.daa;
        if(s.audio_only||!s.asic_valid[0x82]||s.asic_registers[0x82]!=0xa0
                ||!s.has_overlay||!daa||daa->qualified_samples<4000)return;
        if(s.has_exchange&&(daa->operation==analog::Originate||daa->operation==analog::Dialing)
                &&media.port.exchange.s.state!=analog::Connected
                &&media.port.exchange.s.state!=analog::AnswerTone)return;
        s.asic_registers[0x82]=0x60;
        if(!s.asic_started) {
            s.asic_started=s.v8_armed=s.call_resume=1;
            core->set_data_trace(true);s.rate_trace=1;
            reply(2,0);reply(3,0);
        }
    }
    void advance_asic() {
        if(s.asic_started&&s.call_overlay_active&&s.asic_valid[0x82]
                &&s.asic_registers[0x82]==0x60)s.asic_registers[0x82]=0x20;
    }
    void observe(uint16_t header,uint16_t data) {
        if(!((header>=0x13&&header<=0x1f)||(header>=0x7d&&header<=0x84)))return;
        const auto previous=s.asic_registers[header];
        s.asic_registers[header]=data;s.asic_valid[header]=1;++s.asic_writes[header];
        if(s.audio_only)return;
        if(header==0x82&&data==0xa0){start_asic();return;}
        if(header==0x82&&(data&0x40)&&!s.asic_started) {
            s.asic_started=1;reply(2,0);reply(3,0);
        }
        if(header!=0x1f||previous||!data)return;
        for(const unsigned reg:{0x13,0x15,0x16,0x19,0x1a,0x1b})if(!s.asic_valid[reg])return;
        ++s.asic_commits;++s.asic_register_commits;
        if(!s.v8_armed&&(s.has_exchange||!media.dial_digits.empty()
                ||(media.daa&&media.daa->operation==analog::AnswerOperation)))
            s.v8_armed=s.call_resume=1;
    }
    void answer(uint16_t header) {
        const unsigned tag=header&255;
        if(tag==0x7c&&media.daa) {
            reply(0x7c,media.daa->detector()?0x30:0);++s.detector_replies;
        } else if(tag==0x54&&s.active)reply(0x54,0);
    }
    void complete_message(uint16_t header,uint16_t data,uint16_t acknowledgement) {
        observe(header,data);deliver(header,data);answer(header);
        s.pending_valid=0;acknowledge(acknowledgement);
    }
    void acknowledge(uint16_t value) {
        if(value&2) {
            if(!inbound.empty()&&s.inbound_seen) {
                ++delivered[uint32_t(message(0,true))];s.inbound_seen=0;
            } else if((core->io(uint16_t(status_cell))^6)&2)++s.messages_taken;
        }
        if(value&4)++s.stream_acks;
        core->set_io(uint16_t(status_cell),uint16_t(core->io(uint16_t(status_cell))|(value&6)));
    }
    int mailbox(unsigned direction,uint16_t port,uint16_t value,uint16_t &answer,uint64_t now) {
        if(!s.active)return 0;
        if(direction==2&&port>=0x58&&port<=0x5e&&!(port&1)) {
            s.runtime_mode=1;
            auto &word=port<0x5c?s.runtime_header:s.runtime_data;
            if(port==0x58||port==0x5c)word=(word&0xff00)|(value&255);
            else word=(word&255)|((value&255)<<8);
            if(port==0x5e){s.pending_header=s.runtime_header;s.pending_data=s.runtime_data;s.pending_valid=1;}
            return 1;
        }
        if(!s.runtime_mode)return 0;
        if(port==0x1c) {
            if(direction==1) {
                const auto status=core->io(uint16_t(status_cell));
                answer=((status&1)||s.pending_valid)?0:1;
                if(!inbound.empty()||((status^6)&2))answer|=2;
                if((status^6)&4)answer|=4;
                return 1;
            }
            if((value&1)&&s.pending_valid) {
                const auto header=uint16_t(s.runtime_header),data=uint16_t(s.runtime_data);
                const uint64_t pc=cpu_registers
                    ? ((uint64_t(cpu_registers[9])<<4)+cpu_registers[12])&0xfffff : ~uint64_t(0);
                observer.record(header,data,now,pc);
                const bool resume_before=s.call_resume;
                complete_message(header,data,value);
                // A legacy call-entry continuation is functional host work.
                // Diagnostic records never request a host handoff.
                const bool phase_pending=s.asic_started&&s.call_overlay_active
                    &&s.asic_valid[0x82]&&s.asic_registers[0x82]==0x60;
                if(bool(s.call_resume)!=resume_before||phase_pending){s.pin_sync=1;return 2;}
                return 1;
            }
            acknowledge(value);return 1;
        }
        if(direction==1&&port>=0x58&&port<=0x62&&!(port&1)) {
            uint16_t word;
            if(port<0x60&&!inbound.empty()) {
                word=port<0x5c?inbound.front().first:inbound.front().second;
                if(port<0x5c)s.inbound_seen=1;
            } else word=core->io_output(uint16_t(port<0x5c?tag_cell:port<0x60?word_cell:stream_cell));
            answer=(word>>((port==0x5a||port==0x5e||port==0x62)?8:0))&255;
            return 1;
        }
        return 0;
    }
    void overlay_clear() {overlay_buffer.clear();overlay_groups.clear();overlay_target=-1;}
    void overlay_start() {
        if(s.overlay_halves){s.overlay_halves=0;return;}
        overlay_clear();s.overlay_status=3;s.overlay_pending=1;
        s.overlay_mark=core->data(0xff62);s.overlay_write_mark=core->data_write_count(0xff62);
    }
    uint16_t overlay_read() {
        if(s.overlay_pending) {
            if(core->data_write_count(0xff62)!=s.overlay_write_mark) {
                s.overlay_pending=0;s.overlay_status|=4;
                overlay_destinations.push_back(core->data(0xff62));
            } else ++s.overlay_waits;
        }
        return uint16_t(s.overlay_status);
    }
    void overlay_group(uint16_t base,const uint8_t *block) {
        Group group;group.base=base;std::copy_n(block,8,group.data.begin());overlay_groups.push_back(group);
    }
    void overlay_accumulate(const uint8_t *half,size_t size,bool committed) {
        ++s.transfers;overlay_buffer.insert(overlay_buffer.end(),half,half+size);
        if(overlay_target<0) {
            if(overlay_buffer.size()<8)return;
            if(overlay_heads.size()<6) {
                std::array<uint8_t,8> head;std::copy_n(overlay_buffer.begin(),8,head.begin());
                overlay_heads.push_back(head);
            }
            for(size_t k=0;k<overlays.size();++k) {
                const auto &row=overlays[k];
                if(row.entry&&row.data.size()>=8&&std::equal(row.data.begin(),row.data.begin()+8,overlay_buffer.begin())) {
                    overlay_target=int(k);break;
                }
            }
            if(overlay_target<0){overlay_clear();return;}
        }
        const auto &row=overlays[size_t(overlay_target)];
        if(overlay_buffer.size()<row.data.size()||!committed)return;
        s.overlay_match=std::equal(row.data.begin(),row.data.end(),overlay_buffer.begin());s.overlay_id=row.index;
        if(s.overlay_match) {
            uint64_t verified=0,unreadable=0;
            for(const auto &group:overlay_groups) {
                if(group.base<0x2000){unreadable+=4;continue;}
                for(unsigned k=0;k<4;++k) {
                    const uint16_t expected_word=uint16_t(group.data[2*k]|unsigned(group.data[2*k+1])<<8);
                    if(core->program(uint16_t(group.base+k))!=expected_word){s.overlay_match=0;break;}
                }
                if(!s.overlay_match)break;
                verified+=4;
            }
            if(s.overlay_match){s.overlay_verified+=verified;s.overlay_unreadable+=unreadable;}
        }
        if(s.overlay_match)++s.overlay_downloads;
        overlay_clear();
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
