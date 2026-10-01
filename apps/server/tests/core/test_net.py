"""The outbound guard: hostile destinations are refused, the checked address is used."""

import socket

import httpx
import pytest

from server.core import net
from server.core.net import (
    PinnedTransport,
    UnsafeURLError,
    check_url,
    is_public_address,
)

PUBLIC = "93.184.216.34"


@pytest.fixture
def dns(monkeypatch):
    table = {"api.example.com": [PUBLIC]}

    async def fake(host, port):
        if host not in table:
            raise socket.gaierror("unknown host")
        return list(table[host])

    monkeypatch.setattr(net, "resolve", fake)
    return table


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",  # v4-mapped loopback
        "::ffff:169.254.169.254",
        "224.0.0.1",
        "not-an-ip",
    ],
)
def test_non_public_addresses(address):
    assert is_public_address(address) is False


def test_public_addresses():
    assert is_public_address(PUBLIC)
    assert is_public_address("2606:4700:4700::1111")


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",  # not https
        "ftp://api.example.com/",
        "https://localhost/",
        "https://LOCALHOST./",
        "https://db.internal/",
        "https://postgres.default.svc.cluster.local/",
        "https://kubernetes.default.svc/",
        "https://printer.local/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://169.254.169.254/latest/meta-data/",
        "https://10.0.0.1:8443/",
        "https:///nohost",
    ],
)
async def test_hostile_urls_are_refused(dns, url):
    with pytest.raises(UnsafeURLError):
        await check_url(url)


async def test_a_name_with_any_private_answer_is_refused(dns):
    dns["mixed.example.com"] = [PUBLIC, "10.0.0.7"]
    with pytest.raises(UnsafeURLError, match="non-public"):
        await check_url("https://mixed.example.com/")


async def test_unresolvable_names_are_refused(dns):
    with pytest.raises(UnsafeURLError, match="resolve"):
        await check_url("https://nope.example.com/")


async def test_host_allowlist(dns):
    await check_url("https://api.example.com/", allowed_hosts=["api.example.com"])
    with pytest.raises(UnsafeURLError, match="not an allowed host"):
        await check_url("https://api.example.com/", allowed_hosts=["api.openai.com"])


async def test_http_only_when_opted_in(dns):
    with pytest.raises(UnsafeURLError):
        await check_url("http://api.example.com/")
    assert (await check_url("http://api.example.com/", allow_http=True)).port == 80


async def _send(transport, url):
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as c:
        return await c.get(url)


async def test_the_connection_goes_to_the_checked_address(dns):
    seen = {}

    def handler(request):
        seen["host"] = request.url.host
        seen["header"] = request.headers["host"]
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, text="ok")

    transport = PinnedTransport(inner=httpx.MockTransport(handler))
    response = await _send(transport, "https://api.example.com/v1/models")

    assert response.status_code == 200
    assert seen == {
        "host": PUBLIC,
        "header": "api.example.com",
        "sni": "api.example.com",
    }


async def test_dns_rebinding_is_stopped_at_connect_time(dns):
    """The name is public when first checked, private on the next lookup."""
    transport = PinnedTransport(
        inner=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    await _send(transport, "https://api.example.com/")

    dns["api.example.com"] = ["169.254.169.254"]
    with pytest.raises(httpx.ConnectError, match="non-public"):
        await _send(transport, "https://api.example.com/")


async def test_a_redirect_to_a_private_host_is_not_followed(dns):
    """The transport returns the 3xx; following it would go through the guard again."""
    dns["internal-svc.example.com"] = ["10.0.0.5"]

    def handler(request):
        if request.url.host == PUBLIC:
            return httpx.Response(
                302, headers={"location": "https://internal-svc.example.com/"}
            )
        raise AssertionError("must not connect to the private host")

    transport = PinnedTransport(inner=httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        with pytest.raises(httpx.ConnectError, match="non-public"):
            await client.get("https://api.example.com/")


async def test_pinned_client_never_follows_redirects_by_default():
    client = net.pinned_client()
    try:
        assert client.follow_redirects is False
        assert client.trust_env is False
    finally:
        await client.aclose()
