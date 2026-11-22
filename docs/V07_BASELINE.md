# BarOS V0.7 — 集成候选与真实试点基线

状态：0.7.0-rc.1候选，不是已发布到main。工作期间远端已合并G0；本代理没有执行PR合并。未获得明确合并授权，本轮不自动合并PR，不重写远程历史，不打正式release标签。测试通过只能说明列出的候选和环境已验证。

## 1. 重新核对的真实远程状态

**工作期间再次复核更新：** PR #1已于2026-11-22 15:30:48北京时间由远端操作普通合并；main当前为a17518c98525106bccc2f8717ec8b7ddef3c5e7e。下面最初观察保留为历史，不是最终main。NIGHTFALL已从该最新main建立独立分支feat/nightfall-v07-main@7da2ca2acb909d2a16cbf237e45453d73082a9dc，草稿PR #4目标main。旧临时草稿#2已关闭并指向#4，原分支保留。候选PR #3依赖#4，只评审Task007增量。

核对时间：2026-11-22 15:29北京时间（07:29 UTC）。通过git ls-remote、GitHub PR及Actions API重新查询，未使用用户提供的缩写代替查询。

| 对象 | 实际HEAD/状态 |
| --- | --- |
| main | 4e86ad26e0d48d47c6cb8df60e35821f7b4f7126 |
| feat/g0-e2e | 2a7c18b0d64c5ab80d963c5c6566b3a159e332f8 |
| feat/task-006-realistic-demo | 92ddf094c85f0ef374bcf4676c8a75eb6de47b4f |
| PR #1 | open、未合并、非draft、mergeable/clean；base=main@4e86ad2，head=2a7c18b |
| PR #2 | NIGHTFALL独立草稿；base=feat/g0-e2e，head=92ddf09；等待#1 |
| 本轮受测代码HEAD | e73b1ca448e5958e8bbadc81c5d96abc843e3119 |
| 候选分支 | feat/v07-pilot-baseline；最终文档提交HEAD用git rev-parse HEAD读取，不冒充main |

[PR #1](https://github.com/cqian7145-cyber/Enterprise-Knowledge-Base/pull/1) · [PR #2](https://github.com/cqian7145-cyber/Enterprise-Knowledge-Base/pull/2)。GitHub PR的merge_commit_sha可能只是可合并测试提交，不能据此声称已合并；本次merged=false。

远程已有证据：

- main push CI：run44913582122，success。
- G0 PR CI：[run44917355196](https://github.com/cqian7145-cyber/Enterprise-Knowledge-Base/actions/runs/44917355196)，success。
- NIGHTFALL push CI：[run44997993365](https://github.com/cqian7145-cyber/Enterprise-Knowledge-Base/actions/runs/44997993365)，success，Unit/DOM、Chromium desktop及mobile三项均success。

这些旧CI结果只归属于对应SHA，不能替代本轮新候选的回归。

## 2. 依赖审查与集成差异

真实父子关系为4e86ad2 → 2a7c18b → 92ddf09。隔离副本从最新origin/main出发，依次执行merge --ff-only origin/feat/g0-e2e和merge --ff-only origin/feat/task-006-realistic-demo，均快进成功，无冲突。未修改原工作区的任何已有源码、配置、Git元数据或SQLite数据。

| 层 | 差异及评审范围 |
| --- | --- |
| G0 | 13文件，816插入/3删除；真实Cookie/CSRF、桌面和390px手机视口E01–E12、恢复演练、覆盖检查、CI/设备文档；无业务代码变化 |
| NIGHTFALL相对G0 | 20文件，1744插入/10删除；显式离线demo CLI、合成资料/历史API回放、持续模拟标识、50条合成名称/别名、9组后端测试、NF01–NF06及文档 |
| Task007相对NIGHTFALL | 候选版本号、真实CLI首次执行/重复/环境隔离测试、普通数据库页面不显示模拟标识断言、本文/机器证据/下一任务卡/README；不新增业务模块或迁移 |

合并建议：先明确授权合并#1，重新查询main和CI。若采用保留祖先的普通合并，可在确认#2 diff只剩NIGHTFALL后将base改为最新main；若#1 squash导致祖先不同，从最新main新建分支只cherry-pick 92ddf09，再建独立PR，保留旧分支与记录，不force-push。NIGHTFALL合并后，再将本轮Task007候选差异基于最新main评审。任何main变化都使本报告成为旧观察，必须重新确认依赖和运行必要回归。

## 3. 已实现功能与版本

Memory知识系列/版本/审核/定时生效/负责人/复审/反馈提案和来源追踪；Academy版本课程/多题考试/实操/重学及技能证据；Flow固定开收吧/交接/异常/报修；Command由业务记录计算待办；Service审核话术/客诉/场景；Inventory单位/SKU/历史配方/来源销售/双人盘点；Insight冻结证据/材料成本/库存差异/独立复算；HQ明确授权/总部发布/本店签收审核；Agents固定七项准备计划/人工审批/幂等执行和审计。

API/OpenAPI版本0.7.0-rc.1；Schema迁移仍1–5；demo数据集nightfall-v1；公式stock-material-v1；没有LLM、向量库或通用自主Agent。已有queries.resolved表示有引用，不表示员工实际解决。

## 4. 本轮自动化结果

| 检查 | 本轮实际结果 |
| --- | --- |
| 全量Python | 84 passed，260.36秒；原82项＋2项V0.7身份/真实CLI首次导入隔离验收 |
| G0 Chromium desktop/mobile | 共24 passed，182.72秒；各12，0失败/0跳过 |
| NIGHTFALL六故事desktop/mobile | 共12 passed，153.33秒；各6，0失败/0跳过 |
| Node四套及JS语法 | 全通过 |
| 两套覆盖校验 | E01–E12、NF01–NF06齐全，0缺例/失败/跳过 |
| pip check | No broken requirements found |

本轮没有失败或跳过的自动化用例。原有TestClient依赖弃用警告保留为已知风险。完整JUnit已保存至docs/evidence/v07-python.xml、v07-g0.xml、v07-nightfall.xml，机器摘要含各文件SHA-256；不引用旧轮测试代替本轮结果。

本轮使用Windows11、Python3.14.2、FastAPI0.165.0、pytest9.2.0、Playwright1.65.2、Node24.22.1。CI继续使用锁文件、Python3.14和Node22；本机Node版本不同，因此仍需对应提交的远程CI，不能以本机结果证明Linux/Node22。

全部测试使用隔离临时库和合成人员；没有打开或改写正式客户库。新增CLI测试真实运行argparse/cli.main，只有getpass输入由测试提供随机密码，业务API、身份/CSRF、事务和校验均未替换；特意让BAROS_DB指向另一个临时“正常库”，验证显式导入目标及正常库哈希不变。故障注入覆盖回滚、目标不存在、staging清除和错误记录。重复CLI不再询问密码且文件哈希不变。

E01新增正常库/api/environment为false且浏览器模拟横幅隐藏；正常库虽是合成测试哨兵，但走的是没有demo_manifest的真实应用数据库路径。NF01验证demo横幅；两者不能靠环境变量互相冒充。不能从这里推导已对某个实际客户数据库做过检查。

机器证据见[evidence/V07_AUTOMATION.json](evidence/V07_AUTOMATION.json)。完整本地JUnit、日志、截图、observations、失败trace及恢复演练在候选副本test-results，按.gitignore不进入公开源码树。远程CI运行产物保留7天，超过期限须重跑/按授权另存，不承诺永久可下载。

## 5. 可复现运行与人工演示

在新目录检出明确候选SHA，保留原工作区；安装requirements.lock，浏览器另装requirements-e2e.lock和Chromium。常规命令：

~~~powershell
python -m pytest -q --junitxml=test-results/v07-python.xml
node --check web/app.js
node tests/test_web.cjs
node tests/test_operations_web.cjs
node --check web/commerce.js
node tests/test_commerce_web.cjs
node --check web/org.js
node tests/test_org_web.cjs
python -m pytest --run-e2e tests/e2e -q --junitxml=test-results/v07-g0.xml
python tools/check_e2e_report.py test-results/v07-g0.xml --profile all
python -m pytest --run-e2e tests/demo_e2e -q --junitxml=test-results/v07-nightfall.xml
python tools/check_e2e_report.py test-results/v07-nightfall.xml --profile all --suite nightfall
~~~

浏览器安装：python -m playwright install --no-shell chromium（Linux CI加--with-deps）。以各目录自己的虚拟环境python执行，不把测试BAROS_DB设置带入客户服务。

人工演示使用新路径，操作人现场设置密码，无仓库默认密码：

~~~powershell
python -m app.cli seed-realistic-demo --database "D:\workspace\v07-nightfall-demo.sqlite" --environment demo --confirm SIMULATED-DATA
$env:BAROS_DB = 'D:\workspace\v07-nightfall-demo.sqlite'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8007
~~~

详见[初始化与隔离](DEMO_SETUP.md)、[逐步故事](DEMO_SCENARIOS.md)、[字段和来源](DEMO_DATA_DICTIONARY.md)。打开http://127.0.0.1:8007，用独立浏览器上下文，检查模拟标识。演示六条：资料/岗位吧台范围、新人培养及变更重学、异常处理与Command、库存差异/下载复算/缺证、HQ签收不等于生效、受控计划和旧配方执行阻止。前端实际点击的NF01–NF06与这些主题一致，不将其包装成人工签收。

## 6. 人工缺口、已知风险和试点阻塞

| 项目 | 状态及影响 |
| --- | --- |
| 正式main集成/发布 | 部分完成：G0的#1已由远端操作合并；仍需明确授权依次审批NIGHTFALL #4及候选 #3 |
| 真机 | 未验证：OPPO、iPhone/Safari、平板、虚拟键盘/横屏、现场灯光/弱网与高峰流程；390px Chromium不是Android/iPhone设备 |
| 真实资料与问题 | 阻塞：授权材料、有效来源/负责人、岗位/吧台范围和至少50条实际问法/人工标注未交付；NIGHTFALL50问全部合成 |
| 真实培训资格/安全 | 未验证：模拟实操和安全升级占位不能代替场所批准；过敏标签、消防、医疗等需现场负责人/专业规则 |
| 公网部署 | 未验证：TLS、Secure Cookie、代理信任/限流、主机名限制、告警、凭据交付、实际恢复容量和目标RTO/RPO |
| SQLite单实例 | 风险：当前适用于单实例验证，未进行多实例/大容量/磁盘损坏/真实连锁迁入回退演练 |
| Demo时钟与导入 | 历史回放只适用于离线串行构建；不能从Web进程调用fixture；新库可重建，禁止覆盖；运行恢复真实时钟，未来版本/授权会到期 |
| 依赖弃用警告 | 已知：Starlette TestClient/httpx弃用警告仍在，当前锁文件测试通过；本轮未升级依赖或隐藏警告 |
| 数据口径 | 材料贡献额不是净利润；缺成本/映射为缺口，查询有引用不代表实际解决；不从合成数字推导ROI |
| 浏览器和资料隐私 | 测试证据只含合成数据；真实问题/截图不得自动提交公开仓库，须另定授权与保留期限 |

本候选通过的自动化不能宣称G1真实资料、G2现场价值或G3真实多店已完成。下一张任务为[Task008真实问题评估与查询结果采集](TASK_008_REAL_QUESTIONS.md)，先采集可核对的实际问题与结果，再决定检索迭代。

## 7. 本轮远端候选核验入口

候选草稿PR基于feat/task-006-realistic-demo，仅评审Task007增量；不自动合入main。候选最终文档提交保持受测代码不变，GitHub Actions会在该提交重新运行完整矩阵。最终状态与产物请查看[候选分支Actions](https://github.com/cqian7145-cyber/Enterprise-Knowledge-Base/actions?query=branch%3Afeat%2Fv07-pilot-baseline)及PR checks；本报告不将创建PR视为已通过远端CI。

## 8. 最新main对齐的追加记录

从main@a17518c建立NIGHTFALL评审分支，再用普通merge合入原92ddf09；没有cherry-pick重复提交，也没有改写原分支。候选追加合并该评审分支前后git tree完全相同，因此上文受测代码及JUnit仍对应相同代码树；随后只更新此文及机器摘要。最终准确候选HEAD见PR #3，远程CI重新执行全矩阵。当前评审顺序为[独立NIGHTFALL #4](https://github.com/cqian7145-cyber/Enterprise-Knowledge-Base/pull/4) → [基线 #3](https://github.com/cqian7145-cyber/Enterprise-Knowledge-Base/pull/3)，均保持草稿，不自动合并。
