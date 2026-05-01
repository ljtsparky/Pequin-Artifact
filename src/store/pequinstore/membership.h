/***********************************************************************
 *
 * membership.h:
 *   Manages shard membership certificates for cross-shard coordination
 *   in heterogeneous BFT deployments. Each shard publishes a signed
 *   membership certificate listing its replicas' public keys and quorum
 *   thresholds; foreign shards use these certificates to verify
 *   cross-shard snapshot certificates (SS-CERTs) without relying on
 *   shared authority membership (the "sister replica" assumption).
 *
 **********************************************************************/
#ifndef PEQUIN_MEMBERSHIP_H
#define PEQUIN_MEMBERSHIP_H

#include "lib/configuration.h"
#include "lib/keymanager.h"
#include "store/pequinstore/pequin-proto.pb.h"

#include <map>
#include <mutex>

namespace pequinstore {

class MembershipManager {
public:
  MembershipManager() = default;
  ~MembershipManager() = default;

  // Generate this shard's membership certificate from the current
  // configuration and key material. The cert_digest is computed as
  // BLAKE3(group_id || version || f || n || replica_ids...).
  static proto::ShardMembershipCert GenerateCert(
      uint64_t group_id,
      uint64_t version,
      const transport::Configuration *config,
      KeyManager *keyManager);

  // Verify a membership certificate's integrity by recomputing its
  // BLAKE3 digest and comparing against cert_digest.
  static bool VerifyCert(const proto::ShardMembershipCert &cert);

  // Store a foreign shard's membership certificate. Rejects certs with
  // a version <= the currently stored version for the same group.
  void StoreForeignCert(const proto::ShardMembershipCert &cert);

  // Retrieve the stored membership certificate for a given group.
  // Returns nullptr if no cert is stored for that group.
  const proto::ShardMembershipCert* GetCert(uint64_t group_id) const;

  // Check whether we have a cert for the given group.
  bool HasCert(uint64_t group_id) const;

private:
  mutable std::mutex mu_;
  std::map<uint64_t, proto::ShardMembershipCert> certs_;
};

} // namespace pequinstore

#endif // PEQUIN_MEMBERSHIP_H
