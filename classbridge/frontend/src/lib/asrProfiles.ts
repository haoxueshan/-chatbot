import { useEffect, useState } from "react";
import { request } from "./api";
import type { ASRProfile } from "./types";

export const profilesChanged = () => window.dispatchEvent(new Event("asr-profiles-changed"));
export function useASRProfiles() {
  const [profiles,setProfiles]=useState<ASRProfile[]>([]), [error,setError]=useState(""), [loading,setLoading]=useState(true);
  useEffect(()=>{
    let active=true,version=0;
    const load=async()=>{
      const current=++version;
      try {
        const result=await request<ASRProfile[]>("/asr/profiles");
        if(active && current===version){setProfiles(result);setError("");}
      } catch(e){if(active && current===version)setError(e instanceof Error?e.message:"模型列表加载失败");}
      finally{if(active && current===version)setLoading(false);}
    };
    void load();window.addEventListener("asr-profiles-changed",load);
    return ()=>{active=false;window.removeEventListener("asr-profiles-changed",load);};
  },[]);
  return {profiles,error,loading};
}
