"""A tiny local website for crawler tests: static pages, redirects, robots.txt and a JS-built SPA."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FOOTER = '<footer><p>Acme Widgets Ltd, 1 High Street, Leeds.</p><a href="mailto:hello@acme.test">Email us</a></footer>'
NAV = '<nav><a href="/">Home</a><a href="/about">About</a></nav>'


def page(title: str, body: str) -> str:
    return f"<html><head><title>{title}</title></head><body>{NAV}<main>{body}</main>{FOOTER}</body></html>"


STATIC = {
    "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private\n"),
    "/": (
        "text/html",
        page(
            "Acme Widgets",
            '<h1>Acme Widgets</h1><p>We make the finest blue widgets in Yorkshire, shipped worldwide within three days.</p><a href="/about">About</a> <a href="/services?tab=1#top">Services</a> <a href="/contact">Contact</a> <a href="/private">Private</a> <a href="/out">Out</a> <a href="https://evil.example/x">Evil</a> <a href="/brochure.pdf">PDF</a> <a href="/loop?page=2">Loop</a>',
        ),
    ),
    "/about": (
        "text/html",
        page(
            "About Acme",
            "<h1>About Acme</h1><p>Founded in 1987 by Jane Acme, the company employs forty people and holds ISO 9001 certification for quality management.</p>",
        ),
    ),
    "/services": (
        "text/html",
        page(
            "Our services",
            "<h1>Services</h1><p>Widget design, widget repair and bulk widget supply for manufacturers across the United Kingdom and Europe.</p><h2>Pricing</h2><p>Repairs start from forty pounds. Bulk supply is quoted individually after a free consultation.</p>",
        ),
    ),
    "/contact": (
        "text/html",
        page(
            "Contact",
            '<h1>Contact</h1><p>Call our team on <a href="tel:+441130000000">0113 000 0000</a> between nine and five.</p>',
        ),
    ),
    "/private": (
        "text/html",
        page(
            "Private",
            "<p>Secret staff-only page that robots.txt forbids crawlers from reading.</p>",
        ),
    ),
    "/loop": (
        "text/html",
        page(
            "Loop",
            '<p>An endless calendar style page with enough words to be indexed properly by the crawler.</p><a href="/loop?page=3">Next</a>',
        ),
    ),
}

SPA_SHELL = """<!doctype html><html><head><title>SPA Co</title></head><body><div id="root"></div>
<script>
const pages = {
  "/": ["Welcome to SPA Co", "SPA Co builds client rendered software for logistics firms, with live route optimisation and driver apps.", [["/pricing","Pricing"],["/team","Team"]]],
  "/pricing": ["SPA Co pricing", "Plans start at two hundred pounds a month per depot, including unlimited drivers and phone support.", [["/","Home"]]],
  "/team": ["Meet the team", "Our engineers are based in Bristol and have fifteen years of experience in transport software.", [["/","Home"]]]
};
const p = pages[location.pathname] || pages["/"];
setTimeout(() => {
  document.getElementById("root").innerHTML = "<main><h1>" + p[0] + "</h1><p>" + p[1] + "</p>" +
    p[2].map(l => '<a href="' + l[0] + '">' + l[1] + "</a>").join(" ") + "</main>";
}, 100);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    spa = False

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/out" and not self.spa:
            self.send_response(302)
            self.send_header("Location", "http://evil.example/landing")
            self.end_headers()
            return
        if self.spa:
            ctype, body = (
                ("text/plain", "User-agent: *\nAllow: /\n")
                if path == "/robots.txt"
                else ("text/html", SPA_SHELL)
            )
        elif path in STATIC:
            ctype, body = STATIC[path]
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@contextmanager
def serve(spa: bool = False) -> Iterator[str]:
    handler = type("H", (Handler,), {"spa": spa})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
