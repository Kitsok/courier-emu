// A bounded media-clock wait; signalling and terminal reads stay in Python.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <poll.h>
#include <sys/select.h>
#include <time.h>

namespace courier {
struct PacerWait {
    uint64_t enabled=0, waits=0, wakeups=0, resume_flags=0;
    double interval=0, waited=0, port_waited=0;
};
inline double pacer_now() {
    timespec now;
    if(clock_gettime(CLOCK_MONOTONIC,&now))return -1;
    return double(now.tv_sec)+double(now.tv_nsec)*1e-9;
}
// -1: original Python service required, 0: no lead, 1: timeout,
// 2/4: console/signalling wakeup, 8: interrupted/error wait.
inline int pacer_wait(PacerWait &s,int console,int signal,double deadline,double signal_deadline) {
    if(!s.enabled || console<0 || signal<0 || console>=FD_SETSIZE || signal>=FD_SETSIZE)return -1;
    const double before=pacer_now();
    if(before<0 || !std::isfinite(deadline) || !(s.interval>0))return -1;
    const double delay=std::min(s.interval,deadline-before);
    if(delay<=0)return 0;
    if(signal_deadline<=before+delay)return -1;
    pollfd descriptors[2]={{console,POLLIN,0},{signal,POLLIN,0}};
    if(::poll(descriptors,2,0)!=0)return -1;
    fd_set read;
    FD_ZERO(&read);FD_SET(console,&read);FD_SET(signal,&read);
    timespec timeout{time_t(delay),long((delay-std::floor(delay))*1e9)};
    const int result=::pselect(std::max(console,signal)+1,&read,nullptr,nullptr,&timeout,nullptr);
    const double after=pacer_now();
    ++s.waits;
    const double elapsed=after>=before?after-before:0;
    s.waited+=elapsed;s.port_waited+=elapsed;
    if(result<0)return 8;
    if(!result)return 1;
    int flags=0;
    if(FD_ISSET(console,&read)){flags|=2;++s.wakeups;}
    if(FD_ISSET(signal,&read))flags|=4;
    return flags;
}
}
