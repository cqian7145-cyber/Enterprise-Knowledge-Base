// DOM rendering and actual form payload checks; does not replace a real browser.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),calls=[];
function node(key){if(!nodes.has(key))nodes.set(key,{innerHTML:'',textContent:'',dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},showModal(){},close(){},scrollIntoView(){},querySelectorAll(){return Array.from({length:(this.innerHTML.match(/class="course-question"/g)||[]).length})},insertAdjacentHTML(_,html){this.innerHTML+=html}});return nodes.get(key)}
const admin={id:1,name:'主管',username:'admin',role:'admin',job:'bartender',stations:['main']};
const people=[admin,{...admin,id:2,name:'员工',role:'staff'}];
const mod={id:1,course_id:1,version:1,title:'开吧课程',objective:'学会检查开吧标准',revision_ids:[1],quiz:[{question:'器具是否消毒',options:['是','否'],answer:0}],pass_score:100,is_latest:true,stale:false};
const progress={id:1,user_id:2,module_id:1,name:'员工',title:mod.title,version:1,status:'practical',best_score:100,pass_score:100,stale:false,active:true};
const run={id:1,station:'main',kind:'opening',business_date:'2026-11-21',owner_id:2,owner_name:'员工',owner_active:true,version:4,state:'open',done:0,total:1,items:[{id:9,position:0,label:'检查设备',state:'pending',note:'',evidence:''}]};
const incident={id:3,station:'main',title:'设备报警',description:'设备无法正常启动',report_evidence:'设备编号ICE01',owner_id:2,owner_name:'员工',owner_active:true,state:'open',version:5,kind:'repair'};
const evidence={user_id:2,name:'员工',definition:'技能证据对应版本',items:[{...progress,qualified:false,materials:[1],material_versions:[{title:'开吧标准',version:1,source:'主管书面确认'}],attempts:[{score:100}],reviews:[{reviewer_name:'主管',passed:false,note:'需要重新练习操作',evidence:'<img src=x onerror=bad>'}]}]};
const command={business_date:'2026-11-21',counts:{training:1,overdue_training:1,incidents:1,runs:1},missing_runs:[{station:'main',kind:'closing',title:'收吧清单'}],runs:[run],incidents:[incident],training:[progress],standard_changes:[{title:'开吧标准',version:2,state:'current',change_note:'新设备检查标准'}],feedback:[],pending_reviews:0,definition:'真实业务记录'};
const context=vm.createContext({console,AbortController,setTimeout,clearTimeout,FormData:class{constructor(form){this.entries=Object.entries(form.values||{}).flatMap(([k,v])=>Array.isArray(v)?v.map(x=>[k,x]):[[k,v]])}*[Symbol.iterator](){yield* this.entries}getAll(k){return this.entries.filter(([x])=>x===k).map(([,v])=>v)}has(k){return this.entries.some(([x])=>x===k)}},document:{querySelector:node,querySelectorAll(){return []},addEventListener(){}},fetch:async(url,opts)=>{calls.push({url,opts});let data={};if(opts.method==='POST'){data=url.includes('/version')?{id:2,version:2,reassigned:[2],blocked:[]}:{};}else if(url==='/api/me')data={user:admin,csrf:'token'};else if(url==='/api/config')data=[];else if(url==='/api/manage/users'||url.startsWith('/api/flow/people'))data=people;else if(url==='/api/manage/modules')data=[mod];else if(url==='/api/manage/training')data=[progress];else if(url==='/api/manage/revisions')data=[{id:1,document_id:7}];else if(url.startsWith('/api/knowledge'))data=[{id:7,revision_id:2,title:'新版标准',version:2}];else if(url==='/api/training')data=[];else if(url==='/api/flow/runs/1')data=run;else if(url.startsWith('/api/flow/runs?'))data=[run];else if(url==='/api/flow/incidents/3')data=incident;else if(url.startsWith('/api/flow/incidents?'))data=[incident];else if(url==='/api/flow/templates')data={opening:{title:'开吧清单'}};else if(url.startsWith('/api/academy/evidence'))data=evidence;else if(url==='/api/manage/command')data=command;return {ok:true,status:200,json:async()=>data}}});
vm.runInContext(fs.readFileSync('web/app.js','utf8'),context);
async function submit(form){context.form=form;await vm.runInContext('doSubmit(form)',context)}
async function click(dataset){context.button={dataset};await vm.runInContext('operationsClick(button)',context)}
function last(url){const c=calls.filter(c=>c.url===url&&c.opts.method==='POST').at(-1);assert(c,'Missing POST '+url);return JSON.parse(c.opts.body)}
(async()=>{
 await new Promise(r=>setTimeout(r,10));
 for(const page of ['team','flow','command','evidence']){vm.runInContext('page='+JSON.stringify(page),context);await vm.runInContext('render()',context);assert(!node('#content').innerHTML.includes('重新加载'),page);assert(node('#content').innerHTML.length>300,page)}
 assert(node('#content').innerHTML.includes('&lt;img'));assert(!node('#content').innerHTML.includes('<img'));
 vm.runInContext('page="team"',context);await vm.runInContext('render()',context);
 await click({courseVersion:'1'});const modal=node('#modal-body').innerHTML;assert(modal.includes('value="2" selected'));assert(modal.includes('是\n否'.replace('\\n','\n')));assert(modal.includes('变更原因'));
 node('#course-questions').innerHTML='<fieldset class="course-question"></fieldset>';
 await click({courseAddQuestion:'1'});assert(node('#course-questions').innerHTML.includes('question_1'));
 await submit({id:'course-form',dataset:{id:'1'},values:{title:'新版课程',objective:'学会新增设备检查',revision_ids:['2'],pass_score:'80',question_0:'是否检查',options_0:'是\n否'.replace('\\n','\n'),answer_0:'1',question_1:'是否记录',options_1:'是\n否'.replace('\\n','\n'),answer_1:'2',change_note:'增加设备检查与证据',due_at:'2026-12-20T10:00'}});
 const course=last('/api/manage/modules/1/version');assert.deepEqual(course.revision_ids,[2]);assert.equal(course.quiz.length,2);assert.equal(course.quiz[1].answer,1);assert.equal(course.quiz[0].options.length,2);assert.equal(course.due_at,'2026-12-20T02:00:00.000Z');
 await submit({id:'academy-practical',dataset:{id:'1'},values:{passed:'false',note:'仍需再次练习操作',evidence:'现场发现遗漏消毒步骤'}});assert.equal(last('/api/manage/training/1/reviews').passed,false);
 await submit({id:'academy-assign',dataset:{},values:{module_id:'1',user_id:'2',due_at:'2026-12-20T10:00'}});assert.equal(last('/api/manage/assignments').user_id,2);
 vm.runInContext('page="flow"',context);await vm.runInContext('render()',context);
 await click({startRun:'handoff'});assert(node('#modal-body').innerHTML.includes('接班人'));
 await submit({id:'flow-start',dataset:{station:'main'},values:{kind:'handoff',owner_id:'2',recipient_id:'1'}});const start=last('/api/flow/runs');assert.equal(start.recipient_id,1);assert.equal(start.kind,'handoff');assert(/^\d{4}-\d{2}-\d{2}$/.test(start.business_date));
 await click({flowRun:'1'});assert(node('#modal-body').innerHTML.includes('现场证据'));
 await submit({id:'flow-item-9',dataset:{flowItem:'9'},values:{state:'issue',note:'制冰设备无法启动',evidence:'现场报警显示E02'}});assert.equal(last('/api/flow/runs/1/items/9').version,4);
 await submit({id:'flow-close',dataset:{},values:{note:'逐项核查后完成清单'}});assert.equal(last('/api/flow/runs/1/close').version,4);
 await submit({id:'repair-form',dataset:{},values:{title:'设备异常',description:'设备无法正常启动',evidence:'现场报警读数E02',owner_id:'2'}});assert.equal(last('/api/flow/incidents').station,'main');
 await click({flowIncident:'3'});await submit({id:'incident-resolve',dataset:{},values:{resolution:'维修完成且复检正常',evidence:'维修工单WX001已完成'}});assert.equal(last('/api/flow/incidents/3/resolve').version,5);
 await submit({id:'flow-owner-form',dataset:{kind:'run',id:'1',version:'4'},values:{owner_id:'2',recipient_id:'1'}});assert.equal(last('/api/flow/runs/1/owner').recipient_id,1);
 await click({closeIncident:'3'});assert.equal(last('/api/flow/incidents/3/close').version,5);
 vm.runInContext('user.role="staff";page="flow"',context);await vm.runInContext('render()',context);assert(!node('#app').innerHTML.includes('data-page="command"'));assert(node('#app').innerHTML.includes('data-page="evidence"'));
 console.log('PASS: Academy/Flow/Command/evidence renders, escaping, multi-question version form, relearning deadline timezone, practical failure, assignments, handoff, item evidence, closure, repair, reassignment and staff navigation');
})().catch(e=>{console.error(e);process.exitCode=1});
