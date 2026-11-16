// SPDX-License-Identifier: BSD-3-Clause
// MAME instruction execution with Courier's existing memory/I/O bus.
#include <Python.h>
#include <vector>
#include "emu.h"
#include "i186.h"
#include "i86inline.h"
#include "interrupts186.hpp"
#include "serial186.hpp"
#include "timers186.hpp"
#include "microwire93c66.hpp"
#include "dte186.hpp"
#include "dte_transmit.hpp"

namespace {
struct Stop {};
struct Redirect {};
struct Interrupt {};
class CourierCpu;

// Existing native board-worker ABI, shared with the reference CPU engine.
struct PollCpu {
    uint32_t *regs;
    uint8_t *memory;
    std::size_t memory_size;
    const uint8_t *guard;
    uint8_t *io_events;
    uint32_t io_event_count;
    uint8_t *mmio_events;
    uint32_t mmio_count;
    uint64_t batch_total;
};

class PlainSpace : public address_space {
public:
    uint8_t *memory=nullptr;
    uint8_t read_byte(offs_t a) override {return memory[a&0xfffff];}
    void write_byte(offs_t a,u8 value) override {memory[a&0xfffff]=value;}
};

class CourierCpu : public i80186_cpu_device {
public:
    CourierCpu(machine_config &config):i80186_cpu_device(config,"courier186",nullptr,20160000) {}
    uint8_t *memory=nullptr,*guard=nullptr;
    uint32_t *registers=nullptr;
    PyObject *callback=nullptr;
    uint64_t done=0;
    bool failed=false, stop_after=false, irq_fallback=false;
    courier::MachineServiceState *irqs=nullptr;
    courier::Serial186 *uart=nullptr;
    courier::Timers186 *timers=nullptr;
    courier::Microwire93c66 *eeprom=nullptr;
    courier::DteWire186 *wire=nullptr;
    courier::DteTransmit *output=nullptr;
    const uint8_t *device_access=nullptr,*host_ports=nullptr;
    uint8_t *mmio_events=nullptr;
    uint32_t mmio_count=0,mmio_capacity=0;
    using HostIo=int (*)(void*,int,uint16_t,int,uint16_t,uint64_t,uint16_t*);
    HostIo host_io=nullptr;
    void *host_context=nullptr;
    uint64_t host_base=0;
    using Poll=int (*)(void*,uint64_t,uint32_t,void*);
    Poll poll=nullptr;
    void *poll_context=nullptr;
    uint64_t poll_total=0,poll_next=0,poll_period=0;
    int poll_code=-1;
    uint32_t transfer_first=0,transfer_last=0;
    const uint8_t *interrupt_policy=nullptr;
    uint64_t *fault_counts=nullptr;

    void native_regs(uint32_t *values) const {
        for(unsigned i=0;i<8;++i)values[i]=m_regs.w[i];
        for(unsigned i=0;i<4;++i)values[8+i]=m_sregs[i];
        values[12]=m_ip;values[13]=CompressFlags();
    }
    void native_restore(const uint32_t *values) {
        for(unsigned i=0;i<8;++i)m_regs.w[i]=uint16_t(values[i]);
        for(unsigned i=0;i<4;++i)m_sregs[i]=uint16_t(values[8+i]);
        m_ip=uint16_t(values[12]);ExpandFlags(uint16_t(values[13]));
    }
    bool serial_access(uint32_t a,unsigned n,bool write) const {
        if(!uart||!irqs||!device_access||!mmio_events||a<0xff60||a>0xff6a
                ||(a&1)||(n!=1&&n!=2))return false;
        return (device_access[a&255]&(write?2:1)) &&
            (write ? a!=0xff66&&a!=0xff68 : a!=0xff6a);
    }
    bool timer_access(uint32_t a,unsigned n,bool write) const {
        if(!timers||!device_access||!mmio_events||(a&1)||(n!=1&&n!=2)
                ||!(device_access[a&255]&(write?2:1)))return false;
        if(a>=0xff30&&a<=0xff46&&a!=0xff44)return write||timers->answers_reads;
        return write&&(a==0xff08||(a>=0xff12&&a<=0xff1e));
    }
    bool timer_read(uint32_t a,unsigned n,uint32_t &value) {
        if(!timer_access(a,n,false))return false;
        const unsigned offset=(a-0xff30)/2,index=offset/4;
        const uint64_t total=timers->instruction_base+done;
        const int64_t tick=timers->tick_at(total);
        const uint32_t pc=((uint32_t(m_sregs[CS])<<4)+m_ip)&0xfffff;
        value=timers->read(a,n,total,pc<transfer_first||pc>=transfer_last);
        const unsigned entry=offset>10?offset-1:offset;
        ++timers->read_counts[entry][n-1];
        timers->read_mask|=uint64_t(1)<<(2*entry+n-1);
        timers->last_read_tick[index]=uint64_t(tick);
        return true;
    }
    bool pio_access(uint32_t a,unsigned n,bool write) const {
        return eeprom&&device_access&&mmio_events&&a>=0xff50&&a<=0xff5e
            &&!(a&1)&&(n==1||n==2)&&(device_access[a&255]&(write?2:1));
    }
    bool pio_read(uint32_t a,unsigned n,uint32_t &value) {
        if(!pio_access(a,n,false)||(a==0xff5a&&!wire))return false;
        value=memory[a];if(n==2)value|=uint32_t(memory[a+1])<<8;
        if(a==0xff5a) {
            value=(value&~0xa0u)|(eeprom->data_out?0x80:0)
                |(wire->level(int64_t(host_base+done))>0?0x20:0);
        }
        const unsigned index=(a-0xff50)/2;
        ++eeprom->pio_reads[index][n-1];
        eeprom->pio_read_mask|=uint64_t(1)<<(2*index+n-1);
        return true;
    }
    bool pio_write(uint32_t a,unsigned n,uint32_t value) {
        if(!pio_access(a,n,true))return false;
        if(a==0xff56) {
            if(host_io&&host_ports&&(host_ports[a]&2)) {
                uint16_t changed=0;
                if(!host_io(host_context,2,uint16_t(a),int(n),uint16_t(value),host_base+done,&changed))
                    return false;
                if(changed)stop_after=true;
            } else if(!(value&2)||((memory[a]^value)&0x8a))return false;
            eeprom->port1(value);
        } else if(a==0xff5e)eeprom->pio_data_in=bool(value&0x80);
        queue_write(a,n,value,8);return true;
    }
    void queue_write(uint32_t a,unsigned n,uint32_t value,unsigned applied) {
        if(mmio_count==mmio_capacity) {
            PyErr_SetString(PyExc_RuntimeError,"MAME MMIO batch capacity exceeded");
            failed=true;throw Stop{};
        }
        uint8_t *e=mmio_events+8*mmio_count++;
        e[0]=uint8_t(a);e[1]=uint8_t(a>>8);e[2]=uint8_t(a>>16);e[3]=uint8_t(a>>24);
        e[4]=uint8_t(value);e[5]=uint8_t(value>>8);e[6]=uint8_t(n);e[7]=uint8_t(applied);
        // Leave room for the largest next REP instruction before yielding.
        if(mmio_count>=mmio_capacity-65536)stop_after=true;
    }
    uint16_t port(unsigned direction,uint16_t p,unsigned n,uint16_t value=0) {
        uint16_t answer=0;
        if(host_io&&(host_ports[p]&direction)) {
            const int handled=host_io(host_context,int(direction),p,int(n),value,host_base+done+1,&answer);
            if(handled){if(handled>1)stop_after=true;return answer;}
        }
        return uint16_t(event(direction==1?3:4,p,n,value));
    }

    void publish() {native_regs(registers);}
    void restore() {native_restore(registers);}
    uint32_t event(unsigned kind,uint32_t address,unsigned size,uint32_t value=0) {
        if(output)output->flush();
        publish();
        PyObject *answer=PyObject_CallFunction(callback,"IIIIK",kind,address,size,value,
                                             (unsigned long long)done);
        if(!answer){failed=true;throw Stop{};}
        const uint64_t raw=PyLong_AsUnsignedLongLong(answer);Py_DECREF(answer);
        if(raw>>32)stop_after=true;
        const uint32_t result=uint32_t(raw);
        if(PyErr_Occurred()){failed=true;throw Stop{};}
        restore();return result;
    }
    void mapped(uint32_t a,unsigned n,unsigned permission) {
        for(unsigned i=0;i<n;++i)if(!(guard[(a+i)&0xfffff]&permission)) {
            PyErr_Format(PyExc_RuntimeError,"unmapped %s at 0x%x",
                         permission==1?"read":"write",a);
            failed=true;throw Stop{};
        }
    }
    uint32_t load(uint32_t a,unsigned n) {
        a&=0xfffff;mapped(a,n,1);
        if(serial_access(a,n,false)) {
            const unsigned index=(a-0xff60)/2;
            const uint32_t value=uart->read(a)&(n==1?255:65535);
            ++uart->native_reads;++uart->read_counts[index][n-1];
            uart->read_mask|=uint64_t(1)<<(2*index+n-1);
            memory[a]=uint8_t(value);if(n==2)memory[a+1]=uint8_t(value>>8);
            return value;
        }
        uint32_t timer_value;
        if(timer_read(a,n,timer_value)||pio_read(a,n,timer_value)) {
            memory[a]=uint8_t(timer_value);if(n==2)memory[a+1]=uint8_t(timer_value>>8);
            return timer_value;
        }
        if(guard[a]&16)event(1,a,n);
        uint32_t value=memory[a];
        if(n==2)value|=uint32_t(memory[(a+1)&0xfffff])<<8;
        return value;
    }
    void store(uint32_t a,unsigned n,uint32_t value) {
        a&=0xfffff;mapped(a,n,2);
        if(serial_access(a,n,true)) {
            ++uart->native_writes;
            const int byte=uart->write(a,value,*irqs);
            if(byte>=0&&output)stop_after=output->write(uint8_t(byte),n)||stop_after;
            else {if(byte>=0)stop_after=true;queue_write(a,n,value,4);}
        } else if(pio_write(a,n,value)) {
            // Device state and accounting are already committed.
        } else if(a!=0xff32&&timer_access(a,n,true)) {
            timers->write(a,n,value,timers->instruction_base+done);
            queue_write(a,n,value,2);
        } else if(mmio_events&&(guard[a]&64)) {
            const bool eoi=irqs&&irqs->irq_enabled&&a==0xff02;
            if(eoi)irqs->eoi(uint16_t(value));
            queue_write(a,n,value,eoi?1:0);
        } else if(guard[a]&32)event(2,a,n,value);
        memory[a]=uint8_t(value);
        if(n==2)memory[(a+1)&0xfffff]=uint8_t(value>>8);
    }
    uint8_t read_byte(uint32_t a) override {return uint8_t(load(a,1));}
    uint16_t read_word(uint32_t a) override {return uint16_t(load(a,2));}
    void write_byte(uint32_t a,uint8_t value) override {store(a,1,value);}
    void write_memory_byte_al(uint32_t a) override {store(a,1,m_regs.b[AL]);}
    void write_word(uint32_t a,uint16_t value) override {store(a,2,value);}
    uint8_t read_port_byte(uint16_t p) override {return uint8_t(port(1,p,1));}
    uint16_t read_port_word(uint16_t p) override {return port(1,p,2);}
    void write_port_byte(uint16_t p,uint8_t value) override {port(2,p,1,value);}
    void write_port_byte_al(uint16_t p) override {port(2,p,1,m_regs.b[AL]);}
    void write_port_word(uint16_t p,uint16_t value) override {port(2,p,2,value);}
    uint8_t fetch() override {
        const uint32_t a=((uint32_t(m_sregs[CS])<<4)+m_ip)&0xfffff;
        mapped(a,1,1);++m_ip;return memory[a];
    }
    void debugger_instruction_hook(offs_t pc) override {
        if(m_seg_prefix)return;
        if(guard[pc&0xfffff]&8) {
            const unsigned action=event(5,pc&0xfffff,1);
            if(action==0)throw Stop{};
            if(action==2)throw Redirect{};
        }
    }
    bool direct_interrupt(unsigned vector) const {
        if(vector>255||!interrupt_policy||(interrupt_policy[vector]&3)!=3)return false;
        for(unsigned k=0;k<4;++k) {
            const auto access=guard[vector*4+k];
            if(!(access&1)||(access&16))return false;
        }
        for(unsigned k=0;k<3;++k) {
            const uint32_t a=((uint32_t(m_sregs[SS])<<4)+uint16_t(m_regs.w[SP]-2*(k+1)))&0xfffff;
            for(unsigned j=0;j<2;++j) {
                const auto access=guard[(a+j)&0xfffff];
                if(!(access&2)||(access&32))return false;
            }
        }
        return true;
    }
    void interrupt(int vector,int trap=1) override {
        if(direct_interrupt(unsigned(vector))) {
            // Reuse MAME's FLAGS/CS/IP frame and interrupt flag handling.
            // CPU exceptions are not controller requests and need no EOI.
            i8086_common_cpu_device::interrupt(vector,trap);
            if(trap&&fault_counts){++fault_counts[0];++fault_counts[unsigned(vector)+1];}
            return;
        }
        // Host services and watched/guarded frames retain the existing hook.
        event(6,unsigned(vector),unsigned(trap));
        throw Interrupt{};
    }
    void begin() {m_halt=false;failed=stop_after=irq_fallback=false;done=mmio_count=0;poll_code=-1;restore();}
    bool halted() const {return m_halt;}
    bool service() {
        if(!poll||poll_total+done+1<poll_next)return true;
        if(output)output->flush();
        uint32_t values[14];native_regs(values);
        PollCpu cpu{values,memory,0x100000,guard,nullptr,0,
                    mmio_events,mmio_count,poll_total};
        const int code=poll(poll_context,host_base+done+1,values[13],&cpu);
        native_restore(values);
        if(code==1||code==4) {
            poll_next=poll_total+done+1+poll_period;
            // The reference worker's legacy IRQ entry consumes a dispatch
            // edge. Managed 186 IRQs use MAME's shadow in step() instead.
            if(code==4){++done;return false;}
            return true;
        }
        poll_code=code;throw Stop{};
    }
    void step() {
        // MAME maintains its STI/MOV-SS/POP-SS shadow across calls. Deliver
        // shared board requests before the next eligible instruction.
        if(irqs&&irqs->pending_mask&&!m_no_interrupt) {
            uint32_t regs[14];native_regs(regs);
            const int entered=irqs->dispatch(regs,memory,0x100000,guard);
            if(entered<0){irq_fallback=true;throw Stop{};}
            if(entered)native_restore(regs);
        }
        do {m_icount=1;execute_run();} while(m_seg_prefix_next);
    }
};

// Native context owns the backing buffers. Python APIs expose live views;
// their storage remains pinned while any native bus pointer can reference it.
struct NativeBuffer {
    PyObject *object=nullptr;
    Py_buffer view{};
    explicit NativeBuffer(Py_ssize_t size) {
        object=PyByteArray_FromStringAndSize(nullptr,size);
        if(!object)throw Stop{};
        if(PyObject_GetBuffer(object,&view,PyBUF_WRITABLE)<0) {
            Py_DECREF(object);object=nullptr;throw Stop{};
        }
        std::memset(view.buf,0,size_t(size));
    }
    ~NativeBuffer(){PyBuffer_Release(&view);Py_XDECREF(object);}
    uint8_t *data(){return static_cast<uint8_t*>(view.buf);}
};
struct Instance {
    NativeBuffer memory{0x100000},guard{0x100000},registers{14*4};
    running_machine machine;
    machine_config config{machine};
    PlainSpace space;
    CourierCpu cpu{config};
    std::vector<Py_buffer> devices;
    Instance() {
        devices.reserve(16);
        space.memory=cpu.memory=memory.data();cpu.guard=guard.data();
        cpu.registers=reinterpret_cast<uint32_t*>(registers.data());cpu.registers[13]=2;
        cpu.shim_set_space(AS_PROGRAM,&space);cpu.shim_set_space(AS_IO,&space);
        machine.set_cpu(&cpu);cpu.shim_start();cpu.shim_reset();
    }
    void release_devices() {
        for(auto &view:devices)if(view.obj)PyBuffer_Release(&view);
        devices.clear();
    }
    ~Instance(){release_devices();}
};

void destroy(PyObject *capsule) {delete static_cast<Instance*>(PyCapsule_GetPointer(capsule,"courier.mame186"));}
PyObject *create(PyObject *,PyObject *args) {
    if(!PyArg_ParseTuple(args,""))return nullptr;
    try {
        auto *instance=new Instance;
        PyObject *capsule=PyCapsule_New(instance,"courier.mame186",destroy);
        if(!capsule)delete instance;
        return capsule;
    }
    catch(const Stop &){return nullptr;}
    catch(const std::exception &e){PyErr_SetString(PyExc_RuntimeError,e.what());return nullptr;}
}
PyObject *buffers(PyObject *,PyObject *capsule) {
    auto *instance=static_cast<Instance*>(PyCapsule_GetPointer(capsule,"courier.mame186"));
    if(!instance)return nullptr;
    return Py_BuildValue("OOO",instance->memory.object,instance->guard.object,instance->registers.object);
}
PyObject *configure(PyObject *,PyObject *args) {
    PyObject *capsule,*bindings;
    if(!PyArg_ParseTuple(args,"OO",&capsule,&bindings))return nullptr;
    auto *instance=static_cast<Instance*>(PyCapsule_GetPointer(capsule,"courier.mame186"));
    if(!instance)return nullptr;
    auto &cpu=instance->cpu;
    instance->release_devices();
    cpu.irqs=nullptr;cpu.uart=nullptr;cpu.timers=nullptr;cpu.eeprom=nullptr;cpu.wire=nullptr;
    cpu.device_access=nullptr;cpu.mmio_events=nullptr;
    cpu.host_io=nullptr;cpu.host_context=nullptr;cpu.host_ports=nullptr;
    cpu.poll=nullptr;cpu.output=nullptr;
    if(bindings!=Py_None) {
        if(!PyTuple_Check(bindings)||PyTuple_GET_SIZE(bindings)!=16) {
            PyErr_SetString(PyExc_ValueError,"invalid MAME device bindings");return nullptr;
        }
        auto buffer=[&](unsigned index,Py_ssize_t size)->uint8_t* {
            PyObject *value=PyTuple_GET_ITEM(bindings,index);
            if(value==Py_None)return nullptr;
            if(!PyByteArray_Check(value)||PyByteArray_GET_SIZE(value)!=size) {
                PyErr_SetString(PyExc_ValueError,"invalid MAME device buffer");return nullptr;
            }
            instance->devices.push_back({});
            auto &view=instance->devices.back();
            if(PyObject_GetBuffer(value,&view,PyBUF_WRITABLE)<0)return nullptr;
            return static_cast<uint8_t*>(view.buf);
        };
        cpu.irqs=reinterpret_cast<courier::MachineServiceState*>(buffer(0,sizeof(courier::MachineServiceState)));
        cpu.uart=reinterpret_cast<courier::Serial186*>(buffer(1,sizeof(courier::Serial186)));
        cpu.device_access=buffer(2,256);
        cpu.mmio_events=buffer(3,8*8*65536);cpu.mmio_capacity=8*65536;
        if(PyTuple_GET_ITEM(bindings,4)!=Py_None) {
            cpu.host_io=reinterpret_cast<CourierCpu::HostIo>(PyLong_AsVoidPtr(PyTuple_GET_ITEM(bindings,4)));
            cpu.host_context=PyLong_AsVoidPtr(PyTuple_GET_ITEM(bindings,5));
            cpu.host_ports=buffer(6,65536);
        }
        cpu.timers=reinterpret_cast<courier::Timers186*>(buffer(8,sizeof(courier::Timers186)));
        cpu.eeprom=reinterpret_cast<courier::Microwire93c66*>(buffer(9,sizeof(courier::Microwire93c66)));
        cpu.wire=reinterpret_cast<courier::DteWire186*>(buffer(10,sizeof(courier::DteWire186)));
        if(PyTuple_GET_ITEM(bindings,12)!=Py_None)
            cpu.output=static_cast<courier::DteTransmit*>(PyLong_AsVoidPtr(PyTuple_GET_ITEM(bindings,12)));
        PyObject *span=PyTuple_GET_ITEM(bindings,13);
        cpu.transfer_first=cpu.transfer_last=0;
        if(span!=Py_None) {
            if(!PyTuple_Check(span)||PyTuple_GET_SIZE(span)!=2) {
                PyErr_SetString(PyExc_ValueError,"invalid timer transfer span");return nullptr;
            }
            cpu.transfer_first=uint32_t(PyLong_AsUnsignedLong(PyTuple_GET_ITEM(span,0)));
            cpu.transfer_last=uint32_t(PyLong_AsUnsignedLong(PyTuple_GET_ITEM(span,1)));
        }
        cpu.interrupt_policy=buffer(14,256);
        cpu.fault_counts=reinterpret_cast<uint64_t*>(buffer(15,8*257));
        PyObject *poll=PyTuple_GET_ITEM(bindings,11);
        if(poll!=Py_None) {
            if(!PyTuple_Check(poll)||PyTuple_GET_SIZE(poll)!=2) {
                PyErr_SetString(PyExc_ValueError,"invalid MAME worker binding");return nullptr;
            }
            cpu.poll=reinterpret_cast<CourierCpu::Poll>(PyLong_AsVoidPtr(PyTuple_GET_ITEM(poll,0)));
            cpu.poll_context=PyLong_AsVoidPtr(PyTuple_GET_ITEM(poll,1));
        }
        if(PyErr_Occurred())return nullptr;
        if(cpu.host_io&&!cpu.host_ports) {
            PyErr_SetString(PyExc_ValueError,"missing MAME native port table");return nullptr;
        }
    }
    Py_RETURN_NONE;
}
PyObject *stop(PyObject *,PyObject *capsule) {
    auto *instance=static_cast<Instance*>(PyCapsule_GetPointer(capsule,"courier.mame186"));
    if(!instance)return nullptr;
    instance->cpu.stop_after=true;Py_RETURN_NONE;
}
PyObject *run(PyObject *,PyObject *args) {
    PyObject *capsule,*callback;
    unsigned long long count,base,total,next,period;
    if(!PyArg_ParseTuple(args,"OKOKKKK",&capsule,&count,&callback,&base,&total,&next,&period))return nullptr;
    auto *instance=static_cast<Instance*>(PyCapsule_GetPointer(capsule,"courier.mame186"));
    if(!instance)return nullptr;
    if(!PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_ValueError,"invalid MAME bus callback");return nullptr;
    }
    auto &cpu=instance->cpu;cpu.callback=callback;
    cpu.host_base=base;cpu.poll_total=total;cpu.poll_next=next;cpu.poll_period=period;
    try {
        cpu.begin();
        while(cpu.done<count&&!cpu.stop_after) {
            // Keep host signal/stop handling responsive during native runs.
            // A handled signal can request a stop without raising an error.
            if(!(cpu.done&65535)) {
                if(PyErr_CheckSignals()<0){cpu.failed=true;throw Stop{};}
                if(cpu.stop_after)break;
            }
            try {if(!cpu.service())continue;cpu.step();++cpu.done;}
            catch(const Redirect &) {continue;}
            catch(const Interrupt &) {++cpu.done;break;}
            if(cpu.halted()||cpu.stop_after)break;
        }
    } catch(const Stop &) {}
      catch(const std::exception &e){PyErr_SetString(PyExc_RuntimeError,e.what());cpu.failed=true;}
    if(cpu.output)cpu.output->flush();
    if(cpu.failed)return nullptr;
    try {cpu.publish();}catch(const Stop &){return nullptr;}
    return Py_BuildValue("KiiIKi",(unsigned long long)cpu.done,cpu.halted(),cpu.irq_fallback,cpu.mmio_count,
                         (unsigned long long)cpu.poll_next,cpu.poll_code);
}
PyMethodDef methods[]={{"create",create,METH_VARARGS,"Create a native Courier CPU context."},
    {"buffers",buffers,METH_O,"Expose the context's live RAM and register buffers."},
    {"configure",configure,METH_VARARGS,"Retain native device bindings until reconfigured."},
    {"stop",stop,METH_O,"Stop after the current native instruction."},
    {"run",run,METH_VARARGS,"Run native 80186 instructions on the Courier bus."},{nullptr,nullptr,0,nullptr}};
PyModuleDef module={PyModuleDef_HEAD_INIT,"_mame_native",nullptr,-1,methods,nullptr,nullptr,nullptr,nullptr};
}
PyMODINIT_FUNC PyInit__mame_native(){return PyModule_Create(&module);}
