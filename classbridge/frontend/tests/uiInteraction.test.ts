import assert from "node:assert/strict";
import { test, afterEach, after } from "node:test";
import { Window } from "happy-dom";

// Real DOM events and React effects (not SSR snapshots). No live services or data.
const dom = new Window({ url: "http://localhost/" });
for (const name of [
  "window",
  "document",
  "navigator",
  "location",
  "history",
  "HTMLElement",
  "HTMLInputElement",
  "HTMLSelectElement",
  "Node",
  "NodeFilter",
  "Element",
  "Event",
  "KeyboardEvent",
  "CustomEvent",
  "MutationObserver",
  "getComputedStyle",
  "HTMLTextAreaElement",
]) {
  Object.defineProperty(globalThis, name, {
    configurable: true,
    value: name === "window" ? dom : (dom as any)[name],
  });
}
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
const React = await import("react");
const { act } = React;
const { createRoot } = await import("react-dom/client");
const { Sidebar, ResponsiveSidebar, Titlebar } =
  await import("../src/components/Shell.tsx");
const { Home, NewSession } = await import("../src/components/Home.tsx");
const { Settings } = await import("../src/components/Settings.tsx");
const { Library } = await import("../src/components/Library.tsx");
const { SessionView } = await import("../src/components/SessionView.tsx");
const { default: App } = await import("../src/App.tsx");
const h = React.createElement;
const preferences = {
  theme: "light",
  subtitle_size: 24,
  show_original: true,
  retain_audio: false,
  audio_retention_days: 7,
  terms: [{ source: "작업기억", target: "工作记忆" }],
  asr_context: "인지심리학",
  target_language: "zh-CN",
} as any;
const lesson = {
  id: "lesson",
  title: "韩英课堂",
  mode: "demo",
  kind: "classroom",
  status: "idle",
  retain_audio: false,
  duration_ms: 90000,
  captured_ms: 60000,
  created_at: "2026-11-02T00:00:00Z",
  segments: [],
  stages: [],
} as any;
const other = {
  ...lesson,
  id: "other",
  title: "会议记录",
  kind: "meeting",
  mode: "real",
};
const roots: ReturnType<typeof createRoot>[] = [];
async function mount(element: React.ReactNode) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await act(async () => root.render(element));
  return {
    root,
    container,
    render: async (next: React.ReactNode) => {
      await act(async () => root.render(next));
    },
  };
}
function button(name: string, scope: ParentNode = document) {
  const result = Array.from(
    scope.querySelectorAll<HTMLButtonElement>("button"),
  ).find(
    (b) =>
      b.getAttribute("aria-label") === name || b.textContent?.trim() === name,
  );
  assert.ok(result, `button exists: ${name}`);
  return result;
}
async function click(name: string, scope?: ParentNode) {
  await act(async () => button(name, scope).click());
}
function json(data: unknown) {
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
}
function setupApi() {
  globalThis.fetch = async (url) =>
    json(
      String(url).includes("auth/me")
        ? { id: "u", username: "test" }
        : String(url).endsWith("/settings")
          ? preferences
          : String(url).endsWith("/sessions")
            ? [lesson, other]
            : String(url).includes("/sessions/lesson")
              ? lesson
              : String(url).includes("/sessions/other")
                ? other
                : [],
    );
}
class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 0;
  sent: any[] = [];
  closed = false;
  onopen: any;
  onmessage: any;
  onerror: any;
  onclose: any;
  constructor(public url: string) {
    Socket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.closed = true;
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  event(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}
globalThis.WebSocket = Socket as any;
setupApi();
afterEach(async () => {
  await act(async () => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
  dom.history.replaceState(null, "", "/");
  Socket.instances.length = 0;
  setupApi();
});
after(async () => dom.happyDOM.close());

for (const failure of ["backpressure", "closed", "send-throws"]) {
  test(`audio ${failure} releases capture once and rejects late frames`, async () => {
    const { useLive } = await import("../src/lib/useLive.ts");
    const { AudioCapture } = await import("../src/lib/audio.ts");
    const originalStart = AudioCapture.prototype.start, originalStop = AudioCapture.prototype.stop;
    let onFrame!: (frame: ArrayBuffer) => void, stopped = 0, state!: ReturnType<typeof useLive>;
    AudioCapture.prototype.start = async function (callback) { onFrame = callback; };
    AudioCapture.prototype.stop = function () { stopped++; };
    function Probe() { state = useLive(other, () => {}); return null; }
    try {
      await mount(h(Probe));
      const socket = Socket.instances.at(-1)! as Socket & { bufferedAmount: number };
      await act(async () => socket.open());
      await act(async () => state.start());
      const request = socket.sent.find(e => e.type === "start").request_id;
      await act(async () => socket.event({type:"session.state",session_id:other.id,stream_id:"current",request_id:request,event_seq:1,state:"recording",ready:true}));
      socket.bufferedAmount = 63360;
      const send = socket.send.bind(socket);
      let frames = 0, controls = 0;
      socket.send = ((data: string | ArrayBuffer) => {
        if (data instanceof ArrayBuffer) {
          if (failure === "send-throws") throw new Error("mock audio write failed");
          frames++; socket.bufferedAmount += data.byteLength;
        } else {
          controls++;
          if (failure === "send-throws") throw new Error("mock control write failed");
          send(data);
        }
      }) as typeof socket.send;
      if (failure === "closed") socket.readyState = 3;
      await act(async () => { onFrame(new ArrayBuffer(640)); onFrame(new ArrayBuffer(640)); onFrame(new ArrayBuffer(640)); });
      assert.equal(state.active, false);
      assert.equal(stopped, 1);
      assert.equal(frames, failure === "backpressure" ? 1 : 0);
      assert.equal(controls, failure === "backpressure" ? 2 : failure === "send-throws" ? 1 : 0);
      if (failure === "send-throws") assert.equal(socket.closed, true);
      await act(async () => state.stop());
      assert.equal(stopped, 1);
    } finally {
      AudioCapture.prototype.start = originalStart;
      AudioCapture.prototype.stop = originalStop;
    }
  });
}

test("settings save and restore a selectable default without clearing tagged terms", async () => {
  let saved:any;
  const original={...preferences,terms:[...preferences.terms,{source:"기억",target:"memory",target_language:"en"}]};
  const view=await mount(h(Settings,{preferences:original,save:async(p:any)=>{saved=p;}}));
  const select=view.container.querySelector<HTMLSelectElement>('[aria-label="默认字幕翻译语言"]')!;
  assert.equal(select.options.length,14);
  await act(async()=>{select.value="ja";select.dispatchEvent(new dom.Event("change",{bubbles:true}));});
  await click("保存偏好");
  assert.equal(saved.target_language,"ja");
  assert.deepEqual(saved.terms,original.terms);
  assert.match(view.container.textContent!,/默认字幕翻译语言：日语/);
  await view.render(null);
  await view.render(h(Settings,{preferences:saved,save:async()=>{}}));
  assert.equal(view.container.querySelector<HTMLSelectElement>('[aria-label="默认字幕翻译语言"]')!.value,"ja");
});

test("new session uses the saved target and demo cannot silently call a non-Chinese translation", async () => {
  let saved:any;
  const view=await mount(h(NewSession,{kind:"classroom",defaultTarget:"en",close(){},submit:async(data:any)=>{saved=data;}}));
  const select=document.querySelector<HTMLSelectElement>('[aria-label="字幕翻译目标语言"]')!;
  assert.equal(select.value,"en");
  assert.equal(button("创建会话").disabled,true);
  assert.match(document.body.textContent!,/模拟演示仅支持简体中文/);
  assert.equal(saved,undefined);
  const real=Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find(b=>b.textContent?.includes("真实课堂"))!;
  await act(async()=>real.click());
  await click("创建会话");
  assert.equal(saved.target_language,"en");
  assert.equal(saved.mode,"real");
});

test("subtitle labels and RTL direction follow the session snapshot despite preference changes", async () => {
  const props={session:{...lesson,mode:"real",target_language:"ar"},preferences:{...preferences,target_language:"ja"},
    onActivity(){},refresh(){},back(){},notify(){},openSession(){},deleted(){}} as any;
  const view=await mount(h(SessionView,props));
  const socket=Socket.instances.at(-1)!;
  await act(async()=>socket.open());
  const base={session_id:"lesson",stream_id:"s",sentence_id:"1",source_revision:1,translation_revision:1,event_seq:0,start_ms:0,end_ms:1000,mode:"real"};
  await act(async()=>socket.event({...base,type:"transcript.partial",event_id:"p",text:"한국어 원문"}));
  await act(async()=>socket.event({...base,type:"translation.partial",event_id:"t",translation:"مرحبا بالعالم",target_language:"ar"}));
  assert.match(view.container.textContent!,/临时译文/);
  assert.equal(view.container.querySelector('[lang="ar"]')?.getAttribute("dir"),"rtl");
  await act(async()=>socket.event({...base,type:"transcript.final",event_id:"f",event_seq:1,text:"한국어 원문"}));
  assert.match(view.container.textContent!,/正在翻译为阿拉伯语/);
  await act(async()=>socket.event({...base,type:"translation.final",event_id:"tf",event_seq:2,translation:"مرحبا بالعالم",target_language:"ar"}));
  assert.match(view.container.textContent!,/阿拉伯语翻译已完成/);
  await view.render(h(SessionView,{...props,preferences:{...preferences,target_language:"en"}}));
  assert.match(view.container.textContent!,/阿拉伯语翻译已完成/);
  assert.equal(Socket.instances.length,1);
});

test("opening a new-session form from the mobile drawer retains input focus and restores menu on Escape", async () => {
  const original = dom.matchMedia.bind(dom);
  dom.matchMedia = (() => ({
    matches: true,
    addEventListener() {},
    removeEventListener() {},
  })) as any;
  try {
    await mount(h(App));
    await click("打开导航");
    await click("新建会话");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    assert.equal(document.activeElement?.tagName, "INPUT");
    assert.equal(document.querySelectorAll('[role="dialog"]').length, 1);
    await act(async () =>
      document.dispatchEvent(
        new dom.KeyboardEvent("keydown", {
          key: "Escape",
          bubbles: true,
        }) as any,
      ),
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    assert.equal(document.querySelector('[role="dialog"]'), null);
    assert.equal(
      document.activeElement?.getAttribute("aria-label"),
      "打开导航",
    );
  } finally {
    dom.matchMedia = original;
  }
});

test("new-session failure remains retryable; idle Escape dismisses with valid accessible title", async () => {
  let closed = 0;
  await mount(
    h(NewSession, {
      kind: "classroom",
      close: () => closed++,
      submit: async () => {
        throw new Error("测试服务暂不可用");
      },
    }),
  );
  const dialog = document.querySelector('[role="dialog"]')!;
  assert.ok(document.getElementById(dialog.getAttribute("aria-labelledby")!));
  await act(async () =>
    document
      .querySelector("form")!
      .dispatchEvent(
        new dom.Event("submit", { bubbles: true, cancelable: true }) as any,
      ),
  );
  assert.match(
    document.querySelector('[role="alert"]')!.textContent!,
    /测试服务暂不可用/,
  );
  assert.equal(button("创建会话").disabled, false);
  assert.equal(button("关闭").disabled, false);
  await act(async () =>
    document.dispatchEvent(
      new dom.KeyboardEvent("keydown", { key: "Escape", bubbles: true }) as any,
    ),
  );
  assert.equal(closed, 1);
});

test("unmounting library clears its polling interval", async () => {
  const realSet = globalThis.setInterval,
    realClear = globalThis.clearInterval;
  const pending = new Set();
  globalThis.setInterval = ((...args: any[]) => {
    const id = (realSet as any)(...args);
    pending.add(id);
    return id;
  }) as any;
  globalThis.clearInterval = ((id: any) => {
    pending.delete(id);
    return realClear(id);
  }) as any;
  try {
    const view = await mount(h(Library, { notify() {} }));
    assert.equal(pending.size, 1);
    await view.render(null);
    assert.equal(pending.size, 0);
  } finally {
    globalThis.setInterval = realSet;
    globalThis.clearInterval = realClear;
  }
});

test("sidebar callbacks, selected route, create and capture navigation lock", async () => {
  const calls: string[] = [];
  const props = {
    page: "home",
    sessions: [lesson, other],
    activeId: "lesson",
    navigate: (p: string) => calls.push(p),
    select: (s: any) => calls.push(s.id),
    create: () => calls.push("create"),
    disabled: false,
  } as any;
  const view = await mount(h(Sidebar, props));
  await click("资料库");
  await click("新建会话");
  await act(async () =>
    view.container
      .querySelectorAll<HTMLButtonElement>(".recent-item")[1]
      .click(),
  );
  assert.deepEqual(calls, ["library", "create", "other"]);
  assert.equal(button("工作台").getAttribute("aria-current"), "page");
  await view.render(h(Sidebar, { ...props, disabled: true, collapsed: true }));
  await click("工作台");
  await click("新建会话");
  assert.deepEqual(calls, ["library", "create", "other"]);
  assert.equal(
    view.container.querySelectorAll<HTMLButtonElement>(".recent-item")[1]
      .disabled,
    true,
  );
  assert.equal(button("资料库").title, "资料库");
});

test("topbar theme callback and offline state, logout disabled during capture", async () => {
  let toggles = 0,
    logouts = 0;
  const props = {
    title: "工作台",
    dark: false,
    toggle: () => toggles++,
    logout: () => logouts++,
    disabled: true,
    online: false,
    username: "test",
    menu() {},
    collapse() {},
    collapsed: false,
    menuOpen: false,
  };
  const view = await mount(h(Titlebar, props));
  await click("切换深色主题");
  await click("退出登录");
  assert.equal(toggles, 1);
  assert.equal(logouts, 0);
  assert.match(view.container.textContent!, /网络离线/);
  await view.render(h(Titlebar, { ...props, dark: true }));
  assert.ok(button("切换浅色主题"));
});

test("dashboard opens correct session and creates each original kind with actual list statistics", async () => {
  const selected: string[] = [],
    kinds: string[] = [];
  const view = await mount(
    h(Home, {
      sessions: [lesson, other],
      search: "",
      setSearch() {},
      create: (k: string) => kinds.push(k),
      select: (s: any) => selected.push(s.id),
      library() {},
      settings() {},
    }),
  );
  for (const row of view.container.querySelectorAll<HTMLButtonElement>(
    ".session-row",
  ))
    await act(async () => row.click());
  for (const row of view.container.querySelectorAll<HTMLButtonElement>(
    ".dashboard-action",
  ))
    await act(async () => row.click());
  assert.deepEqual(selected, ["lesson", "other"]);
  assert.deepEqual(kinds, ["classroom", "meeting", "interview"]);
  assert.match(view.container.textContent!, /2 分钟/);
  assert.match(view.container.textContent!, /模拟演示/);
  assert.ok(!view.container.textContent!.includes("准确率"));
});

test("new-session dialog blocks dismissal while submitting and preserves create payload", async () => {
  let closed = 0,
    resolve: (value?: unknown) => void = () => {},
    payload: any;
  const props = {
    kind: "meeting",
    close: () => closed++,
    submit: (data: unknown) => {
      payload = data;
      return new Promise<void>((r) => {
        resolve = r;
      });
    },
  };
  await mount(h(NewSession, props));
  assert.ok(document.querySelector('[role="dialog"]'));
  assert.equal(document.activeElement?.tagName, "INPUT");
  assert.equal(
    (document.querySelector('input[type="checkbox"]') as HTMLInputElement)
      .disabled,
    true,
  );
  await act(async () =>
    document
      .querySelector("form")!
      .dispatchEvent(
        new dom.Event("submit", { bubbles: true, cancelable: true }) as any,
      ),
  );
  assert.equal(payload.kind, "meeting");
  assert.equal(payload.mode, "demo");
  assert.equal(button("关闭").disabled, true);
  await act(async () =>
    document.dispatchEvent(
      new dom.KeyboardEvent("keydown", { key: "Escape", bubbles: true }) as any,
    ),
  );
  assert.equal(closed, 0);
  await act(async () => resolve());
});

test("settings preserve all fields and classroom preset saves only on explicit save", async () => {
  let saved: any;
  const view = await mount(
    h(Settings, {
      preferences,
      save: async (value: any) => {
        saved = value;
      },
    }),
  );
  for (const label of [
    "外观与阅读",
    "语言与专业术语",
    "录音与麦克风",
    "音频与隐私",
    "模型连接状态",
    "识别热词强度",
  ])
    assert.ok(view.container.textContent!.includes(label));
  await click("应用韩英远场课堂预设（仍需点击保存）");
  assert.equal(saved, undefined);
  await click("保存偏好");
  assert.equal(saved.asr_language_mode, "ko_en");
  assert.equal(saved.asr_hotword_weight, 4);
  assert.equal(saved.asr_acoustic_profile, "far");
  assert.equal(saved.audio_processing_mode, "standard");
  assert.deepEqual(saved.terms, preferences.terms);
  assert.equal(saved.asr_context, preferences.asr_context);
  for (const key of [
    "theme",
    "subtitle_size",
    "show_original",
    "retain_audio",
    "target_language",
  ])
    assert.equal(saved[key], preferences[key]);
});

test("library keeps native upload entry, types and scanning limits", async () => {
  const view = await mount(h(Library, { notify() {} }));
  const input =
    view.container.querySelector<HTMLInputElement>('input[type="file"]')!;
  assert.equal(input.accept, ".pdf,.pptx,.docx");
  let selected = 0;
  input.addEventListener("click", () => selected++);
  await click("上传资料");
  assert.equal(selected, 1);
  assert.match(view.container.textContent!, /40 MB/);
  assert.match(view.container.textContent!, /扫描件/);
  assert.ok(view.container.querySelector(".upload-zone"));
  assert.ok(view.container.querySelector('input[aria-label="搜索资料"]'));
});

test("sidebar breakpoint listener is removed and only one navigation tree renders", async () => {
  const old = dom.matchMedia.bind(dom);
  let removed = 0,
    added = 0;
  const query = {
    matches: true,
    addEventListener() {
      added++;
    },
    removeEventListener() {
      removed++;
    },
  };
  dom.matchMedia = (() => query) as any;
  try {
    const setOpen = () => {};
    const view = await mount(
      h(ResponsiveSidebar, {
        page: "home",
        sessions: [],
        navigate() {},
        select() {},
        create() {},
        disabled: false,
        open: true,
        setOpen,
      }),
    );
    assert.equal(
      document.querySelectorAll('nav[aria-label="主导航"]').length,
      1,
    );
    await view.render(null);
    assert.equal(added, 1);
    assert.equal(removed, 1);
  } finally {
    dom.matchMedia = old;
  }
});

test("subtitle tabs, side collapse, focus and snapshot refresh do not recreate the live socket", async () => {
  const session = {
    ...lesson,
    segments: [
      {
        sentence_id: "sentence",
        stream_id: "stream",
        source_revision: 1,
        translation_revision: 1,
        text: "작업기억은 working memory입니다.",
        translation: "工作记忆是 working memory。",
        status: "final",
        source_final: true,
        translation_final: true,
        start_ms: 0,
        end_ms: 3000,
        mode: "demo",
      },
    ],
  };
  const props = {
    session,
    preferences,
    onActivity() {},
    refresh() {},
    back() {},
    notify() {},
    openSession() {},
    deleted() {},
  };
  const view = await mount(h(SessionView, props));
  const socket = Socket.instances.at(-1)!;
  await act(async () => socket.open());
  assert.match(view.container.textContent!, /작업기억은/);
  assert.match(view.container.textContent!, /工作记忆是/);
  assert.match(view.container.textContent!, /模拟演示，不调用付费 API/);
  assert.match(view.container.textContent!, /已连接/);
  await click("开始模拟");
  assert.ok(socket.sent.some((x) => x.type === "start"));
  const count = Socket.instances.length;
  await click("切换侧栏");
  await click("切换专注阅读");
  await act(async () =>
    view.container
      .querySelectorAll<HTMLButtonElement>(".mobile-tabs button")[2]
      .click(),
  );
  await view.render(h(SessionView, { ...props, session: { ...session } }));
  assert.equal(Socket.instances.length, count);
  assert.equal(socket.closed, false);
  assert.ok(button("停止模拟"));
  await click("停止模拟");
  assert.ok(socket.sent.some((x) => x.type === "stop"));
  await view.render(null);
  assert.equal(socket.closed, true);
});

test("responsive presentation and tools keep one real-mode capture until explicit stop", async () => {
  const { AudioCapture } = await import("../src/lib/audio.ts");
  const originalStart = AudioCapture.prototype.start, originalStop = AudioCapture.prototype.stop;
  let starts = 0, stops = 0;
  AudioCapture.prototype.start = async function () { starts++; };
  AudioCapture.prototype.stop = function () { stops++; };
  const props = {session:other, preferences, onActivity(){}, refresh(){}, back(){}, notify(){}, openSession(){}, deleted(){}};
  try {
    const view = await mount(h(SessionView, props));
    const socket = Socket.instances.at(-1)!;
    await act(async () => socket.open());
    await click("开始录音");
    const request = socket.sent.find(e=>e.type === "start");
    await act(async () => socket.event({type:"session.state",session_id:other.id,stream_id:"responsive-stream",request_id:request.request_id,event_seq:1,state:"recording",ready:true}));
    assert.equal(starts,1);
    const details = view.container.querySelector<HTMLDetailsElement>('.session-details')!;
    for(const [width,height] of [[390,844],[844,390],[1024,768],[1440,900]]) {
      dom.happyDOM.setWindowSize({width,height});
      await act(async () => { window.dispatchEvent(new Event('resize')); window.dispatchEvent(new Event('orientationchange')); });
      await act(async () => { details.open=true; });
      assert.equal(button('删除会话').disabled,true);
      assert.equal(button('清空').disabled,true);
      assert.equal(button('本会话资料').disabled,true);
      await click('切换侧栏');
      await click('切换专注阅读');
      await click('切换专注阅读');
      await act(async () => view.container.querySelectorAll<HTMLButtonElement>('.mobile-tabs button')[2].click());
      await act(async () => view.container.querySelectorAll<HTMLButtonElement>('.mobile-tabs button')[0].click());
      await view.render(h(SessionView,{...props,preferences:{...preferences,theme:'dark'}}));
      await act(async () => details.querySelector('summary')!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
      assert.equal(details.open,false);
      assert.equal(document.activeElement,details.querySelector('summary'));
      assert.equal(Socket.instances.length,1);
      assert.equal(socket.closed,false);
      assert.equal(starts,1);
      assert.equal(stops,0);
      assert.ok(button('停止录音'));
    }
    await click('停止录音');
    assert.equal(stops,1);
    assert.equal(socket.sent.filter(e=>e.type==='start').length,1);
    assert.equal(socket.sent.filter(e=>e.type==='stop').length,1);
    await view.render(null);
    assert.equal(socket.closed,true);
  } finally {
    AudioCapture.prototype.start=originalStart;
    AudioCapture.prototype.stop=originalStop;
  }
});

test("subtitle follow skips unchanged height, follows growth and respects history reading", async () => {
  const originalRAF=window.requestAnimationFrame, originalCancel=window.cancelAnimationFrame;
  const originalObserver=globalThis.ResizeObserver,resize=new Set<()=>void>();
  globalThis.ResizeObserver=class {
    constructor(public callback:()=>void){resize.add(callback);}
    observe(){} unobserve(){} disconnect(){resize.delete(this.callback);}
  } as any;
  const frames=new Map<number,FrameRequestCallback>();let next=0;
  window.requestAnimationFrame=(fn)=>{frames.set(++next,fn);return next;};
  window.cancelAnimationFrame=(id)=>{frames.delete(id);};
  async function paint(){await act(async()=>{for(const [id,fn] of [...frames]){frames.delete(id);fn(0);}});}
  try {
    const view=await mount(h(SessionView,{session:lesson,preferences,onActivity(){},refresh(){},back(){},notify(){},openSession(){},deleted(){}}));
    const socket=Socket.instances.at(-1)!;await act(async()=>socket.open());
    const list=view.container.querySelector<HTMLElement>('.subtitle-list')!;
    let height=1000,top=800,scrolls=0;
    Object.defineProperties(list,{scrollHeight:{configurable:true,get:()=>height},clientHeight:{configurable:true,get:()=>200},scrollTop:{configurable:true,get:()=>top,set:v=>{top=v;}}});
    list.scrollTo=((options:ScrollToOptions)=>{scrolls++;top=options.top!;}) as typeof list.scrollTo;
    const source={session_id:lesson.id,stream_id:'stream',sentence_id:'follow',source_revision:1,event_seq:1,type:'transcript.final',text:'source',event_id:'source'};
    await act(async()=>socket.event(source));await paint();scrolls=0;
    for(let i=0;i<20;i++){
      await act(async()=>socket.event({...source,type:'translation.partial',event_id:`mt-${i}`,event_seq:i+2,source_status:'final',translation:'译文'.repeat(i+1)}));
      await paint();
    }
    console.log({unchangedHeightScrolls:scrolls});assert.equal(scrolls,0);
    height=1100;
    for(const callback of resize){callback();callback();}
    assert.equal(frames.size,1);await paint();assert.equal(scrolls,1);
    await act(async()=>socket.event({...source,type:'translation.final',event_id:'done',event_seq:30,translation:'完整译文'}));await paint();
    assert.equal(scrolls,1);assert.equal(top,900);
    await act(async()=>{top=0;list.dispatchEvent(new Event('scroll'));});
    height=1200;
    await act(async()=>socket.event({...source,sentence_id:'next',event_id:'next',event_seq:31}));await paint();
    assert.equal(scrolls,1);assert.equal(top,0);
    await click('回到最新');await paint();assert.equal(top,1000);
    await view.render(null);assert.equal(frames.size,0);assert.equal(resize.size,0);
  } finally {window.requestAnimationFrame=originalRAF;window.cancelAnimationFrame=originalCancel;globalThis.ResizeObserver=originalObserver;}
});

test("incremental subtitle DOM separates reversible source and mutable Chinese without reopening capture", async () => {
  const view = await mount(h(SessionView, { session: { ...lesson, mode: "real" }, preferences,
    onActivity() {}, refresh() {}, back() {}, notify() {}, openSession() {}, deleted() {} }));
  const socket = Socket.instances.at(-1)!;
  await act(async () => socket.open());
  const base = { session_id: "lesson", stream_id: "s", sentence_id: "1", source_revision: 1,
    translation_revision: 1, event_seq: 0, start_ms: 0, end_ms: 1000, mode: "real" };
  await act(async () => socket.event({ ...base, type: "transcript.partial", event_id: "p",
    text: "오늘은 RAG 배웁니다.", stable_preview: "오늘은 RAG ", unstable_tail: "배웁니다." }));
  assert.equal(view.container.querySelector(".stable-source-preview")?.textContent, "오늘은 RAG ");
  assert.equal(view.container.querySelector(".unstable-source-tail")?.textContent, "배웁니다.");
  await act(async () => socket.event({ ...base, type: "translation.partial", event_id: "t",
    translation: "今天学习 RAG", preview_source_text: "오늘은 RAG", preview_request_id: 1, preview_complete: true }));
  assert.match(view.container.textContent!, /临时翻译预览/);
  await act(async () => socket.event({ ...base, type: "transcript.final", event_id: "f", event_seq: 1,
    source_revision: 2, text: "오늘은 RAG 배웁니다." }));
  assert.equal(view.container.querySelector(".unstable-source-tail"), null);
  assert.equal(Socket.instances.length, 1);
  assert.equal(socket.sent.filter(x => x.type === "start").length, 0);
});

test("App ignores stale session reads and restores hash when back navigation is blocked by capture", async () => {
  let release: (data: Response) => void = () => {};
  const normal = globalThis.fetch;
  globalThis.fetch = async (url, init) =>
    String(url).endsWith("/sessions/other")
      ? new Promise<Response>((r) => {
          release = r;
        })
      : normal(url, init);
  const view = await mount(h(App));
  const rows =
    view.container.querySelectorAll<HTMLButtonElement>(".session-row");
  await act(async () => rows[1].click());
  await click("资料库");
  await act(async () => release(json(other)));
  assert.ok(view.container.querySelector(".library"));
  assert.ok(!view.container.querySelector(".session-view"));
  await act(async () => {
    dom.location.hash = "session/lesson";
    dom.dispatchEvent(new dom.Event("hashchange"));
  });
  const socket = Socket.instances.at(-1)!;
  await act(async () => socket.open());
  await click("开始模拟");
  await act(async () => {
    dom.location.hash = "settings";
    dom.dispatchEvent(new dom.Event("hashchange"));
  });
  assert.equal(dom.location.hash, "#session/lesson");
  assert.ok(view.container.querySelector(".session-view"));
  assert.equal(button("资料库").disabled, true);
});
