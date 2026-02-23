import CryptoKit
import Domain
import Foundation

public struct SHA256ArtifactValidator: ModelArtifactValidating {
    public init() {}

    public func validateArtifact(at url: URL, expectedSHA256: String) async throws {
        let data = try Data(contentsOf: url)
        let digest = SHA256.hash(data: data)
        let checksum = digest.map { String(format: "%02x", $0) }.joined()

        if checksum.lowercased() != expectedSHA256.lowercased() {
            throw FilesMindError.validationFailed("Artifact checksum mismatch")
        }
    }
}
