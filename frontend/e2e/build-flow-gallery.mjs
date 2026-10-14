import { readdir, readFile, mkdir, copyFile, writeFile, unlink } from 'node:fs/promises'
import { resolve, join, dirname, relative } from 'node:path'

const root = resolve(process.argv[2] || '../.artifacts/browser-flow-20261014')
const results = JSON.parse(await readFile(join(root, 'results.json'), 'utf8'))
const reports = [results]
for (const file of process.argv.slice(3)) reports.push(JSON.parse(await readFile(join(root, file), 'utf8')))
const outcomes = new Map()
function readOutcomes(suites) {
  for (const suite of suites) {
    for (const spec of suite.specs || []) for (const test of spec.tests) {
      outcomes.set(`${spec.id}:${test.projectName}`, { title: spec.title, passed: test.status === 'expected' && test.results.at(-1)?.status === 'passed' })
    }
    readOutcomes(suite.suites || [])
  }
}
for (const report of reports) {
  if (report.stats.interrupted) throw new Error('Interrupted browser run')
  readOutcomes(report.suites)
}
if (!outcomes.size || [...outcomes.values()].some(test => !test.passed))
  throw new Error('Every scenario must have a recorded passing result; failed scenarios require a real retest report')
const manifests = []
async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) await walk(path)
    else if (entry.name === 'flow-steps.json') manifests.push(path)
  }
}
await walk(join(root, 'raw'))
if (reports.length > 1) await walk(join(root, 'retest-raw'))
const latestFlows = new Map()
for (const path of manifests.sort()) {
  const flow = JSON.parse(await readFile(path, 'utf8'))
  latestFlows.set(flow.title, { path, flow })
}
const viewer = join(root, 'viewer')
await mkdir(join(viewer, 'images'), { recursive: true })
// Replace only this generator's numbered screenshots; raw browser evidence stays local.
for (const entry of await readdir(join(viewer, 'images'), { withFileTypes: true }))
  if (entry.isFile() && /^\d{4}\.png$/.test(entry.name)) await unlink(join(viewer, 'images', entry.name))
const frames = []
const groups = []
for (const { path, flow } of latestFlows.values()) {
  if (flow.status !== 'passed') throw new Error(`Incomplete flow: ${flow.title}`)
  if (flow.steps.some((step, index) => step.index !== index + 1)) throw new Error(`Missing action screenshot: ${flow.title}`)
  const directory = dirname(path)
  const shots = [...flow.steps]
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith('.png') || entry.name.startsWith('flow-')) continue
    const png = await readFile(join(directory, entry.name))
    // Ignore 1px upload fixtures. Preserve real screenshot pixels without editing.
    if (png.length >= 24 && png.readUInt32BE(16) > 300 && png.readUInt32BE(20) > 100)
      shots.push({ action: '结果核对 · ' + entry.name.replace(/\.png$/, ''), file: entry.name, url: '' })
  }
  const results = shots.filter(shot => shot.action.startsWith('结果核对'))
  let selected
  if (results.length) selected = results.length === 1 ? results : [results[0], results.at(-1)]
  else {
    const pages = new Map()
    for (const shot of shots)
      if (shot.url && shot.url !== '/login' && !shot.action.startsWith('填写')) pages.set(shot.url, shot)
    selected = [...pages.values()].slice(-2)
  }
  const group = { title: flow.title, count: selected.length }
  if (!group.count) throw new Error(`Missing screenshots: ${flow.title}`)
  groups.push(group)
  for (const shot of selected) {
    const index = frames.length + 1
    const file = `images/${String(index).padStart(4, '0')}.png`
    await copyFile(join(directory, shot.file), join(viewer, file))
    frames.push({ index, group: flow.title, action: shot.action, url: shot.url, file })
  }
}
if (groups.length !== outcomes.size || groups.some(group => ![...outcomes.values()].some(test => test.title === group.title && test.passed))) throw new Error('Screenshot flows do not match passing test count')
const date = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Singapore' }).format(new Date(results.stats.startTime))
const data = JSON.stringify({ date, groups, frames }).replaceAll('<', '\\u003c')
const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>前端流程截图册 · ${date}</title>
<style>body{margin:0;background:#f7f7f5;color:#222;font:16px/1.65 system-ui,sans-serif}header,main{max-width:1280px;margin:auto;padding:32px}h1{font-size:38px;margin:0 0 12px}p{color:#555}input,select,button{font:inherit;border:1px solid #ccc;border-radius:8px;padding:10px;background:white;color:#222}nav{display:flex;gap:12px;flex-wrap:wrap}input{flex:1;min-width:240px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:20px}article{background:white;border-radius:12px;padding:14px}article button{padding:0;border:0;width:100%;cursor:zoom-in}article img{display:block;width:100%;height:190px;object-fit:contain;background:#eee}article h2{font-size:15px;margin:10px 0}small{color:#555}.badge{color:#17663d}dialog{border:0;border-radius:12px;padding:18px;width:92vw;max-width:1500px;height:90vh}dialog::backdrop{background:#000b}.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.detail{height:calc(100% - 75px);overflow:auto;text-align:center}.detail img{max-width:100%;height:auto}#caption{flex:1}a{color:#1462c2}</style>
<header><h1>前端流程截图册</h1><div class="badge">${date} · ${groups.length} 条流程通过 · ${frames.length} 张新截图</div><p>真实 Vue 页面、Java Spring Boot、MySQL 与 Redis；使用隔离测试学院和数据库，上传图片为测试占位附件。覆盖预约审批、交接与归还验收、报修、角色权限、学院隔离、并发预约和通知。旧处罚申诉、逾期和维护校准流程已移除。</p><nav><input id="search" placeholder="搜索流程或操作步骤" aria-label="搜索截图"><select id="group" aria-label="选择流程"><option value="">全部流程</option></select></nav><p id="count"></p></header><main><div class="grid" id="grid"></div></main>
<dialog id="viewer"><div class="controls"><button id="prev">上一张 ←</button><button id="next">下一张 →</button><span id="caption"></span><a id="original" target="_blank">原图</a><button id="close">关闭 Esc</button></div><div class="detail"><img id="large" alt="流程截图"></div></dialog>
<script type="application/json" id="data">${data}</script><script>
const data=JSON.parse(document.getElementById('data').textContent), grid=document.getElementById('grid'), modal=document.getElementById('viewer'), search=document.getElementById('search'), group=document.getElementById('group');let visible=data.frames,position=0;
for(const flow of data.groups){const option=document.createElement('option');option.value=flow.title;option.textContent=flow.title+' ('+flow.count+')';group.append(option)}
function show(index){position=index;const frame=visible[position];document.getElementById('large').src=frame.file;document.getElementById('large').alt=frame.action;document.getElementById('caption').textContent=frame.index+' / '+data.frames.length+' · '+frame.group+' · '+frame.action;document.getElementById('original').href=frame.file;document.querySelector('.detail').scrollTop=0;if(!modal.open)modal.showModal()}
function render(){const query=search.value.trim().toLowerCase();visible=data.frames.filter(frame=>(!group.value||frame.group===group.value)&&(!query||(frame.group+' '+frame.action+' '+frame.url).toLowerCase().includes(query)));grid.replaceChildren();document.getElementById('count').textContent='显示 '+visible.length+' / '+data.frames.length+' 张。点击放大，方向键逐张查看。';for(const [i,frame] of visible.entries()){const article=document.createElement('article'),button=document.createElement('button'),img=document.createElement('img'),title=document.createElement('h2'),label=document.createElement('small');img.src=frame.file;img.alt=frame.action;img.loading='lazy';button.append(img);button.onclick=()=>show(i);title.textContent=String(frame.index).padStart(3,'0')+' · '+frame.action;label.textContent=frame.group;article.append(button,title,label);grid.append(article)}}
search.oninput=render;group.onchange=render;document.getElementById('close').onclick=()=>modal.close();document.getElementById('prev').onclick=()=>show((position-1+visible.length)%visible.length);document.getElementById('next').onclick=()=>show((position+1)%visible.length);document.addEventListener('keydown',event=>{if(!modal.open)return;if(event.key==='ArrowRight')document.getElementById('next').click();if(event.key==='ArrowLeft')document.getElementById('prev').click()});render();
</script></html>`
await writeFile(join(viewer, 'gallery.html'), html)
const markdown = `# 前端流程截图册\n\n${date} · ${groups.length} 条流程 · ${frames.length} 张关键截图\n\n` + groups.map((group, index) => {
  const shots = frames.filter(frame => frame.group === group.title)
  return `## ${index + 1}. ${group.title}\n\n` + shots.map(frame => `![${group.title} · ${frame.action}](${frame.file})`).join('\n\n')
}).join('\n\n') + '\n'
await writeFile(join(viewer, 'gallery.md'), markdown)
await writeFile(join(root, 'manifest.json'), JSON.stringify({ date, passed: groups.length, screenshots: frames.length, runs: reports.map(report => ({ passed: report.stats.expected, failed: report.stats.unexpected, startedAt: report.stats.startTime })), groups }, null, 2))
await writeFile(join(root, 'REPORT.md'), `# ${date} 前端流程截图册\n\n${groups.length} 条真实浏览器流程通过，${frames.length} 张关键截图。每条流程最多保留两张，优先选择结果核对截图。\n\n[查看截图册（GitHub 直接显示图片）](viewer/gallery.md)\n\n` + groups.map(g => `- ${g.title}：${g.count} 张`).join('\n') + '\n')
console.log(JSON.stringify({ gallery: relative(process.cwd(), join(viewer, 'gallery.html')), flows: groups.length, screenshots: frames.length }))
