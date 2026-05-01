/***********************************************************************
 *
 * membership.cc:
 *   Implementation of shard membership certificate management for
 *   cross-shard coordination without the sister-replica assumption.
 *
 **********************************************************************/
#include "store/pequinstore/membership.h"
#include "lib/assert.h"
#include "lib/blake3.h"

#include <string>

namespace pequinstore {

proto::ShardMembershipCert MembershipManager::GenerateCert(
    uint64_t group_id,
    uint64_t version,
    const transport::Configuration *config,
    KeyManager *keyManager) {

  proto::ShardMembershipCert cert;
  cert.set_group_id(group_id);
  cert.set_version(version);

  int gf = config->GroupF(static_cast<int>(group_id));
  int gn = config->GroupN(static_cast<int>(group_id));
  cert.set_f(static_cast<uint64_t>(gf));
  cert.set_n(static_cast<uint64_t>(gn));

  // Populate replica info with global IDs and public keys.
  for (int idx = 0; idx < gn; idx++) {
    auto *rep = cert.add_replicas();
    uint64_t globalId = config->GlobalReplicaId(static_cast<int>(group_id), idx);
    rep->set_replica_id(globalId);

    // Serialize the public key bytes from the key manager.
    crypto::PubKey *pubKey = keyManager->GetPublicKey(globalId);
    if (pubKey != nullptr) {
      // Store the raw public key bytes. Ed25519 public keys are 32 bytes.
      rep->set_public_key(
          std::string(reinterpret_cast<const char*>(pubKey), 32));
    }
  }

  // Compute cert_digest = BLAKE3(group_id || version || f || n || replica_ids...).
  blake3_hasher hasher;
  blake3_hasher_init(&hasher);
  blake3_hasher_update(&hasher, &group_id, sizeof(group_id));
  blake3_hasher_update(&hasher, &version, sizeof(version));
  uint64_t fVal = static_cast<uint64_t>(gf);
  uint64_t nVal = static_cast<uint64_t>(gn);
  blake3_hasher_update(&hasher, &fVal, sizeof(fVal));
  blake3_hasher_update(&hasher, &nVal, sizeof(nVal));
  for (const auto &rep : cert.replicas()) {
    uint64_t rid = rep.replica_id();
    blake3_hasher_update(&hasher, &rid, sizeof(rid));
  }
  uint8_t digest[BLAKE3_OUT_LEN];
  blake3_hasher_finalize(&hasher, digest, BLAKE3_OUT_LEN);
  cert.set_cert_digest(std::string(reinterpret_cast<char*>(digest), BLAKE3_OUT_LEN));

  return cert;
}

bool MembershipManager::VerifyCert(const proto::ShardMembershipCert &cert) {
  // Recompute BLAKE3 digest and compare.
  blake3_hasher hasher;
  blake3_hasher_init(&hasher);
  uint64_t group_id = cert.group_id();
  uint64_t version = cert.version();
  uint64_t fVal = cert.f();
  uint64_t nVal = cert.n();
  blake3_hasher_update(&hasher, &group_id, sizeof(group_id));
  blake3_hasher_update(&hasher, &version, sizeof(version));
  blake3_hasher_update(&hasher, &fVal, sizeof(fVal));
  blake3_hasher_update(&hasher, &nVal, sizeof(nVal));
  for (const auto &rep : cert.replicas()) {
    uint64_t rid = rep.replica_id();
    blake3_hasher_update(&hasher, &rid, sizeof(rid));
  }
  uint8_t digest[BLAKE3_OUT_LEN];
  blake3_hasher_finalize(&hasher, digest, BLAKE3_OUT_LEN);

  std::string computed(reinterpret_cast<char*>(digest), BLAKE3_OUT_LEN);
  return computed == cert.cert_digest();
}

void MembershipManager::StoreForeignCert(const proto::ShardMembershipCert &cert) {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = certs_.find(cert.group_id());
  if (it != certs_.end()) {
    // Only accept newer versions.
    if (cert.version() <= it->second.version()) {
      return;
    }
  }
  certs_[cert.group_id()] = cert;
}

const proto::ShardMembershipCert* MembershipManager::GetCert(uint64_t group_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = certs_.find(group_id);
  if (it != certs_.end()) {
    return &it->second;
  }
  return nullptr;
}

bool MembershipManager::HasCert(uint64_t group_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  return certs_.find(group_id) != certs_.end();
}

} // namespace pequinstore
