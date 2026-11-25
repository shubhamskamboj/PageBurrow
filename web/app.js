"use strict";

const $ = id => document.getElementById(id);
const ui = Object.fromEntries([...document.querySelectorAll("[id]")].map(el => [el.id, el]));
const SVG_NS = "http://www.w3.org/2000/svg";
const state = {
  token: "", file: "", count: 0, page: 0, tool: "replace", selection: null,
  asset: null, zoom: null, result: null, edits: [], undo: [], redo: [], busy: false,
  changedPage: false, drag: null,
  // Movable objects (added text and whiteouts). `live` is the selected object, or a
  // new text draft whose id is null. Selected text is left out of the server raster
  // (`hidden`) and drawn in the browser so it can follow the pointer.
  live: null, hidden: null, gesture: null, tap: null, nudgeTimer: 0, lastTap: 0,
  textStyle: { font: "Helvetica", size: 12, color: "#242b2a" }
};
const toolInfo = {
  replace: ["Edit text", "Click a line or text segment on the page. Its font and point size will appear here."],
  text: ["Add text", "Click or tap where the text should start. Click text you added to move, resize or edit it."],
  image: ["Image", "Choose a PNG or JPEG, then drag on the page to place it."],
  link: ["Link", "Drag over an area you want to turn into a clickable link."],
  highlight: ["Highlight", "Drag to highlight an area."],
  whiteout: ["Eraser", "Drag over text to erase it. The paper color and texture around it stay as they are. Click an erased area to move or resize it."],
  rectangle: ["Rectangle", "Drag to draw a rectangle."],
  ellipse: ["Ellipse", "Drag to draw an ellipse or circle."],
  line: ["Line", "Drag from where the line starts to where it ends."],
  draw: ["Draw", "Draw freehand with the mouse, a finger or a pen. Choose the pen color and width below."]
};
// Browser stand-ins for the PDF standard fonts. Arial, Times New Roman and Courier New
// share their widths; the preview is also stretched to the exact width the server reports.
// Ascent and descent (per em) size the selection frame around the visible letters;
// cap is the capital-letter height, used to match the size of erased text.
const SANS = 'Arial, Helvetica, "Liberation Sans", Arimo, sans-serif';
const SERIF = '"Times New Roman", Times, "Liberation Serif", Tinos, serif';
const FONTS = {
  "Helvetica": { family: SANS, weight: 400, ascent: 0.76, descent: 0.22, cap: 0.72 },
  "Helvetica-Bold": { family: SANS, weight: 700, ascent: 0.76, descent: 0.22, cap: 0.72 },
  "Times-Roman": { family: SERIF, weight: 400, ascent: 0.71, descent: 0.22, cap: 0.66 },
  "Times-Bold": { family: SERIF, weight: 700, ascent: 0.71, descent: 0.22, cap: 0.68 },
  "Courier": { family: '"Courier New", Courier, "Liberation Mono", Cousine, monospace', weight: 400, ascent: 0.66, descent: 0.21, cap: 0.58 }
};
const FIELDS = ["start", "end", "text", "font", "size", "color", "stretch", "strength", "mode"];
// Side handles come first so corner handles sit on top where they overlap.
const TEXT_HANDLES = ["w", "e", "nw", "ne", "sw", "se"];
const RECT_HANDLES = ["n", "e", "s", "w", "nw", "ne", "se", "sw"];
const coarse = matchMedia("(pointer: coarse)");
const MIN_RECT = 3;
const measure = document.createElement("canvas").getContext("2d");
let thumbObserver;
let thumbUrls = new Set();
let pendingPdf;
let previousFocus;
let nextId = 1;

async function api(path, { data, raw, password, token = state.token } = {}) {
  const headers = { "X-Local-Editor": "1", "X-Document": token };
  if (password) headers["X-PDF-Password"] = encodeURIComponent(password);
  if (!raw) headers["Content-Type"] = "application/json";
  const response = await (window.pageBurrowRequest || fetch)("/api/" + path, {
    method: "POST", headers, body: raw || JSON.stringify(data ?? {}),
    cache: "no-store"
  });
  const isJson = response.headers.get("Content-Type")?.includes("application/json");
  if (!response.ok) {
    throw new Error(isJson ? (await response.json()).error : "Could not reach the local editor.");
  }
  return isJson ? response.json() : response.blob();
}

function displayError(value = "") {
  const node = state.token ? ui.error : ui["welcome-error"];
  node.textContent = value;
  node.hidden = !value;
}

function setBusy(value) {
  state.busy = value;
  ui.open.disabled = value;
  ui.export.disabled = value;
  ui.tools.inert = value;
  ui.sheet.inert = value;
  ui.apply.disabled = value;
  ui["pick-image"].disabled = value;
  ui.remove.disabled = value;
  ui["text-here"].disabled = value;
  ui["match-fill"].disabled = ui["white-fill"].disabled = ui.strength.disabled = value;
  syncButtons();
}

async function busy(work) {
  if (state.busy) return false;
  displayError();
  setBusy(true);
  try {
    await work();
    return true;
  } catch (error) {
    displayError(error.message);
    return false;
  } finally {
    setBusy(false);
  }
}

async function openPdf(file, password = "") {
  if (!file) return;
  await busy(async () => {
    let opened;
    try {
      opened = await api("open", { raw: file, password });
    } catch (error) {
      if (error.message === "Enter the correct PDF password.") {
        pendingPdf = file;
        ui["password-error"].textContent = password ? "That password did not unlock the PDF." : "Enter the password for this PDF.";
        ui.password.value = "";
        ui["password-dialog"].returnValue = "";
        ui["password-dialog"].showModal();
        return;
      }
      throw error;
    }
    clearTimeout(state.nudgeTimer);
    Object.assign(state, {
      token: opened.token, file: file.name, count: opened.count, page: 0,
      selection: null, edits: [], undo: [], redo: [], zoom: null, asset: null, result: null, changedPage: true,
      live: null, hidden: null, gesture: null, tap: null, drag: null
    });
    ui["page-image"].removeAttribute("src");
    ui["document-warning"].textContent = "Saving edits can invalidate digital signatures.";
    ui["document-warning"].hidden = !opened.signature;
    ui.filename.textContent = file.name;
    ui.filename.title = file.name;
    ui.filename.hidden = ui.export.hidden = ui["compress-open"].hidden = ui.work.hidden = false;
    ui.welcome.hidden = ui["tool-view"].hidden = true;
    ui["home-button"].hidden = false;
    if (location.hash !== "#edit") history.pushState(null, "", "#edit");
    ui["page-count"].textContent = opened.count;
    await activate("replace");
    await render(state.edits);
    buildThumbs();
  });
}

function buildThumbs() {
  thumbObserver?.disconnect();
  for (const url of thumbUrls) URL.revokeObjectURL(url);
  thumbUrls = new Set();
  ui.thumbnails.replaceChildren();
  const docToken = state.token;
  thumbObserver = new IntersectionObserver(entries => {
    for (const { target, isIntersecting } of entries) {
      if (!isIntersecting) continue;
      thumbObserver.unobserve(target);
      api("render", { data: { page: Number(target.dataset.page), thumbnail: true }, token: docToken })
        .then(blob => {
          if (state.token !== docToken) return;
          const url = URL.createObjectURL(blob);
          thumbUrls.add(url);
          target.src = url;
        })
        .catch(() => {});
    }
  }, { root: document.querySelector(".sidebar") });
  const fragment = document.createDocumentFragment();
  for (let i = 0; i < state.count; i++) {
    const button = document.createElement("button");
    const img = document.createElement("img");
    const label = document.createElement("span");
    img.alt = "";
    img.dataset.page = i;
    label.textContent = i + 1;
    button.className = "thumb";
    button.setAttribute("aria-label", "Page " + (i + 1));
    button.append(img, label);
    button.addEventListener("click", () => go(i));
    fragment.append(button);
    thumbObserver.observe(img);
  }
  ui.thumbnails.append(fragment);
  syncButtons();
}

function syncButtons() {
  const { busy, page, count, undo, redo, result } = state;
  ui.back.disabled = busy || page === 0;
  ui.next.disabled = busy || page + 1 >= count;
  ui["page-value"].disabled = busy;
  ui["page-value"].value = page + 1;
  ui["page-value"].max = count;
  ui["page-of"].textContent = "/ " + count;
  ui.undo.disabled = busy || !undo.length;
  ui.redo.disabled = busy || !redo.length;
  ui.minus.disabled = ui.fit.disabled = ui.plus.disabled = !result;
  const current = ui.thumbnails.querySelector('[aria-current="page"]');
  const selected = ui.thumbnails.children[page];
  if (current !== selected) {
    current?.removeAttribute("aria-current");
    selected?.setAttribute("aria-current", "page");
    selected?.scrollIntoView({ block: "nearest" });
  }
}

function resize() {
  if (!state.result) return;
  const { width, height } = state.result;
  const style = getComputedStyle(ui.stage);
  const available = ui.stage.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  const zoom = state.zoom ?? Math.min(available / width, 1.28);
  ui.sheet.style.width = Math.max(80, width * zoom) + "px";
  ui.sheet.style.aspectRatio = width + " / " + height;
  ui.fit.textContent = state.zoom === null ? "Fit width" : Math.round(zoom * 100) + "%";
  placeFrame();
}

function place(element, [x0, y0, x1, y1]) {
  const { width, height } = state.result;
  element.style.left = (100 * x0 / width) + "%";
  element.style.top = (100 * y0 / height) + "%";
  element.style.width = (100 * (x1 - x0) / width) + "%";
  element.style.height = (100 * (y1 - y0) / height) + "%";
}

function updateOverlay() {
  ui.overlay.replaceChildren();
  if (!state.result) return;
  if (state.tool === "replace") {
    for (const [id, item] of Object.entries(state.result.spans)) {
      const button = document.createElement("button");
      button.className = "hit" + (item.editable ? "" : " locked") + (state.selection?.span === id ? " active" : "");
      place(button, item.box);
      const edit = state.edits.find(edit => edit.page === state.page && edit.type === "replace" && edit.span === id);
      button.setAttribute("aria-label", (item.editable ? "Edit: " : "Text: ") + (edit?.text || item.text));
      button.title = item.editable ? item.font + " · " + formatSize(item.size) + " pt" : "This text cannot be edited directly.";
      button.addEventListener("click", () => openSelection({ span: id }, button));
      ui.overlay.append(button);
    }
    return;
  }
  // Text and whiteouts added in this session can be picked up again with their tool.
  const type = { text: "text", whiteout: "whiteout" }[state.tool];
  for (const edit of state.edits) {
    if (!type || edit.page !== state.page || edit.type !== type || edit.id === state.live?.id) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "object";
    button.dataset.object = edit.id;
    place(button, objectBox(edit));
    button.setAttribute("aria-label", type === "text" ? "Added text: " + edit.text : edit.mode === "erase" ? "Erased area" : "Whiteout");
    button.title = "Drag to move · click to select";
    // Pointer presses are handled on the sheet; this covers Enter and Space.
    button.addEventListener("click", event => { if (event.detail === 0) selectFromKeyboard(edit.id); });
    ui.overlay.append(button);
  }
  const live = state.live;
  if (live?.page === state.page) {
    const frame = document.createElement("div");
    frame.className = "frame" + (live.id === null ? " draft" : "");
    frame.dataset.object = live.id ?? "draft";
    for (const name of live.type === "text" ? TEXT_HANDLES : RECT_HANDLES) {
      const handle = document.createElement("span");
      handle.className = "handle";
      handle.dataset.handle = name;
      frame.append(handle);
    }
    ui.overlay.append(frame);
    placeFrame();
  }
}

async function render(edits) {
  edits = await withPatches(edits);
  const hide = state.live?.type === "text" ? state.live.id : null;
  const result = await api("render", { data: { page: state.page, edits, hide } });
  const image = new Image();
  image.src = "data:image/" + (result.format || "png") + ";base64," + result.raster;
  await image.decode();
  ui["page-image"].src = image.src;
  delete result.raster;
  state.result = result;
  state.edits = edits;
  state.hidden = hide;
  const fresh = state.live?.id != null && edits.find(edit => edit.id === state.live.id);
  if (fresh?.patchKey) {
    state.live = { ...state.live, asset: fresh.asset, mask: fresh.mask, patchKey: fresh.patchKey, erased: fresh.erased, ink: fresh.ink };
  }
  resize();
  updateOverlay();
  drawLive();
  syncButtons();
  if (state.changedPage) {
    ui.stage.scrollTo(0, 0);
    state.changedPage = false;
  }
  refreshInstruction();
}

async function go(index) {
  if (!Number.isInteger(index) || index < 0 || index >= state.count || index === state.page) {
    syncButtons();
    return;
  }
  if (!(await finishLive())) {
    syncButtons();
    return;
  }
  await busy(async () => {
    const old = state.page;
    state.page = index;
    state.changedPage = true;
    closeSelection();
    ui["edit-status"].textContent = "";
    try {
      await render(state.edits);
    } catch (error) {
      state.page = old;
      throw error;
    }
  });
}

function refreshInstruction() {
  let instruction = toolInfo[state.tool][1];
  const live = state.live;
  if (live?.type === "text") {
    instruction = live.id === null
      ? "Type your text, then select Add text. Drag the box, or click elsewhere on the page, to place it."
      : "Drag the text to move it. Drag a corner to make the font bigger or smaller, or a side handle to stretch or compress it. Arrow keys nudge it.";
  } else if (live?.mode === "erase") {
    instruction = "Drag the erased area to move it, or drag a handle to resize it. If faint marks remain, raise the strength.";
  } else if (live) {
    instruction = "Drag the whiteout to move it, or drag a handle to resize it. Arrow keys nudge it.";
  } else if (state.tool === "replace" && state.result && !Object.values(state.result.spans).some(span => span.editable)) {
    instruction = "There is no directly editable text on this page. For a scan, use Eraser and Add text.";
  } else if (state.tool === "image" && state.asset) {
    instruction = state.asset.name + " · Drag on the page to place the image.";
  }
  ui.instruction.textContent = instruction;
}

async function activate(tool) {
  if (!(await finishLive())) return;
  state.tool = tool;
  closeSelection();
  displayError();
  ui["edit-status"].textContent = "";
  ui["tool-title"].textContent = toolInfo[tool][0];
  for (const button of ui.tools.querySelectorAll("[data-tool]")) {
    button.setAttribute("aria-pressed", String(button.dataset.tool === tool));
  }
  ui.sheet.dataset.tool = tool;
  ui["pick-image"].hidden = tool !== "image";
  ui["eraser-mode"].hidden = tool !== "whiteout";
  ui["pen-options"].hidden = tool !== "draw";
  refreshInstruction();
}

function closeSelection() {
  state.selection = null;
  ui.selection.hidden = true;
  ui["selection-warning"].hidden = true;
  updateOverlay();
}

function formatSize(value) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

function openSelection(selection, focusFrom) {
  displayError();
  ui["edit-status"].textContent = "";
  closeSelection();
  previousFocus = focusFrom;
  const kind = state.tool;
  const span = state.result.spans[selection.span];
  if (span && !span.editable) {
    ui["selection-warning"].textContent = "This text uses a layout or text layer the editor cannot safely replace.";
    ui["selection-warning"].hidden = false;
    return;
  }
  state.selection = selection;
  const edit = span && state.edits.find(edit => edit.page === state.page && edit.type === "replace" && edit.span === selection.span);
  ui.selection.hidden = false;
  ui.sample.hidden = !span;
  if (span) {
    ui["font-name"].textContent = span.font;
    ui["font-size"].textContent = formatSize(span.size) + " pt · original size";
    ui.swatch.style.background = "#" + span.color.toString(16).padStart(6, "0");
  }
  ui["text-field"].hidden = !["replace", "text"].includes(kind);
  ui["font-field"].hidden = ui["text-field"].hidden;
  ui["size-field"].hidden = kind !== "text";
  ui["color-field"].hidden = !["text", "rectangle", "ellipse", "line"].includes(kind);
  ui["url-field"].hidden = kind !== "link";
  ui["width-field"].hidden = ui["fill-field"].hidden = ui["nudge-field"].hidden = ui["text-here"].hidden = true;
  ui["strength-field"].hidden = true;
  ui.apply.hidden = false;
  ui.apply.textContent = "Apply";
  ui.cancel.textContent = "Cancel";
  ui.remove.textContent = "Remove original text";
  ui.font.options[0].hidden = !span;
  ui.font.value = edit?.font ?? (span ? "match" : "Helvetica");
  ui.value.value = edit?.text ?? span?.text ?? "";
  ui.url.value = "";
  $("remove").hidden = !span || edit?.text === "";
  $("restore").hidden = !edit;
  updateOverlay();
  if (!ui["text-field"].hidden) {
    ui.value.focus();
    if (span) ui.value.select();
  } else if (!ui["url-field"].hidden) ui.url.focus();
  else ui.color.focus();
}

async function commit(edits, noteId, successText = "Edit applied.") {
  await busy(async () => {
    const before = state.edits;
    await render(edits);
    state.undo.push(before);
    state.redo.length = 0;
    closeSelection();
    ui["edit-status"].textContent = state.result.notes[noteId] || successText;
  });
}

async function moveHistory(from, to, message) {
  if (!from.length || state.busy) return;
  const live = state.live;
  clearTimeout(state.nudgeTimer);
  state.live = null;
  const ok = await busy(async () => {
    const before = state.edits;
    await render(from.at(-1));
    from.pop();
    to.push(before);
    closeSelection();
    ui["edit-status"].textContent = message;
  });
  if (!ok) restoreLive(live);
}

function replace(value) {
  const { span } = state.selection;
  const original = state.result.spans[span];
  const rest = state.edits.filter(edit => !(edit.page === state.page && edit.type === "replace" && edit.span === span));
  if (value === original.text && ui.font.value === "match") {
    if (rest.length !== state.edits.length) commit(rest, null, "Original text restored.");
    else closeSelection();
    return;
  }
  const id = nextId++;
  commit([...rest, { id, span, page: state.page, type: "replace", text: value, font: ui.font.value }], id);
}

function addEdit(type, data) {
  const id = nextId++;
  commit([...state.edits, { id, page: state.page, type, ...data }], id);
}

// ---------- Geometry of movable objects (PDF points, page display space) ----------

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

function pagePoint(event) {
  const box = ui.sheet.getBoundingClientRect();
  const { width, height } = state.result;
  return [(event.clientX - box.left) * width / box.width, (event.clientY - box.top) * height / box.height];
}

function coords(event) {
  const [x, y] = pagePoint(event);
  return [clamp(x, 0, state.result.width), clamp(y, 0, state.result.height)];
}

function fontOf(edit) {
  return FONTS[edit.font] || FONTS.Helvetica;
}

function measureUnit(text, name) {
  const font = FONTS[name] || FONTS.Helvetica;
  measure.font = font.weight + " 100px " + font.family;
  return measure.measureText(text).width / 100;
}

// Width in points. Uses the server's exact width when the text and font are unchanged.
function textWidth(edit) {
  if (!edit.text) return 0;
  const committed = edit.id !== null && state.edits.find(item => item.id === edit.id);
  const exact = committed && state.result?.objects?.[edit.id];
  const unit = exact && committed.text === edit.text && committed.font === edit.font
    ? exact / (committed.size * (committed.stretch ?? 1))
    : measureUnit(edit.text, edit.font);
  return unit * edit.size * (edit.stretch ?? 1);
}

function rectBox(edit) {
  const [ax, ay] = edit.start;
  const [bx, by] = edit.end;
  return [Math.min(ax, bx), Math.min(ay, by), Math.max(ax, bx), Math.max(ay, by)];
}

function objectBox(edit) {
  if (edit.type !== "text") return rectBox(edit);
  const font = fontOf(edit);
  const [x, y] = edit.start;
  const width = textWidth(edit) || edit.size * 0.08;
  return [x, y - font.ascent * edit.size, x + width, y + font.descent * edit.size];
}

// The server needs the whole line on the page and the baseline at least one size below the top.
function fitText(edit, [x, y]) {
  const { width, height } = state.result;
  return [clamp(x, 0, Math.max(0, width - textWidth(edit))), clamp(y, Math.min(edit.size, height), height)];
}

function textFits(edit) {
  const { width, height } = state.result;
  const [x, y] = edit.start;
  return x >= 0 && x + textWidth(edit) <= width + 0.005 && y >= edit.size && y <= height;
}

function dragText(g, dx, dy) {
  const o = g.origin;
  if (g.handle === "move") return { ...o, start: fitText(o, [o.start[0] + dx, o.start[1] + dy]) };
  const [x0, y0, x1, y1] = g.box;
  if (g.handle === "e" || g.handle === "w") {
    // Side handles stretch or compress the letters horizontally.
    const unit = textWidth(o) / (o.stretch ?? 1);
    if (!(unit > 0)) return o;
    const right = g.handle === "e";
    const room = right ? state.result.width - x0 : x1;
    const width = clamp(right ? x1 - x0 + dx : x1 - x0 - dx, unit * 0.25, Math.min(unit * 4, room));
    return { ...o, stretch: width / unit, start: [right ? x0 : Math.max(0, x1 - width), o.start[1]] };
  }
  // Corner handles scale the font size; the opposite corner stays where it is.
  const west = g.handle.includes("w");
  const north = g.handle.includes("n");
  const corner = [west ? x0 : x1, north ? y0 : y1];
  const anchor = [west ? x1 : x0, north ? y1 : y0];
  const v = [corner[0] - anchor[0], corner[1] - anchor[1]];
  const k = ((corner[0] + dx - anchor[0]) * v[0] + (corner[1] + dy - anchor[1]) * v[1]) / (v[0] ** 2 + v[1] ** 2);
  const scaled = factor => {
    const size = Math.round(clamp(o.size * factor, 4, 144) * 10) / 10;
    const ratio = size / o.size;
    const left = west ? x1 - (x1 - x0) * ratio : x0;
    const top = north ? y1 - (y1 - y0) * ratio : y0;
    return { ...o, size, start: [Math.max(0, left), top + fontOf(o).ascent * size] };
  };
  let result = scaled(k);
  if (!textFits(result)) {
    // Shrink the step until the text stays on the page.
    let low = 1;
    let high = k;
    for (let i = 0; i < 20; i++) {
      const mid = (low + high) / 2;
      if (textFits(scaled(mid))) low = mid;
      else high = mid;
    }
    result = scaled(low);
  }
  return result;
}

function dragBox(g, dx, dy) {
  const { width, height } = state.result;
  let [x0, y0, x1, y1] = g.box;
  if (g.handle === "move") {
    const mx = clamp(dx, -x0, width - x1);
    const my = clamp(dy, -y0, height - y1);
    [x0, y0, x1, y1] = [x0 + mx, y0 + my, x1 + mx, y1 + my];
  } else {
    if (g.handle.includes("w")) x0 = clamp(x0 + dx, 0, x1 - MIN_RECT);
    if (g.handle.includes("e")) x1 = clamp(x1 + dx, x0 + MIN_RECT, width);
    if (g.handle.includes("n")) y0 = clamp(y0 + dy, 0, y1 - MIN_RECT);
    if (g.handle.includes("s")) y1 = clamp(y1 + dy, y0 + MIN_RECT, height);
  }
  const fx = value => clamp(value, 0, width);
  const fy = value => clamp(value, 0, height);
  return { ...g.origin, start: [fx(x0), fy(y0)], end: [fx(x1), fy(y1)] };
}

// Median color of the lighter half of the pixels around (and optionally inside) an
// area. Ink is darker than paper, so this finds the paper tone of a scan.
function sampleBackground(box, inside) {
  const image = ui["page-image"];
  if (!image.naturalWidth || !state.result) return "#ffffff";
  const sx = image.naturalWidth / state.result.width;
  const sy = image.naturalHeight / state.result.height;
  const band = 6;
  const left = Math.max(0, Math.floor(box[0] * sx) - band);
  const top = Math.max(0, Math.floor(box[1] * sy) - band);
  const right = Math.min(image.naturalWidth, Math.ceil(box[2] * sx) + band);
  const bottom = Math.min(image.naturalHeight, Math.ceil(box[3] * sy) + band);
  const w = right - left;
  const h = bottom - top;
  if (w < 1 || h < 1) return "#ffffff";
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(image, left, top, w, h, 0, 0, w, h);
  const data = context.getImageData(0, 0, w, h).data;
  const inner = [Math.floor(box[0] * sx) - left, Math.floor(box[1] * sy) - top, Math.ceil(box[2] * sx) - left, Math.ceil(box[3] * sy) - top];
  const step = inside ? Math.max(1, Math.floor(Math.sqrt(w * h / 40000))) : 1;
  const pixels = [];
  for (let y = 0; y < h; y += step) {
    for (let x = 0; x < w; x += step) {
      if (!inside && x >= inner[0] && x < inner[2] && y >= inner[1] && y < inner[3]) continue;
      const i = (y * w + x) * 4;
      pixels.push([data[i], data[i + 1], data[i + 2]]);
    }
  }
  if (!pixels.length) return "#ffffff";
  const luma = ([r, g, b]) => 0.299 * r + 0.587 * g + 0.114 * b;
  pixels.sort((a, b) => luma(b) - luma(a));
  const light = pixels.slice(0, Math.ceil(pixels.length / 2));
  return "#" + [0, 1, 2].map(channel => {
    const values = light.map(pixel => pixel[channel]).sort((a, b) => a - b);
    return values[values.length >> 1].toString(16).padStart(2, "0");
  }).join("");
}

// ---------- Eraser: remove the ink, keep the paper ----------

function eraserMode() {
  return document.querySelector('input[name="eraser-mode"]:checked')?.value || "erase";
}

function patchKey(edit) {
  return JSON.stringify([rectBox(edit), edit.strength ?? 3]);
}

// Box dilation of a 0/1 mask (separable running counts).
function dilate(mask, w, h, r) {
  const tmp = new Uint8Array(mask.length);
  const out = new Uint8Array(mask.length);
  for (let y = 0; y < h; y++) {
    const row = y * w;
    let count = 0;
    for (let x = 0; x <= Math.min(r, w - 1); x++) count += mask[row + x];
    for (let x = 0; x < w; x++) {
      tmp[row + x] = count > 0 ? 1 : 0;
      if (x + r + 1 < w) count += mask[row + x + r + 1];
      if (x - r >= 0) count -= mask[row + x - r];
    }
  }
  for (let x = 0; x < w; x++) {
    let count = 0;
    for (let y = 0; y <= Math.min(r, h - 1); y++) count += tmp[y * w + x];
    for (let y = 0; y < h; y++) {
      out[y * w + x] = count > 0 ? 1 : 0;
      if (y + r + 1 < h) count += tmp[(y + r + 1) * w + x];
      if (y - r >= 0) count -= tmp[(y - r) * w + x];
    }
  }
  return out;
}

function gridFilter(grid, gw, gh, r, pick) {
  const out = new Float32Array(grid.length);
  for (let gy = 0; gy < gh; gy++) {
    for (let gx = 0; gx < gw; gx++) {
      let value = grid[gy * gw + gx];
      for (let y = Math.max(0, gy - r); y <= Math.min(gh - 1, gy + r); y++) {
        for (let x = Math.max(0, gx - r); x <= Math.min(gw - 1, gx + r); x++) value = pick(value, grid[y * gw + x]);
      }
      out[gy * gw + gx] = value;
    }
  }
  return out;
}

// Finds dark marks (text, handwriting, lines) in a rendered area and rebuilds those
// pixels from the paper around them, keeping its color, gradient and grain. All
// other pixels become transparent, so the original background shows through
// unchanged. Strength 1-5: higher also removes fainter marks.
function eraseInk(image, strength = 3) {
  const { width: w, height: h, data } = image;
  const source = image.original || data.slice();  // read from here, write the patch to data
  const n = w * h;
  const lum = new Float32Array(n);
  for (let i = 0; i < n; i++) lum[i] = 0.299 * source[4 * i] + 0.587 * source[4 * i + 1] + 0.114 * source[4 * i + 2];

  // 1. Paper brightness: a bright percentile per cell, closed over neighboring cells
  //    so cells that are entirely ink take the paper level around them.
  const cell = clamp(Math.round(Math.min(w, h) * 0.12), 3, 48);
  const gw = Math.ceil(w / cell);
  const gh = Math.ceil(h / cell);
  let grid = new Float32Array(gw * gh);
  const values = [];
  for (let gy = 0; gy < gh; gy++) {
    for (let gx = 0; gx < gw; gx++) {
      values.length = 0;
      for (let y = gy * cell; y < Math.min(h, (gy + 1) * cell); y++) {
        for (let x = gx * cell; x < Math.min(w, (gx + 1) * cell); x++) values.push(lum[y * w + x]);
      }
      values.sort((a, b) => a - b);
      grid[gy * gw + gx] = values[Math.floor((values.length - 1) * 0.8)];
    }
  }
  grid = gridFilter(gridFilter(grid, gw, gh, 2, Math.max), gw, gh, 2, Math.min);
  const darkness = new Float32Array(n);  // how much darker than the paper each pixel is
  for (let y = 0; y < h; y++) {
    const fy = clamp((y + 0.5) / cell - 0.5, 0, gh - 1);
    const y0 = Math.floor(fy);
    const y1 = Math.min(gh - 1, y0 + 1);
    const ty = fy - y0;
    for (let x = 0; x < w; x++) {
      const fx = clamp((x + 0.5) / cell - 0.5, 0, gw - 1);
      const x0 = Math.floor(fx);
      const x1 = Math.min(gw - 1, x0 + 1);
      const tx = fx - x0;
      const paper = (grid[y0 * gw + x0] * (1 - tx) + grid[y0 * gw + x1] * tx) * (1 - ty)
        + (grid[y1 * gw + x0] * (1 - tx) + grid[y1 * gw + x1] * tx) * ty;
      darkness[y * w + x] = paper - lum[y * w + x];
    }
  }

  // 2. Thresholds from the paper's own noise, and relative to the darkest ink so
  //    a light background pattern is kept.
  const hist = new Uint32Array(511);
  for (let i = 0; i < n; i++) hist[clamp(Math.round(darkness[i]), -255, 255) + 255]++;
  const quantile = q => {
    let sum = 0;
    for (let k = 0; k < 511; k++) {
      sum += hist[k];
      if (sum >= q * n) return k - 255;
    }
    return 255;
  };
  const level = clamp(Math.round(strength), 1, 5) - 1;
  const center = quantile(0.25);
  const spread = Math.max(1, center - quantile(0.08));
  const ink = Math.max(0, quantile(0.995));
  const strong = clamp(Math.max(center + [8, 6.5, 5, 4, 3][level] * spread + 8, [0.5, 0.42, 0.33, 0.25, 0.16][level] * ink), 14, 120);
  const weak = Math.max(center + 2.5 * spread + 4, strong * 0.3);

  // 3. Ink mask: clear marks plus their soft edges, grown by a pixel for scan blur.
  //    JPEG scans also leave a lighter (or darker) halo around letters; pixels near
  //    the ink that stand out from the paper are rebuilt too, or a ghost would remain.
  const core = new Uint8Array(n);
  for (let i = 0; i < n; i++) core[i] = darkness[i] > strong ? 1 : 0;
  const near = dilate(core, w, h, 3);
  const mask = new Uint8Array(n);
  for (let i = 0; i < n; i++) mask[i] = core[i] || (near[i] && darkness[i] > weak) ? 1 : 0;
  const grown = dilate(mask, w, h, 1);
  const around = dilate(mask, w, h, Math.max(4, Math.round(cell / 3)));
  const bright = 3 * spread + 6;
  const fill = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    fill[i] = grown[i] || (around[i] && (darkness[i] < -bright || darkness[i] > weak * 0.6)) ? 1 : 0;
  }
  const halo = dilate(fill, w, h, 2);
  let clean = new Uint8Array(n);
  let cleanCount = 0;
  for (let i = 0; i < n; i++) cleanCount += clean[i] = halo[i] ? 0 : 1;
  if (cleanCount < n * 0.02) {
    clean = fill.map(value => 1 - value);
    cleanCount = clean.reduce((a, b) => a + b, 0);
  }

  // 4. Paper color per cell (for grain) and overall, from clean pixels.
  const cellColor = new Float32Array(gw * gh * 3);
  const cellCount = new Uint32Array(gw * gh);
  const overall = [0, 0, 0];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (!clean[i]) continue;
      const c = Math.floor(y / cell) * gw + Math.floor(x / cell);
      cellCount[c]++;
      for (let k = 0; k < 3; k++) {
        cellColor[c * 3 + k] += source[4 * i + k];
        overall[k] += source[4 * i + k];
      }
    }
  }
  for (let c = 0; c < gw * gh; c++) for (let k = 0; k < 3; k++) cellColor[c * 3 + k] /= cellCount[c] || 1;
  for (let k = 0; k < 3; k++) overall[k] = cleanCount ? overall[k] / cleanCount : 255;

  // 5. Fill: blend the nearest clean pixels left, right, above and below (keeps
  //    gradients), plus the grain of a random clean pixel nearby (keeps texture).
  const sum = new Float32Array(n * 3);
  const weight = new Float32Array(n);
  const gather = (i, j, distance) => {
    const wgt = 1 / distance;
    weight[i] += wgt;
    for (let k = 0; k < 3; k++) sum[i * 3 + k] += wgt * source[4 * j + k];
  };
  for (let y = 0; y < h; y++) {
    let last = -1;
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (clean[i]) last = x;
      else if (fill[i] && last >= 0) gather(i, y * w + last, x - last);
    }
    last = -1;
    for (let x = w - 1; x >= 0; x--) {
      const i = y * w + x;
      if (clean[i]) last = x;
      else if (fill[i] && last >= 0) gather(i, y * w + last, last - x);
    }
  }
  for (let x = 0; x < w; x++) {
    let last = -1;
    for (let y = 0; y < h; y++) {
      const i = y * w + x;
      if (clean[i]) last = y;
      else if (fill[i] && last >= 0) gather(i, last * w + x, y - last);
    }
    last = -1;
    for (let y = h - 1; y >= 0; y--) {
      const i = y * w + x;
      if (clean[i]) last = y;
      else if (fill[i] && last >= 0) gather(i, last * w + x, last - y);
    }
  }
  let seed = 0x9e3779b9;  // fixed seed: the same area always gives the same result
  const random = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const reach = Math.max(3, cell);
  // Viewers resample the patch and its transparency at most zoom levels, which blurs
  // its edge. A few opaque pixels copied unchanged from the page around the rebuilt
  // area keep that blurred edge on plain paper, and the transparent pixels next to it
  // keep the paper color too (not black), so no outline of the letters shows.
  const cover = dilate(fill, w, h, 3);
  const bleed = dilate(cover, w, h, 3);
  const inkPixels = [];
  let erased = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (core[i]) inkPixels.push(i);
      if (!fill[i]) {
        for (let k = 0; k < 3; k++) data[4 * i + k] = bleed[i] ? source[4 * i + k] : 0;
        data[4 * i + 3] = cover[i] ? 255 : 0;
        continue;
      }
      erased++;
      const base = weight[i]
        ? [sum[i * 3] / weight[i], sum[i * 3 + 1] / weight[i], sum[i * 3 + 2] / weight[i]]
        : cellCount[Math.floor(y / cell) * gw + Math.floor(x / cell)]
          ? [0, 1, 2].map(k => cellColor[(Math.floor(y / cell) * gw + Math.floor(x / cell)) * 3 + k])
          : overall;
      const grain = [0, 0, 0];
      for (let tries = 0; tries < 8; tries++) {
        const qx = x + Math.round((random() * 2 - 1) * reach);
        const qy = y + Math.round((random() * 2 - 1) * reach);
        if (qx < 0 || qy < 0 || qx >= w || qy >= h || !clean[qy * w + qx]) continue;
        const j = qy * w + qx;
        const c = Math.floor(qy / cell) * gw + Math.floor(qx / cell);
        for (let k = 0; k < 3; k++) grain[k] = source[4 * j + k] - cellColor[c * 3 + k];
        break;
      }
      for (let k = 0; k < 3; k++) data[4 * i + k] = clamp(Math.round(base[k] + grain[k] * 0.9), 0, 255);
      data[4 * i + 3] = 255;
    }
  }
  return { erased, ink: inkStats(inkPixels, source, w, cell) };
}

// Color, left edge, top and baseline (in pixels) of the first line of erased text,
// used to place new text where the old text was.
function inkStats(pixels, source, w, cell) {
  if (pixels.length < 12) return null;
  const rows = new Map();
  let first = Infinity;
  let last = -1;
  for (const i of pixels) {
    const y = Math.floor(i / w);
    rows.set(y, (rows.get(y) || 0) + 1);
    first = Math.min(first, y);
    last = Math.max(last, y);
  }
  // The first line ends at the first gap of empty rows.
  const gap = Math.max(2, Math.round(cell / 2));
  let end = first;
  for (let y = first, empty = 0; y <= last; y++) {
    if (rows.get(y)) {
      end = y;
      empty = 0;
    } else if (++empty > gap) break;
  }
  let peak = 0;
  for (let y = first; y <= end; y++) peak = Math.max(peak, rows.get(y) || 0);
  let top = first;
  while (top < end && (rows.get(top) || 0) < peak * 0.1) top++;
  let baseline = end;
  while (baseline > top && (rows.get(baseline) || 0) < peak * 0.3) baseline--;
  let left = Infinity;
  const channels = [[], [], []];
  for (const i of pixels) {
    const y = Math.floor(i / w);
    if (y < top || y > end) continue;
    left = Math.min(left, i % w);
    if (channels[0].length < 4000) for (let k = 0; k < 3; k++) channels[k].push(source[4 * i + k]);
  }
  const color = "#" + channels.map(values => {
    values.sort((a, b) => a - b);
    return values[values.length >> 1].toString(16).padStart(2, "0");
  }).join("");
  return { color, left, top, baseline: baseline + 1 };
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

// Minimal PNG writer for 8-bit gray (1 channel) or RGB (3 channels) pixels.
async function encodePng(width, height, pixels, channels) {
  const stride = width * channels + 1;
  const raw = new Uint8Array(stride * height);
  for (let y = 0; y < height; y++) raw.set(pixels.subarray(y * width * channels, (y + 1) * width * channels), y * stride + 1);
  const stream = new Blob([raw]).stream().pipeThrough(new CompressionStream("deflate"));
  const compressed = new Uint8Array(await new Response(stream).arrayBuffer());
  const chunk = (type, body) => {
    const bytes = new Uint8Array(12 + body.length);
    const view = new DataView(bytes.buffer);
    view.setUint32(0, body.length);
    for (let i = 0; i < 4; i++) bytes[4 + i] = type.charCodeAt(i);
    bytes.set(body, 8);
    let crc = 0xffffffff;
    for (let i = 4; i < 8 + body.length; i++) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    view.setUint32(8 + body.length, (crc ^ 0xffffffff) >>> 0);
    return bytes;
  };
  const header = new Uint8Array(13);
  new DataView(header.buffer).setUint32(0, width);
  new DataView(header.buffer).setUint32(4, height);
  header.set([8, channels === 3 ? 2 : 0, 0, 0, 0], 8);  // 8-bit RGB or gray, no interlace
  const signature = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
  return new Blob([signature, chunk("IHDR", header), chunk("IDAT", compressed), chunk("IEND", new Uint8Array())], { type: "image/png" });
}

// Renders the original page under an erased area, removes the ink in the browser and
// uploads the result as a transparent patch.
async function makePatch(edit) {
  const box = rectBox(edit);
  const blob = await api("clip", { data: { page: edit.page, rect: box } });
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(bitmap, 0, 0);
  bitmap.close();
  const image = context.getImageData(0, 0, canvas.width, canvas.height);
  const { erased, ink } = eraseInk(image, edit.strength ?? 3);
  // Colors and transparency go up as two images. An RGBA image would have its
  // transparent pixels turned black, which shows as a dark outline once a PDF viewer
  // resamples the patch at another zoom.
  const count = canvas.width * canvas.height;
  const colors = new Uint8Array(count * 3);
  const alpha = new Uint8Array(count);
  for (let i = 0; i < count; i++) {
    colors[3 * i] = image.data[4 * i];
    colors[3 * i + 1] = image.data[4 * i + 1];
    colors[3 * i + 2] = image.data[4 * i + 2];
    alpha[i] = image.data[4 * i + 3];
  }
  const { asset } = await api("image", { raw: await encodePng(canvas.width, canvas.height, colors, 3) });
  const { asset: mask } = await api("image", { raw: await encodePng(canvas.width, canvas.height, alpha, 1) });
  // Convert ink measurements from patch pixels to page points.
  const sx = (box[2] - box[0]) / canvas.width;
  const sy = (box[3] - box[1]) / canvas.height;
  const points = ink && {
    color: ink.color, left: box[0] + ink.left * sx, top: box[1] + ink.top * sy, baseline: box[1] + ink.baseline * sy
  };
  return { ...edit, asset, mask, patchKey: patchKey(edit), erased, ink: points };
}

// Makes sure every erased area on this page has a patch for its current position.
async function withPatches(edits) {
  let changed = false;
  const result = [];
  for (const edit of edits) {
    if (edit.page === state.page && edit.type === "whiteout" && edit.mode === "erase" && edit.patchKey !== patchKey(edit)) {
      result.push(await makePatch(edit));
      changed = true;
    } else {
      result.push(edit);
    }
  }
  return changed ? result : edits;
}

// ---------- Selected object: preview, frame and panel ----------

function pending(live) {
  const edit = live && live.id !== null && state.edits.find(item => item.id === live.id);
  return !!edit && FIELDS.some(key => JSON.stringify(edit[key]) !== JSON.stringify(live[key]));
}

function merged(live) {
  return state.edits.map(edit => edit.id === live.id ? structuredClone(live) : edit);
}

function svgNode(name, attributes) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function drawLive() {
  ui.live.replaceChildren();
  const live = state.live;
  if (!live || !state.result || live.page !== state.page) return;
  ui.live.setAttribute("viewBox", "0 0 " + state.result.width + " " + state.result.height);
  if (live.type === "whiteout") {
    // The committed whiteout stays in the page image (so text on top of it stays
    // visible); only an unsaved position or color is previewed here.
    if (!state.edits.some(edit => edit.id === live.id) || pending(live)) {
      const [x0, y0, x1, y1] = rectBox(live);
      // An erased area is rebuilt by the server when released; until then mark the area.
      ui.live.append(svgNode("rect", {
        x: x0, y: y0, width: x1 - x0, height: y1 - y0,
        fill: live.mode === "erase" ? "#20a76c" : live.color || "#ffffff",
        "fill-opacity": live.mode === "erase" ? 0.14 : 0.85
      }));
    }
  } else if (live.text) {
    const font = fontOf(live);
    const width = textWidth(live);
    const node = svgNode("text", {
      x: live.start[0], y: live.start[1], "font-size": live.size, "font-family": font.family,
      "font-weight": font.weight, fill: live.color
    });
    if (width > 0) {
      node.setAttribute("textLength", width);
      node.setAttribute("lengthAdjust", "spacingAndGlyphs");
    }
    node.style.whiteSpace = "pre";
    node.textContent = live.text;
    ui.live.append(node);
  } else {
    const font = fontOf(live);
    const [x, y] = live.start;
    ui.live.append(svgNode("line", {
      class: "caret", x1: x, x2: x, y1: y - font.ascent * live.size, y2: y + font.descent * live.size,
      stroke: live.color, "stroke-width": Math.max(0.6, live.size * 0.06)
    }));
  }
  placeFrame();
}

function placeFrame() {
  const frame = ui.overlay.querySelector(".frame");
  if (!frame || !state.live) return;
  let box = objectBox(state.live);
  if (state.live.type === "text") {
    // Small text gets a roomier frame so its handles do not cover each other.
    const scale = ui.sheet.getBoundingClientRect().width / state.result.width;
    const least = (coarse.matches ? 34 : 24) / (scale || 1);
    const padX = Math.max(0, (least - (box[2] - box[0])) / 2);
    const padY = Math.max(0, (least - (box[3] - box[1])) / 2);
    box = [box[0] - padX, box[1] - padY, box[2] + padX, box[3] + padY];
  }
  place(frame, box);
  frame.classList.toggle("empty", state.live.type === "text" && !state.live.text);
}

function syncLiveFields() {
  const live = state.live;
  if (live?.type !== "text") return;
  ui.size.value = Math.round(live.size * 10) / 10;
  ui.stretch.value = Math.round((live.stretch ?? 1) * 100);
  ui.color.value = live.color;
}

function showLivePanel(focusText = false) {
  const live = state.live;
  const isText = live.type === "text";
  ui.selection.hidden = false;
  ui.sample.hidden = true;
  ui["selection-warning"].hidden = true;
  for (const id of ["text-field", "font-field", "size-field", "width-field", "color-field"]) ui[id].hidden = !isText;
  const erase = live.mode === "erase";
  ui["url-field"].hidden = true;
  ui["text-here"].hidden = isText;
  ui["fill-field"].hidden = isText || erase;
  ui["strength-field"].hidden = !erase;
  ui["nudge-field"].hidden = false;
  ui.font.options[0].hidden = true;
  ui.apply.hidden = !isText;
  ui.apply.textContent = live.id === null ? "Add text" : "Apply";
  ui.cancel.textContent = isText ? "Cancel" : "Done";
  ui.remove.hidden = live.id === null;
  ui.remove.textContent = isText ? "Delete this text" : erase ? "Restore the erased content" : "Delete this whiteout";
  ui.restore.hidden = true;
  if (isText) {
    ui.value.value = live.text;
    ui.font.value = live.font;
    syncLiveFields();
  } else if (erase) {
    ui.strength.value = live.strength ?? 3;
  } else {
    ui.fill.value = live.color || "#ffffff";
  }
  refreshInstruction();
  if (focusText && isText) ui.value.focus();
}

function restoreLive(live) {
  state.live = live ?? null;
  if (state.live) showLivePanel();
  else closeSelection();
  updateOverlay();
  drawLive();
  refreshInstruction();
}

function selectObject(id) {
  const edit = state.edits.find(item => item.id === id);
  if (!edit) return false;
  displayError();
  ui["edit-status"].textContent = "";
  state.live = structuredClone(edit);
  showLivePanel();
  updateOverlay();
  drawLive();
  return true;
}

function startDraft(start, extra = {}) {
  const draft = { id: null, page: state.page, type: "text", start, text: "", ...state.textStyle, stretch: 1, ...extra };
  draft.start = fitText(draft, start);
  displayError();
  ui["edit-status"].textContent = "";
  state.live = draft;
  showLivePanel(true);
  updateOverlay();
  drawLive();
}

// Saves the object's changes (geometry, text, font...) as one undo step.
async function commitLive(edits, message, previous) {
  const ok = await busy(async () => {
    const before = state.edits;
    await render(edits);
    state.undo.push(before);
    state.redo.length = 0;
    ui["edit-status"].textContent = message;
  });
  if (!ok) restoreLive(previous);
  return ok;
}

// Deselects the object. Unsaved changes are kept unless `discard` is set.
async function finishLive(discard = false) {
  const live = state.live;
  if (!live) return true;
  if (state.busy) return false;
  clearTimeout(state.nudgeTimer);
  let edits = state.edits;
  let message = "Changes applied.";
  if (!discard && live.id === null && live.text.trim()) {
    edits = [...edits, { ...structuredClone(live), id: nextId++ }];
    message = "Text added.";
  } else if (!discard && pending(live)) {
    edits = merged(live);
  }
  state.live = null;
  closeSelection();
  drawLive();
  refreshInstruction();
  if (edits === state.edits && state.hidden === null) return true;
  const ok = await busy(async () => {
    const before = state.edits;
    await render(edits);
    if (edits !== before) {
      state.undo.push(before);
      state.redo.length = 0;
      ui["edit-status"].textContent = message;
    }
  });
  if (!ok) restoreLive(live);
  return ok;
}

function applyLive() {
  const live = state.live;
  if (!live || state.busy) return;
  if (live.type !== "text") {
    finishLive();
    return;
  }
  if (!live.text.trim()) {
    displayError("Type the text to add.");
    ui.value.focus();
    return;
  }
  const size = Number(ui.size.value);
  const width = Number(ui.stretch.value);
  if (!(size >= 4 && size <= 144)) {
    displayError("Choose a size from 4 to 144 pt.");
    return;
  }
  if (!(width >= 25 && width <= 400)) {
    displayError("Choose a width from 25% to 400%.");
    return;
  }
  state.textStyle = { font: live.font, size: live.size, color: live.color };
  if (live.id === null) {
    const edit = { ...structuredClone(live), id: nextId++ };
    state.live = structuredClone(edit);
    updateOverlay();
    commitLive([...state.edits, edit], "Text added. Drag it to move it, or drag a corner to resize it.", live)
      .then(ok => {
        if (!ok || state.live?.id !== edit.id) return;
        showLivePanel();
        ui.value.blur();
      });
  } else if (pending(live)) {
    commitLive(merged(live), "Changes applied.", live);
  } else {
    finishLive();
  }
}

async function deleteLive() {
  const live = state.live;
  if (!live || state.busy) return;
  if (live.id === null) {
    finishLive(true);
    return;
  }
  clearTimeout(state.nudgeTimer);
  state.live = null;
  closeSelection();
  drawLive();
  refreshInstruction();
  const ok = await busy(async () => {
    const before = state.edits;
    await render(before.filter(edit => edit.id !== live.id));
    state.undo.push(before);
    state.redo.length = 0;
    ui["edit-status"].textContent = live.type === "text" ? "Text deleted." : live.mode === "erase" ? "Erased content restored." : "Whiteout deleted.";
  });
  if (!ok) restoreLive(live);
}

function liveInput(changes) {
  const live = state.live;
  if (live?.type !== "text" || state.gesture) return;
  const next = { ...live, ...changes };
  next.start = fitText(next, next.start);
  state.live = next;
  drawLive();
}

function nudge(dx, dy) {
  const live = state.live;
  if (!live || state.busy || state.gesture) return;
  const g = { origin: live, box: objectBox(live), handle: "move" };
  state.live = live.type === "text" ? dragText(g, dx, dy) : dragBox(g, dx, dy);
  drawLive();
  if (live.id === null) return;
  // Save a burst of nudges as one undo step.
  const id = live.id;
  const committed = structuredClone(state.edits.find(edit => edit.id === id));
  clearTimeout(state.nudgeTimer);
  state.nudgeTimer = setTimeout(() => {
    if (state.live?.id === id && !state.busy && !state.gesture && pending(state.live)) {
      commitLive(merged(state.live), "Moved.", committed);
    }
  }, 450);
}

function commitFill(color) {
  const live = state.live;
  if (live?.type !== "whiteout" || live.mode === "erase" || live.id === null || state.busy) return;
  const committed = structuredClone(state.edits.find(edit => edit.id === live.id));
  state.live = { ...live, color };
  ui.fill.value = color;
  drawLive();
  if (committed.color === color) return;
  commitLive(merged(state.live), "Fill color updated.", committed);
}

async function addWhiteout(start, end) {
  const box = rectBox({ start, end });
  const mode = eraserMode();
  const previous = state.live;
  const edits = previous && pending(previous) ? merged(previous) : state.edits;
  const edit = { id: nextId++, page: state.page, type: "whiteout", start: box.slice(0, 2), end: box.slice(2) };
  if (mode === "erase") Object.assign(edit, { mode: "erase", strength: 3 });
  else edit.color = mode === "match" ? sampleBackground(box, true) : "#ffffff";
  state.live = structuredClone(edit);
  showLivePanel();
  updateOverlay();
  drawLive();
  const ok = await commitLive([...edits, edit], mode === "erase"
    ? "Text erased. Drag the area to move it, or drag a handle to resize it."
    : "Whiteout added. Drag it to move it, or drag a handle to resize it.", previous);
  if (ok && mode === "erase" && !state.edits.find(item => item.id === edit.id)?.erased) {
    ui["edit-status"].textContent = "No text was found in this area. Raise the strength, or select an area with text.";
  }
}

function selectFromKeyboard(id) {
  if (state.busy) return;
  const live = state.live;
  if (live && (pending(live) || (live.id === null && live.text.trim()))) {
    finishLive();
    return;
  }
  if (!selectObject(id)) return;
  if (state.live.type === "text") busy(() => render(state.edits));
  ui["nudge-field"].querySelector("button").focus();
}

// ---------- Pointer gestures on objects ----------

function startGesture(event, target) {
  const id = target.dataset.object === "draft" ? null : Number(target.dataset.object);
  const live = state.live;
  const wasSelected = !!live && live.id === id;
  if (!wasSelected) {
    // Save the current object first; the next press picks up the other one.
    if (live && (pending(live) || (live.id === null && live.text.trim()))) {
      finishLive();
      return;
    }
    if (!selectObject(id)) return;
  }
  event.preventDefault();
  clearTimeout(state.nudgeTimer);
  state.gesture = {
    pointer: event.pointerId,
    handle: event.target.closest("[data-handle]")?.dataset.handle || "move",
    start: pagePoint(event),
    client: [event.clientX, event.clientY],
    origin: structuredClone(state.live),
    box: objectBox(state.live),
    moved: false,
    wasSelected
  };
  ui.sheet.setPointerCapture(event.pointerId);
}

function moveGesture(event) {
  const g = state.gesture;
  if (!g.moved && Math.hypot(event.clientX - g.client[0], event.clientY - g.client[1]) < 4) return;
  g.moved = true;
  const [x, y] = pagePoint(event);
  const dx = x - g.start[0];
  const dy = y - g.start[1];
  state.live = g.origin.type === "text" ? dragText(g, dx, dy) : dragBox(g, dx, dy);
  drawLive();
  syncLiveFields();
}

function endGesture() {
  const g = state.gesture;
  state.gesture = null;
  const live = state.live;
  if (!live) return;
  if (!g.moved) {
    const now = Date.now();
    // A second tap on selected text opens it for typing.
    if (live.type === "text" && g.wasSelected && now - state.lastTap < 450) {
      ui.value.focus();
      ui.value.select();
    }
    state.lastTap = now;
    if (live.type === "text" && live.id !== null && state.hidden !== live.id) busy(() => render(state.edits));
    return;
  }
  if (live.id === null) return;
  commitLive(merged(live), g.handle === "move" ? "Moved." : "Resized.", g.origin);
}

function textTap(point) {
  const live = state.live;
  if (live?.id === null) {
    state.live = { ...live, start: fitText(live, point) };
    drawLive();
    return;
  }
  if (live) {
    finishLive();
    return;
  }
  startDraft(point);
}

function showRegion(start, end) {
  const { width, height } = state.result;
  ui.region.style.left = (100 * Math.min(start[0], end[0]) / width) + "%";
  ui.region.style.top = (100 * Math.min(start[1], end[1]) / height) + "%";
  ui.region.style.width = (100 * Math.abs(start[0] - end[0]) / width) + "%";
  ui.region.style.height = (100 * Math.abs(start[1] - end[1]) / height) + "%";
}

// ---------- Event wiring ----------

ui.open.onclick = () => ui["pdf-file"].click();
ui["pdf-file"].onchange = event => {
  openPdf(event.target.files[0]);
  event.target.value = "";
};
ui["password-dialog"].onclose = () => {
  const pdf = pendingPdf;
  pendingPdf = null;
  const password = ui.password.value;
  ui.password.value = "";
  if (ui["password-dialog"].returnValue === "confirm") openPdf(pdf, password);
};

// Leaves the editor (used by "All tools"); unsaved edits are lost, so ask first.
function leaveEditor() {
  if (!state.token) return true;
  if (state.edits.length && !confirm("Leave the editor? Edits you have not downloaded will be lost.")) return false;
  api("close").catch(() => {});
  clearTimeout(state.nudgeTimer);
  Object.assign(state, { token: "", file: "", edits: [], undo: [], redo: [], live: null, result: null, gesture: null, drag: null });
  ui.work.hidden = ui.export.hidden = ui["compress-open"].hidden = ui.filename.hidden = true;
  closeSelection();
  return true;
}
ui.tools.onclick = event => {
  const button = event.target.closest("[data-tool]");
  if (button) activate(button.dataset.tool);
};
ui.back.onclick = () => go(state.page - 1);
ui.next.onclick = () => go(state.page + 1);
ui["page-value"].onchange = event => go(Number(event.target.value) - 1);
ui["page-value"].onkeydown = event => {
  if (event.key === "Enter") go(Number(event.target.value) - 1);
};
ui.undo.onclick = () => moveHistory(state.undo, state.redo, "Edit undone.");
ui.redo.onclick = () => moveHistory(state.redo, state.undo, "Edit redone.");
ui.fit.onclick = () => { state.zoom = null; resize(); };
ui.minus.onclick = () => {
  state.zoom = Math.max(0.25, ui.sheet.offsetWidth / state.result.width / 1.2);
  resize();
};
ui.plus.onclick = () => {
  state.zoom = Math.min(3, ui.sheet.offsetWidth / state.result.width * 1.2);
  resize();
};
new ResizeObserver(resize).observe(ui.stage);
ui.cancel.onclick = () => {
  const hadLive = !!state.live;
  if (hadLive) finishLive(true);
  else closeSelection();
  displayError();
  // Text hit buttons are rebuilt when the selection is cleared.
  if (!hadLive && previousFocus?.isConnected) previousFocus.focus();
  else ui.tools.querySelector('[aria-pressed="true"]').focus();
};
ui.remove.onclick = () => {
  if (state.live) deleteLive();
  else replace("");
};
ui.restore.onclick = () => commit(
  state.edits.filter(edit => !(edit.page === state.page && edit.type === "replace" && edit.span === state.selection.span)),
  null, "Original text restored."
);
ui["edit-form"].onsubmit = event => {
  event.preventDefault();
  if (state.live) {
    applyLive();
    return;
  }
  if (!state.selection) return;
  if (state.tool === "replace") {
    replace(ui.value.value);
    return;
  }
  addEdit(state.tool, {
    ...state.selection, text: ui.value.value, font: ui.font.value, size: ui.size.value,
    color: ui.color.value, url: ui.url.value
  });
};
// Live preview while the selected text is edited in the panel.
ui.value.addEventListener("input", () => liveInput({ text: ui.value.value }));
ui.value.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && state.live?.type === "text") {
    event.preventDefault();
    applyLive();
  }
});
ui.font.addEventListener("change", () => liveInput({ font: ui.font.value }));
ui.size.addEventListener("input", () => {
  const size = Number(ui.size.value);
  if (size >= 4 && size <= 144) liveInput({ size });
});
ui.stretch.addEventListener("input", () => {
  const width = Number(ui.stretch.value);
  if (width >= 25 && width <= 400) liveInput({ stretch: width / 100 });
});
ui.color.addEventListener("input", () => liveInput({ color: ui.color.value }));
ui["nudge-field"].onclick = event => {
  const button = event.target.closest("[data-nudge]");
  if (!button) return;
  const [dx, dy] = button.dataset.nudge.split(",").map(Number);
  nudge(dx, dy);
};
ui.fill.addEventListener("input", () => {
  if (state.live?.type !== "whiteout") return;
  state.live = { ...state.live, color: ui.fill.value };
  drawLive();
});
ui.fill.addEventListener("change", () => commitFill(ui.fill.value));
ui["match-fill"].onclick = () => {
  if (state.live?.type === "whiteout") commitFill(sampleBackground(rectBox(state.live), false));
};
ui["white-fill"].onclick = () => commitFill("#ffffff");
ui["text-here"].onclick = async () => {
  const live = state.live;
  if (live?.type !== "whiteout" || state.busy) return;
  const [x0, y0, x1, y1] = rectBox(live);
  const ink = live.mode === "erase" && live.ink;
  await activate("text");
  if (state.tool !== "text" || state.live) return;
  const font = FONTS[state.textStyle.font] || FONTS.Helvetica;
  if (ink && ink.baseline - ink.top > 2) {
    // Start where the erased text was, at its size and in its ink color.
    const size = Math.round(clamp((ink.baseline - ink.top) / font.cap, 4, 144) * 10) / 10;
    startDraft([ink.left, ink.baseline], { size, color: ink.color });
    return;
  }
  // Otherwise fit the new text to the height of the area and center it vertically.
  const lineHeight = font.ascent + font.descent;
  const height = y1 - y0;
  const size = Math.round(clamp(height * 0.8 / lineHeight, 4, 144) * 10) / 10;
  const baseline = y0 + (height - lineHeight * size) / 2 + font.ascent * size;
  startDraft([x0 + Math.min(3, (x1 - x0) * 0.05), baseline], { size });
};
ui.strength.addEventListener("change", () => {
  const live = state.live;
  if (live?.mode !== "erase" || live.id === null || state.busy) return;
  const committed = structuredClone(state.edits.find(edit => edit.id === live.id));
  state.live = { ...live, strength: Number(ui.strength.value) };
  commitLive(merged(state.live), "Erase strength updated.", committed).then(ok => {
    if (ok && !state.live?.erased) ui["edit-status"].textContent = "No text was found in this area at this strength.";
  });
});
ui["pick-image"].onclick = () => ui["image-file"].click();
ui["image-file"].onchange = event => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  busy(async () => {
    const { asset } = await api("image", { raw: file });
    state.asset = { id: asset, name: file.name };
    refreshInstruction();
  });
};
ui.sheet.onpointerdown = event => {
  if (state.busy || !state.result || event.button !== 0 || state.gesture || state.drag) return;
  const object = event.target.closest("[data-object]");
  if (object) {
    startGesture(event, object);
    return;
  }
  if (state.tool === "replace") return;
  if (state.tool === "text") {
    // Placed on release, so a finger can still scroll the page.
    state.tap = { pointer: event.pointerId, x: event.clientX, y: event.clientY };
    return;
  }
  if (state.tool === "image" && !state.asset) {
    ui["image-file"].click();
    return;
  }
  if (state.tool === "draw") {
    // Freehand pen: collect points and preview the stroke until the pointer is released.
    if (state.live) finishLive();
    const first = coords(event);
    ui.live.replaceChildren();
    ui.live.setAttribute("viewBox", "0 0 " + state.result.width + " " + state.result.height);
    const stroke = svgNode("polyline", { fill: "none", stroke: ui["pen-color"].value, "stroke-width": ui["pen-width"].value,
                                         "stroke-linecap": "round", "stroke-linejoin": "round", points: first.join(",") });
    ui.live.append(stroke);
    state.ink = { pointer: event.pointerId, points: [first], stroke };
    ui.sheet.setPointerCapture(event.pointerId);
    return;
  }
  state.drag = { start: coords(event), pointer: event.pointerId };
  ui.sheet.setPointerCapture(event.pointerId);
  showRegion(state.drag.start, state.drag.start);
  ui.region.hidden = false;
};
ui.sheet.onpointermove = event => {
  if (state.gesture?.pointer === event.pointerId) moveGesture(event);
  else if (state.drag?.pointer === event.pointerId) showRegion(state.drag.start, coords(event));
  else if (state.ink?.pointer === event.pointerId) {
    const next = coords(event);
    const last = state.ink.points.at(-1);
    if (Math.hypot(next[0] - last[0], next[1] - last[1]) < 0.8) return;  // keep the stroke light
    state.ink.points.push(next);
    state.ink.stroke.setAttribute("points", state.ink.points.map(p => p.join(",")).join(" "));
  }
};
ui.sheet.onpointercancel = event => {
  if (state.gesture?.pointer === event.pointerId) {
    state.live = state.gesture.origin;
    state.gesture = null;
    drawLive();
    syncLiveFields();
  }
  if (state.drag?.pointer === event.pointerId) state.drag = null;
  if (state.tap?.pointer === event.pointerId) state.tap = null;
  if (state.ink?.pointer === event.pointerId) {
    state.ink = null;
    drawLive();
  }
  ui.region.hidden = true;
};
ui.sheet.onpointerup = event => {
  if (state.gesture?.pointer === event.pointerId) {
    endGesture();
    return;
  }
  if (state.ink?.pointer === event.pointerId) {
    const { points } = state.ink;
    state.ink = null;
    if (points.length < 2) {
      drawLive();
      return;
    }
    addEdit("ink", { start: points[0], points, color: ui["pen-color"].value, width: Number(ui["pen-width"].value) });
    return;
  }
  if (state.tap?.pointer === event.pointerId) {
    const tap = state.tap;
    state.tap = null;
    if (!state.busy && Math.hypot(event.clientX - tap.x, event.clientY - tap.y) <= 10) textTap(coords(event));
    return;
  }
  if (state.drag?.pointer !== event.pointerId) return;
  const { start } = state.drag;
  const end = coords(event);
  state.drag = null;
  ui.region.hidden = true;
  const tooSmall = state.tool === "line"
    ? Math.hypot(start[0] - end[0], start[1] - end[1]) < 3
    : Math.min(Math.abs(start[0] - end[0]), Math.abs(start[1] - end[1])) < 2;
  if (tooSmall) {
    if (state.live) finishLive();
    else displayError(state.tool === "line" ? "Drag to draw a longer line." : "Drag to select an area on the page.");
    return;
  }
  if (["link", "rectangle", "ellipse", "line"].includes(state.tool)) openSelection({ start, end });
  else if (state.tool === "whiteout") addWhiteout(start, end);
  else addEdit(state.tool, { start, end, asset: state.asset?.id });
};
// ---------- Preview before downloading (the edited PDF, or the compressed one) ----------

const finalPreview = { viewer: null, onClose: null, onDownload: null };
const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

function forgetUploads(ids) {
  ids = ids.filter(Boolean);
  if (ids.length) {
    (window.pageBurrowRequest || fetch)("/api/forget", { method: "POST", headers: { "X-Local-Editor": "1", "Content-Type": "application/json" }, body: JSON.stringify({ ids }) }).catch(() => {});
  }
}

// The result is shown page by page, and next to the PDF it was made from, before it is downloaded.
function openPreview({ url, name, resultId, beforeId, heading, summary, resultLabel, beforeLabel, backText, onClose = null, onDownload = null }) {
  closePreview();
  ui["preview-heading"].textContent = heading;
  ui["preview-summary"].textContent = summary;
  ui["preview-download"].href = url;
  ui["preview-download"].download = name;
  ui["preview-back"].textContent = backText;
  Object.assign(finalPreview, { onClose, onDownload });
  ui["preview-dialog"].showModal();
  finalPreview.viewer = new ResultPreview(ui["preview-body"], {
    files: [{ id: resultId, name }], before: beforeId ? { id: beforeId } : null, heading: "", resultLabel, beforeLabel
  });
  finalPreview.viewer.stage.focus({ preventScroll: true });
}

function closePreview() {
  finalPreview.viewer?.destroy();
  finalPreview.viewer = null;
  const done = finalPreview.onClose;
  finalPreview.onClose = null;
  done?.();
  if (ui["preview-dialog"].open) ui["preview-dialog"].close();
}
ui["preview-back"].onclick = () => closePreview();
ui["preview-dialog"].addEventListener("close", () => closePreview()); // also Esc
ui["preview-download"].addEventListener("click", () => {
  const done = finalPreview.onDownload;
  setTimeout(() => { // after the browser has started the download
    closePreview();
    done?.();
  }, 0);
});

ui.export.onclick = async () => {
  if (!(await finishLive())) return;
  busy(async () => {
    const response = await (window.pageBurrowRequest || fetch)("/api/export", {
      method: "POST", cache: "no-store", body: JSON.stringify({ edits: state.edits }),
      headers: { "X-Local-Editor": "1", "X-Document": state.token, "X-Preview": "1", "Content-Type": "application/json" }
    });
    if (!response.ok) {
      const isJson = response.headers.get("Content-Type")?.includes("application/json");
      throw new Error(isJson ? (await response.json()).error : "Could not reach the local editor.");
    }
    const url = URL.createObjectURL(await response.blob());
    const resultId = response.headers.get("X-Preview-Id");
    const pages = new Set(state.edits.map(edit => edit.page)).size;
    openPreview({
      url, resultId, beforeId: response.headers.get("X-Before-Id"),
      name: state.file.replace(/\.pdf$/i, "") + "-edited.pdf",
      heading: "Check your PDF before downloading",
      summary: state.edits.length
        ? `${plural(state.edits.length, "change")} on ${plural(pages, "page")}. Choose Original or Side by side to compare with the PDF you opened.`
        : "You have not made any changes yet, so this is the PDF as you opened it.",
      resultLabel: "Edited", beforeLabel: "Original", backText: "Back to editing",
      onClose: () => {
        forgetUploads([resultId]);
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      },
      onDownload: () => { ui["edit-status"].textContent = "PDF downloaded."; }
    });
  });
};
// ---------- Compress (a chosen PDF, or the open document with its edits) ----------

const MAX_COMPRESS = 200_000_000;
const compress = { file: null, url: null, busy: false, preview: null };
const formatMB = bytes => new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(bytes / 1e6) + " MB";

// Server copies kept for the preview: the result, and the PDF before compressing when it
// was made just for this (with edits; otherwise it is the opened PDF, kept for the session).
function forgetCompressPreview() {
  const kept = compress.preview;
  compress.preview = null;
  if (kept) forgetUploads([kept.resultId, kept.temporaryBefore ? kept.beforeId : null]);
}

function compressResult(kind, title, summary = "", note = "") {
  if (compress.url) URL.revokeObjectURL(compress.url);
  compress.url = null;
  forgetCompressPreview();
  ui["compress-preview"].hidden = true;
  ui["compress-download"].hidden = true;
  ui["compress-download"].removeAttribute("href");
  ui["compress-result"].hidden = !kind;
  ui["compress-result"].dataset.kind = kind;
  ui["compress-title"].textContent = title;
  ui["compress-summary"].textContent = summary;
  ui["compress-note"].textContent = note;
}

function openCompress(file) {
  if (compress.busy) return;
  displayError();
  if (file && ((!file.name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") || !file.size || file.size > MAX_COMPRESS)) {
    displayError("Choose a PDF that is not empty and no larger than 200 MB.");
    return;
  }
  compress.file = file || null;
  ui["compress-source"].textContent = file
    ? file.name + " · " + formatMB(file.size)
    : state.file + (state.edits.length ? " · including your edits" : "");
  compressResult("", "");
  ui["compress-run"].hidden = false;
  if (!ui["compress-dialog"].open) ui["compress-dialog"].showModal();
}

async function runCompress() {
  if (compress.busy) return;
  const value = Number(ui["compress-target"].value);
  if (!(value >= 0.01 && value <= 200)) {
    compressResult("error", "Check the maximum size", "Enter a size from 0.01 to 200 MB.");
    ui["compress-target"].focus();
    return;
  }
  const target = String(Math.round(value * 1000) / 1000);
  const page = ui["compress-page"].value;
  const mode = new FormData(ui["compress-form"]).get("compress-mode");
  const query = new URLSearchParams({ target, page, mode });
  const file = compress.file;
  const headers = { "X-Local-Editor": "1" };
  let body;
  if (file) {
    headers["Content-Type"] = "application/pdf";
    body = file;
  } else {
    headers["Content-Type"] = "application/json";
    headers["X-Document"] = state.token;
    headers["X-Preview"] = "1";
    body = JSON.stringify({ edits: state.edits });
  }
  compress.busy = true;
  for (const control of ui["compress-form"].elements) control.disabled = true;
  ui["compress-run"].textContent = "Compressing…";
  compressResult("pending", "Compressing PDF", "Large scans can take a minute or more.");
  try {
    const response = await (window.pageBurrowRequest || fetch)("/api/compress?" + query, { method: "POST", headers, body, cache: "no-store" });
    if (!response.ok) {
      const details = response.headers.get("Content-Type")?.includes("application/json") ? await response.json() : {};
      compressResult("error", "Could not compress the PDF", details.error || "The PDF could not be compressed.");
      return;
    }
    const blob = await response.blob();
    const limit = Math.round(value * 1e6);
    const hit = blob.size <= limit;
    const pages = response.headers.get("X-PDF-Pages");
    const jpeg = response.headers.get("X-Compression") === "jpeg";
    const before = file ? formatMB(file.size) + " → " : "";
    const summary = before + formatMB(blob.size) + " · " + pages + (pages === "1" ? " page" : " pages") + " · " + (page === "a4" ? "A4" : "Original page size");
    let note = jpeg ? "JPEG compression applied at the original image dimensions." : "Image pixels preserved.";
    if (!hit) note += " This file is larger than your " + formatMB(limit) + " limit.";
    compressResult(hit ? "ok" : "miss", hit ? "PDF meets your size limit" : "Size limit could not be reached", summary, note);
    compress.url = URL.createObjectURL(blob);
    const base = (file ? file.name : state.file).replace(/\.pdf$/i, "") + (file ? "" : "-edited");
    ui["compress-download"].href = compress.url;
    ui["compress-download"].download = base + (page === "a4" ? "_A4" : "") + (hit ? "_compressed.pdf" : "_best_effort.pdf");
    ui["compress-download"].hidden = false;
    ui["compress-run"].hidden = true;
    const resultId = response.headers.get("X-Preview-Id");
    if (resultId) {
      compress.preview = { resultId, beforeId: response.headers.get("X-Before-Id"), temporaryBefore: !file && state.edits.length > 0 };
      ui["compress-preview"].hidden = false;
    }
  } catch {
    compressResult("error", "Connection interrupted", "Check that PageBurrow is still running, then try again.");
  } finally {
    compress.busy = false;
    for (const control of ui["compress-form"].elements) control.disabled = false;
    ui["compress-run"].textContent = "Compress";
  }
}

ui["compress-open"].onclick = async () => {
  if (state.busy || !(await finishLive())) return;
  openCompress(null);
};
ui["compress-form"].onsubmit = event => {
  event.preventDefault();
  runCompress();
};
// Changing a setting after a result offers to compress again.
ui["compress-form"].oninput = () => {
  if (compress.busy || !ui["compress-run"].hidden) return;
  compressResult("", "");
  ui["compress-run"].hidden = false;
};
ui["compress-preview"].onclick = () => {
  const kept = compress.preview;
  if (!kept) return;
  openPreview({
    url: compress.url, name: ui["compress-download"].download, resultId: kept.resultId, beforeId: kept.beforeId,
    heading: "Check the compressed PDF",
    summary: ui["compress-summary"].textContent + ". Zoom in to check that text and pictures are still sharp enough.",
    resultLabel: "Compressed", beforeLabel: "Before compressing", backText: "Back"
  });
};
ui["compress-close"].onclick = () => ui["compress-dialog"].close();
ui["compress-dialog"].addEventListener("close", () => {
  // The download link stays valid until the dialog is opened again; the preview copies are not needed.
  forgetCompressPreview();
  ui["compress-preview"].hidden = true;
});
ui["compress-dialog"].oncancel = event => {
  if (compress.busy) event.preventDefault();
};

// Phone and tablet access (started with the "phone access" launcher).
(window.pageBurrowRequest || fetch)("/api/status", { method: "POST", headers: { "X-Local-Editor": "1" }, cache: "no-store" })
  .then(response => response.ok ? response.json() : null)
  .then(status => {
    if (!status?.lan) return;
    const { urls, pin } = status.lan;
    const banner = ui["phone-banner"];
    banner.replaceChildren();
    const strong = text => Object.assign(document.createElement("strong"), { textContent: text });
    banner.append("Phone and tablet access is on. On a device on the same Wi-Fi, open ");
    urls.forEach((url, i) => banner.append(i ? " or " : "", strong(url)));
    if (!urls.length) banner.append("this computer's network address");
    banner.append(" and enter PIN ", strong(pin), ".");
    banner.hidden = false;
  })
  .catch(() => {});

document.addEventListener("keydown", event => {
  if (!state.token || event.target.closest("dialog")) return;
  const typing = event.target.closest("input,textarea,select");
  if (state.live && !state.busy) {
    if (event.key === "Escape") {
      event.preventDefault();
      finishLive(true);
      return;
    }
    if (!typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const step = event.shiftKey ? 10 : 1;
      const move = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
      if (move) {
        event.preventDefault();
        nudge(...move);
        return;
      }
      if ((event.key === "Delete" || event.key === "Backspace") && state.live.id !== null) {
        event.preventDefault();
        deleteLive();
        return;
      }
    }
  }
  if (typing || !(event.ctrlKey || event.metaKey)) return;
  const key = event.key.toLowerCase();
  if (key === "z" || key === "y") {
    event.preventDefault();
    if (key === "y" || event.shiftKey) ui.redo.click();
    else ui.undo.click();
  }
});
