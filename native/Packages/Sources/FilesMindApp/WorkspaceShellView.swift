import DesignSystem
import Domain
import SwiftUI

struct WorkspaceShellView: View {
    @Bindable var model: AppModel

    var body: some View {
        NavigationSplitView {
            SidebarPane(model: model)
                .frame(minWidth: 250)
        } content: {
            ImportQueuePane(model: model)
                .frame(minWidth: 330)
        } detail: {
            MindMapCanvasPane(model: model)
                .frame(minWidth: 600)
        }
        .navigationTitle("filesMind")
    }
}

private struct SidebarPane: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: DesignSpacing.x4) {
            Text("Workspace")
                .font(.system(size: DesignTypography.hero, weight: .semibold))

            Text(model.workspaceStatus)
                .font(.system(size: DesignTypography.body))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)

            if let workspaceURL = model.workspaceURL {
                Text(workspaceURL.path())
                    .font(.system(size: DesignTypography.caption, weight: .regular, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .textSelection(.enabled)
            }

            if let lastError = model.lastError {
                Text(lastError)
                    .font(.system(size: DesignTypography.body))
                    .foregroundStyle(.red)
                    .lineLimit(3)
            }

            Divider()

            Button("Choose Workspace") {
                model.chooseWorkspace()
            }
            .buttonStyle(.borderedProminent)

            Button("Import Files") {
                model.chooseAndEnqueueImports()
            }
            .buttonStyle(.bordered)

            Spacer(minLength: DesignSpacing.x6)

            VStack(alignment: .leading, spacing: DesignSpacing.x2) {
                Text("Aesthetic Baseline")
                    .font(.system(size: DesignTypography.title, weight: .medium))
                Text("Calm · Precision · Depth · Focus")
                    .font(.system(size: DesignTypography.body))
                    .foregroundStyle(.secondary)
            }
            .padding(DesignSpacing.x3)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: DesignCornerRadius.medium))
        }
        .padding(DesignSpacing.x4)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

private struct ImportQueuePane: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: DesignSpacing.x3) {
            Text("Import Queue")
                .font(.system(size: DesignTypography.hero, weight: .semibold))

            if model.importJobs.isEmpty {
                VStack(alignment: .leading, spacing: DesignSpacing.x2) {
                    Text("No jobs yet")
                        .font(.system(size: DesignTypography.bodyLarge, weight: .medium))
                    Text("Use \"Import Files\" to enqueue Markdown/PDF documents.")
                        .font(.system(size: DesignTypography.body))
                        .foregroundStyle(.secondary)
                }
                .padding(.top, DesignSpacing.x2)
            } else {
                List(model.importJobs) { job in
                    ImportJobRow(job: job)
                }
                .listStyle(.inset)
            }

            Spacer(minLength: 0)
        }
        .padding(DesignSpacing.x4)
        .background(Color(nsColor: .controlBackgroundColor))
    }
}

private struct ImportJobRow: View {
    let job: ImportJob

    var body: some View {
        VStack(alignment: .leading, spacing: DesignSpacing.x2) {
            HStack {
                Text(job.fileURL.lastPathComponent)
                    .font(.system(size: DesignTypography.bodyLarge, weight: .medium))
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(job.status.rawValue.capitalized)
                    .font(.system(size: DesignTypography.caption, weight: .semibold))
                    .foregroundStyle(statusColor)
                    .textCase(.uppercase)
            }

            ProgressView(value: job.progress)
                .tint(statusColor)

            if let message = job.message {
                Text(message)
                    .font(.system(size: DesignTypography.caption))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, DesignSpacing.x1)
    }

    private var statusColor: Color {
        switch job.status {
        case .queued:
            return .gray
        case .parsing:
            return .orange
        case .indexed:
            return .green
        case .failed:
            return .red
        }
    }
}
