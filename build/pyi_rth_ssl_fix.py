"""Preload the OpenSSL DLLs that match conda's _ssl.pyd.

Without this, Windows may bind _ssl.pyd to a mismatched libssl/libcrypto
(entry point COMP_get_type not found).
"""

import ctypes
import os
import sys

_base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
for _name in (
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "libcrypto-3.dll",
    "libssl-3.dll",
):
    _path = os.path.join(_base, _name)
    if os.path.isfile(_path):
        try:
            ctypes.WinDLL(_path)
        except OSError:
            pass
