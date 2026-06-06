#!/usr/bin/env python3
"""
Render nginx.conf and landing page HTML from templates.

Called by run.sh with the following env vars:
  GW_PUBLIC_URL, GW_TOKEN, TERMINAL_PORT,
  ENABLE_HTTPS_PROXY, HTTPS_PROXY_PORT,
  GATEWAY_INTERNAL_PORT, ACCESS_MODE,
  ENABLE_OPENAI_API, API_SERVER_PORT,
  DISK_TOTAL, DISK_USED, DISK_AVAIL, DISK_PCT
"""

import os
import subprocess
from pathlib import Path


def _api_proxy_locations(api_port: str) -> str:
    """Route OpenAI-compatible Assist API paths to the Hermes API server."""
    return f"""
        # OpenAI-compatible Assist API (hermes gateway API server)
        location ^~ /v1/ {{
            proxy_pass http://127.0.0.1:{api_port};
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_read_timeout 86400s;
            proxy_send_timeout 86400s;
            proxy_buffering off;
        }}

        location = /health {{
            proxy_pass http://127.0.0.1:{api_port}/health;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
        }}

        location ^~ /health/ {{
            proxy_pass http://127.0.0.1:{api_port};
            proxy_http_version 1.1;
            proxy_set_header Host $host;
        }}

        location ^~ /api/ {{
            proxy_pass http://127.0.0.1:{api_port};
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_read_timeout 86400s;
            proxy_send_timeout 86400s;
            proxy_buffering off;
        }}
"""


def main():
    tpl = Path('/etc/nginx/nginx.conf.tpl').read_text()
    landing_tpl = Path('/etc/nginx/landing.html.tpl').read_text()

    public_url = os.environ.get('GW_PUBLIC_URL', '')
    terminal_port = os.environ.get('TERMINAL_PORT', '7681')
    enable_https = os.environ.get('ENABLE_HTTPS_PROXY', 'false') == 'true'
    https_port = os.environ.get('HTTPS_PROXY_PORT', '')
    internal_gw_port = os.environ.get('GATEWAY_INTERNAL_PORT', '')
    access_mode = os.environ.get('ACCESS_MODE', 'custom')
    enable_openai_api = os.environ.get('ENABLE_OPENAI_API', 'false').lower() in ('1', 'true', 'yes')
    api_server_port = os.environ.get('API_SERVER_PORT', '8642')

    # Disk usage info (collected by run.sh)
    disk_total = os.environ.get('DISK_TOTAL', '')
    disk_used = os.environ.get('DISK_USED', '')
    disk_avail = os.environ.get('DISK_AVAIL', '')
    disk_pct = os.environ.get('DISK_PCT', '')
    nginx_log_level = os.environ.get('NGINX_LOG_LEVEL', 'minimal')
    setup_api_key = os.environ.get('SETUP_API_KEY', 'no')
    setup_model = os.environ.get('SETUP_MODEL', 'no')
    setup_mcp = os.environ.get('SETUP_MCP', 'no')
    setup_assist = os.environ.get('SETUP_ASSIST', 'no')
    gateway_url_hint = os.environ.get('SETUP_GATEWAY_URL_HINT', '')

    # Token comes from environment (best-effort CLI query in run.sh)
    token = os.environ.get('GW_TOKEN', '')

    gw_path = '' if public_url.endswith('/') else '/'

    # ── nginx.conf ──────────────────────────────────────────────
    # Build access_log directive (minimal suppresses HA health-check / polling noise)
    if nginx_log_level == 'minimal':
        access_log_block = (
            '# Suppress repetitive HA health-check / polling requests\n'
            '  map $http_user_agent $loggable {\n'
            '    ~HomeAssistant 0;\n'
            '    default 1;\n'
            '  }\n'
            '  access_log /dev/stdout combined if=$loggable;'
        )
    else:
        access_log_block = 'access_log /dev/stdout;'

    conf = tpl.replace('__NGINX_ACCESS_LOG__', access_log_block)
    conf = conf.replace('__TERMINAL_PORT__', terminal_port)

    # Build HTTPS gateway proxy block (only for lan_https mode)
    https_block = ''
    if enable_https and https_port and internal_gw_port:
        api_locations = ''
        if enable_openai_api and api_server_port:
            api_locations = _api_proxy_locations(api_server_port)
        https_block = f"""
    # --- HTTPS Gateway Proxy (lan_https mode) ---
    server {{
        listen {https_port} ssl;

        ssl_certificate     /config/certs/gateway.crt;
        ssl_certificate_key /config/certs/gateway.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;
{api_locations}
        # Dashboard Web UI and WebSocket traffic
        location / {{
            proxy_pass http://127.0.0.1:{internal_gw_port};
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_read_timeout 86400s;
            proxy_send_timeout 86400s;
            proxy_buffering off;
        }}

        # Download the local CA certificate (install on phone for trusted access)
        location = /cert/ca.crt {{
            alias /etc/nginx/html/hermes-ca.crt;
            default_type application/x-x509-ca-cert;
            add_header Content-Disposition 'attachment; filename="hermes-ca.crt"';
        }}
    }}
"""

    conf = conf.replace('__HTTPS_GATEWAY_BLOCK__', https_block)
    Path('/etc/nginx/nginx.conf').write_text(conf)

    # ── landing page ────────────────────────────────────────────
    # If lan_https and no explicit public URL, auto-construct one
    if enable_https and not public_url:
        try:
            lan_ip = subprocess.check_output(
                ['hostname', '-I'], text=True, timeout=2
            ).split()[0]
        except Exception:
            lan_ip = '127.0.0.1'
        public_url = f'https://{lan_ip}:{https_port}'
        gw_path = '/'

    landing = landing_tpl.replace('__GATEWAY_TOKEN__', token)
    landing = landing.replace('__GATEWAY_PUBLIC_URL__', public_url)
    landing = landing.replace('__GW_PUBLIC_URL_PATH__', gw_path)
    landing = landing.replace('__ACCESS_MODE__', access_mode)
    landing = landing.replace('__HTTPS_PORT__', https_port if enable_https else '')
    landing = landing.replace('__DISK_TOTAL__', disk_total)
    landing = landing.replace('__DISK_USED__', disk_used)
    landing = landing.replace('__DISK_AVAIL__', disk_avail)
    landing = landing.replace('__DISK_PCT__', disk_pct)
    landing = landing.replace('__SETUP_API_KEY__', setup_api_key)
    landing = landing.replace('__SETUP_MODEL__', setup_model)
    landing = landing.replace('__SETUP_MCP__', setup_mcp)
    landing = landing.replace('__SETUP_ASSIST__', setup_assist)
    landing = landing.replace('__SETUP_GATEWAY_URL_HINT__', gateway_url_hint)

    out_dir = Path('/etc/nginx/html')
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / 'index.html'
    out_file.write_text(landing)

    # Ensure nginx can read it even if base image uses restrictive umask/permissions.
    try:
        out_dir.chmod(0o755)
        out_file.chmod(0o644)
    except Exception:
        pass


if __name__ == '__main__':
    main()
