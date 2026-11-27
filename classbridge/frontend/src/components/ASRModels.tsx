import { useEffect, useState } from "react";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n";
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
  const {t}=useI18n();
  const {profiles,error,loading}=useASRProfiles();
  const valid=profiles.filter(p=>p.enabled && p.validation.valid);
  return <label>{t("asrModels.label")}
    <select aria-label={t("asrModels.label")} value={value} disabled={disabled || loading} onChange={e=>onChange(e.target.value)}>
      <option value="" disabled>{t("asrModels.choose")}</option>
      {value && !valid.some(p=>p.id===value) && <option value={value} disabled>{historical || t("asrModels.selected")} {t("asrModels.unavailable")}</option>}
      {valid.map(p=><option key={p.id} value={p.id}>{p.display_name} · {p.provider} / {p.model_id}{p.is_default?` · ${t("asrModels.default")}`:""}</option>)}
    </select>
    {error && <small role="alert">{t("asrModels.failed")}</small>}
    {!loading && !valid.length && <small role="status">{t("asrModels.noAvailable")}</small>}
  </label>;
}

type Draft=Pick<ASRProfile,"provider"|"model_id"|"display_name"|"language_hints"|"enabled"|"is_default"|"credential_ref"|"provider_options">;
export function ASRModels() {
  const {t}=useI18n();
  const {profiles,error,loading}=useASRProfiles();
  const [providers,setProviders]=useState<ASRProviderInfo[]>([]),[message,setMessage]=useState<TranslationKey | "">("");
  const [draft,setDraft]=useState<Draft|null>(null),[editing,setEditing]=useState<string|null>(null),[options,setOptions]=useState("{}");
  const [busy,setBusy]=useState(false);
  useEffect(()=>{let active=true;void request<ASRProviderInfo[]>("/asr/providers").then(x=>{if(active)setProviders(x);}).catch(()=>{if(active)setMessage("asrModels.failed");});return()=>{active=false;};},[]);
  const definition=providers.find(p=>p.id===draft?.provider);
  const perform=async(action:()=>Promise<unknown>)=>{
    setBusy(true);setMessage("");
    try {await action();profilesChanged();}
    catch{setMessage("asrModels.failed");}
    finally{setBusy(false);}
  };
  const chooseProvider=(provider:ASRProviderInfo)=>{
    setMessage("");
    setDraft({provider:provider.id,model_id:provider.default_model,display_name:provider.name,language_hints:null,
      enabled:provider.implemented,is_default:false,credential_ref:provider.credential_ref,provider_options:{}});setOptions("{}");
  };
  const check=(profile:ASRProfile,live=false)=>perform(async()=>{
    const result=await post<ASRValidation>(`/asr/profiles/${profile.id}/validate`,{live,confirm_paid:live});
    setMessage(result.valid ? (live ? "asrModels.testPassed" : "asrModels.localPassed") : "asrModels.testFailed");
  });
  return <Card id="settings-asr" tabIndex={-1} className="settings-card asr-models">
    <div className="settings-title"><div><h2>{t("asrModels.title")}</h2><p>{t("asrModels.description")}</p></div></div>
    <Button disabled={busy || !providers.length} onClick={()=>{setEditing(null);chooseProvider(providers[0]);}}>{t("asrModels.add")}</Button>
    {error && <p role="alert" className="error-box">{t("asrModels.failed")}</p>}
    {message && <p role="status" className="info-box">{t(message)}</p>}
    {loading && <p role="status" className="model-loading" aria-busy="true">{t("asrModels.loading")}</p>}
    {!loading && !error && !profiles.length && <div className="empty-state compact"><h3>{t("asrModels.empty")}</h3><p>{t("asrModels.emptyDescription")}</p></div>}
    {profiles.map(p=><section key={p.id} className="asr-profile-row" aria-label={p.display_name}>
      <div className="asr-profile-heading"><strong>{p.display_name}</strong>{p.is_default && <Badge>{t("asrModels.default")}</Badge>}<Badge className={p.enabled && p.validation.valid ? "green" : "amber"}>{t(!p.enabled ? "asrModels.disabled" : p.validation.valid ? "asrModels.valid" : "asrModels.pending")}</Badge></div>
      <p><code>{p.provider} / {p.model_id}</code> · {p.language_hints===null?t("asrModels.inherit"):p.language_hints.join(" / ") || t("asrModels.auto")}</p>
      <p className="tiny muted">{t(p.enabled?"asrModels.enabled":"asrModels.disabled")} · {t(p.validation.valid?"asrModels.valid":"asrModels.pending")}</p>
      <div className="asr-actions">
        <Button variant="secondary" disabled={busy} onClick={()=>{setMessage("");setEditing(p.id);setDraft({provider:p.provider,model_id:p.model_id,display_name:p.display_name,language_hints:p.language_hints,enabled:p.enabled,is_default:p.is_default,credential_ref:p.credential_ref,provider_options:p.provider_options});setOptions(JSON.stringify(p.provider_options,null,2));}}>{t("asrModels.edit")}</Button>
        <Button variant="secondary" disabled={busy || !p.validation.valid || p.is_default} onClick={()=>void perform(()=>request(`/asr/profiles/${p.id}`,{method:"PATCH",body:JSON.stringify({is_default:true})}))}>{t("asrModels.makeDefault")}</Button>
        <Button variant="secondary" disabled={busy} onClick={()=>void perform(()=>request(`/asr/profiles/${p.id}`,{method:"PATCH",body:JSON.stringify({enabled:!p.enabled,...(p.enabled?{is_default:false}:{})})}))}>{t(p.enabled?"asrModels.disable":"asrModels.enable")}</Button>
        <Button variant="secondary" disabled={busy} onClick={()=>void check(p)}>{t("asrModels.check")}</Button>
        <Button variant="secondary" disabled={busy || !p.validation.valid} onClick={()=>{if(confirm(t("asrModels.paidConfirm")))void check(p,true);}}>{t("asrModels.live")}</Button>
        <Button variant="destructive" disabled={busy} onClick={()=>{if(confirm(t("asrModels.deleteConfirm",{name:p.display_name})))void perform(()=>request(`/asr/profiles/${p.id}`,{method:"DELETE"}));}}>{t("asrModels.delete")}</Button>
      </div>
    </section>)}
    <p className="tiny muted">{providers.filter(p=>!p.implemented).map(p=>t("asrModels.notIntegrated",{name:p.name})).join("; ")}</p>
    {draft && <Dialog title={t(editing?"asrModels.editTitle":"asrModels.addTitle")} description={t("asrModels.dialogDescription")} busy={busy} close={()=>setDraft(null)}>
      <form className="asr-profile-form" onSubmit={e=>{e.preventDefault();void perform(async()=>{
        const parsed=JSON.parse(options);
        if(!parsed || Array.isArray(parsed) || typeof parsed!=="object"){setMessage("asrModels.jsonError");return;}
        await request(editing?`/asr/profiles/${editing}`:"/asr/profiles",{method:editing?"PATCH":"POST",body:JSON.stringify({...draft,provider_options:parsed})});
        setDraft(null);setMessage("asrModels.saved");
      });}}>
        <h2>{t(editing?"asrModels.editTitle":"asrModels.addTitle")}</h2>
        <fieldset disabled={busy}>
          <label>{t("asrModels.provider")}<select aria-label={t("asrModels.providerAria")} value={draft.provider} onChange={e=>chooseProvider(providers.find(p=>p.id===e.target.value)!)}>{providers.map(p=><option key={p.id} value={p.id}>{p.name}{p.implemented?"":` · ${t("asrModels.notImplemented")}`}</option>)}</select></label>
          <label>{t("asrModels.name")}<Input aria-label={t("asrModels.nameAria")} required maxLength={100} value={draft.display_name} onChange={e=>setDraft({...draft,display_name:e.target.value})}/></label>
          <label>{t("asrModels.modelId")}<Input aria-label={t("asrModels.modelId")} required maxLength={120} value={draft.model_id} onChange={e=>setDraft({...draft,model_id:e.target.value})}/></label>
          <label>{t("asrModels.hints")}<select aria-label={t("asrModels.hints")} value={draft.language_hints===null?"inherit":draft.language_hints.join(",")} onChange={e=>setDraft({...draft,language_hints:e.target.value==="inherit"?null:e.target.value.split(",").filter(Boolean)})}>
            <option value="inherit">{t("asrModels.inherit")}</option><option value="">{t("asrModels.auto")}</option><option value="ko,en">{t("asrModels.koEn")}</option><option value="ko">{t("asrModels.ko")}</option><option value="en">{t("asrModels.en")}</option>
          </select></label>
          <p>{t("asrModels.credentials")}: <code>{draft.credential_ref}</code> ({t("asrModels.noKeys")})</p>
          <label>{t("asrModels.options")}<Textarea aria-label={t("asrModels.options")} rows={5} value={options} onChange={e=>setOptions(e.target.value)}/></label>
          <small>{t("asrModels.allowed",{fields:Object.keys(definition?.options_schema.properties || {}).join(", ") || t("asrModels.none")})}</small>
          <label className="checkbox-label"><input type="checkbox" checked={draft.enabled} disabled={!definition?.implemented} onChange={e=>setDraft({...draft,enabled:e.target.checked,is_default:e.target.checked?draft.is_default:false})}/>{t("asrModels.enable")}</label>
          <label className="checkbox-label"><input type="checkbox" checked={draft.is_default} disabled={!draft.enabled || !definition?.implemented} onChange={e=>setDraft({...draft,is_default:e.target.checked})}/>{t("asrModels.defaultModel")}</label>
          {message && <p role="alert">{t(message)}</p>}
          <Button type="submit" disabled={busy}>{t(busy?"asrModels.saving":"asrModels.save")}</Button>
          <Button variant="secondary" type="button" disabled={busy} onClick={()=>setDraft(null)}>{t("asrModels.cancel")}</Button>
        </fieldset>
      </form>
    </Dialog>}
  </Card>;
}
