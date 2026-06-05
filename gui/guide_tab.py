"""
guide_tab.py — Built-in setup and troubleshooting guide.

Rendered in a QTextBrowser so it works completely offline.
"""

from __future__ import annotations

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

GUIDE_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {
    font-family: -apple-system, "Segoe UI", Ubuntu, sans-serif;
    font-size: 13px;
    background: #1E1E2E;
    color: #CDD6F4;
    margin: 20px 30px;
    line-height: 1.6;
  }
  h1 { color: #4CAF50; font-size: 22px; border-bottom: 2px solid #3D3D5C; padding-bottom: 8px; }
  h2 { color: #42A5F5; font-size: 17px; margin-top: 28px; }
  h3 { color: #FFA726; font-size: 14px; margin-top: 18px; }
  code, pre {
    background: #13131f;
    border: 1px solid #3D3D5C;
    border-radius: 4px;
    padding: 2px 6px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
    color: #66BB6A;
  }
  pre {
    display: block;
    padding: 10px 14px;
    overflow-x: auto;
    white-space: pre-wrap;
  }
  a { color: #42A5F5; }
  .step {
    background: #252535;
    border-left: 4px solid #4CAF50;
    border-radius: 0 6px 6px 0;
    padding: 10px 16px;
    margin: 10px 0;
  }
  .warn {
    background: rgba(255,167,38,0.1);
    border-left: 4px solid #FFA726;
    border-radius: 0 6px 6px 0;
    padding: 10px 16px;
    margin: 10px 0;
  }
  .info {
    background: rgba(66,165,245,0.1);
    border-left: 4px solid #42A5F5;
    border-radius: 0 6px 6px 0;
    padding: 10px 16px;
    margin: 10px 0;
  }
  ol li, ul li { margin: 6px 0; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; }
  th { background: #252535; padding: 8px 12px; text-align: left; }
  td { padding: 6px 12px; border-bottom: 1px solid #3D3D5C; }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 11px; font-weight: bold; margin-left: 6px;
  }
  .badge-green { background: #2E7D32; color: #fff; }
  .badge-blue  { background: #1565C0; color: #fff; }
  .badge-red   { background: #B71C1C; color: #fff; }
</style>
</head>
<body>

<h1>MasterHttpRelayVPN — Setup Guide</h1>

<h2>1. What Is This App?</h2>
<p>
  MasterHttpRelayVPN is a <strong>local privacy proxy</strong> that routes your
  browser and application traffic through a Google Apps Script relay, bypassing
  Deep Packet Inspection (DPI) censorship.
</p>

<h3>How It Works</h3>
<p>
  Your traffic takes this path:
</p>
<pre>Browser/App → Local proxy (127.0.0.1:8085)
           → Google front (SNI = www.google.com)
           → Apps Script relay (script.google.com)
           → Target website</pre>

<p>
  The trick is <strong>domain fronting</strong>: from the network's perspective,
  you are talking to <code>www.google.com</code> (which censors typically allow).
  Inside the encrypted TLS tunnel, the real destination is
  <code>script.google.com</code>, which then fetches the actual website.
</p>

<h3>Exit Node (for Cloudflare-protected sites)</h3>
<p>
  Some sites (claude.ai, chatgpt.com) block Google datacenter IPs. An optional
  <strong>exit node</strong> — a Cloudflare Worker or VPS — adds a second hop
  so traffic exits from a residential/Cloudflare IP:
</p>
<pre>… Apps Script relay → Cloudflare Worker → claude.ai, chatgpt.com, …</pre>

<div class="info">
  <strong>Privacy note:</strong> This tool is for bypassing censorship in restricted
  regions. It does NOT provide anonymity — the Apps Script relay can see your
  plaintext requests.
</div>

<h2>2. Step-by-Step First-Time Setup</h2>

<h3>Step A — Deploy the Google Apps Script Relay</h3>

<div class="step">
<ol>
  <li>Go to <a href="https://script.google.com">https://script.google.com</a> → click <strong>New project</strong></li>
  <li>Delete all default code in the editor</li>
  <li>In this app: go to <strong>Configuration tab</strong> → click
      <strong>"Copy Code.gs to Clipboard"</strong></li>
  <li>Paste the code into the Google Apps Script editor</li>
  <li>Find the line:<br>
      <code>const AUTH_KEY = "your-secret-password-here";</code><br>
      Replace <code>your-secret-password-here</code> with a strong random password
      (use the <strong>"Generate Random"</strong> button in the Config tab)</li>
  <li>Click <strong>Deploy</strong> → <strong>New deployment</strong></li>
  <li>Set type to <strong>Web app</strong></li>
  <li>Set "Execute as: <strong>Me</strong>" and "Who has access: <strong>Anyone</strong>"</li>
  <li>Click <strong>Deploy</strong> → authorize when prompted</li>
  <li>Copy the <strong>Deployment ID</strong> (it looks like
      <code>AKfycby...long string...</code>)</li>
  <li>Paste it into the <strong>Script ID</strong> field in the Configuration tab</li>
  <li>Also paste your AUTH_KEY into the <strong>Auth Key</strong> field</li>
  <li>Click <strong>Save Config</strong></li>
</ol>
</div>

<div class="warn">
  <strong>Important:</strong> Every time you change the code in Code.gs, you must
  create a <em>new deployment</em> (not redeploy the existing one). Apps Script
  deployments are immutable snapshots.
</div>

<h3>Step B — Deploy the Cloudflare Worker Exit Node (Optional)</h3>
<p>Required for: <code>claude.ai</code>, <code>chatgpt.com</code>, <code>openai.com</code>
and any site that blocks Google datacenter IPs.</p>

<div class="step">
<ol>
  <li>Go to <a href="https://dash.cloudflare.com">https://dash.cloudflare.com</a> →
      <strong>Workers &amp; Pages</strong> → <strong>Create</strong></li>
  <li>Choose <strong>Hello World</strong> → Deploy → Edit Code</li>
  <li>In this app: click <strong>"Copy cloudflare_worker.js to Clipboard"</strong></li>
  <li>Paste the code into the Cloudflare editor, replacing all existing code</li>
  <li>Find: <code>const PSK = "CHANGE_ME_TO_A_RANDOM_SECRET";</code><br>
      Set it to a strong random password (<em>different</em> from your AUTH_KEY)</li>
  <li>Click <strong>Deploy</strong></li>
  <li>Copy the worker URL, e.g. <code>https://your-worker.workers.dev</code></li>
  <li>In this app: Configuration tab → Exit Node section:<br>
      — Enable the toggle<br>
      — Paste the worker URL<br>
      — Paste the PSK<br>
      — Set mode to <strong>Selective</strong><br>
      — Ensure <code>claude.ai</code>, <code>chatgpt.com</code>, <code>openai.com</code>
        are in the hosts list</li>
  <li>Click <strong>Save Config</strong></li>
</ol>
</div>

<h3>Step C — Connect</h3>

<div class="step">
<ol>
  <li>Click the big green <strong>▶ Connect</strong> button on the Dashboard tab</li>
  <li>Watch the Live Logs tab — look for:
      <code>HTTP proxy listening on 127.0.0.1:8085</code></li>
  <li>Enable the <strong>System Proxy</strong> toggle on the Dashboard</li>
  <li>Open a browser and visit <a href="https://example.com">https://example.com</a>
      to confirm it works</li>
</ol>
</div>

<h3>Step D — Certificate Installation (for HTTPS)</h3>

<p>The proxy intercepts HTTPS connections using a locally-generated certificate
authority (MITM CA). You need to trust this CA so your browser accepts its
certificates.</p>

<div class="step">
<ol>
  <li>The app auto-installs the CA on first run on Windows and most Linux systems</li>
  <li>If your browser shows certificate warnings, go to:
      <strong>Tray icon</strong> → right-click → <strong>Install CA Certificate</strong></li>
  <li><strong>Firefox users only:</strong> Firefox has its own certificate store.
      Go to: <em>Settings → Privacy &amp; Security → Certificates →
      View Certificates → Authorities → Import</em><br>
      Import the file <code>ca/ca.crt</code> from the app folder</li>
</ol>
</div>

<h2>3. Proxy Mode Guide</h2>

<table>
  <tr>
    <th>Mode</th>
    <th>What it covers</th>
    <th>Requirements</th>
  </tr>
  <tr>
    <td><strong>System Proxy</strong> <span class="badge badge-green">Easy</span></td>
    <td>Browsers, most desktop apps that respect OS proxy settings</td>
    <td>No special privileges needed</td>
  </tr>
  <tr>
    <td><strong>TUN Mode</strong> <span class="badge badge-red">Advanced</span></td>
    <td>ALL applications — games, system apps, command-line tools, everything</td>
    <td>Requires administrator / root privileges</td>
  </tr>
  <tr>
    <td><strong>Both</strong> <span class="badge badge-blue">Recommended</span></td>
    <td>All apps via TUN; browsers also use System Proxy as fallback</td>
    <td>Requires administrator / root privileges</td>
  </tr>
</table>

<h3>When to use System Proxy only</h3>
<p>
  Best for everyday web browsing. Browsers (Chrome, Firefox, Edge) automatically
  use the OS proxy. Most desktop apps (Slack, Teams, VS Code) also respect it.
</p>

<h3>When to use TUN Mode</h3>
<p>
  Use TUN mode when you need to route ALL traffic — for example, a game launcher
  that doesn't respect proxy settings, or <code>curl</code>/<code>wget</code>
  from a terminal. Note: TUN mode requires the app to be run as
  administrator (Windows) or root/sudo (Linux).
</p>

<h2>4. Troubleshooting</h2>

<h3>Certificate Errors in Browser</h3>
<div class="step">
  <ol>
    <li>Make sure the proxy has run at least once (so <code>ca/ca.crt</code> exists)</li>
    <li>Install the CA: tray icon → <strong>Install CA Certificate</strong></li>
    <li>Completely close and reopen your browser (check Task Manager for background processes)</li>
    <li>Firefox: import <code>ca/ca.crt</code> manually via Settings → Privacy &amp; Security
        → Certificates → Authorities → Import</li>
  </ol>
</div>

<h3>"unauthorized" Error in Logs</h3>
<div class="step">
  The AUTH_KEY in your config does not match the one in Code.gs.<br>
  Fix: make sure both values are identical, then create a <em>new deployment</em>
  in Google Apps Script.
</div>

<h3>502 Bad JSON</h3>
<div class="step">
  <ol>
    <li>Wrong Deployment ID — check and update in Configuration tab</li>
    <li>Apps Script daily quota exhausted — add more script IDs under
        <em>Script IDs (Load Balancing)</em></li>
    <li>Deployment access not set to "Anyone" — redeploy with correct settings</li>
  </ol>
</div>

<h3>Connection Timeout / Slow Browsing</h3>
<div class="step">
  <ol>
    <li>Use the <strong>"Scan for Fastest IP"</strong> button in the Configuration tab</li>
    <li>Add multiple Apps Script deployment IDs for load balancing</li>
    <li>Ensure all dependencies are installed (run <code>install_deps.bat</code> / <code>.sh</code>)</li>
  </ol>
</div>

<h3>Page Looks Like Random Characters</h3>
<div class="step">
  The website sent a compressed response the proxy couldn't decode correctly.
  Fix: update the engine files and <em>redeploy</em> your Apps Script (create a new deployment).
</div>

<h3>TUN Mode: "Requires administrator rights"</h3>
<div class="step">
  Windows: right-click the app shortcut → <strong>Run as administrator</strong><br>
  Linux: run with <code>sudo</code> or grant <code>CAP_NET_ADMIN</code> to the binary
</div>

<h3>System Proxy set but browser doesn't use it</h3>
<div class="step">
  Firefox has its own proxy settings. Go to:<br>
  <em>Firefox Settings → General → Network Settings → Use system proxy settings</em>
</div>

<h3>Apps Script executions increasing very fast</h3>
<div class="step">
  You have too many ad-block lists enabled, or one of your configured sites
  generates many requests. Reduce the number of lists in the Ad Blocking section
  of the Configuration tab.
</div>

<h3>YouTube opens but video doesn't play</h3>
<div class="step">
  Enable <strong>youtube_via_relay</strong> in the Advanced tab, then restart the proxy.
</div>

<h2>5. Multiple Script IDs (Load Balancing)</h2>
<p>
  Google Apps Script has a daily execution quota. To avoid hitting it, deploy
  multiple copies of Code.gs under different Google accounts or projects, and
  add all their Deployment IDs to the
  <strong>Script IDs (Load Balancing)</strong> list in the Configuration tab.
  The engine will distribute traffic across all IDs automatically.
</p>

<h2>6. LAN Sharing</h2>
<p>
  Enable the <strong>LAN Sharing</strong> toggle to let other devices on your
  local network (phones, tablets, other computers) route their traffic through
  this proxy. On those devices, set the HTTP proxy to your computer's LAN IP
  and port 8085. They also need to install <code>ca/ca.crt</code> as a trusted CA.
</p>

</body>
</html>
"""


class GuideTab(QWidget):
    """
    The Built-in Setup Guide tab.

    Rendered as rich HTML in a QTextBrowser — fully offline, no internet required.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(GUIDE_HTML)
        self.browser.setStyleSheet(
            "QTextBrowser { background: #1E1E2E; border: none; }"
        )
        layout.addWidget(self.browser)
