// Organizational and planner DOM/payload checks; real-browser testing is separate.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),calls=[],events={};function node(k){if(!nodes.has(k))nodes.set(k,{innerHTML:'',textContent:'',dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},showModal(){},close(){},scrollIntoView(){}});return nodes.get(k)}
const admin={id:1,name:'主管',username:'admin',role:'admin',store:'pilot',home_store:'pilot',tenant_id:1,hq_owner:true,job:'bartender',stations:['main']};
const people=[{id:1,name:'主管',store:'pilot'},{id:2,name:'员工',store:'pilot'}];
const content={summary:'统一准备标准',steps:['核对器具'],ingredients:[],allergens:[]};
const template={id:1,template_id:1,version:1,title:'总部准备标准',kind:'sop',state:'published',source:'总部确认的资料',change_note:'统一模板首版',content};
const delivery={id:1,template_version_id:1,store:'pilot',title:template.title,version:1,state:'pending',rollout:'not_adopted',template,adoption:null};
const hq={owner:true,tenant:{id:1,name:'连锁总部',code:'legacy:pilot'},stores:[{code:'pilot',name:'一店',verification_note:'旧店资料迁移'},{code:'branch2',name:'二店',verification_note:'仅为测试门店'}],people,grants:[{id:1,name:'员工',store:'branch2',role:'staff',job:'bartender',note:'明确授权',expires_at:'2026-12-20T00:00:00Z'}],transfers:[{id:1,store:'other',state:'pending',destination_tenant:1,note:'原负责人申请迁入'}],templates:[template],deliveries:[delivery]};
const keys=['standard','inventory','count','service','training','flow','launch'];
const plan={id:1,title:'新品准备',station:'main',recipe_revision_id:1,version:3,state:'approved',launch_at:'2026-12-20T02:00:00Z',inputs:{recipe:{title:'金汤力',version:1},limitations:['规则式草稿','逐项核对证据']},tasks:keys.map(key=>({key,title:key,description:'核对真实业务记录并保留证据',owner_id:2,due_at:'2026-12-20T02:00:00Z'})),task_ids:[]};
const task={id:7,title:'核对新品',description:'核对实际标准与原料',owner_name:'员工',owner_id:2,due_at:'2026-12-20T02:00:00Z',state:'open',source_kind:'launch_plan',version:1};
const revision={id:1,document_id:1,title:template.title,kind:'sop',approved_at:'2026-10-01',version:1,source:'原店批准资料',content};
const context=vm.createContext({console,AbortController,setTimeout,clearTimeout,FormData:class{constructor(form){this.entries=Object.entries(form.values||{}).flatMap(([k,v])=>Array.isArray(v)?v.map(x=>[k,x]):[[k,v]])}*[Symbol.iterator](){yield* this.entries}has(k){return this.entries.some(([x])=>x===k)}getAll(k){return this.entries.filter(([x])=>x===k).map(([,v])=>v)}},document:{querySelector:node,querySelectorAll(){return []},addEventListener(name,fn){events[name]=fn}},fetch:async(url,opts)=>{calls.push({url,opts});let data={};const selected=opts.headers['X-BarOS-Store']||'pilot';if(opts.method==='POST')data={id:1};else if(url==='/api/me')data={user:{...admin,store:selected},csrf:'token'};else if(url==='/api/context')data={tenant:hq.tenant,home_store:'pilot',active_store:selected,stores:hq.stores};else if(url==='/api/config')data=[];else if(url.startsWith('/api/knowledge')||url==='/api/training')data=[];else if(url==='/api/hq')data=hq;else if(url==='/api/hq/deliveries/1')data=delivery;else if(url==='/api/manage/revisions')data=[revision];else if(url.startsWith('/api/tasks?'))data=[task];else if(url.startsWith('/api/agents/plans?'))data=[plan];else if(url==='/api/agents/plans/1')data=plan;else if(url.startsWith('/api/flow/people'))data=people;else if(url==='/api/agents/tool-audit')data=[{tool_name:'create_launch_todos',outcome:'blocked',detail:'<输入已改变>',plan_id:1,request_hash:'hash'}];return {ok:true,status:200,json:async()=>data}}});
vm.runInContext(fs.readFileSync('web/app.js','utf8'),context);vm.runInContext(fs.readFileSync('web/org.js','utf8'),context);
async function click(dataset){context.button={dataset};await vm.runInContext('orgClick(button)',context)}
async function submit(id,values,dataset={}){context.form={id,values,dataset};await vm.runInContext('doSubmit(form)',context)}
function payload(url){const c=calls.filter(c=>c.url===url&&c.opts.method==='POST').at(-1);assert(c,url);return JSON.parse(c.opts.body)}
(async()=>{
 await new Promise(r=>setTimeout(r,10));
 for(const page of ['hq','agents']){vm.runInContext('page='+JSON.stringify(page),context);await vm.runInContext('render()',context);assert(!node('#content').innerHTML.includes('重新加载'),page);assert(node('#content').innerHTML.length>200,page)}
 assert(node('#content').innerHTML.includes('&lt;输入已改变&gt;'));assert(!node('#content').innerHTML.includes('<输入已改变>'));
 await events.change({target:{id:'store-switch',value:'branch2'}});assert(calls.some(c=>c.url==='/api/me'&&c.opts.headers['X-BarOS-Store']==='branch2'));assert.equal(vm.runInContext('user.store',context),'branch2');await click({orgHome:'1'});assert.equal(vm.runInContext('activeStore',context),'');
 vm.runInContext('page="hq"',context);await vm.runInContext('render()',context);
 await submit('hq-store-form',{code:'branch3',name:'第三门店',verification_note:'门店负责人已提供资料确认',job:'bartender',station:'main'});assert.equal(payload('/api/hq/stores').code,'branch3');
 await submit('hq-grant-form',{user_id:'2',store:'branch2',role:'staff',job:'bartender',stations:'main',expires_at:'2026-12-20T10:00',note:'轮岗需要明确跨店授权'});let p=payload('/api/hq/grants');assert.equal(p.user_id,2);assert.deepEqual(p.stations,['main']);assert.equal(p.expires_at,'2026-12-20T02:00:00.000Z');
 await submit('hq-revoke-form',{note:'轮岗结束立即撤销授权'},{id:'1'});assert.equal(payload('/api/hq/grants/1/revoke').note,'轮岗结束立即撤销授权');
 await submit('hq-transfer-form',{destination_code:'legacy:pilot',note:'原店负责人申请整体迁入'});assert.equal(payload('/api/hq/transfers').destination_code,'legacy:pilot');
 await submit('hq-transfer-decision-form',{accepted:'true',note:'核对原负责人申请后接受迁入'},{id:'1'});assert(payload('/api/hq/transfers/1/decision').accepted);
 await click({hqTemplateNew:'1'});await submit('hq-template-form',{revision_id:'1',change_note:'总部统一准备标准的首版'});assert.equal(payload('/api/hq/templates').content.summary,content.summary);
 await submit('hq-approve-form',{risk_confirmed:'on'},{id:'1'});assert(payload('/api/hq/templates/1/approve').risk_confirmed);
 await submit('hq-release-form',{stores:['pilot','branch2']},{id:'1',key:'stable-release-key'});p=payload('/api/hq/templates/1/release');assert.equal(p.idempotency_key,'stable-release-key');assert.equal(p.stores.length,2);
 await click({hqDelivery:'1'});assert(node('#modal-body').innerHTML.includes('本店需要修改模板内容'));
 await submit('hq-sign-form',{accepted:'true',jobs:'bartender',stations:'main',note:'本店已核对并采用总部标准',override:'on',difference_note:'本店器具位置与总部不同',summary:'按本店实际安排准备',steps:'先核对二号柜器具'});p=payload('/api/hq/deliveries/1/sign');assert.equal(p.local_content.summary,'按本店实际安排准备');assert.equal(p.difference_note,'本店器具位置与总部不同');
 vm.runInContext('page="agents"',context);await vm.runInContext('render()',context);
 await submit('agent-new-form',{title:'新配方准备',recipe_revision_id:'1',owner_id:'2',launch_at:'2026-12-20T10:00'},{key:'stable-plan-key'});assert.equal(payload('/api/agents/plans').idempotency_key,'stable-plan-key');
 await click({agentPlan:'1'});assert(node('#modal-body').innerHTML.includes('按批准计划生成待办'));
 await submit('agent-decision-form',{approved:'true',note:'核对七项准备任务后批准'});assert.equal(payload('/api/agents/plans/1/decision').version,3);
 await click({agentExecute:'1'});await submit('agent-execute-form',{}, {key:'stable-execute-key'});p=payload('/api/agents/plans/1/execute');assert.equal(p.version,3);assert.equal(p.idempotency_key,'stable-execute-key');
 await submit('agent-task-form',{title:'核对器具',description:'逐项确认并记录检查结果',owner_id:'2',due_at:'2026-12-20T10:00'},{key:'stable-manual-task'});assert.equal(payload('/api/tasks').owner_id,2);
 await submit('agent-task-close-form',{evidence:'现场检查全部器具完毕记录A01'},{id:'7'});assert.equal(payload('/api/tasks/7/close').version,1);
 vm.runInContext('user={...user,role:"staff",hq_owner:false};page="agents"',context);await vm.runInContext('render()',context);assert(!node('#app').innerHTML.includes('data-page="hq"'));assert(node('#content').innerHTML.includes('我的上市待办'));assert(!node('#content').innerHTML.includes('生成上市准备计划草稿'));
 console.log('PASS: HQ/Agents renders, context headers and return-home, store/grant/transfer payloads, template review/release/local differences, stable request keys, approval version, task evidence, escaping and employee boundaries');
})().catch(e=>{console.error(e);process.exitCode=1});
