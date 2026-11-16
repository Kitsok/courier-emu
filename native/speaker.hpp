// Bounded asynchronous speaker tap; modem frames never wait for playback.
#pragma once
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <fcntl.h>
#include <mutex>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <spawn.h>
#include <string>
#include <stdexcept>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>
extern char **environ;
namespace courier {
class Speaker {
    std::atomic<unsigned> references{1};
    std::mutex mutex;
    std::condition_variable changed;
    std::deque<std::vector<uint8_t>> frames;
    std::string player;
    double volume;
    bool enabled=false,stopped=false,disabled=false;
    uint64_t generation=0;
    int error=0;
    std::thread worker;
    static void reap(pid_t pid) {
        if(pid<=0)return;
        for(unsigned phase=0;phase<3;++phase) {
            if(phase)::kill(pid,phase==1?SIGTERM:SIGKILL);
            for(unsigned k=0;k<20;++k) {
                const auto result=::waitpid(pid,nullptr,WNOHANG);
                if(result==pid||(result<0&&errno==ECHILD))return;
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
            }
        }
        while(::waitpid(pid,nullptr,0)<0&&errno==EINTR){}
    }
    int launch(pid_t &pid) {
        int pipefd[2];if(::pipe(pipefd))return -errno;
        for(const auto fd:pipefd)::fcntl(fd,F_SETFD,FD_CLOEXEC);
        posix_spawn_file_actions_t actions;
        int status=::posix_spawn_file_actions_init(&actions);
        if(!status) {
            ::posix_spawn_file_actions_adddup2(&actions,pipefd[0],STDIN_FILENO);
            ::posix_spawn_file_actions_addclose(&actions,pipefd[1]);
            ::posix_spawn_file_actions_addopen(&actions,STDOUT_FILENO,"/dev/null",O_WRONLY,0);
            ::posix_spawn_file_actions_addopen(&actions,STDERR_FILENO,"/dev/null",O_WRONLY,0);
            const char *args[]={player.c_str(),"--raw","--format=s16le","--rate=8000",
                "--channels=1","--latency-msec=60","--client-name=courier-emu",
                "--stream-name=Courier speaker",nullptr};
            status=::posix_spawnp(&pid,player.c_str(),&actions,nullptr,
                                 const_cast<char **>(args),environ);
            ::posix_spawn_file_actions_destroy(&actions);
        }
        ::close(pipefd[0]);
        if(status){::close(pipefd[1]);return -status;}
        if(::fcntl(pipefd[1],F_SETFL,O_NONBLOCK)<0) {
            const auto code=errno;::close(pipefd[1]);reap(pid);pid=-1;return -code;
        }
        return pipefd[1];
    }
    void run() {
        sigset_t mask;::sigemptyset(&mask);::sigaddset(&mask,SIGPIPE);
        ::pthread_sigmask(SIG_BLOCK,&mask,nullptr);
        pid_t pid=-1;int fd=-1;uint64_t playing=0;
        auto close_player=[&](){if(fd>=0){::close(fd);fd=-1;}reap(pid);pid=-1;};
        try {
            while(true) {
                std::vector<uint8_t> frame;uint64_t serial;
                {
                    std::unique_lock lock(mutex);
                    changed.wait(lock,[&]{return stopped||playing!=generation||!frames.empty();});
                    if(stopped)break;
                    serial=generation;
                    if(playing!=serial) {
                        playing=serial;lock.unlock();close_player();continue;
                    }
                    if(!enabled||frames.empty())continue;
                    frame=std::move(frames.front());frames.pop_front();
                }
                if(fd<0) {
                    fd=launch(pid);
                    if(fd<0){std::lock_guard lock(mutex);error=-fd;disabled=true;frames.clear();break;}
                }
                size_t offset=0;
                const auto deadline=std::chrono::steady_clock::now()+std::chrono::milliseconds(100);
                while(offset<frame.size()&&std::chrono::steady_clock::now()<deadline) {
                    {std::lock_guard lock(mutex);if(stopped||!enabled||serial!=generation)break;}
                    pollfd output{fd,POLLOUT,0};const auto ready=::poll(&output,1,20);
                    if(ready<0&&errno==EINTR)continue;
                    if(ready<0)throw std::runtime_error("speaker output poll failed");
                    if(!ready)continue;
                    const auto wrote=::write(fd,frame.data()+offset,frame.size()-offset);
                    if(wrote<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;
                    if(wrote<=0)throw std::runtime_error("speaker player closed its input");
                    offset+=size_t(wrote);
                }
                if(offset<frame.size())close_player();
            }
        } catch(...) {std::lock_guard lock(mutex);error=EIO;disabled=true;frames.clear();}
        close_player();
    }
public:
    Speaker(const char *command,double gain):player(command?command:""),volume(gain),disabled(player.empty()) {
        if(!std::isfinite(gain)||gain<0||gain>1)throw std::invalid_argument("invalid speaker volume");
        if(!disabled)worker=std::thread([this]{run();});
    }
    ~Speaker(){close();}
    void retain(){++references;}
    void release(){if(--references==0)delete this;}
    void close() {
        {std::lock_guard lock(mutex);stopped=true;frames.clear();changed.notify_all();}
        if(worker.joinable())worker.join();
    }
    void enable(bool value) {
        std::lock_guard lock(mutex);
        if(enabled!=value){enabled=value;++generation;frames.clear();changed.notify_all();}
    }
    void feed(const int32_t *tx,size_t nt,const int32_t *rx,size_t nr) {
        std::lock_guard lock(mutex);
        if(!enabled||disabled||stopped)return;
        const size_t count=std::min(nt,nr);
        for(size_t start=0;start<count;start+=160) {
            const size_t end=std::min(start+160,count);std::vector<uint8_t> frame;
            frame.reserve(2*(end-start));
            for(size_t k=start;k<end;++k) {
                const double mixed=std::nearbyint(double(int64_t(tx[k])+rx[k])*volume);
                const auto sample=int16_t(std::max(-32768.0,std::min(32767.0,mixed)));
                frame.push_back(uint8_t(sample));frame.push_back(uint8_t(uint16_t(sample)>>8));
            }
            if(frames.size()==10)frames.pop_front();frames.push_back(std::move(frame));
        }
        changed.notify_one();
    }
    unsigned status() {
        std::lock_guard lock(mutex);
        return unsigned(enabled)|(unsigned(disabled)<<1)|(unsigned(error!=0)<<2);
    }
};
} // namespace courier
