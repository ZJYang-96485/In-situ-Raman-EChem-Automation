"""Read-only inspection of candidate CHI SDK files without loading a library."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import platform
import struct
from typing import Iterable

from .sdk_mapping import unresolved_live_bindings


_PE_MACHINE_NAMES = {
    0x014C: ("x86", 32),
    0x8664: ("x86_64", 64),
    0xAA64: ("arm64", 64),
}


@dataclass(frozen=True)
class SDKCandidateInspection:
    path: str
    exists: bool
    size_bytes: int | None
    sha256: str | None
    file_format: str | None
    architecture: str | None
    bitness: int | None
    exported_symbols: tuple[str, ...]
    error: str | None

    @property
    def is_32_bit_windows_pe(self) -> bool:
        return (
            self.file_format == "PE"
            and self.architecture == "x86"
            and self.bitness == 32
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "file_format": self.file_format,
            "architecture": self.architecture,
            "bitness": self.bitness,
            "exported_symbols": list(self.exported_symbols),
            "is_32_bit_windows_pe": self.is_32_bit_windows_pe,
            "error": self.error,
        }


@dataclass(frozen=True)
class PreflightReport:
    status: str
    host_system: str
    host_machine: str
    host_python_bitness: int
    host_can_load_documented_libec: bool
    sdk_loaded: bool
    device_contacted: bool
    candidates: tuple[SDKCandidateInspection, ...]
    required_exports: tuple[str, ...]
    missing_required_exports: tuple[str, ...]
    unresolved_live_bindings: tuple[str, ...]

    @property
    def ready_for_live_connection(self) -> bool:
        return False

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "host_system": self.host_system,
            "host_machine": self.host_machine,
            "host_python_bitness": self.host_python_bitness,
            "host_can_load_documented_libec": self.host_can_load_documented_libec,
            "sdk_loaded": self.sdk_loaded,
            "device_contacted": self.device_contacted,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "required_exports": list(self.required_exports),
            "missing_required_exports": list(self.missing_required_exports),
            "unresolved_live_bindings": list(self.unresolved_live_bindings),
            "ready_for_live_connection": self.ready_for_live_connection,
        }


def inspect_sdk_candidate(path: str | Path) -> SDKCandidateInspection:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return SDKCandidateInspection(
            str(candidate), False, None, None, None, None, None, (), "file does not exist"
        )
    if not candidate.is_file():
        return SDKCandidateInspection(
            str(candidate), True, None, None, None, None, None, (), "path is not a file"
        )
    try:
        data = candidate.read_bytes()
        digest = sha256(data).hexdigest()
        architecture, bitness, exports = _inspect_pe_bytes(data)
        return SDKCandidateInspection(
            str(candidate), True, len(data), digest, "PE", architecture, bitness,
            exports, None,
        )
    except (OSError, ValueError, struct.error) as error:
        size = candidate.stat().st_size if candidate.exists() else None
        digest = None
        try:
            digest = sha256(candidate.read_bytes()).hexdigest()
        except OSError:
            pass
        return SDKCandidateInspection(
            str(candidate), True, size, digest, None, None, None, (), str(error)
        )


def run_connection_preflight(
    sdk_candidates: Iterable[str | Path] = (),
    *,
    required_exports: Iterable[str] = (),
) -> PreflightReport:
    candidates = tuple(inspect_sdk_candidate(path) for path in sdk_candidates)
    required_list: list[str] = []
    for symbol in required_exports:
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("required export names must be non-empty strings")
        if symbol not in required_list:
            required_list.append(symbol)
    required = tuple(required_list)
    available_exports = {
        symbol
        for candidate in candidates
        for symbol in candidate.exported_symbols
    }
    missing = tuple(symbol for symbol in required if symbol not in available_exports)
    if not candidates:
        status = "awaiting_sdk_artifacts"
    elif any(candidate.error for candidate in candidates):
        status = "inspection_failed"
    elif missing:
        status = "required_exports_missing"
    elif not any(candidate.is_32_bit_windows_pe for candidate in candidates):
        status = "documented_32_bit_library_not_found"
    else:
        status = "inspection_complete_mapping_required"
    host_system = platform.system()
    host_python_bitness = struct.calcsize("P") * 8
    return PreflightReport(
        status=status,
        host_system=host_system,
        host_machine=platform.machine(),
        host_python_bitness=host_python_bitness,
        host_can_load_documented_libec=(
            host_system == "Windows"
            and host_python_bitness == 32
            and any(candidate.is_32_bit_windows_pe for candidate in candidates)
        ),
        sdk_loaded=False,
        device_contacted=False,
        candidates=candidates,
        required_exports=required,
        missing_required_exports=missing,
        unresolved_live_bindings=unresolved_live_bindings(),
    )


def _inspect_pe_bytes(data: bytes) -> tuple[str, int, tuple[str, ...]]:
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("not a Windows PE file")
    pe_offset = _u32(data, 0x3C)
    if pe_offset + 24 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\x00\x00":
        raise ValueError("invalid PE header")
    machine = _u16(data, pe_offset + 4)
    architecture, machine_bitness = _PE_MACHINE_NAMES.get(
        machine, (f"unknown_0x{machine:04x}", 0)
    )
    section_count = _u16(data, pe_offset + 6)
    optional_size = _u16(data, pe_offset + 20)
    optional_offset = pe_offset + 24
    if optional_offset + optional_size > len(data):
        raise ValueError("truncated PE optional header")
    magic = _u16(data, optional_offset)
    if magic == 0x10B:
        bitness = 32
        data_directory_offset = optional_offset + 96
    elif magic == 0x20B:
        bitness = 64
        data_directory_offset = optional_offset + 112
    else:
        raise ValueError(f"unsupported PE optional-header magic 0x{magic:04x}")
    if machine_bitness and machine_bitness != bitness:
        raise ValueError("PE machine and optional-header bitness disagree")
    if data_directory_offset + 8 > optional_offset + optional_size:
        return architecture, bitness, ()
    export_rva = _u32(data, data_directory_offset)
    if export_rva == 0:
        return architecture, bitness, ()
    section_offset = optional_offset + optional_size
    sections = []
    for index in range(section_count):
        offset = section_offset + index * 40
        if offset + 40 > len(data):
            raise ValueError("truncated PE section table")
        _virtual_size = _u32(data, offset + 8)
        virtual_address = _u32(data, offset + 12)
        raw_size = _u32(data, offset + 16)
        raw_offset = _u32(data, offset + 20)
        sections.append((virtual_address, raw_size, raw_offset))
    export_offset = _rva_to_offset(export_rva, sections, len(data))
    if export_offset + 40 > len(data):
        raise ValueError("truncated PE export directory")
    name_count = _u32(data, export_offset + 24)
    names_rva = _u32(data, export_offset + 32)
    if name_count > 10000:
        raise ValueError("PE export-name count exceeds inspection limit")
    names_offset = _rva_to_offset(names_rva, sections, len(data))
    exports: list[str] = []
    for index in range(name_count):
        name_rva = _u32(data, names_offset + index * 4)
        name_offset = _rva_to_offset(name_rva, sections, len(data))
        exports.append(_read_c_string(data, name_offset))
    return architecture, bitness, tuple(exports)


def _rva_to_offset(
    rva: int,
    sections: list[tuple[int, int, int]],
    data_length: int,
) -> int:
    for virtual_address, span, raw_offset in sections:
        if virtual_address <= rva < virtual_address + span:
            offset = raw_offset + (rva - virtual_address)
            if offset >= data_length:
                break
            return offset
    raise ValueError(f"PE RVA 0x{rva:x} is outside file sections")


def _read_c_string(data: bytes, offset: int) -> str:
    end = data.find(b"\x00", offset, min(len(data), offset + 4096))
    if end == -1:
        raise ValueError("unterminated PE export name")
    try:
        return data[offset:end].decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("non-ASCII PE export name") from error


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise ValueError("truncated PE field")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("truncated PE field")
    return struct.unpack_from("<I", data, offset)[0]
