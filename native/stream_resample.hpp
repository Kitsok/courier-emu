// Complete native streaming converter, including its kernels and retune state.
#pragma once
#include "resample.hpp"
#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>
#include <mutex>

#if defined(__clang__)
#pragma clang fp contract(off)
#elif defined(__GNUC__)
#pragma GCC push_options
#pragma GCC optimize ("fp-contract=off")
#endif
namespace courier::resample {
using Kernel=std::vector<double>;

inline double kernel_sum(const std::vector<double> &values,bool compensated) {
    double hi=0,lo=0;
    for(const double value:values) {
        if(!compensated){hi+=value;continue;}
        const double sum=hi+value;
        lo+=std::abs(hi)>=std::abs(value)?(hi-sum)+value:(value-sum)+hi;
        hi=sum;
    }
    return compensated?hi+lo:hi;
}
inline const std::vector<double> &windows() {
    static const std::vector<double> table=[] {
        std::vector<double> result(size_t(PHASES*TAPS));
        const double norm=bessel_i0(KAISER_BETA);
        for(long phase=0;phase<=PHASES/2;++phase) {
            const double fraction=double(phase)/PHASES;
            for(long k=0;k<TAPS;++k) {
                const double t=double(k-(HALF_TAPS-1))-fraction,ratio=t/HALF_TAPS;
                const double value=std::abs(ratio)<1?bessel_i0(KAISER_BETA*std::sqrt(1-ratio*ratio))/norm:0;
                result[size_t(phase*TAPS+k)]=value;
                if(phase>0 && phase<PHASES/2)result[size_t((PHASES-phase)*TAPS+TAPS-1-k)]=value;
            }
        }
        return result;
    }();
    return table;
}
inline std::shared_ptr<const Kernel> kernel_for(double cutoff,bool compensated) {
    // Match round(cutoff, 9), including its decimal-to-binary rounding rather
    // than multiplying by 1e9 and introducing a second rounding at a half.
    char text[64];std::snprintf(text,sizeof text,"%.9f",cutoff);
    const double key=std::strtod(text,nullptr);
    static std::mutex mutex;
    static std::map<std::pair<double,bool>,std::shared_ptr<const Kernel>> cache;
    std::lock_guard<std::mutex> lock(mutex);
    const auto found=cache.find({key,compensated});if(found!=cache.end())return found->second;
    auto table=std::make_shared<Kernel>(size_t(PHASES*TAPS));
    const auto &window=windows();const double pi=3.141592653589793;
    std::vector<double> row(size_t(TAPS),0.0);
    for(long phase=0;phase<PHASES;++phase) {
        const double fraction=double(phase)/PHASES;
        for(long k=0;k<TAPS;++k) {
            const double t=double(k-(HALF_TAPS-1))-fraction,x=2*key*t;
            const double sinc=x==0?1:std::sin(pi*x)/(pi*x);
            row[size_t(k)]=2*key*sinc*window[size_t(phase*TAPS+k)];
        }
        const double total=kernel_sum(row,compensated);
        for(long k=0;k<TAPS;++k)(*table)[size_t(phase*TAPS+k)]=row[size_t(k)]/total;
    }
    cache[{key,compensated}]=table;
    return table;
}

struct StreamState {
    double input_rate=0,output_rate=0,position=0,input_time=0,next_time=0;
    uint64_t converted=0,timed=0;
};
struct Stream {
    StreamState s;
    bool precise=true,compensated=true;
    std::vector<double> history=std::vector<double>(TAPS,0),recent=std::vector<double>(2*TAPS,0);
    Timed timed;
    std::shared_ptr<const Kernel> kernel;
    std::vector<int16_t> out;
    explicit Stream(bool dot_precise=true,bool sum_compensated=true):precise(dot_precise),compensated(sum_compensated) {
        timed.norm=bessel_i0(KAISER_BETA);
    }
    void convert(const int16_t *samples,size_t count,double input,double output) {
        out.clear();if(!count)return;
        if(input>0 && output>0 && (s.timed || (s.input_rate>0 && input!=s.input_rate))) {
            if(!s.timed) {
                timed.history=recent;timed.times.clear();
                for(int64_t k=-int64_t(recent.size());k<0;++k)timed.times.push_back(double(k)/s.input_rate);
                timed.input_time=s.input_time;
                timed.next_time=(s.position-HALF_TAPS-1)/s.input_rate;
                timed.input_rate=s.input_rate;timed.output_rate=s.output_rate;s.timed=1;
            }
            kernel=kernel_for(.98*std::min(input,output)/2/input,compensated);
            timed.run(samples,count,input,output,kernel->data());timed.commit();out=timed.out;
            s.input_rate=input;s.output_rate=output;s.input_time=timed.input_time;s.next_time=timed.next_time;
            s.converted+=out.size();return;
        }
        for(size_t k=0;k<count;++k)recent.push_back(double(samples[k]));
        if(recent.size()>size_t(2*TAPS))recent.erase(recent.begin(),recent.end()-2*TAPS);
        if(input<=0 || output<=0 || (input==output && s.input_rate==0)) {
            for(size_t k=0;k<count;++k)history.push_back(double(samples[k]));
            if(history.size()>size_t(TAPS))history.erase(history.begin(),history.end()-TAPS);
            out.assign(samples,samples+count);return;
        }
        if(input!=s.input_rate || output!=s.output_rate) {
            const bool changed=input!=s.input_rate;
            s.input_rate=input;s.output_rate=output;
            kernel=kernel_for(.98*std::min(input,output)/2/input,compensated);
            if(changed)s.position=0;
        }
        for(size_t k=0;k<count;++k)history.push_back(double(samples[k]));
        const double step=input/output;
        const size_t capacity=size_t(std::ceil(std::max(0.0,double(history.size())-TAPS-s.position)/step))+2;
        out.resize(capacity);
        const size_t count_out=fixed(history.data(),history.size(),kernel->data(),step,s.position,precise,
                                     out.data(),out.size(),&s.position);
        out.resize(count_out);
        const size_t consumed=history.size()-TAPS;
        history.erase(history.begin(),history.begin()+consumed);s.position-=double(consumed);
        s.converted+=out.size();
    }
};
} // namespace courier::resample
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC pop_options
#endif
