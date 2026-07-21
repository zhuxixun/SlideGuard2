import asyncio

from slideguard.server.lifecycle import LifecycleController


def test_idle_disconnect_requests_shutdown() -> None:
    async def scenario() -> list[str]:
        events: list[str] = []
        lifecycle = LifecycleController(idle_seconds=0.01)
        lifecycle.set_shutdown_callback(lambda: events.append("shutdown"))
        await lifecycle.connected()
        await lifecycle.disconnected()
        await asyncio.sleep(0.03)
        return events

    assert asyncio.run(scenario()) == ["shutdown"]


def test_reconnect_cancels_idle_shutdown() -> None:
    async def scenario() -> list[str]:
        events: list[str] = []
        lifecycle = LifecycleController(idle_seconds=0.02)
        lifecycle.set_shutdown_callback(lambda: events.append("shutdown"))
        await lifecycle.connected()
        await lifecycle.disconnected()
        await lifecycle.connected()
        await asyncio.sleep(0.04)
        await lifecycle.close()
        return events

    assert asyncio.run(scenario()) == []

