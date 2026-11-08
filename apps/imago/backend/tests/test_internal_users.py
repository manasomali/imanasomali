"""`POST /internal/users/lookup` e `GET /internal/users/{id}` (ETH-59)."""

import pytest

from app.models import MAX_ACCOUNT_ID, User
from tests.factories import new_user, save
from tests.internal_helpers import ENGRAFI_TOKEN, ETHOS_TOKEN, bearer

EMAIL = "bia@example.com"
UNAUTHORIZED = {"error": "unauthorized", "field": None}
NOT_FOUND = {"error": "not_found", "field": None}


@pytest.fixture
def internal(app, make_client):
    # As aplicações chamam direto, sem Origin (não são um navegador)
    return make_client(app, origin=False)


@pytest.fixture
def bia(db_session) -> User:
    user = new_user(EMAIL, locale="en", timezone="Europe/Lisbon")
    save(db_session, user)
    return user


# --- lookup ---


@pytest.mark.parametrize("token", [ETHOS_TOKEN, ENGRAFI_TOKEN])
def test_lookup_finds_the_active_account(internal, bia, token):
    response = internal.post(
        "/internal/users/lookup", json={"email": "  Bia@Example.COM "}, headers=bearer(token)
    )

    assert response.status_code == 200
    assert response.json() == {"id": bia.id, "locale": "en"}


@pytest.mark.parametrize("values", [None, {"is_active": False}, {"status": "deleting"}])
def test_lookup_is_404_for_missing_blocked_and_deleting(internal, db_session, values):
    if values is not None:
        save(db_session, new_user(EMAIL, **values))

    response = internal.post(
        "/internal/users/lookup", json={"email": EMAIL}, headers=bearer(ETHOS_TOKEN)
    )

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


@pytest.mark.parametrize("headers", [{}, bearer("x" * 43), bearer(ETHOS_TOKEN[:-1] + "Z")])
def test_lookup_without_a_valid_token_is_401(internal, bia, headers):
    response = internal.post("/internal/users/lookup", json={"email": EMAIL}, headers=headers)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": "bia"}, "email"),
        ({"email": "joão@example.com"}, "email"),
        ({"email": 3}, "email"),
        ({}, "email"),
        ({"email": EMAIL, "app": "ethos"}, "app"),
    ],
)
def test_lookup_validates_the_body(internal, bia, body, field):
    response = internal.post("/internal/users/lookup", json=body, headers=bearer(ETHOS_TOKEN))

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": field}


# --- GET /internal/users/{id} ---


def test_get_user(internal, bia):
    response = internal.get(f"/internal/users/{bia.id}", headers=bearer(ETHOS_TOKEN))

    assert response.status_code == 200
    assert response.json() == {
        "id": bia.id,
        "email": EMAIL,
        "locale": "en",
        "timezone": "Europe/Lisbon",
        "active": True,
    }


@pytest.mark.parametrize("values", [{"is_active": False}, {"status": "deleting"}])
def test_get_blocked_or_deleting_user_is_not_active(internal, db_session, values):
    user = new_user(EMAIL, **values)
    save(db_session, user)

    response = internal.get(f"/internal/users/{user.id}", headers=bearer(ENGRAFI_TOKEN))

    assert response.status_code == 200
    assert response.json()["active"] is False


def test_get_missing_user_is_404(internal, bia):
    other = bia.id - 1 if bia.id > 1 else bia.id + 1

    response = internal.get(f"/internal/users/{other}", headers=bearer(ETHOS_TOKEN))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_largest_id_is_accepted(internal, db_session):
    save(db_session, new_user(EMAIL, id=MAX_ACCOUNT_ID))

    response = internal.get(f"/internal/users/{MAX_ACCOUNT_ID}", headers=bearer(ETHOS_TOKEN))

    assert response.json()["id"] == MAX_ACCOUNT_ID


@pytest.mark.parametrize("user_id", ["0", "-1", str(MAX_ACCOUNT_ID + 1), "abc", "1.5"])
def test_get_invalid_id_is_422(internal, user_id):
    response = internal.get(f"/internal/users/{user_id}", headers=bearer(ETHOS_TOKEN))

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": "user_id"}


def test_get_without_token_is_401(internal, bia):
    response = internal.get(f"/internal/users/{bia.id}")

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


def test_routes_are_not_behind_the_origin_check(app, make_client, bia):
    # Mesmo com um Origin estranho (as aplicações não são navegador), vale só o token
    client = make_client(app, origin="https://evil.example")

    response = client.post(
        "/internal/users/lookup", json={"email": EMAIL}, headers=bearer(ETHOS_TOKEN)
    )

    assert response.status_code == 200
