(() => {
  const limit = 200_000_000;
  const panel = document.querySelector("#large-pdf");
  const form = panel.querySelector("form");
  const { operation, files, ranges, angle } = form.elements;
  const selectedFiles = panel.querySelector("#large-pdf-selected");
  const status = panel.querySelector("#large-pdf-status");
  const downloads = panel.querySelector("#large-pdf-downloads");
  const submit = panel.querySelector("#large-pdf-submit");
  const cancel = panel.querySelector("#large-pdf-cancel");
  const sizeFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  const sizeLabel = bytes => bytes < 1_000_000
    ? `${sizeFormat.format(bytes / 1000)} KB`
    : `${sizeFormat.format(bytes / 1e6)} MB`;
  let worker = null;
  let urls = [];
  let selection = [];

  function clearResults() {
    urls.forEach(url => URL.revokeObjectURL(url));
    urls = [];
    downloads.replaceChildren();
    status.textContent = "";
    status.classList.remove("error");
  }

  function renderFiles() {
    const items = selection.map((file, index) => {
      const item = document.createElement("li");
      item.textContent = `${file.name} · ${sizeLabel(file.size)}`;
      if (operation.value === "merge" && selection.length > 1) {
        const actions = document.createElement("span");
        actions.className = "large-pdf-file-actions";
        for (const [label, offset] of [["Move up", -1], ["Move down", 1]]) {
          const button = document.createElement("button");
          const destination = index + offset;
          button.type = "button";
          button.className = "ghost";
          button.textContent = label;
          button.setAttribute("aria-label", `${label} for ${file.name}`);
          button.disabled = destination < 0 || destination >= selection.length;
          button.addEventListener("click", () => {
            [selection[index], selection[destination]] = [selection[destination], selection[index]];
            renderFiles();
            clearResults();
            selectedFiles.children[destination].querySelector("button:enabled")?.focus();
          });
          actions.append(button);
        }
        item.append(actions);
      }
      return item;
    });
    selectedFiles.replaceChildren(...items);
  }

  function updateOptions() {
    const merge = operation.value === "merge";
    const rotate = operation.value === "rotate";
    const pageSelection = ["split", "extract", "remove", "rotate"].includes(operation.value);
    if (!merge && selection.length > 1) selection = [];
    files.multiple = merge;
    ranges.closest("label").hidden = !pageSelection;
    ranges.required = pageSelection && !rotate;
    panel.querySelector("#large-pdf-range-help").textContent = operation.value === "split"
      ? "Each comma-separated range becomes a separate PDF."
      : rotate ? "Leave blank to rotate every page." : "";
    angle.closest("label").hidden = !rotate;
    panel.querySelector("#large-pdf-merge-help").hidden = !merge;
    renderFiles();
    clearResults();
  }

  function finish() {
    worker?.terminate();
    worker = null;
    form.querySelector("fieldset").disabled = false;
    submit.textContent = "Process PDF";
    cancel.hidden = true;
  }

  function showError(message) {
    status.textContent = message;
    status.classList.add("error");
  }

  operation.addEventListener("change", updateOptions);
  files.addEventListener("change", () => {
    if (files.files.length) selection = Array.from(files.files);
    files.value = "";
    renderFiles();
    clearResults();
  });
  form.addEventListener("input", event => {
    if (event.target === ranges || event.target === angle) clearResults();
  });
  cancel.addEventListener("click", () => {
    finish();
    status.textContent = "Processing canceled.";
  });
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (worker) return;
    clearResults();
    const chosen = selection;
    const task = operation.value;
    if (chosen.length < (task === "merge" ? 2 : 1)) {
      showError(task === "merge" ? "Choose at least two PDFs to merge." : "Choose a PDF to continue.");
      return;
    }
    if (chosen.some(file => !file.size || (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf"))) {
      showError("Choose PDF files that are not empty.");
      return;
    }
    if (chosen.reduce((size, file) => size + file.size, 0) > limit) {
      showError("The selected files exceed 200 MB total.");
      return;
    }
    status.textContent = "Loading the PDF engine and processing your files. Large PDFs may take a minute.";
    try {
      worker = new Worker("/large-pdf-worker.js", { type: "module" });
    } catch {
      showError("This browser could not start the PDF engine.");
      return;
    }
    worker.onmessage = ({ data }) => {
      finish();
      if (data.error) {
        showError(data.error);
        return;
      }
      const output = data.results[0].blob;
      status.textContent = task === "compress"
        ? output.size < chosen[0].size
          ? `Reduced from ${sizeLabel(chosen[0].size)} to ${sizeLabel(output.size)}.`
          : "Lossless compression could not reduce this PDF. You can download a copy."
        : data.results.length > 1 ? `${data.results.length} PDFs are ready.` : "Your PDF is ready.";
      for (const { blob, name } of data.results) {
        const url = URL.createObjectURL(blob);
        urls.push(url);
        const link = document.createElement("a");
        link.className = "primary large-pdf-download";
        link.href = url;
        link.download = name;
        link.textContent = `Download ${name} · ${sizeLabel(blob.size)}`;
        downloads.append(link);
      }
    };
    worker.onerror = () => {
      finish();
      showError("The PDF engine stopped. Try again in a current desktop browser with more available memory.");
    };
    worker.postMessage({ files: chosen, operation: task, pageRanges: ranges.value, angle: Number(angle.value) });
    form.querySelector("fieldset").disabled = true;
    cancel.hidden = false;
    submit.textContent = "Processing…";
  });
  updateOptions();
  panel.hidden = false;
  document.querySelector("#large-pdf-entry").hidden = false;
})();
