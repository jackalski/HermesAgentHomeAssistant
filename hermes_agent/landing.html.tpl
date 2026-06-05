<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hermes Agent</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Noto Sans,sans-serif;margin:0;padding:16px;background:#0b0f14;color:#e6edf3}
    a,button{font:inherit}
    .card{max-width:1100px;margin:0 auto;background:#111827;border:1px solid #1f2937;border-radius:12px;padding:16px}
    .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
    .btn{background:#2563eb;color:white;border:0;border-radius:10px;padding:10px 14px;cursor:pointer;text-decoration:none;display:inline-block;font-size:14px}
    .btn.secondary{background:#334155}
    .btn.green{background:#059669}
    .btn.amber{background:#d97706}
    .btn:hover{filter:brightness(1.15)}
    .muted{color:#9ca3af;font-size:14px}
    .term{margin-top:14px;height:60vh;min-height:360px;border:1px solid #1f2937;border-radius:10px;overflow:hidden}
    iframe{width:100%;height:100%;border:0;background:black}
    code{background:#0b1220;padding:2px 6px;border-radius:6px;font-size:13px}
    .status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:12px 0}
    .status-item{padding:10px 14px;border-radius:10px;background:#0d1117;border:1px solid #1f2937;font-size:14px;display:flex;align-items:center;gap:8px}
    .status-item .icon{font-size:18px;flex-shrink:0}
    .banner{padding:12px 16px;border-radius:10px;margin:10px 0;font-size:14px;line-height:1.5}
    .banner.info{background:#1e3a5f;border:1px solid #2563eb}
    .banner.warn{background:#422006;border:1px solid #d97706}
    .banner.error{background:#3b0d0d;border:1px solid #dc2626}
    .banner.success{background:#052e16;border:1px solid #059669}
    .wizard{background:#0d1117;border:1px solid #1f2937;border-radius:10px;padding:14px;margin:12px 0}
    .wizard h3{margin:0 0 8px;font-size:15px}
    .wizard ol{margin:6px 0;padding-left:22px;font-size:14px;line-height:1.8}
    .wizard code{font-size:12px}
    details{margin:8px 0}
    details>summary{cursor:pointer;font-size:14px;color:#60a5fa;font-weight:500}
    details>summary:hover{text-decoration:underline}
    .hidden{display:none}
    .badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:12px;font-weight:600;vertical-align:middle}
    .badge.secure{background:#059669;color:#fff}
    .badge.insecure{background:#dc2626;color:#fff}
    .badge.mode{background:#2563eb;color:#fff}
  </style>
</head>
<body>
  <div class="card">
    <h2 style="margin:0 0 4px 0">Hermes Agent</h2>
    <div style="margin-bottom:10px">
      <span class="badge mode" id="modeBadge">__ACCESS_MODE__</span>
      <span class="badge" id="secureBadge"></span>
    </div>

    <!-- ==================== STATUS GRID ==================== -->
    <div class="status-grid">
      <div class="status-item" id="statusGateway">
        <span class="icon">⏳</span>
        <span>Gateway: checking&hellip;</span>
      </div>
      <div class="status-item" id="statusSecure">
        <span class="icon">🔒</span>
        <span>Secure context: checking&hellip;</span>
      </div>
      <div class="status-item" id="statusAccess">
        <span class="icon">📡</span>
        <span>Access mode: <b>__ACCESS_MODE__</b></span>
      </div>
      <div class="status-item" id="statusDisk">
        <span class="icon" id="diskIcon">💾</span>
        <span id="diskText">Disk: __DISK_USED__ / __DISK_TOTAL__ (__DISK_PCT__) — __DISK_AVAIL__ free</span>
      </div>
    </div>

    <!-- ==================== ACTION BUTTONS ==================== -->
    <div class="row" style="margin-bottom:6px">
      <a class="btn" id="gwbtn" href="__GATEWAY_PUBLIC_URL____GW_PUBLIC_URL_PATH__?token=__GATEWAY_TOKEN__" target="_blank" rel="noopener noreferrer">Open Gateway Web UI</a>
      <a class="btn secondary" href="./terminal/" target="_self">Open Terminal (full page)</a>
      <a class="btn green hidden" id="certBtn" href="" target="_blank" rel="noopener noreferrer">Download CA Certificate</a>
    </div>

    <!-- ==================== MIGRATION BANNER ==================== -->
    <div class="banner warn hidden" id="migrationBanner">
      <b>⚠️ Migration notice:</b> Hermes Agent requires HTTPS or localhost for Control UI.
      Plain HTTP LAN access no longer works. Switch <code>access_mode</code> to <b>lan_https</b>
      in add-on Configuration for one-click secure LAN access, then restart.
    </div>

    <!-- ==================== LOW DISK SPACE BANNER ==================== -->
    <div class="banner warn hidden" id="diskBanner">
      <b>⚠️ Low disk space:</b> <span id="diskBannerText"></span><br>
      Add-on updates and Docker builds may fail. Open the terminal and run <code>hermes-cleanup</code> to free space.
      For Docker-level cleanup, open a <strong>host root shell</strong> (Advanced SSH add-on with Protection Mode off, or type <code>login</code> at the HAOS console) and run <code>docker image prune -a</code>.
    </div>

    <!-- ==================== ERROR BANNER (populated by JS) ==================== -->
    <div class="banner error hidden" id="errorBanner"></div>

    <!-- ==================== SUCCESS BANNER ==================== -->
    <div class="banner success hidden" id="successBanner"></div>

    <!-- ==================== SETUP READINESS ==================== -->
    <details open>
      <summary>Setup status</summary>
      <div style="margin-top:8px;font-size:13px;color:#9ca3af;line-height:1.9">
        <div>API key synced: <b id="setupApiKey">__SETUP_API_KEY__</b></div>
        <div>Model configured: <b id="setupModel">__SETUP_MODEL__</b></div>
        <div>Home Assistant MCP: <b id="setupMcp">__SETUP_MCP__</b></div>
        <div>Assist API enabled: <b id="setupAssist">__SETUP_ASSIST__</b> <span class="muted">(optional — set <code>enable_openai_api</code> for voice/Assist)</span></div>
        <div id="setupGatewayHint" class="muted" style="margin-top:6px"></div>
      </div>
    </details>

    <!-- ==================== HOME ASSISTANT ==================== -->
    <details>
      <summary>Home Assistant</summary>
      <div style="margin-top:8px;font-size:13px;color:#9ca3af;line-height:1.9">
        <div>
          Install the <a href="https://github.com/jackalski/HermesAgentHomeAssistantIntegration" target="_blank" rel="noopener">Hermes Agent integration</a>
          (HACS) for chat card, voice mode, and tool services.
        </div>
        <div style="margin-top:6px">
          <b>Status sensors</b> (when <code>enable_ha_status_sensors</code> is ON):
          MQTT entities auto-appear if the <b>Mosquitto</b> add-on is installed; otherwise use
          <code>/status.json</code> on this Ingress page.
        </div>
        <div id="haStatusLive" class="muted" style="margin-top:8px">Loading live status…</div>
        <div class="muted" style="margin-top:6px;font-size:12px">
          Example MQTT entities: <code>binary_sensor.hermes_gateway_running</code>,
          <code>sensor.hermes_main_model</code>, <code>sensor.hermes_total_tokens</code>,
          <code>sensor.hermes_estimated_cost_usd</code>
        </div>
      </div>
    </details>

    <!-- ==================== ACCESS WIZARD ==================== -->
    <div class="wizard hidden" id="wizard">
      <h3>🧭 Quick-Start: Secure LAN Access</h3>
      <div id="wizardContent"></div>
    </div>

    <!-- ==================== TIPS ==================== -->
    <details>
      <summary>Tips &amp; token help</summary>
      <div class="muted" style="margin-top:6px">
        <b>First-time setup (3 fields):</b> set <code>setup_profile</code> to <b>home_assistant</b>, paste your <b>OpenRouter API key</b> (or another provider key) and optional <b>Home Assistant token</b>, then restart. The add-on bootstraps model, browser, timezone, and MCP automatically. Run <code>hermes onboard</code> only if you need OAuth or advanced tuning.
      </div>
      <div class="muted" style="margin-top:6px">
        The gateway UI opens in a separate tab to avoid websocket/proxy issues with Ingress.
        Set <code>gateway_public_url</code> in add-on options if the button URL is wrong.
      </div>
      <div class="muted" style="margin-top:6px">
        If the Gateway UI says <b>Unauthorized</b>, get your token from the terminal:<br>
        <code>jq -r '.gateway.auth.token' /config/.hermes/hermes.json</code><br>
        <small style="color:#6b7280">(If <code>hermes config show</code> redacts secrets, read the file directly instead.)</small>
      </div>
      <div class="muted" style="margin-top:6px">
        The add-on starts the gateway automatically. For manual debugging in the terminal use <code>hermes gateway run</code> (not <code>hermes-agent gateway run</code>). Pin a stable release via add-on option <code>hermes_agent_version_preset</code> if <code>latest</code> breaks.
      </div>
    </details>

    <!-- ==================== PROXY RECIPES ==================== -->
    <details>
      <summary>MCP setup (Home Assistant control)</summary>
      <div style="margin-top:8px;font-size:13px;color:#9ca3af;line-height:1.7">
        <p><b>MCP (Model Context Protocol)</b> lets Hermes Agent control Home Assistant entities, services, and automations directly.</p>

        <b>Automatic (recommended)</b>
        <ol style="margin:4px 0;padding-left:22px;line-height:1.8">
          <li>Create a <b>Long-Lived Access Token</b> in HA: click your profile avatar → scroll to <b>Long-Lived Access Tokens</b> → <b>Create Token</b></li>
          <li>Paste it into add-on option <code>homeassistant_token</code> in <b>Settings → Add-ons → Configuration</b></li>
          <li>Set <code>auto_configure_mcp</code> to <b>ON</b> in add-on Configuration</li>
          <li>Leave <code>hass_url</code> empty on HAOS (autodetected) and restart — MCP is configured automatically</li>
        </ol>

        <b>Manual (Hermes built-in MCP)</b>
        <p>Add to <code>/config/.hermes/config.yaml</code> under <code>mcp_servers</code>, then run <code>/reload-mcp</code> in Gateway chat:</p>
        <pre style="background:#0b1220;padding:8px;border-radius:6px;overflow-x:auto;font-size:12px">mcp_servers:
  HA:
    url: "http://supervisor/core/api/mcp"
    headers:
      Authorization: "Bearer YOUR_LONG_LIVED_TOKEN"</pre>

        <b>After upgrades</b> — if Hermes Agent has stale HA data:
        <p>Run <code>/reload-mcp</code> in Gateway chat, or restart the add-on.</p>

        <p><b>Tip:</b> The first MCP session needs a capable model (Gemini 3.1 Pro, Claude Sonnet 4, GPT-4.1). After setup, cheaper models work fine.</p>
      </div>
    </details>

    <details>
      <summary>Reverse-proxy recipes (NPM / Caddy / Traefik / Tailscale)</summary>
      <div style="margin-top:8px;font-size:13px;color:#9ca3af;line-height:1.7">

        <b>Nginx Proxy Manager (NPM)</b>
        <pre style="background:#0b1220;padding:8px;border-radius:6px;overflow-x:auto;font-size:12px">Scheme:   https
Forward:  &lt;HA-IP&gt;:18789
WS:       ON
SSL tab:  Request a new SSL certificate (Let's Encrypt or custom)</pre>

        <b>Caddy</b>
        <pre style="background:#0b1220;padding:8px;border-radius:6px;overflow-x:auto;font-size:12px">hermes.example.com {
    reverse_proxy &lt;HA-IP&gt;:18789
}</pre>

        <b>Traefik (docker labels)</b>
        <pre style="background:#0b1220;padding:8px;border-radius:6px;overflow-x:auto;font-size:12px">- "traefik.http.routers.hermes.rule=Host(`hermes.example.com`)"
- "traefik.http.routers.hermes.tls.certresolver=le"
- "traefik.http.services.hermes.loadbalancer.server.port=18789"</pre>

        <b>Cloudflare Tunnel (Cloudflared add-on)</b>
        <p>Keep <code>access_mode: lan_https</code>. Point the tunnel at the local HTTPS origin (self-signed cert — use <code>noTLSVerify</code>):</p>
        <pre style="background:#0b1220;padding:8px;border-radius:6px;overflow-x:auto;font-size:12px">ingress:
  - hostname: hermes.example.com
    service: https://127.0.0.1:18789
    originRequest:
      noTLSVerify: true</pre>
        <p>Set <code>gateway_public_url</code> to <code>https://hermes.example.com</code> and restart.</p>

        <b>Tailscale HTTPS</b>
        <pre style="background:#0b1220;padding:8px;border-radius:6px;overflow-x:auto;font-size:12px"># 1. Set access_mode to tailnet_https in add-on configuration
# 2. Enable Tailscale HTTPS in your Tailnet admin: DNS → HTTPS Certificates
# 3. On the HA host:  tailscale cert &lt;machine-name&gt;.ts.net
# 4. Set gateway_public_url to https://&lt;machine-name&gt;.ts.net:18789</pre>
      </div>
    </details>

    <!-- ==================== TERMINAL ==================== -->
    <div class="term">
      <iframe src="./terminal/" title="Terminal"></iframe>
    </div>
  </div>

  <!-- ==================== CLIENT-SIDE LOGIC ==================== -->
  <script>
  (function() {
    const ACCESS_MODE = '__ACCESS_MODE__';
    const HTTPS_PORT = '__HTTPS_PORT__';
    const GW_PUBLIC_URL = '__GATEWAY_PUBLIC_URL__';
    const GW_TOKEN = '__GATEWAY_TOKEN__';
    const DISK_PCT = '__DISK_PCT__';
    const DISK_AVAIL = '__DISK_AVAIL__';
    const DISK_USED = '__DISK_USED__';
    const DISK_TOTAL = '__DISK_TOTAL__';

    const $ = id => document.getElementById(id);

    function formatSetupFlag(el) {
      if (!el) return;
      const val = (el.textContent || '').trim().toLowerCase();
      el.innerHTML = val === 'yes' ? '✅ yes' : '❌ no';
    }
    formatSetupFlag($('setupApiKey'));
    formatSetupFlag($('setupModel'));
    formatSetupFlag($('setupMcp'));
    formatSetupFlag($('setupAssist'));
    const gatewayHint = '__SETUP_GATEWAY_URL_HINT__';
    if (gatewayHint && $('setupGatewayHint')) {
      $('setupGatewayHint').innerHTML =
        'Suggested gateway URL: <code>' + gatewayHint + '</code> — set <code>gateway_public_url</code> if the Open Gateway button URL is wrong.';
    }

    // ---------- Secure context detection ----------
    const isSecure = window.isSecureContext;
    const secureBadge = $('secureBadge');
    const statusSecure = $('statusSecure');
    if (isSecure) {
      secureBadge.textContent = 'secure';
      secureBadge.className = 'badge secure';
      statusSecure.innerHTML = '<span class="icon">✅</span><span>Secure context: <b>yes</b></span>';
    } else {
      secureBadge.textContent = 'not secure';
      secureBadge.className = 'badge insecure';
      statusSecure.innerHTML = '<span class="icon">❌</span><span>Secure context: <b>no</b> — HTTPS required for Control UI</span>';
    }

    // ---------- HA status.json (add-on exporter) ----------
    (async function loadHaStatus() {
      const el = $('haStatusLive');
      if (!el) return;
      try {
        const r = await fetch('/status.json', { cache: 'no-store' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const s = await r.json();
        const u = s.usage || {};
        const gw = s.gateway_running ? 'running' : 'unreachable';
        const model = (s.main_provider && s.main_model && s.main_model !== 'unknown')
          ? s.main_provider + ' / ' + s.main_model
          : (s.main_model || 'not set');
        const tokens = u.total_tokens != null ? u.total_tokens : '—';
        const cost = u.estimated_cost_usd != null ? '$' + Number(u.estimated_cost_usd).toFixed(4) : '—';
        el.innerHTML =
          'Gateway: <b>' + gw + '</b> · Model: <b>' + model + '</b> · Tokens: <b>' + tokens + '</b> · Est. cost: <b>' + cost + '</b>' +
          (s.updated_at ? ' <span class="muted">(updated ' + s.updated_at + ')</span>' : '');
      } catch {
        el.innerHTML = 'Live status unavailable yet — exporter may still be starting. Check add-on logs or <code>/share/hermes/status.json</code>.';
      }
    })();

    // ---------- Gateway health check ----------
    (async function checkGateway() {
      const statusEl = $('statusGateway');
      try {
        const url = GW_PUBLIC_URL
          ? GW_PUBLIC_URL.replace(/\/$/, '') + '/api/health'
          : '/api/health'; // fallback to relative (only works if proxied)
        const r = await fetch(url, { mode: 'no-cors', cache: 'no-store' }).catch(() => null);
        if (r && (r.ok || r.type === 'opaque')) {
          statusEl.innerHTML = '<span class="icon">✅</span><span>Gateway: <b>running</b></span>';
        } else {
          statusEl.innerHTML = '<span class="icon">⚠️</span><span>Gateway: <b>unreachable</b> (may still be starting)</span>';
        }
      } catch {
        statusEl.innerHTML = '<span class="icon">❌</span><span>Gateway: <b>unreachable</b></span>';
      }
    })();

    // ---------- Error translation ----------
    const ERROR_MAP = {
      'control ui requires device identity': {
        friendly: 'The Gateway UI requires HTTPS or localhost (secure context). Plain HTTP over LAN is blocked.',
        fix: ACCESS_MODE === 'lan_https'
          ? 'Your add-on is configured for lan_https. Open the gateway via the HTTPS URL above and install the CA certificate on your device.'
          : 'Switch <code>access_mode</code> to <b>lan_https</b> in add-on Configuration, then restart. This enables a built-in HTTPS proxy for LAN access.'
      },
      'requires secure context': {
        friendly: 'The browser is not in a secure context. HTTPS or localhost is required.',
        fix: 'Use the HTTPS URL provided by the add-on, or set up a reverse proxy with TLS.'
      },
      'pairing required': {
        friendly: 'The Gateway requires device pairing before the Control UI can connect.',
        fix: ACCESS_MODE === 'lan_https'
          ? 'Restart the add-on — by default it sets <code>controlUi.dangerouslyDisableDeviceAuth: true</code> to skip pairing (token auth is still enforced). You can change this via <code>controlui_disable_device_auth</code> in add-on options. <br><small>Note: v2026.2.22+ shows an <em>expected</em> security warning for this flag in the gateway logs — it is safe to ignore.</small>'
          : 'Set <code>access_mode</code> to <b>lan_https</b> and restart. Or from the terminal: edit <code>/config/.hermes/hermes.json</code> and set <code>gateway.controlUi.dangerouslyDisableDeviceAuth: true</code>, then restart the gateway.'
      },
      'origin not allowed': {
        friendly: 'The Gateway rejected the browser origin. The Control UI URL is not in the allow-list.',
        fix: ACCESS_MODE === 'lan_https'
          ? 'Restart the add-on — it auto-adds HTTPS origins to <code>controlUi.allowedOrigins</code>. If you changed your LAN IP, a restart regenerates the config.'
          : 'Manually add your origin: <code>hermes config set gateway.controlUi.allowedOrigins \'["https://YOUR_IP:18789"]\' </code>'
      },
      '1008': {
        friendly: 'WebSocket disconnected (1008).',
        fix: 'Ensure you are connecting over HTTPS. Check the add-on logs for the specific sub-error (device identity / origin / pairing).'
      }
    };

    // Expose for manual use: translateError('1008')
    window.translateError = function(rawError) {
      const lower = (rawError || '').toLowerCase();
      for (const [pattern, info] of Object.entries(ERROR_MAP)) {
        if (lower.includes(pattern)) {
          return info;
        }
      }
      return null;
    };

    // ---------- Migration banner ----------
    if (ACCESS_MODE === 'custom') {
      $('migrationBanner').classList.remove('hidden');
    }

    // ---------- Disk space monitoring ----------
    if (DISK_PCT) {
      const pctNum = parseInt(DISK_PCT, 10);
      const diskIcon = $('diskIcon');
      const statusDisk = $('statusDisk');
      if (pctNum >= 90) {
        diskIcon.textContent = '🔴';
        statusDisk.style.borderColor = '#dc2626';
        $('diskBanner').classList.remove('hidden');
        $('diskBannerText').textContent =
          `Disk is ${DISK_PCT} full (${DISK_AVAIL} free of ${DISK_TOTAL}).`;
      } else if (pctNum >= 75) {
        diskIcon.textContent = '🟡';
        statusDisk.style.borderColor = '#d97706';
        $('diskBanner').classList.remove('hidden');
        $('diskBannerText').textContent =
          `Disk is ${DISK_PCT} full (${DISK_AVAIL} free of ${DISK_TOTAL}). Consider cleaning up soon.`;
      } else {
        diskIcon.textContent = '🟢';
      }
    }

    // ---------- CA certificate download ----------
    if (ACCESS_MODE === 'lan_https' && HTTPS_PORT) {
      const certBtn = $('certBtn');
      // Build cert URL relative to the gateway's HTTPS port
      const host = window.location.hostname || 'homeassistant.local';
      certBtn.href = 'https://' + host + ':' + HTTPS_PORT + '/cert/ca.crt';
      certBtn.classList.remove('hidden');
    }

    // ---------- Access wizard ----------
    const wizardEl = $('wizard');
    const wizardContent = $('wizardContent');

    if (ACCESS_MODE === 'lan_https') {
      wizardEl.classList.remove('hidden');
      wizardContent.innerHTML = `
        <div class="banner success">✅ Built-in HTTPS proxy is active on port <b>${HTTPS_PORT}</b>.</div>
        <ol>
          <li>Click <b>Open Gateway Web UI</b> above — it will use HTTPS automatically.</li>
          <li>Your browser may show a certificate warning the first time. Click <b>Advanced → Proceed</b> to continue.</li>
          <li><b>For phones/tablets (one-time):</b> Click <b>Download CA Certificate</b>, then install it:
            <ul style="margin:4px 0;padding-left:18px">
              <li><b>Android:</b> Settings → Security → Install certificate → CA certificate → select the file</li>
              <li><b>iOS:</b> Open the .crt file → Install Profile → Settings → General → About → Certificate Trust Settings → enable</li>
            </ul>
            After installing the CA, the browser will trust the gateway without warnings.
          </li>
        </ol>`;
    } else if (ACCESS_MODE === 'lan_reverse_proxy') {
      wizardEl.classList.remove('hidden');
      wizardContent.innerHTML = `
        <ol>
          <li>Configure your reverse proxy (NPM / Caddy / Traefik) to forward HTTPS to <code>&lt;HA-IP&gt;:${GW_PUBLIC_URL ? new URL(GW_PUBLIC_URL).port || '18789' : '18789'}</code>.</li>
          <li>Set <code>gateway_public_url</code> to your HTTPS URL (e.g. <code>https://hermes.example.com</code>).</li>
          <li>Set <code>gateway_trusted_proxies</code> to your proxy's IP/CIDR.</li>
          <li>Restart the add-on. See <b>Reverse-proxy recipes</b> below for copy-paste configs.</li>
        </ol>`;
    } else if (ACCESS_MODE === 'tailnet_https') {
      wizardEl.classList.remove('hidden');
      wizardContent.innerHTML = `
        <ol>
          <li>Ensure Tailscale is installed on the HA host and this device.</li>
          <li>Enable HTTPS certificates in Tailnet admin: <b>DNS → HTTPS Certificates</b>.</li>
          <li>On the HA host: <code>tailscale cert &lt;machine-name&gt;.ts.net</code></li>
          <li>Set <code>gateway_public_url</code> to <code>https://&lt;machine-name&gt;.ts.net:18789</code></li>
          <li>Restart the add-on.</li>
        </ol>`;
    } else if (ACCESS_MODE === 'local_only') {
      wizardEl.classList.remove('hidden');
      wizardContent.innerHTML = `
        <div class="banner info">Gateway is bound to localhost only. Use the embedded terminal or Ingress.</div>
        <p style="font-size:14px;">To access from phones or other devices, switch <code>access_mode</code> to <b>lan_https</b> in add-on Configuration.</p>`;
    } else if (ACCESS_MODE === 'custom' && !isSecure) {
      wizardEl.classList.remove('hidden');
      wizardContent.innerHTML = `
        <div class="banner warn">You are using custom settings and this page is not in a secure context.
        The Gateway Control UI will reject connections over plain HTTP.</div>
        <p style="font-size:14px"><b>Recommended:</b> Go to <b>Settings → Add-ons → Hermes Agent → Configuration</b>
        and set <code>access_mode</code> to one of:</p>
        <ul style="font-size:14px;line-height:1.8;padding-left:22px">
          <li><b>lan_https</b> — easiest, adds built-in HTTPS proxy (no external setup needed)</li>
          <li><b>lan_reverse_proxy</b> — if you already have NPM / Caddy / Traefik</li>
          <li><b>tailnet_https</b> — if you use Tailscale</li>
        </ul>`;
    }

  })();
  </script>
</body>
</html>
