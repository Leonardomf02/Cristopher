// OCR nativo do macOS (Vision). Muito melhor em recibos PT do que o tesseract em
// inglês e não precisa de instalar nada. Uso: ocr <ficheiro> [--json]
import Foundation
import Vision
import AppKit
import PDFKit

func cgImage(_ path: String) -> CGImage? {
    let url = URL(fileURLWithPath: path)
    if path.lowercased().hasSuffix(".pdf") {
        guard let doc = PDFDocument(url: url), let page = doc.page(at: 0) else { return nil }
        let rect = page.bounds(for: .mediaBox)
        let escala: CGFloat = 2.0
        let img = NSImage(size: CGSize(width: rect.width * escala, height: rect.height * escala))
        img.lockFocus()
        NSColor.white.setFill()
        NSRect(origin: .zero, size: img.size).fill()
        if let ctx = NSGraphicsContext.current?.cgContext {
            ctx.scaleBy(x: escala, y: escala)
            page.draw(with: .mediaBox, to: ctx)
        }
        img.unlockFocus()
        var proposta = NSRect(origin: .zero, size: img.size)
        return img.cgImage(forProposedRect: &proposta, context: nil, hints: nil)
    }
    guard let img = NSImage(contentsOf: url) else { return nil }
    var proposta = NSRect(origin: .zero, size: img.size)
    return img.cgImage(forProposedRect: &proposta, context: nil, hints: nil)
}

let args = CommandLine.arguments
guard args.count > 1, let imagem = cgImage(args[1]) else {
    FileHandle.standardError.write("não consegui abrir a imagem\n".data(using: .utf8)!)
    exit(2)
}

let pedido = VNRecognizeTextRequest()
pedido.recognitionLevel = .accurate
pedido.usesLanguageCorrection = true
pedido.recognitionLanguages = ["pt-PT", "en-US"]

do {
    try VNImageRequestHandler(cgImage: imagem, options: [:]).perform([pedido])
} catch {
    FileHandle.standardError.write("falhou o OCR: \(error)\n".data(using: .utf8)!)
    exit(3)
}

// O Vision devolve blocos soltos: label e valor de um recibo saem separados. Junta
// por linha (y parecido) e ordena da esquerda para a direita para o texto ficar
// legível como no papel.
struct Bloco { let texto: String; let x: CGFloat; let y: CGFloat; let altura: CGFloat }
let blocos: [Bloco] = (pedido.results ?? []).compactMap { obs in
    guard let t = obs.topCandidates(1).first?.string else { return nil }
    let c = obs.boundingBox
    return Bloco(texto: t, x: c.minX, y: c.midY, altura: c.height)
}
var linhas: [[Bloco]] = []
for b in blocos.sorted(by: { $0.y > $1.y }) {
    let tolerancia = max(b.altura * 0.6, 0.008)
    if let i = linhas.indices.last, let ref = linhas[i].first, abs(ref.y - b.y) <= tolerancia {
        linhas[i].append(b)
    } else {
        linhas.append([b])
    }
}
let texto = linhas.map { linha in
    linha.sorted(by: { $0.x < $1.x }).map(\.texto).joined(separator: "   ")
}.joined(separator: "\n")
print(texto)
