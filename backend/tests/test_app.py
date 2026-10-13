"""Backend routes + access control against a synthetic published issue --
no real run data."""

import time

import pytest
from conftest import NOT_FETCHED_RUN_ID, OPEN_RUN_ID, RESTRICTED_RUN_ID
from fastapi.testclient import TestClient

from access import COOKIE_NAME, MAX_AGE_SECONDS, REFRESH_AFTER_SECONDS, Access
from app import create_app

PASSWORD = "hunter2"


@pytest.fixture
def client(data):
    # https, or the client won't send the Secure cookie back.
    return TestClient(create_app(PASSWORD, frontend_dir=data / "no-frontend"), base_url="https://testserver")


@pytest.fixture
def logged_in(client):
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 204
    return client


def test_anonymous_visitors_see_only_open_issues(client):
    assert [i["run_id"] for i in client.get("/api/issues").json()] == [OPEN_RUN_ID]
    assert client.get(f"/api/issues/{OPEN_RUN_ID}").status_code == 200
    # Restricted and not fetched (no 00_source.json)
    # look like they don't exist.
    for path in [
        f"/api/issues/{RESTRICTED_RUN_ID}",
        f"/api/issues/{RESTRICTED_RUN_ID}/pages/1",
        f"/api/issues/{RESTRICTED_RUN_ID}/pages/1/image",
        f"/api/issues/{RESTRICTED_RUN_ID}/audio",
        f"/api/issues/{NOT_FETCHED_RUN_ID}",
    ]:
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_everything_else_needs_a_login(client):
    for method, path in [
        ("GET", "/api/not-a-route"),
        ("GET", "/"),
        ("POST", f"/api/issues/{OPEN_RUN_ID}/audio"),
    ]:
        assert client.request(method, path).status_code == 401, path
    assert client.get("/robots.txt").status_code == 200


def test_session_and_logout(client):
    assert client.get("/api/session").json() == {"logged_in": False}
    client.post("/api/login", json={"password": PASSWORD})
    assert client.get("/api/session").json() == {"logged_in": True}
    assert client.post("/api/logout").status_code == 204
    assert client.get("/api/session").json() == {"logged_in": False}


def test_api_docs_are_public(client):
    assert client.get("/api/docs").status_code == 200
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/api/issues/{run_id}/pages/{page}/segments/{segment}/audio" in paths
    assert "/robots.txt" not in paths


def test_wrong_password_sets_no_cookie(client):
    r = client.post("/api/login", json={"password": "nope"})
    assert r.status_code == 401
    assert COOKIE_NAME not in r.cookies


def test_login_cookie_is_httponly_secure_and_long_lived(client):
    header = client.post("/api/login", json={"password": PASSWORD}).headers["set-cookie"]
    assert "HttpOnly" in header and "Secure" in header and f"Max-Age={MAX_AGE_SECONDS}" in header


def test_issues_latest_first_and_only_published_fetched_runs(logged_in):
    issues = logged_in.get("/api/issues").json()
    assert [i["run_id"] for i in issues] == [RESTRICTED_RUN_ID, OPEN_RUN_ID]
    assert logged_in.get(f"/api/issues/{NOT_FETCHED_RUN_ID}").status_code == 404
    assert issues[0] == {
        "run_id": RESTRICTED_RUN_ID,
        "paper": "restricted",
        "paper_title": "Restricted Daily",
        "edition": "daily",
        "date": "2026-10-02",
    }
    assert logged_in.get(f"/api/issues/{RESTRICTED_RUN_ID}").json()["pages"][0]["segment_count"] == 1


def test_page_json_hides_the_image_path(logged_in):
    page = logged_in.get(f"/api/issues/{RESTRICTED_RUN_ID}/pages/1").json()
    assert "image" not in page and "thumbnail" not in page
    assert page["articles"][0]["bbox"] == [0.0, 0.0, 0.5, 0.5]


def test_page_image(logged_in):
    r = logged_in.get(f"/api/issues/{RESTRICTED_RUN_ID}/pages/1/image")
    assert r.status_code == 200
    assert r.content == b"\x89PNG fake"
    assert r.headers["content-type"] == "image/png"


def test_page_thumbnail(logged_in):
    r = logged_in.get(f"/api/issues/{RESTRICTED_RUN_ID}/pages/1/thumbnail")
    assert (r.status_code, r.content, r.headers["content-type"]) == (200, b"\xff\xd8 fake", "image/jpeg")


def test_missing_things_404(logged_in):
    for path in [
        "/api/issues/restricted-daily-2026-10-03",
        "/api/issues/nope",
        "/api/issues/..",
        f"/api/issues/{RESTRICTED_RUN_ID}/pages/2",
        f"/api/issues/{RESTRICTED_RUN_ID}/pages/2/image",
    ]:
        assert logged_in.get(path).status_code == 404, path


def test_forged_tampered_or_expired_cookies_rejected():
    access = Access(PASSWORD)
    now = 1_000_000_000
    good = f"{now}.{access._sign(now)}"
    assert access.issued_at(good, now=now) == now
    assert access.issued_at(f"{now + 1}.{access._sign(now)}", now=now) is None
    assert access.issued_at(f"{now}.{Access('other')._sign(now)}", now=now) is None
    assert access.issued_at(good, now=now + MAX_AGE_SECONDS) is None
    assert access.issued_at("garbage", now=now) is None


def _cookie_issued_ago(client, seconds: int) -> None:
    issued = int(time.time()) - seconds
    client.cookies.set(COOKIE_NAME, f"{issued}.{Access(PASSWORD)._sign(issued)}")


def test_cookie_older_than_a_day_gets_reissued(client):
    _cookie_issued_ago(client, REFRESH_AFTER_SECONDS + 60)
    r = client.get("/api/issues")
    assert r.status_code == 200
    assert COOKIE_NAME in r.headers["set-cookie"]


def test_fresh_cookie_is_left_alone(client):
    _cookie_issued_ago(client, 60)
    r = client.get("/api/issues")
    assert r.status_code == 200
    assert "set-cookie" not in r.headers


def test_frontend_shell_is_public_but_content_is_not(data, tmp_path):
    shell = tmp_path / "dist"
    (shell / "assets").mkdir(parents=True)
    (shell / "index.html").write_text("<html>shell</html>")
    (shell / "assets" / "index-abc.js").write_text("js")
    client = TestClient(create_app(PASSWORD, frontend_dir=shell), base_url="https://testserver")

    assert client.get("/").text == "<html>shell</html>"
    assert client.get("/assets/index-abc.js").text == "js"
    # Exact paths only: nothing else under the shell's folders, and the
    # restricted issues stay hidden.
    assert client.get("/assets/other.js").status_code == 401
    assert client.get(f"/api/issues/{RESTRICTED_RUN_ID}").status_code == 404
