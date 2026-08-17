# ccsync-sftp -- the chrooted internal-sftp sidecar. ZERO_TOUCH_PLAN.md 3.1
# ("SFTP as a sidecar is the decision that removes the most"): lane A/B talk
# to THIS instead of the NAS host's own sshd, so the product needs no NAS
# accounts, no home directories, no `chown -R`, no sshd `Match Group` block
# appended to a middleware-owned config file. See README.md in this directory
# for the chroot layout and the uid model this image assumes.
#
# BUILD FROM THE REPO ROOT, same as dashboard/deploy/Dockerfile and for the
# same reason -- the two shell helpers and sshd_config below are COPYed with
# paths relative to the root so both images share one build convention:
#
#   docker build -f dashboard/deploy/sftp/Dockerfile -t ccsync-sftp:<ver> .
#
# Alpine, not the dashboard's python:3.12-slim: this image carries none of
# our Python -- just OpenSSH and two small shell scripts -- so Alpine's
# openssh-server (a few MB) is the honest base rather than dragging in glibc
# and everything Debian-slim pulls with it.
#
# Pinned BY DIGEST, matching dashboard/deploy/Dockerfile's own reasoning: a
# bare `alpine:3.20` tag is mutable, and this image is the thing that holds
# every editor's pubkey verification and the tree mount, i.e. the thing a
# customer's security review reads first. Resolved 2026-08-17 against
# registry-1.docker.io; the index digest below covers both amd64 (TrueNAS,
# the DS423+) and arm64. `docs/spikes/zero-touch-spikes-2026-08-17.md` S2
# spiked this same design on 3.19 and calls 3.20 an equally fine pin.
#
# Bump it deliberately, together with dashboard/deploy/Dockerfile's own pin,
# and re-run this image through a build before shipping either.
ARG BASE_IMAGE=alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="ccsync-sftp" \
      org.opencontainers.image.description="Chrooted internal-sftp sidecar for the CC Sync appliance -- keys served by the dashboard, no NAS accounts" \
      org.opencontainers.image.source="https://example.invalid/ccsync" \
      org.opencontainers.image.licenses="NOASSERTION"

# openssh-server: OpenSSH itself -- a BSD-style licence, the same "fine to
#   ship" verdict tools/check_licenses.py's own docstring gives it, and the
#   ONLY new copyleft-adjacent surface here is what Alpine's base image
#   already carries (musl is MIT; busybox is GPLv2, and every Alpine image
#   ever shipped already carries it -- this is not the ffmpeg situation,
#   which is a GPLv3 build we chose not to bake in at all, see
#   dashboard/deploy/Dockerfile and COMMERCIAL_READINESS.md item 3).
# openssh-sftp-server: Alpine SPLITS this out of openssh-server -- the spike
#   that validated this whole image installed it explicitly
#   (docs/spikes/zero-touch-spikes-2026-08-17.md S2) and this Dockerfile
#   matches that exact, proven package list rather than assume
#   `internal-sftp` works without it.
# shadow: gives us `useradd -o` (a non-unique uid). BusyBox's own `adduser`
#   REFUSES a shared uid, and every editor is the same service uid today
#   (ZERO_TOUCH_PLAN.md section 5 -- per-project uids are spike S3, not yet
#   built). shadow's own licence is BSD-3-Clause since its 4.9 release.
# curl: the two helper scripts below talk to the dashboard's internal API.
# jq: parses `GET /internal/sftp/users`' JSON in ccsync-users (MIT).
RUN apk add --no-cache openssh-server openssh-sftp-server shadow curl jq \
    && rm -rf /var/cache/apk/*

COPY dashboard/deploy/sftp/sshd_config /etc/ssh/sshd_config
COPY dashboard/deploy/sftp/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY dashboard/deploy/sftp/ccsync-keys.sh /usr/local/bin/ccsync-keys
COPY dashboard/deploy/sftp/ccsync-users.sh /usr/local/bin/ccsync-users

# /jail is the chroot root ForceCommand lands editors in (README.md "chroot
# layout"). ChrootDirectory requires it, and every directory above it up to
# /, to be owned by root and not group/other-writable -- sshd's StrictModes
# check refuses the login otherwise, silently from an editor's point of view
# (rclone just sees "Connection reset").  /jail/tree is the tree BIND MOUNT
# (compose's job, not this image's -- an empty /jail/tree here is normal,
# it means nobody has attached the volume yet).
#
# `sftpkeys`: a dedicated, otherwise-empty account for `AuthorizedKeysCommandUser`
# -- NOT `nobody`. ccsync-keys.sh reads the internal API token from a file;
# `nobody` reading it would mean every unprivileged process in the container
# is equally entitled to it, which is a strictly bigger exposure than one
# named, single-purpose account (spike recommendation,
# docs/spikes/zero-touch-spikes-2026-08-17.md S2 verdict). `-D`: no password
# set at all -- this account is never logged into, only exec'd BY sshd as a
# fixed, already-known uid.
RUN chmod 755 /usr/local/bin/entrypoint.sh /usr/local/bin/ccsync-keys /usr/local/bin/ccsync-users \
    && mkdir -p /jail/tree /etc/ccsync \
    && chown root:root /jail \
    && chmod 755 /jail \
    && adduser -D -H -s /sbin/nologin sftpkeys

# Stays root. sshd needs it (privilege separation drops to the target user
# post-auth, but the listener and the pre-fork are root), and so does
# `useradd`/`addgroup` in ccsync-users -- this container IS the thing that
# owns the tree mount, so tree/account ownership is its own business
# (ZERO_TOUCH_PLAN.md 3.1). Nothing here holds a NAS credential the way the
# dashboard container does, so root-in-this-container is a much smaller
# blast radius than root-over-SSH-on-the-NAS-host was.
EXPOSE 22

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
