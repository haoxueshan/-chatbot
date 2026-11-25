import { useEffect, useState } from "react";
import { request, post } from "../lib/api";
import { profilesChanged, useASRProfiles } from "../lib/asrProfiles";
import type { ASRProfile, ASRProviderInfo, ASRValidation } from "../lib/types";
import { Card } from "./ui/card";
import { Button } from "./ui/button";
import { Input, Textarea } from "./ui/input";
import { Dialog } from "./ui/dialog";
import { Badge } from "./ui/badge";

export function ASRSelector({value,onChange,disabled=false,historical}: {
  value:string;onChange:(id:string)=>void;disabled?:boolean;historical?:string;
}) {
  const {profiles,error,loading}=useASRProfiles();
  const valid=profiles.filter(p=>p.enabled && p.validation.valid);
  return <label>语音识别模型
    <select aria-label="语音识别模型" value={value} disabled={disabled || loading} onChange={e=>onChange(e.target.value)}>
      <option value="" disabled>请选择模型</option>
      {value && !valid.some(p=>p.id===value) && <option value={value} disabled>{historical || "已选模型"}（不可用或已删除）</option>}
      {valid.map(p=><option key={p.id} value={p.id}>{p.display_name} · {p.provider} / {p.model_id}{p.is_default?" · 默认":""}</option>)}
    </select>
    {error && <small role="alert">{error}</small>}
    {!loading && !valid.length && <small role="status">暂无可用模型，请到偏好设置配置服务器密钥与模型。</small>}
  </label>;
}

type Draft=Pick<ASRProfile,"provider"|"model_id"|"display_name"|"language_hints"|"enabled"|"is_default"|"credential_ref"|"provider_options">;
export function ASRModels() {
  const {profiles,error,loading}=useASRProfiles();
  const [providers,setProviders]=useState<ASRProviderInfo[]>([]),[message,setMessage]=useState("");
  const [draft,setDraft]=useState<Draft|null>(null),[editing,setEditing]=useState<string|null>(null),[options,setOptions]=useState("{}");
  const [busy,setBusy]=useState(false);
  useEffect(()=>{let active=true;void request<ASRProviderInfo[]>("/asr/providers").then(x=>{if(active)setProviders(x);}).catch(e=>{if(active)setMessage(e.message);});return()=>{active=false;};},[]);
  const definition=providers.find(p=>p.id===draft?.provider);
  const perform=async(action:()=>Promise<unknown>)=>{
    setBusy(true);setMessage("");
    try {await action();profilesChanged();}
    catch(e){setMessage(e instanceof Error?e.message:"模型操作失败");}
    finally{setBusy(false);}
  };
  const chooseProvider=(provider:ASRProviderInfo)=>{
    setMessage("");
    setDraft({provider:provider.id,model_id:provider.default_model,display_name:provider.name,language_hints:null,
      enabled:provider.implemented,is_default:false,credential_ref:provider.credential_ref,provider_options:{}});setOptions("{}");
  };
  const check=(profile:ASRProfile,live=false)=>perform(async()=>{
    const result=await post<ASRValidation>(`/asr/profiles/${profile.id}/validate`,{live,confirm_paid:live});
    setMessage(result.message);
  });
  return <Card id="settings-asr" tabIndex={-1} className="settings-card asr-models">
    <div className="settings-title"><div><h2>语音识别模型管理</h2><p>密钥只在服务器配置。阿里云翻译与知识服务独立保留。</p></div></div>
    <Button disabled={busy || !providers.length} onClick={()=>{setEditing(null);chooseProvider(providers[0]);}}>新增模型配置</Button>
    {error && <p role="alert" className="error-box">{error}</p>}
    {message && <p role="status" className="info-box">{message}</p>}
    {loading && <p role="status" className="model-loading" aria-busy="true">正在加载模型配置…</p>}
    {!loading && !error && !profiles.length && <div className="empty-state compact"><h3>尚未添加识别模型</h3><p>新增模型配置后，即可在真实会话中选择。密钥保存在服务器。</p></div>}
    {profiles.map(p=><section key={p.id} className="asr-profile-row" aria-label={p.display_name}>
      <div className="asr-profile-heading"><strong>{p.display_name}</strong>{p.is_default && <Badge>默认</Badge>}<Badge className={p.enabled && p.validation.valid ? "green" : "amber"}>{!p.enabled ? "已停用" : p.validation.valid ? "本地配置有效" : "待配置"}</Badge></div>
      <p><code>{p.provider} / {p.model_id}</code> · {p.language_hints===null?"跟随课堂语言提示":p.language_hints.join(" / ") || "自动识别"}</p>
      <p className="tiny muted">{p.enabled?"已启用":"已停用"} · {p.validation.message}</p>
      <div className="asr-actions">
        <Button variant="secondary" disabled={busy} onClick={()=>{setMessage("");setEditing(p.id);setDraft({provider:p.provider,model_id:p.model_id,display_name:p.display_name,language_hints:p.language_hints,enabled:p.enabled,is_default:p.is_default,credential_ref:p.credential_ref,provider_options:p.provider_options});setOptions(JSON.stringify(p.provider_options,null,2));}}>编辑</Button>
        <Button variant="secondary" disabled={busy || !p.validation.valid || p.is_default} onClick={()=>void perform(()=>request(`/asr/profiles/${p.id}`,{method:"PATCH",body:JSON.stringify({is_default:true})}))}>设为默认</Button>
        <Button variant="secondary" disabled={busy} onClick={()=>void perform(()=>request(`/asr/profiles/${p.id}`,{method:"PATCH",body:JSON.stringify({enabled:!p.enabled,...(p.enabled?{is_default:false}:{})})}))}>{p.enabled?"停用":"启用"}</Button>
        <Button variant="secondary" disabled={busy} onClick={()=>void check(p)}>配置检查</Button>
        <Button variant="secondary" disabled={busy || !p.validation.valid} onClick={()=>{if(confirm("真实连通测试将发送 200ms 静音，可能产生费用，不验证课堂准确率。确定继续？"))void check(p,true);}}>真实连通测试（可能计费）</Button>
        <Button variant="destructive" disabled={busy} onClick={()=>{if(confirm(`删除模型配置“${p.display_name}”？历史字幕和录音仍保留。`))void perform(()=>request(`/asr/profiles/${p.id}`,{method:"DELETE"}));}}>删除</Button>
      </div>
    </section>)}
    <p className="tiny muted">{providers.filter(p=>!p.implemented).map(p=>`${p.name}：尚未接入`).join("；")}</p>
    {draft && <Dialog title={editing?"编辑 ASR 模型":"新增 ASR 模型"} description="配置模型参数，不输入 API Key" busy={busy} close={()=>setDraft(null)}>
      <form className="asr-profile-form" onSubmit={e=>{e.preventDefault();void perform(async()=>{
        const parsed=JSON.parse(options);
        if(!parsed || Array.isArray(parsed) || typeof parsed!=="object")throw new Error("供应商参数必须为 JSON 对象");
        await request(editing?`/asr/profiles/${editing}`:"/asr/profiles",{method:editing?"PATCH":"POST",body:JSON.stringify({...draft,provider_options:parsed})});
        setDraft(null);setMessage("模型配置已保存");
      });}}>
        <h2>{editing?"编辑语音识别模型":"新增语音识别模型"}</h2>
        <fieldset disabled={busy}>
          <label>供应商<select aria-label="ASR 供应商" value={draft.provider} onChange={e=>chooseProvider(providers.find(p=>p.id===e.target.value)!)}>{providers.map(p=><option key={p.id} value={p.id}>{p.name}{p.implemented?"":" · 尚未接入"}</option>)}</select></label>
          <label>显示名称<Input aria-label="模型显示名称" required maxLength={100} value={draft.display_name} onChange={e=>setDraft({...draft,display_name:e.target.value})}/></label>
          <label>API 模型 ID<Input aria-label="API 模型 ID" required maxLength={120} value={draft.model_id} onChange={e=>setDraft({...draft,model_id:e.target.value})}/></label>
          <label>语言提示<select aria-label="模型语言提示" value={draft.language_hints===null?"inherit":draft.language_hints.join(",")} onChange={e=>setDraft({...draft,language_hints:e.target.value==="inherit"?null:e.target.value.split(",").filter(Boolean)})}>
            <option value="inherit">跟随课堂偏好</option><option value="">自动识别</option><option value="ko,en">韩语 / 英语</option><option value="ko">韩语</option><option value="en">英语</option>
          </select></label>
          <p>服务器密钥引用：<code>{draft.credential_ref}</code>（网页不接收密钥正文）</p>
          <label>供应商参数（JSON）<Textarea aria-label="供应商参数" rows={5} value={options} onChange={e=>setOptions(e.target.value)}/></label>
          <small>允许字段：{Object.keys(definition?.options_schema.properties || {}).join("、") || "无"}。不允许设置 URL 或认证头。</small>
          <label className="checkbox-label"><input type="checkbox" checked={draft.enabled} disabled={!definition?.implemented} onChange={e=>setDraft({...draft,enabled:e.target.checked,is_default:e.target.checked?draft.is_default:false})}/>启用</label>
          <label className="checkbox-label"><input type="checkbox" checked={draft.is_default} disabled={!draft.enabled || !definition?.implemented} onChange={e=>setDraft({...draft,is_default:e.target.checked})}/>默认模型</label>
          {message && <p role="alert">{message}</p>}
          <Button type="submit" disabled={busy}>{busy?"保存中…":"保存模型"}</Button>
          <Button variant="secondary" type="button" disabled={busy} onClick={()=>setDraft(null)}>取消</Button>
        </fieldset>
      </form>
    </Dialog>}
  </Card>;
}
