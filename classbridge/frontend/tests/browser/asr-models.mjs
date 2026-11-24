// Browser-only fixtures: no user data, microphone or model API connections.
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const origin=process.env.AUDIT_URL || 'http://127.0.0.1:5177';
const output='../docs/screenshots/asr-models';
await mkdir(output,{recursive:true});
const definitions=[
  {id:'aliyun',name:'阿里云 Qwen',default_model:'qwen-audio-3.1-asr-flash-streaming',credential_ref:'DASHSCOPE_API_KEY',implemented:true,options_schema:{properties:{context:{},vad_model:{}}}},
  {id:'soniox',name:'Soniox',default_model:'stt-rt-v6',credential_ref:'SONIOX_API_KEY',implemented:true,options_schema:{properties:{context:{},terms:{},max_endpoint_delay_ms:{}}}},
  {id:'elevenlabs',name:'ElevenLabs Scribe v3 Live',default_model:'scribe-v3-live',credential_ref:'ELEVENLABS_API_KEY',implemented:false,options_schema:{properties:{}}},
  {id:'deepgram',name:'Deepgram Nova-3',default_model:'nova-3',credential_ref:'DEEPGRAM_API_KEY',implemented:false,options_schema:{properties:{}}},
];
let profiles=[{id:'mock-aliyun',provider:'aliyun',model_id:definitions[0].default_model,display_name:'Mock · 原默认 Qwen',language_hints:null,enabled:true,is_default:true,credential_ref:'DASHSCOPE_API_KEY',provider_options:{},validation:{valid:true,message:'Mock 配置检查，无真实模型连接'}}];
const preferences={theme:'light',subtitle_size:24,show_original:true,retain_audio:false,audio_retention_days:7,terms:[],target_language:'zh-CN',asr_language_mode:'auto',models:{translation:'qwen-mt-flash'},api_key_configured:false};
const browser=await chromium.launch({headless:true});
const context=await browser.newContext();const calls=[];const errors=[];
await context.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.origin!==origin)return route.abort();
  if(!url.pathname.startsWith('/api/'))return route.continue();
  const method=route.request().method(),path=url.pathname,body=route.request().postDataJSON();
  calls.push({path,method,body});let data=[];
  if(path.endsWith('/auth/me'))data={id:'mock-user',username:'Mock 验收'};
  else if(path.endsWith('/settings'))data=preferences;
  else if(path.endsWith('/providers'))data=definitions;
  else if(path.endsWith('/validate'))data={valid:true,message:'Mock 本地检查完成',paid_request:false};
  else if(path.includes('/asr/profiles')){
    if(method==='POST')profiles.push({...body,id:'mock-soniox',validation:{valid:true,message:'Mock 配置有效；未联网'}});
    if(method==='PATCH')profiles=profiles.map(p=>p.id===path.split('/').at(-1)?{...p,...body}:p);
    if(method==='DELETE')profiles=profiles.filter(p=>p.id!==path.split('/').at(-1));
    data=method==='GET'?profiles:profiles.at(-1) || {ok:true};
  }
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
});
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
try {
  await page.setViewportSize({width:1440,height:900});
  await page.goto(`${origin}/#settings`);
  await page.getByRole('heading',{name:'语音识别模型管理'}).waitFor();
  await page.getByRole('button',{name:'新增模型配置'}).click();
  await page.getByLabel('ASR 供应商').selectOption('soniox');
  await page.getByLabel('模型显示名称').fill('Mock · 韩英课堂 Soniox');
  await page.getByLabel('模型语言提示').selectOption('ko,en');
  await page.getByLabel('供应商参数').fill('{"terms":["인공지능","RAG"]}');
  await page.screenshot({path:`${output}/desktop-edit.png`});
  await page.getByRole('button',{name:'保存模型',exact:true}).click();
  await page.getByRole('region',{name:'Mock · 韩英课堂 Soniox'}).waitFor();
  assert.equal(profiles[1].model_id,'stt-rt-v6');
  const section=page.getByRole('region',{name:'Mock · 韩英课堂 Soniox'});
  await section.getByRole('button',{name:'配置检查',exact:true}).click();
  assert.ok(calls.every(c=>!c.body?.live));
  await page.locator('.asr-models').scrollIntoViewIfNeeded();
  await page.screenshot({path:`${output}/desktop-settings.png`});
  await page.setViewportSize({width:390,height:844});
  await page.locator('.asr-models').scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:`${output}/mobile-settings.png`});
  await section.getByRole('button',{name:'编辑',exact:true}).click();
  await page.getByLabel('模型显示名称').fill('Mock · 已编辑');
  assert.equal(await page.locator('[role=dialog]').evaluate(el=>el.scrollWidth>el.clientWidth+1),false);
  await page.screenshot({path:`${output}/mobile-edit.png`});
  await page.getByRole('button',{name:'保存模型',exact:true}).click();
  assert.equal(profiles[1].display_name,'Mock · 已编辑');
  await page.setViewportSize({width:1440,height:900});
  await page.goto(origin);
  await page.getByRole('button',{name:'新建会话',exact:true}).first().click();
  await page.getByText('真实课堂',{exact:true}).click();
  await page.getByLabel('语音识别模型').selectOption('mock-soniox');
  assert.equal(await page.getByLabel('语音识别模型').inputValue(),'mock-soniox');
  assert.equal(await page.getByLabel('语音识别模型').locator('option').count(),3);
  await page.screenshot({path:`${output}/new-session.png`});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({result:'passed',viewports:['1440x900','390x844'],paidCalls:calls.filter(c=>c.body?.live).length,screenshots:5}));
} finally {await browser.close();}
