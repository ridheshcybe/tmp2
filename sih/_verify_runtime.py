"""Verify AeroTwin backend runtime behavior for the reported bug claims."""
import asyncio
import sys

sys.path.insert(0, ".")

import backend.database as db
from httpx import AsyncClient, ASGITransport
from backend.main import app


async def main():
    await db.init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Start a mission
        r = await client.post(
            "/api/missions/start",
            json={"engine_id": "TAPAS-BH-201-001", "name": "Test", "duration_s": 10},
        )
        mid = r.json().get("mission_id")
        print("1 START:", r.status_code, r.json())

        await asyncio.sleep(2)

        # 2. Engine state: live RPM and throttle
        r = await client.get("/api/engine/TAPAS-BH-201-001/state")
        d = r.json()
        print(
            "2 STATE: rpm=%r throttle=%r h_index=%r rtb=%r rul=%r sensors=%r"
            % (
                d.get("observed", {}).get("rpm"),
                d.get("observed", {}).get("throttle"),
                d.get("health_index"),
                d.get("rtb_alert"),
                d.get("rul_minutes"),
                d.get("sensor_status"),
            )
        )

        # 3. Inject a fault
        r = await client.post(
            "/api/faults/inject", json={"fault_type": "MISFIRE", "severity": 0.8}
        )
        print("3 INJECT:", r.status_code, r.json())

        r = await client.get("/api/engine/TAPAS-BH-201-001/state")
        d = r.json()
        print(
            "4 AFTER INJECT: rtb=%r fault=%r h_index=%r"
            % (d.get("rtb_alert"), d.get("fault_class"), d.get("health_index"))
        )

        # 4. Clear faults
        r = await client.post("/api/faults/clear")
        print("5 CLEAR:", r.status_code, r.json())

        r = await client.get("/api/engine/TAPAS-BH-201-001/state")
        d = r.json()
        print(
            "6 AFTER CLEAR: rtb=%r fault=%r h_index=%r"
            % (d.get("rtb_alert"), d.get("fault_class"), d.get("health_index"))
        )

        # 5. Health timeline field name
        r = await client.get("/api/reports/%s/health-timeline" % mid)
        tj = r.json()
        print(
            "7 TIMELINE: count=%r first=%r"
            % (tj.get("count"), tj.get("data", [{}])[0] if tj.get("data") else None)
        )

        # 6. CSV vs JSON download
        r = await client.get("/api/reports/%s/download/csv" % mid)
        print(
            "8 CSV: status=%r content-type=%r bytes=%r"
            % (r.status_code, r.headers.get("content-type"), len(r.content))
        )
        r = await client.get("/api/reports/%s/download" % mid)
        print(
            "9 JSON dl: status=%r content-type=%r"
            % (r.status_code, r.headers.get("content-type"))
        )


asyncio.run(main())
