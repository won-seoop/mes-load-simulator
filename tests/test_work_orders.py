from concurrent.futures import ThreadPoolExecutor

from app.models import PROCESS_ROUTE


def _create_work_order(client, order_no="WO-001", quantity=100, product="WAFER-A"):
    response = client.post(
        "/work-orders",
        json={
            "order_no": order_no,
            "product_code": product,
            "planned_quantity": quantity,
            "priority": 3,
        },
    )
    assert response.status_code == 200
    return response.json()


def _release(client, work_order_id):
    response = client.post(f"/work-orders/{work_order_id}/release")
    assert response.status_code == 200
    return response.json()


def test_seeded_products_are_available(client):
    response = client.get("/products")
    assert response.status_code == 200
    assert {product["code"] for product in response.json()} >= {
        "WAFER-A",
        "WAFER-B",
        "PANEL-X",
        "PANEL-Y",
    }


def test_work_order_rejects_unknown_product(client):
    response = client.post(
        "/work-orders",
        json={
            "order_no": "WO-UNKNOWN",
            "product_code": "UNKNOWN",
            "planned_quantity": 100,
        },
    )
    assert response.status_code == 422


def test_work_order_number_is_unique(client):
    _create_work_order(client, order_no="WO-DUP")
    duplicate = client.post(
        "/work-orders",
        json={
            "order_no": "WO-DUP",
            "product_code": "WAFER-A",
            "planned_quantity": 100,
        },
    )
    assert duplicate.status_code == 409


def test_work_order_rejects_inactive_product(client):
    product = client.post(
        "/products",
        json={"code": "INACTIVE", "name": "Inactive Product", "is_active": 0},
    )
    assert product.status_code == 200

    response = client.post(
        "/work-orders",
        json={
            "order_no": "WO-INACTIVE",
            "product_code": "INACTIVE",
            "planned_quantity": 100,
        },
    )
    assert response.status_code == 409


def test_concurrent_duplicate_work_order_number_allows_one(client):
    payload = {
        "order_no": "WO-RACE",
        "product_code": "WAFER-A",
        "planned_quantity": 100,
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(lambda _: client.post("/work-orders", json=payload), range(2))
        )

    assert sorted(response.status_code for response in responses) == [200, 409]


def test_lot_requires_released_work_order(client):
    work_order = _create_work_order(client)
    response = client.post(
        f"/work-orders/{work_order['id']}/lots",
        json={"quantity": 25},
    )
    assert response.status_code == 409


def test_lot_split_cannot_exceed_planned_quantity(client):
    work_order = _create_work_order(client, quantity=100)
    _release(client, work_order["id"])

    for quantity in (40, 35, 25):
        response = client.post(
            f"/work-orders/{work_order['id']}/lots",
            json={"quantity": quantity},
        )
        assert response.status_code == 200

    excess = client.post(
        f"/work-orders/{work_order['id']}/lots",
        json={"quantity": 1},
    )
    assert excess.status_code == 409

    current = client.get(f"/work-orders/{work_order['id']}").json()
    assert current["released_quantity"] == 100
    assert len(client.get(f"/work-orders/{work_order['id']}/lots").json()) == 3


def test_concurrent_lot_split_preserves_planned_quantity(client):
    work_order = _create_work_order(client, order_no="WO-CONCURRENT", quantity=100)
    _release(client, work_order["id"])

    def create_lot():
        return client.post(
            f"/work-orders/{work_order['id']}/lots",
            json={"quantity": 60},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: create_lot(), range(2)))

    assert sorted(response.status_code for response in responses) == [200, 409]
    current = client.get(f"/work-orders/{work_order['id']}").json()
    assert current["released_quantity"] == 60
    assert len(client.get(f"/work-orders/{work_order['id']}/lots").json()) == 1


def test_work_order_completes_when_all_planned_lots_complete(client):
    work_order = _create_work_order(client, order_no="WO-COMPLETE", quantity=20)
    _release(client, work_order["id"])
    lot = client.post(
        f"/work-orders/{work_order['id']}/lots",
        json={"quantity": 20},
    ).json()

    for _ in PROCESS_ROUTE:
        response = client.post(f"/lots/{lot['id']}/advance")
        assert response.status_code == 200

    current = client.get(f"/work-orders/{work_order['id']}").json()
    assert current["completed_quantity"] == 20
    assert current["status"] == "COMPLETED"
