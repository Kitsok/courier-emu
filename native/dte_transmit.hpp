// Native UART output, result-boundary handling and bounded terminal delivery.
#pragma once
#include <algorithm>
#include <deque>
#include "terminal_io.hpp"
namespace courier {
struct TransmitState {
    uint64_t online=0,truncated=0,size=0,recent_size=0,writes[2]{},error=0;
    uint64_t entered=0,left=0,schedule_pending=0,schedule_ready=0,activity=0;
    uint8_t serial[65536]{},recent[12]{};
};
struct DteTransmit {
    TransmitState &s;
    TerminalTransport &terminal;
    uint8_t *memory;
    uint64_t callbacks,idle,collecting,online_idle;
    std::string line;
    std::deque<std::string> results;
    DteTransmit(TransmitState &state,TerminalTransport &transport,uint8_t *m,
                const uint64_t *layout):s(state),terminal(transport),memory(m),
        callbacks(layout[0]),idle(layout[1]),collecting(layout[2]),online_idle(layout[3]) {}
    bool command_mode() const {
        const auto value=memory[callbacks+4]|unsigned(memory[callbacks+5])<<8;
        return value==idle||value==collecting||value==online_idle;
    }
    bool write(uint8_t byte,unsigned width=0) {
        ++s.activity;
        if(width)++s.writes[width-1];
        if(!s.online||command_mode()||line.compare(0,7,"CONNECT")==0) {
            const char ch=char(byte&127);
            if(ch=='\r'||ch=='\n') {
                const bool connect=line=="CONNECT"||(line.compare(0,8,"CONNECT ")==0
                    &&std::all_of(line.begin()+8,line.end(),[](char c){return c>=32&&c<=126;}));
                if(connect||line=="OK"||line=="ERROR"||line=="NO CARRIER"
                        ||line=="NO DIAL TONE"||line=="BUSY"||line=="NO ANSWER"
                        ||line=="RING"||line=="RINGING")results.push_back(line);
                line.clear();
            } else if(line.size()<1024)line+=ch;
            else line.clear();
        } else line.clear();
        if(s.size<sizeof s.serial)s.serial[s.size++]=byte;else s.truncated=1;
        if(s.recent_size==12)std::memmove(s.recent,s.recent+1,11);
        else ++s.recent_size;
        s.recent[s.recent_size-1]=byte&127;
        if(!s.online&&s.recent_size>=8) {
            const auto tail=s.recent+s.recent_size-8;
            if((tail[0]=='\r'||tail[0]=='\n')&&!std::memcmp(tail+1,"CONNECT",7)) {
                s.online=1;++s.entered;
            }
        }
        if(s.online&&s.recent_size==12&&!std::memcmp(s.recent,"\nNO CARRIER\r",12)) {
            s.online=0;++s.left;
        }
        if(s.online&&s.schedule_pending&&(byte&127)==10)s.schedule_ready=1;
        terminal.enqueue(s.online?byte:byte&127);
        return s.entered||s.left||s.schedule_ready||!results.empty();
    }
    void flush() {if(!s.error)s.error=uint64_t(terminal.drain());}
    size_t take(char *out,size_t capacity) {
        size_t size=0;
        while(!results.empty()&&results.front().size()+1<=capacity-size) {
            const auto &value=results.front();std::memcpy(out+size,value.data(),value.size());
            size+=value.size();out[size++]='\n';results.pop_front();
        }
        return size;
    }
};
} // namespace courier
