# Community Credit Ledger (ccl)

Offline mutual-credit and barter ledger for communities. No Internet, no banks, no digital money.

ccl lets a village, farm, intentional community, or neighborhood keep a fair
record of trades in goods and skilled labour. It runs on one ordinary
computer (Ubuntu or Raspberry Pi) with SQLite and no server or network
connection. Member keys live on cheap USB sticks (encrypted, PIN-unlocked) or
on YubiKey-class hardware tokens. Every transaction is signed by both parties
and chained by hash, and anyone can verify the whole ledger from a backup.
Members set their own rates, balances start at zero and always sum to zero,
and a searchable noticeboard lists what people offer and need.

Project site: https://knightsmiles.github.io/ccl/ · Manual: [MANUAL.md](MANUAL.md) · Design: [DESIGN.md](DESIGN.md)

## Install

    sudo apt install python3-pip            # Ubuntu / Raspberry Pi OS
    pip install --break-system-packages https://github.com/knightsmiles/ccl/archive/refs/tags/v0.1.0.tar.gz

or from a checkout of this repository:

    pip install .                           # or: pip install --break-system-packages .
    pip install '.[yubikey]'                # optional, for hardware tokens

Only dependency is `cryptography` (ECDSA P-256, SHA-256, scrypt, AES-GCM).

## Layout

    ccl/crypto.py   keys, signing, canonical JSON, encrypted key files
    ccl/signer.py   Signer abstraction: StickSigner, YubiKeySigner
    ccl/ledger.py   SQLite schema, members/devices/certificates, transactions,
                    listings (FTS5), verify, backup
    ccl/cli.py      the `ccl` command
    tests/          pytest suite (python -m pytest)

## Quick start

A "stick" is just a mount point (e.g. `/media/scotty/USB1`). The commands
below use directories so you can try it without hardware.

    export CCL_DB=/var/lib/ccl/ledger.db
    export CCL_SITE_KEY=/media/scotty/ADMIN     # the administrator's stick

    ccl init --admin-name "Scotty" --description "Village ledger"
    ccl enroll --name "Alice" --contact "farm rd" --limit 200 --stick /media/scotty/USB1
    ccl enroll --name "Bob"   --contact "electrician" --limit 500 --stick /media/scotty/USB2
    ccl fee 0.25                                 # optional per-transaction fee

    ccl listing post --device /media/scotty/USB2 --type offer --category trades \
        --title "House wiring" --unit hour --asking 12
    ccl listing search wiring
    ccl listing report                           # printable sheet for the notice board

    ccl transact --payer /media/scotty/USB1 --payee /media/scotty/USB2 \
        --amount 48 -d "4h barn wiring" --listing 1 --close-listing

    ccl members
    ccl statement 2
    ccl verify
    ccl backup --to /media/scotty/BACKUP1 --to /media/scotty/BACKUP2

Everything that needs the site key (`init`, `enroll`, `device add`, and
`transact` when a fee is set) prompts for the site-key PIN. Members are
prompted for their own PINs at signing time. Global options (`--db`,
`--site-key`) go before the subcommand.

## What is on a member's stick

    ccl/key.json       private key, AES-256-GCM, key derived from PIN with scrypt
    ccl/cert.json      enrollment certificate signed by the site key
    ccl/site.pub       site public key
    ccl/history.jsonl  signed copies of every transaction the member is party to
    ccl/README.txt

Losing a stick: `ccl device revoke --member N` (pick the device), then
`ccl device add N --stick /media/...` for a replacement. Old signatures remain
valid. Enroll two devices per member from the start.

## Fees

The administrator is member #1 and the site key is registered as that
member's signing device. A fee is therefore an ordinary dual-signed
transaction (payer → administrator) that appears in every statement and in
`verify`; there is no hidden arithmetic.

## Backups

`ccl backup` uses the SQLite online-backup API, so it is safe while the
program is running. A cron line for two drives:

    17 * * * *  CCL_DB=/var/lib/ccl/ledger.db ccl backup --to /media/BACKUP1 --to /media/BACKUP2

`ccl --db /media/BACKUP1/ledger-xxxx-latest.db verify` checks a backup on
any machine with the software installed — no site key needed.

## Restore to new hardware

Copy the latest backup to the new machine and point `CCL_DB` at it. The site
identity and every member device stay valid because nothing is derived from
hardware.

## Multi-site (deferred)

Every record carries `site_id`. Merging two sites' ledgers is not implemented;
the field exists so it can be without a schema change.

## YubiKey path

`YubiKeySigner` uses PIV slot 9c via `yubikey-manager`. It is written to the
documented API but has not been exercised against real hardware in this
build; test it before enrolling members on tokens. The site key can also be a
YubiKey: `ccl --site-key yubikey init ...`.

## Status / open questions (from DESIGN.md §8)

- Credit-limit policy: fixed at enrollment, changed by `member-set --limit`.
- Disputes: `ccl reverse` creates a new signed entry in the opposite direction;
  it still needs both parties. Policy for a refusing party is not implemented.
- Listing expiry: default 60 days (`listing_days` setting), `--days` per listing.
- License: GPL-3.0-or-later for the code, CC BY-SA 4.0 for the documentation.
- Packaging: `pip install` for now; `.deb` / PyInstaller later.

## Known limitations

ccl 0.1.0 is a first release. It works and has a test suite, but read these
limits before using it for a real community:

- **The YubiKey / hardware-token path is untested on real hardware.** It is
  written against the documented API and the Signer abstraction, but no
  physical token has been used with it. The encrypted USB-stick path is the
  tested one.
- **Multi-site merging is not implemented.** Every record carries a `site_id`
  so separate communities could merge or trade later, but the merge itself
  does not exist. Run one site per ledger.
- **No independent security audit.** The cryptography is standard (ECDSA
  P-256, SHA-256, scrypt, AES-GCM), but no outside party has reviewed the
  code. Keep regular backups and run `ccl verify` often.

## No support

ccl is released as is. The author does not provide support, answer
questions, review pull requests, or take feature requests. The manual covers
installation and use. If you want to improve ccl, fork it and maintain your
own version; that is exactly what the GPL is for.

## License

The ccl software is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version. See [LICENSE](LICENSE).

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. Communities using it to record balances do so at
their own risk.

The user manual (MANUAL.md) and design document (DESIGN.md) are licensed
under the Creative Commons Attribution-ShareAlike 4.0 International License
(CC BY-SA 4.0). See [LICENSES/CC-BY-SA-4.0.txt](LICENSES/CC-BY-SA-4.0.txt).
You may copy, translate, and adapt them, provided you credit the original
and share your version under the same license.

Copyright (C) 2026 Scotty Wimberley
