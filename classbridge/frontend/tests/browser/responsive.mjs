// Real Chromium layout audit. All business HTTP / WebSockets are isolated mocks.
// PLAYWRIGHT_MODULE may point to an existing playwright-core installation.
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const phase = process.argv[2] || 'after';
const output = resolve('../docs/screenshots/responsive');
await mkdir(output, { recursive: true });
const preferences = { theme: 'light', subtitle_size: 24, show_original: true, retain_audio: false,
  audio_retention_days: 7, terms: [], target_language: 'zh-CN', asr_language_mode: 'auto' };
const sentences = [
  ['오늘은 인공지능을 공부합니다. 데이터와 모델의 관계를 살펴봅시다.', '今天学习人工智能。我们将一起探讨数据与模型之间的关系。'],
  ['A model learns patterns from examples, but correlation is not causation.', '模型从示例中学习规律，但相关性并不意味着因果关系。'],
  ['작업 기억은 정보를 잠시 유지하고 처리하는 능력입니다.', '工作记忆指短暂保存信息并对其进行处理的能力。'],
];
const lesson = { id: 'responsive-fixture', title: '模拟验收 · 韩英课堂与人工智能基础', kind: 'classroom', mode: 'demo',
  status: 'idle', retain_audio: false, duration_ms: 90000, captured_ms: 60000, created_at: '2026-11-10T00:00:00Z',
  target_language: 'zh-CN', stages: [], segments: Array.from({length: 30}, (_, i) => ({
    sentence_id: `sentence-${i}`, stream_id: 'fixture-stream', source_revision: 1, translation_revision: 1,
    start_ms: i * 3000, end_ms: i * 3000 + 2500, text: sentences[i % 3][0], translation: sentences[i % 3][1],
    source_status: 'final', translation_status: 'final', source_final: true, translation_final: true,
    status: 'final', mode: 'demo', target_language: 'zh-CN',
  })) };
const documents = [{ id: 'fixture-document', filename: '模拟资料_인공지능_人工智能课堂讲义_very-long-filename.pdf', status: 'ready', index_status: 'ready', index_mode: 'demo', page_count: 2, version: 1, chunks: [{id:'c1', page:1, text: '模拟讲义内容。'.repeat(100)}] }];
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext();
await context.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname;
  if (path.endsWith('/settings') && route.request().method() !== 'GET') Object.assign(preferences,route.request().postDataJSON());
  const data = path.endsWith('/auth/me') ? { id:'fixture-user', username:'模拟验收' }
    : path.endsWith('/settings') ? preferences
    : path.endsWith('/sessions') ? [lesson]
    : path.endsWith(`/sessions/${lesson.id}`) ? lesson
    : path.endsWith('/documents/fixture-document') ? documents[0]
    : path.endsWith('/documents') ? documents
    : path.endsWith('/chat') ? [{question:'模拟：课堂重点是什么？', answer:'模拟回答：原始证据和相关性需要区分。 ' + 'https://example.invalid/'.repeat(12) + '\nمرحبا بكم في المحاضرة. 한국어와 English 混排。', mode:'demo', citations:[]}] : [];
  await route.fulfill({ status:200, contentType:'application/json', body:JSON.stringify(data) });
});
await context.addInitScript(() => {
  const NativeSocket = window.WebSocket;
  window.auditSockets = [];
  window.WebSocket = class extends EventTarget {
    static OPEN = 1; static CLOSED = 3;
    readyState = 0; bufferedAmount = 0; sent = [];
    constructor(url, protocols) {
      super();
      if (!String(url).includes('/ws/sessions/')) return new NativeSocket(url, protocols);
      window.auditSockets.push(this);
      setTimeout(() => { this.readyState = 1; this.onopen?.({}); }, 0);
    }
    send(data) { this.sent.push(data); }
    close() { this.readyState = 3; }
    event(data) { this.onmessage?.({data: JSON.stringify(data)}); }
  };
});
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const origin = process.env.AUDIT_URL || 'http://127.0.0.1:5175';
const sizes = [[320,568],[360,800],[390,844],[430,932],[844,390],[768,1024],[1024,768],[1180,820],[1280,800],[1440,900],[1920,1080]];
const names = ['mobile-320-session','mobile-360-session','mobile-390-session-light','mobile-430-session','mobile-landscape-session','ipad-portrait-session','ipad-landscape-session','tablet-session','laptop-session','desktop-session','desktop-wide-session'];
const metrics = [];
for (let i = 0; i < sizes.length; i++) {
  const [width,height] = sizes[i];
  await page.setViewportSize({width,height});
  await page.goto(`${origin}/#session/${lesson.id}`);
  await page.locator('.subtitle-segment').first().waitFor();
  await page.evaluate(() => document.fonts.ready);
  // Let existing ResizeObserver / animation frame follow settle, then inspect history at the same start.
  await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
  await page.locator('.subtitle-list').evaluate(el => { el.style.scrollBehavior='auto'; el.scrollTop=0; el.dispatchEvent(new Event('scroll')); });
  await page.evaluate(() => new Promise(r => requestAnimationFrame(r)));
  const result = await page.evaluate(() => {
    const box = selector => document.querySelector(selector).getBoundingClientRect();
    const list = document.querySelector('.subtitle-list');
    const bounds = box('.subtitle-list');
    const bar = box('.capture-bar');
    const top = Math.max(0, bounds.top), bottom = Math.min(innerHeight, bounds.bottom, bar.top);
    // Count actual complete text line boxes, not font-size arithmetic or happy-dom geometry.
    let lines = 0;
    for (const text of list.querySelectorAll('.source-text, .translation-text')) {
      const range = document.createRange(); range.selectNodeContents(text);
      const rows = new Set();
      for (const rect of range.getClientRects()) if (rect.height > 0 && rect.top >= top && rect.bottom <= bottom) rows.add(Math.round(rect.top));
      lines += rows.size;
    }
    return { viewport_width:innerWidth, viewport_height:innerHeight, app_height:box('.app-shell').height,
      session_header_height:box('.session-heading').height, subtitle_panel_height:box('.subtitle-panel').height,
      subtitle_list_client_height:list.clientHeight, subtitle_visible_height:Math.max(0, bottom-top),
      capture_bar_height:bar.height, capture_visible:bar.top >= 0 && bar.bottom <= innerHeight+1,
      visible_subtitle_lines:lines, horizontal_overflow:document.documentElement.scrollWidth > innerWidth ||
        [...document.querySelectorAll('.main-content, .session-view, .subtitle-panel')].some(el=>el.scrollWidth>el.clientWidth+1) };
  });
  metrics.push(result);
  if (phase === 'after') {
    assert.equal(result.horizontal_overflow, false, `overflow at ${width}`);
    assert.equal(result.capture_visible, true, `capture visible ${width}x${height}`);
  }
  await page.screenshot({path:resolve(output, `${phase === 'before' ? 'before-' : ''}${names[i]}.png`)});
}
await writeFile(resolve(output, `${phase}.json`), JSON.stringify(metrics, null, 2));
if (phase === 'after') {
  const checks = [];
  async function checkLayout(label, selector) {
    const result = await page.locator(selector).evaluate(el => {
      const rect = el.getBoundingClientRect();
      return { width:innerWidth, height:innerHeight, overflow:el.scrollWidth>el.clientWidth+1,
        inViewport: rect.left>=-1 && rect.right<=innerWidth+1 && rect.top>=-1 && rect.bottom<=innerHeight+1 };
    });
    assert.equal(result.overflow,false,`${label}: horizontal overflow ${JSON.stringify(result)}`);
    assert.equal(result.inViewport,true,`${label}: outside viewport ${JSON.stringify(result)}`);
    checks.push({label,...result});
  }
  for (const [width,height] of sizes) {
    await page.setViewportSize({width,height});
    for (const name of ['home','settings','library']) {
      await page.goto(`${origin}/#${name}`);
      await page.locator('.page-scroll').waitFor();
      await checkLayout(name,'.page-scroll');
      if(width===390) await page.screenshot({path:resolve(output,`mobile-${name}.png`)});
    }
    await page.goto(`${origin}/#session/${lesson.id}`);
    await page.locator('.subtitle-segment').first().waitFor();
    const tab = page.locator('.mobile-tabs button').filter({hasText:'AI 问答'});
    if(await tab.isVisible()) await tab.click();
    else await page.locator('.insight-tabs button').filter({hasText:'AI 问答'}).click();
    await page.getByLabel('输入问题').fill('한국어 输入法与 English');
    await checkLayout('chat','.chat-panel');
    await checkLayout('chat composer','.chat-compose');
    await checkLayout('chat text','.chat-turns');
    await page.getByLabel('输入问题').dispatchEvent('keydown',{key:'Enter',isComposing:true});
    assert.equal(await page.getByLabel('输入问题').inputValue(),'한국어 输入法与 English');
    await page.locator('.session-details > summary').click();
    await checkLayout('tools','.session-details-content');
    await page.getByRole('button',{name:'本会话资料',exact:true}).click();
    await page.getByRole('dialog').waitFor();
    await checkLayout('documents dialog','.ui-dialog');
    await page.getByRole('dialog').getByRole('button',{name:/查看来源/}).click();
    await page.getByRole('dialog',{name:'资料来源预览',exact:true}).waitFor();
    await page.locator('.document-chunks article').waitFor();
    await checkLayout('document preview','.document-preview');
    await checkLayout('document text','.document-chunks');
    await page.keyboard.press('Escape');
    await page.getByRole('dialog',{name:'资料来源预览',exact:true}).waitFor({state:'hidden'});
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.waitForFunction(()=>document.activeElement?.getAttribute('aria-label')==='本会话资料');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.session-details').evaluate(el=>el.open),false);
  }
  // Same SessionView / WebSocket across rotation, pane switches, theme and drawer.
  await page.setViewportSize({width:390,height:844});
  await page.goto(`${origin}/#session/${lesson.id}`);
  await page.getByRole('button',{name:'开始模拟',exact:true}).click();
  await page.getByRole('button',{name:'停止模拟',exact:true}).waitFor();
  const socketCount=await page.evaluate(()=>window.auditSockets.length);
  for(const [width,height] of [[844,390],[1024,768],[1440,900],[390,844]]) {
    await page.setViewportSize({width,height});
    await page.getByRole('button',{name:'停止模拟',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>window.auditSockets.length),socketCount);
    const tabs=page.locator('.mobile-tabs button');
    if(await tabs.first().isVisible()) { await tabs.nth(2).click(); await tabs.nth(0).click(); }
    if(width===1440) {
      await page.getByRole('button',{name:'折叠侧边栏',exact:true}).click();
      await page.locator('.session-details > summary').click();
      await page.getByRole('button',{name:'切换侧栏',exact:true}).click();
      await page.getByRole('button',{name:'切换侧栏',exact:true}).click();
      await page.locator('.session-details > summary').click();
    }
  }
  await page.getByRole('button',{name:'打开导航',exact:true}).click();
  await page.getByRole('dialog').waitFor();
  assert.equal(await page.getByRole('dialog').getByRole('button',{name:'资料库',exact:true}).isDisabled(),true);
  await page.keyboard.press('Escape');
  await page.getByRole('dialog').waitFor({state:'hidden'});
  await page.getByRole('button',{name:'切换深色主题',exact:true}).click();
  await page.waitForFunction(()=>document.documentElement.classList.contains('dark'));
  await page.screenshot({path:resolve(output,'mobile-390-session-dark.png'),animations:'disabled'});
  await page.locator('.session-details > summary').click();
  for(const name of ['删除会话','清空','本会话资料']) assert.equal(await page.getByRole('button',{name,exact:true}).isDisabled(),true);
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(()=>window.auditSockets.length),socketCount);
  assert.equal(await page.evaluate(()=>window.auditSockets.at(-1).sent.filter(x=>JSON.parse(x).type==='start').length),1);
  assert.equal(await page.evaluate(()=>window.auditSockets.at(-1).sent.filter(x=>JSON.parse(x).type==='stop').length),0);
  await page.getByRole('button',{name:'停止模拟',exact:true}).click();
  // Short viewport models available layout space only; this is NOT a native Safari keyboard test.
  await page.goto(`${origin}/#session/${lesson.id}`);
  await page.setViewportSize({width:390,height:500});
  await page.locator('.mobile-tabs button').nth(2).click();
  await page.getByLabel('输入问题').fill('한국어 질문 / 输入中');
  await page.getByLabel('输入问题').focus();
  await checkLayout('reduced viewport composer','.chat-compose');
  await page.screenshot({path:resolve(output,'mobile-chat-compact-viewport.png')});
  await page.setViewportSize({width:390,height:844});
  await page.reload();
  await page.locator('.subtitle-segment').first().waitFor();
  await page.locator('.subtitle-list').evaluate(el=>{el.scrollTop=0;el.dispatchEvent(new Event('scroll'));});
  await page.getByRole('button',{name:'回到最新',exact:true}).waitFor();
  await page.evaluate(id=>window.auditSockets.at(-1).event({type:'transcript.final',event_id:'audit-final',event_seq:100,
    session_id:id,stream_id:'fixture-stream',sentence_id:'new-final',source_revision:1,text:'LongWord'.repeat(40),start_ms:100000,end_ms:101000,mode:'demo'}),lesson.id);
  await page.locator('#sentence-new-final').waitFor({state:'attached'});
  assert.equal(await page.locator('.subtitle-list').evaluate(el=>el.scrollTop),0,'new final cannot steal history position');
  await page.getByRole('button',{name:'回到最新',exact:true}).click();
  await page.waitForFunction(()=>{const el=document.querySelector('.subtitle-list');return el.scrollHeight-el.scrollTop-el.clientHeight<2;});
  await checkLayout('long subtitles','.subtitle-list');
  assert.equal(await page.locator('.subtitle-segment').count(),31,'all historical rows remain');
  // Restore a selected RTL target from a mock history snapshot without touching preference logic.
  const oldTarget=lesson.target_language;
  lesson.target_language='ar';
  const originals=lesson.segments;
  lesson.segments=originals.map(s=>({...s,target_language:'ar',translation:'هذه ترجمة تجريبية للنص الأصلي في المحاضرة.'}));
  await page.reload();
  await page.locator('.translation-text[dir="rtl"]').first().waitFor();
  await checkLayout('RTL subtitles','.subtitle-list');
  lesson.target_language=oldTarget; lesson.segments=originals;
  await page.setViewportSize({width:844,height:390});
  await page.evaluate(id=>window.auditSockets.at(-1).event({type:'processing.failed',event_id:'mock-error',event_seq:101,session_id:id,task_kind:'translate',message:'模拟错误：翻译服务暂时不可用，请检查连接。原文仍保留。'}),lesson.id);
  await page.getByRole('alert').waitFor();
  await checkLayout('landscape visible error','.session-notice');
  await checkLayout('landscape capture with error','.capture-bar');
  await page.setViewportSize({width:390,height:844});
  await page.goto(`${origin}/#home`);
  await page.getByRole('button',{name:'打开导航',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'新建会话',exact:true}).click();
  await page.getByRole('dialog',{name:'新建会话',exact:true}).waitFor();
  await checkLayout('create dialog','.ui-dialog');
  await page.screenshot({path:resolve(output,'mobile-create-dialog.png')});
  await page.keyboard.press('Escape');
  await page.getByRole('dialog').waitFor({state:'hidden'});
  await page.waitForFunction(()=>document.activeElement?.getAttribute('aria-label')==='打开导航');
  await context.route('**/api/auth/me', route=>route.fulfill({status:401,contentType:'application/json',body:'{"detail":"Mock login required"}'}));
  for(const [width,height] of sizes) {
    await page.setViewportSize({width,height});
    await page.reload();
    await page.locator('.login-box').waitFor();
    assert.equal(await page.locator('.login').evaluate(el=>el.scrollWidth>el.clientWidth+1),false,`login overflow ${width}`);
    await page.locator('.login-box input[type="password"]').scrollIntoViewIfNeeded();
    const rect=await page.locator('.login-box input[type="password"]').boundingBox();
    assert.ok(rect && rect.y>=0 && rect.y+rect.height<=height,'login input remains reachable');
    checks.push({label:'login',width,height,overflow:false});
  }
  await writeFile(resolve(output,'checks.json'),JSON.stringify({checks,lifecycle:'same mock WebSocket; one start, no stop across resize/tabs/theme/drawer/sidebar',native_keyboard_tested:false},null,2));
}
assert.deepEqual(errors, [], 'no browser runtime errors');
console.log(JSON.stringify(metrics));
await browser.close();
