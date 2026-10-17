"""Verify that debug stripping leaves every allocated ELF section unchanged."""
import hashlib
import json
from pathlib import Path
import struct
import sys


def allocated_sections(path):
    result = {}
    with Path(path).open('rb') as stream:
        header = struct.unpack('<16sHHIQQQIHHHHHH', stream.read(64))
        assert header[0][:6] == b'\x7fELF\x02\x01', 'expected ELF64 little-endian'
        stream.seek(header[6])
        sections = [struct.unpack('<IIQQQQIIQQ', stream.read(header[11]))
                    for _ in range(header[12])]
        names = sections[header[13]]
        stream.seek(names[4])
        strings = stream.read(names[5])
        for name, kind, flags, address, offset, size, *_ in sections:
            if not flags & 2:
                continue
            section_name = strings[name:].split(b'\0', 1)[0].decode()
            digest = None
            if kind != 8:  # NOBITS has no file contents.
                stream.seek(offset)
                hasher = hashlib.sha256()
                remaining = size
                while remaining:
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    assert chunk
                    remaining -= len(chunk)
                    hasher.update(chunk)
                digest = hasher.hexdigest()
            result[section_name] = dict(type=kind, flags=flags, address=address,
                                        size=size, sha256=digest)
    return result

original, stripped = sys.argv[1:]
sections = allocated_sections(original)
assert sections == allocated_sections(stripped)
print(json.dumps(dict(original=original, stripped=stripped,
                     allocated_sections_unchanged=True, sections=sections), indent=2))
