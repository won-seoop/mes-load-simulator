import random

from locust import HttpUser, between, task

PRODUCTS = ["WAFER-A", "WAFER-B", "PANEL-X", "PANEL-Y"]


class MesUser(HttpUser):
    wait_time = between(0.2, 1.2)

    @task(3)
    def create_lot(self):
        self.client.post(
            "/lots",
            json={"product": random.choice(PRODUCTS), "quantity": random.randint(10, 50)},
            name="/lots [create]",
        )

    @task(6)
    def advance_lot(self):
        # A lot needs repeated /advance calls to walk the full process route
        # (ETCH -> CVD -> CMP -> INSPECT), so both WAITING and already
        # in-flight PROCESSING lots are eligible, not just WAITING ones.
        status = random.choice(["WAITING", "PROCESSING"])
        resp = self.client.get(f"/lots?status={status}", name="/lots [list waiting/processing]")
        if resp.status_code != 200:
            return
        lots = resp.json()
        if not lots:
            return
        lot = random.choice(lots)
        with self.client.post(
            f"/lots/{lot['id']}/advance",
            name="/lots/[id]/advance",
            catch_response=True,
        ) as advance:
            if advance.status_code == 409:
                # Another worker advanced the same snapshot first. This is an
                # expected optimistic-concurrency result, not a server error.
                advance.request_meta["name"] = "/lots/[id]/advance [conflict]"
                advance.success()

    @task(2)
    def list_equipment(self):
        self.client.get("/equipment", name="/equipment [list]")

    @task(2)
    def check_metrics(self):
        self.client.get("/metrics", name="/metrics")
