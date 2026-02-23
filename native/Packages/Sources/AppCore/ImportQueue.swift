import Domain
import Foundation
import TelemetryKit

public actor ImportQueue {
    private var jobs: [UUID: ImportJob] = [:]
    private var orderedIDs: [UUID] = []
    private var continuations: [UUID: AsyncStream<[ImportJob]>.Continuation] = [:]
    private let telemetry: Telemetry

    public init(telemetry: Telemetry = ConsoleTelemetry()) {
        self.telemetry = telemetry
    }

    public func currentJobs() -> [ImportJob] {
        orderedIDs.compactMap { jobs[$0] }
    }

    public func subscribe() -> AsyncStream<[ImportJob]> {
        let id = UUID()
        return AsyncStream { continuation in
            continuations[id] = continuation
            continuation.onTermination = { [weak self] _ in
                Task { await self?.removeContinuation(id) }
            }
            continuation.yield(orderedIDs.compactMap { jobs[$0] })
        }
    }

    public func enqueue(fileURLs: [URL]) {
        for fileURL in fileURLs {
            let job = ImportJob(fileURL: fileURL, status: .queued, progress: 0)
            jobs[job.id] = job
            orderedIDs.append(job.id)
            telemetry.info("Enqueued import job: \(fileURL.lastPathComponent)")
            Task {
                await process(jobID: job.id)
            }
        }
        broadcast()
    }

    private func process(jobID: UUID) async {
        update(jobID: jobID, status: .parsing, progress: 0.2, message: "Parsing")
        try? await Task.sleep(for: .milliseconds(250))

        update(jobID: jobID, status: .parsing, progress: 0.55, message: "Chunking")
        try? await Task.sleep(for: .milliseconds(250))

        update(jobID: jobID, status: .indexed, progress: 1.0, message: "Indexed")
    }

    private func update(jobID: UUID, status: ImportJobStatus, progress: Double, message: String?) {
        guard var job = jobs[jobID] else { return }
        job.status = status
        job.progress = max(0, min(progress, 1))
        job.message = message
        jobs[jobID] = job
        broadcast()
    }

    private func broadcast() {
        let snapshot = orderedIDs.compactMap { jobs[$0] }
        for continuation in continuations.values {
            continuation.yield(snapshot)
        }
    }

    private func removeContinuation(_ id: UUID) {
        continuations[id] = nil
    }
}
