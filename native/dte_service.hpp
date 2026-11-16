// Terminal-to-UART processing at the existing native board deadlines.
#pragma once
#include "dte_receive.hpp"
#include "dte_transmit.hpp"
#include "dsp_lifecycle.hpp"
#include "timers186.hpp"
namespace courier {
struct InputState {uint64_t events=0,error=0,int1_delivered=0,opened_at=0;};
struct DteService {
    InputState &s;
    DteReceive &rx;
    Serial186 &uart;
    DteWire186 &wire;
    MachineServiceState &irqs;
    Timers186 &timers;
    DspLifecycle &life;
    DteTransmit &output;
    std::string raw,edited,command,log;
    DteService(InputState &state,void **parts):s(state),rx(*static_cast<DteReceive*>(parts[0])),
        uart(*static_cast<Serial186*>(parts[1])),wire(*static_cast<DteWire186*>(parts[2])),
        irqs(*static_cast<MachineServiceState*>(parts[3])),timers(*static_cast<Timers186*>(parts[4])),
        life(*static_cast<DspLifecycle*>(parts[5])),output(*static_cast<DteTransmit*>(parts[6])) {}
    void poll() {
        uint8_t data[16];const size_t room=rx.input.size()<16?16-rx.input.size():0;
        const auto count=output.terminal.read(data,room);
        if(count<0){s.error=uint64_t(-count);s.events|=8;return;}
        if(count)rx.push(data,size_t(count));
        if(output.terminal.closed())s.events|=4;
    }
    void tick(uint8_t *memory,uint64_t now,uint32_t flags) {
        if(!(timers.controller_mask&16)&&!irqs.external_pending&&(flags&0x200)&&wire.take_edge()) {
            irqs.external_pending=13;irqs.refresh_pending();s.int1_delivered=1;
        }
        const bool ready=!life.s.reset_asserted&&life.s.active&&life.s.launched;
        const bool off_hook=life.media.daa&&life.media.daa->off_hook;
        const unsigned conditions=unsigned(bool(flags&0x200))|unsigned(bool(output.s.online))<<1
            |unsigned(off_hook)<<2|unsigned(ready)<<3;
        const auto opened=rx.s.opened;
        const auto event=rx.advance(memory,uart,irqs,wire,now,conditions);
        if(!opened&&rx.s.opened){s.opened_at=now;s.events|=16;}
        if(!(event&256))return;
        const uint8_t byte=uint8_t(event);
        const auto callback=memory[rx.layout[0]+4]|unsigned(memory[rx.layout[0]+5])<<8;
        const bool mode=callback==rx.layout[3]||callback==rx.layout[4]||callback==rx.layout[7];
        if(!mode){raw.clear();edited.clear();return;}
        if(memory[rx.layout[8]])output.terminal.enqueue(byte&127);
        if(byte==10||byte==13) {
            rx.s.attention_armed=0;
            if(raw.size()>=2&&((raw[0]=='A'&&raw[1]=='T')||(raw[0]=='a'&&raw[1]=='t'))) {
                command=raw;s.events|=1;
            }
            raw.clear();
        } else if(raw.size()<1024)raw+=char(byte);
        const uint8_t visible=byte&127;
        if(visible==10||visible==13) {
            if(edited.size()>=2&&(edited[0]=='A'||edited[0]=='a')&&(edited[1]=='T'||edited[1]=='t')) {
                log=edited;s.events|=2;
            }
            edited.clear();
        } else if(visible==8||visible==127) {if(!edited.empty())edited.pop_back();}
        else if(edited.size()<1024)edited+=char(visible);else edited.clear();
        output.flush();
    }
};
} // namespace courier
