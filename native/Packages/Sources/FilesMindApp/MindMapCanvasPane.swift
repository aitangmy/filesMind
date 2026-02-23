import DesignSystem
import Domain
import GraphEngine
import SwiftUI

struct MindMapCanvasPane: View {
    @Bindable var model: AppModel

    @State private var pan = CGSize(width: 24, height: 24)
    @State private var zoom: CGFloat = 0.65
    @State private var steadyPan = CGSize(width: 24, height: 24)
    @State private var steadyZoom: CGFloat = 0.65

    var body: some View {
        GeometryReader { proxy in
            let viewport = worldViewport(for: proxy.size)
            let visibleNodes = model.visibleGraphNodes(in: viewport)

            ZStack(alignment: .topLeading) {
                Canvas { context, size in
                    drawBackgroundGrid(context: &context, size: size)
                    drawNodes(context: &context, nodes: visibleNodes)
                }
                .background(
                    LinearGradient(
                        colors: [
                            Color(nsColor: .windowBackgroundColor),
                            Color(nsColor: .underPageBackgroundColor)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .gesture(panGesture.simultaneously(with: zoomGesture))

                HStack(spacing: DesignSpacing.x2) {
                    Label("Visible: \(visibleNodes.count)", systemImage: "scope")
                    Label("Total: \(model.graphNodes.count)", systemImage: "point.3.connected.trianglepath.dotted")
                    Label(String(format: "Zoom: %.2fx", zoom), systemImage: "plus.magnifyingglass")
                }
                .font(.system(size: DesignTypography.caption, weight: .medium))
                .padding(.horizontal, DesignSpacing.x3)
                .padding(.vertical, DesignSpacing.x2)
                .background(.regularMaterial, in: Capsule())
                .padding(DesignSpacing.x4)

                if model.importedDocuments.isEmpty {
                    OnboardingCard()
                        .padding(.top, 98)
                        .padding(.leading, DesignSpacing.x4)
                        .transition(.opacity.combined(with: .scale(scale: 0.98)))
                }
            }
        }
        .overlay(alignment: .bottomTrailing) {
            Button("Reset View") {
                withAnimation(.spring(response: DesignMotion.regular, dampingFraction: 0.86)) {
                    pan = CGSize(width: 24, height: 24)
                    zoom = 0.65
                    steadyPan = pan
                    steadyZoom = zoom
                }
            }
            .buttonStyle(.bordered)
            .padding(DesignSpacing.x4)
        }
    }

    private var panGesture: some Gesture {
        DragGesture(minimumDistance: 1)
            .onChanged { value in
                pan = CGSize(
                    width: steadyPan.width + value.translation.width,
                    height: steadyPan.height + value.translation.height
                )
            }
            .onEnded { _ in
                steadyPan = pan
            }
    }

    private var zoomGesture: some Gesture {
        MagnifyGesture()
            .onChanged { value in
                zoom = max(0.2, min(2.5, steadyZoom * value.magnification))
            }
            .onEnded { _ in
                steadyZoom = zoom
            }
    }

    private func worldViewport(for size: CGSize) -> Rect {
        let worldX = Double(-pan.width / zoom)
        let worldY = Double(-pan.height / zoom)
        let worldWidth = Double(size.width / zoom)
        let worldHeight = Double(size.height / zoom)
        return Rect(x: worldX, y: worldY, width: worldWidth, height: worldHeight)
    }

    private func drawBackgroundGrid(context: inout GraphicsContext, size: CGSize) {
        let gridStep: CGFloat = 48
        let color = Color.gray.opacity(0.16)

        for x in stride(from: CGFloat(0), through: size.width, by: gridStep) {
            let path = Path { p in
                p.move(to: CGPoint(x: x, y: 0))
                p.addLine(to: CGPoint(x: x, y: size.height))
            }
            context.stroke(path, with: .color(color), lineWidth: 0.6)
        }

        for y in stride(from: CGFloat(0), through: size.height, by: gridStep) {
            let path = Path { p in
                p.move(to: CGPoint(x: 0, y: y))
                p.addLine(to: CGPoint(x: size.width, y: y))
            }
            context.stroke(path, with: .color(color), lineWidth: 0.6)
        }
    }

    private func drawNodes(context: inout GraphicsContext, nodes: [GraphNode]) {
        let isOnboardingState = model.importedDocuments.isEmpty
        for node in nodes {
            let rect = CGRect(
                x: node.rect.x * zoom + pan.width,
                y: node.rect.y * zoom + pan.height,
                width: node.rect.width * zoom,
                height: node.rect.height * zoom
            )

            let rounded = RoundedRectangle(cornerRadius: DesignCornerRadius.small)
            let path = rounded.path(in: rect)
            let isFocused = node.id == model.focusedGraphNodeID
            context.fill(
                path,
                with: .color(fillColor(isFocused: isFocused, isOnboardingState: isOnboardingState))
            )
            context.stroke(
                path,
                with: .color(strokeColor(isFocused: isFocused, isOnboardingState: isOnboardingState)),
                lineWidth: isFocused ? 2.2 : 1
            )

            let title = Text(node.title)
                .font(.system(size: max(11, DesignTypography.body * zoom * 0.8), weight: .medium))
                .foregroundStyle(titleColor(isFocused: isFocused, isOnboardingState: isOnboardingState))
            context.draw(title, at: CGPoint(x: rect.midX, y: rect.midY), anchor: .center)
        }
    }

    private func fillColor(isFocused: Bool, isOnboardingState: Bool) -> Color {
        if isFocused {
            return Color.accentColor.opacity(0.18)
        }
        return isOnboardingState ? Color.white.opacity(0.82) : Color.white.opacity(0.92)
    }

    private func strokeColor(isFocused: Bool, isOnboardingState: Bool) -> Color {
        if isFocused {
            return Color.accentColor.opacity(0.9)
        }
        return isOnboardingState ? Color.black.opacity(0.2) : Color.black.opacity(0.12)
    }

    private func titleColor(isFocused: Bool, isOnboardingState: Bool) -> Color {
        if isFocused {
            return .accentColor
        }
        return isOnboardingState ? .secondary : .primary
    }
}

private struct OnboardingCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: DesignSpacing.x3) {
            Text("Welcome to filesMind")
                .font(.system(size: DesignTypography.title, weight: .semibold))
            Text("This is the initial workspace canvas. Start from the left sidebar and the graph will be built automatically.")
                .font(.system(size: DesignTypography.body))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: DesignSpacing.x2) {
                stepBadge(index: 1, title: "Choose Workspace")
                stepBadge(index: 2, title: "Import Markdown/PDF")
                stepBadge(index: 3, title: "Search and focus graph nodes")
            }
        }
        .padding(DesignSpacing.x4)
        .frame(maxWidth: 360, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: DesignCornerRadius.large)
                .fill(.thinMaterial)
        )
        .overlay(
            RoundedRectangle(cornerRadius: DesignCornerRadius.large)
                .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
        )
    }

    private func stepBadge(index: Int, title: String) -> some View {
        HStack(spacing: DesignSpacing.x2) {
            Text("\(index)")
                .font(.system(size: DesignTypography.caption, weight: .semibold, design: .rounded))
                .frame(width: 18, height: 18)
                .background(Color.accentColor.opacity(0.18), in: Circle())
                .foregroundStyle(Color.accentColor)
            Text(title)
                .font(.system(size: DesignTypography.body, weight: .medium))
        }
    }
}
