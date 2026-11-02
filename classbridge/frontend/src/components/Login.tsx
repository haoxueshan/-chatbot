import { useState, type FormEvent } from "react";
import {
  ArrowRight,
  AudioLines,
  BookOpen,
  Languages,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { post } from "../lib/api";
import type { User } from "../lib/types";
export function Login({ done }: { done: (u: User) => void }) {
  const [username, setUsername] = useState("admin"),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      done(await post<User>("/auth/login", { username, password }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="login">
      <section className="login-story">
        <div className="brand light">
          <span className="brand-icon">
            <AudioLines />
          </span>
          <span>
            ClassBridge<small>语音理解工作台</small>
          </span>
        </div>
        <div className="login-main">
          <span className="eyebrow light">
            <span />
            让理解，跨越语言
          </span>
          <h1>
            专注此刻。
            <br />
            每一句，都听懂。
          </h1>
          <p>
            让韩语、英语课堂自然流入你的中文笔记。
            <br />
            听见原文，理解知识，带着证据继续探索。
          </p>
          <div className="sample-caption">
            <div>
              <span className="tag">产品示意 · 非实时字幕</span>
              <Languages size={18} />
            </div>
            <p>Learning begins with asking good questions.</p>
            <strong>学习，始于提出好问题。</strong>
            <span className="sample-line" />
          </div>
          <div className="feature-row">
            <span>
              <AudioLines size={17} />
              双语字幕
            </span>
            <span>
              <BookOpen size={17} />
              知识沉淀
            </span>
            <span>
              <Sparkles size={17} />
              循证问答
            </span>
          </div>
        </div>
        <span className="login-foot">从声音到理解，从课堂到知识。</span>
      </section>
      <section className="login-form">
        <div className="login-box">
          <div className="lock-mark">
            <LockKeyhole size={25} />
          </div>
          <span className="eyebrow">你的私人学习空间</span>
          <h2>欢迎回来</h2>
          <p className="muted">登录 ClassBridge，继续你的理解之旅。</p>
          <form onSubmit={submit}>
            <label>
              用户名
              <input
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label>
              密码
              <input
                autoComplete="current-password"
                required
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <div role="alert" className="error-box">
                {error}
              </div>
            )}
            <button className="primary full" disabled={busy}>
              {busy ? "正在登录…" : "进入工作台"}
              <ArrowRight size={17} />
            </button>
          </form>
          <div className="login-note">
            <ShieldCheck size={17} />
            <p>
              仅限已创建的私人账户。管理员需在服务器初始化；公开注册已关闭。
            </p>
          </div>
          <p className="tiny muted">
            首次体验？登录后创建「模拟演示」会话即可，演示不调用付费 API。
          </p>
        </div>
      </section>
    </main>
  );
}
