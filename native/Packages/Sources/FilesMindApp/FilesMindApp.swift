import AppCore
import Foundation
import SwiftUI

@main
struct FilesMindApp: App {
    @State private var model = AppModel(container: AppBootstrap.makeDefault(installRoot: FilesMindPaths.modelsRootURL))

    var body: some Scene {
        WindowGroup {
            WorkspaceShellView(model: model)
                .frame(minWidth: 1180, minHeight: 760)
                .onAppear {
                    model.start()
                }
        }
        .windowStyle(.titleBar)
        .defaultSize(width: 1320, height: 860)
    }
}

enum FilesMindPaths {
    static var modelsRootURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return base
            .appendingPathComponent("FilesMind", isDirectory: true)
            .appendingPathComponent("Models", isDirectory: true)
    }
}
