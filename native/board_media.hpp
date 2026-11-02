// Persistent standalone Courier codec/line pipeline. The native worker lends
// the current C5x only while servicing; resets never leave a stale core pointer.
#pragma once
#include "c5x_core.h"
#include "sip_port.hpp"
#include "stream_resample.hpp"

namespace courier::analog {
struct BoardMediaState {
    uint64_t tx_index=0,codec_last=0,idle=0,frames=0,tx_consumed=0,resampled=0,crossing_retune=0,reported_tx_index=0;
    int64_t peak_codec=0,peak_line=0,line_rx_peak=0,codec_in_peak=0,handed_peak=0;
    int64_t handed_at=0,handed_ever=0,queue_peak=0;
    uint64_t queue_input=1,clocked_input=0,replayed=0;
    double cushion_rate=0;
};
struct BoardMedia {
    SipPort &port;
    Daa *daa;
    BoardMediaState s;
    resample::Stream tx_converter,rx_converter;
    std::deque<int16_t> line_buffer,in_flight,deferred_rx;
    std::vector<int32_t> frame;
    std::vector<int16_t> received;
    std::vector<uint16_t> words;
    size_t frame_samples;
    uint64_t frame_instructions,batch;
    std::string dial_digits;
    int64_t instructions=0;
    bool active=false,in_frame=false,fallback=false;
    BoardMedia(SipPort &subscriber,Daa *device,size_t samples,uint64_t period,uint64_t quantum,
               bool precise,bool compensated):port(subscriber),daa(device),
        tx_converter(precise,compensated),rx_converter(precise,compensated),
        frame_samples(samples),frame_instructions(period),batch(quantum) {
        if(!samples || !period || !quantum)throw std::invalid_argument("invalid native line cadence");
        port.retain();
    }
    ~BoardMedia(){port.release_reference();}
    BoardMedia(const BoardMedia &)=delete;
    BoardMedia &operator=(const BoardMedia &)=delete;
    static int64_t peak(const int16_t *data,size_t count) {
        int64_t value=0;for(size_t k=0;k<count;++k)value=std::max<int64_t>(value,std::abs(int(data[k])));return value;
    }
    void chunk(const int16_t *data,size_t count,double rate) {
        if(!count)return;
        if(rate) {
            tx_converter.convert(data,count,rate,8000);
            for(const auto sample:tx_converter.out)line_buffer.push_back(sample);
            s.peak_line=std::max(s.peak_line,peak(tx_converter.out.data(),tx_converter.out.size()));
            s.resampled+=tx_converter.out.size();
        } else {
            line_buffer.insert(line_buffer.end(),data,data+count);
            s.peak_line=std::max(s.peak_line,peak(data,count));s.resampled+=count;
        }
    }
    void collect(C5xCore &core) {
        const auto &source=core.line_tx_samples();const size_t end=source.size(),start=size_t(s.tx_index);
        if(end<start)throw std::logic_error("notify native media before resetting codec output");
        if(end==start)return;
        const auto *data=reinterpret_cast<const int16_t *>(source.data());
        double rate=double(core.codec_sample_rate_millihz())/1000;
        size_t offset=start;bool crossed=false;
        for(const auto &event:core.line_tx_clock_events()) {
            if(event[0]<=start)rate=40320000.0/double(event[1]);
            else if(event[0]<end) {
                chunk(data+offset,size_t(event[0])-offset,rate);
                offset=size_t(event[0]);rate=40320000.0/double(event[1]);crossed=true;
            }
        }
        chunk(data+offset,end-offset,rate);
        if(crossed)++s.crossing_retune;
        s.peak_codec=std::max(s.peak_codec,peak(data+start,end-start));
        s.tx_consumed+=end-start;s.tx_index=s.reported_tx_index=end;
    }
    void queue(C5xCore &core,const std::vector<int32_t> &input,bool frame_metrics=true) {
        if(input.empty())return;
        received.clear();for(const auto sample:input)received.push_back(int16_t(sample));
        const int64_t input_peak=peak(received.data(),received.size());
        if(frame_metrics)s.line_rx_peak=std::max(s.line_rx_peak,input_peak);
        if(frame_metrics && !s.queue_input) {deferred_rx.insert(deferred_rx.end(),received.begin(),received.end());return;}
        s.codec_in_peak=std::max(s.codec_in_peak,input_peak);
        if(frame_metrics)s.queue_peak=std::max(s.queue_peak,input_peak);
        const double rate=double(core.codec_sample_rate_millihz())/1000;
        const std::vector<int16_t> *converted=&received;
        if(!s.clocked_input) {
            rx_converter.convert(received.data(),received.size(),8000,rate);converted=&rx_converter.out;
            if(!converted->empty() && rate>0 && rate!=s.cushion_rate) {
                const auto serial=core.serial_state();
                const int64_t pending=int64_t(serial.codec_rx_queued)-int64_t(serial.codec_rx_consumed);
                if(pending<32){words.assign(size_t(32-std::max<int64_t>(0,pending)),0);core.queue_codec_rx(words.data(),words.size());}
                s.cushion_rate=rate;
            }
        }
        if(!converted->empty()) {
            const int64_t handed=peak(converted->data(),converted->size());
            if(handed){s.handed_peak=std::max(s.handed_peak,handed);s.handed_at=s.handed_ever=instructions;}
            words.clear();for(const auto sample:*converted)words.push_back(uint16_t(sample));
            if(s.clocked_input)core.queue_line_rx(words.data(),words.size());else core.queue_codec_rx(words.data(),words.size());
            in_flight.insert(in_flight.end(),converted->begin(),converted->end());
            const auto serial=core.serial_state();
            const uint64_t pending=s.clocked_input?core.codec_state().codec_rx_size:
                serial.codec_rx_queued-serial.codec_rx_consumed;
            while(in_flight.size()>pending)in_flight.pop_front();
        }
    }
    void begin(C5xCore &core,int64_t total) {
        if(active)throw std::logic_error("native codec service already in progress");
        instructions=total;fallback=false;
        const uint64_t produced=core.line_tx_count();
        if(produced==s.codec_last) {
            s.idle+=batch;if(s.idle<frame_instructions)return;
            s.idle=0;fallback=true;
        } else {s.codec_last=produced;s.idle=0;collect(core);}
        active=fallback || line_buffer.size()>=frame_samples;
    }
    int resume(C5xCore &core) {
        while(active) {
            if(!in_frame) {
                frame.assign(frame_samples,0);
                for(size_t k=0;k<frame_samples && !line_buffer.empty();++k){frame[k]=line_buffer.front();line_buffer.pop_front();}
                port.begin(daa && daa->off_hook,frame.data(),frame.size(),int64_t(frame_samples),media::monotonic(),true);
                in_frame=true;
            }
            const int event=port.resume();if(event)return event;
            queue(core,port.exchange.output);
            if(daa) {
                daa->line_state=port.exchange.line_state();daa->observe(int64_t(frame_samples));
                if(!port.exchange.dialed.empty() && daa->operation==Originate)daa->operation=Dialing;
                dial_digits=port.exchange.dialed;
            }
            ++s.frames;in_frame=false;
            active=!fallback && line_buffer.size()>=frame_samples;
        }
        return 0;
    }
    // The bridge calls these at actual reset/rebuild edges, never on a batch
    // boundary. The analog stream and its FIR history survive the DSP reset.
    void reset(bool clear_buffer) {
        if(active || port.running)throw std::logic_error("cannot reset native media during a frame");
        s.tx_index=0;s.cushion_rate=0;
        if(clear_buffer)line_buffer.clear();
    }
    void rebuild(C5xCore &core) {
        reset(false);s.handed_peak=s.handed_at=0;
        words.clear();for(const auto sample:in_flight)words.push_back(uint16_t(sample));
        if(!words.empty())s.replayed=words.size();
        if(s.clocked_input)core.queue_line_rx(words.data(),words.size());else core.queue_codec_rx(words.data(),words.size());
    }
};
} // namespace courier::analog
