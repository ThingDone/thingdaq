"""Inject autoflush into the exact archived USB write machine code."""

import argparse
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import (
    UC_ARCH_ARM,
    UC_HOOK_CODE,
    UC_HOOK_MEM_WRITE,
    UC_MODE_MCLASS,
    UC_MODE_THUMB,
    Uc,
)
from unicorn.arm_const import (
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_SP,
)


def exercise(elf_path, *, interrupt, used=48, size=24, guarded=False):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    for addr, length in [
        (0, 0x100000),
        (0x20000000, 0x100000),
        (0x20200000, 0x100000),
        (0x402E0000, 0x10000),
        (0x60000000, 0x100000),
        (0xE0000000, 0x100000),
    ]:
        uc.mem_map(addr, length)
    with elf_path.open("rb") as f:
        elf = ELFFile(f)
        symbols = {
            s.name: s["st_value"]
            for s in elf.get_section_by_name(".symtab").iter_symbols()
        }
        for section in elf.iter_sections():
            if section["sh_flags"] & 2 and section["sh_type"] != "SHT_NOBITS":
                uc.mem_write(section["sh_addr"], section.data())

    def put(name, value, width):
        uc.mem_write(symbols[name], value.to_bytes(width, "little"))

    def get(name, width):
        return int.from_bytes(uc.mem_read(symbols[name], width), "little")

    put("usb_configuration", 1, 1)
    put("usb_cdc_line_rtsdtr", 1, 1)
    put("tx_noautoflush", 0, 1)
    put("tx_head", 0, 1)
    put("tx_available", 2048 - used, 2)
    uc.mem_write(symbols["txbuffer"], b"A" * 2048 + b"B" * 6144)
    source = 0x20080000
    uc.mem_write(source, b"C" * size)
    uc.reg_write(UC_ARM_REG_SP, 0x200FF000)
    stop = 0x90000
    writes = []
    injected = False
    deferred = False
    irq_enabled = True
    core_start = symbols["usb_serial_write.part.0"] & ~1
    # Pin the exact load/load/address/guard sequence; refuse a different binary.
    assert bytes(uc.mem_read(core_start + 0x26, 12)) == bytes.fromhex(
        "1d783b8802eb451284f80090"
    )
    injection_pc = core_start + 0x2E
    uc.mem_write(0xE000E10C, (1 << 17).to_bytes(4, "little"))

    def nvic(machine, access, address, size, value, data):
        nonlocal irq_enabled
        if address == 0xE000E18C and value & (1 << 17):
            irq_enabled = False
            machine.mem_write(0xE000E10C, bytes(4))
        if address == 0xE000E10C and value & (1 << 17):
            irq_enabled = True

    uc.hook_add(UC_HOOK_MEM_WRITE, nvic)

    def hook(machine, address, length, data):
        nonlocal injected, deferred
        if address == stop:
            machine.emu_stop()
            return
        if interrupt and not injected and address == injection_pc:
            assert get("tx_noautoflush", 1) == 0
            if irq_enabled:
                injected = True
                machine.emu_stop()
                return
            deferred = True
        if address == (symbols["memcpy"] & ~1):
            dest = machine.reg_read(UC_ARM_REG_R0)
            src = machine.reg_read(UC_ARM_REG_R1)
            count = machine.reg_read(UC_ARM_REG_R2)
            machine.mem_write(dest, bytes(machine.mem_read(src, count)))
            machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))
        if address == (symbols["usb_transmit"] & ~1):
            descriptor = machine.reg_read(UC_ARM_REG_R1)
            _, status, pointer = struct.unpack("<III", machine.mem_read(descriptor, 12))
            writes.append(bytes(machine.mem_read(pointer, status >> 16)))
            machine.mem_write(descriptor + 4, bytes(4))
            machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))

    uc.hook_add(UC_HOOK_CODE, hook)

    def call(addr):
        uc.reg_write(UC_ARM_REG_LR, stop | 1)
        uc.emu_start(addr | 1, stop + 2, count=100000)

    if guarded:
        uc.reg_write(UC_ARM_REG_R0, 0x20090000)
        uc.reg_write(UC_ARM_REG_R1, source)
        uc.reg_write(UC_ARM_REG_R2, size)
        call(symbols["_ZN8thingdaq3usb19TeensyCdcByteStream5writeEPKhj"])
    else:
        uc.reg_write(UC_ARM_REG_R0, source)
        uc.reg_write(UC_ARM_REG_R1, size)
        call(symbols["usb_serial_write"])
    if injected:
        context = uc.context_save()
        uc.reg_write(UC_ARM_REG_SP, 0x200FE000)
        call(symbols["usb_serial_flush_callback"])
        uc.context_restore(context)
        uc.emu_start(injection_pc | 1, stop + 2, count=100000)
    accepted = uc.reg_read(UC_ARM_REG_R0)
    call(symbols["usb_serial_flush_callback"])
    observed = b"".join(writes)
    return {
        "interrupt": injected,
        "guarded": guarded,
        "deferred": deferred,
        "irq_enabled_after": irq_enabled,
        "used": used,
        "requested": size,
        "accepted": accepted,
        "transfer_lengths": [len(w) for w in writes],
        "expected_bytes": used + size,
        "observed_bytes": len(observed),
        "correct": observed == b"A" * used + b"C" * size,
        "observed_regions": [
            {"value": chr(v), "count": observed.count(v)} for v in b"ABC"
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-elf", type=Path, required=True)
    parser.add_argument("--fixed-elf", type=Path, required=True)
    args = parser.parse_args()
    results = [
        exercise(args.original_elf, interrupt=False),
        exercise(args.original_elf, interrupt=True),
        exercise(args.fixed_elf, interrupt=True, guarded=True),
    ]
    assert results[0]["correct"] and not results[1]["correct"] and results[2]["correct"]
    assert results[2]["deferred"] and results[2]["irq_enabled_after"]
    print(json.dumps(results, indent=2))
