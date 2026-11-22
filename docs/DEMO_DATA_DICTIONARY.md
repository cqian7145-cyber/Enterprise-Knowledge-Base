# NIGHTFALL 合成数据字典与来源

数据集标识nightfall-v1。所有数据均为SIMULATED DATA / 模拟数据，原创合成；未采集真实商家内部资料、真实顾客、真实订单或供应商报价。示例配方借用常见饮品名称只是为了检索演示，不声称采用任何官方配方或真实门店批准标准。

## 数据组成

| 范围 | 初始数量/含义 | 原始来源 |
| --- | --- | --- |
| 主店员工 | 18名，含管理员/主管/调酒/服务岗位 | app/demo_data.py EMPLOYEES |
| 其他账号 | 2名河畔店员工＋1名独立租户管理员 | app/demo_fixture.py bootstrap |
| 门店/租户 | 同一虚构集团2店，另有1个独立隔离租户/店 | 原有registry和HQ API |
| 知识系列 | 72条：26配方、20 SOP、20服务资料、权限/隔离样例、HQ两店采用、待审和停用样例 | knowledge_dataset及业务回放 |
| 知识版本 | 74条，含金汤力V1/V2/未来V3 | 原草稿/提交/发布API |
| 课程 | 8个课程系列、9个版本 | 原Academy API |
| 培训分配/测验/实操 | 14项分配、9次测验、5次观察 | 按业务故事顺序提交 |
| Flow | 14个日历营业日×3模板＝42份，2条异常/报修 | 原固定模板与日期规则 |
| 库存SKU/成本 | 32个SKU、32条历史价格（31个初价＋金酒新版价），1个SKU故意缺价 | SKUS＋成本录入API |
| 商品/配方映射 | 26个商品，V1全部映射并追加金汤力V2映射 | 原逐项SKU映射API |
| 销售 | 59行、8批：7日完整主报告＋1个缺证期间 | SIM-POS合成来源 |
| 盘点/报表 | 3份双人可信盘点，2份冻结报告 | 原盘点/复核/Insight API |
| 总部/Agent | 1模板分发2店；2计划，7待办（初始2关闭） | 原HQ/Agent审批和执行API |

实际数量也保存在导入输出counts和数据库demo_manifest中。演示操作后数量会改变，不能用初始数量冒充当前看板。

## 身份与权限

- users：username为可登录合成账号；name始终含“模拟”；role仍使用staff/manager/admin三个真实枚举，不发明“主调”权限枚举；岗位job为bartender或server，具体职务在姓名与演示角色中表达。
- stores/tenants：nf-downtown与nf-riverside同集团；isolation-lab属于独立租户。没有把第二家虚构店包装成第二家真实店验收。
- stations：main主吧台、terrace露台吧台、vip VIP吧台；知识jobs/stations和账号范围由原后端判断。VIP配方不对仅有main权限的人开放。
- store_grants：nf_admin有河畔店明确授权；nf_rotating曾获授权，随后通过撤销API失效。权限变化保留审计，没有手工删除历史。

## 知识与版本

| 字段/表 | 含义 |
| --- | --- |
| documents | 稳定知识系列，含title/kind/jobs/stations/aliases/risk；同系列范围不随版本修改 |
| revisions | 不可覆盖批准版本；state为draft/review/published/retired，version在系列内递增 |
| content.ingredients | name、十进制字符串amount、unit；当前示例用ml/g，和SKU基础维度一致 |
| content其他字段 | summary、steps、technique、glass、garnish、allergens；装饰“示意”不是库存计量行，也未伪装成已计成本 |
| content.allergens | “未核验，按实际标签与场所制度人工确认”，不写“保证无过敏原” |
| content.service | context/response/escalation_trigger/escalation_contact；场景另有practice_prompt与assessment_points |
| source | 模拟标识＋NF-EDITORIAL来源；HQ采用来源追加模板和版本编号 |
| created_by/approved_by | 实际由API操作者产生；普通知识由主调创建、管理员审核，历史不会手填不存在的审核人 |
| effective_at/approved_at | UTC时区ISO8601，先审核后在指定时间生效；未来版本不是当前有效标准 |
| knowledge_metadata | 有效负责人、复审日期、并发版本；特设缺负责人及逾期样例 |
| feedback/proposals/events | 原查询→引用版本→纠错→提案→草稿→审核生效→关闭反馈的完整链路；另保留1条未完成缺口求助 |

“批准”只指独立演示环境中的合成业务状态。消防、医疗、未成年人、醉酒、过敏内容仅为占位与人工升级，不是可执行的场所安全SOP。

## 培训字段

modules绑定明确revision_ids和3道题，pass_score=100；course_id连接同一课程的多个不可变版本。assignments记录分配人、assigned_at、due_at、best_score及superseded_by。attempts与practical_reviews保存全部考试和观察；reviewer必须不同于学员，理论通过后才能验收。旧课程资料被替代后即失效，历史分数与实操不删除，也不冒充当前资格。

系统当前持久状态仍为learning/practical/completed/stale，没有新增“浏览过但未提交”状态。未开始、进行中、理论未过等演示差异从有无attempt及分数反映。

## 日期口径

导入日为锚点，start_date为其北京时间日期前14日；0–13日产生Flow。第0日建立账号和资料；1日03:00为主报告期初，8日03:00为期末。7个完整销售批次对应（当日03:00，次日03:00]；销售时间必须在批次内。退单发生次日01:30仍属于前一日该来源批次。

Flow的business_date是创建清单时明确提交的北京时间日历日期；收吧可跨午夜完成，closed_at仍按实际下一日UTC时刻保存。它不是系统已有“凌晨自动归属上一营业日”的证明。全部时刻存UTC，页面显示Asia/Shanghai。

## 库存与金额

| 类型 | 存储/换算 |
| --- | --- |
| 基础数量 | quantity_milli：0.001个基础单位；如750ml为750000 |
| 包装单位 | 单SKU固定换算；GIN“瓶”=750ml，MINT“包”=100g，LIMEPIECE“箱”=50个；不跨ml/g维度猜测密度 |
| 采购单价 | price为人民币十进制字符串，按明确包装换算到cost_micro：每基础单位0.000001元 |
| 销售金额 | net_revenue_fen：人民币分，允许退款负数；合成含税实收，不代表真实收入 |
| 实际制作 | produced_quantity独立于quantity净销量；赠饮制作1但净收入0，退款制作0且不逆转已消耗原料 |
| 商品 | NF01–NF26绑定documents系列；销售根据当时批准与生效的历史配方选择revision_id |
| 原料映射 | ingredient_index逐项覆盖，绑定不可变recipe_map_id；历史销售消费行保留cost_id/cost_micro |
| 替代 | 唯一批准的V1金酒→备选金酒，比例1；仅NF-SUB-01显式使用，不自动替代全部销售 |
| 全量盘点 | 每次覆盖32SKU，包括明确0值；主调盘点、另一主管复核，不能自批 |
| 出入库 | 2瓶入库1500ml、调入750ml、报损100ml、调出250ml；均有唯一external_key |
| 理论结存 | 期初＋入库＋调入−报损−调出−理论制作消耗 |
| 差异 | 期末实盘−理论结存；GIN为-180ml，期末0.288元/ml估值-51.84元 |

金酒同时进入夜幕金汤力及夜航乌龙，180ml差异不证明某个单品/员工是原因。装饰、冰、租金、人工、运费及分摊不在材料成本行中；材料贡献额不能称净利润。

## 来源编号与复算

- NF-Dxx-PAID/DISCOUNT/GIFT/REFUND：某个合成营业来源日的销售行；没有真实支付交易、顾客姓名或手机号。
- NF-BATCH-xx / SIM-POS-Dxx：明确起止时间且不重叠的人工模拟POS来源；“完整”只表示构造数据的覆盖声明。
- SIM-PO-BASE / SIM-PO-PRICE-V2：合成采购成本依据，180→216元/瓶的生效变化。
- SIM-MOVE：4条合成库存原单；调拨的另一侧位于主吧台盘点范围外，未伪造未实现的采购订单或仓库系统。
- SIM-COUNT-OPEN/CLOSE/GAP：完整SKU原始盘点/复核证据。
- SIM-NF-OBS / SIM-FLOW / SIM-REPAIR：合成实操与运营证据，绝不是实际照片、维修工单或认证。
- Insight inputs/result/input_hash/result_hash：保存原始依据与stock-material-v1公式；导出JSON后可无数据库复算并检测篡改。

缺证报告单独使用后续期间：UNMAPPED-DEMO缺商品映射，季节果浆缺历史成本；报告如实返回null/数据缺口。装饰成本未纳入的边界单独说明，不通过“价格0”假装有完整成本。

## 演示身份元数据

仅独立演示库含demo_manifest单行表：dataset、payload。payload有label/simulated/anchor/start_date、账号角色目录、各故事记录编号、counts、独立构造的expected数量及sku_ids；不含密码、会话或密钥。/api/environment只公开模拟标记及数据集标识，不公开这些账号/故事详情。

业务API正常使用、审计、修改密码和查看页面；导入完成后所有构建会话已清除。后续RAG评估必须保留门店/岗位/吧台和版本过滤，不要直接把全库视为所有员工都能读取的语料。

## 合成检索基准

fixtures/nightfall_questions.json包含26个中文标题和24个英文别名共50条查询，声明synthetic_only:true及real_venue_acceptance:false。每条包含expected_title、岗位、吧台及期望状态；版本ID必须在查询时按当前有效版本核对，不把固定ID当永久答案。该文件用于可复现名称/别名回归，不是独立语义检索质量评估。
