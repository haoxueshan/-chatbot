import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AudioCapture, type AudioInputOptions, type AudioQuality, type AppliedAudioSettings } from "./audio";
import { connectLive } from "./liveConnection";
import { isCurrentCaptureEvent } from "./captureEvents";
import { applyEvent, initialTranscript, orderedSegments } from "./events";
import type { BridgeEvent, Session } from "./types";
import type { CaptureHealth } from "./captureHealth";
import type { ASRLanguageMode } from "./asrLanguages";

export function useLive(session: Session, onSaved: () => void, audioOptions: AudioInputOptions = {}) {
  const [transcript, setTranscript] = useState(() =>
    initialTranscript(session.id, session.segments),
  );
  const [connection, setConnection] = useState("连接中");
  const [active, setActive] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [settling, setSettling] = useState(false);
  const [level, setLevel] = useState(0);
  const [inputPeak, setInputPeak] = useState(0);
  const [audioQuality,setAudioQuality]=useState<AudioQuality>();
  const [appliedAudio,setAppliedAudio]=useState<AppliedAudioSettings>();
  const [asrAcousticProfile, setAsrAcousticProfile] = useState<"far" | "near">();
  const [queue, setQueue] = useState(0);
  const [elapsed, setElapsed] = useState(
    session.captured_ms ?? session.duration_ms ?? 0,
  );
  const [notice, setNotice] = useState("");
  const [health, setHealth] = useState<CaptureHealth>();
  const [asrLanguageMode, setAsrLanguageMode] = useState<ASRLanguageMode>();
  const [asrEnhancement, setAsrEnhancement] =
    useState<BridgeEvent["asr_enhancement"]>();
  const [gaps, setGaps] = useState<BridgeEvent[]>(session.gaps || []);
  const [latency, setLatency] = useState<NonNullable<BridgeEvent["latency"]>>(
    {},
  );
  const [reconnect, setReconnect] = useState(0);
  const ws = useRef<WebSocket | null>(null),
    audio = useRef<AudioCapture | null>(null),
    activeRef = useRef(false),
    sequence = useRef(session.event_seq || 0),
    generation = useRef(0),
    startSent = useRef(false),
    requestSequence = useRef(0),
    captureRequest = useRef<string | null>(null),
    activeStream = useRef<string | null>(null),
    readyTimer = useRef<ReturnType<typeof setTimeout>>(),
    started = useRef(0),
    total = useRef(session.captured_ms ?? session.duration_ms ?? 0),
    saved = useRef(onSaved),
    wake = useRef<{ release: () => Promise<void> } | null>(null),
    lastGap = useRef<string | null>(null);
  saved.current = onSaved;
  const stop = useCallback((reason?: string) => {
    generation.current++;
    setHealth(undefined);
    clearTimeout(readyTimer.current);
    setPreparing(false);
    audio.current?.stop();
    audio.current = null;
    activeRef.current = false;
    setActive(false);
    setLevel(0);
    setInputPeak(0);
    setAudioQuality(undefined);
    total.current += started.current ? Date.now() - started.current : 0;
    started.current = 0;
    setElapsed(total.current);
    if (ws.current?.readyState === WebSocket.OPEN && startSent.current) {
      if (reason)
        ws.current.send(
          JSON.stringify({ type: "capture.gap", reason, duration_ms: null }),
        );
      setSettling(true);
      ws.current.send(JSON.stringify({ type: "stop" }));
    } else if (!startSent.current) {
      captureRequest.current = null;
      activeStream.current = null;
    }
    startSent.current = false;
    if (reason) setNotice(reason);
    void wake.current?.release();
    wake.current = null;
  }, []);
  useEffect(() => {
    if (!activeRef.current) {
      total.current = session.captured_ms ?? session.duration_ms;
      setElapsed(total.current);
    }
    for (const segment of session.segments || []) {
      if (segment.latency && Object.keys(segment.latency).length)
        setLatency(segment.latency);
      setTranscript((old) => {
        const event = {
          ...segment,
          session_id: session.id,
          event_id: `snapshot:${segment.sentence_id}:${segment.source_revision}:${segment.translation_revision}:${session.event_seq || 0}`,
          event_seq: 0,
          type: "segment.updated",
          translation: segment.translation || undefined,
        };
        return applyEvent(old, event);
      });
    }
  }, [session.captured_ms, session.duration_ms, session.segments]);
  useEffect(() => {
    let connectionNotice = "";
    const transport = connectLive({
      url: () =>
        `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/sessions/${session.id}?after_seq=${sequence.current}`,
      onSocket: (socket) => {
        ws.current = socket;
      },
      onState: (state) => {
        setConnection(state);
        if (state === "已连接" && lastGap.current && ws.current) {
          ws.current.send(
            JSON.stringify({
              type: "capture.gap",
              reason: lastGap.current,
              duration_ms: 0,
            }),
          );
          lastGap.current = null;
        }
      },
      onNotice: (message) => {
        const previous = connectionNotice;
        connectionNotice = message;
        setNotice((old) => (!message && old !== previous ? old : message));
      },
      onMessage: (data) => {
        let e: BridgeEvent;
        try {
          e = JSON.parse(data);
        } catch {
          setNotice("收到无法识别的服务端消息");
          return;
        }
        if (e.session_id && e.session_id !== session.id) return;
        if (e.type === "connection.pong") return;
        if (e.type === "capture.health") {
          if (
            activeRef.current &&
            e.stream_id === activeStream.current &&
            e.diagnostics
          )
            setHealth(e.diagnostics);
          return;
        }
        sequence.current = Math.max(sequence.current, e.event_seq || 0);
        setTranscript((s) => applyEvent(s, e));
        const currentCapture = isCurrentCaptureEvent(
          e,
          captureRequest.current,
          activeStream.current,
          requestSequence.current,
        );
        if (e.type === "processing.failed") {
          if (e.task_kind || currentCapture || !captureRequest.current)
            setNotice(e.message || "处理失败，请检查设置或重试");
          if (activeRef.current && currentCapture) {
            // A rejected start never created an upstream capture to drain.
            if (!e.event_seq) startSent.current = false;
            stop();
            if (!e.event_seq) setSettling(false);
          }
        }
        if (e.type === "capture.gap")
          setGaps((items) =>
            items.some((x) => x.event_id === e.event_id)
              ? items
              : [...items, e],
          );
        if (e.latency) setLatency(e.latency);
        if (typeof e.queue_size === "number") setQueue(e.queue_size);
        if (e.type === "session.state") {
          const state = e.state || e.status;
          if (
            state === "recording" &&
            e.ready &&
            currentCapture &&
            activeRef.current
          ) {
            activeStream.current = e.stream_id || null;
            if (!started.current) {
              total.current = e.captured_ms ?? total.current;
              setElapsed(total.current);
              started.current = Date.now();
              setAsrLanguageMode(e.asr_language_mode);
              setAsrAcousticProfile(e.asr_acoustic_profile);
              setAsrEnhancement(e.asr_enhancement);
              clearTimeout(readyTimer.current);
              setPreparing(false);
              audio.current?.begin();
            }
          }
          if (e.cleared) {
            setGaps([]);
            setLatency({});
            total.current = 0;
            setElapsed(0);
          }
          if (currentCapture || (!captureRequest.current && e.recovered)) {
            if (state === "processing") setSettling(true);
            if (
              ["stopped", "completed", "idle", "failed"].includes(state || "")
            )
              setSettling(false);
          }
          if (
            ["stopped", "completed", "idle", "failed"].includes(state || "") &&
            currentCapture
          ) {
            generation.current++;
            captureRequest.current = null;
            activeStream.current = null;
            setHealth(undefined);
            clearTimeout(readyTimer.current);
            setPreparing(false);
            startSent.current = false;
            audio.current?.stop();
            audio.current = null;
            activeRef.current = false;
            setActive(false);
            setLevel(0);
            total.current += started.current ? Date.now() - started.current : 0;
            started.current = 0;
            void wake.current?.release();
            wake.current = null;
          }
          if (
            ["stopped", "completed", "idle", "failed"].includes(state || "") &&
            typeof e.captured_ms === "number" &&
            currentCapture
          ) {
            total.current = e.captured_ms;
            setElapsed(e.captured_ms);
          }
          saved.current();
        }
      },
      onLost: () => {
        setSettling(false);
        setQueue(0);
        if (activeRef.current) {
          lastGap.current =
            "网络连接中断，此时段音频未恢复；重新连接后需手动开始";
          stop();
          setNotice(lastGap.current);
        }
        captureRequest.current = null;
        activeStream.current = null;
      },
    });
    const resume = () => {
      if (!document.hidden) transport.resume();
    };
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("online", resume);
    return () => {
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("online", resume);
      transport.dispose();
      generation.current++;
      captureRequest.current = null;
      activeStream.current = null;
      clearTimeout(readyTimer.current);
      startSent.current = false;
      audio.current?.stop();
      audio.current = null;
      activeRef.current = false;
      void wake.current?.release();
      wake.current = null;
    };
  }, [session.id, reconnect, stop]);
  useEffect(() => {
    const timer = setInterval(() => {
      if (activeRef.current) {
        const duration =
          total.current + (started.current ? Date.now() - started.current : 0);
        setElapsed(duration);
        setQueue(Math.ceil((ws.current?.bufferedAmount || 0) / 640));
        if (duration >= 105 * 60 * 1000)
          stop("已达到单次录音 105 分钟的应用限制。此限制不是账户消费上限。");
      }
    }, 250);
    return () => clearInterval(timer);
  }, [stop]);
  useEffect(() => {
    const hidden = () => {
      if (document.hidden && activeRef.current && session.mode === "real")
        stop(
          "页面进入后台，已停止麦克风并记录采集缺口。请保持页面在前台；不保证锁屏或后台录音。",
        );
    };
    const before = (event: BeforeUnloadEvent) => {
      if (activeRef.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("beforeunload", before);
    return () => {
      document.removeEventListener("visibilitychange", hidden);
      window.removeEventListener("beforeunload", before);
    };
  }, [session.mode, stop]);
  const start = async () => {
    if (ws.current?.readyState !== WebSocket.OPEN) {
      setNotice("尚未连接到服务器");
      return;
    }
    if (activeRef.current || settling) return;
    setNotice("");
    setHealth(undefined);
    setAsrLanguageMode(undefined);
    setAudioQuality(undefined);setAppliedAudio(undefined);
    setAsrAcousticProfile(undefined);
    setAsrEnhancement(undefined);
    activeRef.current = true;
    setActive(true);
    setPreparing(session.mode === "real");
    const requestGeneration = ++generation.current;
    captureRequest.current = `${requestGeneration}:${Date.now()}`;
    activeStream.current = null;
    const socket = ws.current;
    requestSequence.current = sequence.current;
    try {
      if (session.mode === "real") {
        const capture = new AudioCapture();
        audio.current = capture;
        await capture.start(
          (frame) => {
            if (requestGeneration !== generation.current) return;
            if (!startSent.current || !started.current) return;
            if (socket !== ws.current || socket.readyState !== WebSocket.OPEN) {
              stop("连接断开，已停止采集");
              return;
            }
            if (socket.bufferedAmount > 64000) {
              stop("音频发送积压超过 2 秒，已停止采集，防止继续积累延迟");
              return;
            }
            socket.send(frame);
          },
          (rms, quality) => { setLevel(rms); setInputPeak(quality?.input_peak ?? 0); setAudioQuality(quality); },
          stop,
          true,
          {...audioOptions,onSettings:setAppliedAudio},
        );
      }
      if (requestGeneration !== generation.current || !activeRef.current)
        return;
      if (socket !== ws.current || socket.readyState !== WebSocket.OPEN) {
        stop("连接断开，请重新开始");
        return;
      }
      if (session.mode === "demo") started.current = Date.now();
      startSent.current = true;
      socket.send(
        JSON.stringify({ type: "start", request_id: captureRequest.current }),
      );
      if (session.mode === "real")
        readyTimer.current = setTimeout(() => {
          if (requestGeneration === generation.current && !started.current)
            stop("识别服务准备超时，已释放麦克风，请检查服务端后重试。");
        }, 40_000);
      if ("wakeLock" in navigator && activeRef.current) {
        try {
          const lock = await (
            navigator as Navigator & {
              wakeLock: {
                request: (
                  type: "screen",
                ) => Promise<{ release: () => Promise<void> }>;
              };
            }
          ).wakeLock.request("screen");
          if (requestGeneration !== generation.current) await lock.release();
          else wake.current = lock;
        } catch {
          /* availability is not guaranteed */
        }
      }
    } catch (error) {
      if (requestGeneration === generation.current) {
        stop();
        setNotice(error instanceof Error ? error.message : "无法开始采集");
      }
    }
  };
  const segments = useMemo(() => orderedSegments(transcript), [transcript]);
  return {
    segments,
    connection,
    active,
    preparing,
    settling,
    level,
    inputPeak,
    audioQuality,
    appliedAudio,
    asrAcousticProfile,
    queue,
    elapsed,
    notice,
    health,
    asrLanguageMode,
    asrEnhancement,
    setNotice,
    gaps,
    latency,
    start,
    stop,
    retry: () => setReconnect((x) => x + 1),
    clear: () => {
      setTranscript(initialTranscript(session.id));
      setGaps([]);
      setLatency({});
      total.current = 0;
      setElapsed(0);
    },
  };
}
