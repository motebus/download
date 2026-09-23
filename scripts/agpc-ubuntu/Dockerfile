# Package-build foundation. Runtime/host-bridge acceptance is still required.
FROM --platform=linux/amd64 ubuntu@sha256:678c6550cc43645e08669028bc177f50be4e7c5b8cca677067b1914d4afc7a03
LABEL org.motebus.agpc.role="mac-runtime" \
      org.opencontainers.image.title="AGPC Ubuntu 26.04" \
      org.opencontainers.image.description="Existing signed AGPC DEBs on Ubuntu; Mac host bridge pending"
ENV container=docker
COPY medge-archive-keyring.gpg /usr/share/keyrings/medge-archive-keyring.gpg
COPY medge.sources /etc/apt/sources.list.d/medge.sources.pending
COPY agent-computer-apt-overlay.json /usr/share/agpc-build/package-lock.json
COPY scripts/agpc-ubuntu/install-packages.sh /usr/local/libexec/agpc-install-packages
COPY scripts/agpc-host-bridge/ /usr/local/libexec/agpc/
RUN bash /usr/local/libexec/agpc-install-packages \
    && chmod 0755 /usr/local/libexec/agpc/codex-stream.py \
    && python3 /usr/local/libexec/agpc/configure-cx.py /etc/cx-mesh/cx-mesh.toml \
    && install -m 0644 /usr/local/libexec/agpc/ssh.service /etc/systemd/system/ssh.service \
    && rm -f /etc/systemd/system/ssh.service.requires/ssh.socket \
             /etc/systemd/system/ssh.service.wants/sshd-keygen.service \
    && ln -sf /dev/null /etc/systemd/system/ssh.socket \
    && ln -sf /dev/null /etc/systemd/system/dev-hugepages.mount \
    && ln -sf /dev/null /etc/systemd/system/sys-fs-fuse-connections.mount
STOPSIGNAL SIGRTMIN+3
# Preserve packaged service contracts. Do not substitute fake systemctl commands.
# No privileged/cgroup-host configuration is shipped; Mac runtime admission is pending.
CMD ["/sbin/init"]
