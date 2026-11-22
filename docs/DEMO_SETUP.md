# NIGHTFALL 独立演示库：初始化、隔离与重建

所有资料属于 **SIMULATED DATA / 模拟数据**，品牌、人员、订单、采购、配方批准及实操证据均为虚构。不构成真实出品标准、岗位认证或经营事实。

## 基线

本轮核对远程 main：4e86ad26e0d48d47c6cb8df60e35821f7b4f7126。现有九个模块已存在，数据库迁移为 v1–v5。本地沿用上轮 G0 测试基础 2a7c18b；不新增业务模块、不修改正式业务 Schema 或放松校验。

## 首次初始化

在仓库根目录安装现有 requirements.lock。使用一个全新的绝对路径，文件名必须含 demo；禁止使用默认 data/baros.sqlite。

~~~powershell
.\.venv\Scripts\python.exe -m app.cli seed-realistic-demo --database "D:\workspace\nightfall-demo.sqlite" --environment demo --confirm SIMULATED-DATA
~~~

命令交互要求操作人输入并确认 12–200 位密码。全部演示账号最初使用操作人设置的同一个密码，便于独立产品演示；可以通过原有修改密码功能分别修改。没有默认密码，没有将密码写入配置、manifest、日志或公开仓库。不要把正式账号密码用于演示。

常用账号：nf_admin（店长/管理员）、nf_lead（主调）、nf_supervisor（复核主管）、nf_mentor（带教）、nf_new（新人已复练通过）、nf_retry（实操未通过）、nf_theory（待实操）、nf_failed（理论未过）、nf_learning（部分答对）、nf_idle（未测验）、nf_bar1（跨版重学及上新待办）、nf_server1（服务岗位）、nf_rotating（分店授权已撤销）、nf_branch（河畔店长）、iso_admin（独立租户）。完整账号及角色由命令输出 accounts 提供；用户名 nf_ 开头均为合成人员。

重复执行同一命令不再要求密码，不修改已有数据或密码，返回 unchanged: true。重复执行不是“重置演示”；演示中产生的新记录会保留。

## 启动这个演示库

~~~powershell
$env:BAROS_DB = 'D:\workspace\nightfall-demo.sqlite'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8006
~~~

打开 http://127.0.0.1:8006 。请用独立浏览器配置或全新无痕上下文；同主机不同端口仍可能共享 Cookie。密码由操作人保管，本仓库不提供密码。当前实例须独立于正式服务运行，不能把正式域名或正式服务配置切到演示库。

浏览器登录页、工作台和弹窗显示模拟标识。标识读取当前数据库中的 demo_manifest，不能单靠环境变量将真实资料伪装成模拟资料。清除/关闭该 PowerShell 终端的 BAROS_DB 设置后再运行其他实例。

## 隔离与失败处理

1. 在验证参数和已有文件身份后，才创建同目录临时 staging 库。已有普通 SQLite、其他版本数据集、非数据库文件以及默认业务路径一律拒绝，不覆盖用户记录。
2. 初始化沿用现有 v1–v5 迁移。业务记录在一项外层事务中构建；每次原 API 数据操作使用 savepoint，失败先撤销该操作。预期的 Agent 阻止案例仍按原业务规则写工具审计。
3. 通过真实 Cookie、CSRF、角色及门店上下文调用现有 API，不跳过 Pydantic、审核、双人盘点、幂等或来源校验。
4. 完成外键和完整性检查后提交，清除构建会话与登录限流资料，再用现有 SQLite backup API 独占创建目标文件。构建失败回滚并清理 staging；目标已存在时不能覆盖，发布竞争也由独占创建保护。
5. 失败记录写入目标文件名加 .import-errors.jsonl，只记录阶段、错误类型、回滚标识和时间，不记录密码、请求正文、Cookie 或账号散列。CLI 的校验错误会直接报出；参数检查失败不初始化数据库。

## 为什么有专用历史 fixture

Flow 只允许创建北京时间当天清单；正常 API 不接受任意历史操作日期。批准版本也不能直接改时间。本工具仅在一次性的离线构建进程中，把领域时钟依次设为相应模拟时刻，按原 API 创建和关闭记录。运营流单独按日回放，知识/培训流按其依赖顺序回放；每个流内部日期递增，依赖账号均在第 0 日创建。没有修改已批准正文或历史时间戳，也没有给线上 API 添加回溯时间参数。

仅首个管理员的建立沿用原 CLI 的引导 SQL；其他账号经创建及首次改密 API 建立。租户登记调用原 ensure_registry，SQL 仅调整合成主店/租户显示名称。demo_manifest 是此独立数据文件的身份与导入清单，不是正式库迁移。普通应用启动仍只初始化 Schema，不导入任何资料。

不要从运行中的 Web 服务调用这个离线工具：它在构建期间临时替换进程内连接/时钟适配器，用于单进程串行 fixture 回放。CLI 正常退出后适配器全部恢复，服务器使用正常时钟与连接。

## 重建与时间边界

每次新建一个不同的 demo 文件路径，例如 nightfall-demo-02.sqlite，重新设置演示密码，验证后手动选择新路径启动独立实例。本工具没有删除或覆盖命令。旧库可以保留供追溯；如需删除，由操作人先确认路径和数据身份。

以导入时北京时间所在日期为锚点，生成前 14 个日历营业日。Flow 业务日期就是创建清单时明确提交的北京时间日期；收吧可在次日 02:00 完成，仍保留原日期。本轮没有发明凌晨自动归属上一营业日的全局规则。销售/成本/审核时间统一存 UTC ISO8601，页面显示北京时间。

数据库使用真实时钟继续运行：未来配方会在标注日期实际生效，授权和计划也会实际到期。需要长期重演初始状态时创建新路径，不能假定演示时间永久冻结。

## 验收与复算

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip install -r requirements-e2e.lock
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.browsers"
.\.venv\Scripts\python.exe -m playwright install --no-shell chromium
.\.venv\Scripts\python.exe -m pytest --run-e2e tests/e2e -q --junitxml=test-results/g0.xml
.\.venv\Scripts\python.exe -m pytest --run-e2e tests/demo_e2e -q --junitxml=test-results/nightfall.xml
.\.venv\Scripts\python.exe tools/check_e2e_report.py test-results/g0.xml --profile all
.\.venv\Scripts\python.exe tools/check_e2e_report.py test-results/nightfall.xml --profile all --suite nightfall
~~~

两套浏览器测试使用自己生成的临时数据库，不读取上面人工创建的演示库，更不会读取默认业务库。报告可在 Insight 下载完整依据 JSON，然后独立复算：

~~~powershell
.\.venv\Scripts\python.exe -m app.report_math "D:\workspace\baros-insight-1.json"
~~~

详细演示路径见 DEMO_SCENARIOS.md；字段和来源见 DEMO_DATA_DICTIONARY.md；实际验收结果见 DEMO_ACCEPTANCE.md。
