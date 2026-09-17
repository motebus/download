FROM docker.io/library/ubuntu@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 adduser passwd init-system-helpers libgcc-s1 && rm -rf /var/lib/apt/lists/*
