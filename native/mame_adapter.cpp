// SPDX-License-Identifier: BSD-3-Clause
// MAME instruction execution with Courier's existing memory/I/O bus.
#include <Python.h>
#include "emu.h"
#include "i186.h"
#include "i86inline.h"
#include "interrupts186.hpp"
#include "serial186.hpp"
#include "timers186.hpp"

namespace {
struct Stop {};
struct Redirect {};
struct Interrupt {};
class CourierCpu;

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
    PyObject *registers=nullptr,*callback=nullptr;
    uint64_t done=0;
    bool failed=false, stop_after=false, irq_fallback=false;
    courier::MachineServiceState *irqs=nullptr;
    courier::Serial186 *uart=nullptr;
    courier::Timers186 *timers=nullptr;
    const uint8_t *device_access=nullptr,*host_ports=nullptr;
    uint8_t *mmio_events=nullptr;
    uint32_t mmio_count=0,mmio_capacity=0;
    using HostIo=int (*)(void*,int,uint16_t,int,uint16_t,uint64_t,uint16_t*);
    HostIo host_io=nullptr;
    void *host_context=nullptr;
    uint64_t host_base=0;

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
        const unsigned offset=(a-0xff30)/2,index=offset/4,field=offset%4;
        const int64_t tick=timers->tick_at(timers->instruction_base+done);
        auto preview=timers->slots[index];preview.advance(tick);
        // Delay acceleration and board-specific grants retain their existing
        // slow path; ordinary control/count/compare reads stay native.
        if(field==3&&timers->fast&&!(preview.control&0x20)&&preview.counting())return false;
        timers->slots[index]=preview;
        value=uint32_t(field==0?preview.count:field==1?preview.compare_a:
                       field==2?preview.compare_b:preview.control)&(n==1?255:65535);
        const unsigned entry=offset>10?offset-1:offset;
        ++timers->reads;++timers->revision;++timers->read_counts[entry][n-1];
        timers->read_mask|=uint64_t(1)<<(2*entry+n-1);
        timers->last_read_tick[index]=uint64_t(tick);
        return true;
    }
    void queue_write(uint32_t a,unsigned n,uint32_t value,unsigned applied) {
        if(mmio_count==mmio_capacity) {
            PyErr_SetString(PyExc_RuntimeError,"MAME MMIO batch capacity exceeded");
            failed=true;throw Stop{};
        }
        uint8_t *e=mmio_events+8*mmio_count++;
        e[0]=uint8_t(a);e[1]=uint8_t(a>>8);e[2]=uint8_t(a>>16);e[3]=uint8_t(a>>24);
        e[4]=uint8_t(value);e[5]=uint8_t(value>>8);e[6]=uint8_t(n);e[7]=uint8_t(applied);
    }
    uint16_t port(unsigned direction,uint16_t p,unsigned n,uint16_t value=0) {
        uint16_t answer=0;
        if(host_io&&(host_ports[p]&direction)
                &&host_io(host_context,int(direction),p,int(n),value,host_base+done+1,&answer))
            return answer;
        return uint16_t(event(direction==1?3:4,p,n,value));
    }

    void publish() {
        uint32_t values[14];
        for(unsigned i=0;i<8;++i)values[i]=m_regs.w[i];
        for(unsigned i=0;i<4;++i)values[8+i]=m_sregs[i];
        values[12]=m_ip;values[13]=CompressFlags();
        for(unsigned i=0;i<14;++i) {
            PyObject *value=PyLong_FromUnsignedLong(values[i]);
            if(!value){failed=true;throw Stop{};}
            PyList_SetItem(registers,i,value);
        }
    }
    void restore() {
        uint16_t values[14];
        for(unsigned i=0;i<14;++i) {
            values[i]=uint16_t(PyLong_AsUnsignedLong(PyList_GET_ITEM(registers,i)));
            if(PyErr_Occurred()){failed=true;throw Stop{};}
        }
        for(unsigned i=0;i<8;++i)m_regs.w[i]=values[i];
        for(unsigned i=0;i<4;++i)m_sregs[i]=values[8+i];
        m_ip=values[12];ExpandFlags(values[13]);
    }
    uint32_t event(unsigned kind,uint32_t address,unsigned size,uint32_t value=0) {
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
        if(timer_read(a,n,timer_value)) {
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
            if(uart->write(a,value,*irqs)>=0)stop_after=true;
            queue_write(a,n,value,4);
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
    void interrupt(int vector,int trap=1) override {
        // Hardware IRQs are dispatched by the existing Courier board. CPU
        // faults and INT instructions retain its diagnostic/service hooks.
        event(6,unsigned(vector),unsigned(trap));
        throw Interrupt{};
    }
    void begin() {m_halt=false;failed=stop_after=irq_fallback=false;done=mmio_count=0;restore();}
    bool halted() const {return m_halt;}
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

struct Instance {
    running_machine machine;
    machine_config config{machine};
    PlainSpace space;
    CourierCpu cpu{config};
    Py_buffer memory_view{},guard_view{};
    Instance(PyObject *m,PyObject *g) {
        // These exports pin the backing bytearrays for the CPU's lifetime.
        // A resize must fail rather than invalidate persistent bus pointers.
        if(PyObject_GetBuffer(m,&memory_view,PyBUF_WRITABLE)<0)throw Stop{};
        if(PyObject_GetBuffer(g,&guard_view,PyBUF_WRITABLE)<0) {
            PyBuffer_Release(&memory_view);throw Stop{};
        }
        space.memory=cpu.memory=static_cast<uint8_t*>(memory_view.buf);
        cpu.guard=static_cast<uint8_t*>(guard_view.buf);
        cpu.shim_set_space(AS_PROGRAM,&space);cpu.shim_set_space(AS_IO,&space);
        machine.set_cpu(&cpu);cpu.shim_start();cpu.shim_reset();
    }
    ~Instance(){PyBuffer_Release(&memory_view);PyBuffer_Release(&guard_view);}
};

void destroy(PyObject *capsule) {delete static_cast<Instance*>(PyCapsule_GetPointer(capsule,"courier.mame186"));}
PyObject *create(PyObject *,PyObject *args) {
    PyObject *memory,*guard;
    if(!PyArg_ParseTuple(args,"OO",&memory,&guard))return nullptr;
    if(!PyByteArray_Check(memory)||!PyByteArray_Check(guard)
            ||PyByteArray_GET_SIZE(memory)!=0x100000||PyByteArray_GET_SIZE(guard)!=0x100000) {
        PyErr_SetString(PyExc_ValueError,"MAME 186 requires 1 MiB memory and guard buffers");return nullptr;
    }
    try {return PyCapsule_New(new Instance(memory,guard),"courier.mame186",destroy);}
    catch(const Stop &){return nullptr;}
    catch(const std::exception &e){PyErr_SetString(PyExc_RuntimeError,e.what());return nullptr;}
}
PyObject *run(PyObject *,PyObject *args) {
    PyObject *capsule,*registers,*callback,*bindings=Py_None;unsigned count;
    if(!PyArg_ParseTuple(args,"OOIO|O",&capsule,&registers,&count,&callback,&bindings))return nullptr;
    auto *instance=static_cast<Instance*>(PyCapsule_GetPointer(capsule,"courier.mame186"));
    if(!instance)return nullptr;
    if(!PyList_Check(registers)||PyList_GET_SIZE(registers)!=14||!PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_ValueError,"invalid MAME CPU registers or callback");return nullptr;
    }
    auto &cpu=instance->cpu;cpu.registers=registers;cpu.callback=callback;
    cpu.irqs=nullptr;cpu.uart=nullptr;cpu.timers=nullptr;cpu.device_access=nullptr;cpu.mmio_events=nullptr;
    cpu.host_io=nullptr;cpu.host_context=nullptr;cpu.host_ports=nullptr;
    if(bindings!=Py_None) {
        if(!PyTuple_Check(bindings)||PyTuple_GET_SIZE(bindings)!=9) {
            PyErr_SetString(PyExc_ValueError,"invalid MAME device bindings");return nullptr;
        }
        auto buffer=[&](unsigned index,Py_ssize_t size)->uint8_t* {
            PyObject *value=PyTuple_GET_ITEM(bindings,index);
            if(value==Py_None)return nullptr;
            if(!PyByteArray_Check(value)||PyByteArray_GET_SIZE(value)!=size) {
                PyErr_SetString(PyExc_ValueError,"invalid MAME device buffer");return nullptr;
            }
            return reinterpret_cast<uint8_t*>(PyByteArray_AS_STRING(value));
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
        cpu.host_base=PyLong_AsUnsignedLongLong(PyTuple_GET_ITEM(bindings,7));
        cpu.timers=reinterpret_cast<courier::Timers186*>(buffer(8,sizeof(courier::Timers186)));
        if(PyErr_Occurred())return nullptr;
        if(cpu.host_io&&!cpu.host_ports) {
            PyErr_SetString(PyExc_ValueError,"missing MAME native port table");return nullptr;
        }
    }
    try {
        cpu.begin();
        while(cpu.done<count) {
            try {cpu.step();++cpu.done;}
            catch(const Redirect &) {continue;}
            catch(const Interrupt &) {++cpu.done;break;}
            if(cpu.halted()||cpu.stop_after)break;
        }
    } catch(const Stop &) {}
      catch(const std::exception &e){PyErr_SetString(PyExc_RuntimeError,e.what());cpu.failed=true;}
    if(cpu.failed)return nullptr;
    try {cpu.publish();}catch(const Stop &){return nullptr;}
    return Py_BuildValue("KiiI",(unsigned long long)cpu.done,cpu.halted(),cpu.irq_fallback,cpu.mmio_count);
}
PyMethodDef methods[]={{"create",create,METH_VARARGS,"Create a MAME 80186 CPU."},
    {"run",run,METH_VARARGS,"Run native 80186 instructions on the Courier bus."},{nullptr,nullptr,0,nullptr}};
PyModuleDef module={PyModuleDef_HEAD_INIT,"_mame_native",nullptr,-1,methods,nullptr,nullptr,nullptr,nullptr};
}
PyMODINIT_FUNC PyInit__mame_native(){return PyModule_Create(&module);}
