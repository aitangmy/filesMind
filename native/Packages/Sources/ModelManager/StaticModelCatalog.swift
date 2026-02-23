import Domain
import Foundation

public struct StaticModelCatalog: ModelCatalogProviding {
    private let models: [ModelDescriptor]

    public init(models: [ModelDescriptor]) {
        self.models = models
    }

    public func fetchManifest() async throws -> [ModelDescriptor] {
        models
    }
}
