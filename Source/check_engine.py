#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnoses why the mpv engine (libmpv-2.dll) can't be loaded.

Run it on Windows:
    python check_engine.py

It prints exactly what is missing or mismatched and how to fix it.
"""
import ctypes
import os
import struct
import sys
import platform

MACHINES = {
    0x014C: "x86 (32-bit)",
    0x8664: "x64 (64-bit)",
    0xAA64: "ARM64",
    0x01C4: "ARM (32-bit)",
}


def pe_machine(path):
    """CPU machine value from a PE file, or None."""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"MZ":
                return None
            f.seek(0x3C)
            pe_off = struct.unpack("<I", f.read(4))[0]
            f.seek(pe_off)
            if f.read(4) != b"PE\x00\x00":
                return None
            return struct.unpack("<H", f.read(2))[0]
    except Exception:
        return None


def main():
    print("=" * 62)
    print(" Lumo - engine diagnostic")
    print("=" * 62)

    py_bits = struct.calcsize("P") * 8
    print(f"1) Python : {sys.version.split()[0]}  ({py_bits}-bit)")
    print(f"   OS     : {platform.platform()}")
    print()

    print("2) python-mpv package:")
    try:
        import mpv
        print("   OK - installed, version", getattr(mpv, "__version__", "unknown"))
        pkg_ok = True
    except Exception as e:
        print(f"   MISSING / broken -> {e}")
        print("   FIX:  pip install python-mpv")
        pkg_ok = False
    print()

    names = ["libmpv-2.dll", "mpv-2.dll", "mpv-1.dll", "mpv.dll"]
    here = os.path.dirname(os.path.abspath(__file__))

    print("3) Looking for the mpv DLL:")
    found = []
    for n in names:
        p = os.path.join(here, n)
        if os.path.exists(p):
            found.append(p)
            print(f"   FOUND next to this script: {n}")
    for n in names:
        for d in os.environ.get("PATH", "").split(os.pathsep):
            d = d.strip()
            if not d:
                continue
            p = os.path.join(d, n)
            if os.path.exists(p):
                found.append(p)
                print(f"   FOUND in PATH: {p}")
                break
    if not found:
        print("   NOT FOUND anywhere on the search path.")
        print("   FIX: put libmpv-2.dll next to main.py, or run get_libmpv.bat")
    print()

    for p in found:
        print(f"4) Inspecting: {os.path.basename(p)}")
        print(f"   Path: {p}")
        m = pe_machine(p)
        if m is None:
            print("   Not a valid PE file - is it really a Windows DLL?")
        else:
            label = MACHINES.get(m, hex(m))
            print(f"   DLL architecture: {label}")
            if m == 0x8664 and py_bits == 32:
                print("   *** MISMATCH: 32-bit Python cannot load a 64-bit DLL. ***")
                print("       Download the 32-bit dev build:  mpv-dev-i686-*.7z")
            elif m == 0x014C and py_bits == 64:
                print("   *** MISMATCH: 64-bit Python cannot load a 32-bit DLL. ***")
                print("       Download the 64-bit dev build:  mpv-dev-x86_64-*.7z")
            else:
                print("   OK: bitness matches Python")
        try:
            ctypes.CDLL(p)
            print("   ctypes.CDLL load: OK")
        except OSError as e:
            we = getattr(e, "winerror", None)
            print(f"   ctypes.CDLL load FAILED: {e}")
            if we == 193:
                print("   -> Error 193 = bitness mismatch (see above).")
            elif we == 126:
                print("   -> Error 126 = a dependency of the DLL is missing.")
                print("      Install the Microsoft Visual C++ Redistributable")
                print("      (vc_redist.x64.exe) from microsoft.com and retry.")
        print()

    print("=" * 62)
    print(" Summary of the most likely causes:")
    print("   A. python-mpv not installed     -> pip install python-mpv")
    print("   B. DLL not next to main.py      -> run get_libmpv.bat")
    print("   C. Python/DLL bitness mismatch  -> use the matching build")
    print("=" * 62)

    if pkg_ok and found:
        print()
        print("If everything above looks OK but the player still fails,")
        print("paste the full output of this script to your assistant.")
    else:
        print()
        print("Fix the items marked above, then run the player again.")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
