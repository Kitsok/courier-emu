// Persistent analog line devices. Python uses live views of the POD state;
// the worker can call these same models without Python callbacks or copies.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

#if defined(__clang__)
#pragma clang fp contract(off)
#elif defined(__GNUC__)
#pragma GCC push_options
#pragma GCC optimize ("fp-contract=off")
#endif

namespace courier::analog {
constexpr double pi = 3.141592653589793238462643383279502884;
inline int32_t rounded(double value) {
    return int32_t(std::clamp(std::nearbyint(value), -32768.0, 32767.0));
}

enum LineState { Disconnected, Quiet, DialTone, Ringing };
enum Operation { IdleOperation, Originate, AnswerOperation, Dialing, Trying, ConnectedOperation, FailedOperation, RingingOperation };
struct Daa {
    int64_t line_state=Disconnected, sample_rate=8000, off_hook=0, operation=IdleOperation;
    int64_t generated_samples=0, qualified_samples=0;
    bool connected() const { return line_state != Disconnected; }
    bool dial_tone() const { return off_hook && operation==Originate && line_state==DialTone; }
    bool detector() const {
        if (!off_hook || !connected()) return false;
        return operation==AnswerOperation || operation==Dialing || operation==Trying
            || operation==ConnectedOperation || dial_tone()
            || (operation==Originate && line_state==Quiet);
    }
    void seize(int64_t kind) { off_hook=1; operation=kind; qualified_samples=0; }
    void release() { off_hook=0; operation=IdleOperation; qualified_samples=0; }
    void observe(int64_t count) {
        if (count>0 && detector()) { generated_samples+=count; qualified_samples+=count; }
    }
    void render(int64_t count, int32_t *out) {
        if (count<=0) return;
        const int64_t first=generated_samples;
        generated_samples+=count;
        const bool present=detector();
        if (present) qualified_samples+=count;
        for (int64_t k=0;k<count;++k) {
            const double index=double(first+k);
            out[k]=present && dial_tone() ? rounded(
                4000.0*std::sin(2*pi*350*index/double(sample_rate))
                +4000.0*std::sin(2*pi*440*index/double(sample_rate))) : 0;
        }
    }
};

struct DecoderState {
    int64_t sample_rate=8000, block_samples=80, accept_blocks=3, blocks=0;
    int64_t candidate=-1, run=0, held=-1;
};
struct Decoder {
    DecoderState state;
    std::string digits;
    std::vector<int32_t> pending;
    static constexpr const char *keys="123A456B789C*0#D";
    double bin(const int32_t *samples, size_t count, int frequency, double total) const {
        const double coefficient=2*std::cos(2*pi*frequency/double(state.sample_rate));
        double first=0, second=0;
        for (size_t k=0;k<count;++k) {
            const double current=double(samples[k])+coefficient*first-second;
            second=first; first=current;
        }
        return (first*first+second*second-coefficient*first*second)/(double(count)*total);
    }
    int classify(const int32_t *samples, size_t count) const {
        double total=0;
        for (size_t k=0;k<count;++k) total+=double(samples[k])*samples[k];
        if (!(total>0) || std::sqrt(total/double(count))<200) return -1;
        const int rows[4]={697,770,852,941}, columns[4]={1209,1336,1477,1633};
        int row=0,column=0; double r=-1,c=-1;
        for (int k=0;k<4;++k) { const double p=bin(samples,count,rows[k],total); if(p>r){r=p;row=k;} }
        for (int k=0;k<4;++k) { const double p=bin(samples,count,columns[k],total); if(p>c){c=p;column=k;} }
        if(r<0.10 || c<0.10 || r+c<0.25 || std::sqrt(std::max(r,c)/std::min(r,c))>8) return -1;
        return row*4+column;
    }
    std::string feed(const int32_t *samples, size_t count) {
        if(count)pending.insert(pending.end(),samples,samples+count);
        std::string found;
        const size_t n=size_t(state.block_samples);
        if (!n) return found;
        size_t used=0;
        while(pending.size()-used>=n) {
            ++state.blocks;
            const int key=classify(pending.data()+used,n); used+=n;
            if(key<0) { state.candidate=-1;state.run=0;state.held=-1;continue; }
            if(key!=state.candidate) { state.candidate=key;state.run=1; } else ++state.run;
            if(state.run==state.accept_blocks && key!=state.held) {
                state.held=key;digits+=keys[key];found+=keys[key];
            }
        }
        pending.erase(pending.begin(),pending.begin()+used);
        return found;
    }
};

enum ExchangeState { Idle, Dial, Collecting, Routing, Ringback, Busy, Reorder, AnswerTone, Connected, IncomingRing, Released };
enum Outcome { Pending, AnswerOutcome, BusyOutcome, ReorderOutcome, NoAnswer };
struct ExchangeStateData {
    int64_t sample_rate=8000, default_outcome=AnswerOutcome, answer_after_rings=2, no_answer_rings=8;
    int64_t answer_tone_ms=3000, interdigit_ms=4000, routing_ms=500, first_digit_ms=16000;
    int64_t ring_on_ms=2000, ring_off_ms=4000, incoming_rings=12, pulse_dialing=1, hotline=0;
    int64_t state=Idle, off_hook=0, outcome=Pending, rings_delivered=0, flashes=0;
    int64_t elapsed=0, tx_samples=0, rx_samples=0, calls=0;
    int64_t state_at=0, tone_index=0, hook_at=0, pulses=0, last_digit_at=0;
    int64_t has_router=0, has_peer=0, inbound_present=0;
};

// A frame may yield only for an explicit control-plane route or a peer-audio
// provider. The continuation retains its exact subframe and callback order.
// The native SIP board uses a native provider and needs no audio callbacks.
struct Exchange {
    // Native frame owners pin the device independently of Python views.
    size_t references=1;
    void retain() {++references;}
    void release_reference() {if(--references==0)delete this;}
    ExchangeStateData s;
    Decoder decoder;
    std::map<std::string,int64_t> directory;
    std::vector<int> dial_tone{350,440};
    std::string dialed,inbound_number;
    int event=0; // 1 route, 2 peer PCM
    void (*native_peer)(void *,Exchange &)=nullptr;
    void *native_peer_context=nullptr;
    std::vector<int32_t> tx,output;
    int64_t requested=0,position=0,step=0;
    std::string found;
    size_t digit_index=0;
    int phase=0;
    bool running=false;
    int64_t samples(int64_t ms) const { return std::max<int64_t>(1,ms*s.sample_rate/1000); }
    int64_t in_state() const { return s.elapsed-s.state_at; }
    void enter(int state) { s.state=state;s.state_at=s.elapsed;s.tone_index=0; }
    bool ringing() const { return s.state==IncomingRing && in_state()%samples(s.ring_on_ms+s.ring_off_ms)<samples(s.ring_on_ms); }
    bool connected() const { return s.state==AnswerTone || s.state==Connected; }
    int line_state() const { return s.state==Released ? Disconnected : s.state==IncomingRing ? Ringing : s.state==Dial ? DialTone : Quiet; }
    void ring(const char *number) {
        if(s.off_hook || (s.state!=Idle && s.state!=Released)) return;
        s.inbound_present=number!=nullptr;inbound_number=number?number:"";
        s.rings_delivered=0;enter(IncomingRing);
    }
    void release() {
        if(s.state==IncomingRing) { s.inbound_present=0;inbound_number.clear();enter(Idle); }
        else if(s.state!=Idle) enter(Released);
    }
    void finish_route(int64_t result) { s.outcome=result;s.rings_delivered=0;enter(Routing);event=0; }
    void route() {
        if(s.has_router) { event=1;return; }
        const auto it=directory.find(dialed);
        finish_route(it==directory.end()?s.default_outcome:it->second);
    }
    void observe_hook(bool off_hook) {
        if(off_hook==bool(s.off_hook)) return;
        const int64_t held=s.elapsed-s.hook_at;
        s.off_hook=off_hook;s.hook_at=s.elapsed;
        if(off_hook) {
            if(s.state==IncomingRing) { ++s.calls;enter(Connected);return; }
            if((s.state==Dial || s.state==Collecting) && s.pulse_dialing) {
                const int64_t ms=held*1000/s.sample_rate;
                if(ms>=20 && ms<=95) { ++s.pulses;s.last_digit_at=s.elapsed;if(s.state==Dial)enter(Collecting);return; }
                if(ms<=1200) { ++s.flashes;return; }
            }
            if(s.state==Idle || s.state==Released) {
                ++s.calls;dialed.clear();s.outcome=Pending;s.pulses=0;
                decoder=Decoder();decoder.state.sample_rate=s.sample_rate;
                s.last_digit_at=s.elapsed;
                if(s.hotline)route();else enter(Dial);
            }
        } else {
            if(((s.state==Dial || s.state==Collecting) && s.pulse_dialing) || s.state==IncomingRing)return;
            enter(Idle);dialed.clear();s.outcome=Pending;
        }
    }
    void accept(char digit) {
        if(s.state==Dial)enter(Collecting);
        dialed+=digit;s.last_digit_at=s.elapsed;s.pulses=0;
        if(digit=='#' || directory.count(dialed))route();
    }
    void set_outcome(int64_t result) {
        if(s.state!=Routing && s.state!=Ringback)return;
        s.outcome=result;
        if(s.state==Ringback && (result==BusyOutcome || result==ReorderOutcome))enter(result==BusyOutcome?Busy:Reorder);
    }
    void answer() {
        if(s.state==Routing || s.state==Ringback) { ++s.calls;enter(s.answer_tone_ms?AnswerTone:Connected); }
    }
    void advance() {
        if(!s.off_hook && (s.state==Dial || s.state==Collecting)) {
            if(s.elapsed-s.hook_at>=samples(1200)) { enter(Idle);dialed.clear();s.outcome=Pending;s.pulses=0; }
            return;
        }
        switch(s.state) {
        case Dial:
            if(in_state()>=samples(s.first_digit_ms)){s.outcome=ReorderOutcome;enter(Reorder);}return;
        case Collecting:
            if(s.pulses && s.elapsed-s.last_digit_at>=samples(300)) {
                dialed+=char('0'+s.pulses%10);s.pulses=0;s.last_digit_at=s.elapsed;
                if(directory.count(dialed))route();
            }
            if(!event && s.state==Collecting && !dialed.empty() && !s.pulses
                && s.elapsed-s.last_digit_at>=samples(s.interdigit_ms))route();
            return;
        case Routing:
            if(in_state()<samples(s.routing_ms) || s.outcome==Pending)return;
            enter(s.outcome==BusyOutcome?Busy:s.outcome==ReorderOutcome?Reorder:Ringback);return;
        case Ringback:
            s.rings_delivered=in_state()/samples(6000);
            if(s.outcome==AnswerOutcome && s.rings_delivered>=s.answer_after_rings){++s.calls;enter(s.answer_tone_ms?AnswerTone:Connected);}
            else if(s.outcome==NoAnswer && s.rings_delivered>=s.no_answer_rings)enter(Released);
            return;
        case AnswerTone: if(in_state()>=samples(s.answer_tone_ms))enter(Connected);return;
        case IncomingRing:
            s.rings_delivered=in_state()/samples(s.ring_on_ms+s.ring_off_ms);
            if(s.incoming_rings && s.rings_delivered>=s.incoming_rings){s.inbound_present=0;inbound_number.clear();enter(Idle);}return;
        default:return;
        }
    }
    std::vector<int> tone(int64_t &on,int64_t &off) const {
        on=off=0;if(!s.off_hook)return {};
        switch(s.state) {
        case Dial:return dial_tone;
        case Ringback:on=2000;off=4000;return {440,480};
        case Busy:on=off=500;return {480,620};
        case Reorder:case Released:on=off=250;return {480,620};
        case AnswerTone:return {2100};
        default:return {};
        }
    }
    void render(int64_t count) {
        int64_t on,off;const auto frequencies=tone(on,off);
        const int64_t period=on?samples(on+off):0,on_samples=on?samples(on):0;
        const double scale=frequencies.empty()?0:4000/std::sqrt(double(frequencies.size()));
        for(int64_t k=0;k<count;++k) {
            const int64_t index=s.tone_index+k;
            double value=0;
            if(!period || index%period<on_samples)
                for(const int f:frequencies)value+=scale*std::sin(2*pi*f*double(index)/double(s.sample_rate));
            output.push_back(rounded(value));
        }
        s.tone_index+=count;
    }
    void begin(bool off_hook,const int32_t *data,size_t size,int64_t count) {
        tx.clear();if(size)tx.assign(data,data+size);
        output.clear();requested=std::max<int64_t>(0,count);position=step=0;phase=0;event=0;
        running=requested>0;
        if(!running)return;
        s.tx_samples+=int64_t(size);observe_hook(off_hook);
    }
    int resume() {
        if(event)return event;
        while(running) {
            if(position>=requested) { s.rx_samples+=int64_t(output.size());running=false;break; }
            if(phase==0) {
                step=std::min<int64_t>(80,requested-position);found.clear();digit_index=0;
                const size_t available=position<int64_t(tx.size())?std::min<size_t>(size_t(step),tx.size()-size_t(position)):0;
                if((s.state==Dial || s.state==Collecting) && available)
                    found=decoder.feed(tx.data()+position,available);
                phase=1;
            }
            if(phase==1) {
                while(digit_index<found.size()) { accept(found[digit_index++]);if(event)return event; }
                phase=2;advance();if(event)return event;
            }
            if(phase==2) {
                if(s.state==Connected) {
                    if(native_peer)native_peer(native_peer_context,*this);
                    else if(s.has_peer){event=2;return event;}
                    else output.insert(output.end(),size_t(step),0);
                } else render(step);
                phase=3;
            }
            if(phase==3){s.elapsed+=step;position+=step;phase=0;}
        }
        return 0;
    }
    void peer_result(const int32_t *data,size_t size) {
        const size_t copied=std::min<size_t>(size,size_t(step));
        if(copied)output.insert(output.end(),data,data+copied);
        output.insert(output.end(),size_t(step)-copied,0);
        event=0;phase=3;
    }
};
} // namespace courier::analog

#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC pop_options
#endif
