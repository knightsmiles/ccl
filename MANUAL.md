# Community Credit Ledger — User Manual

Version 0.1 · September 2026

> Copyright (C) 2026 Scotty Wimberley. This document is licensed under the
> [Creative Commons Attribution-ShareAlike 4.0 International License](LICENSES/CC-BY-SA-4.0.txt)
> (CC BY-SA 4.0). You are free to copy, share, translate, and adapt it, as
> long as you give credit and release your version under the same license.
> The ccl software itself is licensed separately under the GNU GPL version 3
> or later.

This manual is for the person who runs the community computer (the
**administrator**) and, in the last section, for ordinary **members**. It
assumes you have never used Linux and don't want to become an expert. Every
command you need is written out in full. Where you see a word in
`this kind of type`, that is something you type exactly as shown.

---

## Part 1 — What this is

### The idea in one paragraph

The ledger is a shared record of who has done what for whom, kept on one
computer that never connects to the internet. Nobody issues money. Everyone
starts at zero. When Bob wires Alice's barn and they agree it is worth 48
credits, Bob's balance goes up by 48 and Alice's goes down by 48. Alice is not
in debt to Bob; she is in debt to the community, and she clears it by doing
something for anyone else. Add up everybody's balance and you always get zero.

### What the software does

- Keeps the record of every transaction.
- Makes sure a transaction can only be recorded if **both** people were
  present and approved it with their own USB stick and PIN.
- Makes it impossible to secretly change or delete an old entry without it
  being detectable by anyone who checks.
- Gives every member a copy of their own history on their stick.
- Keeps a noticeboard of offers ("I have a tractor for hire") and wants ("I
  need a roof fixed") so people can find each other.
- Makes backups.

### What the software does not do

- It does not connect to anything. No internet, no phone app, no website.
- It does not decide prices. Two people agree a number; the software writes
  it down.
- It does not stop the administrator from lying — but it makes any lie
  provable, because members hold signed copies and anyone can run a check.

### The pieces

| Piece | What it is |
|---|---|
| The **community computer** | An ordinary PC or Raspberry Pi with the software on it. Lives somewhere members can get to. |
| The **ledger file** | One file on that computer (`ledger.db`) that holds everything. |
| The **administrator stick** | A USB stick holding the *site key*. This is the key that admits new members. Keep it like you would keep the keys to the building. |
| **Member sticks** | Each member has one or (better) two cheap USB sticks. Each holds their private key, locked with a PIN. |
| **Backup drives** | Two USB drives or external disks the ledger is copied to. |
| **Hardware tokens** (optional) | YubiKey-type devices for members who want extra security. Same job as a stick. |

### Words you will see

- **Credit** — the unit of account. Written with two decimals, e.g. `12.50`.
- **Balance** — a member's running total. Negative is normal and expected;
  it means they have received more than they've given so far.
- **Credit limit** — how far negative a member is allowed to go. Set by you.
- **PIN** — a password (at least 4 characters) that unlocks a stick. Only
  the member knows it.
- **Site** — this community's ledger. Every stick is stamped with the site
  identity so a stick from another community can't be used here.
- **Listing** — an offer or a want on the noticeboard.
- **Verify** — a check that walks the whole ledger and reports any tampering.

---

## Part 2 — Setting up (done once)

If you bought a preinstalled bundle, skip to **2.3**.

### 2.1 Opening the Terminal

All commands are typed into a program called **Terminal**. On Ubuntu, press
`Ctrl` + `Alt` + `T`, or click the grid of dots at the bottom-left and type
"terminal". A window with a blinking cursor opens. You type a command, press
`Enter`, and the computer answers underneath.

Three things worth knowing:

- Nothing happens until you press `Enter`.
- If you make a typo, the computer says so and nothing is changed. Just try
  again.
- When you are asked for a PIN, **the letters do not appear as you type**.
  That is deliberate. Type the PIN and press `Enter`.

### 2.2 Installing the software

Plug the computer into the internet **only for this step**, then type these
lines one at a time, pressing `Enter` after each. The first will ask for your
computer password.

    sudo apt install python3-pip
    pip install --break-system-packages https://github.com/knightsmiles/ccl/archive/refs/tags/v0.1.0.tar.gz

That downloads and installs the software in one step. If you were given the
software as a file instead (on a USB stick, say), use this second line in
place of the one above:

    pip install --break-system-packages /path/to/ccl-0.1.0.tar.gz

(Replace `/path/to/` with wherever the file is — for example
`~/Downloads/ccl-0.1.0.tar.gz`.)

Check it worked:

    ccl --version

It should reply `ccl 0.1.0`. You can now unplug the internet for good.

### 2.3 Telling the software where things are

The software needs to know two things every time it runs: where the ledger
file is, and where the administrator stick is. Rather than typing them each
time, set them once.

First, decide on a name for the administrator stick. Plug in an **empty** USB
stick, open the file manager, right-click the stick, choose *Rename* (or
*Format*), and call it `ADMIN`. Do the same for backup drives, calling them
`BACKUP1` and `BACKUP2`. Named sticks always appear at the same place, which
is what makes the rest of this manual work.

Now type (replacing `scotty` with your own login name — it's shown at the
start of every Terminal line, before the `@`):

    mkdir -p ~/ledger
    echo 'export CCL_DB=$HOME/ledger/ledger.db' >> ~/.bashrc
    echo 'export CCL_SITE_KEY=/media/scotty/ADMIN' >> ~/.bashrc
    source ~/.bashrc

That's it. From now on every command knows where to look.

> **Where do sticks appear?** On Ubuntu a stick named `ALICE1` shows up at
> `/media/scotty/ALICE1` (with your login name instead of `scotty`). On
> Raspberry Pi OS it is the same. If you are ever unsure, type
> `ls /media/$USER` and the computer lists every stick currently plugged in.

### 2.4 Creating the site

With the `ADMIN` stick plugged in:

    ccl init --admin-name "Your Name" --description "Riverside Community Ledger"

You will be asked to choose a PIN for the site key and to repeat it. **Write
this PIN down and keep it somewhere safe, separate from the stick.** If you
lose it, no new members can ever be added.

The computer prints a *site ID* and a *site public key*. You don't need to
copy them; they are stored in the ledger.

You are now member **#1**, the administrator. Your "stick" for signing
purposes is the `ADMIN` stick itself.

### 2.5 Setting a fee (optional)

If the community has agreed that a small amount goes to the administrator on
each transaction to pay for the computer, sticks and your time:

    ccl fee 0.25

sets it to a quarter credit. `ccl fee 0` switches it off. `ccl fee` alone
shows the current value. Fees show up in every statement as an ordinary
payment to member #1 — nothing is hidden.

### 2.6 Categories

The noticeboard sorts listings into categories. The starting list is:
trades, transport, tools, food, livestock, housing, clothing, services,
other. To see or change it:

    ccl category
    ccl category --add fishing
    ccl category --remove clothing

Keep the list short — a dozen at most — so people can find things.

### 2.7 First backup

Plug in `BACKUP1` and `BACKUP2`, then:

    ccl backup --to /media/scotty/BACKUP1 --to /media/scotty/BACKUP2

See Part 5 for making this automatic.

---

## Part 3 — Enrolling members

### 3.1 What you need

- The member, in person.
- Two empty USB sticks. Name them in the file manager first, e.g. `ALICE1`
  and `ALICE2`. Any name works but member-name-plus-number is easy to keep
  track of. (Cheap 4 GB sticks are fine; the files are tiny.)
- The `ADMIN` stick plugged in.
- An agreed credit limit — how far negative they may go. A new member might
  start at 100 or 200; you can raise it later.

### 3.2 The command

    ccl enroll --name "Alice Nguyen" --contact "Farm Rd, ask at the gate" --limit 200 --stick /media/scotty/ALICE1 --stick /media/scotty/ALICE2

Then:

1. You are asked for the **site key PIN** (yours).
2. For each stick, the **member** is asked to choose a PIN and repeat it.
   Turn the keyboard toward them and look away. Four digits is the minimum;
   six is better. They must remember it — you cannot recover it.

The computer prints the member's number (`#2`, `#3`, ...) and confirms each
stick. Both sticks now work for that member. Tell them to keep one at home.

The `--contact` text is what other members see on the noticeboard next to
this person's listings. It can be anything — a road, a phone number, "Sundays
at the market".

### 3.3 Checking a stick

Plug it in and type:

    ccl whoami /media/scotty/ALICE1

The computer shows the member's name, number and balance. (No PIN is needed
for this — looking is free, only signing needs the PIN.) If a stick is from
another community or has been revoked, it says so.

### 3.4 Members with a hardware token

If a member brings a YubiKey (or similar), plug it in and add `--yubikey` in
place of a `--stick`:

    ccl enroll --name "Bob Ross" --contact "electrician" --limit 500 --yubikey

The token will ask for its own PIN on its own terms. Wherever this manual
says `/media/scotty/SOMESTICK` for that member, type the word `yubikey`
instead.

*Note: this path has been written to the manufacturer's documentation but
not yet tested on real hardware. Try it with a spare token before relying on
it.*

### 3.5 Adding a stick to an existing member

    ccl device add 2 --stick /media/scotty/ALICE3

(`2` is the member's number.) Same PIN routine as enrollment.

### 3.6 Lost or stolen stick

A stick is useless without its PIN, so there is no panic — but revoke it the
same day. With the member present:

    ccl device revoke --member 2

The computer lists the member's devices; type the number of the lost one and
press `Enter`. Everything the stick signed in the past stays valid. Then add
a replacement (3.5). If they had only one stick and it's lost, you enroll a
new stick with `device add` — their balance and history are in the ledger,
not on the stick.

### 3.7 Changing a limit, suspending or closing a member

    ccl member-set 2 --limit 400
    ccl member-set 2 --status suspended
    ccl member-set 2 --status active
    ccl member-set 2 --status closed

A suspended or closed member cannot post or transact. Their history stays.
A member should get back to zero before closing, but the software does not
enforce this — that is a community rule, not a software rule.

### 3.8 Seeing everyone

    ccl members

Lists every member with balance, limit and status.

---

## Part 4 — Day to day

### 4.1 Recording a transaction

This is the heart of it. Both people must be at the computer.

1. Both plug in a stick. Say Alice's is `ALICE1` and Bob's is `BOB1`.
2. Agree on three things out loud: who is paying, how much, and a short
   description.
3. Type:

       ccl transact --payer /media/scotty/ALICE1 --payee /media/scotty/BOB1 --amount 48 --description "4 hours barn wiring"

4. The screen shows a summary like:

       Alice Nguyen (#2) pays Bob Ross (#3) 48.00 credits for: 4 hours barn wiring
       + fee of 0.25 credits to the administrator
       Confirm? [y/N]

   Both look at it. If it's right, type `y` and `Enter`. If not, type `n`
   and start over.
5. Alice is asked for her PIN, then Bob for his. (If a fee is set, you are
   asked for the site key PIN too.)
6. The computer prints the entry numbers and writes a receipt to both sticks.
7. Both unplug.

Nothing about either member stays on the computer in unlocked form.

**Mixed deals.** Alice gives Bob 20 kg of apples and Bob does 4 hours of
wiring. That is two transactions: Alice pays Bob 48 for wiring, Bob pays
Alice 12 for apples. Record them one after the other. The difference (36)
stays on the ledger — that's the point.

**Linking to a listing.** If the deal came from the noticeboard, add
`--listing 7` (the listing number) so the record shows it, and
`--close-listing` to take it down at the same time.

**If it fails.** The most common reasons, and what the screen will say:

- *would exceed credit limit* — the payer is at their limit. Either raise it
  (3.7) or they do some work first.
- *wrong PIN or corrupted key file* — try again; PINs are case-sensitive.
- *does not contain ccl/key.json — is the stick mounted?* — the stick isn't
  plugged in, or the name is wrong. `ls /media/$USER` shows what's there.
- *this device has been revoked* — they're using the old stick.
- *key is not enrolled at this site* — the stick is from somewhere else.

### 4.2 Balances and statements

    ccl balance 2
    ccl statement 2

The statement is a bank-style list: date, amount in or out, who with,
description, running balance. To print it, `ccl statement 2 | lp` sends it
to the default printer.

Members can also look at their own stick (Part 6).

### 4.3 The noticeboard

**Posting.** A member plugs in and types (or you type for them):

    ccl listing post --device /media/scotty/BOB1 --type offer --category trades --title "House wiring, any size job" --unit hour --asking 12 --description "Evenings and weekends. Bring your own cable if you have it."

- `--type` is `offer` or `want`.
- `--category` must be one from `ccl category`.
- `--unit` is what the price is per: `hour`, `each`, `day`, `kg`, `crate`...
  anything short.
- `--asking` is the price per unit. Leave it out and the listing shows
  "negotiable".
- Add `--no-trades` if they want credits only and won't swap for goods.
- Listings expire after 60 days unless you give `--days 14` etc. Expired
  listings vanish from searches automatically; nothing is deleted.

The moment a listing is posted, the computer shows any **matching listings
of the opposite kind** — Bob posts a wiring offer and sees at once that
Alice wants her barn wired.

**Searching.**

    ccl listing search wiring
    ccl listing search --category transport
    ccl listing search tractor --type offer

Searching matches whole words and the beginnings of words, so `pick` finds
"pickup".

**Reading one in full, closing one.**

    ccl listing show 7
    ccl listing close 7

**The weekly sheet.** Every week, print the new listings and pin them up:

    ccl listing report | lp

(or `ccl listing report --days 14`). The bottom line of the sheet is the
current *tip hash* — a long string of letters and numbers that stands for
the entire ledger at that moment. Pin it up too. If anyone ever wants to
prove the ledger hasn't been rewritten, that number is how (see 5.3).

### 4.4 Reversing a mistake

Nothing is ever edited or deleted. If a transaction was wrong, a second
transaction goes the other way. Both people must be present, just as they
were the first time:

    ccl reverse 14 --payer /media/scotty/BOB1 --payee /media/scotty/ALICE1 --reason "amount entered as 480 instead of 48"

Here `14` is the number of the wrong entry, `--payer` is the person who
*received* it originally (they are now paying it back), and `--payee` is the
person who paid. The statement will show both entries.

What if one party refuses? The software has no answer for that; it is a
matter for the community, the same as any dispute between neighbours. Write
down the agreed rule and stick to it.

---

## Part 5 — Looking after the ledger

### 5.1 Backups

Every backup makes a dated copy of the whole ledger, plus a copy called
`...-latest.db`, on each drive you name.

Do it by hand any time:

    ccl backup --to /media/scotty/BACKUP1 --to /media/scotty/BACKUP2

To make it automatic every hour, type `crontab -e` once, choose the editor
`nano` if asked, add this single line at the bottom (all on one line, with
your login name in place of `scotty`):

    17 * * * * CCL_DB=/home/scotty/ledger/ledger.db /home/scotty/.local/bin/ccl backup --to /media/scotty/BACKUP1 --to /media/scotty/BACKUP2

then press `Ctrl`+`O`, `Enter`, `Ctrl`+`X` to save and leave. Leave both
backup drives plugged in. Once a month, take one of them home and swap it
for a third drive — fire, theft and floods happen to computers too.

If `ccl` is not found by cron, type `which ccl` in the Terminal and use the
path it prints in place of `/home/scotty/.local/bin/ccl`.

### 5.2 Checking the ledger

    ccl verify

This re-checks every entry from the very first: that each links to the one
before, that both signatures are genuine, that every signature came from a
stick that really belonged to that member, and that all balances add up to
zero. It ends with either

    OK — chain intact, all signatures valid, balances sum to zero.

or a list of problems. Run it every week. Run it after any crash, power cut
or anything odd. A problem means either the file is damaged (restore from
backup, 5.4) or somebody changed something they shouldn't have.

### 5.3 Letting anyone check

This is what makes the system trustworthy. Any member may take a backup
drive (or a copy of the `...-latest.db` file) to any computer with the
software installed and run:

    ccl --db /media/wherever/ledger-xxxxxxxx-latest.db verify

No PIN and no administrator stick are needed. If the tip hash it prints
matches the one pinned on the wall the week the copy was made, the copy is
the real ledger, and the administrator has not rewritten it since. Encourage
people to do this. The more often it's done, the less anyone has to take on
faith.

### 5.4 Restoring after a disaster

If the computer dies, the ledger is *not* lost — it's on the backup drives,
and every member's own history is on their sticks.

On a new or repaired computer: install the software (2.2), do the setup in
2.3, then copy the newest `...-latest.db` from a backup drive to
`~/ledger/ledger.db`:

    cp /media/scotty/BACKUP1/ledger-*-latest.db ~/ledger/ledger.db
    ccl verify

Every member's stick still works. Nothing about the ledger is tied to the
old machine.

### 5.5 Moving to a bigger computer

Same as 5.4. Copy the file, install the software, done.

### 5.6 The administrator stick

Everything that admits people to the community depends on the `ADMIN` stick
and its PIN. Suggested practice:

- Make a second admin stick at set-up time by simply copying the whole
  `ccl` folder from `ADMIN` to another named stick with the file manager.
  Both work. Keep the copy at home.
- Never leave `ADMIN` plugged into the community computer unattended. It is
  only needed for enrolling, adding devices, and (if a fee is set) at
  transaction time.
- If you hand the administrator role to someone else, hand over the stick
  and the PIN. The site identity goes with the ledger, not with you.

### 5.7 Things that show what's going on

    ccl site        site ID, number of members, number of entries, tip hash, fee
    ccl members     everyone, with balances
    ccl device list 2   a member's sticks and tokens
    ccl stick-info /media/scotty/ALICE1   the certificate on a stick, and whether it's valid here

---

## Part 6 — For members (copy this page and hand it out)

**Your stick** holds the key that lets you approve transactions. It is
locked with your PIN. Without the PIN, the stick is useless to anyone — but
report a lost stick to the administrator anyway, and keep your second stick
at home.

**Your PIN** is yours alone. The administrator cannot see it or recover it.
If you forget it, you'll need a new stick (your balance and history are
safe; they live in the ledger, not on the stick).

**Your balance** starts at zero. Doing work or supplying goods for someone
makes it go up. Receiving makes it go down. Going negative is normal — it
just means the community has done more for you than you've done for it so
far. There is a limit on how far negative you can go; ask the administrator
what yours is.

**Prices are between you and the other person.** Nobody sets a rate for an
hour of anything. Agree the number before you go to the computer.

**To record a deal**, both of you go to the computer with your sticks. The
screen will show who pays whom and how much. Read it. Type your PIN only if
it's right. Both of you unplug afterwards.

**To find work or things**, look at the sheet on the wall, or ask at the
computer to search — for example "anyone want firewood?" or "anyone got a
trailer for hire?". To post your own offer or want, tell the administrator
what you have or need, the price per hour/day/item (or "negotiable"), and
how to reach you.

**Your stick keeps your receipts.** Inside it there's a folder called `ccl`
with a file `history.jsonl` — a signed copy of every transaction you've been
part of, refreshed each time you visit. It is proof, independent of the
administrator, of what you've given and received.

**You can check the whole ledger yourself.** Ask the administrator for a
copy of the backup file, take it to any computer with the software, and run
the verify check. If the long number it prints matches the one pinned on
the wall, nothing has been tampered with. You don't need anyone's permission
or password to do this.

---

## Appendix A — Every command on one page

Global (before the command): `--db FILE` use a different ledger file;
`--site-key DIR` use a different administrator stick.

| Task | Command |
|---|---|
| Create the site | `ccl init --admin-name "NAME" --description "TEXT"` |
| Enroll | `ccl enroll --name "NAME" --contact "TEXT" --limit N --stick DIR [--stick DIR] [--yubikey]` |
| Who is this stick | `ccl whoami DIR` |
| Add a stick | `ccl device add MEMBER --stick DIR` |
| Revoke a stick | `ccl device revoke --member MEMBER` |
| List sticks | `ccl device list MEMBER` |
| List members | `ccl members` |
| Change limit/status | `ccl member-set MEMBER --limit N` / `--status active|suspended|closed` |
| Record a deal | `ccl transact --payer DIR --payee DIR --amount N --description "TEXT" [--listing ID] [--close-listing]` |
| Reverse a deal | `ccl reverse ID --payer DIR --payee DIR --reason "TEXT"` |
| Balance | `ccl balance MEMBER` |
| Statement | `ccl statement MEMBER` |
| Refresh a stick's receipts | `ccl history-refresh DIR` |
| Post a listing | `ccl listing post --device DIR --type offer|want --category C --title "T" [--unit U] [--asking N] [--description "D"] [--days N] [--no-trades]` |
| Search listings | `ccl listing search [WORDS] [--category C] [--type offer|want] [--all]` |
| Show / close a listing | `ccl listing show ID` / `ccl listing close ID` |
| Weekly sheet | `ccl listing report [--days N]` |
| Check everything | `ccl verify` |
| Back up | `ccl backup --to DIR --to DIR` |
| Fee | `ccl fee` / `ccl fee N` / `ccl fee 0` |
| Categories | `ccl category [--add NAME] [--remove NAME]` |
| Site info | `ccl site` |
| Stick certificate | `ccl stick-info DIR` |

`DIR` is where the stick appears, e.g. `/media/scotty/ALICE1`, or the word
`yubikey`. `MEMBER` and `ID` are numbers.

## Appendix B — When something goes wrong

| The screen says | What it means | What to do |
|---|---|---|
| `ccl: command not found` | Software not installed, or Terminal opened before set-up finished | Close Terminal, open it again. If still not found, redo 2.2. |
| `ledger.db is not an initialised ledger` | Wrong folder, or `init` never run | Check 2.3; run `ccl site`. |
| `does not contain ccl/key.json — is the stick mounted?` | Stick not plugged in or name mistyped | `ls /media/$USER` to see what's plugged in. |
| `wrong PIN or corrupted key file` | Mistyped PIN | Try again. If it never works, the member needs a new stick (3.5). |
| `key is not enrolled at this site` | Stick from another community, or never enrolled | Check with `ccl stick-info DIR`. |
| `this device has been revoked` | Old stick | Use the replacement. |
| `would exceed credit limit` | Payer is at the limit | Raise it (3.7) or they earn first. |
| `payer and payee are the same member` | Both sticks belong to one person | Plug in the right sticks. |
| `a fee is configured but no site signer` | Fee is on and ADMIN stick isn't in | Plug in ADMIN, or `ccl fee 0`. |
| `verify` lists PROBLEMS | File damaged or tampered | Restore from the newest backup that verifies clean (5.4). Keep the bad file for evidence. |
| `Permission denied` | Trying to write somewhere you're not allowed | Check the stick isn't write-protected (some have a switch). |

## Appendix C — Buying sticks

Any USB stick works. The software writes a few kilobytes. Suggestions:

- Buy the smallest capacity sold; they're the cheapest and last longest.
- Buy them in a batch and name them before the enrollment day.
- A key-ring loop on the stick stops them getting lost.
- Members who want more security can buy a YubiKey 5 or Nitrokey; the
  ledger treats it like a stick whose key can never be copied off it.
