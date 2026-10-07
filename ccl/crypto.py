# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Scotty Wimberley
"""ECDSA P-256 / SHA-256 primitives, canonical serialization, and encrypted
key files for USB sticks.

Encodings used throughout the ledger:
  public key  -> hex of the 33-byte compressed SEC1 point
  signature   -> hex of the DER-encoded ECDSA signature
  hash        -> hex of SHA-256
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

CURVE = ec.SECP256R1()

# scrypt parameters: ~50 ms on a Pi 4, well under a second on anything else.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1


# --------------------------------------------------------------------------
# Canonical serialization and hashing
# --------------------------------------------------------------------------

def canonical(obj: Any) -> bytes:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8, no NaN."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def digest_of(obj: Any) -> bytes:
    return sha256(canonical(obj))


def hash_hex(obj: Any) -> str:
    return digest_of(obj).hex()


# --------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------

def generate_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(CURVE)


def public_key_hex(key: ec.EllipticCurvePrivateKey | ec.EllipticCurvePublicKey) -> str:
    pub = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PublicFormat,
    )
    return pub.public_bytes(Encoding.X962, PublicFormat.CompressedPoint).hex()


def public_key_from_hex(hexstr: str) -> ec.EllipticCurvePublicKey:
    return ec.EllipticCurvePublicKey.from_encoded_point(CURVE, bytes.fromhex(hexstr))


def private_key_to_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_numbers().private_value.to_bytes(32, "big")


def private_key_from_bytes(raw: bytes) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(raw, "big"), CURVE)


# --------------------------------------------------------------------------
# Signing and verification (over a precomputed SHA-256 digest)
# --------------------------------------------------------------------------

def sign_digest(key: ec.EllipticCurvePrivateKey, digest: bytes) -> bytes:
    if len(digest) != 32:
        raise ValueError("digest must be 32 bytes (SHA-256)")
    return key.sign(digest, ec.ECDSA(Prehashed(hashes.SHA256())))


def verify_digest(public_key_hexstr: str, digest: bytes, signature: bytes) -> bool:
    try:
        pub = public_key_from_hex(public_key_hexstr)
        pub.verify(signature, digest, ec.ECDSA(Prehashed(hashes.SHA256())))
        return True
    except (InvalidSignature, ValueError):
        return False


# --------------------------------------------------------------------------
# Encrypted key file (USB stick path)
# --------------------------------------------------------------------------

class WrongPIN(Exception):
    pass


def _kdf(pin: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).derive(
        pin.encode("utf-8")
    )


def encrypt_private_key(key: ec.EllipticCurvePrivateKey, pin: str) -> dict:
    """Return a JSON-serializable dict holding the AES-256-GCM-encrypted key."""
    salt = os.urandom(16)
    nonce = os.urandom(12)
    aes_key = _kdf(pin, salt)
    raw = private_key_to_bytes(key)
    pub_hex = public_key_hex(key)
    ct = AESGCM(aes_key).encrypt(nonce, raw, pub_hex.encode())
    return {
        "format": "ccl-key-v1",
        "curve": "P-256",
        "kdf": "scrypt",
        "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ct).decode(),
        "public_key": pub_hex,
    }


def decrypt_private_key(blob: dict, pin: str) -> ec.EllipticCurvePrivateKey:
    if blob.get("format") != "ccl-key-v1":
        raise ValueError("unrecognised key file format")
    salt = base64.b64decode(blob["salt"])
    nonce = base64.b64decode(blob["nonce"])
    ct = base64.b64decode(blob["ciphertext"])
    aes_key = Scrypt(salt=salt, length=32, n=blob["n"], r=blob["r"], p=blob["p"]).derive(
        pin.encode("utf-8")
    )
    try:
        raw = AESGCM(aes_key).decrypt(nonce, ct, blob["public_key"].encode())
    except InvalidTag:
        raise WrongPIN("wrong PIN or corrupted key file")
    key = private_key_from_bytes(raw)
    if public_key_hex(key) != blob["public_key"]:
        raise ValueError("key file public key does not match private key")
    return key
