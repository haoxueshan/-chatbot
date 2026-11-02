import assert from "node:assert/strict";
import { test, type TestContext } from "node:test";
import {
  connectLive, CONNECT_TIMEOUT_MS, HEARTBEAT_INTERVAL_MS, HEARTBEAT_TIMEOUT_MS,
} from "../src/lib/liveConnection.ts";

class FakeSocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  sent: string[] = [];
  constructor(readonly url: string) {}
  send(data: string) { this.sent.push(data); }
  close() { this.readyState = 3; }
  open() { this.readyState = 1; this.onopen?.(); }
  receive(data: string) { this.onmessage?.({ data }); }
  fail(code = 1006) { this.readyState = 3; this.onclose?.({ code }); }
}

function fixture(t: TestContext) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const sockets: FakeSocket[] = [], states: string[] = [], messages: string[] = [];
  let lost = 0, sequence = 7;
  const controller = connectLive({
    url: () => `wss://example.test/ws/sessions/lesson?after_seq=${sequence}`,
    socket: (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket as unknown as WebSocket;
    },
    onSocket() {},
    onState: (state) => states.push(state),
    onMessage: (message) => { messages.push(message); sequence = 19; },
    onLost: () => { lost++; },
    onNotice() {},
  });
  t.after(() => controller.dispose());
  return { controller, sockets, states, messages, lost: () => lost };
}

test("a stuck handshake times out and late callbacks cannot revive the old socket", (t) => {
  const f = fixture(t), old = f.sockets[0];
  const staleOpen = old.onopen!, staleMessage = old.onmessage!;
  t.mock.timers.tick(CONNECT_TIMEOUT_MS);
  assert.equal(old.readyState, 3);
  assert.equal(f.states.at(-1), "断线，恢复中");
  assert.equal(f.lost(), 1);
  t.mock.timers.tick(1_500);
  assert.equal(f.sockets.length, 2);
  staleOpen(); staleMessage({ data: "old result" });
  assert.equal(f.states.at(-1), "正在恢复记录");
  assert.deepEqual(f.messages, []);
  f.sockets[1].open();
  assert.equal(f.states.at(-1), "已连接");
  assert.deepEqual(f.sockets[1].sent, []); // Recovery never sends start/audio.
});

test("handshake retries have a finite budget even when browsers emit no close event", (t) => {
  const f = fixture(t);
  for (let i = 0; i < 7; i++) {
    t.mock.timers.tick(CONNECT_TIMEOUT_MS);
    if (i < 6) t.mock.timers.tick(15_000);
  }
  assert.equal(f.sockets.length, 7);
  assert.equal(f.states.at(-1), "已断开");
  f.controller.resume();
  t.mock.timers.tick(120_000);
  assert.equal(f.sockets.length, 7);
});

test("foreground probing detects a silently broken open socket without restarting capture", (t) => {
  const f = fixture(t), socket = f.sockets[0];
  socket.open();
  f.controller.resume(); f.controller.resume();
  assert.deepEqual(socket.sent.map(JSON.parse), [{ type: "ping" }]);
  t.mock.timers.tick(HEARTBEAT_TIMEOUT_MS);
  assert.equal(f.lost(), 1);
  assert.equal(socket.readyState, 3);
  t.mock.timers.tick(1_500);
  assert.equal(f.sockets.length, 2);
});

test("live messages satisfy the heartbeat and reconnect uses the latest event cursor", (t) => {
  const f = fixture(t), socket = f.sockets[0];
  socket.open();
  t.mock.timers.tick(HEARTBEAT_INTERVAL_MS);
  socket.receive("stable caption");
  assert.equal(f.lost(), 0);
  socket.fail();
  t.mock.timers.tick(1_500);
  assert.ok(f.sockets[1].url.endsWith("after_seq=19"));
  const staleClose = f.sockets[1].onclose!;
  f.controller.dispose();
  staleClose({ code: 1006 });
  t.mock.timers.tick(120_000);
  assert.equal(f.sockets.length, 2);
  assert.equal(f.lost(), 1);
});

test("replacement/auth rejection stays terminal on foreground and online events", (t) => {
  const f = fixture(t);
  f.sockets[0].open();
  f.sockets[0].fail(4001);
  f.controller.resume();
  t.mock.timers.tick(120_000);
  assert.equal(f.sockets.length, 1);
  assert.equal(f.states.at(-1), "已断开");
});

test("rapid accept-close loops cannot reset the retry budget", (t) => {
  const f = fixture(t);
  for (let i = 0; i < 7; i++) {
    f.sockets.at(-1)!.open();
    f.sockets.at(-1)!.fail();
    t.mock.timers.tick(15_000);
  }
  assert.equal(f.sockets.length, 7);
  assert.equal(f.states.at(-1), "已断开");
});
