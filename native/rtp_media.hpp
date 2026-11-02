// Authoritative RTP media transport. SIP signalling stays on the control plane;
// sockets, queues, G.711 conversion and packet timing do not require the GIL.
#pragma once
#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <deque>
#include <mutex>
#include <set>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>
#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

namespace courier::media {
inline double monotonic() {
    timespec now{};clock_gettime(CLOCK_MONOTONIC,&now);
    return double(now.tv_sec)+double(now.tv_nsec)*1e-9;
}
inline int32_t decode_ulaw(uint8_t value) {
    value=uint8_t(~value);int32_t sample=((value&15)<<3)+132;
    sample<<=(value&0x70)>>4;sample-=132;
    return value&128?-sample:sample;
}
inline int32_t decode_alaw(uint8_t value) {
    value^=0x55;int32_t sample=(value&15)<<4;const int segment=(value&0x70)>>4;
    sample=segment==0?sample+8:(sample+0x108)<<(segment-1);
    return value&128?sample:-sample;
}
inline uint8_t encode_ulaw(int32_t sample) {
    sample=std::clamp(sample,int32_t(-32768),int32_t(32767));
    const int sign=sample<0?128:0;if(sign)sample=-sample;
    sample=std::min(sample,int32_t(32635))+132;
    int exponent=7,mask=0x4000;
    while(exponent && !(sample&mask)){--exponent;mask>>=1;}
    return uint8_t(~(sign|(exponent<<4)|((sample>>(exponent+3))&15)));
}
inline uint8_t encode_alaw(int32_t sample) {
    sample=std::clamp(sample,int32_t(-32768),int32_t(32767))>>3;
    const int mask=sample>=0?0xd5:0x55;if(sample<0)sample=-sample-1;
    const int ends[8]={0x1f,0x3f,0x7f,0xff,0x1ff,0x3ff,0x7ff,0xfff};
    int segment=0;while(segment<8 && sample>ends[segment])++segment;
    if(segment==8)return uint8_t(0x7f^mask);
    const int shift=segment<2?1:segment;
    return uint8_t(((segment<<4)|((sample>>shift)&15))^mask);
}

// Order is shared with the control-plane adapter. Queued sizes are computed
// in snapshots; all actual storage and mutation stay in Media.
struct State {
    uint64_t sequence=0,timestamp=0,ssrc=0,packets_sent=0,packets_received=0;
    uint64_t octets_sent=0,octets_received=0,preanswer_discarded=0;
    uint64_t primed=0,buffer_samples=480,clocked=0,session_state=0,payload_type=0,law=0,codewords=0;
    uint64_t tx_audio_size=0,rx_audio_size=0,tx_codewords_size=0,rx_codewords_size=0,error=0;
    double next_at=0,gain=1;
};

class Media {
public:
    std::recursive_mutex mutex;
    State state;
private:
    int fd_=-1;
    sockaddr_in remote_{};
    bool has_remote_=false,stop_=false;
    std::set<std::pair<uint32_t,uint16_t>> retired_;
    std::deque<int32_t> tx_audio_,rx_audio_,tx_words_,rx_words_;
    std::array<int32_t,256> decode_{};
    std::thread thread_;
    std::condition_variable_any wake_;

    std::deque<int32_t> &queue(int which) {
        switch(which){case 0:return tx_audio_;case 1:return rx_audio_;case 2:return tx_words_;default:return rx_words_;}
    }
    static std::pair<uint32_t,uint16_t> peer(const sockaddr_in &address) {
        return {address.sin_addr.s_addr,address.sin_port};
    }
    static sockaddr_in address(const char *ip,unsigned port) {
        sockaddr_in result{};result.sin_family=AF_INET;result.sin_port=htons(uint16_t(port));
        if(!ip || inet_pton(AF_INET,ip,&result.sin_addr)!=1)throw std::invalid_argument("RTP peer must be an IPv4 address");
        return result;
    }
    void decode_table() {
        for(unsigned k=0;k<256;++k)decode_[k]=state.law?decode_alaw(uint8_t(k)):decode_ulaw(uint8_t(k));
    }
    void receive_locked() {
        uint8_t packet[2048];sockaddr_in source{};
        for(;;) {
            socklen_t length=sizeof source;
            const ssize_t count=::recvfrom(fd_,packet,sizeof packet,MSG_DONTWAIT,reinterpret_cast<sockaddr *>(&source),&length);
            if(count<0) {
                if(errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR)state.error=uint64_t(errno);
                return;
            }
            if(retired_.count(peer(source)) || count<12 || (packet[1]&0x7f)!=state.payload_type)continue;
            auto &destination=state.codewords?rx_words_:rx_audio_;
            for(ssize_t k=12;k<count;++k)destination.push_back(state.codewords?packet[k]:decode_[packet[k]]);
            ++state.packets_received;state.octets_received+=uint64_t(count-12);
        }
    }
    void flush_locked(double now) {
        auto &source=state.codewords?tx_words_:tx_audio_;
        if(state.clocked) {
            if(state.session_state!=5){state.primed=0;return;}
            if(!state.primed) {
                if(source.size()<state.buffer_samples)return;
                state.primed=1;state.next_at=now;
            } else if(now>=state.next_at && source.size()<160){state.primed=0;return;}
        }
        while(state.session_state==5 && has_remote_ && source.size()>=160 && now>=state.next_at) {
            uint8_t packet[172];packet[0]=0x80;packet[1]=uint8_t(state.payload_type);
            const uint16_t sequence=htons(uint16_t(state.sequence));
            const uint32_t stamp=htonl(uint32_t(state.timestamp)),ssrc=htonl(uint32_t(state.ssrc));
            std::memcpy(packet+2,&sequence,2);std::memcpy(packet+4,&stamp,4);std::memcpy(packet+8,&ssrc,4);
            for(unsigned k=0;k<160;++k) {
                const int32_t sample=source.front();source.pop_front();
                packet[12+k]=state.codewords?uint8_t(sample):state.law?encode_alaw(sample):encode_ulaw(sample);
            }
            if(::sendto(fd_,packet,sizeof packet,0,reinterpret_cast<const sockaddr *>(&remote_),sizeof remote_)<0) {
                state.error=uint64_t(errno);return;
            }
            state.sequence=(state.sequence+1)&0xffff;
            state.timestamp=(state.timestamp+160)&0xffffffff;
            state.next_at+=160.0/8000.0;
            ++state.packets_sent;state.octets_sent+=160;
        }
    }
    void loop() {
        std::unique_lock<std::recursive_mutex> lock(mutex);
        while(!stop_) {
            receive_locked();flush_locked(monotonic());
            if(state.error)return;
            const double delay=state.primed?std::max(.001,state.next_at-monotonic()):.02;
            wake_.wait_for(lock,std::chrono::duration<double>(std::min(.02,delay)));
        }
    }
public:
    explicit Media(int fd) {
        fd_=::dup(fd);
        if(fd_<0)throw std::runtime_error("cannot duplicate RTP socket");
        const int flags=::fcntl(fd_,F_GETFL,0);
        if(flags<0 || ::fcntl(fd_,F_SETFL,flags|O_NONBLOCK)<0) {
            ::close(fd_);fd_=-1;throw std::runtime_error("cannot set nonblocking RTP socket");
        }
        decode_table();
    }
    ~Media(){stop();if(fd_>=0)::close(fd_);}
    void stop() {
        {std::lock_guard<std::recursive_mutex> lock(mutex);stop_=true;wake_.notify_all();}
        if(thread_.joinable())thread_.join();
    }
    void clock(uint64_t samples) {
        if(samples<160)throw std::invalid_argument("RTP transmit buffer must hold a packet");
        std::lock_guard<std::recursive_mutex> lock(mutex);
        state.buffer_samples=samples;
        if(state.clocked)return;
        stop_=false;thread_=std::thread([this]{loop();});state.clocked=1;
    }
    void configure(uint64_t session_state,uint64_t payload,uint64_t law,uint64_t words,double gain) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        state.session_state=session_state;state.payload_type=payload;state.codewords=words;state.gain=gain;
        if(state.law!=law){state.law=law;decode_table();}
        wake_.notify_all();
    }
    void remote(const char *ip,unsigned port) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        if(ip){remote_=address(ip,port);has_remote_=true;}else has_remote_=false;
    }
    void retire(const char *ip,unsigned port,int operation) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        if(!ip){retired_.clear();return;}
        const auto key=peer(address(ip,port));
        if(operation)retired_.insert(key);else retired_.erase(key);
    }
    State snapshot() {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        State result=state;
        result.tx_audio_size=tx_audio_.size();result.rx_audio_size=rx_audio_.size();
        result.tx_codewords_size=tx_words_.size();result.rx_codewords_size=rx_words_.size();
        return result;
    }
    void set(unsigned field,uint64_t value) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        // Only the scalar metadata/counters are externally writable.
        if(field<10)std::memcpy(reinterpret_cast<uint8_t *>(&state)+field*sizeof(uint64_t),&value,sizeof value);
        else if(field==19)state.error=value;
    }
    void next(double value) {std::lock_guard<std::recursive_mutex> lock(mutex);state.next_at=value;}
    void poll(double now) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        receive_locked();if(!state.clocked)flush_locked(now);
    }
    void receive() {std::lock_guard<std::recursive_mutex> lock(mutex);receive_locked();}
    void flush(double now) {std::lock_guard<std::recursive_mutex> lock(mutex);if(!state.clocked)flush_locked(now);}
    void send(const int32_t *data,size_t count,bool words,double now) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        if(state.session_state==5) {
            auto &destination=words?tx_words_:tx_audio_;
            for(size_t k=0;k<count;++k) {
                const int32_t value=words?data[k]:int32_t(std::nearbyint(double(data[k])*state.gain));
                if(!words && destination.size()>=16000)destination.pop_front();
                destination.push_back(value);
            }
        } else if(state.session_state>=1 && state.session_state<=3)state.preanswer_discarded+=count;
        wake_.notify_all();if(!state.clocked)flush_locked(now);
    }
    size_t values(int which,int32_t *out,size_t capacity,bool consume) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        auto &source=queue(which);const size_t count=source.size(),n=std::min(count,capacity);
        if(out)std::copy_n(source.begin(),n,out);
        if(consume)source.erase(source.begin(),source.begin()+n);
        return count;
    }
    void clear(int which) {std::lock_guard<std::recursive_mutex> lock(mutex);queue(which).clear();}
    void append(int which,const int32_t *data,size_t count) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        auto &destination=queue(which);
        for(size_t k=0;k<count;++k){if(which==0 && destination.size()>=16000)destination.pop_front();destination.push_back(data[k]);}
        wake_.notify_all();
    }
};
} // namespace courier::media
