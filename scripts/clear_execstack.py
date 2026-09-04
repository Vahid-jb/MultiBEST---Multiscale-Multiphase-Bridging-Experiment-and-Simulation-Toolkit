#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Clear executable-stack flags from ELF program headers.

Some Python distributions ship ``libpython`` with an executable ``GNU_STACK``
program header. Hardened Linux systems can refuse to load such objects from a
PyInstaller bundle. This helper clears only the execute bit on ``PT_GNU_STACK``.
"""

import argparse
import struct
from pathlib import Path

PT_GNU_STACK = 0x6474E551
PF_X = 0x1


def clear_execstack(path: Path) -> bool:
    with path.open("r+b") as handle:
        if handle.read(4) != b"\x7fELF":
            raise ValueError(f"{path} is not an ELF file")

        handle.seek(4)
        elf_class = handle.read(1)
        endian = handle.read(1)
        if elf_class != b"\x02":
            raise ValueError(f"{path} is not a 64-bit ELF file")

        byte_order = "<" if endian == b"\x01" else ">"
        handle.seek(32)
        phoff = struct.unpack(f"{byte_order}Q", handle.read(8))[0]
        handle.seek(54)
        phentsize = struct.unpack(f"{byte_order}H", handle.read(2))[0]
        phnum = struct.unpack(f"{byte_order}H", handle.read(2))[0]

        for index in range(phnum):
            entry_offset = phoff + index * phentsize
            handle.seek(entry_offset)
            p_type = struct.unpack(f"{byte_order}I", handle.read(4))[0]
            if p_type != PT_GNU_STACK:
                continue

            flags_offset = entry_offset + 4
            handle.seek(flags_offset)
            flags = struct.unpack(f"{byte_order}I", handle.read(4))[0]
            if not flags & PF_X:
                return False

            handle.seek(flags_offset)
            handle.write(struct.pack(f"{byte_order}I", flags & ~PF_X))
            return True

    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    for path in args.paths:
        changed = clear_execstack(path)
        print(f"{path}: {'cleared executable stack' if changed else 'unchanged'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
