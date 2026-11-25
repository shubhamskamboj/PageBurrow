/* Each tab owns a private Python filesystem and runs one tool request at a time. */
let runtime;
let handler;
let available;
let tess;
let tessReady;
let api;
let activeLanguage;
async function loadOcr() {
  importScripts("./runtime/tesseract-core-lstm.js");
  tess = await TesseractCore({ locateFile: file => new URL("./runtime/" + file, self.location.href).href });
}
self.pageBurrowOcr = (png, language, dpi) => {
  if (activeLanguage !== language) {
    if (api) { api.End(); tess.destroy(api); api = null; }
    activeLanguage = null;
    for (const code of language.split("+")) {
      const filename = code + ".traineddata";
      tess.FS.writeFile("/" + filename, runtime.FS.readFile("/pageburrow/tessdata/" + filename));
    }
    api = new tess.TessBaseAPI();
    if (api.Init("/", language, 1) !== 0) throw new Error("Could not initialize the selected OCR language.");
    activeLanguage = language;
  }
  const view = png.getBuffer("u8");
  try { tess.FS.writeFile("/input", view.data); } finally { view.release(); }
  let renderer;
  try {
    if (api.SetImageFile(1, 0) === 1) throw new Error("The OCR engine could not read this page.");
    api.SetSourceResolution(Math.max(70, dpi));
    api.Recognize(null);
    renderer = new tess.TessPDFRenderer("recognized", "/", false);
    renderer.BeginDocument("PageBurrow");
    renderer.AddImage(api);
    renderer.EndDocument();
    return tess.FS.readFile("/recognized.pdf");
  } finally {
    if (renderer) tess.destroy(renderer);
    api.Clear();
    for (const name of ["/input", "/recognized.pdf"]) {
      try { tess.FS.unlink(name); } catch { /* A failed recognition may have produced no file. */ }
    }
  }
};
async function resource(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error("A toolbox component could not be loaded. Check your connection and try again.");
  return response;
}
async function initialize() {
  importScripts("./runtime/pyodide.js");
  const indexURL = new URL("./runtime/", self.location.href).href;
  const manifest = await (await resource(indexURL + "engine.json")).json();
  runtime = await loadPyodide({ indexURL });
  await runtime.loadPackage([...manifest.packages, indexURL + manifest.wheel]);
  const bundle = await (await resource(indexURL + "toolbox.zip")).arrayBuffer();
  runtime.unpackArchive(bundle, "zip", { extractDir: "/pageburrow" });
  runtime.runPython("import sys; sys.path.insert(0, '/pageburrow'); from local_engine import dispatch");
  handler = runtime.globals.get("dispatch");
  available = new Set(manifest.languages);
}
let ready;
let queue = Promise.resolve();
self.onmessage = ({ data }) => {
  queue = queue.then(async () => {
    try {
      ready ||= initialize().catch(error => { ready = null; throw error; });
      await ready;
      let path = data.path;
      if (path === "/api/tool") {
        tessReady ||= loadOcr().catch(error => { tessReady = null; throw error; });
        await tessReady;
      }
      if (path === "/api/ocr-language") {
        const { code } = JSON.parse(new TextDecoder().decode(data.body));
        if (!available.has(code)) throw new Error("This language pack is unavailable.");
        const language = await (await resource("./languages/" + encodeURIComponent(code) + ".traineddata")).arrayBuffer();
        runtime.FS.writeFile("/pageburrow/tessdata/" + code + ".traineddata", new Uint8Array(language));
        path = "/api/tools-info";
        data.body = new ArrayBuffer(0);
      }
      const result = handler(path, JSON.stringify(data.headers), new Uint8Array(data.body));
      try {
        const [status, headers, bytes] = result.toJs({ dict_converter: Object.fromEntries });
        self.postMessage({ id: data.id, status, headers, body: bytes }, [bytes.buffer]);
      } finally { result.destroy(); }
    } catch (error) {
      self.postMessage({ id: data.id, error: String(error.message || error) });
    }
  });
};
