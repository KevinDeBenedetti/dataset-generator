"""The OpenAI-compatible key and its endpoint travel as a pair (no database)."""

from server.services.credentials import OPENAI_API_KEY
from server.tests.creds import make_creds

SERVER = make_creds(
    openai_api_key="sk-server-0000000000000",
    openai_base_url="http://litellm.litellm.svc.cluster.local:4000/v1",
    hf_token="hf_server",
    base_url_trusted=True,
)


def test_the_servers_key_comes_with_the_servers_endpoint():
    # A URL the user typed never receives the server's key.
    user = make_creds(openai_base_url="https://gateway.example.com/v1")
    lent = user.with_openai_of(SERVER)

    assert lent.secret(OPENAI_API_KEY) == "sk-server-0000000000000"
    assert lent.openai_base_url == SERVER.openai_base_url
    assert lent.base_url_trusted is True and lent.openai_from_server is True


def test_nothing_is_lent_without_a_server_key():
    user = make_creds(openai_base_url="https://gateway.example.com/v1")
    assert user.with_openai_of(make_creds()) is user


def test_the_development_fallback_pairs_the_endpoint_with_its_key():
    # The user's own key keeps the user's endpoint (OpenAI when blank) — never
    # the server's private gateway — while other missing values still fill in.
    mine = make_creds(openai_api_key="sk-mine-00000000000000")
    filled = mine.filled_from(SERVER)
    assert filled.secret(OPENAI_API_KEY) == "sk-mine-00000000000000"
    assert filled.openai_base_url == "" and filled.base_url_trusted is False
    assert filled.openai_from_server is False
    assert filled.secret("hf_token") == "hf_server"

    # Without a key of their own, the user calls the server's endpoint.
    borrowed = make_creds(openai_base_url="https://gateway.example.com/v1")
    borrowed = borrowed.filled_from(SERVER)
    assert borrowed.openai_base_url == SERVER.openai_base_url
    assert borrowed.secret(OPENAI_API_KEY) == "sk-server-0000000000000"
    assert borrowed.openai_from_server is True
