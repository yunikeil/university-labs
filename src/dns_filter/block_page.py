from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PAGE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DNS filter works</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      background: #f7f7fb;
      color: #16161d;
    }
    body {
      min-height: 100vh;
      margin: 0;
      display: grid;
      place-items: center;
    }
    main {
      width: min(680px, calc(100% - 32px));
      text-align: center;
    }
    h1 {
      margin: 0 0 12px;
      font-size: clamp(32px, 8vw, 72px);
      line-height: 1;
      letter-spacing: 0;
    }
    p {
      margin: 10px auto;
      max-width: 540px;
      font-size: 18px;
      line-height: 1.5;
      color: #444452;
    }
    .panel {
      margin-top: 28px;
      padding: 18px;
      border: 1px solid #d9d9e6;
      border-radius: 8px;
      background: #ffffff;
      box-shadow: 0 12px 40px rgba(34, 38, 55, 0.08);
    }
    .meter {
      height: 10px;
      border-radius: 999px;
      overflow: hidden;
      background: #ececf4;
    }
    .bar {
      width: 42%;
      height: 100%;
      border-radius: inherit;
      background: #26a269;
      animation: wiggle 1.8s ease-in-out infinite alternate;
    }
    .joke {
      margin-top: 14px;
      font-size: 14px;
      color: #666674;
    }
    @keyframes wiggle {
      from { width: 23%; }
      to { width: 91%; }
    }
    @media (prefers-color-scheme: dark) {
      :root {
        background: #111216;
        color: #f2f2f5;
      }
      p { color: #c6c6d1; }
      .panel {
        background: #1b1c22;
        border-color: #343642;
        box-shadow: none;
      }
      .meter { background: #2b2d36; }
      .joke { color: #a9a9b7; }
    }
  </style>
</head>
<body>
  <main>
    <h1>DNS фильтр работает</h1>
    <p>Этот домен попал в список блокировки, поэтому DNS вернул адрес локальной заглушки.</p>
    <section class="panel" aria-label="Статус фильтра">
      <div class="meter"><div class="bar"></div></div>
      <p class="joke">Пакетик дошёл до DNS, посмотрел на список и решил устроить себе выходной.</p>
    </section>
  </main>
</body>
</html>
"""


class BlockPageHandler(BaseHTTPRequestHandler):
    """Возвращает одну и ту же страницу для любого HTTP-пути."""

    server_version = "DnsFilterBlockPage/0.1"

    def do_GET(self) -> None:
        self.respond()

    def do_HEAD(self) -> None:
        self.respond(include_body=False)

    def do_POST(self) -> None:
        self.respond()

    def respond(self, include_body: bool = True) -> None:
        body = PAGE.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        if include_body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a tiny block page HTTP server.")
    parser.add_argument("--host", default="127.0.0.1", help="Address to listen on.")
    parser.add_argument("--port", default=8081, type=int, help="Port to listen on.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    address = (args.host, args.port)

    with ThreadingHTTPServer(address, BlockPageHandler) as server:
        print(f"Block page listening on http://{args.host}:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()

