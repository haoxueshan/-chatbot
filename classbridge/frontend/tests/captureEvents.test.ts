import assert from "node:assert/strict";
import { test } from "node:test";
import { isCurrentCaptureEvent } from "../src/lib/captureEvents.ts";
import type { BridgeEvent } from "../src/lib/types.ts";

const event = (extra: Partial<BridgeEvent>): BridgeEvent => ({
  type: "session.state",
  event_id: "event",
  session_id: "session",
  event_seq: 8,
  state: "stopped",
  stream_id: "old-stream",
  request_id: "old-request",
  ...extra,
});

test("replayed stop/failure from an older task cannot stop a new preparation", () => {
  for (const type of ["session.state", "processing.failed"]) {
    assert.equal(
      isCurrentCaptureEvent(event({ type }), "new-request", null, 5),
      false,
    );
    assert.equal(
      isCurrentCaptureEvent(event({ type }), "new-request", "new-stream", 5),
      false,
    );
  }
  assert.equal(
    isCurrentCaptureEvent(
      event({ request_id: "new-request", stream_id: "new-stream" }),
      "new-request",
      "new-stream",
      5,
    ),
    true,
  );
  assert.equal(
    isCurrentCaptureEvent(
      event({ request_id: "new-request", event_seq: 4 }),
      "new-request",
      null,
      5,
    ),
    false,
  );
});

test("start rejection, draining, and background failures retain distinct identities", () => {
  assert.equal(
    isCurrentCaptureEvent(
      event({
        type: "processing.failed",
        event_seq: 0,
        request_id: "new-request",
      }),
      "new-request",
      null,
      5,
    ),
    true,
  );
  assert.equal(
    isCurrentCaptureEvent(
      event({ request_id: "new-request", stream_id: "new-stream" }),
      "new-request",
      "new-stream",
      5,
    ),
    true,
  );
  assert.equal(
    isCurrentCaptureEvent(
      event({ request_id: "new-request", task_kind: "suggest_correction" }),
      "new-request",
      null,
      5,
    ),
    false,
  );
  assert.equal(
    isCurrentCaptureEvent(
      event({ request_id: "new-request", recovered: true }),
      "new-request",
      null,
      5,
    ),
    false,
  );
  assert.equal(
    isCurrentCaptureEvent(
      event({ request_id: undefined, stream_id: "new-stream" }),
      "new-request",
      "new-stream",
      5,
    ),
    true,
  );
  assert.equal(
    isCurrentCaptureEvent(
      event({ request_id: undefined }),
      "new-request",
      null,
      5,
    ),
    false,
  );
  assert.equal(isCurrentCaptureEvent(event({}), null, null, 5), false);
});
