# Community Credit Ledger — Design Document

Status: implemented in ccl 0.1.0 (this document records the original design)
Author: Scotty Wimberley (with Claude)
Date: 2026-09-03

> Copyright (C) 2026 Scotty Wimberley. This document is licensed under the
> [Creative Commons Attribution-ShareAlike 4.0 International License](LICENSES/CC-BY-SA-4.0.txt)
> (CC BY-SA 4.0). You are free to copy, share, translate, and adapt it, as
> long as you give credit and release your version under the same license.
> The ccl software itself is licensed separately under the GNU GPL version 3
> or later.

## 1. Purpose

Software for a community that wants to trade goods and skilled labor without
digital money or any network connection. Runs on a single ordinary computer
(Ubuntu or Raspberry Pi).

**Open source** (decided 2026-09-03). Openness is part of the product: members
can inspect the code that signs their transactions and verifies the ledger.
Licensed GPL-3.0-or-later (code) and CC BY-SA 4.0 (documentation).
Released as is, without support.

Not intended for small one-on-one trades (eggs for a favor); those are easier
done face to face. Intended for larger or asymmetric deals where finding a
counterparty or settling a difference in value is the hard part.

## 2. Economic model: mutual credit

- Unit of account: the **credit**. Nobody issues credits. Every member starts at
  zero. Providing goods or labor raises your balance; receiving lowers it. The
  sum of all balances is always zero.
- Each member has a negative limit (credit limit) set at enrollment and
  adjustable by the administrator.
- **Rates are set by the individual, per transaction.** There is no fixed
  hour = credit rule. An engineer, a mechanic, and a laborer each publish
  their own asking rate; the buyer and seller agree a total for each job and
  that total is what the ledger records. Two mechanics may charge different
  rates.
- Physical goods (tractors, cars, tools, produce, boats) are priced the same
  way: whatever the two parties agree. Rentals (tractor by the day) are just
  another line item.
- Mixed deals (apples for four hours of electrical work) are recorded as two
  transactions that net out. If the agreed values differ, the difference
  remains as credit. No special "barter mode" is needed.
- The administrator may charge a small fee per transaction. The fee is
  recorded as an ordinary visible transaction from payer to administrator,
  never hidden in the arithmetic.

## 3. Trust model

Members trust the administrator the way credit-union members trust the person
holding the ledger book. The software's job is to make administrator
dishonesty **detectable**, not impossible:

- Forgery is impossible: every transaction is signed by both parties.
- Omission or misreporting is detectable: members carry signed copies of their
  own history, and anyone can verify the whole chain from a backup.

Two levels of member security, chosen per member at enrollment:

| Path | Where the private key lives | Trust required |
|------|-----------------------------|----------------|
| USB stick (default, ~$3) | Encrypted file on the stick; decrypted with PIN in host RAM at signing time, then wiped | Member trusts the host briefly sees the key |
| YubiKey / Nitrokey / SoloKey (optional) | Inside the device; never leaves it; PIN handled by the device | Member trusts only their own device |

A member may register more than one device (two sticks, a stick and a YubiKey,
etc.) against the same account. Losing one device means revoking that key,
not losing the account. Every member should have at least two.

## 4. Cryptography

- Signature algorithm: **ECDSA P-256 (secp256r1)** for both paths. Chosen
  because every YubiKey generation and every mainstream Python crypto library
  supports it, so a stick-generated key and a YubiKey-generated key are
  identical in the ledger.
- Hash: SHA-256.
- Transactions are dual-signed (payer and payee) over the canonical
  serialization of the record.
- The ledger is append-only. Each entry includes the hash of the previous
  entry, forming a chain. The hash of the day's last entry can be printed and
  pinned to the wall.
- USB-stick keys are stored encrypted (PIN-derived key via a proper KDF such
  as scrypt or Argon2; AES-256-GCM).
- YubiKey path uses PIV or OpenPGP-card signing via `yubikey-manager` /
  `python-fido2`.

## 4a. Site identity and enrollment certificates

- The site identity belongs to the ledger, not the machine. It is **not**
  derived from hardware (MAC, disk serial, machine-id), so a restore from
  backup onto new hardware keeps every member device valid.
- On first run the software generates a random **site ID** (UUID) and a
  **site keypair** (ECDSA P-256). Both are stored in the database and so
  travel with backups. The site private key should live on the
  administrator's own hardware token rather than on disk.
- Enrolling a device writes a small **enrollment certificate** to the stick or
  a YubiKey data slot:

      site_id, member_id, device_public_key, issued_date, signature by site key

- Any copy of the software holding the site public key can verify a
  certificate. A device from another site, or one created without the
  administrator's key, is rejected. Revocation stays a ledger operation; the
  certificate never needs rewriting.
- This also answers the copy question: the software can and should be freely
  copied. A copy cannot impersonate this ledger because it lacks the site
  private key. Authority is bound to the administrator's key, not to the
  machine or the binary.

## 5. Software architecture

Single Python application, SQLite database, no web server, no Docker, no
accounts. `pip install` and run.

### Signer abstraction

    class Signer:
        def public_key(self) -> bytes
        def sign(self, digest: bytes) -> bytes

    StickSigner    – reads encrypted key file from mounted stick, prompts PIN,
                     decrypts, signs in RAM, zeroes key material
    YubiKeySigner  – sends digest to device, device prompts PIN/touch, returns
                     signature

Everything above this layer sees only public keys and signatures and cannot
tell the two paths apart.

### Database tables (SQLite)

- `members` — id, display name, contact, credit limit, status, enrolled date,
  site_id
- `devices` — member id, public key, device type (stick / hardware token),
  label, status (active / revoked), registered date
- `transactions` — id, previous-entry hash, timestamp, payer, payee, amount,
  description, optional listing reference, payer signature, payee signature,
  entry hash
- `listings` — id, member, type (offer / want), category, title, description,
  unit (hour / each / day / kg), asking price, will-consider-trades flag,
  posted date, expiry, status
- `categories` — short fixed list maintained by the administrator (trades,
  transport, tools, food, livestock, housing, …)
- `sites` — site id, site public key, description (see §4a, §7)

Full-text search on listings via SQLite FTS5.

### Core operations

1. **Enroll** — create member, generate or register key(s), set credit limit.
2. **Transact** — both parties present device and PIN; software builds the
   record, obtains both signatures, appends to ledger, writes a copy of the
   signed entry to each party's stick.
3. **Post listing** — offer or want; on posting, automatically show matching
   listings of the opposite type.
4. **Search** — free-text plus category filter; also a printable "new
   listings this week" report for the notice board.
5. **Balance / statement** — per member, with running history.
6. **Verify** — walks the entire chain from a backup, checks every hash and
   both signatures on every entry, recomputes all balances. Anyone can run it.
7. **Backup** — automatic copy of the database to two external drives
   (cron); each member's own history is also refreshed on their stick at
   every visit.
8. **Revoke device** — mark a key inactive; existing signatures remain valid.

## 6. Member workflow (at the community computer)

1. Member plugs in stick or YubiKey; enters PIN.
2. Browses listings, posts offers/wants, checks balance.
3. To settle a deal, both parties plug in, both confirm the amount on screen,
   both enter PIN; the transaction is recorded and receipts written to both
   sticks.
4. Member unplugs and leaves. Nothing about the member remains decrypted on
   the host.

## 7. Scaling

- One machine with SQLite comfortably handles thousands of members and
  millions of transactions.
- The limit is geography, not load. Every record carries a `site_id` from
  day one so that, if a second community computer is ever needed, each site
  issues transactions only for its own members and the two ledgers can be
  merged by carrying a drive between them without conflicts. This is deferred;
  the field is included now so the option stays open.

## 8. Open questions

- Credit-limit policy: fixed at enrollment, or grow with transaction history?
- Dispute handling: reversal is a new signed transaction, never an edit — but
  who authorizes it when one party refuses to sign?
- Listing expiry defaults.
- ~~Choice of open-source license~~ — settled: GPL-3.0-or-later.
- Packaging: plain source plus PyInstaller/Nuitka binaries for x86-64 and
  ARM64 (build on the target architecture); `.deb` with a post-install
  first-run step is the tidiest on Ubuntu / Pi OS.

## 9. Reference points

LETS, Ithaca Hours, Sardex (mutual-credit currencies); Cyclos and Community
Forge (existing LETS software, network-based); YubiKey / Nitrokey / SoloKey
(hardware signing devices).
