"""Deterministic admission tests: no network or paid model calls."""
import gc
import pytest

from app.services.incremental_translation import PreviewBudget
from test_incremental_translation import scheduler, flush


class Owner:
    pass


def test_waiting_capture_precedes_reentrant_owner_and_preserves_rate_limit():
    gate = PreviewBudget()
    a, b, c = Owner(), Owner(), Owner()
    assert gate.acquire(0, 1, 3, owner=a)
    assert not gate.acquire(0, 1, 3, owner=b)
    assert not gate.acquire(0, 1, 3, owner=c)
    gate.release()
    assert not gate.acquire(1, 1, 3, owner=a)
    assert gate.acquire(1, 1, 3, owner=b)
    gate.release()
    assert not gate.acquire(2, 1, 3, owner=a)
    assert gate.acquire(2, 1, 3, owner=c)
    gate.release()
    assert not gate.acquire(3, 1, 3, owner=a)
    assert gate.acquire(60, 1, 3, owner=a)
    gate.release()
    assert gate.active == 0


def test_withdraw_stale_and_collected_owners_do_not_block_admission():
    gate = PreviewBudget()
    a, b = Owner(), Owner()
    assert not gate.acquire(0, 0, 10, owner=a)
    gate.withdraw(a)
    assert gate.acquire(0, 1, 10, owner=b)
    gate.release()
    assert not gate.acquire(0, 0, 10, owner=a)
    assert gate.acquire(5, 1, 10, owner=b)
    gate.release()
    assert not gate.acquire(6, 0, 10, owner=a)
    del a
    gc.collect()
    assert not gate.waiters
    assert gate.acquire(6, 1, 10, owner=b)
    gate.release()


@pytest.mark.asyncio
async def test_completion_callback_cannot_steal_waiting_captures_slot():
    gate = PreviewBudget()
    a, provider_a, clock_a, _ = scheduler()
    b, provider_b, clock_b, _ = scheduler()
    a.budget = b.budget = gate
    try:
        a.update('a1', 1, 'First complete sentence.', 0, 1000)
        a.update('a2', 1, 'Second complete sentence.', 0, 1000)
        b.update('b1', 1, 'Other capture sentence.', 0, 1000)
        clock_a[0] = clock_b[0] = 3
        a.tick()
        b.tick()
        await flush()
        # A already queued its second sentence before B arrived; it may finish
        # that turn, but cannot re-enter ahead of B after relinquishing it.
        b.tick()
        await flush()
        b.tick()
        await flush()
        assert provider_b.calls == ['Other capture sentence.']
        assert len(provider_a.calls) <= 2
    finally:
        await a.close()
        await b.close()
    assert gate.active == 0
    assert not gate.waiters