"""Phase 8 kill -9 recovery test script.
Runs on the production server. Must be executed inside the app container.
"""
import asyncio
import os
import signal
import subprocess
import sys
import time

TEST_TASK_TYPE = "phase8_kill9_test"
TEST_TASK_ID = "phase8_kill9_001"
LEASE_SEC = 15
HEARTBEAT_SEC = 3


async def main():
    print("=== Phase 8: kill -9 Recovery Test ===\n")

    from app.services.task_queue_service import task_queue
    from app.core.config import settings

    # 1. Enqueue test task
    print("1. Enqueuing test task...")
    result = await task_queue.enqueue_v2(
        TEST_TASK_TYPE,
        {"test": "kill9", "ts": time.time()},
        task_id=TEST_TASK_ID,
        max_retries=0,
    )
    assert result.accepted, f"Enqueue failed: {result.reason}"
    print(f"   task_id={TEST_TASK_ID} accepted")

    # 2. Start worker in background (separate process)
    print("\n2. Starting worker process...")
    worker_proc = subprocess.Popen(
        [sys.executable, "-c", f"""
import asyncio
import signal
import sys
import time

stop_flag = False

def handle_sigterm(signum, frame):
    global stop_flag
    stop_flag = True
    print("WORKER: SIGTERM received, draining...", flush=True)

signal.signal(signal.SIGTERM, handle_sigterm)

async def run():
    from app.services.task_queue_service import task_queue

    task_type = "{TEST_TASK_TYPE}"
    task_id = "{TEST_TASK_ID}"

    print(f"WORKER: PID={{os.getpid()}} starting...", flush=True)

    # Dequeue the test task
    task = await task_queue.dequeue_v2(task_type, lease_sec={LEASE_SEC})
    if task is None:
        print(f"WORKER: No task found", flush=True)
        return

    print(f"WORKER: Claimed task_id={{task.task_id}} gen={{task.generation}}", flush=True)

    # Write PID file so parent can find us
    with open("/tmp/phase8_worker_pid", "w") as f:
        f.write(str(os.getpid()))

    # Heartbeat loop — keep the task alive
    heartbeat_interval = {HEARTBEAT_SEC}
    for i in range(60):  # max 60 iterations
        if stop_flag:
            print(f"WORKER: Stop flag set, releasing task", flush=True)
            # Try safe release
            try:
                await task_queue.heartbeat_v2(task, lease_sec=1)
            except Exception:
                pass
            return

        ok = await task_queue.heartbeat_v2(task, lease_sec={LEASE_SEC})
        if not ok:
            print(f"WORKER: Heartbeat rejected (fenced!), stopping", flush=True)
            return
        print(f"WORKER: Heartbeat {{i+1}}/60 ok", flush=True)
        await asyncio.sleep(heartbeat_interval)

    print("WORKER: Normal completion after 60 iterations", flush=True)

asyncio.run(run())
        """],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(f"   Worker PID: {worker_proc.pid}")

    # 3. Wait for worker to claim the task
    print("\n3. Waiting for worker to claim task...")
    for i in range(30):
        await asyncio.sleep(0.5)
        # Check if PID file exists
        try:
            with open("/tmp/phase8_worker_pid", "r") as f:
                worker_pid = int(f.read().strip())
            print(f"   Worker PID from file: {worker_pid}")
            break
        except (FileNotFoundError, ValueError):
            pass
    else:
        # Check worker output for debugging
        try:
            out, _ = worker_proc.communicate(timeout=1)
            print(f"   Worker output: {out[:500]}")
        except subprocess.TimeoutExpired:
            print("   Worker still running but no PID file found")
        print("   FAIL: Worker did not create PID file")
        worker_proc.kill()
        return 1

    # 4. Verify task is processing
    print("\n4. Verifying task is in processing state...")
    metrics = await task_queue.get_metrics_v2(task_types=[TEST_TASK_TYPE])
    print(f"   Queue metrics: ready={metrics.ready} processing={metrics.processing}")

    # Check the task directly
    task = await task_queue.dequeue_v2(TEST_TASK_TYPE, lease_sec=1)
    if task is not None:
        print("   FAIL: Task still available for claim — worker didn't claim it!")
        worker_proc.kill()
        return 1
    print("   OK: Task not available for re-claim (held by worker)")

    # 5. Record current generation
    # Get task info from Redis
    import redis.asyncio as aioredis
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    task_key = f"taskq:v2:task:{TEST_TASK_ID}"
    task_data = await r.hgetall(task_key)
    gen_before = task_data.get("generation", "?")
    owner_before = task_data.get("owner_token", "?")
    print(f"\n5. Pre-kill state: gen={gen_before} owner={owner_before[:12]}...")

    # 6. EXECUTE kill -9
    print(f"\n6. EXECUTING kill -9 {worker_pid}...")
    os.kill(worker_pid, signal.SIGKILL)
    worker_proc.wait(timeout=5)
    print(f"   Worker process terminated, rc={worker_proc.returncode}")

    # 7. Wait for lease expiration + reaper
    print(f"\n7. Waiting {LEASE_SEC + 5}s for lease expiry + reaper...")
    await asyncio.sleep(LEASE_SEC + 5)

    # 8. Run reaper
    print("8. Running reaper...")
    reclaimed = await task_queue._reclaim_expired(TEST_TASK_TYPE)
    print(f"   Reclaimed: {reclaimed} tasks")

    # 9. Verify task can be claimed by new worker
    print("\n9. Claiming task with new worker...")
    task2 = await task_queue.dequeue_v2(TEST_TASK_TYPE, lease_sec=30)
    if task2 is None:
        print("   FAIL: Task was lost — could not be reclaimed!")
        await r.aclose()
        return 1

    gen_after = task2.generation
    print(f"   Reclaimed: task_id={task2.task_id} gen={gen_after}")

    # 10. Verify generation incremented
    if int(gen_after) > int(gen_before):
        print(f"   OK: Generation incremented ({gen_before} -> {gen_after})")
    else:
        print(f"   WARN: Generation not incremented ({gen_before} -> {gen_after})")

    # 11. Verify stale worker is fenced
    print("\n10. Verifying stale worker fencing...")
    # Try to heartbeat with old owner — should fail
    from app.services.task_queue_service import Task as QueueTask
    stale_task = QueueTask(
        task_id=TEST_TASK_ID,
        task_type=TEST_TASK_TYPE,
        payload={"test": "kill9"},
        status=None,
        owner_token=owner_before,
        generation=int(gen_before),
        retry_count=0,
        lease_expires_at=0,
    )
    hb_ok = await task_queue.heartbeat_v2(stale_task, lease_sec=30)
    if hb_ok:
        print("   FAIL: Stale worker heartbeat was accepted!")
    else:
        print("   OK: Stale worker heartbeat rejected (fenced)")

    # 12. Complete the task
    print("\n11. Completing task...")
    ok = await task_queue.complete_v2(task2)
    print(f"   complete_v2 returned: {ok}")

    # 13. Final verification
    print("\n12. Final queue state:")
    metrics = await task_queue.get_metrics_v2(task_types=[TEST_TASK_TYPE])
    print(f"   ready={metrics.ready} processing={metrics.processing}")

    # Cleanup
    try:
        os.remove("/tmp/phase8_worker_pid")
    except FileNotFoundError:
        pass

    # Verify clean state
    if metrics.processing == 0 and metrics.ready == 0:
        print("\n=== PASS: kill -9 recovery test passed ===")
        await r.aclose()
        return 0
    else:
        print(f"\n=== FAIL: Queue not clean: ready={metrics.ready} processing={metrics.processing} ===")
        await r.aclose()
        return 1


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
