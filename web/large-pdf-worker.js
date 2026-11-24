const LIMIT = 200_000_000;
const BLOCK_SIZE = 256 * 1024;
const SAVE_OPTIONS = "garbage=2,compress=yes,compress-images=yes,compress-fonts=yes,objstms=yes";

function openPdf(file, { PDFDocument, Stream }) {
  const reader = new FileReaderSync();
  let start = 0;
  let bytes = new Uint8Array();
  // MuPDF reads small blocks at a time. Cache a window over the file so it
  // never needs to copy the entire input into the JavaScript or WASM heap.
  const stream = new Stream({
    fileSize: () => file.size,
    read(memory, offset, length, position) {
      const end = Math.min(file.size, position + length);
      if (position >= end) return 0;
      if (position < start || end > start + bytes.length) {
        start = position;
        bytes = new Uint8Array(reader.readAsArrayBuffer(file.slice(start, Math.max(end, start + BLOCK_SIZE))));
      }
      memory.set(bytes.subarray(position - start, end - start), offset);
      return end - position;
    },
    close() { bytes = new Uint8Array(); },
  });
  let doc;
  try {
    doc = new PDFDocument(stream);
    if (doc.needsPassword()) throw new Error("Unlock the PDF before using Large PDF Tools.");
    if (!doc.countPages()) throw new Error("Choose a PDF with at least one page.");
    const trailer = doc.getTrailer();
    const signatureFlags = trailer.get("Root", "AcroForm", "SigFlags");
    try {
      if (signatureFlags.asNumber() & 3) {
        throw new Error("This PDF has signature fields. Saving it could invalidate a digital signature.");
      }
    } finally {
      signatureFlags.destroy();
      trailer.destroy();
    }
    return doc;
  } catch (error) {
    doc?.destroy();
    throw error;
  } finally {
    stream.destroy();
  }
}

function readRanges(text, pageCount) {
  return text.split(",").map(part => {
    const match = /^(\d+)(?:\s*-\s*(\d+))?$/.exec(part.trim());
    if (!match) throw new Error("Enter page numbers or ranges like 1-3, 6, 9-12.");
    const start = Number(match[1]);
    const end = Number(match[2] || start);
    if (start < 1 || end < start || end > pageCount) {
      throw new Error(`Choose pages between 1 and ${pageCount}.`);
    }
    return Array.from({ length: end - start + 1 }, (_, index) => start - 1 + index);
  });
}

function save(doc) {
  const output = doc.saveToBuffer(SAVE_OPTIONS);
  try {
    return new Blob([output.asUint8Array()], { type: "application/pdf" });
  } finally {
    output.destroy();
  }
}

function merge(files, engine) {
  const merged = new engine.PDFDocument();
  try {
    for (const file of files) {
      const doc = openPdf(file, engine);
      const graft = merged.newGraftMap();
      try {
        const count = doc.countPages();
        for (let i = 0; i < count; i++) graft.graftPage(-1, doc, i);
      } finally {
        graft.destroy();
        doc.destroy();
      }
    }
    return save(merged);
  } finally {
    merged.destroy();
  }
}

function processDocument({ files, operation, pageRanges, angle }, engine) {
  if (!files.length || files.some(file => file.size === 0) ||
      files.reduce((size, file) => size + file.size, 0) > LIMIT) {
    throw new Error("Choose PDF files totaling no more than 200 MB.");
  }
  if (operation === "merge") return [{ blob: merge(files, engine), name: "merged.pdf" }];
  const [file] = files;
  const base = file.name.replace(/\.pdf$/i, "");
  const doc = openPdf(file, engine);
  try {
    if (operation === "compress") {
      const compressed = save(doc);
      return [{ blob: compressed.size < file.size ? compressed : file, name: `${base}-compressed.pdf` }];
    }
    const count = doc.countPages();
    const groups = pageRanges.trim() ? readRanges(pageRanges, count) : [Array.from({ length: count }, (_, i) => i)];
    const selected = [...new Set(groups.flat())];
    if (operation === "split") {
      if (groups.length < 2 || groups.length > 20) {
        throw new Error("Enter between 2 and 20 comma-separated page ranges to split.");
      }
      if (groups.reduce((length, group) => length + group.length, 0) !== selected.length) {
        throw new Error("Page ranges for splitting must not overlap.");
      }
      return groups.map((group, index) => {
        const part = openPdf(file, engine);
        try {
          part.rearrangePages(group);
          return { blob: save(part), name: `${base}-part-${index + 1}.pdf` };
        } finally {
          part.destroy();
        }
      });
    }
    if (operation === "rotate") {
      for (const index of selected) {
        const page = doc.findPage(index);
        const rotation = page.getInheritable("Rotate");
        try {
          page.put("Rotate", ((rotation.asNumber() + angle) % 360 + 360) % 360);
        } finally {
          rotation.destroy();
          page.destroy();
        }
      }
    } else if (operation === "extract") {
      doc.rearrangePages(selected);
    } else if (operation === "remove") {
      const removed = new Set(selected);
      const keep = Array.from({ length: count }, (_, index) => index).filter(index => !removed.has(index));
      if (!keep.length) throw new Error("Keep at least one page in the PDF.");
      doc.rearrangePages(keep);
    } else {
      throw new Error("Choose a PDF operation.");
    }
    return [{ blob: save(doc), name: `${base}-${operation}.pdf` }];
  } finally {
    doc.destroy();
  }
}

self.onmessage = async ({ data }) => {
  try {
    const engine = await import("/vendor/mupdf-1.28.6/mupdf.js");
    self.postMessage({ results: processDocument(data, engine) });
  } catch (error) {
    self.postMessage({ error: error instanceof Error ? error.message : "This PDF could not be processed." });
  }
};
