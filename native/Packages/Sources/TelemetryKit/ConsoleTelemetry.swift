import Domain
import Foundation

public final class ConsoleTelemetry: Telemetry, @unchecked Sendable {
    public init() {}

    public func info(_ message: String) {
        print("[INFO] \(message)")
    }

    public func warning(_ message: String) {
        print("[WARN] \(message)")
    }

    public func error(_ message: String) {
        print("[ERROR] \(message)")
    }
}
