"""Exercise real Nginx routing with local mock APIs; never contacts production.

Usage: python scripts/verify-edge-nginx.py --nginx /path/to/nginx
       --openssl /path/to/openssl --website ../Bid-product-website
"""
import argparse
import http.client
import json
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class API(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({
            "service": self.server.service,
            "path": self.path,
            "host": self.headers.get("Host"),
            "proto": self.headers.get("X-Forwarded-Proto"),
            "cookie": self.headers.get("Cookie"),
            "forwarded": self.headers.get("X-Forwarded-For"),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nginx", required=True)
    parser.add_argument("--openssl", default="openssl")
    parser.add_argument("--website", required=True)
    args = parser.parse_args()
    nginx = str(Path(args.nginx).resolve())
    root = Path(__file__).resolve().parents[1] / "deploy" / "edge-nginx"
    mocks = []
    for name in ("ops", "website-api"):
        server = ThreadingHTTPServer(("127.0.0.1", 0), API)
        server.service = name
        threading.Thread(target=server.serve_forever, daemon=True).start()
        mocks.append(server)
    process = None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with tempfile.TemporaryDirectory(prefix="yxciedu-nginx-") as directory:
            stage = Path(directory)
            for folder in ("logs", "temp", "snippets", "html/web", "website"):
                (stage / folder).mkdir(parents=True, exist_ok=True)
            (stage / "html/web/index.html").write_text("OPERATIONS SPA", encoding="utf-8")
            (stage / "website/index.html").write_text("WEBSITE SPA", encoding="utf-8")
            (stage / "website/assets").mkdir()
            (stage / "website/assets/app.js").write_text("asset", encoding="utf-8")
            cert, key = stage / "cert.pem", stage / "key.pem"
            subprocess.run([
                args.openssl, "req", "-x509", "-nodes", "-newkey", "rsa:2048",
                "-subj", "/CN=www.yxciedu.com", "-addext",
                "subjectAltName=DNS:www.yxciedu.com,DNS:yxciedu.com",
                "-days", "1", "-keyout", str(key), "-out", str(cert),
            ], check=True, capture_output=True, creationflags=flags)
            http_port, tls_port, web_port = free_port(), free_port(), free_port()

            def adapt(text):
                replacements = {
                    "listen [::]:80 default_server;": "",
                    "listen [::]:80;": "",
                    "listen [::]:443 ssl;": "",
                    "listen 80": f"listen 127.0.0.1:{http_port}",
                    "listen 443": f"listen 127.0.0.1:{tls_port}",
                    "/etc/nginx/snippets/": stage.as_posix() + "/snippets/",
                    "/usr/share/nginx/html": stage.as_posix() + "/html",
                    "/etc/nginx/ssl/yxciedu/www.yxciedu.com_bundle.crt": cert.as_posix(),
                    "/etc/nginx/ssl/yxciedu/www.yxciedu.com.key": key.as_posix(),
                    "http://yuxin-ai-ops-backend:8001": f"http://127.0.0.1:{mocks[0].server_port}",
                    "http://bid-website-api:3001": f"http://127.0.0.1:{mocks[1].server_port}",
                    "http://bid-web:80": f"http://127.0.0.1:{web_port}",
                }
                for old, new in replacements.items():
                    text = text.replace(old, new)
                return text

            for source in (root / "snippets").glob("*.conf"):
                (stage / "snippets" / source.name).write_text(
                    adapt(source.read_text(encoding="utf-8")), encoding="utf-8")
            edge = adapt((root / "conf.d/yxciedu.conf").read_text(encoding="utf-8"))
            web = (Path(args.website) / "nginx.conf").read_text(encoding="utf-8")
            web = web.replace("listen 80;", f"listen 127.0.0.1:{web_port};")
            web = web.replace("/usr/share/nginx/html", stage.as_posix() + "/website")
            config = "worker_processes 1;\npid logs/nginx.pid;\nevents {}\nhttp {\n" + edge + web + "\n}\n"
            (stage / "nginx.conf").write_text(config, encoding="utf-8")
            command = [nginx, "-p", stage.as_posix() + "/", "-c", "nginx.conf"]
            syntax = subprocess.run(command + ["-t"], capture_output=True, creationflags=flags)
            if syntax.returncode:
                raise RuntimeError(syntax.stderr.decode(errors="replace"))
            process = subprocess.Popen(command, creationflags=flags, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            context = ssl.create_default_context(cafile=str(cert))
            context.check_hostname = False  # local TCP address; production never disables validation

            def request(path, host="www.yxciedu.com", tls=True, port=None, headers=None):
                connection = (http.client.HTTPSConnection("127.0.0.1", port or tls_port, context=context, timeout=3)
                              if tls else http.client.HTTPConnection("127.0.0.1", port or http_port, timeout=3))
                try:
                    connection.request("GET", path, headers={"Host": host, **(headers or {})})
                    response = connection.getresponse()
                    return response.status, dict(response.getheaders()), response.read().decode()
                finally:
                    connection.close()

            for _ in range(50):
                try:
                    if request("/healthz", "localhost", False)[0] == 200:
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("Nginx did not start")

            count = 0
            for path, service, upstream_path in (
                ("/api/public/bootstrap?q=hello%20world", "website-api", "/api/public/bootstrap?q=hello%20world"),
                ("/api/v1/common/health/ready", "ops", "/common/health/ready"),
                ("/api/v1/static/upload/avatar.png?v=1", "ops", "/api/v1/static/upload/avatar.png?v=1"),
                ("/product-api/growth/invites/code?x=1", "ops", "/api/v1/growth/invites/code?x=1"),
            ):
                status, _, body = request(path, headers={"Cookie": "bid_refresh=test", "X-Forwarded-For": "spoofed"})
                data = json.loads(body)
                assert (status, data["service"], data["path"]) == (200, service, upstream_path), data
                assert data["proto"] == "https" and data["host"] == "www.yxciedu.com", data
                assert data["forwarded"] == "127.0.0.1", data
                assert data["cookie"] == (None if path.startswith("/product-api/") else "bid_refresh=test"), data
                count += 1
            for path, expected in (("/", "WEBSITE SPA"), ("/invite/code", "WEBSITE SPA"),
                                   ("/payout/wechat", "WEBSITE SPA"), ("/web/", "OPERATIONS SPA"),
                                   ("/web/system/user", "OPERATIONS SPA")):
                status, _, body = request(path)
                assert status == 200 and body == expected, (path, status, body)
                count += 1
            status, headers, _ = request("/payout/wechat")
            assert headers["Referrer-Policy"] == "no-referrer" and headers["Cache-Control"] == "no-store"
            count += 1
            for path in ("/web", "/api", "/api/v1", "/product-api"):
                status, headers, _ = request(path)
                assert status == 308 and headers["Location"].endswith(path + "/"), (path, headers)
                count += 1
            for host, tls in (("www.yxciedu.com", False), ("yxciedu.com", False), ("yxciedu.com", True)):
                status, headers, _ = request("/web/?a=1", host, tls)
                assert status == 308 and headers["Location"] == "https://www.yxciedu.com/web/?a=1"
                count += 1
            status, _, body = request("/api/v1/common/health/ready", "119.45.121.36", False)
            assert status == 200 and json.loads(body)["path"] == "/common/health/ready"
            count += 1
            assert request("/private", "unknown.example", False)[0] == 404
            count += 1
            for path in ("/api/public/bootstrap", "/product-api/growth"):
                assert request(path, tls=False, port=web_port)[0] == 404
                count += 1
            print(f"PASS: nginx -t and {count} routing/HTTPS cases")
            subprocess.run(command + ["-s", "quit"], check=True, capture_output=True, creationflags=flags)
            process.wait(timeout=10)
            process = None
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=5)
        for server in mocks:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
