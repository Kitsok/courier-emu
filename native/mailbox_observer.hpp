// Bounded mailbox diagnostics. Only the CPU thread writes these records;
// host observers copy snapshots while guest execution has yielded.
#pragma once
#include <array>
#include <algorithm>
#include <cstdint>

namespace courier {
struct MailboxObserverState {
    uint64_t words=0,history_count=0,history_overwritten=0,summary_count=0,summary_overflow=0;
    uint64_t history_enabled=1;
};
struct MailboxRecord {uint64_t sequence,instructions,pc,header,data;};
struct MailboxSummary {uint64_t key=0,count=0,instructions=0,pc=~uint64_t(0),order=0;};
static_assert(sizeof(MailboxRecord)==40&&sizeof(MailboxSummary)==40);
struct MailboxObserver {
    static constexpr size_t history_capacity=64,summary_capacity=4096;
    MailboxObserverState &s;
    std::array<MailboxRecord,history_capacity> history{};
    std::array<MailboxSummary,summary_capacity> summaries{};
    size_t next=0;
    explicit MailboxObserver(MailboxObserverState &state):s(state) {}
    void record(uint16_t header,uint16_t data,uint64_t instructions,uint64_t pc) {
        s.words+=2;
        const auto sequence=s.words/2;
        if(s.history_enabled) {
            history[next]={sequence,instructions,pc,header,data};next=(next+1)%history_capacity;
            if(s.history_count<history_capacity)++s.history_count;else ++s.history_overwritten;
        }
        const uint32_t key=uint32_t(header)<<16|data;
        size_t at=uint32_t(key*uint32_t(2654435761u))>>20;
        // Bound lookup time even when diagnostics encounter many unique words.
        for(unsigned probe=0;probe<64;++probe,at=(at+1)%summary_capacity) {
            auto &row=summaries[at];
            if(!row.count) {
                row={key,1,instructions,pc,sequence};++s.summary_count;return;
            }
            if(row.key==key) {
                ++row.count;if(row.pc==~uint64_t(0))row.pc=pc;return;
            }
        }
        ++s.summary_overflow;
    }
    size_t copy_history(MailboxRecord *out,size_t capacity) const {
        const size_t count=std::min<size_t>(capacity,s.history_count);
        const size_t first=(next+history_capacity-size_t(s.history_count))%history_capacity;
        for(size_t k=0;k<count;++k)out[k]=history[(first+k)%history_capacity];
        return size_t(s.history_count);
    }
    size_t copy_summaries(MailboxSummary *out,size_t capacity) const {
        size_t count=0;
        for(const auto &row:summaries)if(row.count&&count<capacity)out[count++]=row;
        return size_t(s.summary_count);
    }
};
} // namespace courier
