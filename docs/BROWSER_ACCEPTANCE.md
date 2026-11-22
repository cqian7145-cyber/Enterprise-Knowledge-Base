# G0：真实 Chromium 浏览器验收

基线：main@4e86ad26e0d48d47c6cb8df60e35821f7b4f7126；实施分支：feat/g0-e2e。
执行日期：2026-11-21（北京时间）。本报告只记录实际执行的自动化验收，不代替店内真机与真实资料验收。

## 本地实测结果

| 检查 | 结果 | 实测范围 |
| --- | --- | --- |
| 原后端回归 + 新恢复演练 | 73 passed，132.36秒 | 原72项保持通过；新增1项旧库升级／恢复／原版本和培训证据校验 |
| Chromium桌面 | 12/12通过 | 1440×1000、真实网络请求、浏览器Cookie/CSRF |
| Chromium手机视口 | 12/12通过 | 390×844、touch/is_mobile；不是实际Android或iOS设备 |
| 完整浏览器批次 | 24 passed，178.31秒 | 不模拟DOM，不替换API响应；真实FastAPI子进程 + 每例独立SQLite |
| 浏览器引擎 | 159.0.8154.6 | Playwright 1.65.2，Chromium channel，headless |
| 本地操作系统 | Windows，10.0.26200 | 不推断其他设备同样通过 |

本轮没有改动业务API、数据库迁移或前端业务代码。首轮测试中出现的旧引用状态断言及AJAX等待问题属于测试同步问题：现行引用失效契约为404；浏览器已经达到的load-state networkidle不能用作后续AJAX提交完成依据。测试改为观察真实page request生命周期，并在关键处验证实际状态，不修改生产行为来迎合测试。

## 十二条验收路径

每条均在desktop和mobile各执行一次。

| 编号 | 覆盖 | 证据与边界 |
| --- | --- | --- |
| E01 | 登录→查45ml配方→提交有帮助；断网后恢复查询 | 真实点击和表单；检查页面宽度不溢出；offline是真实浏览器网络断开，非真实移动弱网 |
| E02 | 初始密码强制修改→旧会话401→新密码重登 | 真实Cookie和改密表单；初始账号不能浏览功能菜单 |
| E03 | 会话到期、账号停用→返回登录 | 过期通过临时测试库注入；停用通过受保护API；实际页面重新认证 |
| E04 | 同名配方按吧台／租户隔离 | 主吧45ml，露台99ml的合成资料；员工只见授权版本；跨范围403/404 |
| E05 | 未来版本尚未生效→到时切换 | 通过API安排未来版本，浏览器前后查询；实际等待生效时刻，不改系统时间 |
| E06 | 未知、提示注入、替代和过敏问题→保守拒答／求助 | 真实提问与提交主管求助；无依据不产生引用证据 |
| E07 | SOP草稿→提交→审核发布→员工可查 | 创建／审核／发布走真实UI；未发布不命中；无CSRF／外源写请求403 |
| E08 | 理论0分→100分→实操未通过→通过 | 全流程真实表单；理论通过不自动合格；两次实操记录都保留 |
| E09 | 旧引用不可打开、旧培训失效、新版重学 | 通过API安排更新和新课程；浏览器检查旧按钮禁用及新任务可用；404不泄露旧证据 |
| E10 | 交接四项、异常生成、指定接班确认、负责人处理、主管关闭 | 全流程真实UI；交班人不能替代指定接班人；关闭清单不自动关闭异常 |
| E11 | 目标店选择、权限撤销、403、返回本店 | 授权由API安排；门店切换和返回真实点击；验证目标店无本店配方，授权撤销即时生效 |
| E12 | 上新计划UI创建与人工审批→4个并发请求 | 浏览器fetch使用真实Cookie/CSRF并发调用固定工具；仅7条待办、1成功+3重放审计；没有自动发布或库存写入 |

API用于准备已知状态、注入受控故障及核对结果。上表没有把API安排的数据步骤误称为全部UI操作。测试主体通过实际Chromium操作，不使用现有Node VM DOM替身。

## 复现

常规回归（不需要浏览器依赖）：

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
~~~

显式开启真实浏览器验收（所有账号、资料和业务库均为一次性合成数据）：

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-e2e.lock
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.browsers"
.\.venv\Scripts\python.exe -m playwright install --no-shell chromium
.\.venv\Scripts\python.exe -X utf8 -m pytest --run-e2e tests/e2e -q --junitxml=test-results/e2e.xml
.\.venv\Scripts\python.exe tools/check_e2e_report.py test-results/e2e.xml --profile all
~~~

单独执行手机：加 --e2e-profile=mobile。每个测试有独立数据库和本地随机端口，不复用BAROS_DB或任何正式账号。缺浏览器、缺依赖、服务器无法启动都会失败，不以skip伪装通过。

## 失败与结果证据

- test-results/e2e/<UTC运行批次>/<用例>/：各测试角色的完整截图、observations.json、server.log；失败另外保留trace.zip。
- observations记录URL、复现命令、实际浏览器版本、console、pageerror、失败请求与结果；全部为合成测试数据。
- JUnit和覆盖检查要求E01–E12完整、无失败、无错误、无跳过；缺例和“全跳过绿灯”会被拒绝。
- 正常pytest默认不收集E2E；--run-e2e才运行。CI把Unit/DOM、Chromium desktop、Chromium mobile拆为三个独立检查。
- CI无论成功失败都上传对应test-results证据，保留7天。数据库、Cookie调试资料、运行截图和trace不提交公开Git树，也不使用真实门店资料。
- 查看失败trace：python -m playwright show-trace <trace.zip>。

## 未验收范围

没有真实OPPO、iPhone、Safari、吧台平板、虚拟键盘／横屏、3G限速、店内高峰或真实内容验收。手机视口通过不等于已支持所有手机。清单见DEVICE_CHECKLIST.md。

G0的自动化部分在本机已通过；公网TLS／反向代理、真实恢复容量及门店设备仍需按SECURITY_GATE.md现场验收。没有G1真实授权资料、真实50问或商业收益数据，本报告不声称已达到G1–G3。
