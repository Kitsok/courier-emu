// Nonblocking terminal transport used by the native analog runtime.
#pragma once
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <deque>
#include <poll.h>
#include <string>
#include <unistd.h>

namespace courier {
struct TerminalState {
    int64_t fd=-1,lamps_fd=-1;
    uint64_t received=0,sent=0,dropped=0,closed=0,pending=0;
};
class TerminalTransport {
    TerminalState &s;
    std::string output,lamps;
    size_t first=0;
public:
    explicit TerminalTransport(TerminalState &state):s(state) {}
    ~TerminalTransport(){close();}
    int drain() {
        while(first<output.size()&&!s.closed) {
            const auto n=::write(int(s.fd),output.data()+first,output.size()-first);
            if(n<0) {
                if(errno==EINTR)continue;
                if(errno==EAGAIN||errno==EWOULDBLOCK)break;
                if(errno==EIO||errno==EPIPE||errno==EBADF){s.closed=1;break;}
                return errno;
            }
            if(!n)break;
            first+=size_t(n);s.sent+=uint64_t(n);
        }
        s.pending=output.size()-first;
        if(!s.pending){output.clear();first=0;}
        else if(first>65536){output.erase(0,first);first=0;}
        return 0;
    }
    void enqueue(uint8_t byte) {
        output.push_back(char(byte));
        const size_t pending=output.size()-first;
        if(pending>65536){first+=pending-65536;s.dropped+=pending-65536;}
        s.pending=output.size()-first;
    }
    size_t pending_bytes() const {return output.size()-first;}
    int write(uint8_t byte) {enqueue(byte);return drain();}
    int64_t read(uint8_t *data,size_t limit) {
        const int error=drain();if(error)return -error;
        if(s.closed||!limit)return 0;
        ssize_t n;
        do {n=::read(int(s.fd),data,limit);}while(n<0&&errno==EINTR);
        if(n<0) {
            if(errno==EAGAIN||errno==EWOULDBLOCK)return 0;
            if(errno==EIO||errno==EBADF){s.closed=1;return 0;}
            return -errno;
        }
        if(!n)s.closed=1;
        s.received+=uint64_t(n);return n;
    }
    int wait(int milliseconds) {
        if(s.closed)return 1;
        pollfd p{int(s.fd),POLLIN,0};
        const int n=::poll(&p,1,milliseconds);
        if(n<0)return errno==EINTR?0:-errno;
        if(p.revents&POLLNVAL){s.closed=1;return 1;}
        return n>0;
    }
    int show_lamps(const char *data,size_t size) {
        if(s.lamps_fd<0||(size==lamps.size()&&!std::memcmp(data,lamps.data(),size)))return 0;
        std::string line(data,size);line+='\n';
        ssize_t n;
        do {n=::write(int(s.lamps_fd),line.data(),line.size());}while(n<0&&errno==EINTR);
        if(n<0) {
            if(errno==EAGAIN||errno==EWOULDBLOCK)return 0;
            if(errno==EPIPE||errno==EBADF){s.lamps_fd=-1;return 0;}
            return errno;
        }
        lamps.assign(data,size);return 0;
    }
    void close() {
        drain();s.closed=1;
        if(s.fd>=0){::close(int(s.fd));s.fd=-1;}
        if(s.lamps_fd>=0){::close(int(s.lamps_fd));s.lamps_fd=-1;}
    }
};
} // namespace courier
