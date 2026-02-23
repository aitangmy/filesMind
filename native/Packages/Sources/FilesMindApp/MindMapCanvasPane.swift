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
                with: .color(isFocused ? Color.accentColor.opacity(0.18) : Color.white.opacity(0.9))
            )
            context.stroke(
                path,
                with: .color(isFocused ? Color.accentColor.opacity(0.9) : Color.black.opacity(0.12)),
                lineWidth: isFocused ? 2.2 : 1
            )

            let title = Text(node.title)
                .font(.system(size: max(11, DesignTypography.body * zoom * 0.8), weight: .medium))
                .foregroundStyle(isFocused ? Color.accentColor : Color.primary)
            context.draw(title, at: CGPoint(x: rect.midX, y: rect.midY), anchor: .center)
        }
    }
}
