import Domain
import Testing

@Test("Rect intersection should work")
func rectIntersectionShouldWork() {
    let a = Rect(x: 0, y: 0, width: 100, height: 100)
    let b = Rect(x: 80, y: 80, width: 20, height: 20)
    let c = Rect(x: 150, y: 150, width: 20, height: 20)

    #expect(a.intersects(b))
    #expect(!a.intersects(c))
}

@Test("Rect contains point should work")
func rectContainsPointShouldWork() {
    let rect = Rect(x: 10, y: 10, width: 20, height: 20)
    #expect(rect.contains((x: 15, y: 15)))
    #expect(!rect.contains((x: 35, y: 15)))
}
