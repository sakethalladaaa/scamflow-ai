from pathlib import Path

from fastapi.testclient import TestClient

from backend.scamflow.app import create_app
from backend.scamflow.security import CSRF_HEADER_NAME
from backend.scamflow.settings import Environment, Settings


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_path=tmp_path / "auth.sqlite3",
        trusted_origin="http://127.0.0.1:8000",
    )


HEADERS = {"Origin": "http://127.0.0.1:8000", CSRF_HEADER_NAME: "1"}


def test_register_me_login_and_logout(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        registered = client.post(
            "/auth/register",
            headers=HEADERS,
            json={"email": "User@example.com", "password": "correct horse battery staple"},
        )
        assert registered.status_code == 201
        assert registered.json()["email"] == "user@example.com"
        assert registered.json()["role"] == "user"

        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "user@example.com"

        logout = client.post("/auth/logout", headers=HEADERS)
        assert logout.status_code == 204
        assert client.get("/auth/me").status_code == 401


def test_login_rejects_wrong_password_and_accepts_correct_password(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        client.post(
            "/auth/register",
            headers=HEADERS,
            json={"email": "login@example.com", "password": "correct horse battery staple"},
        )
        bad = client.post(
            "/auth/login",
            headers=HEADERS,
            json={"email": "login@example.com", "password": "wrong password"},
        )
        assert bad.status_code == 401

        good = client.post(
            "/auth/login",
            headers=HEADERS,
            json={"email": "login@example.com", "password": "correct horse battery staple"},
        )
        assert good.status_code == 200
