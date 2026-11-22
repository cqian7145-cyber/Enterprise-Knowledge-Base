# G0：备份、升级与隔离恢复手册

本轮不改业务Schema。恢复门槛由tests/test_recovery_gate.py执行，全部使用pytest临时目录，不触碰data/baros.sqlite。

## 已完成的破坏性演练

1. 构造具有账号、已批准知识版本、培训模块、理论成绩、实操通过记录的纯虚构v0库。
2. 升级前用SQLite backup API创建独占新文件，保留真正未升级的回退源。
3. 对原隔离库执行当前增量迁移v1–v5，确认原批准正文、分数和实操说明未变，补建历史技能证据且不重复。
4. 在线备份升级库，再恢复到另一个全新路径；逐表对照documents/revisions/modules/assignments/attempts/practical_reviews/tenants/stores。
5. 重复初始化，执行integrity_check和foreign_key_check；运行真实API登录并验证当前知识和原培训资格。
6. 尝试将快照恢复到已有源路径，确认FileExistsError且源文件SHA-256未变，禁止覆盖保障有效。
7. 确认升级前快照仍未出现schema_migrations，原业务正文保持，可供原版本代码回退。

本机首次专项演练观测：备份0.0189秒、升级0.0232秒、恢复0.0209秒、整体验证0.7572秒。它们只适用于这份微型合成数据，不是生产RTO、RPO或容量承诺。每次运行的实际数据在test-results/recovery/drill.json，后续运行时长可能不同。

## 门店操作步骤

### 1. 记录当前版本并做独占新文件备份

在已授权的备份目录选择一个不存在的目标路径。运行中必须使用现有在线命令，不复制可能遗漏WAL的主库文件：

~~~powershell
.\.venv\Scripts\python.exe -m app.cli backup --destination "D:\workspace\baros-before-upgrade-UNIQUE.sqlite"
~~~

备份包含账号散列和门店资料，只能交给授权人员。本轮没有把任何真实备份上传到GitHub。

### 2. 在独立路径恢复并验证

~~~powershell
.\.venv\Scripts\python.exe -m app.cli restore --source "D:\workspace\baros-before-upgrade-UNIQUE.sqlite" --destination "D:\workspace\baros-restore-check-UNIQUE.sqlite"
~~~

目标必须不存在。该命令不切换线上服务，也不覆盖原库。另开终端，使用恢复文件启动隔离验证实例；使用全新浏览器上下文，避免同一主机不同端口共用Cookie：

~~~powershell
$env:BAROS_DB = 'D:\workspace\baros-restore-check-UNIQUE.sqlite'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
~~~

核对：数据库完整性与外键、租户和门店、管理员／员工登录、有效知识版本、培训成绩和技能证据、Flow/异常存量、库存及冻结报表。真实门店必须对自己的数据表核验，不能用本轮微型库的8表对照代替。

### 3. 执行切换或回退

- 验证成功后，在停写窗口切换目标服务到确认的数据库路径，记录代码提交、数据库路径、核对人和恢复耗时。
- 若迁移失败，不通过手工DROP字段回退；保留失败副本，用升级前快照恢复到新路径，匹配对应旧版代码验证后再切换。
- 停止隔离实例后，该终端的BAROS_DB配置不应被误用到其他部署。不要直接覆盖运行中的库。

## 复现自动演练

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recovery_gate.py -q
~~~

边界：已验证的是隔离v0→v5和恢复到新路径，不代表大容量、损坏磁盘、云主机失效、多实例恢复或真实连锁迁入回退已通过。
