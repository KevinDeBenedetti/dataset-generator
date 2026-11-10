"""Tests for the Reactive Resume reads (services/reactive_resume.py).

The instance is a ``MockTransport`` routing its OpenAPI paths to canned
answers and recording every request: the key sent, the paths asked, and that
a redirect is never followed.
"""

import json

import httpx
import pytest

from server.core.config import config
from server.services import reactive_resume as rr

KEY = "rr-test-key-000"


class FakeInstance:
    def __init__(self) -> None:
        self.routes = {}
        self.requests: list[httpx.Request] = []

    def json(self, path, data, status=200, headers=None) -> None:
        self.routes[path] = lambda _req: httpx.Response(
            status, content=json.dumps(data), headers=headers or {}
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(request.url.path)
        return (
            route(request) if route else httpx.Response(404, json={"code": "NOT_FOUND"})
        )


@pytest.fixture
def instance(monkeypatch):
    fake = FakeInstance()
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(fake.handler), **kwargs),
    )
    monkeypatch.setattr(config, "reactive_resume_url", "https://cv.example.org/")
    monkeypatch.setattr(config, "reactive_resume_api_key", KEY)
    return fake


RESUME = {
    "id": "r1",
    "name": "Engineer",
    "slug": "engineer",
    "isPublic": False,
    "updatedAt": "2026-11-01T10:00:00Z",
    "data": {
        "basics": {
            "name": "Kevin",
            "headline": "Developer",
            "email": "k@example.com",
            "phone": "+33 6 00",
            "location": "Lyon",
            "website": {"url": "https://kevindb.dev", "label": "Site"},
            "customFields": [
                {"id": "1", "text": "Driving licence B"},
                {"id": "2", "text": "GitHub", "link": "https://github.com/kevin"},
                {"id": "3", "text": "Odd link", "link": "javascript:alert(1)"},
            ],
        },
        "summary": {
            "content": "<p>Builds <strong>tools</strong> &amp; datasets.</p>"
            "<ul><li>Python</li><li>Go</li></ul>",
            "hidden": False,
        },
        "sections": {
            "profiles": {
                "title": "Profiles",
                "items": [
                    {
                        "id": "p",
                        "network": "GitHub",
                        "username": "kevin",
                        "website": {"url": "https://github.com/kevin"},
                    }
                ],
            },
            "experience": {
                "title": "Experience",
                "items": [
                    {
                        "id": "e1",
                        "company": "Acme",
                        "position": "Developer",
                        "location": "Lyon",
                        "period": "2020 – 2022",
                        "description": "<p>Shipped things.</p>",
                        "website": {"url": "https://acme.example"},
                    },
                    {
                        "id": "e2",
                        "company": "Hidden Co",
                        "position": "Ghost",
                        "hidden": True,
                    },
                    {
                        "id": "e3",
                        "company": "Initech",
                        "position": "",
                        "dates": {"start": "2023", "present": True},
                        "roles": [
                            {
                                "position": "Lead",
                                "period": "2024 – Present",
                                "description": "<p>Leads.</p>",
                            }
                        ],
                    },
                ],
            },
            "skills": {
                "title": "Skills",
                "items": [
                    {
                        "id": "s",
                        "name": "Python",
                        "level": 4,
                        "keywords": ["FastAPI", " ", "pytest"],
                    }
                ],
            },
            "references": {
                "title": "References",
                "items": [
                    {
                        "id": "ref",
                        "name": "Jane Doe",
                        "position": "CTO",
                        "phone": "+1 555",
                    }
                ],
            },
            "awards": {
                "title": "Awards",
                "hidden": True,
                "items": [{"id": "a", "title": "Prize"}],
            },
        },
        "customSections": [
            {
                "id": "c1",
                "title": "Talks",
                "type": "projects",
                "items": [
                    {
                        "id": "t",
                        "name": "PyCon",
                        "description": "Async talk",
                        "website": {"url": "ftp://files.example"},
                    }
                ],
            }
        ],
    },
}


async def test_the_list_is_read_with_the_key_newest_first(instance):
    instance.json(
        "/api/openapi/resumes",
        [
            {
                "id": "r1",
                "name": "Engineer",
                "slug": "engineer",
                "tags": ["en"],
                "isPublic": True,
                "isLocked": False,
                "updatedAt": "2026-11-01T10:00:00Z",
            },
            {"id": "", "name": "no id"},
            "garbage",
            {"id": "r2", "slug": "fr"},
        ],
    )

    out = await rr.list_resumes()

    assert out["instance"] == "https://cv.example.org"
    assert [r["id"] for r in out["resumes"]] == ["r1", "r2"]
    assert out["resumes"][0] == {
        "id": "r1",
        "name": "Engineer",
        "slug": "engineer",
        "tags": ["en"],
        "is_public": True,
        "is_locked": False,
        "updated_at": "2026-11-01T10:00:00Z",
    }
    assert out["resumes"][1]["name"] == "fr"  # no name: its slug
    request = instance.requests[0]
    assert request.headers["x-api-key"] == KEY
    assert request.url.params["sort"] == "lastUpdatedAt"


async def test_without_a_key_nothing_is_asked(instance, monkeypatch):
    monkeypatch.setattr(config, "reactive_resume_api_key", "  ")
    with pytest.raises(rr.ResumeNotConfiguredError, match="REACTIVE_RESUME_API_KEY"):
        await rr.list_resumes()
    assert instance.requests == []


async def test_the_hosted_instance_is_the_default(instance, monkeypatch):
    monkeypatch.setattr(config, "reactive_resume_url", "")
    instance.json("/api/openapi/resumes", [])
    assert (await rr.list_resumes())["instance"] == "https://rxresu.me"
    assert instance.requests[0].url.host == "rxresu.me"


async def test_a_redirect_is_never_followed(instance):
    instance.json(
        "/api/openapi/resumes",
        {},
        status=302,
        headers={"location": "https://evil.example/collect"},
    )
    with pytest.raises(rr.ResumeUnavailableError, match="REACTIVE_RESUME_URL"):
        await rr.list_resumes()
    # One request: the key never travelled to the redirect's target.
    assert [r.url.host for r in instance.requests] == ["cv.example.org"]


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "doesn't know REACTIVE_RESUME_API_KEY"),
        (403, "no read access"),
        (500, "answered 500"),
    ],
)
async def test_a_refusal_says_what_to_fix_without_the_key(instance, status, message):
    instance.json("/api/openapi/resumes", {"code": "X"}, status=status)
    with pytest.raises(rr.ResumeUnavailableError, match=message) as caught:
        await rr.list_resumes()
    assert KEY not in str(caught.value)


async def test_a_site_that_is_no_instance_is_named(instance):
    # No such route at all, then a page that isn't JSON.
    with pytest.raises(rr.ResumeUnavailableError, match="root of a Reactive Resume"):
        await rr.list_resumes()
    instance.routes["/api/openapi/resumes"] = lambda _r: httpx.Response(
        200, text="<html>hello</html>"
    )
    with pytest.raises(rr.ResumeUnavailableError, match="root of a Reactive Resume"):
        await rr.list_resumes()


async def test_an_unreachable_instance_is_named(instance):
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    instance.routes["/api/openapi/resumes"] = down
    with pytest.raises(rr.ResumeUnavailableError, match="can't be reached"):
        await rr.list_resumes()


async def test_a_resume_is_fetched_by_id(instance):
    instance.json("/api/openapi/resumes/r1", RESUME)

    view = await rr.get_resume("r1")

    assert view["id"] == "r1" and view["basics"]["name"] == "Kevin"
    assert instance.requests[0].headers["x-api-key"] == KEY


async def test_an_unknown_or_odd_id_is_not_found(instance):
    with pytest.raises(rr.ResumeNotFoundError):
        await rr.get_resume("nope")  # the instance's own 404
    with pytest.raises(rr.ResumeNotFoundError):
        await rr.get_resume("../resumes")  # refused before any request
    assert [r.url.path for r in instance.requests] == ["/api/openapi/resumes/nope"]


async def test_an_answer_without_a_resume_is_refused(instance):
    instance.json("/api/openapi/resumes/r1", {"id": "r1"})
    with pytest.raises(rr.ResumeUnavailableError, match="answered no resume"):
        await rr.get_resume("r1")


def test_a_resume_reads_as_text():
    view = rr.resume_view(RESUME)

    assert (view["id"], view["name"], view["slug"], view["is_public"]) == (
        "r1",
        "Engineer",
        "engineer",
        False,
    )
    assert view["basics"] == {
        "name": "Kevin",
        "headline": "Developer",
        "email": "k@example.com",
        "phone": "+33 6 00",
        "location": "Lyon",
        "website": "https://kevindb.dev",
        # A field whose link isn't http(s) keeps its text, not the link.
        "facts": ["Driving licence B", "Odd link"],
        "links": [{"label": "GitHub", "url": "https://github.com/kevin"}],
    }
    assert view["summary"] == "Builds tools & datasets.\n- Python\n- Go"
    # Reading order, the hidden section left out, the custom one last.
    assert [s["key"] for s in view["sections"]] == [
        "experience",
        "skills",
        "references",
        "profiles",
        "custom:c1",
    ]
    experience = view["sections"][0]["items"]
    assert experience == [
        {
            "id": "e1",
            "title": "Developer",
            "subtitle": "Acme · Lyon",
            "period": "2020 – 2022",
            "text": "Shipped things.",
            "keywords": [],
            "url": "https://acme.example",
        },
        {
            # No position of its own: its first role's; dates when no period.
            "id": "e3",
            "title": "Lead",
            "subtitle": "Initech",
            "period": "2023 – Present",
            "text": "Role: Lead (2024 – Present)\nLeads.",
            "keywords": [],
            "url": "",
        },
    ]
    skills, references, profiles, talks = (s["items"][0] for s in view["sections"][1:])
    assert (skills["title"], skills["subtitle"], skills["keywords"]) == (
        "Python",
        "4/5",
        ["FastAPI", "pytest"],
    )
    # A reference's own phone number is not part of the view.
    assert references == {
        "id": "ref",
        "title": "Jane Doe",
        "subtitle": "CTO",
        "period": "",
        "text": "",
        "keywords": [],
        "url": "",
    }
    assert (profiles["title"], profiles["subtitle"], profiles["url"]) == (
        "GitHub",
        "kevin",
        "https://github.com/kevin",
    )
    assert (talks["title"], talks["text"], talks["url"]) == ("PyCon", "Async talk", "")


def test_custom_fields_come_once_each():
    basics = {
        "customFields": [
            {"text": "Licence B"},
            {"text": "Licence B"},
            {"text": "Blog", "link": "https://blog.example"},
            {"text": "Same blog", "link": "https://blog.example"},
        ]
    }
    view = rr.resume_view({"data": {"basics": basics}})
    assert view["basics"]["facts"] == ["Licence B"]
    assert view["basics"]["links"] == [{"label": "Blog", "url": "https://blog.example"}]


def test_items_keep_ids_that_tell_them_apart():
    section = {
        "title": "Skills",
        "items": [
            {"id": "same", "name": "Go", "keywords": ["CLI", "CLI", "API"]},
            {"id": "same", "name": "Rust"},
            {"name": "Zig"},
        ],
    }
    shown = rr.resume_view({"data": {"sections": {"skills": section}}})
    items = shown["sections"][0]["items"]
    assert [i["id"] for i in items] == ["same", "same-1", "skills-2"]
    assert items[0]["keywords"] == ["CLI", "API"]


@pytest.mark.parametrize(
    ("raw", "text"),
    [
        ("Plain text", "Plain text"),
        ("Line one<br>Line two<br/>", "Line one\nLine two"),
        ("<p>caf&eacute; &#233; &lt;b&gt;</p>", "café é <b>"),
        ("<h2>Title</h2><div>Body</div>", "Title\nBody"),
        (None, ""),
    ],
)
def test_rich_text_becomes_lines(raw, text):
    assert rr.html_to_text(raw) == text


@pytest.mark.parametrize(
    ("item", "level"),
    [
        ({"level": 3}, "3/5"),
        ({"level": 0}, ""),
        ({"level": "Advanced"}, "Advanced"),
        ({"level": "0"}, ""),
        ({"fluency": "Native", "level": 5}, "Native"),
    ],
)
def test_levels_read_as_written_else_out_of_five(item, level):
    assert rr._level(item) == level
