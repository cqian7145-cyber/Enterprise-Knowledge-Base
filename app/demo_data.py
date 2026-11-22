"""NIGHTFALL v1: original synthetic editorial data, never venue-approved standards."""
LABEL = 'SIMULATED DATA / 模拟数据'
DATASET = 'nightfall-v1'
STATIONS = ['main', 'terrace', 'vip']
JOBS = ['bartender', 'server']
# code, display name, base unit, package unit, package size, synthetic CNY/package.
SKUS = [
 ('GIN','干金酒','ml','瓶','750','180'),('RUM','白朗姆','ml','瓶','750','120'),
 ('VODKA','伏特加','ml','瓶','750','135'),('TEQUILA','龙舌兰','ml','瓶','750','210'),
 ('BOURBON','波本威士忌','ml','瓶','750','240'),('BRANDY','白兰地','ml','瓶','700','210'),
 ('VERMOUTH','甜味美思','ml','瓶','1000','130'),('DRYVERM','干味美思','ml','瓶','1000','130'),
 ('BITTER','苦味开胃酒','ml','瓶','750','150'),('ORANGE','橙味利口酒','ml','瓶','700','140'),
 ('COFFEE','咖啡利口酒','ml','瓶','700','126'),('SPARKLING','起泡葡萄酒','ml','瓶','750','90'),
 ('TONIC','汤力水','ml','瓶','200','4'),('SODA','苏打水','ml','瓶','330','3.3'),
 ('GINGER','姜汁汽水','ml','瓶','200','5'),('LIME','青柠汁','ml','盒','1000','40'),
 ('LEMON','柠檬汁','ml','盒','1000','35'),('SYRUP','糖浆','ml','瓶','1000','30'),
 ('HONEY','蜂蜜糖浆','ml','瓶','1000','50'),('TEA','乌龙茶液','ml','盒','1000','18'),
 ('ESPRESSO','咖啡液','ml','盒','1000','60'),('PINEAPPLE','菠萝汁','ml','盒','1000','22'),
 ('CRANBERRY','蔓越莓汁','ml','盒','1000','24'),('GRAPEFRUIT','西柚汁','ml','盒','1000','28'),
 ('COCONUT','椰乳','ml','盒','1000','32'),('APPLE','苹果汁','ml','盒','1000','20'),
 ('MINT','薄荷叶','g','包','100','12'),('SALT','盐','g','包','500','5'),
 ('LIMEPIECE','青柠整果','个','箱','50','100'),('GIN_ALT','备选金酒','ml','瓶','750','165'),
 ('OSMANTHUS','桂花糖浆','ml','瓶','1000','65'),('SEASONAL','季节试制果浆（缺价演示）','ml','瓶','1000',None)]
# title, English alias, technique, glass, garnish, ingredient code/amount/unit.
RECIPES = [
 ('夜幕金汤力','Nightfall G&T','兑和','高球杯','青柠片（仅展示）',[('GIN',45,'ml'),('TONIC',120,'ml')]),
 ('经典黛绮莉','Daiquiri','摇和','碟形杯','无',[('RUM',50,'ml'),('LIME',25,'ml'),('SYRUP',15,'ml')]),
 ('经典玛格丽特','Margarita','摇和','玛格丽特杯','盐口示意',[('TEQUILA',45,'ml'),('ORANGE',20,'ml'),('LIME',25,'ml')]),
 ('经典内格罗尼','Negroni','搅拌','古典杯','橙皮示意',[('GIN',30,'ml'),('VERMOUTH',30,'ml'),('BITTER',30,'ml')]),
 ('经典马天尼','Dry Martini','搅拌','马天尼杯','柠檬皮示意',[('GIN',60,'ml'),('DRYVERM',10,'ml')]),
 ('经典莫吉托','Mojito','兑和','高球杯','薄荷',[('RUM',45,'ml'),('LIME',25,'ml'),('SYRUP',15,'ml'),('SODA',90,'ml'),('MINT',2,'g')]),
 ('经典威士忌酸','Whiskey Sour','摇和','古典杯','柠檬皮',[('BOURBON',50,'ml'),('LEMON',25,'ml'),('SYRUP',20,'ml')]),
 ('经典边车','Sidecar','摇和','碟形杯','橙皮',[('BRANDY',45,'ml'),('ORANGE',20,'ml'),('LEMON',20,'ml')]),
 ('浓缩咖啡马天尼','Espresso Martini','摇和','马天尼杯','咖啡豆示意',[('VODKA',40,'ml'),('COFFEE',20,'ml'),('ESPRESSO',30,'ml')]),
 ('经典自由古巴变奏','Rum Ginger','兑和','高球杯','青柠片',[('RUM',45,'ml'),('GINGER',120,'ml'),('LIME',10,'ml')]),
 ('都会红莓','Cosmopolitan Demo','摇和','马天尼杯','橙皮',[('VODKA',40,'ml'),('ORANGE',15,'ml'),('CRANBERRY',30,'ml'),('LIME',15,'ml')]),
 ('午后贝里尼','Peachless Bellini Demo','兑和','香槟杯','无',[('SPARKLING',90,'ml'),('APPLE',45,'ml')]),
 ('夜航乌龙','Oolong Night Flight','摇和','古典杯','茶叶示意',[('GIN',40,'ml'),('TEA',60,'ml'),('HONEY',15,'ml'),('LEMON',15,'ml')]),
 ('暮色桂花','Osmanthus Dusk','摇和','碟形杯','桂花示意',[('VODKA',40,'ml'),('OSMANTHUS',20,'ml'),('LEMON',20,'ml'),('TEA',30,'ml')]),
 ('霓虹西柚','Neon Grapefruit','兑和','高球杯','西柚片示意',[('TEQUILA',35,'ml'),('GRAPEFRUIT',90,'ml'),('SODA',45,'ml')]),
 ('暗巷咖啡','Backstreet Coffee','搅拌','古典杯','无',[('BOURBON',40,'ml'),('COFFEE',20,'ml'),('ESPRESSO',20,'ml')]),
 ('露台晚风','Terrace Breeze','兑和','高球杯','薄荷',[('RUM',30,'ml'),('PINEAPPLE',90,'ml'),('SODA',60,'ml')]),
 ('VIP 琥珀','VIP Amber','搅拌','古典杯','橙皮',[('BOURBON',45,'ml'),('VERMOUTH',20,'ml'),('HONEY',10,'ml')]),
 ('零度青柠','Zero Lime','兑和','高球杯','青柠片',[('LIME',25,'ml'),('SYRUP',15,'ml'),('SODA',150,'ml')]),
 ('零度乌龙','Zero Oolong','兑和','高球杯','无',[('TEA',100,'ml'),('LEMON',15,'ml'),('HONEY',15,'ml'),('SODA',60,'ml')]),
 ('椰风菠萝','Coconut Pineapple Zero','摇和','高球杯','菠萝片示意',[('COCONUT',45,'ml'),('PINEAPPLE',120,'ml'),('LIME',10,'ml')]),
 ('红莓气泡','Cranberry Fizz Zero','兑和','高球杯','薄荷',[('CRANBERRY',100,'ml'),('SODA',90,'ml'),('LIME',10,'ml')]),
 ('低度橙光','Low ABV Orange','兑和','葡萄酒杯','橙片示意',[('VERMOUTH',30,'ml'),('TONIC',120,'ml')]),
 ('低度绯红','Low ABV Scarlet','兑和','葡萄酒杯','橙片示意',[('BITTER',25,'ml'),('GRAPEFRUIT',90,'ml'),('SODA',90,'ml')]),
 ('冬日桂花','Winter Osmanthus','摇和','古典杯','桂花示意',[('BOURBON',35,'ml'),('OSMANTHUS',20,'ml'),('APPLE',60,'ml')]),
 ('季节果园试制','Seasonal Orchard Trial','摇和','碟形杯','无',[('SEASONAL',30,'ml'),('LEMON',20,'ml'),('SODA',90,'ml')])]
SOPS = [
 ('开吧岗位准备','确认当班分工与当前酒单','核对器具位置并记录未完成准备'),
 ('收吧交付','按模拟清单记录工作台状态','遗留事项写明负责人并交接'),
 ('交接班四项确认','逐项说明营业、原料、设备和待办','请指定接班人确认收到'),
 ('杯具清洗交接','查阅实际场所批准的清洗指引（演示占位）','异常杯具暂停流转并交主管'),
 ('工具清洁交接','核对工具编号和演示检查表','实际清洁标准须由场所审核'),
 ('备料批次标签','记录批次、备料人及有效标签','未核实标签的原料交主管确认'),
 ('酒单更新核对','比对当前生效知识版本与展示酒单','旧物料收回并记录经手人'),
 ('原料验收登记','逐项记录模拟到货SKU与包装数量','数量或标签不符交主管确认'),
 ('设备报修登记','记录设备编号、异常现象和影响','登记负责人并等待人工安排'),
 ('双人盘点','覆盖全部SKU并保留原始记录','另一位主管逐项复核后批准'),
 ('赠饮登记','确认主管批准并登记制作份数','赠饮零收入仍记录原料消耗'),
 ('特殊口味请求','记录请求并查询已批准配方','未经批准不得自行替换原料'),
 ('冰块备货交接','记录演示备货数量和负责人','实际食品安全流程待场所审核'),
 ('仓储调拨记录','登记调出调入单号和基础单位','核对另一吧台接收证据'),
 ('报损登记','记录SKU、数量、原因及证据','请主管核对，不能用报损掩盖差异'),
 ('采购价格留档','记录采购单价单位与生效时间','新价格不能覆盖历史销售成本'),
 ('销售来源核对','逐日核对模拟POS唯一行号','退款、赠饮与制作份数分开记录'),
 ('配方版本发布','主调提交变更原因和差异','主管审批并安排生效与重学'),
 ('知识纠错提案','保留原查询和引用版本','反馈转提案后等待新版实际生效'),
 ('高峰岗位协作','按主管确认的分工交接待办','记录队列变化，不虚构客流预测')]
SERVICES = [
 ('顾客迎接','顾客初次到店询问座位','晚上好，我先为您确认当班可安排的座位。'),
 ('口味偏好询问','顾客希望获得饮品推荐','您更喜欢清爽、酸甜还是偏苦的口味？我会按有效酒单介绍。'),
 ('饮品推荐','顾客询问酒单中的选择','我可以介绍配方卡标注的原料与风格，请以当前酒单为准。'),
 ('无酒精选项说明','顾客询问无酒精选项','可先查看零度系列；实际原料含酒情况仍需主管核对标签。'),
 ('低度饮品说明','顾客询问低酒精选项','可以介绍低度系列的配方，不能保证具体酒精含量或安全效果。'),
 ('优惠规则解释','顾客询问演示活动价格','我会核对当班已批准活动规则，不做未授权的优惠承诺。'),
 ('等候时间异议','顾客对等待时间提出异议','感谢提醒，我先核对制作进度，再请当班主管向您说明。'),
 ('口味不符异议','顾客认为饮品风味不符预期','我先记录您反馈的具体风味，请主管核对配方与订单后处理。'),
 ('支付异常','顾客反映付款结果不明确','请先保留支付凭证，由主管核对订单状态，避免重复付款。'),
 ('会员规则说明','顾客询问演示会员权益','本环境没有真实会员系统，权益解释请交主管核对已批准说明。'),
 ('退款诉求升级','顾客提出退款或赔付诉求','我会请当班主管核对模拟订单与规则后回复，不直接承诺退款。'),
 ('客诉升级卡','顾客持续不满或事项超出岗位权限','我已记录您的诉求，立即联系当班主管处理。'),
 ('未成年人核验占位','出现年龄核验相关请求','演示占位：暂停此项办理，交主管按场所已审核制度处理。'),
 ('过敏核验占位','顾客提出过敏或原料安全问题','演示占位：不作安全保证，联系主管核对实际标签和场所制度。'),
 ('醉酒升级占位','出现疑似醉酒或不适情况','演示占位：立即联系现场负责人，按场所审核制度处理。'),
 ('消防流程占位','出现消防相关询问或情景','演示占位：联系现场负责人；本卡不提供可执行消防操作指令。'),
 ('急救流程占位','出现医疗或急救相关情景','演示占位：立即联系现场负责人及当地专业救助；本卡不提供急救操作指令。'),
 ('双语菜单沟通','顾客需要英文饮品名称','我会展示当前配方卡上的中英文名称并请您确认选择。'),
 ('服务沟通演练','新人练习确认口味与复述订单','先复述顾客请求，再查询有效标准；不保存顾客身份资料。'),
 ('投诉沟通演练','新人练习记录异议与主管升级','只记录模拟诉求和订单号，超出权限交当班主管。')]
EMPLOYEES = [
 ('nf_admin','模拟·林店长','admin','bartender',STATIONS),
 ('nf_lead','模拟·周主调','manager','bartender',STATIONS),
 ('nf_supervisor','模拟·沈主管','manager','bartender',STATIONS),
 ('nf_servicelead','模拟·乔领班','manager','server',STATIONS),
 ('nf_mentor','模拟·顾带教','manager','bartender',STATIONS),
 ('nf_new','模拟·陆新人','staff','bartender',['main']),
 ('nf_retry','模拟·唐待复练','staff','bartender',['main']),
 ('nf_theory','模拟·许待实操','staff','bartender',['main']),
 ('nf_failed','模拟·孟理论未过','staff','bartender',['main']),
 ('nf_learning','模拟·江学习中','staff','bartender',['main']),
 ('nf_idle','模拟·叶未开始','staff','bartender',['main']),
 ('nf_bar1','模拟·程调酒师','staff','bartender',['main','terrace']),
 ('nf_bar2','模拟·白调酒师','staff','bartender',STATIONS),
 ('nf_terrace','模拟·贺露台','staff','bartender',['terrace']),
 ('nf_vip','模拟·蓝VIP','staff','bartender',['vip']),
 ('nf_server1','模拟·秦服务员','staff','server',['main','terrace']),
 ('nf_server2','模拟·夏服务员','staff','server',STATIONS),
 ('nf_rotating','模拟·余轮岗','staff','bartender',['main','terrace'])]


def knowledge_dataset():
    names={s[0]:s[1] for s in SKUS}
    items=[]
    for i,(title,en,technique,glass,garnish,ingredients) in enumerate(RECIPES):
        items.append(dict(title=title,kind='recipe',aliases=[en],jobs=['bartender'],stations=['vip'] if i==17 else STATIONS,
          content=dict(summary=LABEL+'；原创示例配方，非真实门店批准标准。'+('无酒精选项仍须核对实际标签。' if 18<=i<=21 else ''),
            ingredients=[dict(name=names[c],amount=str(a),unit=u) for c,a,u in ingredients],technique=technique,glass=glass,garnish=garnish,
            allergens=['未核验：全部原料须按实际商品标签与场所制度人工确认；不得作安全保证'],
            steps=['在独立演示环境核对本卡版本和模拟原料。','按结构化用量演示计量与'+technique+'。','核对杯型与装饰，交模拟带教复核；不得作为真实出品许可。'])))
    for title,a,b in SOPS:
        items.append(dict(title=title,kind='sop',aliases=[],jobs=JOBS,stations=STATIONS,content=dict(summary=LABEL+'；岗位流程演示，实际场所须另行审核。',steps=[a,b])))
    for i,(title,context,response) in enumerate(SERVICES):
        kind='service_scenario' if i>=18 else 'complaint_card' if 10<=i<=16 else 'service_script'
        service=dict(context=context,response=response,escalation_trigger='超出岗位权限、存在不确定性或顾客持续不满',escalation_contact='当班主管／现场负责人')
        if kind=='service_scenario':service.update(practice_prompt='两人角色扮演：'+context,assessment_points=['复述请求并核对有效资料','不作未经授权承诺','能正确联系主管'])
        items.append(dict(title=title,kind=kind,risk=10<=i<=16,aliases=[],jobs=JOBS,stations=STATIONS,content=dict(summary=LABEL+'；非真实安全操作标准。',steps=['查阅当前模拟标准并复述请求','超出权限或安全事项立即人工升级'],service=service)))
    return items
