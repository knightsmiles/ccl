# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Scotty Wimberley
"""ccl — command-line interface for the Community Credit Ledger.

Run `ccl --help`. The database path comes from --db or $CCL_DB
(default ./ledger.db). The site key comes from --site-key or $CCL_SITE_KEY:
a directory holding an encrypted key.json (the administrator's stick) or the
word `yubikey`.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from . import __version__
from .ledger import Ledger, LedgerError, fmt_amount, parse_amount
from .signer import (StickSigner, YubiKeySigner, Signer, stick_dir,
                     CERT_FILE, KEY_FILE)


def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def open_signer(spec: str | None, label: str, pin: str | None = None) -> Signer:
    if not spec:
        die(f"no device given for {label}")
    if spec.lower() == "yubikey":
        return YubiKeySigner(pin=pin, label=label)
    p = Path(spec)
    if not (stick_dir(p) / KEY_FILE).exists():
        die(f"{p} does not contain {os.path.join('ccl', KEY_FILE)} — is the stick mounted?")
    return StickSigner(p, pin=pin, label=label)


def ask_new_pin(label: str) -> str:
    while True:
        a = getpass.getpass(f"Choose a PIN for {label}: ")
        if len(a) < 4:
            print("PIN must be at least 4 characters."); continue
        b = getpass.getpass("Repeat PIN: ")
        if a == b:
            return a
        print("PINs do not match; try again.")


def yes(prompt: str) -> bool:
    return input(f"{prompt}\nConfirm? [y/N] ").strip().lower() in ("y", "yes")


def print_table(rows, cols):
    if not rows:
        print("(none)"); return
    widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) for i, c in enumerate(cols)]
    print("  ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_init(a, L: Ledger):
    if L.initialised:
        die("this ledger is already initialised")
    spec = a.site_key
    if spec.lower() == "yubikey":
        print("Generating site key in YubiKey slot 9c…")
        YubiKeySigner.generate_key()
        signer = YubiKeySigner(label="site key")
    else:
        if (stick_dir(spec) / KEY_FILE).exists():
            die(f"{spec} already holds a key; choose an empty stick for the site key")
        pin = a.pin or ask_new_pin("the site key")
        StickSigner.create(spec, pin)
        signer = StickSigner(spec, pin=pin, label="site key")
    site_id, admin_id = L.init_site(signer, a.description, a.admin_name, a.admin_contact or "")
    if spec.lower() != "yubikey":
        cert = json.loads(L.devices_for(admin_id)[0]["certificate"])
        L.write_stick_files(spec, cert)
    print(f"Site {site_id} created.")
    print(f"Administrator is member #{admin_id} ({a.admin_name}).")
    print(f"Site public key: {L.site_public_key}")
    print("Keep the site key safe — it is the authority that enrolls members and collects fees.")


def cmd_enroll(a, L: Ledger):
    site = open_signer(a.site_key, "site key", a.site_pin)
    limit = parse_amount(a.limit) if a.limit and a.limit != "0" else 0
    mid = L.enroll_member(a.name, a.contact or "", limit)
    print(f"Enrolled member #{mid}: {a.name}  (credit limit -{fmt_amount(limit)})")
    for stick in (a.stick or []):
        _add_stick(L, site, mid, stick, a.pin, a.label)
    if a.yubikey:
        _add_yubikey(L, site, mid, a.label)


def _add_stick(L: Ledger, site: Signer, mid: int, stick: str, pin: str | None, label: str | None):
    if (stick_dir(stick) / KEY_FILE).exists():
        die(f"{stick} already holds a key")
    pin = pin or ask_new_pin(f"member #{mid}'s stick at {stick}")
    pub = StickSigner.create(stick, pin)
    cert = L.register_device(mid, pub, "stick", label or f"stick {Path(stick).name}", site)
    L.write_stick_files(stick, cert)
    L.refresh_history(stick, mid)
    print(f"  stick {stick}: key {pub[:16]}… enrolled and certificate written")


def _add_yubikey(L: Ledger, site: Signer, mid: int, label: str | None):
    print("Generating key in YubiKey slot 9c…")
    pub = YubiKeySigner.generate_key()
    L.register_device(mid, pub, "token", label or "yubikey", site)
    print(f"  YubiKey key {pub[:16]}… enrolled (certificate kept in the ledger)")


def cmd_device_add(a, L: Ledger):
    site = open_signer(a.site_key, "site key", a.site_pin)
    if a.stick:
        _add_stick(L, site, a.member, a.stick, a.pin, a.label)
    elif a.yubikey:
        _add_yubikey(L, site, a.member, a.label)
    else:
        die("give --stick PATH or --yubikey")


def cmd_device_revoke(a, L: Ledger):
    key = a.key or ""
    if a.member is not None:
        devs = [d for d in L.devices_for(a.member) if d["status"] == "active"]
        if not devs:
            die("no active devices for that member")
        for d in devs:
            print(f"  {d['id']:>4}  {d['device_type']:<6} {d['label']:<20} {d['public_key'][:16]}…")
        did = int(input("Device id to revoke: "))
        m = [d for d in devs if d["id"] == did]
        if not m:
            die("no such device id")
        key = m[0]["public_key"]
    full = [d["public_key"] for d in L.conn.execute("SELECT public_key FROM devices")
            if d["public_key"].startswith(key)]
    if len(full) != 1:
        die("key prefix does not identify exactly one device")
    L.revoke_device(full[0])
    print(f"Revoked {full[0][:16]}…  Existing signatures remain valid.")


def cmd_device_list(a, L: Ledger):
    rows = [(d["id"], d["member_id"], d["device_type"], d["label"], d["status"],
             d["public_key"][:16] + "…", d["registered"][:10])
            for d in L.devices_for(a.member)]
    print_table(rows, ["id", "member", "type", "label", "status", "key", "registered"])


def cmd_members(a, L: Ledger):
    rows = [(m["id"], m["display_name"], m["contact"], fmt_amount(L.balance(m["id"])),
             "-" + fmt_amount(m["credit_limit"]), m["status"], "admin" if m["is_admin"] else "")
            for m in L.members()]
    print_table(rows, ["id", "name", "contact", "balance", "limit", "status", ""])


def cmd_member_set(a, L: Ledger):
    if a.limit is not None:
        L.set_credit_limit(a.member, parse_amount(a.limit) if a.limit != "0" else 0)
    if a.status:
        L.set_member_status(a.member, a.status)
    print("ok")


def cmd_whoami(a, L: Ledger):
    s = open_signer(a.device, "device")
    mid = L.member_for_signer(s)
    m = L.member(mid)
    print(f"Member #{mid} {m['display_name']}  balance {fmt_amount(L.balance(mid))}  "
          f"limit -{fmt_amount(m['credit_limit'])}")


def cmd_transact(a, L: Ledger):
    payer = open_signer(a.payer, "payer", a.payer_pin)
    payee = open_signer(a.payee, "payee", a.payee_pin)
    site = open_signer(a.site_key, "site key", a.site_pin) if L.fee() else None
    rows = L.transact(payer, payee, parse_amount(a.amount), a.description,
                      listing_id=a.listing, site_signer=site,
                      confirm=None if a.yes else yes)
    for r in rows:
        print(f"Recorded #{r['id']} {r['kind']}: {fmt_amount(r['amount'])} credits  hash {r['entry_hash'][:16]}…")
    for spec, s in ((a.payer, payer), (a.payee, payee)):
        if spec.lower() != "yubikey":
            n = L.refresh_history(spec, L.member_for_signer(s))
            print(f"  receipt written to {spec} ({n} entries in history)")
    if a.listing and a.close_listing:
        L.close_listing(a.listing)
        print(f"  listing #{a.listing} closed")


def cmd_reverse(a, L: Ledger):
    payer = open_signer(a.payer, "original payee (now paying back)", a.payer_pin)
    payee = open_signer(a.payee, "original payer", a.payee_pin)
    rows = L.reverse(a.transaction, payer, payee, a.reason, confirm=None if a.yes else yes)
    for r in rows:
        print(f"Recorded #{r['id']} {r['kind']}: {fmt_amount(r['amount'])} credits")


def cmd_balance(a, L: Ledger):
    m = L.member(a.member)
    print(f"#{m['id']} {m['display_name']}: {fmt_amount(L.balance(m['id']))} credits "
          f"(limit -{fmt_amount(m['credit_limit'])})")


def cmd_statement(a, L: Ledger):
    m = L.member(a.member)
    running = 0
    rows = []
    for t in L.statement(a.member):
        sign = 1 if t["payee_id"] == a.member else -1
        running += sign * t["amount"]
        other = t["payer_id"] if sign == 1 else t["payee_id"]
        rows.append((t["id"], t["timestamp"][:16].replace("T", " "),
                     ("+" if sign == 1 else "-") + fmt_amount(t["amount"]),
                     f"#{other} {L.member(other)['display_name']}", t["description"][:40],
                     fmt_amount(running)))
    print(f"Statement for #{m['id']} {m['display_name']}")
    print_table(rows, ["tx", "when", "amount", "counterparty", "description", "balance"])


def cmd_history_refresh(a, L: Ledger):
    s = open_signer(a.stick, "stick")
    mid = L.member_for_signer(s)
    n = L.refresh_history(a.stick, mid)
    print(f"{n} entries written to {a.stick}")


def cmd_verify(a, L: Ledger):
    r = L.verify()
    print(f"{r.entries} entries checked; tip hash {r.tip_hash}")
    for mid, b in sorted(r.balances.items()):
        print(f"  #{mid:<4} {fmt_amount(b):>12}")
    if r.ok:
        print("OK — chain intact, all signatures valid, balances sum to zero.")
    else:
        print(f"{len(r.problems)} PROBLEM(S):")
        for p in r.problems:
            print("  ! " + p)
        sys.exit(2)


def cmd_backup(a, L: Ledger):
    for d in a.to:
        try:
            p = L.backup(d)
            print(f"backup written: {p}")
        except OSError as e:
            print(f"backup to {d} FAILED: {e}", file=sys.stderr)


def cmd_fee(a, L: Ledger):
    if a.amount is None:
        print(f"fee per transaction: {fmt_amount(L.fee())}")
    else:
        L.set_setting("fee", str(parse_amount(a.amount) if a.amount != "0" else 0))
        print("ok")


def cmd_category(a, L: Ledger):
    if a.add:
        L.add_category(a.add)
    if a.remove:
        L.remove_category(a.remove)
    print(", ".join(L.categories()))


def _print_listings(L: Ledger, rows):
    out = []
    for l in rows:
        price = "negotiable" if l["asking"] is None else f"{fmt_amount(l['asking'])}/{l['unit']}"
        out.append((l["id"], l["type"], l["category"], l["title"][:34],
                    price, f"#{l['member_id']} {L.member(l['member_id'])['display_name']}",
                    l["expires"]))
    print_table(out, ["id", "type", "category", "title", "asking", "member", "expires"])


def cmd_listing_post(a, L: Ledger):
    if a.member is None:
        mid = L.member_for_signer(open_signer(a.device, "device"))
    else:
        mid = a.member
    asking = parse_amount(a.asking) if a.asking else None
    lid, matches = L.post_listing(mid, a.type, a.category, a.title, a.description or "",
                                  a.unit, asking, not a.no_trades, a.days)
    print(f"Posted listing #{lid}")
    if matches:
        print(f"\nPossible matches ({'wants' if a.type == 'offer' else 'offers'}):")
        _print_listings(L, matches)


def cmd_listing_search(a, L: Ledger):
    L.expire_listings()
    _print_listings(L, L.search_listings(a.query or "", a.category, a.type, a.all))


def cmd_listing_show(a, L: Ledger):
    l = L.listing(a.id)
    if l is None:
        die("no such listing")
    m = L.member(l["member_id"])
    price = "negotiable" if l["asking"] is None else f"{fmt_amount(l['asking'])} per {l['unit']}"
    print(f"#{l['id']}  {l['type'].upper()}  [{l['category']}]  {l['title']}\n"
          f"by #{m['id']} {m['display_name']}  contact: {m['contact']}\n"
          f"asking: {price}   trades considered: {'yes' if l['trades_ok'] else 'no'}\n"
          f"posted {l['posted'][:10]}  expires {l['expires']}  status {l['status']}\n\n{l['description']}")


def cmd_listing_close(a, L: Ledger):
    L.close_listing(a.id); print("ok")


def cmd_listing_report(a, L: Ledger):
    L.expire_listings()
    rows = L.recent_listings(a.days)
    print(f"NEW LISTINGS — last {a.days} days".center(72))
    print("=" * 72)
    cur = None
    for l in rows:
        head = (l["type"], l["category"])
        if head != cur:
            cur = head
            print(f"\n{l['type'].upper()}S — {l['category']}")
            print("-" * 72)
        price = "negotiable" if l["asking"] is None else f"{fmt_amount(l['asking'])}/{l['unit']}"
        m = L.member(l["member_id"])
        print(f"#{l['id']:<4} {l['title'][:44]:<44} {price:>16}")
        print(f"      {m['display_name']}  {m['contact']}")
        if l["description"]:
            print(f"      {l['description'][:64]}")
    print("\n" + "=" * 72)
    tip = L.tip()
    print(f"Ledger tip: entry #{tip[0]}  {tip[1]}")


def cmd_site(a, L: Ledger):
    print(f"site_id     {L.site_id}\npublic key  {L.site_public_key}\n"
          f"members     {len(L.members())}\nentries     {L.tip()[0]}\ntip hash    {L.tip()[1]}\n"
          f"fee         {fmt_amount(L.fee())}\ndatabase    {L.db_path.resolve()}")


def cmd_stick_info(a, L: Ledger | None):
    d = stick_dir(a.stick)
    if not (d / CERT_FILE).exists():
        die("no enrollment certificate on this stick")
    cert = json.loads((d / CERT_FILE).read_text())
    print(json.dumps(cert, indent=1))
    if L is not None and L.initialised:
        from .ledger import verify_certificate
        ok = cert["site_id"] == L.site_id and verify_certificate(cert, L.site_public_key)
        print("certificate valid for this site" if ok else "NOT valid for this site")


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ccl", description="Community Credit Ledger")
    p.add_argument("--version", action="version", version=f"ccl {__version__}")
    p.add_argument("--db", default=os.environ.get("CCL_DB", "ledger.db"), help="ledger database (or $CCL_DB)")
    p.add_argument("--site-key", default=os.environ.get("CCL_SITE_KEY"),
                   help="administrator stick dir holding the site key, or 'yubikey' (or $CCL_SITE_KEY)")
    p.add_argument("--site-pin", help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create site identity and administrator")
    s.add_argument("--admin-name", required=True)
    s.add_argument("--admin-contact")
    s.add_argument("--description", default="")
    s.add_argument("--pin", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("enroll", help="enroll a member and provision devices")
    s.add_argument("--name", required=True)
    s.add_argument("--contact")
    s.add_argument("--limit", default="0", help="credit limit (how far negative), e.g. 200")
    s.add_argument("--stick", action="append", help="mount point of an empty stick (repeatable)")
    s.add_argument("--yubikey", action="store_true")
    s.add_argument("--label")
    s.add_argument("--pin", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_enroll)

    s = sub.add_parser("members", help="list members and balances"); s.set_defaults(fn=cmd_members)

    s = sub.add_parser("member-set", help="change a member's limit or status")
    s.add_argument("member", type=int)
    s.add_argument("--limit")
    s.add_argument("--status", choices=["active", "suspended", "closed"])
    s.set_defaults(fn=cmd_member_set)

    d = sub.add_parser("device", help="member devices").add_subparsers(dest="sub", required=True)
    s = d.add_parser("add"); s.add_argument("member", type=int)
    s.add_argument("--stick"); s.add_argument("--yubikey", action="store_true"); s.add_argument("--label")
    s.add_argument("--pin", help=argparse.SUPPRESS); s.set_defaults(fn=cmd_device_add)
    s = d.add_parser("revoke"); s.add_argument("--key", help="public key or unique prefix")
    s.add_argument("--member", type=int, help="pick interactively from this member's devices")
    s.set_defaults(fn=cmd_device_revoke)
    s = d.add_parser("list"); s.add_argument("member", type=int); s.set_defaults(fn=cmd_device_list)

    s = sub.add_parser("whoami", help="identify the member from a plugged-in device")
    s.add_argument("device", help="stick mount point or 'yubikey'"); s.set_defaults(fn=cmd_whoami)

    s = sub.add_parser("transact", help="record a dual-signed transaction")
    s.add_argument("--payer", required=True, help="payer's stick mount point or 'yubikey'")
    s.add_argument("--payee", required=True, help="payee's stick mount point or 'yubikey'")
    s.add_argument("--amount", required=True)
    s.add_argument("--description", "-d", required=True)
    s.add_argument("--listing", type=int)
    s.add_argument("--close-listing", action="store_true")
    s.add_argument("--yes", "-y", action="store_true", help="skip on-screen confirmation")
    s.add_argument("--payer-pin", help=argparse.SUPPRESS); s.add_argument("--payee-pin", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_transact)

    s = sub.add_parser("reverse", help="reverse a transaction (new signed entry)")
    s.add_argument("transaction", type=int)
    s.add_argument("--payer", required=True, help="original payee's device")
    s.add_argument("--payee", required=True, help="original payer's device")
    s.add_argument("--reason", required=True)
    s.add_argument("--yes", "-y", action="store_true")
    s.add_argument("--payer-pin", help=argparse.SUPPRESS); s.add_argument("--payee-pin", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_reverse)

    s = sub.add_parser("balance"); s.add_argument("member", type=int); s.set_defaults(fn=cmd_balance)
    s = sub.add_parser("statement"); s.add_argument("member", type=int); s.set_defaults(fn=cmd_statement)
    s = sub.add_parser("history-refresh", help="rewrite a member's signed history to their stick")
    s.add_argument("stick"); s.set_defaults(fn=cmd_history_refresh)

    s = sub.add_parser("verify", help="check the whole chain, signatures and balances"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("backup", help="copy the database to one or more directories")
    s.add_argument("--to", action="append", required=True); s.set_defaults(fn=cmd_backup)
    s = sub.add_parser("fee", help="show or set the per-transaction fee"); s.add_argument("amount", nargs="?")
    s.set_defaults(fn=cmd_fee)
    s = sub.add_parser("category", help="list/add/remove categories")
    s.add_argument("--add"); s.add_argument("--remove"); s.set_defaults(fn=cmd_category)
    s = sub.add_parser("site", help="show site identity"); s.set_defaults(fn=cmd_site)
    s = sub.add_parser("stick-info", help="show the certificate on a stick"); s.add_argument("stick")
    s.set_defaults(fn=cmd_stick_info)

    l = sub.add_parser("listing", help="offers and wants").add_subparsers(dest="sub", required=True)
    s = l.add_parser("post")
    s.add_argument("--member", type=int); s.add_argument("--device", help="stick or 'yubikey' instead of --member")
    s.add_argument("--type", required=True, choices=["offer", "want"])
    s.add_argument("--category", required=True); s.add_argument("--title", required=True)
    s.add_argument("--description", "-d"); s.add_argument("--unit", default="each")
    s.add_argument("--asking", help="price per unit; omit for negotiable")
    s.add_argument("--no-trades", action="store_true", help="credits only, no swaps")
    s.add_argument("--days", type=int, help="days until expiry")
    s.set_defaults(fn=cmd_listing_post)
    s = l.add_parser("search"); s.add_argument("query", nargs="?")
    s.add_argument("--category"); s.add_argument("--type", choices=["offer", "want"])
    s.add_argument("--all", action="store_true", help="include closed/expired"); s.set_defaults(fn=cmd_listing_search)
    s = l.add_parser("show"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_listing_show)
    s = l.add_parser("close"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_listing_close)
    s = l.add_parser("report", help="printable 'new listings' sheet for the notice board")
    s.add_argument("--days", type=int, default=7); s.set_defaults(fn=cmd_listing_report)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "stick-info":
            L = Ledger(a.db) if Path(a.db).exists() else None
            return cmd_stick_info(a, L)
        L = Ledger(a.db)
        if a.cmd != "init" and not L.initialised:
            die(f"{a.db} is not an initialised ledger; run `ccl init` first")
        a.fn(a, L)
    except LedgerError as e:
        die(str(e))
    except KeyboardInterrupt:
        die("interrupted", 130)
    except FileNotFoundError as e:
        die(str(e))
    except Exception as e:
        # crypto WrongPIN and similar
        die(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
