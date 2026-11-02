// Native mono PCM WAV sink for subscriber-loop diagnostics.
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

namespace courier::media {
class PcmRecording {
    FILE *file_=nullptr;
    uint32_t bytes_=0,rate_=8000;
    void header() {
        uint8_t h[44]={'R','I','F','F',0,0,0,0,'W','A','V','E','f','m','t',' ',16,0,0,0,1,0,1,0,
                       0,0,0,0,0,0,0,0,2,0,16,0,'d','a','t','a',0,0,0,0};
        auto put=[&](int at,uint32_t value){for(int k=0;k<4;++k)h[at+k]=uint8_t(value>>(8*k));};
        put(4,36+bytes_);put(24,rate_);put(28,rate_*2);put(40,bytes_);
        if(std::fseek(file_,0,SEEK_SET) || std::fwrite(h,1,44,file_)!=44 || std::fseek(file_,0,SEEK_END))
            throw std::runtime_error("cannot update native PCM recording header");
    }
public:
    explicit PcmRecording(const std::string &path,uint32_t rate=8000):rate_(rate) {
        file_=std::fopen(path.c_str(),"wb");
        if(!file_)throw std::runtime_error("cannot open native PCM recording: "+path);
        try{header();}catch(...){std::fclose(file_);file_=nullptr;throw;}
    }
    ~PcmRecording(){if(file_)std::fclose(file_);}
    PcmRecording(const PcmRecording &)=delete;
    void write(const int32_t *data,size_t available,size_t count) {
        if(count>(UINT32_MAX-36-bytes_)/2)throw std::runtime_error("native PCM recording exceeds WAV size limit");
        std::vector<uint8_t> block(count*2);
        for(size_t k=0;k<count;++k) {
            const int16_t sample=int16_t(k<available?std::clamp<int32_t>(data[k],-32768,32767):0);
            block[2*k]=uint8_t(sample);block[2*k+1]=uint8_t(uint16_t(sample)>>8);
        }
        if(std::fwrite(block.data(),1,block.size(),file_)!=block.size())throw std::runtime_error("cannot write native PCM recording");
        bytes_+=uint32_t(block.size());header();
    }
};
} // namespace courier::media
