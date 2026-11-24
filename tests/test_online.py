import http.client
import threading
import unittest
import json
import shutil

import online


class HostedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = online.OnlineServer(("127.0.0.1", 0), online.OnlineRequest)
        cls.server.public_origin = "https://pageburrow.example"
        cls.server.lan = False
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def tearDown(self):
        for session in online.SESSIONS.values():
            shutil.rmtree(session["directory"], ignore_errors=True)
        online.SESSIONS.clear()

    def request(self, path="/", body=None, cookie=None, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        headers = {"Host": "pageburrow.example", "X-Local-Editor": "1"}
        if cookie:
            headers["Cookie"] = cookie
        if extra:
            headers.update(extra)
        conn.request("POST" if body is not None else "GET", path, body, headers)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def session(self):
        code, headers, body = self.request()
        self.assertEqual(code, 200)
        self.assertIn(b"Files are uploaded to this server", body)
        self.assertNotIn(b"Your files are never uploaded", body)
        self.assertIn("Secure; HttpOnly; SameSite=Strict", headers["Set-Cookie"])
        return headers["Set-Cookie"].split(";")[0]

    def test_host_and_origin(self):
        self.assertEqual(self.request(extra={"Host": "evil.example"})[0], 403)
        cookie = self.session()
        self.assertEqual(self.request("/api/status", b"", cookie,
            {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("/api/status", b"", cookie,
            {"Origin": self.server.public_origin})[0], 200)

    def test_visitor_isolation_and_processing(self):
        first, second = self.session(), self.session()
        with online.app.pdf.open() as doc:
            doc.new_page().insert_text((72, 72), "PageBurrow hosted test")
            data = doc.tobytes()
        code, _, raw = self.request("/api/upload", data, first, {"X-File-Name": "test.pdf"})
        self.assertEqual(code, 200)
        token = json.loads(raw)["id"]
        payload = json.dumps({"id": token}).encode()
        self.assertEqual(self.request("/api/preview-info", payload, second)[0], 422)
        self.assertEqual(self.request("/api/preview-info", payload, first)[0], 200)
        code, _, raw = self.request("/api/tool", json.dumps({
            "tool": "merge", "files": [token, token], "options": {}}).encode(), first)
        self.assertEqual(code, 200, raw)
        self.assertTrue(raw.startswith(b"%PDF"))
        with online.app.pdf.open(stream=raw, filetype="pdf") as result:
            self.assertEqual(result.page_count, 2)
        code, _, raw = self.request("/api/open", data, first)
        self.assertEqual(code, 200)
        editor_token = json.loads(raw)["token"]
        self.assertEqual(self.request("/api/render", b'{"page":0}', second,
            {"X-Document": editor_token})[0], 422)

    def test_size_and_disabled_features(self):
        cookie = self.session()
        self.assertEqual(self.request("/api/upload", b"", cookie,
            {"Content-Length": str(online.LIMIT + 1)})[0], 413)
        self.assertEqual(self.request("/api/tool", b'{"tool":"html_to_pdf"}', cookie)[0], 422)
        self.assertEqual(self.request("/api/ocr-language", b'{"code":"eng"}', cookie)[0], 422)

    def test_session_expiry_and_capacity(self):
        cookie = self.session()
        key = cookie.split("=", 1)[1]
        directory = online.SESSIONS[key]["directory"]
        online.SESSIONS[key]["used"] -= online.TTL + 1
        self.assertEqual(self.request("/api/status", b"", cookie)[0], 401)
        self.assertFalse(directory.exists())
        for _ in range(4):
            self.session()
        self.assertEqual(self.request()[0], 503)
        self.assertEqual(self.request("/healthz")[0], 200)


if __name__ == "__main__":
    unittest.main()
