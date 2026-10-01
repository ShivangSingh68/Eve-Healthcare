import pytest


def test_list_centers(client, catalog):
    resp = client.get("/centers")
    assert resp.status_code == 200
    assert {c["name"] for c in resp.json()} == {"Apollo Diagnostics", "Empty Lab"}


def test_get_center_includes_tests_with_price(client, catalog):
    resp = client.get(f"/centers/{catalog['center_id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Apollo Diagnostics"
    assert body["tests"] == [{"id": catalog["test_id"], "name": "CBC", "price": 500.0}]


def test_center_without_tests_has_empty_list(client, catalog):
    assert client.get(f"/centers/{catalog['other_center_id']}").json()["tests"] == []


def test_get_unknown_center_404(client, catalog):
    assert client.get("/centers/9999").status_code == 404


def test_invalid_id_is_422(client):
    assert client.get("/centers/abc").status_code == 422
    assert client.get("/centers/0").status_code == 422


def test_list_and_get_tests(client, catalog):
    listing = client.get("/tests")
    assert listing.status_code == 200
    assert {t["name"] for t in listing.json()} == {"CBC", "MRI"}

    detail = client.get(f"/tests/{catalog['test_id']}").json()
    assert detail["name"] == "CBC"
    assert detail["centers"][0]["price"] == 500.0
    assert detail["centers"][0]["name"] == "Apollo Diagnostics"
    assert client.get("/tests/9999").status_code == 404


def test_pagination_validation(client, catalog):
    assert client.get("/centers?limit=1").json().__len__() == 1
    assert client.get("/centers?limit=0").status_code == 422
    assert client.get("/centers?offset=-1").status_code == 422


# ---- admin-only management -------------------------------------------------------------


def test_catalog_writes_require_authentication(client, catalog):
    assert client.post("/centers", json={"name": "X", "location": "Y"}).status_code == 401


def test_regular_user_cannot_modify_catalog(client, catalog, user_headers):
    assert client.post(
        "/centers", json={"name": "X", "location": "Y"}, headers=user_headers
    ).status_code == 403
    assert client.post("/tests", json={"name": "T"}, headers=user_headers).status_code == 403
    url = f"/centers/{catalog['center_id']}/tests/{catalog['test_id']}"
    assert client.put(url, json={"price": 1}, headers=user_headers).status_code == 403


def test_admin_can_create_center_test_and_offering(client, admin_headers):
    center = client.post(
        "/centers", json={"name": "New Lab", "location": "Goa"}, headers=admin_headers
    )
    test = client.post("/tests", json={"name": "Vitamin D"}, headers=admin_headers)
    assert center.status_code == test.status_code == 201

    url = f"/centers/{center.json()['id']}/tests/{test.json()['id']}"
    created = client.put(url, json={"price": 799.5}, headers=admin_headers)
    assert created.status_code == 201
    updated = client.put(url, json={"price": 700}, headers=admin_headers)
    assert updated.status_code == 200 and updated.json()["price"] == 700.0


def test_duplicate_test_name_conflicts(client, admin_headers):
    assert client.post("/tests", json={"name": "A"}, headers=admin_headers).status_code == 201
    assert client.post("/tests", json={"name": "A"}, headers=admin_headers).status_code == 409



@pytest.mark.parametrize("price", [0, -5, "abc", 10.123])
def test_invalid_price_rejected(client, catalog, admin_headers, price):
    url = f"/centers/{catalog['center_id']}/tests/{catalog['test_id']}"
    assert client.put(url, json={"price": price}, headers=admin_headers).status_code == 422


def test_price_set_for_unknown_center_or_test_404(client, catalog, admin_headers):
    assert client.put(
        f"/centers/9999/tests/{catalog['test_id']}", json={"price": 5}, headers=admin_headers
    ).status_code == 404
    assert client.put(
        f"/centers/{catalog['center_id']}/tests/9999", json={"price": 5}, headers=admin_headers
    ).status_code == 404
