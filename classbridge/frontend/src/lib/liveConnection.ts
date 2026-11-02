// Browser WebSockets can remain CONNECTING after a VPN/background transition.
// Own deadlines and socket identity here; recovery never starts the microphone.
export const CONNECT_TIMEOUT_MS = 10_000;
export const HEARTBEAT_INTERVAL_MS = 10_000;
// Allow the backend's bounded stop/finalization operation to finish first.
export const HEARTBEAT_TIMEOUT_MS = 45_000;
const MAX_RETRIES = 6;

interface Options {
  url: () => string;
  socket?: (url: string) => WebSocket;
  onSocket: (socket: WebSocket | null) => void;
  onState: (state: string) => void;
  onMessage: (data: string) => void;
  onLost: () => void;
  onNotice: (message: string) => void;
}

export function connectLive(options: Options) {
  let current: WebSocket | null = null;
  let disposed = false, terminal = false, attempts = 0;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let deadline: ReturnType<typeof setTimeout> | undefined;
  let heartbeat: ReturnType<typeof setTimeout> | undefined;
  let stable: ReturnType<typeof setTimeout> | undefined;
  let awaitingReply = false;

  const clearTimers = () => {
    clearTimeout(deadline);
    clearTimeout(heartbeat);
    clearTimeout(stable);
    deadline = heartbeat = stable = undefined;
    awaitingReply = false;
  };
  const detach = () => {
    const socket = current;
    current = null;
    clearTimers();
    options.onSocket(null);
    if (socket) {
      socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
      try { socket.close(); } catch { /* A half-open transport may reject close. */ }
    }
  };
  const lost = (code = 1006, message = "") => {
    if (disposed) return;
    detach();
    options.onLost();
    if ([4001, 4401, 4403, 4404].includes(code)) {
      terminal = true;
      options.onState("已断开");
      options.onNotice(code === 4001
        ? "会话已在另一页面打开；此页面已停止连接。"
        : "连接被拒绝，请重新登录并检查会话权限。");
      return;
    }
    if (message) options.onNotice(message);
    if (attempts < MAX_RETRIES) {
      attempts++;
      options.onState("断线，恢复中");
      retry = setTimeout(connect, Math.min(15_000, 750 * 2 ** attempts));
    } else {
      terminal = true;
      options.onState("已断开");
      options.onNotice("无法连接服务端。已保存字幕不会丢失，请点击重新连接；若仍失败，请重新登录。");
    }
  };
  const probe = () => {
    if (disposed || !current || current.readyState !== 1 || awaitingReply) return;
    awaitingReply = true;
    deadline = setTimeout(() => lost(1006, "连接长时间无响应，正在恢复；录音需手动重新开始。"), HEARTBEAT_TIMEOUT_MS);
    try { current.send(JSON.stringify({ type: "ping" })); }
    catch { lost(1006, "连接已中断，正在恢复。"); }
  };
  const scheduleHeartbeat = () => {
    heartbeat = setTimeout(() => {
      if (disposed || !current) return;
      probe();
      if (current) scheduleHeartbeat();
    }, HEARTBEAT_INTERVAL_MS);
  };
  function connect() {
    if (disposed || terminal) return;
    clearTimeout(retry);
    retry = undefined;
    options.onState(attempts ? "正在恢复记录" : "连接中");
    let socket: WebSocket;
    try { socket = (options.socket || ((url) => new WebSocket(url)))(options.url()); }
    catch { lost(1006, "无法建立连接，请检查网络和访问地址。"); return; }
    current = socket;
    options.onSocket(socket);
    const isCurrent = () => !disposed && current === socket;
    deadline = setTimeout(() => {
      if (isCurrent()) lost(1006, "连接超过 10 秒未完成，正在重试。请确认 VPN 和后端服务正常。");
    }, CONNECT_TIMEOUT_MS);
    socket.onopen = () => {
      if (!isCurrent()) return;
      clearTimeout(deadline);
      deadline = undefined;
      options.onState("已连接");
      options.onNotice("");
      // Rapid accept/close loops must still exhaust the retry budget.
      stable = setTimeout(() => { if (isCurrent()) attempts = 0; }, 30_000);
      scheduleHeartbeat();
    };
    socket.onmessage = ({ data }) => {
      if (!isCurrent()) return;
      if (awaitingReply) {
        clearTimeout(deadline);
        deadline = undefined;
        awaitingReply = false;
      }
      options.onMessage(data);
    };
    socket.onerror = () => {
      if (isCurrent()) lost(1006, "连接异常，正在重试；持续失败时请重新登录并检查服务端日志。");
    };
    socket.onclose = ({ code }) => { if (isCurrent()) lost(code); };
  }
  connect();
  return {
    resume() {
      if (disposed || terminal) return;
      if (current?.readyState === 1) probe();
      else if (!current) connect();
      // A pending handshake already has its own deadline.
    },
    dispose() {
      disposed = true;
      clearTimeout(retry);
      detach();
    },
  };
}
