# Deliberately Debian (not the Alpine community base image with s6/bashio): the current Mesa and the Raspberry Pi FFmpeg packages
# (H.265 hardware decoding) are Debian only. The image is fixed here and does not use BUILD_FROM (the Supervisor sets it to its
# Alpine base image).
FROM docker.io/library/debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      mpv libgl1-mesa-dri libegl1 libgles2 libgbm1 python3-yaml alsa-utils pulseaudio-utils curl python3 libdrm-tests ca-certificates \
      gnupg gpgv v4l-utils fonts-dejavu-core fonts-inter \
 && rm -rf /var/lib/apt/lists/*

# Raspberry Pi: FFmpeg libraries of the Raspberry Pi archive give mpv hardware decoding of H.265 (V4L2 stateless decoder of the Pi 5).
# trixie's apt rejects that archive's signing key, so pi-debs.sh downloads and verifies the packages itself (pinned key fingerprint,
# InRelease with gpgv, SHA256 of Packages and of every .deb). Only for arm64.
ARG TARGETARCH
COPY pi-debs.sh /pi-debs.sh
RUN if [ "$TARGETARCH" = "arm64" ]; then \
      apt-get update && sh /pi-debs.sh && apt-get install -y --no-install-recommends /pi-debs/*.deb \
      && rm -rf /var/lib/apt/lists/* /pi-debs; \
    fi

# x86 (amd64): VAAPI drivers for Intel (iHD for current, i965 for older GPUs) and AMD (Mesa) graphics, for hardware decoding of
# H.264 and H.265.
RUN if [ "$TARGETARCH" = "amd64" ]; then \
      apt-get update && apt-get install -y --no-install-recommends intel-media-va-driver i965-va-driver mesa-va-drivers \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Copy root filesystem
COPY rootfs /
COPY translations /translations

# Build arguments
ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION
ENV TV7_VERSION=$BUILD_VERSION

# Labels
LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="Sebastian Goodrick <sebastian@goodrick.ch>" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.authors="Sebastian Goodrick <sebastian@goodrick.ch>" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}

RUN chmod +x /run.sh
CMD ["/run.sh"]
