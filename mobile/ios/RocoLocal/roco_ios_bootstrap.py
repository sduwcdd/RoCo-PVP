"""iOS loader glue only; battle rules and parser remain the shared engine."""
import sys
from pathlib import Path

if sys.platform != "ios" or sys.version_info[:2] != (3, 13):
    raise RuntimeError("Embedded iOS Python 3.13 required")

# PyCryptodome's raw ctypes/cffi libraries are not importlib extension modules.
# Resolve them from signed frameworks after Xcode relocates their .so files.
from Crypto.Util import _raw_api

_frameworks = Path(__file__).resolve().parents[1] / "Frameworks"
_original_load = _raw_api.load_pycryptodome_raw_lib


def _load_raw(name, declarations):
    executable = _frameworks / (name + ".framework") / name
    if executable.is_file():
        return _raw_api.load_lib(str(executable), declarations)
    return _original_load(name, declarations)


_raw_api.load_pycryptodome_raw_lib = _load_raw

# Fail before reporting readiness if native iOS wheels or raw-library packaging fail.
from Crypto.Cipher import AES
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import msgpack
from google.protobuf import descriptor
from scapy.layers.inet import IP, TCP

_key, _nonce, _plain = bytes(32), bytes(12), b"roco-ios-runtime-check"
_cipher = AES.new(_key, AES.MODE_ECB)
if _cipher.decrypt(_cipher.encrypt(bytes(16))) != bytes(16):
    raise RuntimeError("iOS PyCryptodome runtime check failed")
_gcm = AESGCM(_key)
if _gcm.decrypt(_nonce, _gcm.encrypt(_nonce, _plain, None), None) != _plain:
    raise RuntimeError("iOS cryptography runtime check failed")
if msgpack.unpackb(msgpack.packb({"runtime": "ios"})) != {"runtime": "ios"}:
    raise RuntimeError("iOS msgpack runtime check failed")
del _key, _nonce, _plain, _cipher, _gcm
