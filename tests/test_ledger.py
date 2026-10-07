# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Scotty Wimberley
import json
import sqlite3
import pytest

from ccl import crypto
from ccl.ledger import Ledger, LedgerError, parse_amount, fmt_amount, verify_certificate
from ccl.signer import StickSigner, MemorySigner, stick_dir, HISTORY_FILE


@pytest.fixture
def site(tmp_path):
    L = Ledger(tmp_path / "ledger.db")
    admin_stick = tmp_path / "admin"
    StickSigner.create(admin_stick, "0000")
    site_signer = StickSigner(admin_stick, pin="0000")
    L.init_site(site_signer, "test site", "Admin")
    return L, site_signer, tmp_path


def enroll(L, site_signer, tmp_path, name, limit=10000, pin="1234"):
    mid = L.enroll_member(name, "", limit)
    stick = tmp_path / name
    pub = StickSigner.create(stick, pin)
    cert = L.register_device(mid, pub, "stick", "s1", site_signer)
    L.write_stick_files(stick, cert)
    return mid, StickSigner(stick, pin=pin), stick


def test_amounts():
    assert parse_amount("12.50") == 1250
    assert fmt_amount(1250) == "12.50"
    assert fmt_amount(-5) == "-0.05"
    with pytest.raises(LedgerError):
        parse_amount("1.234")
    with pytest.raises(LedgerError):
        parse_amount("-1")


def test_wrong_pin(tmp_path):
    StickSigner.create(tmp_path, "1234")
    with pytest.raises(crypto.WrongPIN):
        StickSigner(tmp_path, pin="9999").sign(b"\0" * 32)


def test_transact_and_verify(site):
    L, ss, tp = site
    a, sa, stick_a = enroll(L, ss, tp, "alice")
    b, sb, stick_b = enroll(L, ss, tp, "bob")
    L.transact(sa, sb, 2500, "four hours wiring")
    L.transact(sb, sa, 1000, "apples", listing_id=None)
    assert L.balance(a) == -1500 and L.balance(b) == 1500
    r = L.verify()
    assert r.ok, r.problems
    assert r.entries == 2
    assert sum(r.balances.values()) == 0
    L.refresh_history(stick_a, a)
    lines = (stick_dir(stick_a) / HISTORY_FILE).read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["entry_hash"] == L.conn.execute("select entry_hash from transactions where id=1").fetchone()[0]


def test_fee(site):
    L, ss, tp = site
    a, sa, _ = enroll(L, ss, tp, "alice")
    b, sb, _ = enroll(L, ss, tp, "bob")
    L.set_setting("fee", "50")
    with pytest.raises(LedgerError):
        L.transact(sa, sb, 1000, "x")            # no site signer to take the fee
    rows = L.transact(sa, sb, 1000, "x", site_signer=ss)
    assert [r["kind"] for r in rows] == ["trade", "fee"]
    assert L.balance(a) == -1050 and L.balance(L.admin_id()) == 50
    assert L.verify().ok


def test_credit_limit(site):
    L, ss, tp = site
    a, sa, _ = enroll(L, ss, tp, "alice", limit=1000)
    b, sb, _ = enroll(L, ss, tp, "bob")
    L.transact(sa, sb, 1000, "ok")
    with pytest.raises(LedgerError):
        L.transact(sa, sb, 1, "over")


def test_tamper_detected(site):
    L, ss, tp = site
    a, sa, _ = enroll(L, ss, tp, "alice")
    b, sb, _ = enroll(L, ss, tp, "bob")
    L.transact(sa, sb, 1000, "x")
    L.transact(sa, sb, 2000, "y")
    with L.conn:
        L.conn.execute("update transactions set amount=1 where id=1")
    r = L.verify()
    assert not r.ok
    assert any("#1" in p for p in r.problems)
    assert any("#2: chain broken" in p for p in r.problems) or any("hash" in p for p in r.problems)


def test_foreign_key_rejected(site):
    L, ss, tp = site
    a, sa, _ = enroll(L, ss, tp, "alice")
    stranger = MemorySigner()
    with pytest.raises(LedgerError):
        L.transact(sa, stranger, 100, "x")


def test_revoke_and_second_device(site):
    L, ss, tp = site
    a, sa, _ = enroll(L, ss, tp, "alice")
    b, sb, _ = enroll(L, ss, tp, "bob")
    L.transact(sa, sb, 100, "before revoke")
    # second stick for alice
    stick2 = tp / "alice2"
    pub2 = StickSigner.create(stick2, "4321")
    L.register_device(a, pub2, "stick", "s2", ss)
    L.revoke_device(sa.public_key())
    with pytest.raises(LedgerError):
        L.transact(sa, sb, 100, "revoked")
    L.transact(StickSigner(stick2, pin="4321"), sb, 100, "with new stick")
    assert L.verify().ok           # old signature still valid


def test_certificate_from_other_site(tmp_path):
    L1 = Ledger(tmp_path / "a.db"); s1 = MemorySigner(); L1.init_site(s1, "", "A")
    L2 = Ledger(tmp_path / "b.db"); s2 = MemorySigner(); L2.init_site(s2, "", "B")
    mid = L1.enroll_member("x")
    cert = L1.register_device(mid, MemorySigner().public_key(), "stick", "", s1)
    assert verify_certificate(cert, L1.site_public_key)
    assert not verify_certificate(cert, L2.site_public_key)


def test_reversal(site):
    L, ss, tp = site
    a, sa, _ = enroll(L, ss, tp, "alice")
    b, sb, _ = enroll(L, ss, tp, "bob")
    orig = L.transact(sa, sb, 700, "disputed")[0]
    with pytest.raises(LedgerError):
        L.reverse(orig["id"], sa, sb, "wrong direction")
    L.reverse(orig["id"], sb, sa, "agreed refund")
    assert L.balance(a) == 0 and L.balance(b) == 0
    assert L.verify().ok


def test_listings(site):
    L, ss, tp = site
    a, sa, _ = enroll(L, ss, tp, "alice")
    b, sb, _ = enroll(L, ss, tp, "bob")
    L.post_listing(a, "want", "transport", "used pickup truck", "running, any condition", "each")
    lid, matches = L.post_listing(b, "offer", "transport", "1998 Toyota pickup", "needs brakes", "each", 150000)
    assert [m["member_id"] for m in matches] == [a]
    assert [l["id"] for l in L.search_listings("toyota")] == [lid]
    assert len(L.search_listings(category="transport")) == 2
    assert len(L.search_listings("pick")) == 2           # prefix match
    L.close_listing(lid)
    assert L.search_listings("toyota") == []
    with pytest.raises(LedgerError):
        L.post_listing(a, "offer", "nonsense", "x")


def test_backup_and_verify_from_copy(site, tmp_path):
    L, ss, tp = site
    a, sa, _ = enroll(L, ss, tp, "alice")
    b, sb, _ = enroll(L, ss, tp, "bob")
    L.transact(sa, sb, 100, "x")
    p = L.backup(tmp_path / "drive1")
    L2 = Ledger(p)
    assert L2.verify().ok and L2.site_id == L.site_id
