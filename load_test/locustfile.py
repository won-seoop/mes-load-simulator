import random
from uuid import uuid4

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

    @task(1)
    def create_work_order_lot(self):
        quantity = random.randint(10, 50)
        order_no = f"WO-{uuid4().hex}"
        create = self.client.post(
            "/work-orders",
            json={
                "order_no": order_no,
                "product_code": random.choice(PRODUCTS),
                "planned_quantity": quantity,
                "priority": random.randint(1, 10),
            },
            name="/work-orders [create]",
        )
        if create.status_code != 200:
            return
        work_order_id = create.json()["id"]
        release = self.client.post(
            f"/work-orders/{work_order_id}/release",
            name="/work-orders/[id]/release",
        )
        if release.status_code != 200:
            return
        self.client.post(
            f"/work-orders/{work_order_id}/lots",
            json={"quantity": quantity},
            name="/work-orders/[id]/lots [create]",
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
    def inspect_or_disposition_lot(self):
        response = self.client.get(
            "/lots?status=QUALITY_HOLD",
            name="/lots [list quality hold]",
        )
        if response.status_code != 200 or not response.json():
            return
        lot = random.choice(response.json())
        events = self.client.get(
            f"/lots/{lot['id']}/events",
            name="/lots/[id]/events [quality trace]",
        )
        if events.status_code != 200:
            return
        inspect_events = [
            event
            for event in events.json()
            if event["event_type"] == "PROCESS_COMPLETED"
            and event["process_step"] == "INSPECT"
        ]
        equipment_id = inspect_events[-1]["equipment_id"] if inspect_events else None

        # Deterministic fault injection: every fourth lot handled by the third
        # tool in an INSPECT group fails. This creates a reproducible
        # equipment-correlated defect pattern for quality anomaly analysis.
        should_fail = (
            equipment_id is not None
            and equipment_id % 3 == 0
            and lot["id"] % 4 == 0
        )
        if not should_fail:
            with self.client.post(
                f"/lots/{lot['id']}/inspections",
                json={"result": "PASS"},
                name="/lots/[id]/inspections [pass]",
                catch_response=True,
            ) as inspection:
                if inspection.status_code == 409:
                    inspection.request_meta["name"] = "/lots/[id]/inspections [conflict]"
                    inspection.success()
            return

        with self.client.post(
            f"/lots/{lot['id']}/inspections",
            json={"result": "FAIL", "defect_code": "INSPECT_SENSOR_DRIFT"},
            name="/lots/[id]/inspections [fail]",
            catch_response=True,
        ) as failed:
            if failed.status_code == 409:
                failed.request_meta["name"] = "/lots/[id]/inspections [conflict]"
                failed.success()
                return
            if failed.status_code != 200:
                return
            attempt_number = failed.json()["attempt_number"]

        # One corrective cycle is allowed. A repeated failure is scrapped so
        # persistent equipment faults cannot create an unbounded rework loop.
        disposition = "REWORK" if attempt_number == 1 else "SCRAP"
        with self.client.post(
            f"/lots/{lot['id']}/quality-disposition",
            json={"disposition": disposition},
            name=f"/lots/[id]/quality-disposition [{disposition.lower()}]",
            catch_response=True,
        ) as result:
            if result.status_code == 409:
                result.request_meta["name"] = "/lots/[id]/quality-disposition [conflict]"
                result.success()
                return
            if result.status_code == 200 and disposition == "REWORK":
                self.client.post(
                    f"/lots/{lot['id']}/rework-release",
                    json={"step_index": 2},
                    name="/lots/[id]/rework-release",
                )

    @task(2)
    def list_equipment(self):
        self.client.get("/equipment", name="/equipment [list]")

    @task(2)
    def check_metrics(self):
        self.client.get("/metrics", name="/metrics")
