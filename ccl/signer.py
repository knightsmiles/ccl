# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Scotty Wimberley
"""Signer abstraction (design §5).

Everything above this layer sees only public keys and signatures and cannot
tell a USB-stick key from a hardware-token key.

    StickSigner    – encrypted key file on a mounted stick; PIN decrypts it in
                     RAM for the duration of one signature, then the key
                     material is dropped.
    YubiKeySigner  – PIV signature slot (9c) on a YubiKey (or any PIV-capable
                     token); the private key never leaves the device.
"""

from __future__ import annotations

import ctypes
import getpass
import json
import os
from pathlib import Path
from typing import Callable

from . import crypto

PinPrompt = Callable[[str], str]

STICK_DIR = "ccl"            # everything we write on a stick lives under <stick>/ccl/
KEY_FILE = "key.json"
CERT_FILE = "cert.json"
SITE_PUB_FILE = "site.pub"
HISTORY_FILE = "history.jsonl"


def default_pin_prompt(label: str) -> str:
    return getpass.getpass(f"PIN for {label}: ")


class Signer:
    """Interface. `sign` takes a 32-byte SHA-256 digest, returns DER signature."""

    label: str = "signer"

    def public_key(self) -> str:      # hex, compressed point
        raise NotImplementedError

    def sign(self, digest: bytes) -> bytes:
        raise NotImplementedError


# --------------------------------------------------------------------------
# USB stick
# --------------------------------------------------------------------------

def stick_dir(stick_path: str | os.PathLike) -> Path:
    return Path(stick_path) / STICK_DIR


def _wipe(buf: bytearray) -> None:
    ctypes.memset((ctypes.c_char * len(buf)).from_buffer(buf), 0, len(buf))


class StickSigner(Signer):
    def __init__(self, stick_path: str | os.PathLike, pin: str | None = None,
                 pin_prompt: PinPrompt = default_pin_prompt, label: str | None = None):
        self.path = stick_dir(stick_path) / KEY_FILE
        if not self.path.exists():
            raise FileNotFoundError(f"no key file at {self.path}")
        with open(self.path) as f:
            self._blob = json.load(f)
        self._pin = pin
        self._pin_prompt = pin_prompt
        self.label = label or f"stick {Path(stick_path)}"

    def public_key(self) -> str:
        return self._blob["public_key"]

    def sign(self, digest: bytes) -> bytes:
        pin = self._pin if self._pin is not None else self._pin_prompt(self.label)
        key = crypto.decrypt_private_key(self._blob, pin)
        try:
            return crypto.sign_digest(key, digest)
        finally:
            # Best effort: overwrite the raw scalar we can reach, then drop the
            # object. Python cannot guarantee the cryptography backend leaves no
            # copies; the YubiKey path exists for members who need that.
            raw = bytearray(crypto.private_key_to_bytes(key))
            _wipe(raw)
            del key

    @staticmethod
    def create(stick_path: str | os.PathLike, pin: str) -> str:
        """Generate a new key on the stick. Returns the public key hex."""
        d = stick_dir(stick_path)
        d.mkdir(parents=True, exist_ok=True)
        target = d / KEY_FILE
        if target.exists():
            raise FileExistsError(f"{target} already exists; refusing to overwrite a key")
        key = crypto.generate_private_key()
        blob = crypto.encrypt_private_key(key, pin)
        tmp = target.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(blob, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
        return blob["public_key"]


# --------------------------------------------------------------------------
# YubiKey / PIV hardware token
# --------------------------------------------------------------------------

class YubiKeySigner(Signer):
    """Signs with the P-256 key in PIV slot 9c (Digital Signature).

    Requires `yubikey-manager` (pip install yubikey-manager) and a token with a
    P-256 key already generated in slot 9c (`ccl device new-yubikey` does this).
    Untested against real hardware in this build — treat as a starting point.
    """

    SLOT = 0x9C

    def __init__(self, pin: str | None = None, pin_prompt: PinPrompt = default_pin_prompt,
                 label: str = "YubiKey"):
        try:
            from ykman.device import list_all_devices  # noqa: F401
            from yubikit.piv import PivSession  # noqa: F401
        except ImportError as e:
            raise RuntimeError("yubikey-manager is not installed: pip install yubikey-manager") from e
        self._pin = pin
        self._pin_prompt = pin_prompt
        self.label = label

    def _session(self):
        from ykman.device import list_all_devices
        from yubikit.core.smartcard import SmartCardConnection
        from yubikit.piv import PivSession
        devs = list_all_devices()
        if not devs:
            raise RuntimeError("no YubiKey found")
        dev, _info = devs[0]
        conn = dev.open_connection(SmartCardConnection)
        return conn, PivSession(conn)

    def public_key(self) -> str:
        conn, piv = self._session()
        try:
            from yubikit.piv import SLOT
            meta = piv.get_slot_metadata(SLOT.SIGNATURE)
            return crypto.public_key_hex(meta.public_key)
        finally:
            conn.close()

    def sign(self, digest: bytes) -> bytes:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
        from yubikit.piv import KEY_TYPE, SLOT
        pin = self._pin if self._pin is not None else self._pin_prompt(self.label)
        conn, piv = self._session()
        try:
            piv.verify_pin(pin)
            return piv.sign(SLOT.SIGNATURE, KEY_TYPE.ECCP256, digest,
                            Prehashed(hashes.SHA256()))
        finally:
            conn.close()

    @staticmethod
    def generate_key(management_key: bytes | None = None) -> str:
        """Generate a fresh P-256 key in slot 9c. Returns public key hex."""
        from yubikit.piv import KEY_TYPE, PIN_POLICY, SLOT, TOUCH_POLICY, DEFAULT_MANAGEMENT_KEY, MANAGEMENT_KEY_TYPE
        s = YubiKeySigner.__new__(YubiKeySigner)
        conn, piv = s._session()
        try:
            piv.authenticate(MANAGEMENT_KEY_TYPE.TDES, management_key or DEFAULT_MANAGEMENT_KEY)
            pub = piv.generate_key(SLOT.SIGNATURE, KEY_TYPE.ECCP256,
                                   PIN_POLICY.ALWAYS, TOUCH_POLICY.DEFAULT)
            return crypto.public_key_hex(pub)
        finally:
            conn.close()


# --------------------------------------------------------------------------
# In-memory signer (tests, and the site key when kept in a file that is
# already decrypted — used only internally)
# --------------------------------------------------------------------------

class MemorySigner(Signer):
    def __init__(self, key=None, label: str = "memory"):
        self._key = key or crypto.generate_private_key()
        self.label = label

    def public_key(self) -> str:
        return crypto.public_key_hex(self._key)

    def sign(self, digest: bytes) -> bytes:
        return crypto.sign_digest(self._key, digest)
