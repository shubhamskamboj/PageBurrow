(() => {
  let worker;
  let nextId = 0;
  const pending = new Map();
  const notice = document.getElementById("engine-status");
  let loaded = false;
  function engine() {
    if (worker) return worker;
    worker = new Worker("./toolbox-worker.js");
    worker.onmessage = ({ data }) => {
      const task = pending.get(data.id);
      if (!task) return;
      pending.delete(data.id);
      if (data.error) {
        notice.textContent = "The PDF engine could not finish. " + data.error;
        notice.hidden = false;
        task.reject(new Error(data.error));
      } else {
        loaded = true;
        notice.hidden = true;
        task.resolve(new Response(data.body, { status: data.status, headers: data.headers }));
      }
    };
    worker.onerror = () => {
      worker.terminate();
      worker = null;
      loaded = false;
      const error = new Error("The browser stopped its PDF engine. Reopen the document, or try a device with more memory.");
      notice.textContent = error.message;
      notice.hidden = false;
      for (const task of pending.values()) task.reject(error);
      pending.clear();
    };
    return worker;
  }
  window.pageBurrowRequest = async (path, options = {}) => {
    if (path === "/api/status") return Response.json({ lan: null, compress: true });
    if (options.body instanceof Blob && options.body.size > 200_000_000) {
      return Response.json({ error: "Choose a file up to 200 MB." }, { status: 413 });
    }
    const body = await new Response(options.body).arrayBuffer();
    const target = engine();
    if (!loaded) {
      notice.textContent = "Loading the PDF engine for this device. The first use needs an internet connection.";
      notice.hidden = false;
    }
    return new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, { resolve, reject });
      target.postMessage({ id, path, headers: Object.fromEntries(new Headers(options.headers)), body }, [body]);
    });
  };
})();
