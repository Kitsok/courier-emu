// Persistent 8 kHz subscriber-loop media bridge. No Python peer PCM callbacks.
#pragma once
#include "analog_devices.hpp"
#include "rtp_media.hpp"
#include <stdexcept>

namespace courier::analog {
struct LineMediaState {
    uint64_t frames=0,underrun_frames=0,underrun_samples=0,pending_peak=0;
};
struct LineMedia {
    Exchange &exchange;
    media::Media &transport;
    LineMediaState s;
    std::deque<int32_t> pending;
    std::vector<std::pair<uint64_t,uint64_t>> underruns;
    std::vector<int32_t> incoming,received;
    explicit LineMedia(Exchange &line,media::Media &rtp):exchange(line),transport(rtp) {
        if(line.s.sample_rate!=8000)throw std::invalid_argument("native SIP media requires an 8 kHz loop");
        if(line.native_peer)throw std::invalid_argument("exchange already has a native media owner");
        line.native_peer_context=this;line.native_peer=&dispatch;
    }
    ~LineMedia() {
        if(exchange.native_peer_context==this){exchange.native_peer=nullptr;exchange.native_peer_context=nullptr;}
    }
    LineMedia(const LineMedia &)=delete;
    LineMedia &operator=(const LineMedia &)=delete;
    static void dispatch(void *context,Exchange &line) {static_cast<LineMedia *>(context)->render(line);}
    void render(Exchange &line) {
        // Match the reference's connected 80-sample subframes, including a
        // short transmit block and draining all newly received audio at once.
        const size_t available=line.position<int64_t(line.tx.size())
            ?std::min<size_t>(size_t(line.step),line.tx.size()-size_t(line.position)):0;
        if(available)transport.send(line.tx.data()+line.position,available,false,media::monotonic());
        {
            std::lock_guard<std::recursive_mutex> lock(transport.mutex);
            const size_t count=transport.values(1,nullptr,0,false);
            incoming.resize(count);transport.values(1,incoming.data(),count,true);
        }
        pending.insert(pending.end(),incoming.begin(),incoming.end());
        s.pending_peak=std::max<uint64_t>(s.pending_peak,pending.size());
        const size_t count=size_t(line.step),copied=std::min(count,pending.size());
        received.assign(count,0);std::copy_n(pending.begin(),copied,received.begin());
        pending.erase(pending.begin(),pending.begin()+copied);
        if(copied<count) {
            ++s.underrun_frames;s.underrun_samples+=count-copied;
            if(underruns.size()<64)underruns.emplace_back(s.frames,count-copied);
        }
        line.peer_result(received.data(),received.size());
    }
};
} // namespace courier::analog
