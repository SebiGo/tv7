# Development image: the runtime dependencies of the add-on (Debian trixie like tv7_player/Dockerfile) plus tooling. The workspace is mounted.
FROM debian:trixie-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      mpv libgl1-mesa-dri libegl1 libgles2 libgbm1 python3 python3-yaml alsa-utils pulseaudio-utils procps psmisc jq curl libdrm-tests ca-certificates \
      v4l-utils git openssh-client shellcheck yamllint less nano nodejs npm \
 && rm -rf /var/lib/apt/lists/*
CMD ["sleep", "infinity"]
