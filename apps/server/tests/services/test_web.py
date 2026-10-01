"""Single-page fetch for the URL source: HTML→text, SSRF guard, size/type limits."""

import socket

import httpx
import pytest

from server.core import net
from server.services import web
from server.services.web import WebFetchError, fetch_page, html_to_text


def test_html_to_text_keeps_content_drops_chrome():
    html = """
    <html><head><style>.x{}</style><script>track()</script></head>
    <body>
      <header>Site header</header><nav><a>Home</a></nav>
      <h1>Install</h1><p>Run <b>make dev</b>&nbsp;to start.</p>
      <h2>Ports</h2><ul><li>API: 8000</li><li>UI: 3000</li></ul>
      <footer>© 2026</footer>
    </body></html>"""
    text = html_to_text(html)
    assert "# Install" in text and "## Ports" in text
    assert "Run make dev to start." in text
    assert "API: 8000" in text and "UI: 3000" in text
    for chrome in ("Site header", "Home", "track()", "© 2026", ".x{}"):
        assert chrome not in text


@pytest.fixture
def resolve(monkeypatch):
    """Map hostnames to fixed addresses instead of real DNS."""
    table = {"docs.example.com": "93.184.216.34"}

    async def fake_resolve(host, port):
        if host not in table:
            raise socket.gaierror("unknown")
        return [table[host]]

    monkeypatch.setattr(net, "resolve", fake_resolve)
    return table


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetches_an_html_page(resolve):
    client = _client(
        lambda req: httpx.Response(
            200,
            text="<p>Hello</p>",
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )
    page = await fetch_page("https://docs.example.com/guide", client)
    assert page.is_html and "Hello" in page.body
    assert page.url == "https://docs.example.com/guide"


@pytest.mark.parametrize(
    "host, address",
    [
        ("localhost", "127.0.0.1"),
        ("intranet", "10.0.0.5"),
        ("metadata", "169.254.169.254"),
        ("v6loop", "::1"),
    ],
)
async def test_refuses_non_public_addresses(resolve, host, address):
    resolve[host] = address
    client = _client(lambda req: pytest.fail("must not be requested"))
    with pytest.raises(WebFetchError, match="non-public"):
        await fetch_page(f"http://{host}/", client)


async def test_redirect_hops_are_rechecked(resolve):
    resolve["intranet"] = "192.168.1.1"

    def handler(req):
        if req.url.host == "docs.example.com":
            return httpx.Response(302, headers={"location": "http://intranet/admin"})
        pytest.fail("the private redirect target must not be requested")

    with pytest.raises(WebFetchError, match="non-public"):
        await fetch_page("https://docs.example.com/", _client(handler))


async def test_follows_public_redirects(resolve):
    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text="moved", headers={"content-type": "text/plain"})

    page = await fetch_page("https://docs.example.com/old", _client(handler))
    assert page.url == "https://docs.example.com/new" and page.body == "moved"


@pytest.mark.parametrize(
    "url", ["ftp://docs.example.com/x", "file:///etc/passwd", "nohost"]
)
async def test_refuses_other_schemes(url):
    with pytest.raises(WebFetchError, match="http"):
        await fetch_page(url, _client(lambda req: pytest.fail("no request")))


async def test_refuses_binary_content(resolve):
    client = _client(
        lambda req: httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    with pytest.raises(WebFetchError, match="content type"):
        await fetch_page("https://docs.example.com/x.pdf", client)


async def test_caps_the_body_size(resolve, monkeypatch):
    monkeypatch.setattr(web, "MAX_BYTES", 10)
    client = _client(
        lambda req: httpx.Response(
            200, text="x" * 100, headers={"content-type": "text/plain"}
        )
    )
    with pytest.raises(WebFetchError, match="larger than"):
        await fetch_page("https://docs.example.com/big", client)


async def test_http_error_status(resolve):
    client = _client(
        lambda req: httpx.Response(404, headers={"content-type": "text/html"})
    )
    with pytest.raises(WebFetchError, match="HTTP 404"):
        await fetch_page("https://docs.example.com/missing", client)


async def test_unresolvable_host(resolve):
    with pytest.raises(WebFetchError, match="resolve"):
        await fetch_page("https://nowhere.invalid/", _client(lambda req: None))
