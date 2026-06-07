<div align="center">

<h1>🛡️ MasterHttpRelayVPN GUI</h1>

<p><strong>A free, open-source VPN client with a graphical interface that bypasses internet censorship using Google Apps Script, Cloudflare Workers, or a VPS exit node as a relay.</strong></p>

<p>
  <img src="https://img.shields.io/badge/version-1.0.0-blue?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10%2B-yellow?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/GUI-PyQt6-purple?style=flat-square" alt="PyQt6">
  <img src="https://img.shields.io/badge/status-active-brightgreen?style=flat-square" alt="Status">
</p>

<p>
  <a href="#-quick-start-no-python-required">⚡ Quick Start (Windows EXE)</a> ·
  <a href="#-how-it-works">How It Works</a> ·
  <a href="#-deploy-your-relay">Deploy Your Relay</a> ·
  <a href="#-run-from-source">Run from Source</a> ·
  <a href="#-troubleshooting">Troubleshooting</a>
</p>

<blockquote>
<strong>For people in Iran, Russia, China, and every other country where the government blocks the free internet.</strong><br>
Access to information is a fundamental human right. This tool is built for you.
</blockquote>

</div>

---

## 📖 Table of Contents

- [What Is This?](#-what-is-this)
- [How It Works](#-how-it-works)
- [Features](#-features)
- [Quick Start — Windows EXE (No Python Required)](#-quick-start-no-python-required)
- [Deploy Your Relay](#-deploy-your-relay)
  - [Option A: Google Apps Script (Free)](#option-a-google-apps-script-free--recommended)
  - [Option B: Cloudflare Worker (Free)](#option-b-cloudflare-worker-free)
  - [Option C: Deno Deploy (Free)](#option-c-deno-deploy-free)
  - [Option D: VPS Exit Node](#option-d-vps-exit-node)
- [Run from Source (Developers)](#-run-from-source-developers)
- [Build an EXE Yourself](#-build-an-exe-yourself)
- [Required External Files](#-required-external-files)
- [Configuration Reference](#-configuration-reference)
- [Proxy Modes Explained](#-proxy-modes-explained)
- [Troubleshooting](#-troubleshooting)
- [FAQ](#-faq)
- [Credits & Core Engine](#-credits--core-engine)
- [Contact & Support](#-contact--support)
- [License](#-license)

---

## 🔍 What Is This?

**MasterHttpRelayVPN GUI** is a desktop application for Windows and Linux that routes your internet traffic through a relay server you control, bypassing Deep Packet Inspection (DPI) and SNI-based filtering used by government censorship systems.

It is a **graphical interface (GUI)** built on top of the [MasterHttpRelayVPN core engine](https://github.com/masterking32/MasterHttpRelayVPN/tree/python_testing) by [@masterking32](https://github.com/masterking32). The GUI makes the tool easy to use for anyone — no command line needed.

**Who is this for?**
- People in **Iran**, Russia, China, or any country with heavy internet filtering.
- Anyone whose ISP or workplace blocks websites using DPI or SNI inspection.
- Privacy-conscious users who want traffic tunneled through a relay they own.

---

## ⚙️ How It Works

The tool uses two techniques to bypass censorship:

### 1. MITM Proxy (Man-in-the-Middle — HTTP/HTTPS)
The application runs a local HTTPS proxy on your machine. It intercepts your browser's HTTPS requests, re-encrypts them, and forwards them through the relay. A locally-trusted certificate (auto-generated and auto-installed) is used so your browser sees a valid HTTPS connection.

### 2. SNI Spoofing / Domain Fronting
When connecting to the relay, the application uses **SNI spoofing** — it presents a trusted Google/Cloudflare domain in the TLS handshake's SNI field (which the DPI system sees) while the actual HTTPS request inside the tunnel goes to your relay. The DPI system sees only traffic to `google.com` or `cloudflare.com` and cannot identify or block it.

### Traffic Flow

```
Your Browser / App
       │
       ▼
[Local Proxy :8080]  ← MasterHttpRelayVPN GUI
       │  (MITM + SNI Spoof)
       ▼
Google / Cloudflare CDN  ← DPI sees only this trusted domain
       │  (HTTPS tunnel inside)
       ▼
Your Relay (Apps Script / Cloudflare Worker / VPS)
       │
       ▼
    The Free Internet 🌍
```

---

## ✨ Features

| Feature | Description |
|---|---|
| 🖥️ **Modern GUI** | Clean dark-themed PyQt6 interface with Dashboard, Config, Proxy Mode, Logs, and built-in Guide tabs |
| 🔌 **System Proxy Mode** | Automatically sets Windows/Linux system-wide HTTP/HTTPS proxy — works for all browsers |
| 🌐 **TUN Mode** | Full VPN mode — routes ALL traffic (not just browsers) through the tunnel using `tun2socks` |
| 📡 **LAN Sharing** | Share your VPN connection with other devices on your local network |
| 🚫 **Ad Blocker** | Built-in DNS-level ad and tracker blocking |
| 🧙 **First-Run Wizard** | Step-by-step setup guide on first launch |
| 📊 **Live Dashboard** | Real-time traffic monitor, uptime counter, animated connection status |
| 🔑 **Google IP Scanner** | Scans for the fastest available Google IP for your location |
| 📋 **Built-in Guide** | Full offline setup and troubleshooting guide inside the app |
| 📦 **No Python Needed** | Pre-built Windows EXE in Releases — just extract and run |
| 🔄 **HTTP/2 Support** | HTTP/2 relay transport for better performance and lower latency |

---

## ⚡ Quick Start (No Python Required)

This is the easiest way. You do **not** need Python, pip, or any developer tools.

### Step 1 — Download the Windows Build

Go to the [**Releases**](../../releases) page of this repository and download the latest `MasterHttpRelayVPN-Windows-v1.0.0.zip`.

### Step 2 — Get the Required Binary File

The release ZIP needs one external file placed in the `assets/bin/` folder:

**`tun2socks.exe`** — enables TUN Mode (full VPN for all apps).
- Download from: [heiher/hev-socks5-tunnel Releases](https://github.com/heiher/hev-socks5-tunnel/releases)
- Pick the file matching your CPU:
  - Most PCs (Intel/AMD): `hev-socks5-tunnel-windows-x86_64.zip`
  - ARM-based PC: `hev-socks5-tunnel-windows-arm64.zip`
- Extract it, rename the `.exe` file to `tun2socks.exe`, and place it in the `assets/bin/` folder inside the extracted ZIP.

> **Note:** If you only want **System Proxy mode** (works for browsers), TUN mode is optional and you can skip this step.

### Step 3 — Deploy Your Relay (Required, One-Time)

You need your own relay to connect through. See [Deploy Your Relay](#-deploy-your-relay) below. The free Google Apps Script option takes about 5 minutes and requires only a Google account.

### Step 4 — Launch & Configure

1. Extract the ZIP to any folder (e.g., `C:\MasterHttpRelayVPN\`).
2. Double-click `MasterHttpRelayVPN.exe`.
3. The **First-Run Wizard** opens — enter your relay URL and secret key.
4. Click **Connect** on the Dashboard.
5. ✅ Your traffic is now routed through your relay!

---

## 🚀 Deploy Your Relay

You must deploy one relay before using the app. All options below are **free**.

> ⚠️ **You need an unfiltered internet connection to deploy the relay once.** Use mobile data (if not filtered in your country), a friend's connection, or a free VPN trial for this one-time step. After your relay is deployed, you use *this app* to connect — no unfiltered connection needed again.

---

### Option A: Google Apps Script (Free) — Recommended

Google's infrastructure is extremely reliable and almost never blocked.

1. Open [https://script.google.com](https://script.google.com) and sign in with any Google account.
2. Click **New project** (top-left button).
3. You will see a code editor with some default code. **Select all of it and delete it.**
4. Open the file `engine/apps_script/Code.gs` from this repository. Copy its entire contents.
5. Paste it into the Google Apps Script editor.
6. Near the top of the file, find this line and **change the key to your own secret password:**
   ```javascript
   const AUTH_KEY = "CHANGE_ME_TO_A_STRONG_SECRET";
   ```
   Example: `const AUTH_KEY = "MyPrivateKey_xK9z!2026";`
   Write this key down — you will need it in the app.
7. Press `Ctrl+S` to save. Give the project any name you like.
8. Click the **Deploy** button (top-right) → **New deployment**.
9. Click the ⚙️ **gear icon** next to "Select type" → choose **Web app**.
10. Set these options:
    - **Description:** anything (e.g., "v1")
    - **Execute as:** Me
    - **Who has access:** Anyone
11. Click **Deploy**.
12. A popup asks for permissions. Click **Authorize access**, choose your Google account, and click **Allow**.
13. You will see a **Deployment URL** that looks like:
    `https://script.google.com/macros/s/AKfycb.../exec`
    **Copy this URL.**
14. Open MasterHttpRelayVPN, go to the **Config** tab:
    - Paste the URL into **Script URL**.
    - Enter your `AUTH_KEY` into **Auth Key**.
    - Click **Save**.
15. Go to **Dashboard** and click **Connect**. 🎉

---

### Option B: Cloudflare Worker (Free)

1. Sign up for a free account at [https://cloudflare.com](https://cloudflare.com).
2. In the dashboard, go to **Workers & Pages** → **Create application** → **Create Worker**.
3. Click **Edit code** on the next page. Delete all default code.
4. Open `engine/apps_script/cloudflare_worker.js` from this repository and paste its contents into the editor.
5. Find the `AUTH_KEY` line and change it to your own secret password.
6. Click **Save and Deploy**.
7. Copy the Worker URL shown (e.g., `https://my-relay.yourname.workers.dev`).
8. Enter this URL and your key in the app's **Config** tab.

---

### Option C: Deno Deploy (Free)

1. Sign up at [https://deno.com/deploy](https://deno.com/deploy) (free, no credit card).
2. Create a **New Project** → choose **Playground**.
3. Open `engine/apps_script/deno_deploy.ts` from this repository and paste it into the playground editor.
4. Set your `AUTH_KEY` in the code.
5. Click **Save & Deploy**.
6. Copy the deployment URL and enter it in the app's Config tab.

---

### Option D: VPS Exit Node

If you have your own server (VPS) outside the censored region:

1. SSH into your VPS.
2. Copy the file `engine/apps_script/setup_vps_exit_node.sh` to your VPS.
3. Run:
   ```bash
   bash setup_vps_exit_node.sh
   ```
4. The script installs and starts the exit node service. Follow the prompts for port and auth key.
5. Use `http://YOUR_VPS_IP:PORT` and your auth key in the app config.

---

## 🐍 Run from Source (Developers)

Run the app directly from Python source — useful for development or if you want to inspect the code.

### Prerequisites

- **Python 3.10 or newer** — [https://www.python.org/downloads/](https://www.python.org/downloads/)
  - Windows: during install, tick ✅ **"Add Python to PATH"**
- **Git** (optional) — [https://git-scm.com](https://git-scm.com)
- Unfiltered internet for the one-time dependency install

### Step 1 — Get the Code

Download and extract the ZIP from GitHub, or clone:
```bash
git clone https://github.com/Sparky2273/MasterHttpRelayVPN.git
cd MasterHttpRelayVPN
```

### Step 2 — Install Dependencies (one time only)

**Windows:**
```bat
install_deps.bat
```

**Linux / macOS:**
```bash
bash install_deps.sh
```

This downloads and installs all required packages (`PyQt6`, `cryptography`, `h2`, `brotli`, etc.) into a local `_vendor/` folder. After this step the app works completely **offline**.

### Step 3 — Run

```bash
python main_gui.py
```

The First-Run Wizard will open and guide you through configuration.

---

## 🔨 Build an EXE Yourself

Create a standalone Windows executable using PyInstaller — no Python installation needed to run it.

**Requirements:** Python 3.10+ and dependencies installed (run `install_deps.bat` first).

**Windows:**
```bat
build_windows.bat
```

**Linux:**
```bash
bash build_linux.sh
```

Output is in `dist\MasterHttpRelayVPN\`. Zip that folder — users just extract and double-click the `.exe`.

---

## 📁 Required External Files

These files are **not included** in the repository because they are platform-specific third-party binaries:

### `tun2socks` — for TUN Mode (Full VPN)

| Platform & CPU | Download Link | Rename to |
|---|---|---|
| Windows AMD64 (most PCs) | [hev-socks5-tunnel-windows-x86_64.zip](https://github.com/heiher/hev-socks5-tunnel/releases) | `tun2socks.exe` |
| Windows ARM64 | [hev-socks5-tunnel-windows-arm64.zip](https://github.com/heiher/hev-socks5-tunnel/releases) | `tun2socks.exe` |
| Linux x86_64 | [hev-socks5-tunnel-linux-x86_64.zip](https://github.com/heiher/hev-socks5-tunnel/releases) | `tun2socks` |
| Linux ARM64 | [hev-socks5-tunnel-linux-arm64.zip](https://github.com/heiher/hev-socks5-tunnel/releases) | `tun2socks` |

After downloading, rename and place in: `assets/bin/tun2socks.exe` (Windows) or `assets/bin/tun2socks` (Linux).

> TUN mode is **optional** — System Proxy mode works for browsers and most apps without it.

---

## ⚙️ Configuration Reference

Config is stored in `config.json`, edited from the **Config** tab in the app.

| Key | Description | Example |
|---|---|---|
| `script_url` | Full URL of your relay deployment | `https://script.google.com/macros/s/ABC.../exec` |
| `auth_key` | The secret key you set in your relay | `MySecretKey123` |
| `proxy_host` | Local proxy host | `127.0.0.1` |
| `proxy_port` | Local proxy port | `8080` |
| `google_ip` | Specific Google IP for SNI fronting (optional) | `142.250.185.46` |
| `adblock_enabled` | Enable built-in ad blocker | `true` / `false` |
| `lan_sharing` | Share proxy with LAN devices | `true` / `false` |

See `engine/config.example.json` for a full example.

---

## 🔀 Proxy Modes Explained

### System Proxy Mode (Default — Recommended)
- Sets the OS-wide HTTP/HTTPS proxy to `127.0.0.1:8080`.
- Works for all browsers and most desktop apps automatically.
- **No admin rights required.**

### TUN Mode (Full VPN)
- Creates a virtual network adapter that routes **all** traffic — including apps that ignore system proxy settings (games, system services, etc.).
- Requires the `tun2socks` binary (see above).
- **Requires Administrator (Windows) or root (Linux).** The app will prompt for this.

You can enable/disable both modes from the **Dashboard** and **Proxy Mode** tabs.

---

## 🔧 Troubleshooting

**"Missing Dependencies" on launch**
→ Run `install_deps.bat` (Windows) or `bash install_deps.sh` (Linux/macOS).

**"Connection failed" / cannot connect**
→ Check your relay URL and auth key in the Config tab are exactly correct.
→ Make sure your Apps Script deployment has "Who has access: Anyone".
→ Try the Google IP Scanner in the Advanced tab.

**Browser still shows blocked sites**
→ Make sure System Proxy is ON (green toggle on Dashboard).
→ If using Firefox: Settings → Network Settings → Manual proxy → `127.0.0.1`, port `8080`.

**Certificate error in browser**
→ Go to the Advanced tab → click **Install Certificate** → approve the Windows prompt → restart your browser.

**TUN Mode not working**
→ Make sure `tun2socks.exe` is in `assets/bin/`.
→ Run the app as Administrator.
→ Make sure System Proxy Mode is also ON.

**App crashes or freezes**
→ Delete `config.json` and re-run the wizard.
→ Check the `logs/` folder for crash details and open a GitHub Issue.

---

## ❓ FAQ

**Q: Is this free?**
A: Yes, 100% free and open source, forever.

**Q: Do I need a paid server?**
A: No. The Google Apps Script option is completely free and requires only a Google account.

**Q: Is my traffic private?**
A: Traffic between you and your relay is encrypted by HTTPS/TLS. Your relay is under your control — no third party sees your data.

**Q: Will it slow down my internet?**
A: There is a small overhead from the extra relay hop. For normal browsing it is fast enough. Use the Google IP Scanner to optimize performance.

**Q: Can I share this with others?**
A: Yes! Please do. Share the GitHub link or the Windows ZIP from the Releases page.

**Q: What if the relay gets blocked?**
A: Switch relay types (e.g., from Apps Script to Cloudflare Worker), or deploy a new relay with a different URL.

---

## 🔧 Related Tools

- [V2RayConverter](https://github.com/Sparky2273/V2RayConverter) — Convert V2Ray/Xray
  configs between URI and JSON format

---

## 🙏 Credits & Core Engine

This GUI is built on top of the **MasterHttpRelayVPN** core proxy engine by [@masterking32](https://github.com/masterking32).

- **Core engine:** [github.com/masterking32/MasterHttpRelayVPN](https://github.com/masterking32/MasterHttpRelayVPN/tree/python_testing)

The GUI layer (this repository) adds:
- PyQt6 desktop interface with dark theme and multiple tabs
- System proxy management across Windows, Linux, and macOS
- TUN adapter with split-tunnelling and routing loop prevention
- First-Run Wizard and Config Manager
- Real-time traffic monitoring dashboard
- Crash logger, log bridge, and log viewer
- Windows and Linux PyInstaller build scripts

---

## 📬 Contact & Support

- **Telegram:** [@Sparky2273](https://t.me/Sparky2273)
- **Email:** mhashemi6699@gmail.com
- **Bug Reports & Feature Requests:** [Open a GitHub Issue](../../issues)

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for full details.

You are free to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of this software.

---

<div align="center">

**Made with ❤️ for internet freedom.**

*No one should be denied access to information.*

</div>
