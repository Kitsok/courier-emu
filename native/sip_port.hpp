// Subscriber-loop supervision. SIP packet parsing remains a control-plane event.
#pragma once
#include "line_media.hpp"
#include <poll.h>
#include <limits>

namespace courier::analog {
enum SipState { SipIdle,SipInviting,SipTrying,SipRinging,SipIncoming,SipConnected,SipClosed,SipFailed };
enum PortEvent { PortDone,PortPoll,PortRejectBusy,PortRing,PortAnswer,PortRoute,PortReject,PortHangup };
struct SipControl {
    int64_t state=SipIdle,inbound=0,last_status=0;
    int64_t signal_fd=-1;
    double deadline=std::numeric_limits<double>::infinity();
};
struct PortState {
    uint64_t sip_state=SipIdle,incoming_active=0,placed=0,answered=0;
    uint64_t frames=0,late_frames=0;
    double next_frame_at=0,frame_duration=0,late_seconds=0,peak_late_seconds=0;
    uint64_t clock_started=0;
};
struct SipPort {
    size_t references=1;
    void retain(){++references;}
    void release_reference(){if(--references==0)delete this;}
    Exchange &exchange;
    LineMedia media;
    SipControl control;
    PortState s;
    std::string incoming_from;
    struct Spike {uint64_t frame;double milliseconds;int64_t state;};
    std::vector<Spike> spikes;
    std::vector<int32_t> tx;
    bool off_hook=false,running=false;
    int64_t count=0;
    int phase=0,event=0;
    explicit SipPort(Exchange &line,media::Media &rtp):exchange(line),media(line,rtp) {}
    void begin(bool hook,const int32_t *data,size_t size,int64_t samples,double now,bool realtime) {
        if(running)throw std::logic_error("subscriber frame already in progress");
        tx.clear();if(size)tx.assign(data,data+size);
        off_hook=hook;count=samples;phase=0;event=0;running=true;
        if(realtime) {
            if(!s.clock_started){s.clock_started=1;s.next_frame_at=now;}
            const double late=std::max(0.0,now-s.next_frame_at);
            s.late_seconds+=late;s.peak_late_seconds=std::max(s.peak_late_seconds,late);++s.frames;
            if(late>.02) {
                ++s.late_frames;
                if(spikes.size()<64)spikes.push_back({s.frames,std::nearbyint(late*10000)/10,exchange.s.state});
            }
            s.frame_duration=double(count)/8000;s.next_frame_at+=s.frame_duration;
        }
        media.s.frames=s.frames;
    }
    int yield(int code,int next) {phase=next;return event=code;}
    // A control action must complete before resumption. State is updated by
    // the signalling owner; route_result additionally completes its exchange
    // continuation. No frame phase or subframe is replayed after a yield.
    void acknowledge() {event=0;}
    void route_result() {
        ++s.placed;exchange.finish_route(control.state==SipFailed?ReorderOutcome:Pending);event=0;
    }
    int resume() {
        if(event)return event;
        while(running) switch(phase) {
        case 0: {
            const double now=media::monotonic();
            pollfd descriptor{int(control.signal_fd),POLLIN,0};
            if(control.signal_fd<0 || now>=control.deadline ||
               ::poll(&descriptor,1,0)!=0)return yield(PortPoll,1);
            media.transport.poll(now);
            if(media.transport.snapshot().error)return yield(PortPoll,1);
            phase=1;break;
        }
        case 1: {
            const int state=int(control.state);
            if(state==SipIncoming && control.inbound) {
                if(exchange.s.off_hook || (exchange.s.state!=Idle && exchange.s.state!=Released))
                    return yield(PortRejectBusy,2); // reference leaves _sip_state unchanged
                exchange.ring(incoming_from.c_str());s.incoming_active=1;s.sip_state=state;
                return yield(PortRing,2);
            } else if(s.incoming_active && (state==SipClosed || state==SipFailed)) {
                exchange.release();s.incoming_active=0;
            } else if(state==SipRinging && !control.inbound) {
                exchange.set_outcome(NoAnswer);
            } else if(state==SipConnected) {
                if(s.sip_state!=SipConnected){++s.answered;media.pending.clear();}
                exchange.answer();
            } else if(state==SipFailed) {
                const int outcome=(control.last_status==486 || control.last_status==600)?BusyOutcome:ReorderOutcome;
                exchange.set_outcome(outcome);
            } else if(state==SipClosed && s.sip_state==SipConnected)exchange.release();
            s.sip_state=state;phase=2;break;
        }
        case 2:
            if(s.incoming_active && off_hook && exchange.s.state==IncomingRing &&
               (control.state==SipIncoming || control.state==SipRinging))return yield(PortAnswer,3);
            phase=3;break;
        case 3:
            exchange.begin(off_hook,tx.data(),tx.size(),count);phase=4;break;
        case 4: {
            const int result=exchange.resume();
            if(result==1) {
                if(exchange.dialed.empty()){exchange.finish_route(ReorderOutcome);break;}
                return yield(PortRoute,4);
            }
            if(result)throw std::logic_error("unexpected native peer continuation");
            phase=5;break;
        }
        case 5:
            if(s.incoming_active && exchange.s.state==Idle) {
                s.incoming_active=0;
                return yield(control.state==SipIncoming || control.state==SipRinging?PortReject:PortHangup,7);
            }
            if(exchange.s.state==Idle && control.state!=SipIdle && control.state!=SipClosed &&
               control.state!=SipFailed && control.state!=SipIncoming)return yield(PortHangup,6);
            phase=7;break;
        case 6:s.sip_state=control.state;phase=7;break;
        default:running=false;return PortDone;
        }
        return PortDone;
    }
};
} // namespace courier::analog
