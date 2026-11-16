// SPDX-License-Identifier: BSD-3-Clause
// MAME instruction execution with Courier's existing memory/I/O bus.
#include <Python.h>
#include "emu.h"
#include "i186.h"
#include "i86inline.h"

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
    bool failed=false, stop_after=false;

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
        if(guard[a]&16)event(1,a,n);
        uint32_t value=memory[a];
        if(n==2)value|=uint32_t(memory[(a+1)&0xfffff])<<8;
        return value;
    }
    void store(uint32_t a,unsigned n,uint32_t value) {
        a&=0xfffff;mapped(a,n,2);
        if(guard[a]&32)event(2,a,n,value);
        memory[a]=uint8_t(value);
        if(n==2)memory[(a+1)&0xfffff]=uint8_t(value>>8);
    }
    uint8_t read_byte(uint32_t a) override {return uint8_t(load(a,1));}
    uint16_t read_word(uint32_t a) override {return uint16_t(load(a,2));}
    void write_byte(uint32_t a,uint8_t value) override {store(a,1,value);}
    void write_memory_byte_al(uint32_t a) override {store(a,1,m_regs.b[AL]);}
    void write_word(uint32_t a,uint16_t value) override {store(a,2,value);}
    uint8_t read_port_byte(uint16_t p) override {return uint8_t(event(3,p,1));}
    uint16_t read_port_word(uint16_t p) override {return uint16_t(event(3,p,2));}
    void write_port_byte(uint16_t p,uint8_t value) override {event(4,p,1,value);}
    void write_port_byte_al(uint16_t p) override {event(4,p,1,m_regs.b[AL]);}
    void write_port_word(uint16_t p,uint16_t value) override {event(4,p,2,value);}
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
    void begin() {m_halt=false;failed=stop_after=false;done=0;restore();}
    bool halted() const {return m_halt;}
    void step() {
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
    PyObject *capsule,*registers,*callback;unsigned count;
    if(!PyArg_ParseTuple(args,"OOIO",&capsule,&registers,&count,&callback))return nullptr;
    auto *instance=static_cast<Instance*>(PyCapsule_GetPointer(capsule,"courier.mame186"));
    if(!instance)return nullptr;
    if(!PyList_Check(registers)||PyList_GET_SIZE(registers)!=14||!PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_ValueError,"invalid MAME CPU registers or callback");return nullptr;
    }
    auto &cpu=instance->cpu;cpu.registers=registers;cpu.callback=callback;
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
    return Py_BuildValue("Ki",(unsigned long long)cpu.done,cpu.halted());
}
PyMethodDef methods[]={{"create",create,METH_VARARGS,"Create a MAME 80186 CPU."},
    {"run",run,METH_VARARGS,"Run native 80186 instructions on the Courier bus."},{nullptr,nullptr,0,nullptr}};
PyModuleDef module={PyModuleDef_HEAD_INIT,"_mame_native",nullptr,-1,methods,nullptr,nullptr,nullptr,nullptr};
}
PyMODINIT_FUNC PyInit__mame_native(){return PyModule_Create(&module);}
