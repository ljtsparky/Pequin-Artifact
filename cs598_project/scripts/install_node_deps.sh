#!/usr/bin/env bash
#
# install_node_deps.sh — re-install everything needed on a fresh CloudLab
# node so the resulting disk image has all binaries, libs, and data
# pre-staged for the Pesto cross-shard experiments.
#
# Usage (on the CloudLab node):
#   bash install_node_deps.sh
#
# This is the canonical recipe for what was baked into the image.
# If the image needs to be re-created, run this top-to-bottom on a fresh
# amd Ubuntu 22.04 node.

set -euo pipefail

# --- 1. Pesto upstream deps (long, ~30 min total) ---
sudo apt-get update
sudo apt-get install -y \
    autoconf automake libtool curl make g++ unzip valgrind cmake gnuplot \
    pkg-config ant parallel python3-pip jq openjdk-11-jre openjdk-11-jdk \
    libsodium-dev libgflags-dev libssl-dev libevent-dev \
    libevent-openssl-2.1-7 libevent-pthreads-2.1-7 libboost-all-dev \
    libuv1-dev libpq-dev postgresql-server-dev-all libfmt-dev \
    libreadline-dev libeigen3-dev

# Pesto's own installer brings the rest (jemalloc, taopq, nlohmann/json,
# googletest, protobuf, secp256k1, cryptopp, BLAKE3, ed25519-donna,
# libcount, libpg_query, IntelTBB, BFTSmart, CockroachDB, PostgreSQL)
if [ ! -d /opt/Pequin-Artifact ]; then
    sudo mkdir -p /opt && sudo chown $USER /opt
    cd /opt
    git clone https://github.com/ljtsparky/Pequin-Artifact.git
    cd Pequin-Artifact
    git checkout cross-shard-membership
fi
cd /opt/Pequin-Artifact
git pull origin cross-shard-membership

# Pesto's full installer (interactive — just hit enter past prompts)
bash install_dependencies.sh || true

# --- 2. Build Pesto ---
cd /opt/Pequin-Artifact/src
source /opt/intel/oneapi/setvars.sh --force
make -j$(nproc)

# --- 3. Generate Ed25519 keys (one-time) ---
if [ ! -d keys ] || [ -z "$(ls -A keys 2>/dev/null)" ]; then
    bash keygen.sh
fi

# --- 4. Pre-generate TPC-C 10-warehouse data ---
sudo mkdir -p /opt/pesto-tpcc-data && sudo chown $USER /opt/pesto-tpcc-data
cd /opt/pesto-tpcc-data
export LD_LIBRARY_PATH=/usr/lib/jvm/java-11-openjdk-amd64/lib/server:$LD_LIBRARY_PATH
/opt/Pequin-Artifact/src/store/benchmark/async/sql/tpcc/sql_tpcc_generator \
    --num_warehouses=10

# --- 5. Download Elle CLI jar ---
sudo mkdir -p /opt/elle-cli && sudo chown $USER /opt/elle-cli
cd /opt/elle-cli
if [ ! -f target/elle-cli-0.1.9-standalone.jar ]; then
    wget -q https://github.com/ligurio/elle-cli/releases/download/0.1.9/elle-cli-bin-0.1.9.zip
    unzip -o elle-cli-bin-0.1.9.zip
fi
sudo ln -sf /opt/elle-cli/target/elle-cli-0.1.9-standalone.jar /usr/local/bin/elle-cli.jar

# --- 6. Verify ---
echo "=========================================="
echo "Node ready. Verification:"
echo ""
echo "Pesto server binary:"
ls -lh /opt/Pequin-Artifact/src/store/server
echo ""
echo "Pesto benchmark binary:"
ls -lh /opt/Pequin-Artifact/src/store/benchmark/async/benchmark
echo ""
echo "Membership unit tests (should be 34/34 PASS):"
source /opt/intel/oneapi/setvars.sh --force >/dev/null 2>&1
/opt/Pequin-Artifact/src/store/pequinstore/tests/membership_test 2>&1 | tail -3
echo ""
echo "TPC-C data:"
du -sh /opt/pesto-tpcc-data/
echo ""
echo "Elle CLI:"
java -jar /usr/local/bin/elle-cli.jar 2>&1 | head -2
echo ""
echo "All set. Snapshot the disk image now."
