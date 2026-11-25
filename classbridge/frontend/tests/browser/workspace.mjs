// Real browser layout checks; all business requests are isolated Mock fixtures.
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const origin = process.env.AUDIT_URL || 'http://127.0.0.1:5177';
const phase = process.argv[2] || 'after';
const output = resolve('../docs/screenshots/p2-workspace');
await mkdir(output, { recursive: true });
const preferences = {theme:'light',subtitle_size:24,show_original:true,retain_audio:false,audio_retention_days:7,
  target_language:'zh-CN',terms:[],asr_language_mode:'ko_en',models:{translation:'qwen-mt-flash'}};
const folders = Array.from({length:24},(_,i)=>({id:`folder-${i}`,name:i===0?'人工智能 · 인공지능':i===1?'长文件夹名称与 English 专业术语'.repeat(4):`课程资料 ${i+1}`,session_count: i<2?3:0,created_at:'',updated_at:''}));
const sessions = Array.from({length:6},(_,i)=>({id:`session-${i}`,title:i===0?'韩英课堂 · 模型与知识':i===1?'长会话标题：한국어 English 与中文混排'.repeat(5):`Mock 课堂记录 ${i+1}`,kind:'classroom',mode:'demo',status:'stopped',folder_id:`folder-${i%2}`,duration_ms:90000,captured_ms:60000,created_at:'2026-11-25T00:00:00Z',target_language:'zh-CN',segments:[],stages:[]}));
const providers = [{id:'aliyun',name:'阿里云 Qwen',default_model:'qwen-audio-3.1-asr-flash-streaming',credential_ref:'DASHSCOPE_API_KEY',implemented:true,options_schema:{properties:{context:{},vad_model:{}}}}];
const profiles = [{id:'mock-asr',provider:'aliyun',model_id:providers[0].default_model,display_name:'Mock · 韩英课堂',language_hints:['ko','en'],enabled:true,is_default:true,credential_ref:'DASHSCOPE_API_KEY',provider_options:{},validation:{valid:true,message:'Mock 本地配置有效；未连接模型'}}];
const documents = [{id:'doc',filename:'人工智能讲义_한국어_English.pdf',status:'ready',index_status:'ready',index_mode:'demo',page_count:12,version:1}];
const browser = await chromium.launch({headless:true});
const context = await browser.newContext();
context.setDefaultTimeout(10000);
const errors=[],calls=[],metrics=[];
await context.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.origin!==origin)return route.abort();
  if(!url.pathname.startsWith('/api/'))return route.continue();
  const path=url.pathname,method=req.method();calls.push({path,method});
  if(path==='/api/settings' && method!=='GET')Object.assign(preferences,req.postDataJSON());
  let data=path==='/api/auth/me'?{id:'mock-user',username:'Mock 验收'}
    :path==='/api/settings'?preferences:path==='/api/session-folders'?folders
    :path==='/api/asr/providers'?providers:path==='/api/asr/profiles'?profiles
    :path==='/api/documents'?documents
    :path==='/api/sessions'?sessions.filter(s=>!url.searchParams.has('folder_id') || s.folder_id===url.searchParams.get('folder_id'))
    :path.startsWith('/api/sessions/')?sessions.find(s=>s.id===path.split('/').at(-1)) || {ok:true}:[];
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
});
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
async function settled(){await page.evaluate(()=>document.fonts.ready);await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));}
async function measure(label,selector){
  const result=await page.locator(selector).evaluate(el=>({width:innerWidth,height:innerHeight,
    overflow:el.scrollWidth>el.clientWidth+1,bodyOverflow:document.documentElement.scrollWidth>innerWidth+1,
    rowHeight:document.querySelector('.session-entry')?.getBoundingClientRect().height ?? document.querySelector('.session-row')?.parentElement.getBoundingClientRect().height ?? null}));
  metrics.push({label,...result});
  if(phase==='after'){assert.equal(result.overflow,false,`${label} overflow ${result.width}`);assert.equal(result.bodyOverflow,false);}
}
try{
  for(const [width,height] of [[320,568],[390,844],[844,390],[768,1024],[1024,768],[1280,800],[1440,900]]){
    await page.setViewportSize({width,height});
    for(const name of ['home','settings','library']){
      await page.goto(`${origin}/#${name}`);await page.locator('.page-scroll').waitFor();await settled();
      if(name==='home')await page.locator('.session-row').first().waitFor();
      if(name==='settings')await page.locator('.asr-profile-row').waitFor();
      await measure(name,'.page-scroll');
      if(width===390 || width===1440)await page.screenshot({path:resolve(output,`${phase}-${width}-${name}-light.png`)});
    }
  }
  await page.setViewportSize({width:1440,height:900});await page.goto(`${origin}/#home`);await page.locator('.session-row').first().waitFor();
  await page.getByRole('button',{name:'切换深色主题'}).click();await settled();
  await page.screenshot({path:resolve(output,`${phase}-desktop-home-dark.png`)});
  await page.goto(`${origin}/#settings`);await page.locator('.asr-profile-row').waitFor();
  await page.screenshot({path:resolve(output,`${phase}-desktop-settings-dark.png`)});
  await page.goto(`${origin}/#home`);await page.locator('.session-row').first().waitFor();
  if(phase==='after'){
    const tree=page.getByRole('navigation',{name:'会话文件夹'});
    await tree.getByRole('button',{name:'收起文件夹'}).click();
    await tree.getByRole('button',{name:'展开文件夹'}).click();
    await tree.getByRole('button',{name:'人工智能 · 인공지능',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.session-row').length===3);
    await page.getByLabel('选择前100个会话').check();
    await page.getByRole('button',{name:'取消选择',exact:true}).click();
    assert.equal(await page.getByRole('button',{name:'移动所选会话',exact:true}).count(),0);
    const more=page.getByLabel('会话操作：韩英课堂 · 模型与知识');
    await more.focus();await page.keyboard.press('Enter');
    await page.getByLabel('移动会话：韩英课堂 · 模型与知识').waitFor({state:'visible'});
    await page.keyboard.press('Escape');await page.waitForFunction(()=>document.activeElement?.getAttribute('aria-label')==='会话操作：韩英课堂 · 模型与知识');
    await tree.getByRole('button',{name:'管理文件夹'}).click();
    await page.getByRole('dialog').waitFor();await measure('folder-dialog','.ui-dialog');
    await page.screenshot({path:resolve(output,'after-folder-dialog.png')});
    await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'hidden'});
  }
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'打开导航'}).click();
  await page.getByRole('dialog').waitFor();await measure('navigation','.navigation-drawer');
  await page.screenshot({path:resolve(output,`${phase}-mobile-navigation-dark.png`)});
  await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'hidden'});
  if(phase==='after'){
    await page.route('**/api/auth/me',route=>route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({detail:'Mock 未登录'})}));
    for(const [width,height] of [[390,844],[1440,900]]){
      await page.setViewportSize({width,height});await page.goto(`${origin}/?audit=login-${width}#home`);
      await page.locator('.login-box').waitFor();await settled();await measure('login','.login');
      await page.screenshot({path:resolve(output,`after-${width}-login.png`)});
    }
  }
  assert.deepEqual(errors,[]);
  assert.equal(calls.some(c=>c.path.endsWith('/validate')),false,'no paid or live model validation');
  await writeFile(resolve(output,`${phase}.json`),JSON.stringify({metrics,errors,paidModelRequests:0},null,2));
  console.log(JSON.stringify({phase,checks:metrics.length,errors:errors.length,paidModelRequests:0}));
}finally{await browser.close();}
