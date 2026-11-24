"use strict";
// Preview of a produced file before it is downloaded, used by every tool and by the editor.
// PageBurrow draws the pages on this device: PDFs, images, and Word, PowerPoint or
// Excel files (converted only for the preview). Markdown and text files show their text.
// When the result was made from one PDF with the same number of pages, the original can be
// shown instead of it or next to it, so changes are easy to check.
(() => {
  const HEAD = { "X-Local-Editor": "1", "Content-Type": "application/json" };
  const ZOOMS = [1, 1.5, 2, 3, 4];
  const OFFICE = /\.(docx|docm|doc|odt|rtf|xlsx|xlsm|xls|ods|pptx|pptm|ppt|odp)$/i;
  const BIG_IMAGES = 24; // page images above thumbnail size kept in memory

  async function call(path, data) {
    let response;
    try {
      response = await fetch(path, { method: "POST", headers: HEAD, body: JSON.stringify(data), cache: "no-store" });
    } catch {
      throw new Error("PageBurrow is not reachable. Check that it is still running.");
    }
    const json = response.headers.get("Content-Type")?.includes("application/json");
    if (!response.ok) throw new Error(json ? (await response.json()).error : "The preview could not be made.");
    return json ? response.json() : response.blob();
  }

  function el(tag, props = {}, ...children) {
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

  class ResultPreview {
    // files: [{id, name}] produced files. before: {id} the PDF they were made from (optional).
    constructor(container, { files, before = null, heading = "Preview", resultLabel = "Result", beforeLabel = "Original", fileCount = files.length }) {
      this.files = files;
      this.before = before;
      this.labels = { result: resultLabel, before: beforeLabel };
      this.index = 0;
      this.page = 0;
      this.zoom = 0;
      this.mode = "result";
      this.serial = 0;
      this.current = null;
      this.beforeInfo = null;
      this.infos = new Map();
      this.images = new Map();
      this.shown = new Map(); // last image drawn for a page, shown while a sharper one loads

      const fileSelect = files.length > 1 ? el("select", { class: "rp-file", "aria-label": "File to preview", onchange: () => this.select(Number(fileSelect.value)) },
        files.map((f, i) => el("option", { value: String(i), text: `${i + 1}. ${f.name}` }))) : null;
      this.modes = el("div", { class: "rp-modes", role: "group", "aria-label": "Compare with the original", hidden: true },
        [["result", resultLabel], ["before", beforeLabel], ["both", "Side by side"]].map(([mode, text]) =>
          el("button", { type: "button", dataset: { mode }, "aria-pressed": String(mode === "result"), text, onclick: () => this.setMode(mode) })));
      this.pagesBox = el("div", { class: "rp-pages" });
      this.textBox = el("pre", { class: "rp-text", tabindex: "0", hidden: true });
      this.status = el("p", { class: "rp-status", role: "status" });
      this.lockInput = el("input", { type: "password", autocomplete: "off", "aria-label": "Password of the PDF" });
      this.lockForm = el("form", { class: "rp-lock", hidden: true, onsubmit: event => this.unlock(event) },
        el("p", { text: "This PDF has an open password. Enter it to see the preview. This also checks that the password works." }),
        el("div", { class: "rp-lock-row" }, this.lockInput, el("button", { class: "primary", type: "submit", text: "Show preview" })));
      this.stage = el("div", { class: "rp-stage", tabindex: "0", "aria-label": "Preview pages. Page Up and Page Down change the page; + and − zoom.",
        onkeydown: event => this.key(event) }, this.pagesBox, this.textBox, this.status, this.lockForm);
      this.prev = el("button", { class: "ghost", type: "button", "aria-label": "Previous page", text: "‹", onclick: () => this.show(this.page - 1) });
      this.next = el("button", { class: "ghost", type: "button", "aria-label": "Next page", text: "›", onclick: () => this.show(this.page + 1) });
      this.pageInput = el("input", { type: "number", min: "1", inputmode: "numeric", "aria-label": "Page number",
        onchange: () => this.show(Number(this.pageInput.value) - 1) });
      this.pageOf = el("span");
      this.zoomOut = el("button", { class: "ghost", type: "button", "aria-label": "Zoom out", text: "−", onclick: () => this.setZoom(this.zoom - 1) });
      this.fit = el("button", { class: "ghost", type: "button", title: "Show the whole page", text: "Fit", onclick: () => this.setZoom(0) });
      this.zoomIn = el("button", { class: "ghost", type: "button", "aria-label": "Zoom in", text: "+", onclick: () => this.setZoom(this.zoom + 1) });
      this.nav = el("div", { class: "rp-nav", hidden: true }, this.prev, el("label", {}, "Page ", this.pageInput), this.pageOf, this.next,
        el("span", { class: "divider" }), this.zoomOut, this.fit, this.zoomIn);
      this.thumbs = el("div", { class: "rp-thumbs", "aria-label": "Pages", hidden: true });
      this.note = el("p", { class: "rp-note", hidden: true });
      this.more = fileCount > files.length
        ? el("p", { class: "rp-note", text: `The preview shows the first ${files.length} of ${fileCount} files. The download contains all of them.` }) : null;
      this.bar = el("div", { class: "rp-bar", hidden: !heading && !fileSelect },
        heading ? el("h2", { class: "rp-title", text: heading }) : null, fileSelect, this.modes);
      this.root = el("section", { class: "rp", "aria-label": heading || "Preview" },
        this.bar, this.stage, this.nav, this.thumbs, this.note, this.more);
      container.append(this.root);

      let width = 0;
      this.resize = new ResizeObserver(() => {
        const now = this.stage.clientWidth;
        if (Math.abs(now - width) < 16) return;
        width = now;
        if (this.current?.kind === "pages") this.layout();
      });
      this.resize.observe(this.stage);
      this.select(0);
    }

    // ---- loading ----

    info(id) {
      if (!this.infos.has(id)) {
        this.infos.set(id, call("/api/preview-info", { id }).catch(error => { this.infos.delete(id); throw error; }));
      }
      return this.infos.get(id);
    }

    image(id, page, width) {
      const key = `${id}:${page}:${width}`;
      if (!this.images.has(key)) {
        this.images.set(key, call("/api/preview", { id, page, width }).then(blob => URL.createObjectURL(blob))
          .catch(error => { this.images.delete(key); throw error; }));
        if (width > 200) { // large page images use a lot of memory: keep only the most recent
          const big = [...this.images.keys()].filter(k => Number(k.split(":")[2]) > 200);
          for (const old of big.slice(0, Math.max(0, big.length - BIG_IMAGES))) {
            this.images.get(old).then(url => {
              for (const [page, shown] of this.shown) if (shown === url) this.shown.delete(page);
              URL.revokeObjectURL(url);
            }).catch(() => {});
            this.images.delete(old);
          }
        }
      }
      return this.images.get(key);
    }

    message(text, error = false) {
      this.status.textContent = text;
      this.status.classList.toggle("rp-error", error);
      this.status.hidden = !text;
    }

    async select(index) {
      const serial = ++this.serial;
      const file = this.files[index];
      Object.assign(this, { index, page: 0, zoom: 0, mode: "result", current: null, beforeInfo: null });
      this.thumbObserver?.disconnect();
      this.pagesBox.replaceChildren();
      this.thumbs.replaceChildren();
      this.textBox.hidden = this.lockForm.hidden = this.nav.hidden = this.thumbs.hidden = this.note.hidden = this.modes.hidden = true;
      this.message(OFFICE.test(file.name) ? "Preparing the preview… Word, Excel and PowerPoint files take a few seconds." : "Preparing the preview…");
      let info;
      try {
        info = await this.info(file.id);
      } catch (error) {
        if (serial === this.serial) this.message(error.message, true);
        return;
      }
      if (serial !== this.serial) return;
      this.current = info;
      if (info.note) {
        this.note.textContent = info.note;
        this.note.hidden = false;
      }
      if (info.kind === "text") {
        this.message("");
        this.textBox.textContent = info.text || "(This file is empty.)";
        this.textBox.hidden = false;
        if (info.cut) {
          this.note.textContent = "Only the beginning of this long file is shown. The download contains all of it.";
          this.note.hidden = false;
        }
      } else if (info.kind === "locked") {
        this.message("");
        this.lockForm.hidden = false;
      } else if (info.kind !== "pages") {
        this.message(info.note || "This file cannot be previewed. Download it to open it.");
      } else {
        this.message("");
        this.nav.hidden = false;
        this.buildThumbs();
        this.show(0);
        if (this.before) this.offerCompare(serial);
      }
    }

    async offerCompare(serial) {
      try {
        const info = await this.info(this.before.id);
        if (serial !== this.serial || info.kind !== "pages" || info.pages !== this.current.pages) return;
        this.beforeInfo = info;
        this.modes.hidden = this.bar.hidden = false;
      } catch { /* the original cannot be shown: no comparison */ }
    }

    async unlock(event) {
      event.preventDefault();
      const file = this.files[this.index];
      try {
        await call("/api/upload-password", { id: file.id, password: this.lockInput.value });
      } catch (error) {
        this.message(error.message, true);
        return;
      }
      this.lockInput.value = "";
      this.infos.delete(file.id);
      this.select(this.index);
    }

    // ---- showing pages ----

    sources() {
      const result = { id: this.files[this.index].id, label: this.labels.result, sizes: this.current.sizes };
      const before = this.beforeInfo && { id: this.before.id, label: this.labels.before, sizes: this.beforeInfo.sizes };
      if (before && this.mode === "before") return [before];
      if (before && this.mode === "both") return [before, result];
      return [result];
    }

    show(page) {
      const info = this.current;
      if (info?.kind !== "pages") return;
      this.page = Math.max(0, Math.min(info.pages - 1, Number.isFinite(page) ? page : 0));
      this.pageInput.value = this.page + 1;
      this.pageInput.max = info.pages;
      this.pageOf.textContent = `of ${info.pages}`;
      this.prev.disabled = this.page === 0;
      this.next.disabled = this.page >= info.pages - 1;
      this.stage.scrollTop = 0;
      this.layout();
      const current = this.thumbs.querySelector('[aria-current="true"]');
      current?.removeAttribute("aria-current");
      const thumb = this.thumbs.children[this.page];
      if (thumb) {
        thumb.setAttribute("aria-current", "true");
        const box = this.thumbs.getBoundingClientRect(), at = thumb.getBoundingClientRect();
        if (at.left < box.left || at.right > box.right) this.thumbs.scrollLeft += at.left - box.left - (box.width - at.width) / 2;
      }
    }

    layout() {
      if (this.current?.kind !== "pages" || !this.stage.isConnected) return;
      const sources = this.sources();
      const style = getComputedStyle(this.stage);
      const room = this.stage.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      // "Fit" shows the whole page: as tall as the preview area allows (minus a caption line)
      const limit = parseFloat(style.maxHeight);
      const caption = sources.length > 1 || sources[0].label !== this.labels.result ? 26 : 0;
      const tall = Math.max(200, (Number.isFinite(limit) ? limit : window.innerHeight * 0.68)
        - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom) - caption - 6);
      const gap = 12;
      const zoom = ZOOMS[this.zoom];
      // keep the same spot in the middle of the view when zooming
      const fx = (this.stage.scrollLeft + this.stage.clientWidth / 2) / Math.max(1, this.stage.scrollWidth);
      const fy = (this.stage.scrollTop + this.stage.clientHeight / 2) / Math.max(1, this.stage.scrollHeight);
      this.pagesBox.replaceChildren(...sources.map(source => {
        const [w, h] = source.sizes[this.page] || source.sizes[0] || [612, 792];
        const fit = Math.max(80, Math.min((room - gap * (sources.length - 1)) / sources.length, tall * w / h));
        const width = Math.round(fit * zoom);
        const pixels = Math.min(2400, Math.ceil(width * (window.devicePixelRatio || 1) / 150) * 150);
        const key = `${source.id}:${this.page}`;
        const img = el("img", { alt: `${source.label}, page ${this.page + 1}`, draggable: "false", style: `width:${width}px;aspect-ratio:${w} / ${h}` });
        if (this.shown.has(key)) img.src = this.shown.get(key);
        const figure = el("figure", { class: "rp-page" }, img,
          sources.length > 1 || source.label !== this.labels.result ? el("figcaption", { text: source.label }) : null);
        this.image(source.id, this.page, pixels).then(url => {
          if (!img.isConnected) return;
          img.src = url;
          this.shown.set(key, url);
        }).catch(error => {
          if (!img.isConnected) return;
          figure.classList.add("rp-failed");
          figure.append(el("figcaption", { text: error.message }));
        });
        return figure;
      }));
      if (zoom > 1) {
        this.stage.scrollLeft = fx * this.stage.scrollWidth - this.stage.clientWidth / 2;
        this.stage.scrollTop = fy * this.stage.scrollHeight - this.stage.clientHeight / 2;
      }
      this.zoomOut.disabled = this.fit.disabled = this.zoom === 0;
      this.zoomIn.disabled = this.zoom === ZOOMS.length - 1;
    }

    buildThumbs() {
      const info = this.current;
      this.thumbs.hidden = info.pages < 2;
      if (info.pages < 2) return;
      const id = this.files[this.index].id;
      this.thumbObserver = new IntersectionObserver(entries => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          this.thumbObserver.unobserve(entry.target);
          const img = entry.target.querySelector("img");
          this.image(id, Number(entry.target.dataset.page), 160).then(url => { img.src = url; }).catch(() => {});
        }
      }, { root: this.thumbs, rootMargin: "0px 400px" });
      for (let i = 0; i < info.pages; i++) {
        const [w, h] = info.sizes[i] || info.sizes[0] || [612, 792];
        const button = el("button", { type: "button", dataset: { page: String(i) }, "aria-label": `Page ${i + 1}`, onclick: () => this.show(i) },
          el("img", { alt: "", draggable: "false", style: `aspect-ratio:${w} / ${h}` }), el("span", { text: String(i + 1) }));
        this.thumbs.append(button);
        this.thumbObserver.observe(button);
      }
    }

    setMode(mode) {
      this.mode = mode;
      for (const button of this.modes.children) button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
      this.layout();
    }

    setZoom(index) {
      this.zoom = Math.max(0, Math.min(ZOOMS.length - 1, index));
      this.layout();
    }

    key(event) {
      if (this.current?.kind !== "pages" || event.target !== this.stage) return;
      const sideways = this.stage.scrollWidth > this.stage.clientWidth + 2;
      const step = { PageUp: -1, PageDown: 1, ArrowLeft: sideways ? 0 : -1, ArrowRight: sideways ? 0 : 1 }[event.key];
      if (step) {
        event.preventDefault();
        this.show(this.page + step);
      } else if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        this.setZoom(this.zoom + 1);
      } else if (event.key === "-") {
        event.preventDefault();
        this.setZoom(this.zoom - 1);
      }
    }

    destroy() {
      this.serial++;
      this.resize.disconnect();
      this.thumbObserver?.disconnect();
      for (const url of this.images.values()) url.then(u => URL.revokeObjectURL(u)).catch(() => {});
      this.images.clear();
      this.shown.clear();
      this.root.remove();
    }
  }

  window.ResultPreview = ResultPreview;
})();
