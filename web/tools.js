"use strict";
// PageBurrow: the tools home page and the page for each tool.
// Files are sent only to the PageBurrow program on this device (or, with phone access,
// to the computer running it); nothing goes to the internet.
(() => {
  const $ = id => document.getElementById(id);
  function make(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value == null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "style") node.style.cssText = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (key === "dataset") Object.assign(node.dataset, value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    node.append(...children.flat().filter(c => c != null && c !== false));
    return node;
  }
  const HEAD = { "X-Local-Editor": "1" };
  const formatSize = bytes => bytes >= 1e6 ? (bytes / 1e6).toFixed(bytes >= 1e7 ? 0 : 1) + " MB" : Math.max(1, Math.round(bytes / 1e3)) + " KB";

  async function post(path, data) {
    const response = await fetch(path, { method: "POST", headers: { ...HEAD, "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}), cache: "no-store" });
    const json = response.headers.get("Content-Type")?.includes("application/json");
    if (!response.ok) throw new Error(json ? (await response.json()).error : "PageBurrow is not reachable. Check that it is still running.");
    return json ? response.json() : response.blob();
  }

  function upload(file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload");
      for (const [k, v] of Object.entries(HEAD)) xhr.setRequestHeader(k, v);
      xhr.setRequestHeader("X-File-Name", encodeURIComponent(file.name || "file"));
      xhr.upload.onprogress = e => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onload = () => {
        let body = {};
        try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
        if (xhr.status === 200) resolve(body);
        else reject(new Error(body.error || "The file could not be added."));
      };
      xhr.onerror = () => reject(new Error("The file could not be sent to PageBurrow."));
      xhr.send(file);
    });
  }

  const previews = new Map();
  async function preview(id, page, width) {
    const key = `${id}:${page}:${width}`;
    if (!previews.has(key)) previews.set(key, post("/api/preview", { id, page, width }).then(blob => URL.createObjectURL(blob)));
    return previews.get(key);
  }

  // ---------------- tool definitions ----------------

  const CATS = [
    ["organize", "Organize PDF", "#e0702a"], ["optimize", "Optimize PDF", "#2f9e5b"], ["to", "Convert to PDF", "#3466d1"],
    ["from", "Convert from PDF", "#b97a0e"], ["edit", "Edit PDF", "#7c4ddb"], ["security", "PDF security", "#cf3a57"],
    ["smart", "Smart tools", "#0e8f9a"], ["flow", "Workflows", "#475569"]
  ];
  const ACCEPT = {
    pdf: [".pdf"], image: [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"],
    word: [".docx", ".docm", ".doc", ".odt", ".rtf", ".txt"], powerpoint: [".pptx", ".pptm", ".ppt", ".odp"],
    excel: [".xlsx", ".xlsm", ".xls", ".ods", ".csv"], html: [".html", ".htm"]
  };
  const pages = (label = "Pages", value = "all") => ({ key: "pages", type: "text", label, value, placeholder: "all, odd, even or 1-3, 5, 8-", help: "Use all, odd, even, or page numbers and ranges." });
  const ocrOptions = [{ key: "ocr", type: "check", label: "Read scanned pages with OCR (offline)", value: true }, { key: "languages", type: "langs", label: "Languages of scanned pages", show: v => v.ocr }];
  const office = [{ key: "engine", type: "select", label: "Converter", value: "auto", choices: [["auto", "Best available"], ["builtin", "Built-in (nothing to install)"]], help: "office" }];
  const positions = [["top-left", "Top left"], ["top-center", "Top center"], ["top-right", "Top right"], ["middle-left", "Middle left"], ["center", "Center"],
    ["middle-right", "Middle right"], ["bottom-left", "Bottom left"], ["bottom-center", "Bottom center"], ["bottom-right", "Bottom right"]];
  const families = [["sans", "Sans-serif (Helvetica)"], ["serif", "Serif (Times)"], ["mono", "Monospace (Courier)"]];

  const TOOLS = [
    { id: "merge", cat: "organize", icon: "⊕", name: "Merge PDF", desc: "Combine PDFs and images into one PDF, in the order you choose.", accept: ["pdf", "image"], min: 2, reorder: true, run: "Merge",
      options: [{ key: "bookmarks", type: "check", label: "Add a bookmark for each file (their own bookmarks are kept)", value: true }] },
    { id: "split", cat: "organize", icon: "✂", name: "Split PDF", desc: "Split by page ranges, every few pages, chosen pages or file size.", accept: ["pdf"], max: 1, run: "Split",
      options: [{ key: "mode", type: "segmented", label: "Split by", value: "ranges", choices: [["ranges", "Ranges"], ["fixed", "Every N pages"], ["extract", "Pages"], ["size", "File size"]] },
        { key: "ranges", type: "text", label: "Ranges, one file each", value: "1-2, 3-", placeholder: "e.g. 1-3, 4-6, 7-", show: v => v.mode === "ranges" },
        { key: "every", type: "number", label: "Pages per file", value: 1, min: 1, max: 10000, show: v => v.mode === "fixed" },
        { key: "pages", type: "text", label: "Pages to extract", value: "all", placeholder: "all or 1, 3-5", show: v => v.mode === "extract" },
        { key: "merge", type: "check", label: "Put them all in one PDF", value: false, show: v => v.mode === "ranges" || v.mode === "extract" },
        { key: "max_mb", type: "number", label: "Largest file size (MB)", value: 5, min: 0.05, max: 2000, step: 0.05, show: v => v.mode === "size" }] },
    { id: "remove_pages", cat: "organize", icon: "−", name: "Remove pages", desc: "Delete pages you do not need: click them or type their numbers.", accept: ["pdf"], max: 1, custom: "pagepick", run: "Remove pages",
      options: [{ key: "pages", type: "text", label: "Pages to remove", value: "", placeholder: "e.g. 2, 5-7" }] },
    { id: "extract_pages", cat: "organize", icon: "⇱", name: "Extract pages", desc: "Copy chosen pages into a new PDF.", accept: ["pdf"], max: 1, custom: "pagepick", run: "Extract pages",
      options: [{ key: "pages", type: "text", label: "Pages to extract", value: "", placeholder: "e.g. 1, 3-4" }, { key: "separate", type: "check", label: "One PDF per page", value: false }] },
    { id: "organize", cat: "organize", icon: "▦", name: "Organize PDF", desc: "Reorder, rotate, delete and add pages, also from several files.", accept: ["pdf", "image"], custom: "organize", run: "Save PDF", options: [] },
    { id: "scan", cat: "organize", icon: "◳", name: "Scan to PDF", desc: "Photograph documents with a phone, straighten and clean them into a PDF.", accept: ["image"], camera: true, custom: "scan", run: "Create PDF",
      options: [{ key: "filter", type: "select", label: "Look", value: "document", choices: [["document", "Clean document (recommended)"], ["bw", "Black and white"], ["gray", "Greyscale"], ["color", "Original colors"]] },
        { key: "page", type: "select", label: "Page size", value: "a4", choices: [["a4", "A4"], ["letter", "Letter"], ["fit", "Same as the photo"]] }] },
    { id: "compress", cat: "optimize", icon: "⇲", name: "Compress PDF", desc: "Make PDFs smaller than a size you choose.", accept: ["pdf"], run: "Compress",
      options: [{ key: "target", type: "number", label: "Maximum size per file (MB)", value: 1, min: 0.01, max: 4000, step: 0.01 },
        { key: "mode", type: "select", label: "Compression", value: "jpeg", choices: [["jpeg", "Allow JPEG for pictures (smaller)"], ["lossless", "Lossless (pictures unchanged)"]] },
        { key: "page", type: "select", label: "Page size", value: "original", choices: [["original", "Keep the original size"], ["a4", "Fit pages to A4"]] }] },
    { id: "repair", cat: "optimize", icon: "✚", name: "Repair PDF", desc: "Rescue damaged PDFs and see exactly what was fixed.", accept: ["pdf"], run: "Repair", options: [] },
    { id: "ocr", cat: "optimize", icon: "Aa", name: "OCR PDF", desc: "Make scans searchable and selectable. The pages look exactly the same.", accept: ["pdf"], run: "Make searchable",
      options: [{ key: "languages", type: "langs", label: "Languages in the document" },
        { key: "dpi", type: "select", label: "Accuracy", value: "300", choices: [["200", "Fast"], ["300", "Recommended"], ["400", "Small print"]] },
        { key: "auto_rotate", type: "check", label: "Turn sideways or upside-down pages automatically", value: true },
        { key: "skip_text", type: "check", label: "Skip pages that already have text", value: true }] },
    { id: "images_to_pdf", cat: "to", icon: "JPG", name: "JPG to PDF", desc: "Turn photos and images into a PDF. JPEGs keep their full quality.", accept: ["image"], reorder: true, run: "Convert",
      options: [{ key: "page", type: "select", label: "Page size", value: "a4", choices: [["a4", "A4"], ["letter", "Letter"], ["fit", "Same as the image"]] },
        { key: "orientation", type: "segmented", label: "Orientation", value: "auto", choices: [["auto", "Auto"], ["portrait", "Portrait"], ["landscape", "Landscape"]], show: v => v.page !== "fit" },
        { key: "margin", type: "segmented", label: "Margin", value: "none", choices: [["none", "None"], ["small", "Small"], ["big", "Big"]] },
        { key: "separate", type: "check", label: "One PDF per image", value: false }] },
    { id: "word_to_pdf", cat: "to", icon: "W", name: "Word to PDF", desc: "Convert Word documents (DOCX, and DOC with LibreOffice) to PDF.", accept: ["word"], run: "Convert", options: office },
    { id: "powerpoint_to_pdf", cat: "to", icon: "P", name: "PowerPoint to PDF", desc: "Convert PowerPoint slides to PDF.", accept: ["powerpoint"], run: "Convert", options: office },
    { id: "excel_to_pdf", cat: "to", icon: "X", name: "Excel to PDF", desc: "Convert spreadsheets (XLSX, CSV) to PDF.", accept: ["excel"], run: "Convert", options: office },
    { id: "html_to_pdf", cat: "to", icon: "</>", name: "HTML to PDF", desc: "Save a web page or HTML file as PDF, using the browser on this computer.", accept: ["html"], optionalFiles: true, run: "Convert",
      options: [{ key: "url", type: "text", label: "Web address", value: "", placeholder: "https://example.com", help: "Or choose .html files on the left." },
        { key: "paper", type: "select", label: "Paper", value: "a4", choices: [["a4", "A4"], ["letter", "Letter"], ["legal", "Legal"], ["a3", "A3"]] },
        { key: "orientation", type: "segmented", label: "Orientation", value: "portrait", choices: [["portrait", "Portrait"], ["landscape", "Landscape"]] },
        { key: "margin", type: "segmented", label: "Margins", value: "small", choices: [["none", "None"], ["small", "Small"], ["normal", "Normal"]] },
        { key: "background", type: "check", label: "Include background colors and images", value: true }] },
    { id: "pdf_to_images", cat: "from", icon: "JPG", name: "PDF to JPG", desc: "Save pages as JPG or PNG images, or pull out the pictures inside.", accept: ["pdf"], run: "Convert",
      options: [{ key: "mode", type: "segmented", label: "Make", value: "pages", choices: [["pages", "Page images"], ["extract", "Pictures inside"]] },
        { key: "format", type: "segmented", label: "Format", value: "jpg", choices: [["jpg", "JPG"], ["png", "PNG"]], show: v => v.mode === "pages" },
        { key: "dpi", type: "select", label: "Resolution", value: "150", choices: [["72", "72 dpi (screen)"], ["150", "150 dpi (recommended)"], ["300", "300 dpi (print)"], ["600", "600 dpi"]], show: v => v.mode === "pages" },
        { key: "quality", type: "range", label: "JPG quality", value: 90, min: 30, max: 100, show: v => v.mode === "pages" && v.format === "jpg" },
        pages()] },
    { id: "pdf_to_word", cat: "from", icon: "W", name: "PDF to Word", desc: "Editable Word file with fonts, images and tables; scans read with OCR.", accept: ["pdf"], run: "Convert", options: ocrOptions },
    { id: "pdf_to_powerpoint", cat: "from", icon: "P", name: "PDF to PowerPoint", desc: "One slide per page, with editable text boxes.", accept: ["pdf"], run: "Convert", options: [] },
    { id: "pdf_to_excel", cat: "from", icon: "X", name: "PDF to Excel", desc: "Tables become spreadsheet sheets with real numbers.", accept: ["pdf"], run: "Convert", options: ocrOptions },
    { id: "pdfa", cat: "from", icon: "A", name: "PDF to PDF/A", desc: "Prepare PDFs for long-term archiving (PDF/A-2b).", accept: ["pdf"], run: "Convert", options: [] },
    { id: "pdf_to_markdown", cat: "from", icon: "MD", name: "PDF to Markdown", desc: "Headings, lists, tables, links and code as Markdown text.", accept: ["pdf"], run: "Convert",
      options: [{ key: "images", type: "check", label: "Include pictures (download is a .zip)", value: false }, { key: "page_breaks", type: "check", label: "Mark page breaks", value: false }, ...ocrOptions] },
    { id: "edit", cat: "edit", icon: "✎", name: "Edit PDF", desc: "Change existing text, add text, images, shapes and drawings, erase text from scans.", editor: true },
    { id: "rotate", cat: "edit", icon: "↻", name: "Rotate PDF", desc: "Turn all, odd, even or chosen pages.", accept: ["pdf"], run: "Rotate",
      options: [{ key: "angle", type: "segmented", label: "Turn", value: "90", choices: [["90", "90° right"], ["180", "180°"], ["270", "90° left"]] }, pages()] },
    { id: "page_numbers", cat: "edit", icon: "#", name: "Page numbers", desc: "Number pages in any position, format and language.", accept: ["pdf"], run: "Add page numbers",
      options: [{ key: "position", type: "select", label: "Position", value: "bottom-center", choices: positions.filter(p => !/middle|^center/.test(p[0])) },
        { key: "format", type: "select", label: "Number format", value: "{n}", choices: [["{n}", "1"], ["Page {n}", "Page 1"], ["Page {n} of {p}", "Page 1 of 9"], ["{n} / {p}", "1 / 9"], ["- {n} -", "- 1 -"], ["custom", "Custom…"]] },
        { key: "custom", type: "text", label: "Custom text", value: "पृष्ठ {n}", help: "{n} page number, {p} total pages, {r} pages numbered, {rf} last number.", show: v => v.format === "custom" },
        { key: "first", type: "number", label: "First number", value: 1, min: -100000, max: 1000000 }, pages("Pages to number"),
        { key: "layout", type: "segmented", label: "Layout", value: "single", choices: [["single", "Single pages"], ["facing", "Book (facing)"]] },
        { key: "cover", type: "check", label: "First page is a cover (right-hand page)", value: true, show: v => v.layout === "facing" },
        { key: "margin", type: "segmented", label: "Margin", value: "medium", choices: [["small", "Small"], ["medium", "Medium"], ["big", "Big"]] },
        { key: "family", type: "select", label: "Font", value: "sans", choices: families },
        { key: "size", type: "number", label: "Size (pt)", value: 11, min: 5, max: 96, half: true }, { key: "color", type: "color", label: "Color", value: "#000000", half: true },
        { key: "bold", type: "check", label: "Bold", value: false }, { key: "opacity", type: "range", label: "Opacity", value: 100, min: 10, max: 100, unit: "%" }] },
    { id: "watermark", cat: "edit", icon: "≋", name: "Watermark", desc: "Stamp text or an image at any angle, position or opacity.", accept: ["pdf"], custom: "watermark", run: "Add watermark",
      options: [{ key: "type", type: "segmented", label: "Watermark", value: "text", choices: [["text", "Text"], ["image", "Image"]] },
        { key: "text", type: "text", label: "Text", value: "CONFIDENTIAL", show: v => v.type === "text" },
        { key: "family", type: "select", label: "Font", value: "sans", choices: families, show: v => v.type === "text" },
        { key: "size", type: "number", label: "Size (pt)", value: 48, min: 4, max: 400, half: true, show: v => v.type === "text" },
        { key: "color", type: "color", label: "Color", value: "#d0021b", half: true, show: v => v.type === "text" },
        { key: "bold", type: "check", label: "Bold", value: true, show: v => v.type === "text" }, { key: "italic", type: "check", label: "Italic", value: false, show: v => v.type === "text" },
        { key: "scale", type: "range", label: "Image width", value: 40, min: 5, max: 100, unit: "% of the page", show: v => v.type === "image" },
        { key: "position", type: "select", label: "Position", value: "center", choices: [...positions, ["mosaic", "Mosaic (repeat across the page)"]] },
        { key: "angle", type: "range", label: "Rotation", value: 45, min: -180, max: 180, unit: "°" },
        { key: "opacity", type: "range", label: "Opacity", value: 40, min: 5, max: 100, unit: "%" },
        { key: "layer", type: "segmented", label: "Layer", value: "over", choices: [["over", "Over the content"], ["under", "Below the content"]] }, pages()] },
    { id: "crop", cat: "edit", icon: "⌗", name: "Crop PDF", desc: "Trim margins automatically or keep the area you draw.", accept: ["pdf"], custom: "crop", run: "Crop",
      options: [{ key: "mode", type: "segmented", label: "Crop", value: "auto", choices: [["auto", "To the content"], ["area", "Draw an area"], ["margins", "Margins"]] },
        { key: "padding", type: "number", label: "Space around the content (pt)", value: 8, min: 0, max: 144, show: v => v.mode === "auto" },
        { key: "top", type: "number", label: "Top (mm)", value: 10, min: 0, max: 1000, half: true, show: v => v.mode === "margins" },
        { key: "bottom", type: "number", label: "Bottom (mm)", value: 10, min: 0, max: 1000, half: true, show: v => v.mode === "margins" },
        { key: "left", type: "number", label: "Left (mm)", value: 10, min: 0, max: 1000, half: true, show: v => v.mode === "margins" },
        { key: "right", type: "number", label: "Right (mm)", value: 10, min: 0, max: 1000, half: true, show: v => v.mode === "margins" },
        pages(), { key: "remove_outside", type: "check", label: "Delete what is outside (true crop, not only hidden)", value: false }] },
    { id: "forms", cat: "edit", icon: "☑", name: "PDF Forms", desc: "Fill in forms, add fields, or detect them on paper-style forms.", accept: ["pdf"], max: 1, custom: "forms", run: "Save form",
      options: [{ key: "flatten", type: "check", label: "Flatten (make the answers part of the page)", value: false }] },
    { id: "unlock", cat: "security", icon: "🔓︎", name: "Unlock PDF", desc: "Remove the password and printing/copying restrictions.", accept: ["pdf"], run: "Unlock", options: [], hint: "Files with a password ask for it when you add them." },
    { id: "protect", cat: "security", icon: "🔒︎", name: "Protect PDF", desc: "Encrypt with AES-256, a password and permissions.", accept: ["pdf"], run: "Protect",
      options: [{ key: "password", type: "password", label: "Password to open the PDF", value: "" }, { key: "confirm", type: "password", label: "Repeat the password", value: "" },
        { key: "allow", type: "checks", label: "Allowed without the owner password", value: ["print", "copy", "edit", "annotate"], choices: [["print", "Printing"], ["copy", "Copying text"], ["edit", "Changing pages"], ["annotate", "Comments and forms"]] },
        { key: "owner_password", type: "password", label: "Owner password (optional)", value: "", help: "Needed to lift the restrictions. Left empty, a random one is used." }] },
    { id: "sign", cat: "security", icon: "✍", name: "Sign PDF", desc: "Draw, type or upload your signature and place it with name and date.", accept: ["pdf"], max: 1, custom: "sign", run: "Sign", options: [] },
    { id: "redact", cat: "security", icon: "▬", name: "Redact PDF", desc: "Permanently remove words, numbers and areas, also on scans.", accept: ["pdf"], max: 1, custom: "redact", run: "Redact",
      options: [{ key: "terms", type: "textarea", label: "Words to remove (one per line)", value: "" },
        { key: "patterns", type: "checks", label: "Also find", value: [], choices: [["email", "Email addresses"], ["phone", "Phone numbers"], ["card", "Card numbers"], ["aadhaar", "Aadhaar numbers"], ["pan", "PAN numbers"]] },
        { key: "match_case", type: "check", label: "Match upper and lower case", value: false }, { key: "whole_words", type: "check", label: "Whole words only", value: true },
        { key: "ocr", type: "check", label: "Search scanned pages with OCR", value: true },
        { key: "pages", type: "text", label: "Whole pages to black out", value: "", placeholder: "e.g. 3, 5" },
        { key: "color", type: "color", label: "Box color", value: "#000000" },
        { key: "clean", type: "check", label: "Remove metadata, hidden text, attachments and scripts", value: true },
        { key: "remove_annotations", type: "check", label: "Remove comments", value: true }] },
    { id: "compare", cat: "security", icon: "≠", name: "Compare PDF", desc: "See text and visual differences in a downloadable report.", accept: ["pdf"], min: 2, max: 2, reorder: true, run: "Compare",
      labels: ["Original", "Changed"], options: [{ key: "mode", type: "segmented", label: "Compare", value: "both", choices: [["both", "Text and look"], ["text", "Text"], ["visual", "Look"]] }] },
    { id: "summarize", cat: "smart", icon: "Σ", name: "Summarize PDF", desc: "Pick the key sentences and terms, offline.", accept: ["pdf"], max: 1, run: "Summarize",
      options: [{ key: "length", type: "segmented", label: "Length", value: "medium", choices: [["short", "Short"], ["medium", "Medium"], ["long", "Long"]] }, ...ocrOptions] },
    { id: "translate", cat: "smart", icon: "文", name: "Translate PDF", desc: "Translate text in place, keeping the layout, with your browser's on-device translation.", accept: ["pdf"], max: 1, custom: "translate", run: "Translate", options: [] },
    { id: "workflow", cat: "flow", icon: "⛓", name: "Workflows", desc: "Chain tools and save them, e.g. merge → number → compress → protect.", accept: ["pdf"], reorder: true, custom: "workflow", run: "Run workflow", options: [] }
  ];
  const TOOL = Object.fromEntries(TOOLS.map(t => [t.id, t]));
  const color = cat => CATS.find(c => c[0] === cat)?.[2] || "#147552";

  // ---------------- state ----------------

  const st = { tool: null, files: [], assets: [], info: null, custom: null, carry: null, url: null, running: false, results: [], preview: null, previewBox: null };
  // Tools whose result keeps the pages of the one PDF it was made from, in the same order:
  // their preview can show the original page instead of, or next to, the result.
  const COMPARABLE = new Set(["rotate", "page_numbers", "watermark", "crop", "forms", "sign", "redact", "compress", "ocr", "pdfa",
    "protect", "unlock", "translate", "repair", "workflow"]);
  const narrow = matchMedia("(max-width: 860px)");
  const view = {
    welcome: $("welcome"), toolView: $("tool-view"), work: $("work"), grid: $("tool-grid"), search: $("tool-search"),
    name: $("tool-name"), desc: $("tool-desc"), icon: $("tool-icon"), drop: $("tool-drop"), dropTitle: $("tool-drop-title"),
    choose: $("tool-choose"), camera: $("tool-camera"), accept: $("tool-accept"), input: $("tool-files"), capture: $("tool-capture"),
    list: $("tool-file-list"), custom: $("tool-custom"), form: $("tool-form"), options: $("tool-options"), run: $("tool-run"),
    working: $("tool-working"), result: $("tool-result"), error: $("tool-error"), home: $("home-button"),
    main: document.querySelector(".tool-main")
  };
  post("/api/tools-info").then(info => { st.info = info; if (st.tool) renderOptions(); }).catch(() => {});

  function error(message = "") {
    view.error.textContent = message;
    view.error.hidden = !message;
  }

  // ---------------- home ----------------

  function renderHome() {
    const query = view.search.value.trim().toLowerCase();
    view.grid.replaceChildren();
    let shown = 0;
    for (const [cat, label] of CATS) {
      const tools = TOOLS.filter(t => t.cat === cat && (!query || (t.name + " " + t.desc).toLowerCase().includes(query)));
      if (!tools.length) continue;
      shown += tools.length;
      view.grid.append(make("section", { class: "tool-cat" }, make("h2", { text: label }),
        make("div", { class: "tool-cards" }, tools.map(t => make("button", { class: "tool-card", type: "button", onclick: () => go(t) },
          make("span", { class: "tool-icon", style: `--cat:${color(t.cat)}`, "aria-hidden": "true", text: t.icon }),
          make("strong", { text: t.name }), make("small", { text: t.desc }))))));
    }
    if (!shown) view.grid.append(make("p", { class: "tool-empty", text: "No tool matches. Try another word." }));
  }
  view.search.addEventListener("input", renderHome);

  function go(tool) {
    if (tool.editor) {
      $("pdf-file").click();
      return;
    }
    location.hash = tool.id;
  }

  function showHome() {
    closeTool();
    view.welcome.hidden = false;
    view.toolView.hidden = view.work.hidden = true;
    view.home.hidden = true;
    document.title = "PageBurrow";
    renderHome();
  }

  function route() {
    const hash = decodeURIComponent(location.hash.slice(1));
    if (hash === "edit") {
      if (typeof state === "undefined" || !state.token) history.replaceState(null, "", "#");
      else return;
    }
    if (typeof state !== "undefined" && state.token) {
      if (!leaveEditor()) {
        history.pushState(null, "", "#edit");
        return;
      }
    }
    const tool = TOOL[hash];
    if (tool && !tool.editor) openTool(tool);
    else showHome();
  }
  window.addEventListener("hashchange", route);
  view.home.addEventListener("click", () => { location.hash = ""; });

  // ---------------- a tool page ----------------

  function clearPreview() {
    st.preview?.destroy();
    st.previewBox?.remove();
    st.preview = st.previewBox = null;
    if (st.results.length) post("/api/forget", { ids: st.results }).catch(() => {});
    st.results = [];
  }

  // Wide screens: the preview fills the left column, next to the Download button.
  // Phones: it sits in the result, just above the Download button.
  function placePreview() {
    if (!st.previewBox) return;
    if (narrow.matches) view.result.insertBefore(st.previewBox, view.result.querySelector(".actions"));
    else view.main.prepend(st.previewBox);
  }
  narrow.addEventListener("change", placePreview);

  function closeTool() {
    clearPreview();
    const ids = [...st.files, ...st.assets].map(f => f.id).filter(Boolean);
    if (ids.length) post("/api/forget", { ids }).catch(() => {});
    st.custom?.destroy?.();
    Object.assign(st, { tool: null, files: [], assets: [], custom: null, running: false });
    if (st.url) URL.revokeObjectURL(st.url);
    st.url = null;
    for (const url of previews.values()) url.then(u => URL.revokeObjectURL(u)).catch(() => {});
    previews.clear();
  }

  function openTool(tool) {
    closeTool();
    st.tool = tool;
    view.welcome.hidden = view.work.hidden = true;
    view.toolView.hidden = false;
    view.home.hidden = false;
    document.title = tool.name + " · PageBurrow";
    view.name.textContent = tool.name;
    view.desc.textContent = tool.desc;
    view.icon.textContent = tool.icon;
    view.icon.style.setProperty("--cat", color(tool.cat));
    const kinds = tool.accept.map(k => ACCEPT[k]).flat();
    view.input.accept = kinds.join(",") + (tool.accept.includes("image") ? ",image/*" : "");
    view.input.multiple = tool.max !== 1;
    view.dropTitle.textContent = tool.max === 1 ? "Choose a file" : "Choose files";
    view.accept.textContent = (tool.hint ? tool.hint + " " : "") + "Accepted: " + kinds.join(" ") + (tool.optionalFiles ? " (optional)" : "");
    view.camera.hidden = !tool.camera;
    view.run.textContent = tool.run;
    view.result.hidden = view.working.hidden = true;
    error();
    view.list.replaceChildren();
    view.custom.replaceChildren();
    renderOptions();
    st.custom = CUSTOM[tool.custom]?.(tool) || null;
    window.scrollTo(0, 0);
    if (st.carry) {
      const file = st.carry;
      st.carry = null;
      addFiles([file]);
    }
  }

  function accepts(tool, file) {
    const name = (file.name || "").toLowerCase();
    return tool.accept.some(k => ACCEPT[k].some(ext => name.endsWith(ext))) || (tool.accept.includes("image") && file.type?.startsWith("image/"))
      || (tool.accept.includes("pdf") && file.type === "application/pdf");
  }

  function addFiles(list) {
    const tool = st.tool;
    error();
    for (const file of list) {
      if (!accepts(tool, file)) {
        error(`${file.name} is not a file this tool accepts.`);
        continue;
      }
      if (tool.max === 1 && st.files.length) removeFile(st.files[0]);
      if (tool.max && st.files.length >= tool.max) {
        error(`This tool takes ${tool.max} files.`);
        break;
      }
      const entry = { file, name: file.name, size: file.size, progress: 0, info: null, id: null, failed: "" };
      st.files.push(entry);
      entry.ready = upload(file, p => { entry.progress = p; drawFile(entry); })
        .then(info => { entry.info = info; entry.id = info.id; drawFile(entry); st.custom?.filesChanged?.(); return info; })
        .catch(e => { entry.failed = e.message; drawFile(entry); });
    }
    renderFiles();
    st.custom?.filesChanged?.();
  }

  function removeFile(entry) {
    st.files = st.files.filter(f => f !== entry);
    if (entry.id) post("/api/forget", { ids: [entry.id] }).catch(() => {});
    renderFiles();
    st.custom?.filesChanged?.();
  }

  function moveFile(entry, step) {
    const i = st.files.indexOf(entry);
    const j = i + step;
    if (j < 0 || j >= st.files.length) return;
    [st.files[i], st.files[j]] = [st.files[j], st.files[i]];
    renderFiles();
    st.custom?.filesChanged?.();
  }

  function renderFiles() {
    view.list.replaceChildren(...st.files.map(entry => entry.row = make("li", { class: "file-item" })));
    st.files.forEach(drawFile);
  }

  function drawFile(entry) {
    const row = entry.row;
    if (!row) return;
    const tool = st.tool;
    const index = st.files.indexOf(entry);
    const info = entry.info;
    const thumb = make("img", { class: "file-thumb", alt: "" });
    if (entry.file.type?.startsWith("image/")) thumb.src = entry.thumb ||= URL.createObjectURL(entry.file);
    else if (info?.kind === "pdf" && info.pages) preview(info.id, 0, 120).then(url => { thumb.src = url; }).catch(() => {});
    const label = tool?.labels?.[index];
    let detail = formatSize(entry.size);
    if (info?.pages) detail += ` · ${info.pages} page${info.pages > 1 ? "s" : ""}`;
    if (info?.damaged) detail += " · damaged";
    const meta = make("div", { class: "file-meta" }, make("strong", { title: entry.name }, label ? make("span", { class: "tag", text: label }) : null, entry.name),
      make("small", { text: entry.failed || detail }));
    if (!info && !entry.failed) meta.append(make("div", { class: "progress" }, make("span", { style: `width:${Math.round(entry.progress * 100)}%` })));
    if (info?.encrypted) {
      const field = make("input", { type: "password", placeholder: "Password", "aria-label": `Password for ${entry.name}` });
      const form = make("form", { onsubmit: async event => {
        event.preventDefault();
        try {
          entry.info = await post("/api/upload-password", { id: info.id, password: field.value });
          drawFile(entry);
          st.custom?.filesChanged?.();
        } catch (e) { error(e.message); }
      } }, field, make("button", { class: "ghost", type: "submit", text: "Use password" }));
      meta.append(make("small", { text: "This PDF has a password." }), form);
    }
    const actions = make("div", { class: "file-actions" });
    if (tool?.reorder || tool?.labels) {
      actions.append(make("button", { type: "button", "aria-label": "Move up", title: "Move up", text: "↑", disabled: index === 0, onclick: () => moveFile(entry, -1) }),
        make("button", { type: "button", "aria-label": "Move down", title: "Move down", text: "↓", disabled: index === st.files.length - 1, onclick: () => moveFile(entry, 1) }));
    }
    actions.append(make("button", { type: "button", "aria-label": `Remove ${entry.name}`, title: "Remove", text: "✕", onclick: () => removeFile(entry) }));
    row.replaceChildren(thumb, meta, actions);
  }

  view.choose.addEventListener("click", () => view.input.click());
  view.camera.addEventListener("click", () => view.capture.click());
  view.input.addEventListener("change", () => { addFiles([...view.input.files]); view.input.value = ""; });
  view.capture.addEventListener("change", () => { addFiles([...view.capture.files]); view.capture.value = ""; });
  view.drop.addEventListener("dragover", e => { e.preventDefault(); view.drop.classList.add("dragging"); });
  view.drop.addEventListener("dragleave", () => view.drop.classList.remove("dragging"));
  view.drop.addEventListener("drop", e => { e.preventDefault(); view.drop.classList.remove("dragging"); addFiles([...e.dataTransfer.files]); });

  // ---------------- options ----------------

  let fields = [];

  function renderOptions(target = view.options, defs = st.tool?.options || [], values = null) {
    if (target === view.options) fields = [];
    target.replaceChildren();
    const store = target === view.options ? fields : [];
    let row = null;
    for (const def of defs) {
      const value = values && def.key in values ? values[def.key] : def.value;
      const field = makeField(def, value);
      store.push(field);
      if (def.half) {
        if (!row) {
          row = make("div", { class: "row2" });
          target.append(row);
        }
        row.append(field.node);
        if (row.children.length === 2) row = null;
      } else {
        row = null;
        target.append(field.node);
      }
    }
    const refresh = () => {
      const current = collect(store);
      for (const f of store) f.node.hidden = f.def.show ? !f.def.show(current) : false;
    };
    target.oninput = target.onchange = refresh;
    refresh();
    return store;
  }

  function makeField(def, value) {
    const id = "opt-" + def.key + "-" + Math.random().toString(36).slice(2, 7);
    const help = def.help === "office" ? officeHelp() : def.help;
    const helpNode = help ? make("small", { id: id + "-help", text: help }) : null;
    const described = help ? id + "-help" : null;
    // The label names the field; help text is linked separately so it is not read as the name.
    const wrap = (input, label = def.label) => make("div", { class: "field" }, make("label", { for: id }, label), input, helpNode);
    let node, read;
    switch (def.type) {
      case "check": {
        const input = make("input", { type: "checkbox", id, checked: !!value });
        node = make("label", { class: "field-check" }, input, make("span", { text: def.label }));
        read = () => input.checked;
        break;
      }
      case "segmented": {
        const name = id;
        const inputs = def.choices.map(([v, label]) => make("label", {}, make("input", { type: "radio", name, value: v, checked: String(value) === v }), label));
        node = make("fieldset", { class: "field", style: "border:0;padding:0;min-width:0" }, make("legend", { text: def.label, style: "padding:0;margin-bottom:5px" }), make("div", { class: "segmented" }, inputs), helpNode);
        read = () => node.querySelector("input:checked")?.value ?? def.value;
        break;
      }
      case "checks": {
        const boxes = def.choices.map(([v, label]) => make("label", { class: "field-check", style: "margin:0" }, make("input", { type: "checkbox", value: v, checked: (value || []).includes(v) }), make("span", { text: label })));
        node = make("fieldset", { class: "field", style: "border:0;padding:0;min-width:0" }, make("legend", { text: def.label, style: "padding:0;margin-bottom:5px" }), make("div", { class: "checks" }, boxes), helpNode);
        read = () => [...node.querySelectorAll("input:checked")].map(i => i.value);
        break;
      }
      case "langs": {
        const installed = st.info?.ocr_languages || [{ code: "eng", name: "English" }];
        const chosen = value || ["eng"];
        const boxes = installed.map(l => make("label", { class: "field-check", style: "margin:0" }, make("input", { type: "checkbox", value: l.code, checked: chosen.includes(l.code) }), make("span", { text: l.name })));
        const available = st.info?.ocr_available || [];
        const select = make("select", { "aria-label": "Language to add" }, available.map(l => make("option", { value: l.code, text: l.name })));
        const add = make("button", { class: "ghost", type: "button", text: "Add", onclick: async () => {
          add.disabled = true;
          add.textContent = "Downloading…";
          try {
            st.info = { ...st.info, ...(await post("/api/ocr-language", { code: select.value })) };
            renderOptions();
          } catch (e) { error(e.message); add.disabled = false; add.textContent = "Add"; }
        } });
        node = make("fieldset", { class: "field", style: "border:0;padding:0;min-width:0" }, make("legend", { text: def.label || "Languages", style: "padding:0;margin-bottom:5px" }),
          make("div", { class: "checks" }, boxes),
          available.length ? make("details", {}, make("summary", { text: "Add a language (downloads 1–15 MB once)", style: "font-weight:500;font-size:13px;cursor:pointer;margin:6px 0" }),
            make("div", { style: "display:flex;gap:6px" }, select, add)) : null);
        read = () => [...node.querySelectorAll(".checks input:checked")].map(i => i.value);
        break;
      }
      case "select": {
        const input = make("select", { id, "aria-describedby": described }, def.choices.map(([v, label]) => make("option", { value: v, text: label, selected: String(value) === v })));
        node = wrap(input);
        read = () => input.value;
        break;
      }
      case "textarea": {
        const input = make("textarea", { id, rows: 3, "aria-describedby": described });
        input.value = value ?? "";
        node = wrap(input);
        read = () => input.value.split(/\n|,/).map(s => s.trim()).filter(Boolean);
        break;
      }
      case "range": {
        const input = make("input", { id, type: "range", min: def.min, max: def.max, value, "aria-describedby": described });
        const out = make("output", { for: id, text: value + (def.unit ? " " + def.unit : "") });
        input.addEventListener("input", () => { out.textContent = input.value + (def.unit ? " " + def.unit : ""); });
        node = make("div", { class: "field" }, make("span", {}, make("label", { for: id }, def.label), ": ", out), input, helpNode);
        read = () => Number(input.value);
        break;
      }
      default: {
        const input = make("input", { id, type: def.type === "number" ? "number" : def.type === "password" ? "password" : def.type === "color" ? "color" : "text",
          min: def.min, max: def.max, step: def.step || (def.type === "number" ? "any" : null), placeholder: def.placeholder,
          autocomplete: def.type === "password" ? "new-password" : "off", "aria-describedby": described });
        input.value = value ?? "";
        node = wrap(input);
        read = () => def.type === "number" ? Number(input.value) : input.value;
      }
    }
    return { def, node, read };
  }

  function officeHelp() {
    if (!st.info) return "";
    return st.info.libreoffice ? "LibreOffice was found on this computer and gives the exact layout."
      : "Install LibreOffice (free) for exact layout and old .doc/.ppt/.xls files; it is then used automatically.";
  }

  function collect(store = fields) {
    const values = {};
    for (const f of store) values[f.def.key] = f.read();
    for (const f of store) if (f.def.show && !f.def.show(values)) delete values[f.def.key];
    return values;
  }

  // ---------------- running ----------------

  async function ready() {
    await Promise.all(st.files.map(f => f.ready));
    const failed = st.files.find(f => f.failed);
    if (failed) throw new Error(`${failed.name}: ${failed.failed}`);
    const locked = st.files.find(f => f.info?.encrypted);
    if (locked) throw new Error(`Enter the password of ${locked.name} first.`);
  }

  async function runTool(tool, ids, options) {
    const response = await fetch("/api/tool", { method: "POST", headers: { ...HEAD, "Content-Type": "application/json" },
      body: JSON.stringify({ tool, files: ids, options }), cache: "no-store" });
    const json = response.headers.get("Content-Type")?.includes("application/json");
    if (!response.ok) throw new Error(json ? (await response.json()).error : "The tool could not finish.");
    if (json) return { meta: await response.json(), blob: null };
    const header = response.headers.get("X-Tool-Result");
    const meta = header ? JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(header), c => c.charCodeAt(0)))) : {};
    return { meta, blob: await response.blob() };
  }

  view.form.addEventListener("submit", async event => {
    event.preventDefault();
    if (st.running) return;
    const tool = st.tool;
    error();
    view.result.hidden = true;
    clearPreview();
    try {
      if (!st.files.length && !tool.optionalFiles) throw new Error(tool.max === 1 ? "Choose a file first." : "Choose files first.");
      if (tool.min && st.files.length < tool.min) throw new Error(`Choose at least ${tool.min} files.`);
      let options = collect();
      if (tool.id === "page_numbers" && options.format === "custom") options.format = options.custom;
      st.running = true;
      view.run.disabled = true;
      view.working.textContent = "Working… OCR and conversions can take a minute.";
      view.working.hidden = false;
      await ready();
      if (st.custom?.run) {
        await st.custom.run(options);
        return;
      }
      options = { ...options, ...(st.custom?.options?.(options) || {}) };
      const ids = [...st.files.map(f => f.id), ...(st.custom?.extraIds?.() || [])];
      const { meta, blob } = await runTool(tool.id, ids, options);
      showResult(meta, blob);
    } catch (e) {
      error(e.message);
    } finally {
      st.running = false;
      view.run.disabled = false;
      view.working.hidden = true;
    }
  });

  function showResult(meta, blob) {
    clearPreview();
    if (st.url) URL.revokeObjectURL(st.url);
    st.url = blob ? URL.createObjectURL(blob) : null;
    const produced = blob ? meta.files || [] : [];
    st.results = produced.map(f => f.id);
    const parts = [make("h2", { text: "Done" })];
    if (meta.message) parts.push(make("p", { text: meta.message }));
    if (produced.length) parts.push(make("p", { class: "preview-hint", text: "Check the preview of the result before you download it." }));
    if (meta.data?.points) {
      parts.push(make("p", { text: "Key points:" }), make("ul", {}, meta.data.points.map(p => make("li", { text: p }))));
      if (meta.data.terms?.length) parts.push(make("p", { text: "Key terms: " + meta.data.terms.join(", ") }));
    }
    if (meta.data?.changes?.length) {
      parts.push(make("ul", {}, meta.data.changes.slice(0, 12).map(c => make("li", { text: `Page ${c.page}: ${c.kind}${c.before ? " “" + c.before + "”" : ""}${c.after ? " → “" + c.after + "”" : ""}` }))));
    }
    if (meta.names?.length) parts.push(make("p", { text: `${meta.names.length} files in one .zip download.` }));
    if (meta.notes?.length) parts.push(make("ul", { class: "notes" }, meta.notes.map(n => make("li", { text: n }))));
    const actions = make("div", { class: "actions" });
    if (blob) {
      actions.append(make("a", { class: "primary button-link", href: st.url, download: meta.name || "result", text: "Download " + (meta.name?.split(".").pop() || "file").toUpperCase() }));
      if (blob.type === "application/pdf") {
        const next = make("select", { "aria-label": "Continue with another tool" },
          make("option", { value: "", text: "Continue with this PDF…" }),
          make("option", { value: "edit", text: "Edit PDF" }),
          TOOLS.filter(t => !t.editor && t.accept?.includes("pdf") && t.id !== st.tool.id).map(t => make("option", { value: t.id, text: t.name })));
        next.addEventListener("change", () => {
          if (!next.value) return;
          const file = new File([blob], meta.name || "result.pdf", { type: "application/pdf" });
          if (next.value === "edit") openPdf(file);
          else {
            st.carry = file;
            location.hash = next.value;
          }
        });
        actions.append(next);
      }
    }
    actions.append(make("button", { class: "ghost", type: "button", text: "Start over", onclick: () => openTool(st.tool) }));
    parts.push(actions);
    view.result.replaceChildren(...parts);
    view.result.hidden = false;
    if (produced.length) {
      const source = st.files.length === 1 && st.files[0].info?.kind === "pdf" && st.files[0].info.pages ? st.files[0] : null;
      const before = produced.length === 1 && source && COMPARABLE.has(st.tool.id) ? { id: source.id } : null;
      st.previewBox = make("div", { class: "result-preview" });
      placePreview();
      st.preview = new ResultPreview(st.previewBox, { files: produced, before, heading: "Preview of the result", fileCount: meta.file_count || produced.length });
      // next to the preview on wide screens (it uses the result's own download link)
      st.preview.bar.append(make("button", { class: "primary rp-download", type: "button", text: "Download",
        onclick: () => view.result.querySelector(".actions a[download]")?.click() }));
    }
    (narrow.matches || !st.previewBox ? view.result : st.previewBox).scrollIntoView({ block: "start", behavior: "smooth" });
  }

  // ---------------- page preview with boxes (crop, sign, redact, forms) ----------------

  class PageView {
    constructor(container, entry, { onDraw = null, label = "" } = {}) {
      this.entry = entry;
      this.page = 0;
      this.items = [];
      this.onDraw = onDraw;
      this.onChange = null;
      this.sheet = make("div", { class: "pv-sheet" });
      this.img = make("img", { alt: label || "Page preview", draggable: "false" });
      this.layer = make("div", { class: "pv-layer" });
      this.region = make("div", { class: "pv-region", hidden: true });
      this.sheet.append(this.img, this.layer, this.region);
      this.counter = make("span");
      this.prev = make("button", { class: "ghost", type: "button", text: "‹ Previous", onclick: () => this.show(this.page - 1) });
      this.next = make("button", { class: "ghost", type: "button", text: "Next ›", onclick: () => this.show(this.page + 1) });
      this.root = make("div", { class: "pv" }, this.sheet, make("div", { class: "pv-nav" }, this.prev, this.counter, this.next));
      container.append(this.root);
      this.sheet.addEventListener("pointerdown", e => this.down(e));
      this.sheet.addEventListener("pointermove", e => this.move(e));
      this.sheet.addEventListener("pointerup", e => this.up(e));
      this.sheet.addEventListener("pointercancel", () => { this.drag = null; this.region.hidden = true; });
      this.show(0);
    }
    get count() { return this.entry.info.pages; }
    get size() { return this.entry.info.sizes[this.page] || this.entry.info.sizes[0]; }
    show(page) {
      this.page = Math.max(0, Math.min(this.count - 1, page));
      const [w, h] = this.size;
      this.sheet.style.aspectRatio = `${w} / ${h}`;
      // The whole page stays in view, so every box and handle can be reached without scrolling.
      this.sheet.style.width = `min(100%, calc(68vh * ${(w / h).toFixed(4)}))`;
      this.img.removeAttribute("src");
      preview(this.entry.id, this.page, 1100).then(url => { if (this.img.isConnected) this.img.src = url; }).catch(() => {});
      this.counter.textContent = `Page ${this.page + 1} of ${this.count}`;
      this.prev.disabled = this.page === 0;
      this.next.disabled = this.page >= this.count - 1;
      this.draw();
    }
    point(e) {
      const box = this.sheet.getBoundingClientRect();
      const [w, h] = this.size;
      return [Math.max(0, Math.min(w, (e.clientX - box.left) * w / box.width)), Math.max(0, Math.min(h, (e.clientY - box.top) * h / box.height))];
    }
    place(node, [x0, y0, x1, y1]) {
      const [w, h] = this.size;
      Object.assign(node.style, { left: 100 * x0 / w + "%", top: 100 * y0 / h + "%", width: 100 * (x1 - x0) / w + "%", height: 100 * (y1 - y0) / h + "%" });
    }
    draw() {
      this.layer.replaceChildren();
      for (const item of this.items) {
        if (item.page !== this.page && !(item.everyPage)) continue;
        const node = make("div", { class: "pv-item", style: `--item:${item.color || "#147552"}` });
        this.place(node, item.rect);
        if (item.label) node.append(make("span", { class: "pv-label", text: item.label }));
        if (item.image) node.append(make("img", { src: item.image, alt: "" }));
        if (item.text) node.append(make("span", { class: "pv-text", text: item.text, style: `font-size:${item.fontSize || 12}px` }));
        if (item.removable !== false) node.append(make("button", { class: "pv-x", type: "button", "aria-label": "Remove", text: "×", onclick: e => { e.stopPropagation(); this.remove(item); } }));
        if (item.resizable) node.append(make("span", { class: "pv-resize", dataset: { resize: "1" } }));
        node.item = item;
        this.layer.append(node);
        if (item.text) this.fitText(node, item);
      }
    }
    fitText(node, item) {
      const span = node.querySelector(".pv-text");
      const box = node.getBoundingClientRect();
      span.style.fontSize = Math.max(6, box.height * 0.72) + "px";
    }
    add(item) { this.items.push(item); this.draw(); this.onChange?.(); }
    remove(item) { this.items = this.items.filter(i => i !== item); this.draw(); this.onChange?.(); }
    down(e) {
      if (e.button !== 0 || e.target.closest(".pv-x")) return;
      const node = e.target.closest(".pv-item");
      const start = this.point(e);
      if (node && node.item.movable !== false) {
        this.drag = { pointer: e.pointerId, item: node.item, start, origin: [...node.item.rect], resize: !!e.target.dataset.resize, node };
      } else if (this.onDraw) {
        this.drag = { pointer: e.pointerId, start, draw: true };
        this.region.hidden = false;
        this.place(this.region, [...start, ...start]);
      } else return;
      e.preventDefault();
      this.sheet.setPointerCapture(e.pointerId);
    }
    move(e) {
      const d = this.drag;
      if (!d || d.pointer !== e.pointerId) return;
      const p = this.point(e);
      if (d.draw) {
        this.place(this.region, [Math.min(d.start[0], p[0]), Math.min(d.start[1], p[1]), Math.max(d.start[0], p[0]), Math.max(d.start[1], p[1])]);
        return;
      }
      const [w, h] = this.size;
      const [x0, y0, x1, y1] = d.origin;
      const dx = p[0] - d.start[0], dy = p[1] - d.start[1];
      if (d.resize) {
        let nx1 = Math.max(x0 + 8, Math.min(w, x1 + dx)), ny1 = Math.max(y0 + 8, Math.min(h, y1 + dy));
        if (d.item.keepRatio) ny1 = y0 + (nx1 - x0) * (y1 - y0) / (x1 - x0);
        d.item.rect = [x0, y0, nx1, Math.min(h, ny1)];
      } else {
        const mx = Math.max(-x0, Math.min(w - x1, dx)), my = Math.max(-y0, Math.min(h - y1, dy));
        d.item.rect = [x0 + mx, y0 + my, x1 + mx, y1 + my];
      }
      this.place(d.node, d.item.rect);
      if (d.item.text) this.fitText(d.node, d.item);
    }
    up(e) {
      const d = this.drag;
      if (!d || d.pointer !== e.pointerId) return;
      this.drag = null;
      if (d.draw) {
        this.region.hidden = true;
        const p = this.point(e);
        const rect = [Math.min(d.start[0], p[0]), Math.min(d.start[1], p[1]), Math.max(d.start[0], p[0]), Math.max(d.start[1], p[1])];
        if (rect[2] - rect[0] > 4 && rect[3] - rect[1] > 4) this.onDraw(rect, this.page);
      } else this.onChange?.();
    }
    destroy() { this.root.remove(); }
  }

  function firstPdf() {
    return st.files.find(f => f.info?.kind === "pdf" && f.info.pages);
  }

  function panel(title, ...children) {
    return make("div", { class: "panel-box" }, title ? make("h2", { text: title }) : null, children);
  }

  // ---------------- custom panels ----------------

  const CUSTOM = {
    pagepick(tool) {
      const box = panel("Click pages to select them");
      const grid = make("div", { class: "thumb-grid" });
      box.append(make("p", { class: "muted", text: "Selected pages are marked with ✕. The page box on the right updates as you click." }), grid);
      let shownFor = null;
      const field = () => fields.find(f => f.def.key === "pages").node.querySelector("input");
      const selected = () => {
        const set = new Set();
        for (const part of field().value.split(",")) {
          const m = part.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
          if (m) for (let n = +m[1]; n <= +(m[2] || m[1]); n++) set.add(n);
        }
        return set;
      };
      const toText = set => {
        const nums = [...set].sort((a, b) => a - b);
        const out = [];
        for (let i = 0; i < nums.length; i++) {
          let j = i;
          while (j + 1 < nums.length && nums[j + 1] === nums[j] + 1) j++;
          out.push(i === j ? `${nums[i]}` : `${nums[i]}-${nums[j]}`);
          i = j;
        }
        return out.join(", ");
      };
      const mark = () => {
        const set = selected();
        for (const card of grid.children) card.setAttribute("aria-pressed", String(set.has(+card.dataset.page)));
      };
      const build = () => {
        const entry = firstPdf();
        if (!entry) { grid.replaceChildren(); box.hidden = true; shownFor = null; return; }
        box.hidden = false;
        if (shownFor === entry.id) return mark();
        shownFor = entry.id;
        const observer = new IntersectionObserver(items => {
          for (const it of items) if (it.isIntersecting) {
            observer.unobserve(it.target);
            preview(entry.id, +it.target.dataset.page - 1, 220).then(url => { it.target.querySelector("img").src = url; }).catch(() => {});
          }
        });
        grid.replaceChildren(...Array.from({ length: entry.info.pages }, (_, i) => {
          const card = make("button", { type: "button", class: "thumb-card", dataset: { page: i + 1 }, "aria-pressed": "false",
            onclick: () => { const set = selected(); set.has(i + 1) ? set.delete(i + 1) : set.add(i + 1); field().value = toText(set); mark(); } },
          make("img", { alt: "" }), `Page ${i + 1}`);
          observer.observe(card);
          return card;
        }));
        mark();
      };
      box.hidden = true;
      view.custom.append(box);
      view.options.addEventListener("input", mark);
      return { filesChanged: build, destroy: () => view.options.removeEventListener("input", mark) };
    },

    organize() {
      const box = panel("Pages", make("p", { class: "muted", text: "Drag pages to reorder them (or use the arrows), turn them, or delete them. Add more files to combine them." }));
      const bar = make("div", { class: "bar" }, make("button", { class: "ghost", type: "button", text: "+ Blank page", onclick: () => { cards.push({ blank: true }); draw(); } }),
        make("button", { class: "ghost", type: "button", text: "Reset", onclick: () => { cards = []; known.clear(); sync(); } }));
      const grid = make("div", { class: "thumb-grid" });
      box.append(bar, grid);
      view.custom.append(box);
      let cards = [];
      const known = new Set();
      let dragged = null;
      function sync() {
        // Add the pages of newly ready files; drop pages of removed files.
        const ids = st.files.map(f => f.id);
        cards = cards.filter(c => c.blank || ids.includes(c.id));
        for (const f of st.files) {
          if (!f.info?.pages || known.has(f.id)) continue;
          known.add(f.id);
          for (let p = 0; p < f.info.pages; p++) cards.push({ id: f.id, page: p, rotate: 0, name: f.name });
        }
        draw();
      }
      function draw() {
        grid.replaceChildren(...cards.map((card, i) => {
          const img = card.blank ? make("div", { class: "blank", text: "Blank page" }) : make("img", { alt: "", style: `transform:rotate(${card.rotate}deg)` });
          if (!card.blank) preview(card.id, card.page, 220).then(url => { img.src = url; }).catch(() => {});
          const node = make("div", { class: "thumb-card", draggable: "true" }, img,
            make("span", { text: card.blank ? `${i + 1}` : `${i + 1} · p.${card.page + 1}${st.files.length > 1 ? " · " + card.name.slice(0, 12) : ""}` }),
            make("div", { class: "card-tools" },
              make("button", { class: "ghost", type: "button", "aria-label": "Move left", text: "←", disabled: i === 0, onclick: () => { [cards[i - 1], cards[i]] = [cards[i], cards[i - 1]]; draw(); } }),
              card.blank ? null : make("button", { class: "ghost", type: "button", "aria-label": "Turn right", text: "↻", onclick: () => { card.rotate = (card.rotate + 90) % 360; draw(); } }),
              make("button", { class: "ghost", type: "button", "aria-label": "Delete page", text: "🗑︎", onclick: () => { cards.splice(i, 1); draw(); } }),
              make("button", { class: "ghost", type: "button", "aria-label": "Move right", text: "→", disabled: i === cards.length - 1, onclick: () => { [cards[i + 1], cards[i]] = [cards[i], cards[i + 1]]; draw(); } })));
          node.addEventListener("dragstart", () => { dragged = i; node.classList.add("dragging"); });
          node.addEventListener("dragend", () => node.classList.remove("dragging"));
          node.addEventListener("dragover", e => { e.preventDefault(); node.classList.add("drop-before"); });
          node.addEventListener("dragleave", () => node.classList.remove("drop-before"));
          node.addEventListener("drop", e => {
            e.preventDefault();
            if (dragged === null || dragged === i) return;
            const [moved] = cards.splice(dragged, 1);
            cards.splice(dragged < i ? i - 1 : i, 0, moved);
            dragged = null;
            draw();
          });
          return node;
        }));
      }
      return {
        filesChanged: sync,
        options: () => {
          if (!cards.length) throw new Error("Keep at least one page.");
          const index = Object.fromEntries(st.files.map((f, i) => [f.id, i]));
          return { pages: cards.map(c => c.blank ? { blank: true } : { file: index[c.id], page: c.page, rotate: c.rotate }) };
        }
      };
    },

    scan() {
      const box = panel("Photos", make("p", { class: "muted", text: "Tap a photo to drag its corners onto the corners of the page. Pages are straightened and cleaned." }));
      const editor = make("div");
      box.append(editor);
      view.custom.append(box);
      const settings = new Map();
      function edit(entry) {
        const url = entry.thumb ||= URL.createObjectURL(entry.file);
        const s = settings.get(entry) || { corners: [[0.03, 0.03], [0.97, 0.03], [0.97, 0.97], [0.03, 0.97]], rotate: 0 };
        settings.set(entry, s);
        const wrap = make("div", { class: "corner-editor" });
        const img = make("img", { src: url, alt: `Photo ${entry.name}` });
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 100 100");
        svg.setAttribute("preserveAspectRatio", "none");
        const shape = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        shape.setAttribute("fill", "#20a76c33");
        shape.setAttribute("stroke", "#147552");
        shape.setAttribute("stroke-width", "0.6");
        svg.append(shape);
        wrap.append(img, svg);
        const dots = s.corners.map((c, i) => {
          const dot = make("span", { class: "corner", role: "slider", "aria-label": ["Top left", "Top right", "Bottom right", "Bottom left"][i] + " corner" });
          dot.addEventListener("pointerdown", e => {
            e.preventDefault();
            dot.setPointerCapture(e.pointerId);
            const moveTo = ev => {
              const r = wrap.getBoundingClientRect();
              s.corners[i] = [Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)), Math.max(0, Math.min(1, (ev.clientY - r.top) / r.height))];
              paint();
            };
            dot.onpointermove = moveTo;
            dot.onpointerup = () => { dot.onpointermove = null; };
          });
          wrap.append(dot);
          return dot;
        });
        function paint() {
          s.corners.forEach(([x, y], i) => Object.assign(dots[i].style, { left: x * 100 + "%", top: y * 100 + "%" }));
          shape.setAttribute("points", s.corners.map(([x, y]) => `${x * 100},${y * 100}`).join(" "));
        }
        paint();
        editor.replaceChildren(make("p", { text: entry.name, style: "font-weight:650;margin:0 0 6px" }), wrap,
          make("div", { class: "bar", style: "margin-top:8px" },
            make("button", { class: "ghost", type: "button", text: "Whole photo", onclick: () => { s.corners = [[0, 0], [1, 0], [1, 1], [0, 1]]; paint(); } }),
            make("button", { class: "ghost", type: "button", text: `Turn page (${s.rotate}°)`, onclick: e => { s.rotate = (s.rotate + 90) % 360; e.target.textContent = `Turn page (${s.rotate}°)`; } })));
      }
      function render() {
        box.hidden = !st.files.length;
        for (const entry of st.files) {
          if (entry.row && !entry.row.dataset.scan) {
            entry.row.dataset.scan = "1";
            entry.row.addEventListener("click", e => { if (!e.target.closest("button")) edit(entry); });
            entry.row.style.cursor = "pointer";
          }
        }
        if (st.files.length && !editor.children.length) edit(st.files.at(-1));
        if (!st.files.length) editor.replaceChildren();
      }
      box.hidden = true;
      return {
        filesChanged: () => setTimeout(render),
        options: () => ({ items: st.files.map(f => settings.get(f) || {}) })
      };
    },

    watermark() {
      const box = panel("Watermark image");
      const input = make("input", { type: "file", accept: "image/png,image/jpeg,image/webp" });
      const status = make("small", { class: "help", text: "PNG with transparency works best." });
      box.append(input, status);
      view.custom.append(box);
      const toggle = () => { box.hidden = collect().type !== "image"; };
      view.options.addEventListener("input", toggle);
      toggle();
      input.addEventListener("change", async () => {
        const file = input.files[0];
        if (!file) return;
        status.textContent = "Adding…";
        try {
          const info = await upload(file);
          st.assets = [info];
          status.textContent = `${file.name} will be used.`;
        } catch (e) { status.textContent = e.message; }
      });
      return {
        extraIds: () => {
          if (collect().type === "image" && !st.assets.length) throw new Error("Choose the watermark image.");
          return collect().type === "image" ? st.assets.map(a => a.id) : [];
        },
        destroy: () => view.options.removeEventListener("input", toggle)
      };
    },

    crop() {
      const holder = make("div");
      const box = panel("Area to keep", make("p", { class: "muted", text: "Drag the green box or its corner. The same area is used on every chosen page." }), holder);
      view.custom.append(box);
      let pv = null, item = null;
      const toggle = () => { box.hidden = collect().mode !== "area" || !firstPdf(); };
      function build() {
        const entry = firstPdf();
        if (!entry) { pv?.destroy(); pv = null; toggle(); return; }
        if (pv?.entry === entry) return toggle();
        pv?.destroy();
        pv = new PageView(holder, entry);
        const [w, h] = pv.size;
        item = { page: 0, everyPage: true, rect: [w * 0.08, h * 0.08, w * 0.92, h * 0.92], label: "Keep", resizable: true, removable: false };
        pv.add(item);
        toggle();
      }
      view.options.addEventListener("input", toggle);
      box.hidden = true;
      return {
        filesChanged: build,
        options: values => {
          if (values.mode !== "area") return {};
          const [w, h] = pv.size;
          return { area: [item.rect[0] / w, item.rect[1] / h, item.rect[2] / w, item.rect[3] / h] };
        },
        destroy: () => view.options.removeEventListener("input", toggle)
      };
    },

    sign() {
      const holder = make("div");
      const sigs = make("div", { class: "sig-list" });
      const itemsBox = make("div", { class: "item-list" });
      const creator = make("div");
      const box = panel("Your signature", creator, make("p", { class: "muted", text: "Created signatures (click to place on the page):" }), sigs,
        make("div", { class: "bar", style: "margin-top:10px" },
          make("button", { class: "ghost", type: "button", text: "+ Name", onclick: () => addText(localStorage.getItem("pdftools-name") || "Your name", "Name") }),
          make("button", { class: "ghost", type: "button", text: "+ Date", onclick: () => addText(new Date().toLocaleDateString(), "Date") }),
          make("button", { class: "ghost", type: "button", text: "+ Text", onclick: () => addText("Text", "Text") })),
        itemsBox);
      const placement = panel("Place on the page", make("p", { class: "muted", text: "Drag items to move them, and their corner to resize them." }), holder);
      view.custom.append(box, placement);
      let pv = null;
      const assets = [];
      // creator: draw / type / upload
      const tabs = ["Draw", "Type", "Upload"].map(name => make("button", { type: "button", class: "ghost", role: "tab", text: name, onclick: () => tab(name) }));
      const body = make("div");
      creator.append(make("div", { class: "tabs", role: "tablist" }, tabs), body);
      function tab(name) {
        tabs.forEach(t => t.setAttribute("aria-selected", String(t.textContent === name)));
        if (name === "Draw") {
          const canvas = make("canvas", { class: "sig-pad", width: 900, height: 270, "aria-label": "Draw your signature here" });
          const ink = make("select", { "aria-label": "Ink color" }, make("option", { value: "#111111", text: "Black ink" }), make("option", { value: "#1a3a8f", text: "Blue ink" }));
          const ctx = canvas.getContext("2d");
          let drawing = false, last = null, empty = true;
          canvas.addEventListener("pointerdown", e => { drawing = true; last = pos(e); canvas.setPointerCapture(e.pointerId); });
          canvas.addEventListener("pointermove", e => {
            if (!drawing) return;
            const p = pos(e);
            ctx.strokeStyle = ink.value; ctx.lineWidth = 5; ctx.lineCap = ctx.lineJoin = "round";
            ctx.beginPath(); ctx.moveTo(...last); ctx.lineTo(...p); ctx.stroke();
            last = p; empty = false;
          });
          canvas.addEventListener("pointerup", () => { drawing = false; });
          function pos(e) { const r = canvas.getBoundingClientRect(); return [(e.clientX - r.left) * canvas.width / r.width, (e.clientY - r.top) * canvas.height / r.height]; }
          body.replaceChildren(canvas, make("div", { class: "bar", style: "margin-top:8px" }, ink,
            make("button", { class: "ghost", type: "button", text: "Clear", onclick: () => { ctx.clearRect(0, 0, canvas.width, canvas.height); empty = true; } }),
            make("button", { class: "primary", type: "button", text: "Use this signature", onclick: () => empty ? error("Draw your signature first.") : useCanvas(canvas) })));
        } else if (name === "Type") {
          const text = make("input", { type: "text", placeholder: "Type your name", value: localStorage.getItem("pdftools-name") || "" });
          const fonts = [["Signature 1", "'Segoe Script','Snell Roundhand','URW Chancery L',cursive"], ["Signature 2", "'Lucida Handwriting','Apple Chancery','Z003',cursive"],
            ["Signature 3", "'Brush Script MT','Bradley Hand','Ink Free',cursive"], ["Plain", "Georgia,'Times New Roman',serif"]];
          const pick = make("select", { "aria-label": "Style" }, fonts.map(([n, f]) => make("option", { value: f, text: n })));
          const canvas = make("canvas", { class: "sig-pad", width: 900, height: 270, "aria-label": "Signature preview" });
          const paint = () => {
            const ctx = canvas.getContext("2d");
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = "#1a2a6c";
            let size = 120;
            do { ctx.font = `${size}px ${pick.value}`; size -= 6; } while (ctx.measureText(text.value).width > canvas.width - 40 && size > 30);
            ctx.textBaseline = "middle";
            ctx.fillText(text.value, 20, canvas.height / 2);
          };
          text.addEventListener("input", paint);
          pick.addEventListener("change", paint);
          body.replaceChildren(text, make("div", { style: "height:8px" }), pick, make("div", { style: "height:8px" }), canvas,
            make("div", { class: "bar", style: "margin-top:8px" }, make("button", { class: "primary", type: "button", text: "Use this signature", onclick: () => {
              if (!text.value.trim()) return error("Type your name first.");
              try { localStorage.setItem("pdftools-name", text.value.trim()); } catch { /* private mode */ }
              useCanvas(canvas);
            } })));
          paint();
        } else {
          const input = make("input", { type: "file", accept: "image/*" });
          input.addEventListener("change", async () => {
            const file = input.files[0];
            if (!file) return;
            const image = await createImageBitmap(file);
            const scale = Math.min(1, 1200 / image.width);
            const canvas = make("canvas", { width: Math.round(image.width * scale), height: Math.round(image.height * scale) });
            const ctx = canvas.getContext("2d", { willReadFrequently: true });
            ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
            // Make the paper behind the signature transparent.
            const data = ctx.getImageData(0, 0, canvas.width, canvas.height);
            for (let i = 0; i < data.data.length; i += 4) {
              const light = (data.data[i] + data.data[i + 1] + data.data[i + 2]) / 3;
              data.data[i + 3] = light > 200 ? 0 : light > 150 ? Math.round(255 * (200 - light) / 50) : 255;
            }
            ctx.putImageData(data, 0, 0);
            useCanvas(canvas);
          });
          body.replaceChildren(make("p", { class: "muted", text: "A photo or scan of your signature on white paper; the paper is removed automatically." }), input);
        }
      }
      tab("Draw");
      async function useCanvas(canvas) {
        const blob = await new Promise(r => canvas.toBlob(r, "image/png"));
        const info = await upload(new File([blob], `signature-${assets.length + 1}.png`, { type: "image/png" }));
        const url = URL.createObjectURL(blob);
        assets.push({ info, url, ratio: canvas.width / canvas.height });
        sigs.append(make("button", { type: "button", "aria-label": "Place this signature", onclick: () => placeImage(assets.length - 1) }, make("img", { src: url, alt: "" })));
        placeImage(assets.length - 1);
      }
      function placeImage(index) {
        if (!pv) return error("Choose the PDF to sign first.");
        const [w, h] = pv.size;
        const width = Math.min(180, w * 0.35);
        pv.add({ kind: "image", image: assets[index].url, imageIndex: index, page: pv.page, rect: [w * 0.55, h * 0.75, w * 0.55 + width, h * 0.75 + width / assets[index].ratio], resizable: true, keepRatio: true, label: "Signature", pages: "this" });
        listItems();
      }
      function addText(text, label) {
        if (!pv) return error("Choose the PDF to sign first.");
        const [w, h] = pv.size;
        pv.add({ kind: "text", text, label, page: pv.page, rect: [w * 0.55, h * 0.88, w * 0.55 + 160, h * 0.88 + 18], resizable: true, pages: "this" });
        listItems();
      }
      function listItems() {
        itemsBox.replaceChildren(...(pv?.items || []).map(item => make("div", {},
          make("strong", { text: item.label }),
          item.kind === "text" ? make("input", { type: "text", value: item.text, "aria-label": item.label, style: "width:auto;flex:1", oninput: e => { item.text = e.target.value; pv.draw(); } }) : null,
          make("select", { "aria-label": "Pages", onchange: e => { item.pages = e.target.value; } },
            [["this", `Page ${item.page + 1}`], ["all", "All pages"], ["last", "Last page"]].map(([v, t]) => make("option", { value: v, text: t, selected: item.pages === v }))))));
      }
      function build() {
        const entry = firstPdf();
        if (!entry || pv?.entry === entry) return;
        pv?.destroy();
        pv = new PageView(holder, entry);
        pv.onChange = listItems;
      }
      return {
        filesChanged: build,
        extraIds: () => assets.map(a => a.info.id),
        options: () => {
          const items = (pv?.items || []).map(item => ({
            kind: item.kind, image: item.imageIndex, text: item.text, page: item.page, rect: item.rect,
            size: Math.max(6, (item.rect[3] - item.rect[1]) * 0.72),
            pages: item.pages === "all" ? "all" : item.pages === "last" ? String(pv.count) : undefined
          }));
          if (!items.length) throw new Error("Create a signature or add a field, then place it on the page.");
          return { items };
        }
      };
    },

    redact() {
      const holder = make("div");
      const list = make("ol", { class: "matches" });
      const find = make("button", { class: "ghost", type: "button", text: "Find matches first", onclick: () => search() });
      const box = panel("Areas and matches", make("p", { class: "muted", text: "Drag on the page to black out any area (works on scans too). “Find matches” shows what the words and patterns will remove." }),
        make("div", { class: "bar" }, find), holder, list);
      view.custom.append(box);
      let pv = null;
      async function search() {
        try {
          await ready();
          find.disabled = true;
          const { meta } = await runTool("redact", st.files.map(f => f.id), { ...collect(), preview: true });
          const matches = meta.data.matches;
          pv.items = pv.items.filter(i => i.kind !== "match");
          for (const m of matches) pv.items.push({ kind: "match", page: m.page, rect: m.rect, color: "#e67e22", removable: false, movable: false });
          pv.draw();
          list.replaceChildren(...matches.slice(0, 200).map(m => make("li", { text: `Page ${m.page + 1}: ${m.text} (${m.kind})` })));
          if (!matches.length) list.replaceChildren(make("li", { text: "No matches. Check the words and patterns." }));
        } catch (e) { error(e.message); } finally { find.disabled = false; }
      }
      function build() {
        const entry = firstPdf();
        if (!entry || pv?.entry === entry) return;
        pv?.destroy();
        pv = new PageView(holder, entry, { onDraw: (rect, page) => pv.add({ kind: "area", page, rect, color: "#111111", label: "Area" }) });
      }
      return {
        filesChanged: build,
        options: () => ({ areas: (pv?.items || []).filter(i => i.kind === "area").map(i => ({ page: i.page, rect: i.rect })) })
      };
    },

    forms() {
      const holder = make("div");
      const fieldsBox = make("div");
      const kind = make("select", { "aria-label": "Type of new field" }, [["text", "Text"], ["checkbox", "Checkbox"], ["combobox", "Drop-down list"]].map(([v, t]) => make("option", { value: v, text: t })));
      const box = panel("Fields", fieldsBox);
      const designer = panel("Add fields", make("p", { class: "muted", text: "Detect the lines and boxes of a paper-style form, or drag on the page to draw a new field." }),
        make("div", { class: "bar" }, make("button", { class: "ghost", type: "button", text: "Detect fields", onclick: () => detect() }), kind), holder);
      view.custom.append(box, designer);
      let pv = null, existing = [];
      async function load(entry) {
        const { meta } = await runTool("forms", [entry.id], { action: "list" });
        existing = meta.data.fields;
        fieldsBox.replaceChildren(existing.length ? make("div", {}, existing.filter(f => !f.readonly && f.type !== "button" && f.type !== "signature").map(f => {
          let input;
          if (f.type === "checkbox" || f.type === "radio") input = make("input", { type: "checkbox", checked: !!f.value, dataset: { name: f.name, kind: f.type, on: f.on } });
          else if (f.options) input = make("select", { dataset: { name: f.name } }, f.options.map(o => make("option", { value: o, text: o, selected: o === f.value })));
          else { input = make("input", { type: "text", dataset: { name: f.name } }); input.value = f.value || ""; }
          return f.type === "checkbox" || f.type === "radio"
            ? make("label", { class: "field-check" }, input, make("span", { text: f.label || f.name }))
            : make("label", { class: "field", style: "display:grid;gap:4px;font-size:13px;font-weight:650;margin:0 0 10px" }, f.label || f.name, input);
        })) : make("p", { class: "muted", text: "This PDF has no fillable fields yet. Detect or draw them below." }));
      }
      async function detect() {
        try {
          const { meta } = await runTool("forms", [firstPdf().id], { action: "detect" });
          for (const c of meta.data.candidates) pv.items.push({ kind: "new", type: c.type, name: c.name, page: c.page, rect: c.rect, label: `${c.type}: ${c.name}`, color: "#3466d1", resizable: true });
          pv.draw();
          if (!meta.data.candidates.length) error("No form lines or boxes were found. Draw the fields instead.");
        } catch (e) { error(e.message); }
      }
      function build() {
        const entry = firstPdf();
        if (!entry || pv?.entry === entry) return;
        pv?.destroy();
        pv = new PageView(holder, entry, { onDraw: (rect, page) => {
          const type = kind.value;
          const name = prompt("Name of the new field", type === "checkbox" ? "agree" : "field");
          if (name === null) return;
          const item = { kind: "new", type, name: name || type, page, rect, label: `${type}: ${name || type}`, color: "#3466d1", resizable: true };
          if (type === "combobox") item.options = (prompt("Choices, separated by commas", "Yes, No") || "Yes").split(",").map(s => s.trim()).filter(Boolean);
          pv.add(item);
        } });
        load(entry).catch(e => error(e.message));
      }
      return {
        filesChanged: build,
        options: values => {
          const filled = {};
          for (const input of fieldsBox.querySelectorAll("[data-name]")) {
            if (input.dataset.kind === "radio") { if (input.checked) filled[input.dataset.name] = input.dataset.on; }
            else filled[input.dataset.name] = input.type === "checkbox" ? input.checked : input.value;
          }
          return { action: "fill", values: filled, flatten: values.flatten,
            create: (pv?.items || []).filter(i => i.kind === "new").map(i => ({ type: i.type, name: i.name, page: i.page, rect: i.rect, options: i.options })) };
        }
      };
    },

    translate() {
      const langs = [["en", "English"], ["hi", "Hindi"], ["mr", "Marathi"], ["bn", "Bengali"], ["ta", "Tamil"], ["te", "Telugu"], ["kn", "Kannada"], ["gu", "Gujarati"],
        ["fr", "French"], ["de", "German"], ["es", "Spanish"], ["pt", "Portuguese"], ["it", "Italian"], ["nl", "Dutch"], ["ru", "Russian"], ["ja", "Japanese"], ["zh", "Chinese"], ["ko", "Korean"], ["ar", "Arabic"], ["tr", "Turkish"]];
      const from = make("select", { "aria-label": "From" }, make("option", { value: "auto", text: "Detect automatically" }), langs.map(([v, t]) => make("option", { value: v, text: t })));
      const to = make("select", { "aria-label": "To" }, langs.map(([v, t]) => make("option", { value: v, text: t, selected: v === "hi" })));
      const support = "Translator" in self
        ? "Translation runs on this device with the translation built into your browser. The first time, the browser may download the language."
        : "This browser has no built-in translation. Use Chrome or Edge (version 138 or newer) on a computer.";
      view.custom.append(panel("Languages", make("label", { class: "field", style: "display:grid;gap:4px;font-size:13px;font-weight:650;margin-bottom:10px" }, "From", from),
        make("label", { class: "field", style: "display:grid;gap:4px;font-size:13px;font-weight:650" }, "To", to), make("p", { class: "muted", style: "margin-top:10px", text: support })));
      return {
        async run() {
          if (!("Translator" in self)) throw new Error("This browser cannot translate on the device. Open PageBurrow in Chrome or Edge 138 or newer on a computer.");
          const ids = st.files.map(f => f.id);
          const { meta } = await runTool("translate", ids, { step: "extract" });
          const segments = meta.data.segments;
          let source = from.value;
          if (source === "auto") {
            try {
              const detector = await LanguageDetector.create();
              const sample = segments.slice(0, 30).map(s => s.text).join(" ").slice(0, 4000);
              source = (await detector.detect(sample))[0]?.detectedLanguage || "en";
            } catch {
              throw new Error("Your browser could not detect the language on this device. Choose the language the PDF is written in under “From”.");
            }
          }
          if (source === to.value) throw new Error("The PDF is already in that language.");
          const translations = {};
          try {
            const availability = await Translator.availability({ sourceLanguage: source, targetLanguage: to.value });
            if (availability === "unavailable") throw new Error("unavailable");
            const translator = await Translator.create({ sourceLanguage: source, targetLanguage: to.value,
              monitor: m => m.addEventListener("downloadprogress", e => { view.working.textContent = `Downloading the language (${Math.round(e.loaded * 100)}%)…`; }) });
            for (let i = 0; i < segments.length; i++) {
              view.working.textContent = `Translating paragraph ${i + 1} of ${segments.length}…`;
              translations[segments[i].id] = await translator.translate(segments[i].text);
            }
          } catch (e) {
            throw new Error("Your browser could not prepare on-device translation for these languages"
              + (e.message && e.message !== "unavailable" ? ` (${e.message})` : "") + ". The first time it needs the internet to download the "
              + "language; also check that this language pair is supported by your browser.");
          }
          view.working.textContent = "Rebuilding the PDF…";
          const result = await runTool("translate", ids, { step: "apply", translations });
          showResult(result.meta, result.blob);
        }
      };
    },

    workflow() {
      const CHAIN = ["merge", "rotate", "page_numbers", "watermark", "crop", "redact", "remove_pages", "extract_pages", "ocr", "repair", "compress", "pdfa", "unlock", "protect"];
      const SKIP = new Set(["pages_pick"]);
      const list = make("ol", { class: "step-list" });
      const saved = make("select", { "aria-label": "Saved workflows" });
      const box = panel("Steps", make("p", { class: "muted", text: "Each step works on the result of the step before. Merge can only be first, Protect only last." }),
        make("div", { class: "bar" }, saved, make("button", { class: "ghost", type: "button", text: "Load", onclick: () => load() }),
          make("button", { class: "ghost", type: "button", text: "Save as…", onclick: () => save() }),
          make("button", { class: "ghost", type: "button", text: "Delete", onclick: () => remove() })), list,
        make("button", { class: "ghost", type: "button", text: "+ Add a step", style: "margin-top:10px", onclick: () => addStep("compress") }));
      view.custom.append(box);
      let steps = [];
      const store = () => { try { return JSON.parse(localStorage.getItem("pdftools-workflows") || "{}"); } catch { return {}; } };
      const keep = all => { try { localStorage.setItem("pdftools-workflows", JSON.stringify(all)); } catch { error("Workflows cannot be saved in this browser mode."); } };
      function refreshSaved() {
        const all = store();
        saved.replaceChildren(make("option", { value: "", text: Object.keys(all).length ? "Saved workflows…" : "No saved workflows yet" }), Object.keys(all).map(n => make("option", { value: n, text: n })));
      }
      function addStep(tool, values = null) {
        steps.push({ tool, values });
        draw();
      }
      function draw() {
        for (const s of steps) if (s.fields) s.values = collect(s.fields);
        list.replaceChildren(...steps.map((s, i) => {
          const select = make("select", { "aria-label": `Step ${i + 1}` }, CHAIN.map(id => make("option", { value: id, text: TOOL[id].name, selected: id === s.tool })));
          select.addEventListener("change", () => { s.tool = select.value; s.values = null; draw(); });
          const opts = make("div", { class: "tool-options" });
          s.fields = renderOptions(opts, (TOOL[s.tool].options || []).filter(o => !SKIP.has(o.key)), s.values);
          return make("li", { class: "step" }, make("div", { class: "step-head" }, make("strong", { text: `${i + 1}.` }), select,
            make("button", { class: "ghost", type: "button", "aria-label": "Move up", text: "↑", disabled: i === 0, onclick: () => { [steps[i - 1], steps[i]] = [steps[i], steps[i - 1]]; draw(); } }),
            make("button", { class: "ghost", type: "button", "aria-label": "Remove step", text: "✕", onclick: () => { steps.splice(i, 1); draw(); } })), opts);
        }));
      }
      function current() {
        for (const s of steps) if (s.fields) s.values = collect(s.fields);
        return steps.map(s => {
          const options = { ...s.values };
          if (s.tool === "page_numbers" && options.format === "custom") options.format = options.custom;
          return { tool: s.tool, options };
        });
      }
      function save() {
        const name = prompt("Name for this workflow", "My workflow");
        if (!name) return;
        const all = store();
        all[name] = current();
        keep(all);
        refreshSaved();
        saved.value = name;
      }
      function load() {
        const flow = store()[saved.value];
        if (!flow) return;
        steps = flow.map(s => ({ tool: s.tool, values: s.options }));
        draw();
      }
      function remove() {
        const all = store();
        if (!saved.value || !all[saved.value]) return;
        delete all[saved.value];
        keep(all);
        refreshSaved();
      }
      refreshSaved();
      addStep("merge");
      addStep("page_numbers");
      addStep("compress");
      return {
        extraIds: () => [],
        options: () => {
          if (!steps.length) throw new Error("Add at least one step.");
          return { steps: current() };
        }
      };
    }
  };

  // Phone/tablet: "Add to Home Screen" opens here; start on the home grid.
  route();
})();
