import random
import time
from uuid import uuid4

from locust import HttpUser, between, task

PRODUCTS = ["WAFER-A", "WAFER-B", "PANEL-X", "PANEL-Y"]

# The fault-injection task below is picked as often as any other weight-1
# task, i.e. roughly once every couple of seconds per user. Firing an actual
# equipment DOWN every time it is picked was tried first and is a documented
# failure case (see ROADMAP.md, 2026-09-21): with 50 concurrent users it
# produced ~580 down-flips in 3 minutes, permanently stranding 702 lots and
# dropping completed lots for the day from the usual ~270-320 to 149. This
# gate keeps most picks a no-op so equipment DOWN stays an occasional,
# recoverable fault instead of the dominant behavior of the whole run.
FAULT_DOWN_PROBABILITY = 0.05

# Independent per-tool faults (above) rarely land all 3 tools of one process
# step DOWN at once: at FAULT_DOWN_PROBABILITY=0.05 that requires 3
# coincident low-probability picks, so most daily runs never actually
# exercise the equipment-down HOLD wait metrics added on 2026-09-21 (see
# ROADMAP.md, "다음 후보"). This module-level flag makes the step-wide fault
# fire at most once per Locust process (one process per daily run, since
# run_daily_test.sh invokes locust without --processes) so every run
# reliably produces one whole-step outage and recovery cycle without
# repeatedly stranding a step for the rest of the run. It is set to True
# before any I/O in fault_inject_step_down so two concurrent greenlets
# cannot both decide to fire it (gevent only switches greenlets on I/O, so
# the check-then-set below never yields in between).
_STEP_DOWN_FIRED = False
FAULT_STEP_DOWN_PROBABILITY = 0.05

# First attempt at the step-wide fault (this constant did not exist yet)
# fired correctly -- 3 tools of one step went DOWN together -- but
# fault_recover_equipment picks any currently-DOWN tool with no gate at all,
# and with 50 users each idling ~0.2-1.2s between tasks it is selected
# often enough to individually recover all 3 tools within roughly a second
# (measured MTTR of 0.1-0.7s in reports/2026-09-23.md and .../2026-09-24.md
# before this fix). No lot's /advance call ever lands while the whole step
# is down, so lots_on_hold_count/peak HOLD samples stayed 0 in both runs
# despite the fault firing. `_down_since` records when Locust itself took a
# tool DOWN so fault_recover_equipment can require it to have stayed down
# for at least MIN_DOWN_DWELL_SECONDS -- a minimal, deliberately simple
# stand-in for "repair takes some nonzero time" -- before recovering it.
_down_since: dict[int, float] = {}
MIN_DOWN_DWELL_SECONDS = 5


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
        # in-flight PROCESSING lots are eligible, not just WAITING ones. HOLD
        # is included too: /advance on a HOLD lot retries it at its current
        # step (see app/main.py's advance_lot docstring comment) once
        # equipment frees up, but nothing does that retry unless a client
        # asks for HOLD lots specifically -- before this, a lot that reached
        # HOLD here would sit there for the rest of the run even after its
        # equipment recovered (see MIN_DOWN_DWELL_SECONDS above and
        # ROADMAP.md, 2026-09-24: reports/2026-09-24.md's first run showed
        # 15 lots on HOLD at run end with avg_resolved_hold_seconds still
        # None -- none of them had ever been retried). HOLD is rare and
        # short-lived by design (typically 0-1 lots for a few seconds, see
        # MIN_DOWN_DWELL_SECONDS), so it is weighted low: an even 3-way split
        # was tried first and measurably cut this run's throughput (RPS
        # 93->86, completed lots ~200->142) because a third of picks queried
        # an empty HOLD list and did no work.
        status = random.choices(
            ["WAITING", "PROCESSING", "HOLD"], weights=[45, 45, 10], k=1
        )[0]
        resp = self.client.get(f"/lots?status={status}", name="/lots [list waiting/processing/hold]")
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

    @task(1)
    def fault_inject_equipment_down(self):
        # Independent fault injection: occasionally take one running tool
        # down, mirroring a real intermittent equipment fault. Gated by
        # FAULT_DOWN_PROBABILITY (see its comment) so it stays rare relative
        # to advance_lot; fault_recover_equipment below brings it back so
        # downtime is transient rather than permanent.
        if random.random() > FAULT_DOWN_PROBABILITY:
            return
        response = self.client.get("/equipment", name="/equipment [list]")
        if response.status_code != 200:
            return
        candidates = [eq for eq in response.json() if eq["status"] != "DOWN"]
        if not candidates:
            return
        target = random.choice(candidates)
        response = self.client.patch(
            f"/equipment/{target['id']}/status",
            json={"status": "DOWN", "reason": "FAULT_INJECTION"},
            name="/equipment/[id]/status [fault: down]",
        )
        if response.status_code == 200:
            _down_since[target["id"]] = time.time()

    @task(1)
    def fault_inject_step_down(self):
        # Whole-step fault: models a shared utility/interlock event (e.g. a
        # bay-level gas or power trip) that takes every tool of one process
        # step down together, rather than one tool failing independently.
        # Fires at most once per run (see _STEP_DOWN_FIRED above).
        global _STEP_DOWN_FIRED
        if _STEP_DOWN_FIRED:
            return
        if random.random() > FAULT_STEP_DOWN_PROBABILITY:
            return
        _STEP_DOWN_FIRED = True
        response = self.client.get("/equipment", name="/equipment [list]")
        if response.status_code != 200:
            return
        equipment = response.json()
        steps = sorted({eq["process_step"] for eq in equipment})
        for step in random.sample(steps, k=len(steps)):
            step_equipment = [
                eq for eq in equipment if eq["process_step"] == step and eq["status"] != "DOWN"
            ]
            # Fewer than 2 up tools is just an ordinary single-tool fault,
            # not a step-wide outage, so try the next step instead.
            if len(step_equipment) < 2:
                continue
            for eq in step_equipment:
                response = self.client.patch(
                    f"/equipment/{eq['id']}/status",
                    json={"status": "DOWN", "reason": "STEP_FAULT_INJECTION"},
                    name="/equipment/[id]/status [fault: step down]",
                )
                if response.status_code == 200:
                    _down_since[eq["id"]] = time.time()
            return

    @task(1)
    def fault_recover_equipment(self):
        # Unconditional (relative to the down-side gates above) so a fault
        # never outpaces its own recovery and a whole process step is not
        # left down for long. Still respects MIN_DOWN_DWELL_SECONDS (see its
        # comment): a tool this Locust process took DOWN is only eligible
        # once it has stayed down that long, so a lot whose /advance lands
        # during the outage has a real chance to observe it instead of the
        # fault self-healing inside the same second it started. A tool with
        # no recorded down-time (e.g. taken DOWN by something other than
        # this process) is treated as immediately eligible rather than stuck
        # forever.
        response = self.client.get("/equipment", name="/equipment [list]")
        if response.status_code != 200:
            return
        now = time.time()
        down = [
            eq
            for eq in response.json()
            if eq["status"] == "DOWN"
            and now - _down_since.get(eq["id"], 0) >= MIN_DOWN_DWELL_SECONDS
        ]
        if not down:
            return
        target = random.choice(down)
        response = self.client.patch(
            f"/equipment/{target['id']}/status",
            json={"status": "IDLE"},
            name="/equipment/[id]/status [fault: recover]",
        )
        if response.status_code == 200:
            _down_since.pop(target["id"], None)
