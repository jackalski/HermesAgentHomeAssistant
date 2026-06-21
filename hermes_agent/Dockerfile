# Base image is Debian Bookworm (glibc). BUILD_ARCH is supplied by the HA Supervisor build.
# Replaces deprecated build.yaml (per-arch ghcr.io/home-assistant/*-base-debian:bookworm).
ARG BUILD_ARCH
ARG BUILD_VERSION
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:bookworm

# System-wide Python/Node tooling (Hermes 0.16+ expects managed uv + MCP SDK on PATH).
ENV PIP_BREAK_SYSTEM_PACKAGES=1 \
    UV_BREAK_SYSTEM_PACKAGES=1 \
    UV_SYSTEM_PYTHON=1 \
    NPM_CONFIG_PREFIX=/usr/local \
    PATH="/usr/local/bin:/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:${PATH}"

# Refresh the base image, then install core system packages (before NodeSource/uv/Hermes).
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
    bash \
    git \
    openssh-client \
    ca-certificates \
    tzdata \
    jq \
    curl \
    tar \
    xz-utils \
    file \
    python3 \
    python3-pip \
    python3-aiohttp \
    python3-yaml \
    python3-venv \
    nginx \
    gnupg \
    build-essential \
    sudo \
    vim \
    nano \
    fd-find \
    ripgrep \
    rsync \
    bat \
    less \
    openssl \
    mosquitto-clients \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# uv — system-wide Python installer (Hermes MCP catalog / uvx servers).
RUN curl -LsSf https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh \
    && uv --version

# Node.js 22 LTS from NodeSource (Debian Bookworm ships Node 18; Hermes requires 20+).
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && chmod 644 /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
    > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && NODE_VERSION="$(node -v)" \
    && echo "$NODE_VERSION" \
    && echo "$NODE_VERSION" | grep -E '^v22\.' \
    && rm -f /etc/apt/sources.list.d/nodesource.list /etc/apt/keyrings/nodesource.gpg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install ttyd (web terminal) - not in Debian repos, download binary
# Docker TARGETARCH: amd64, arm64, arm/v7 → ttyd filenames: x86_64, aarch64, armhf
ARG TARGETARCH
RUN ARCH=$(echo ${TARGETARCH:-$(dpkg --print-architecture)} | sed 's|arm64|aarch64|;s|arm/v7|armhf|;s|armv7|armhf|;s|amd64|x86_64|') \
    && echo "Downloading ttyd for arch: ${ARCH}" \
    && curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.${ARCH}" -o /usr/local/bin/ttyd \
    && chmod +x /usr/local/bin/ttyd

RUN node -v && npm -v

# Install pnpm globally (system-wide; required by some Hermes Agent skills)
RUN npm install -g pnpm && pnpm -v

# Chromium for website automation tasks
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Homebrew (Linuxbrew) for Hermes Agent skill dependencies — optional on older CPUs.
ENV HOMEBREW_NO_AUTO_UPDATE=1 \
    HOMEBREW_NO_INSTALL_CLEANUP=1 \
    HOMEBREW_NO_ANALYTICS=1

RUN useradd -m -s /bin/bash linuxbrew \
    && mkdir -p /home/linuxbrew/.linuxbrew \
    && chown -R linuxbrew:linuxbrew /home/linuxbrew

USER linuxbrew
RUN /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || \
    (echo "WARNING: Homebrew installation failed (likely unsupported CPU - requires SSSE3). Some skills may not work." && exit 0)
RUN if [ -d /home/linuxbrew/.linuxbrew/Homebrew ]; then \
    cd /home/linuxbrew/.linuxbrew/Homebrew && \
    git config --global --add safe.directory /home/linuxbrew/.linuxbrew/Homebrew && \
    /home/linuxbrew/.linuxbrew/bin/brew update --force || true; \
    fi
USER root

COPY brew-wrapper.sh /usr/local/bin/brew
RUN chmod +x /usr/local/bin/brew

USER linuxbrew
RUN if [ -x /home/linuxbrew/.linuxbrew/bin/brew ]; then \
    /home/linuxbrew/.linuxbrew/bin/brew --version && \
    /home/linuxbrew/.linuxbrew/bin/brew install gcc || true; \
    else \
    echo "Skipping gcc installation - Homebrew not available"; \
    fi
USER root

RUN python3 -m pip config set global.break-system-packages true \
    && npm config set fund false \
    && npm config set audit false \
    && npm install -g hermes-agent@0.17.0 \
    && npm install -g agent-browser@latest

# Safety net if a Hermes PyPI wheel omits hermes_cli subpackages (upstream #34701 on older releases).
COPY repair_hermes_wheel.py /repair_hermes_wheel.py
RUN python3 /repair_hermes_wheel.py

# System-wide Python deps: MCP SDK + gateway/dashboard/tooling (uv preferred, pip fallback).
RUN uv pip install --system --break-system-packages --no-cache \
        paho-mqtt \
        mcp \
        websockets \
        "python-telegram-bot[webhooks]>=22.7" \
        edge-tts \
        ddgs \
        "discord.py[voice]>=2.7.1" \
        "brotlicffi>=1.2.0.1" \
        "starlette>=1.0.1" \
        "fastapi>=0.136.3" \
        "uvicorn[standard]>=0.49.0" \
        ptyprocess

# Shell aliases and color options for interactive use
RUN tee -a /etc/bash.bashrc <<'EOF'

# Aliases
alias bat="batcat"
alias fd="fdfind"

# Enable colors
alias ls="ls --color=auto"
alias grep="grep --color=auto"
alias egrep="grep -E --color=auto"
alias fgrep="grep -F --color=auto"
alias diff="diff --color=auto"
alias ip="ip --color=auto"
if [ -z "${LS_COLORS+x}" ]; then
  export LS_COLORS="di=1;34:ln=1;36:so=1;pi=33:ex=1;32:bd=1;33:cd=1;33:su=1;31:sg=1;31:tw=1;34:ow=1;34"
fi
EOF
COPY run.sh /run.sh
COPY addon_log.sh /addon_log.sh
COPY hermes_config_helper.py /hermes_config_helper.py
COPY hermes_status_exporter.py /hermes_status_exporter.py
COPY hermes_mqtt_resolver.py /hermes_mqtt_resolver.py
COPY hermes_connection_tests.py /hermes_connection_tests.py
COPY render_nginx.py /render_nginx.py
COPY hermes-cleanup.sh /usr/local/bin/hermes-cleanup
COPY hermes-proxy-shim.cjs /usr/local/lib/hermes-proxy-shim.cjs
COPY nginx.conf.tpl /etc/nginx/nginx.conf.tpl
COPY landing.html.tpl /etc/nginx/landing.html.tpl
# Baked-in copy of the add-on manifest so runtime helpers can read the live
# version (status exporter) without depending on the Supervisor API.
COPY config.yaml /addon_config.yaml
RUN chmod +x /run.sh /addon_log.sh /hermes_config_helper.py /hermes_status_exporter.py /hermes_mqtt_resolver.py /hermes_connection_tests.py /render_nginx.py /repair_hermes_wheel.py /usr/local/bin/hermes-cleanup \
    && mkdir -p /run/nginx

CMD [ "/run.sh" ]
