import Domain
import Foundation

public actor EnqueueImportUseCase {
    private let queue: ImportQueue

    public init(queue: ImportQueue) {
        self.queue = queue
    }

    public func execute(fileURLs: [URL]) async {
        await queue.enqueue(fileURLs: fileURLs)
    }
}

public actor ObserveImportQueueUseCase {
    private let queue: ImportQueue

    public init(queue: ImportQueue) {
        self.queue = queue
    }

    public func execute() async -> AsyncStream<[ImportJob]> {
        await queue.subscribe()
    }
}
