# Investment App — getting started

A personal portfolio and budget dashboard that runs on your own computer. Nothing is uploaded anywhere: your broker exports, your ledger and your price key stay in this folder. The only thing it talks to on the internet is a free price feed.

**Download:** [investment-app.zip](https://github.com/eric4burns/investment-app-share/archive/refs/heads/main.zip) (about 4 MB). Do not open it from inside an email — save it, then follow the steps below.

**The whole thing in three lines:** unzip → double-click **Investment App.command** (Mac) or **Investment App.bat** (Windows) → on the first screen click **Load sample data** to see it working, or drop in your own exports. Nothing to install.

## 1. Start it

Unzip the archive first, so you have a folder called **investment-app**
(from the download link above it is called **investment-app-share-main**;
the name does not matter):

- **Mac:** double-click the zip (Safari has usually done it already).
- **Windows:** right-click the zip → **Extract All…** → **Extract**. Just
  double-clicking a zip on Windows only *looks* inside it, and nothing in
  there will run.

Then open the folder and:

- **Mac:** double-click **Investment App.command**.
- **Windows:** double-click **Investment App.bat**.

Nothing to install. If Python is not on the computer, the launcher fetches a
private copy for the app on its own — one time, about a minute, no admin
password — and starts. The app opens in your browser at
http://127.0.0.1:8737/. Leave the launcher window open while you use it.

### If the Mac says it cannot be opened

A file that arrived by AirDrop, mail or a download is held back by macOS the
first time. Any one of these gets past it, and it only happens once:

1. **macOS 15 or newer** ("Apple could not verify…"): click **Done**, open
   **System Settings → Privacy & Security**, scroll down to the line that says
   *"Investment App.command" was blocked*, click **Open Anyway**, then **Open**.
2. **Older macOS**: right-click the file, choose **Open**, then **Open** again.
3. **Always works:** open **Terminal** (Spotlight: type Terminal), type
   `bash ` with a space after it, drag **Investment App.command** into the
   Terminal window, press Return.

Once it has started one way, the block is cleared and double-click works
from then on.

### If Windows says it protected your PC

Click **More info**, then **Run anyway**. It only happens once. If a black
window opens and says the file has to stay inside the folder, the zip was
not extracted — see the Extract All step above.

## 2. See it working first — optional

The first screen is **Get started**. At the top is **Load sample data**: a
made-up year for one household — a brokerage account with a few real
tickers, a checking account with pay, rent and bills, and a credit card —
so every tab has something on it in about twenty seconds. Nothing in it is
anyone's real money and every account is called "Sample". When you are
ready for your own, click **Remove sample data** on the same screen and it
is gone.

## 3. Put in your accounts

The same screen walks through each account:

1. Export your activity from the broker, bank or card site (the exact clicks are written under each one — Fidelity, Robinhood, a bank's Web Connect file, credit cards, a pay stub).
2. Drop the file into the matching slot. It is imported on the spot and the screen tells you how many rows it read.
3. Click **Show it in the app** when the last file is in.
4. Click **fetch prices now**. No account or key is needed. (A free **Alpaca** key — email only, no money, no SSN — gives a better price feed; it is optional and the screen says how.)
5. Set your filing status and age for the tax figures — optional; it only changes the Taxes tab.

Re-dropping a file is always safe: nothing is ever counted twice. Add newer exports the same way later, from the **Import files / setup** link at the top of the Overview.

## What you get

What you own and how it has done against the index; a call on every name you hold, with the prices to act at; charts; a watchlist without limits; and the budget side — where the money goes, what bills you every month and what has gone up in price, and a floor on this year's tax.

## What is not in the box

Nobody's data but yours. The person who gave you this archive has their own ledger, their followed-author notes and their price key; none of that travels. Your copy starts empty and fills from your exports.

## On your phone — optional

It cannot run *on* a phone: the app is a small program that has to be
running on a computer. What you can do is open it from your phone while
that computer is on. The launcher prints a phone address when Tailscale is
set up. Tailscale is a free app that makes a private link between your own devices; the app is never opened to the Wi-Fi network as a whole, because it has no password.

1. Install Tailscale from https://tailscale.com/download on the computer that runs the app, and sign in.
2. Install Tailscale on your phone from the App Store or Play Store, and sign in **to the same account**.
3. Turn the Tailscale toggle on, on the phone.
4. Double-click the launcher again. It prints a line like `http://100.x.y.z:8737/`.
5. Open that address in the phone's browser. Add it to the home screen and it opens like an app.

The computer has to be awake and the launcher window open for the phone to reach it.

## Updating to a newer copy

Your own things — the `data` folder with your exports, `ledger.db` beside the
launcher, and `config.json` — are never in the archive, so a newer copy can go
straight over the old one. Nothing is re-imported and nothing is lost.

1. Close the app: close the black launcher window (Windows) or the Terminal
   window (Mac) that it runs in.
2. Download the archive again from the link at the top and extract it the
   same way as the first time. You now have a second folder.
3. Open that new folder, select everything in it (Ctrl+A on Windows, ⌘A on
   Mac), copy, then go into your OLD app folder and paste. When it asks,
   choose **Replace the files in the destination** (Windows) or **Replace**
   (Mac). Your `data` folder, `ledger.db` and `config.json` are not in the new
   copy, so they are untouched.
4. Double-click **Investment App.bat** / **Investment App.command** in the
   old folder as before, and reload the browser tab. If the app is open on
   your phone, reload there too.
5. Delete the second folder.

If you would rather move the other way, copy `data`, `ledger.db` and
`config.json` from the old folder into the new one, run from the new one and
delete the old. Either way the app picks up any new database columns on its
own the first time it starts.

## Keeping prices fresh

Prices update when you click **fetch prices now** on the Get started screen. To have that happen every night on a Mac, see **SETUP.md**, "Running it all the time".
