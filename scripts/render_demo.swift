import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

guard CommandLine.arguments.count == 3 else {
    fputs("Usage: swift scripts/render_demo.swift <captured-cli-output> <output.gif>\n", stderr)
    exit(2)
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
let mint = "pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn"
let captured = try String(contentsOf: inputURL, encoding: .utf8)
let capturedLines = captured.components(separatedBy: .newlines).filter { !$0.isEmpty }
let warnings = capturedLines.filter { $0.trimmingCharacters(in: .whitespaces).hasPrefix("Warning: ") }
let outputLines = capturedLines.filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("Warning: ") } + warnings
let lines = (["$ solana-token-analyzer \(mint)", ""] + outputLines)
    .map { String($0.prefix(132)) }

let width = 1480
let lineHeight = 25
let topInset = 100
let bottomInset = 48
let height = topInset + max(lines.count, 1) * lineHeight + bottomInset
let gifType = UTType.gif.identifier as CFString
guard let destination = CGImageDestinationCreateWithURL(
    outputURL as CFURL,
    gifType,
    lines.count + 5,
    nil
) else {
    fputs("Could not create GIF at \(outputURL.path)\n", stderr)
    exit(1)
}
CGImageDestinationSetProperties(
    destination,
    [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0]] as CFDictionary
)

func makeFrame(visibleLineCount: Int) -> CGImage {
    let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: width,
        pixelsHigh: height,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    )!
    let graphics = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = graphics

    NSColor(calibratedRed: 0.035, green: 0.047, blue: 0.075, alpha: 1).setFill()
    NSBezierPath(rect: NSRect(x: 0, y: 0, width: width, height: height)).fill()
    NSColor(calibratedRed: 0.075, green: 0.09, blue: 0.13, alpha: 1).setFill()
    NSBezierPath(
        roundedRect: NSRect(x: 26, y: 24, width: width - 52, height: height - 48),
        xRadius: 14,
        yRadius: 14
    ).fill()

    let headerY = height - 72
    for (index, color) in [
        NSColor(calibratedRed: 1, green: 0.36, blue: 0.34, alpha: 1),
        NSColor(calibratedRed: 1, green: 0.75, blue: 0.28, alpha: 1),
        NSColor(calibratedRed: 0.27, green: 0.78, blue: 0.39, alpha: 1),
    ].enumerated() {
        color.setFill()
        NSBezierPath(ovalIn: NSRect(x: 48 + index * 22, y: headerY, width: 12, height: 12)).fill()
    }
    let header = "solana-token-analyzer  •  live CLI demo"
    (header as NSString).draw(
        at: NSPoint(x: 120, y: headerY - 3),
        withAttributes: [
            .font: NSFont.systemFont(ofSize: 16, weight: .medium),
            .foregroundColor: NSColor(calibratedWhite: 0.75, alpha: 1),
        ]
    )

    let textFont = NSFont.monospacedSystemFont(ofSize: 16, weight: .regular)
    let attributes: [NSAttributedString.Key: Any] = [
        .font: textFont,
        .foregroundColor: NSColor(calibratedRed: 0.83, green: 0.88, blue: 0.94, alpha: 1),
    ]
    for index in 0..<min(visibleLineCount, lines.count) {
        let y = height - topInset - (index + 1) * lineHeight
        (lines[index] as NSString).draw(at: NSPoint(x: 50, y: y), withAttributes: attributes)
    }

    NSGraphicsContext.restoreGraphicsState()
    return bitmap.cgImage!
}

func addFrame(_ image: CGImage, delay: Double) {
    CGImageDestinationAddImage(
        destination,
        image,
        [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFDelayTime: delay]] as CFDictionary
    )
}

for visibleCount in 1...max(lines.count, 1) {
    addFrame(makeFrame(visibleLineCount: visibleCount), delay: 0.20)
}
for _ in 0..<5 {
    addFrame(makeFrame(visibleLineCount: lines.count), delay: 0.5)
}

guard CGImageDestinationFinalize(destination) else {
    fputs("Could not finalize GIF at \(outputURL.path)\n", stderr)
    exit(1)
}
print("Wrote \(outputURL.path) (\(lines.count) transcript lines)")
