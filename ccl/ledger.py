# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Scotty Wimberley
"""The ledger: SQLite schema, members, devices, enrollment certificates,
dual-signed hash-chained transactions, listings, verification, backup.

Amounts are stored as integers in hundredths of a credit (so 12.50 credits is
1250) — never floats.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from . import crypto
from .signer import Signer, stick_dir, CERT_FILE, SITE_PUB_FILE, HISTORY_FILE

GENESIS_HASH = "0" * 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sites (
    site_id     TEXT PRIMARY KEY,
    public_key  TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created     TEXT NOT NULL,
    is_local    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS members (
    id           INTEGER PRIMARY KEY,
    site_id      TEXT NOT NULL REFERENCES sites(site_id),
    display_name TEXT NOT NULL,
    contact      TEXT NOT NULL DEFAULT '',
    credit_limit INTEGER NOT NULL DEFAULT 0,   -- most negative balance allowed, in hundredths (stored positive)
    status       TEXT NOT NULL DEFAULT 'active', -- active | suspended | closed
    is_admin     INTEGER NOT NULL DEFAULT 0,
    enrolled     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id          INTEGER PRIMARY KEY,
    member_id   INTEGER NOT NULL REFERENCES members(id),
    public_key  TEXT NOT NULL UNIQUE,
    device_type TEXT NOT NULL,                  -- stick | token | site
    label       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active', -- active | revoked
    registered  TEXT NOT NULL,
    revoked     TEXT,
    certificate TEXT NOT NULL                   -- JSON enrollment certificate
);
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY,
    site_id     TEXT NOT NULL,
    prev_hash   TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    payer_id    INTEGER NOT NULL REFERENCES members(id),
    payee_id    INTEGER NOT NULL REFERENCES members(id),
    amount      INTEGER NOT NULL CHECK (amount > 0),
    description TEXT NOT NULL,
    listing_id  INTEGER,
    kind        TEXT NOT NULL DEFAULT 'trade',  -- trade | fee | reversal
    payer_key   TEXT NOT NULL,
    payee_key   TEXT NOT NULL,
    payer_sig   TEXT NOT NULL,
    payee_sig   TEXT NOT NULL,
    entry_hash  TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS tx_payer ON transactions(payer_id);
CREATE INDEX IF NOT EXISTS tx_payee ON transactions(payee_id);
CREATE TABLE IF NOT EXISTS categories (
    name TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS listings (
    id          INTEGER PRIMARY KEY,
    member_id   INTEGER NOT NULL REFERENCES members(id),
    type        TEXT NOT NULL CHECK (type IN ('offer','want')),
    category    TEXT NOT NULL REFERENCES categories(name),
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    unit        TEXT NOT NULL DEFAULT 'each',   -- hour | each | day | kg | ...
    asking      INTEGER,                        -- hundredths; NULL = negotiable
    trades_ok   INTEGER NOT NULL DEFAULT 1,
    posted      TEXT NOT NULL,
    expires     TEXT,
    status      TEXT NOT NULL DEFAULT 'open'    -- open | closed | expired
);
CREATE VIRTUAL TABLE IF NOT EXISTS listings_fts USING fts5(
    title, description, content='listings', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS listings_ai AFTER INSERT ON listings BEGIN
    INSERT INTO listings_fts(rowid, title, description) VALUES (new.id, new.title, new.description);
END;
CREATE TRIGGER IF NOT EXISTS listings_ad AFTER DELETE ON listings BEGIN
    INSERT INTO listings_fts(listings_fts, rowid, title, description) VALUES ('delete', old.id, old.title, old.description);
END;
CREATE TRIGGER IF NOT EXISTS listings_au AFTER UPDATE ON listings BEGIN
    INSERT INTO listings_fts(listings_fts, rowid, title, description) VALUES ('delete', old.id, old.title, old.description);
    INSERT INTO listings_fts(rowid, title, description) VALUES (new.id, new.title, new.description);
END;
"""

DEFAULT_CATEGORIES = ["trades", "transport", "tools", "food", "livestock",
                      "housing", "clothing", "services", "other"]


class LedgerError(Exception):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------
# Amount helpers
# --------------------------------------------------------------------------

def parse_amount(s: str | int | Decimal) -> int:
    """'12.50' -> 1250. Rejects more than two decimals and non-positive values."""
    try:
        d = Decimal(str(s))
    except InvalidOperation:
        raise LedgerError(f"not an amount: {s!r}")
    if d != d.quantize(Decimal("0.01")):
        raise LedgerError("amounts have at most two decimal places")
    if d <= 0:
        raise LedgerError("amount must be positive")
    return int(d * 100)


def fmt_amount(hundredths: int) -> str:
    sign = "-" if hundredths < 0 else ""
    h = abs(hundredths)
    return f"{sign}{h // 100}.{h % 100:02d}"


# --------------------------------------------------------------------------
# Enrollment certificates (§4a)
# --------------------------------------------------------------------------

def make_certificate(site_id: str, member_id: int, device_public_key: str,
                     site_signer: Signer) -> dict:
    body = {"site_id": site_id, "member_id": member_id,
            "device_public_key": device_public_key, "issued": now()}
    sig = site_signer.sign(crypto.digest_of(body))
    return {**body, "signature": sig.hex()}


def verify_certificate(cert: dict, site_public_key: str) -> bool:
    body = {k: cert[k] for k in ("site_id", "member_id", "device_public_key", "issued")}
    return crypto.verify_digest(site_public_key, crypto.digest_of(body),
                                bytes.fromhex(cert["signature"]))


# --------------------------------------------------------------------------
# Transaction records
# --------------------------------------------------------------------------

SIGNED_FIELDS = ("site_id", "prev_hash", "timestamp", "payer_id", "payee_id",
                 "amount", "description", "listing_id", "kind",
                 "payer_key", "payee_key")


def signed_body(row: dict) -> dict:
    return {k: row[k] for k in SIGNED_FIELDS}


def entry_hash(row: dict) -> str:
    return crypto.hash_hex({**signed_body(row),
                            "payer_sig": row["payer_sig"],
                            "payee_sig": row["payee_sig"]})


@dataclass
class VerifyResult:
    ok: bool
    entries: int
    balances: dict[int, int]
    problems: list[str]
    tip_hash: str


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------

class Ledger:
    def __init__(self, db_path: str | os.PathLike):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # ---- settings -------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))

    # ---- site identity --------------------------------------------------

    @property
    def initialised(self) -> bool:
        return self.get_setting("site_id") is not None

    @property
    def site_id(self) -> str:
        sid = self.get_setting("site_id")
        if sid is None:
            raise LedgerError("ledger not initialised; run `ccl init`")
        return sid

    @property
    def site_public_key(self) -> str:
        return self.conn.execute("SELECT public_key FROM sites WHERE site_id=?",
                                 (self.site_id,)).fetchone()["public_key"]

    def init_site(self, site_signer: Signer, description: str, admin_name: str,
                  admin_contact: str = "") -> tuple[str, int]:
        """Create the site identity and the administrator member.

        The administrator's first device *is* the site key, so fees are ordinary
        dual-signed transactions from payer to administrator.
        """
        if self.initialised:
            raise LedgerError("ledger already initialised")
        site_id = str(uuid.uuid4())
        pub = site_signer.public_key()
        with self.conn:
            self.conn.execute(
                "INSERT INTO sites(site_id, public_key, description, created, is_local) VALUES(?,?,?,?,1)",
                (site_id, pub, description, now()))
            self.conn.execute("INSERT INTO settings VALUES('site_id',?)", (site_id,))
            self.conn.execute("INSERT INTO settings VALUES('fee',?)", ("0",))
            self.conn.execute("INSERT INTO settings VALUES('listing_days',?)", ("60",))
            for c in DEFAULT_CATEGORIES:
                self.conn.execute("INSERT OR IGNORE INTO categories VALUES(?)", (c,))
        admin_id = self.enroll_member(admin_name, admin_contact, credit_limit=0, is_admin=True)
        self.register_device(admin_id, pub, "site", "site key", site_signer)
        return site_id, admin_id

    # ---- members --------------------------------------------------------

    def enroll_member(self, name: str, contact: str = "", credit_limit: int = 0,
                      is_admin: bool = False) -> int:
        if credit_limit < 0:
            raise LedgerError("credit limit is given as a positive number")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO members(site_id, display_name, contact, credit_limit, is_admin, enrolled) "
                "VALUES(?,?,?,?,?,?)",
                (self.site_id, name, contact, credit_limit, int(is_admin), now()))
        return cur.lastrowid

    def member(self, member_id: int) -> sqlite3.Row:
        r = self.conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
        if r is None:
            raise LedgerError(f"no member #{member_id}")
        return r

    def admin_id(self) -> int:
        return self.conn.execute("SELECT id FROM members WHERE is_admin=1 ORDER BY id LIMIT 1").fetchone()["id"]

    def members(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM members ORDER BY id").fetchall()

    def set_credit_limit(self, member_id: int, limit: int) -> None:
        self.member(member_id)
        with self.conn:
            self.conn.execute("UPDATE members SET credit_limit=? WHERE id=?", (limit, member_id))

    def set_member_status(self, member_id: int, status: str) -> None:
        if status not in ("active", "suspended", "closed"):
            raise LedgerError("status must be active, suspended or closed")
        self.member(member_id)
        with self.conn:
            self.conn.execute("UPDATE members SET status=? WHERE id=?", (status, member_id))

    # ---- devices --------------------------------------------------------

    def register_device(self, member_id: int, public_key: str, device_type: str,
                        label: str, site_signer: Signer) -> dict:
        """Bind a public key to a member and issue its enrollment certificate."""
        self.member(member_id)
        cert = make_certificate(self.site_id, member_id, public_key, site_signer)
        with self.conn:
            self.conn.execute(
                "INSERT INTO devices(member_id, public_key, device_type, label, registered, certificate) "
                "VALUES(?,?,?,?,?,?)",
                (member_id, public_key, device_type, label, now(), json.dumps(cert)))
        return cert

    def revoke_device(self, public_key: str) -> None:
        r = self.conn.execute("SELECT * FROM devices WHERE public_key=?", (public_key,)).fetchone()
        if r is None:
            raise LedgerError("unknown device key")
        if r["device_type"] == "site":
            raise LedgerError("the site key cannot be revoked")
        with self.conn:
            self.conn.execute("UPDATE devices SET status='revoked', revoked=? WHERE public_key=?",
                              (now(), public_key))

    def devices_for(self, member_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM devices WHERE member_id=? ORDER BY id",
                                 (member_id,)).fetchall()

    def device(self, public_key: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM devices WHERE public_key=?", (public_key,)).fetchone()

    def member_for_signer(self, signer: Signer) -> int:
        """Resolve a plugged-in device to an active member, or raise."""
        d = self.device(signer.public_key())
        if d is None:
            raise LedgerError(f"{signer.label}: key is not enrolled at this site")
        if d["status"] != "active":
            raise LedgerError(f"{signer.label}: this device has been revoked")
        cert = json.loads(d["certificate"])
        if not verify_certificate(cert, self.site_public_key):
            raise LedgerError(f"{signer.label}: enrollment certificate is invalid")
        m = self.member(d["member_id"])
        if m["status"] != "active":
            raise LedgerError(f"member #{m['id']} {m['display_name']} is {m['status']}")
        return m["id"]

    # ---- stick provisioning --------------------------------------------

    def write_stick_files(self, stick_path: str | os.PathLike, cert: dict) -> None:
        d = stick_dir(stick_path)
        d.mkdir(parents=True, exist_ok=True)
        (d / CERT_FILE).write_text(json.dumps(cert, indent=1))
        (d / SITE_PUB_FILE).write_text(self.site_public_key + "\n")
        (d / "README.txt").write_text(
            "Community Credit Ledger member device.\n"
            f"Site: {self.site_id}\nMember: #{cert['member_id']}\n\n"
            "key.json      your private key, encrypted with your PIN\n"
            "cert.json     enrollment certificate signed by the site\n"
            "site.pub      the site's public key\n"
            "history.jsonl signed copies of your transactions\n\n"
            "Keep this stick safe. Anyone with it AND your PIN can sign as you.\n")

    def refresh_history(self, stick_path: str | os.PathLike, member_id: int) -> int:
        """Rewrite the member's full signed history onto the stick. Returns count."""
        rows = self.statement(member_id)
        d = stick_dir(stick_path)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (HISTORY_FILE + ".tmp")
        with open(tmp, "w") as f:
            for r in rows:
                f.write(json.dumps(self._tx_export(r), sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, d / HISTORY_FILE)
        return len(rows)

    @staticmethod
    def _tx_export(r: sqlite3.Row) -> dict:
        return {k: r[k] for k in r.keys()}

    # ---- transactions ---------------------------------------------------

    def tip(self) -> tuple[int, str]:
        r = self.conn.execute("SELECT id, entry_hash FROM transactions ORDER BY id DESC LIMIT 1").fetchone()
        return (r["id"], r["entry_hash"]) if r else (0, GENESIS_HASH)

    def balance(self, member_id: int) -> int:
        r = self.conn.execute(
            "SELECT COALESCE((SELECT SUM(amount) FROM transactions WHERE payee_id=?),0) - "
            "       COALESCE((SELECT SUM(amount) FROM transactions WHERE payer_id=?),0) AS b",
            (member_id, member_id)).fetchone()
        return r["b"]

    def fee(self) -> int:
        return int(self.get_setting("fee", "0"))

    def transact(self, payer: Signer, payee: Signer, amount: int, description: str,
                 listing_id: int | None = None, kind: str = "trade",
                 site_signer: Signer | None = None,
                 confirm=None) -> list[sqlite3.Row]:
        """Record a dual-signed transaction (plus a fee transaction if a fee is
        set and `site_signer` is supplied). Returns the rows appended.

        `confirm(summary: str) -> bool` is called before any signature is
        requested so both parties can see the amount on screen.
        """
        if kind not in ("trade", "fee", "reversal"):
            raise LedgerError("bad kind")
        if not description.strip():
            raise LedgerError("a description is required")
        payer_id = self.member_for_signer(payer)
        payee_id = self.member_for_signer(payee)
        if payer_id == payee_id:
            raise LedgerError("payer and payee are the same member")
        if listing_id is not None and self.listing(listing_id) is None:
            raise LedgerError(f"no listing #{listing_id}")

        fee = self.fee() if kind == "trade" else 0
        admin = self.admin_id()
        if fee and site_signer is None:
            raise LedgerError("a fee is configured but no site signer was supplied to collect it")
        if fee and payer_id == admin:
            fee = 0

        payer_m = self.member(payer_id)
        total_out = amount + fee
        if self.balance(payer_id) - total_out < -payer_m["credit_limit"]:
            raise LedgerError(
                f"{payer_m['display_name']} would exceed credit limit "
                f"(balance {fmt_amount(self.balance(payer_id))}, limit -{fmt_amount(payer_m['credit_limit'])})")

        summary = (f"{payer_m['display_name']} (#{payer_id}) pays "
                   f"{self.member(payee_id)['display_name']} (#{payee_id}) "
                   f"{fmt_amount(amount)} credits for: {description}")
        if fee:
            summary += f"\n+ fee of {fmt_amount(fee)} credits to the administrator"
        if confirm is not None and not confirm(summary):
            raise LedgerError("cancelled")

        appended = []
        with self.conn:
            appended.append(self._append(payer, payee, payer_id, payee_id, amount,
                                         description, listing_id, kind))
            if fee:
                appended.append(self._append(payer, site_signer, payer_id, admin, fee,
                                             f"transaction fee for #{appended[0]['id']}",
                                             None, "fee"))
        return appended

    def _append(self, payer: Signer, payee: Signer, payer_id: int, payee_id: int,
                amount: int, description: str, listing_id: int | None, kind: str) -> sqlite3.Row:
        _, prev = self.tip()
        row = {
            "site_id": self.site_id, "prev_hash": prev, "timestamp": now(),
            "payer_id": payer_id, "payee_id": payee_id, "amount": amount,
            "description": description, "listing_id": listing_id, "kind": kind,
            "payer_key": payer.public_key(), "payee_key": payee.public_key(),
        }
        digest = crypto.digest_of(signed_body(row))
        row["payer_sig"] = payer.sign(digest).hex()
        row["payee_sig"] = payee.sign(digest).hex()
        row["entry_hash"] = entry_hash(row)
        cur = self.conn.execute(
            "INSERT INTO transactions(site_id, prev_hash, timestamp, payer_id, payee_id, amount, "
            "description, listing_id, kind, payer_key, payee_key, payer_sig, payee_sig, entry_hash) "
            "VALUES(:site_id,:prev_hash,:timestamp,:payer_id,:payee_id,:amount,:description,"
            ":listing_id,:kind,:payer_key,:payee_key,:payer_sig,:payee_sig,:entry_hash)", row)
        return self.conn.execute("SELECT * FROM transactions WHERE id=?", (cur.lastrowid,)).fetchone()

    def reverse(self, original_id: int, payer: Signer, payee: Signer, reason: str,
                confirm=None) -> list[sqlite3.Row]:
        """Reversal is a new signed transaction in the opposite direction."""
        o = self.conn.execute("SELECT * FROM transactions WHERE id=?", (original_id,)).fetchone()
        if o is None:
            raise LedgerError(f"no transaction #{original_id}")
        # payer of the reversal is the original payee
        if self.member_for_signer(payer) != o["payee_id"] or self.member_for_signer(payee) != o["payer_id"]:
            raise LedgerError("reversal must be signed by the original payee (now paying) and original payer")
        return self.transact(payer, payee, o["amount"], f"reversal of #{original_id}: {reason}",
                             kind="reversal", confirm=confirm)

    def statement(self, member_id: int) -> list[sqlite3.Row]:
        self.member(member_id)
        return self.conn.execute(
            "SELECT * FROM transactions WHERE payer_id=? OR payee_id=? ORDER BY id",
            (member_id, member_id)).fetchall()

    def all_transactions(self) -> Iterable[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM transactions ORDER BY id")

    # ---- verification ---------------------------------------------------

    def verify(self) -> VerifyResult:
        """Walk the whole chain: hashes, both signatures, key ownership, balances."""
        problems: list[str] = []
        balances: dict[int, int] = {}
        prev = GENESIS_HASH
        n = 0
        site_pub = self.site_public_key
        key_owner = {d["public_key"]: (d["member_id"], json.loads(d["certificate"]))
                     for d in self.conn.execute("SELECT * FROM devices")}
        for pk, (mid, cert) in key_owner.items():
            if not verify_certificate(cert, site_pub) or cert["member_id"] != mid \
                    or cert["device_public_key"] != pk:
                problems.append(f"device {pk[:16]}…: bad enrollment certificate")
        for r in self.all_transactions():
            n += 1
            row = dict(r)
            tag = f"#{row['id']}"
            if row["prev_hash"] != prev:
                problems.append(f"{tag}: chain broken (prev_hash mismatch)")
            if entry_hash(row) != row["entry_hash"]:
                problems.append(f"{tag}: entry hash does not match contents")
            digest = crypto.digest_of(signed_body(row))
            for role in ("payer", "payee"):
                key = row[f"{role}_key"]
                owner = key_owner.get(key)
                if owner is None or owner[0] != row[f"{role}_id"]:
                    problems.append(f"{tag}: {role} key is not a registered device of member #{row[f'{role}_id']}")
                if not crypto.verify_digest(key, digest, bytes.fromhex(row[f"{role}_sig"])):
                    problems.append(f"{tag}: {role} signature invalid")
            balances[row["payer_id"]] = balances.get(row["payer_id"], 0) - row["amount"]
            balances[row["payee_id"]] = balances.get(row["payee_id"], 0) + row["amount"]
            prev = row["entry_hash"]
        if sum(balances.values()) != 0:
            problems.append("balances do not sum to zero")
        for mid, b in balances.items():
            if self.balance(mid) != b:
                problems.append(f"member #{mid}: stored balance {fmt_amount(self.balance(mid))} != recomputed {fmt_amount(b)}")
        return VerifyResult(ok=not problems, entries=n, balances=balances, problems=problems, tip_hash=prev)

    # ---- backup ---------------------------------------------------------

    def backup(self, dest_dir: str | os.PathLike) -> Path:
        """Consistent copy via the SQLite backup API, named with a timestamp."""
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = dest_dir / f"ledger-{self.site_id[:8]}-{stamp}.db"
        out = sqlite3.connect(target)
        with out:
            self.conn.backup(out)
        out.close()
        # keep a stable "latest" copy alongside the dated ones
        shutil.copy2(target, dest_dir / f"ledger-{self.site_id[:8]}-latest.db")
        return target

    # ---- categories -----------------------------------------------------

    def categories(self) -> list[str]:
        return [r["name"] for r in self.conn.execute("SELECT name FROM categories ORDER BY name")]

    def add_category(self, name: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO categories VALUES(?)", (name.strip().lower(),))

    def remove_category(self, name: str) -> None:
        used = self.conn.execute("SELECT COUNT(*) c FROM listings WHERE category=?", (name,)).fetchone()["c"]
        if used:
            raise LedgerError(f"category '{name}' is used by {used} listing(s)")
        with self.conn:
            self.conn.execute("DELETE FROM categories WHERE name=?", (name,))

    # ---- listings -------------------------------------------------------

    def post_listing(self, member_id: int, ltype: str, category: str, title: str,
                     description: str = "", unit: str = "each", asking: int | None = None,
                     trades_ok: bool = True, days: int | None = None) -> tuple[int, list[sqlite3.Row]]:
        """Post an offer or want. Returns (listing id, matching opposite listings)."""
        if self.member(member_id)["status"] != "active":
            raise LedgerError("member is not active")
        if ltype not in ("offer", "want"):
            raise LedgerError("type must be offer or want")
        if category not in self.categories():
            raise LedgerError(f"unknown category '{category}'; known: {', '.join(self.categories())}")
        days = days if days is not None else int(self.get_setting("listing_days", "60"))
        expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).date().isoformat()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO listings(member_id,type,category,title,description,unit,asking,trades_ok,posted,expires) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (member_id, ltype, category, title, description, unit, asking, int(trades_ok), now(), expires))
        lid = cur.lastrowid
        other = "want" if ltype == "offer" else "offer"
        matches = self.search_listings(query=title, category=category, ltype=other)
        matches = [m for m in matches if m["member_id"] != member_id]
        return lid, matches

    def listing(self, listing_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()

    def close_listing(self, listing_id: int) -> None:
        if self.listing(listing_id) is None:
            raise LedgerError(f"no listing #{listing_id}")
        with self.conn:
            self.conn.execute("UPDATE listings SET status='closed' WHERE id=?", (listing_id,))

    def expire_listings(self) -> int:
        today = dt.date.today().isoformat()
        with self.conn:
            cur = self.conn.execute(
                "UPDATE listings SET status='expired' WHERE status='open' AND expires < ?", (today,))
        return cur.rowcount

    def search_listings(self, query: str = "", category: str | None = None,
                        ltype: str | None = None, include_closed: bool = False) -> list[sqlite3.Row]:
        sql = ["SELECT l.* FROM listings l"]
        args: list = []
        where = []
        q = query.strip()
        if q:
            # FTS5 OR-of-terms: any word matches; prefix match on each term.
            terms = [t for t in "".join(ch if ch.isalnum() else " " for ch in q).split() if t]
            if terms:
                fts = " OR ".join(f'"{t}"*' for t in terms)
                sql.append("JOIN listings_fts f ON f.rowid = l.id")
                where.append("listings_fts MATCH ?")
                args.append(fts)
        if category:
            where.append("l.category=?"); args.append(category)
        if ltype:
            where.append("l.type=?"); args.append(ltype)
        if not include_closed:
            where.append("l.status='open'")
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY l.posted DESC")
        return self.conn.execute(" ".join(sql), args).fetchall()

    def recent_listings(self, days: int = 7) -> list[sqlite3.Row]:
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
        return self.conn.execute(
            "SELECT * FROM listings WHERE status='open' AND posted >= ? ORDER BY type, category, posted DESC",
            (since,)).fetchall()
