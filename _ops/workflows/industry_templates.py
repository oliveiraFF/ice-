"""M05-E 多领域内容模板核心（纯函数，E1 独立模块）。

只做四件事：
1. 轻量目录：code/label/template_version，不返回模板正文；
2. 按 code 生成深拷贝完整快照；
3. 严格校验已有快照（历史版本可读取，不要求等于当前版本）；
4. 从完整快照渲染提示段（只用快照自身内容，不按 code 再取最新常量）。

模板只是提问、证据检查与表达约束：不生成事实、证据、资质、效果、需求强度或策略许可，
不分配来源引用号，也不能替代 basis/来源/策略确认。模块不读写文件、数据库、环境变量或网络，
不建立插件/注册中心框架，仅使用标准库 copy/json。

历史快照渲染必须使用其保存的完整内容：即使模板常量更新，旧快照的提示与导出仍逐字节不变。
"""
import copy
import json

DEFAULT_CODE = 'generic'

# 显示名顺序即目录顺序；三个旧 code（generic/local_service/physical_product）拼写保留。
CODES = ('generic', 'health_education', 'science_education', 'finance_education',
         'law_education', 'education_learning', 'technology_digital', 'culture_history',
         'career_skills', 'food_cooking', 'local_service', 'physical_product')

ARRAY_FIELDS = ('questions', 'evidence_checks', 'expression_guidelines', 'boundaries')
REQUIRED_FIELDS = ('code', 'label', 'template_version') + ARRAY_FIELDS
MAX_LABEL = 40
MAX_ITEMS = 8
MAX_ITEM_CHARS = 500

_MISSING = object()

TEMPLATES = {
    'generic': {
        'label': '通用内容',
        'version': 1,
        'questions': [
            '这条内容要回答的核心问题或主张是什么？',
            '已有依据是什么？来源身份、范围与时间是否明确？',
            '哪些部分仍是推断、经验或待核实？',
            '适用条件与不适用情形分别是什么？',
        ],
        'evidence_checks': [
            '把已知事实、他人说法、作者推断分开标注，不相互替代。',
            '检查来源身份、观察范围与时间；未提供就列为缺口。',
            '检查是否存在相反或冲突的资料，冲突是否保留。',
            '检查结论是否超出资料范围，是否缺少条件与例外。',
        ],
        'expression_guidelines': [
            '先给问题与结论范围，再给依据；不预设商业目的。',
            '用“已知 / 推断 / 未知”区分确定程度。',
            '避免绝对化表述；资料不足时明确留缺口。',
        ],
        'boundaries': [
            '不编造事实、数据、来源、机构或案例。',
            '不把模板本身当作证据或需求证明。',
            '不替用户确认策略、批准稿件或发布。',
        ],
    },
    'health_education': {
        'label': '健康与医学科普',
        'version': 1,
        'questions': [
            '观众最需要理解的健康概念或问题是什么？最容易混淆什么？',
            '这个说法属于资料明确结论、研究假设、作者推断，还是示例/类比？',
            '资料涉及哪些人群、年龄、基础疾病与使用条件？哪些人不能外推？',
            '资料给出的证据类型、发表或更新时间与研究范围是什么？',
            '还有哪些结论目前无法确认、需要核实？',
        ],
        'evidence_checks': [
            '来源身份、发布日期/版本、研究对象与样本范围是否提供？',
            '证据类型是否明确（指南/综述/随机试验/观察研究/动物或实验室研究/个案/专家意见）？未说明即列缺口，不自行评级。',
            '结论范围是否与资料一致：相关性是否被写成因果？相对变化是否缺少绝对发生率与分母？',
            '适用人群、剂量、阈值、禁忌与时效是否由资料给出？未给出不得补造。',
            '是否存在相反或冲突的资料？冲突是否保留而不是抹平？',
        ],
        'expression_guidelines': [
            '先说明观众应理解什么、容易混淆什么、资料实际支持什么。',
            '区分资料结论、研究假设、作者推断与示例类比；资料未明确时不称“权威证明/最新指南/临床证实”。',
            '可用“常见疑问 → 概念/机制 → 已有证据 → 条件与未知 → 核实问题”的结构。',
            '数值、分母与时间范围只使用资料给出的内容；类比要说明适用边界。',
            '资料不足时给待核实问题与结构草案，不写确定结论。',
        ],
        'boundaries': [
            '不提供诊断、处方、用药剂量或个体治疗建议；不替代就医。',
            '不虚构论文、机构、专家、指南、引用号或推荐。',
            '不把动物/实验室结果写成已对人有效，不把相关性写成因果。',
            '不默认引导私信、下单、购买课程/产品或就诊服务。',
            '模板本身不是证据，不能作为事实依据或需求证明。',
        ],
    },
    'science_education': {
        'label': '自然科学与生活原理',
        'version': 1,
        'questions': [
            '要解释的概念边界与常用定义是什么？',
            '机制链条中哪些环节有观察或实验支持，哪些只是模型假设？',
            '有哪些可观察现象、反例或失败条件？',
            '所用类比在哪些尺度或条件下会失效？',
            '实验前提（样本、对照、重复、测量方式）是什么？',
        ],
        'evidence_checks': [
            '区分假设、模型预测、实验结果与结论。',
            '检查实验条件与测量方式；缺少对照或重复时列为限制。',
            '检查观察现象与解释是否被混为一谈。',
            '检查数量级、单位与适用范围，避免跨尺度外推。',
        ],
        'expression_guidelines': [
            '先定义，再讲机制，再用可观察现象检验。',
            '类比只用于帮助理解，并标注失效边界。',
            '区分“已观察到”“模型推测”“尚未验证”。',
        ],
        'boundaries': [
            '不把未验证假说说成定论。',
            '不虚构实验、数据、期刊或研究者。',
            '不把实验室条件直接外推到日常生活。',
        ],
    },
    'finance_education': {
        'label': '财经知识科普',
        'version': 1,
        'questions': [
            '要解释的财经概念与计算口径是什么？',
            '计算涉及哪些假设、费用、税费与时间范围？',
            '统计口径、样本与数据来源是什么？',
            '风险与不确定性在哪里？历史表现能否代表未来？',
            '适用于什么资金条件与人群？哪些情形不适用？',
        ],
        'evidence_checks': [
            '数据来源、统计口径与时间范围是否明确？',
            '是否包含费用、税费、通胀或幸存者偏差？',
            '结论是描述、预测还是观点？是否被混用？',
            '是否把历史收益或个案当成可复制结果？',
        ],
        'expression_guidelines': [
            '用“假设 → 计算 → 结果 → 风险”的结构说明。',
            '数字必须带口径、时间与来源；区分事实、预测与观点。',
            '明确不确定性与可能的损失情形。',
        ],
        'boundaries': [
            '不承诺收益、稳赚或不亏。',
            '不提供个体投资建议或交易指令。',
            '不虚构收益率、案例或机构背书。',
            '不把科普内容当作持牌建议。',
        ],
    },
    'law_education': {
        'label': '法律知识科普',
        'version': 1,
        'questions': [
            '涉及哪个法域、什么时间生效的规则？',
            '规则来源是法律、司法解释、案例还是学理？',
            '适用主体、行为与情形是什么？有哪些例外？',
            '哪些是一般解释，哪些需要个案事实才能判断？',
            '事实前提缺失时，哪些结论不能下？',
        ],
        'evidence_checks': [
            '条文/案例的出处、版本与生效时间是否提供？',
            '适用主体与情形是否与资料一致？',
            '是否存在例外、修订或争议观点？',
            '是否把一般规则直接套成个案结论？',
        ],
        'expression_guidelines': [
            '先说明法域与时间，再讲规则，再讲条件与例外。',
            '区分一般解释与个案判断，标明事实前提。',
            '不确定时给核实路径，不装作确定答案。',
        ],
        'boundaries': [
            '不提供个案法律意见或胜诉承诺。',
            '不虚构法条、判例或官方解释。',
            '不把一地规则跨法域套用。',
            '不替代律师或司法机关的判断。',
        ],
    },
    'education_learning': {
        'label': '教育与学习',
        'version': 1,
        'questions': [
            '学习对象是谁？需要哪些先备知识？',
            '学完后能做出什么可验证的行为或作品？',
            '用什么示例、练习与反馈帮助理解？',
            '时间、工具与练习条件是什么？',
            '这套方法在哪些情况下可能无效？',
        ],
        'evidence_checks': [
            '方法来源与适用人群是否明确？',
            '是否有可观察的练习结果或对照证据？',
            '效果描述是否超出资料来源？',
            '是否把个例成绩当作普遍效果？',
        ],
        'expression_guidelines': [
            '用“目标 → 示例 → 练习 → 反馈”的结构。',
            '用可观察行为描述掌握程度，不用空泛口号。',
            '说明练习条件与常见卡点。',
        ],
        'boundaries': [
            '不保证提分、录取、证书或就业结果。',
            '不虚构教学效果数据或成功案例。',
            '不贬低个体能力或制造焦虑。',
            '不替代专业评估与个别辅导。',
        ],
    },
    'technology_digital': {
        'label': '科技与数码',
        'version': 1,
        'questions': [
            '涉及哪个产品/软件与具体版本？',
            '测试环境、设置与样本是什么？',
            '哪些是实测结果，哪些是厂商宣称或作者推断？',
            '对比口径是否一致（版本、设置、样本、测量方式）？',
            '适用场景与不适用场景分别是什么？',
        ],
        'evidence_checks': [
            '版本号、固件或配置是否记录？',
            '测试方法、环境与重复次数是否说明？',
            '宣称来源与实测数据是否分开？',
            '对比是否在同口径下进行？',
        ],
        'expression_guidelines': [
            '先给版本与条件，再给结果。',
            '区分实测、宣称与推断，并给比较口径。',
            '说明个体差异与使用场景限制。',
        ],
        'boundaries': [
            '不虚构跑分、续航、销量或评测数据。',
            '不把单机单次测试当作普遍结论。',
            '不承诺资料未支持的兼容性或性能。',
            '不引导非官方渠道或破解操作。',
        ],
    },
    'culture_history': {
        'label': '文化与历史',
        'version': 1,
        'questions': [
            '涉及什么时间、地域与文化范围？',
            '史料出处、版本与整理者是什么？',
            '哪些是史料记载，哪些是后世解释或演绎？',
            '学界或史料之间存在哪些争议与缺证？',
            '考古或实物证据能否支持该叙述？',
        ],
        'evidence_checks': [
            '区分一手史料、二手转述与研究解释。',
            '检查史料版本、校勘与成书时间。',
            '检查考古/实物证据与文本叙述是否对应。',
            '保留争议与缺证，不用单一叙述抹平。',
        ],
        'expression_guidelines': [
            '先给出处与年代，再叙述内容。',
            '区分“记载”“推断”“传说/影视演绎”。',
            '标注争议与证据强弱，不用确定语气包装推测。',
        ],
        'boundaries': [
            '不把影视、小说或网络演绎当作史实。',
            '不虚构史料、文物、年代或人物言论。',
            '不删改争议或选择性引用以支持结论。',
            '不做无根据的族源、血统或文明优劣断言。',
        ],
    },
    'career_skills': {
        'label': '职场与技能',
        'version': 1,
        'questions': [
            '要解决的任务情境、角色与目标是什么？',
            '可操作步骤与顺序是什么？',
            '需要哪些资源、权限与前置能力？',
            '有什么实践证据能说明方法有效？',
            '在哪些组织或条件下可能不适用？',
        ],
        'evidence_checks': [
            '方法来源与实践范围是否说明？',
            '是否有可验证的结果或反馈？',
            '适用岗位、行业与层级是否明确？',
            '失败条件与风险是否列出？',
        ],
        'expression_guidelines': [
            '用“情境 → 步骤 → 条件 → 验证”的结构。',
            '给具体动作与判断标准，不喊口号。',
            '说明资源前提与常见失败点。',
        ],
        'boundaries': [
            '不保证收入、就业、晋升或面试结果。',
            '不虚构薪资、成功案例或内推资源。',
            '不鼓励违规、造假或损害他人的操作。',
            '不把个案经验当作普遍规律。',
        ],
    },
    'food_cooking': {
        'label': '美食与烹饪',
        'version': 1,
        'questions': [
            '食材、工具与份量是什么？',
            '关键步骤与可观察结果（颜色、温度、质地）是什么？',
            '食安前提（加热、时间、储存）是否说明？',
            '哪些替代方案可行，哪些会失败？',
            '涉及哪些过敏原或特殊人群注意事项？',
        ],
        'evidence_checks': [
            '配方来源与份量口径是否明确？',
            '加热、储存与卫生条件是否说明？',
            '食材差异与替代边界是否交代？',
            '营养或健康说法是否有资料来源？',
        ],
        'expression_guidelines': [
            '用“份量 → 步骤 → 可观察标准 → 失败排查”的结构。',
            '替代方案标注适用边界。',
            '强调食安条件，不省略风险提示。',
        ],
        'boundaries': [
            '不把普通食物写成治疗、减肥或排毒手段。',
            '不虚构营养数据或健康功效。',
            '不忽略过敏原、食安与特殊人群风险。',
            '不宣称替代医疗建议。',
        ],
    },
    'local_service': {
        'label': '本地服务',
        'version': 1,
        'questions': [
            '服务范围、地域与不覆盖情形是什么？',
            '流程、周期与客户需要配合什么？',
            '报价由哪些部分构成？哪些条件会改变价格？',
            '案例是否真实可核验？有哪些限制？',
            '资质、责任边界与售后如何处理？',
        ],
        'evidence_checks': [
            '报价依据（人工/材料/上门/返工）是否拆分说明？',
            '案例来源、时间与可核验性是否交代？',
            '资质、保险与责任范围是否有依据？',
            '地域、资源与排期限制是否说明？',
        ],
        'expression_guidelines': [
            '用“范围 → 流程 → 报价构成 → 限制”的结构。',
            '案例标注来源与条件，不用他人案例冒充自有。',
            '把不确定项写成待确认，不写死承诺。',
        ],
        'boundaries': [
            '不虚构案例、资质、评价或合作方。',
            '不承诺效果、工期或价格除非有依据。',
            '不贬低同行或伪造对比。',
            '不把广告文案当作第三方证明。',
        ],
    },
    'physical_product': {
        'label': '实物产品',
        'version': 1,
        'questions': [
            '使用场景与目标人群是什么？',
            '规格、材质、型号与版本是什么？',
            '体验依据来自自测、他人反馈还是厂商宣称？',
            '对比条件是否一致（型号、环境、使用方法）？',
            '哪些情形不适用或有风险？',
        ],
        'evidence_checks': [
            '规格参数来源与版本是否明确？',
            '测试/体验条件与样本是否说明？',
            '对比口径是否一致？',
            '评价来源与样本量是否交代？',
        ],
        'expression_guidelines': [
            '用“场景 → 规格 → 体验依据 → 限制”的结构。',
            '区分实测、他人反馈与厂商宣称。',
            '说明个体差异与不适用情形。',
        ],
        'boundaries': [
            '不虚构销量、评价、效果或资质。',
            '不把单次体验当作普遍结论。',
            '不承诺绝对效果或无条件适用。',
            '不隐藏已知缺陷与不适用条件。',
        ],
    },
}


def validate_industry_code(value):
    """严格校验领域 code：字符串、精确匹配；不 strip、不 lower、不做别名猜测。"""
    if not isinstance(value, str):
        raise ValueError('内容领域必须是字符串 code')
    if value not in CODES:
        raise ValueError('未知的内容领域 code：%s' % value)
    return value


def catalog():
    """轻量目录：只返回 code/label/template_version，不返回模板正文。"""
    return [{'code': code, 'label': TEMPLATES[code]['label'],
             'template_version': TEMPLATES[code]['version']} for code in CODES]


def _string_list(value, name):
    if not isinstance(value, list):
        raise ValueError('%s 必须是字符串数组' % name)
    if not 1 <= len(value) <= MAX_ITEMS:
        raise ValueError('%s 必须有 1–%d 项' % (name, MAX_ITEMS))
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError('%s 的每一项必须是非空字符串' % name)
        if len(item) > MAX_ITEM_CHARS:
            raise ValueError('%s 的每一项超过 %d 码点上限' % (name, MAX_ITEM_CHARS))
        result.append(item)
    return result


def validate_snapshot(value):
    """严格校验已保存快照；额外键原样深拷贝保留，不按 code 回查当前常量。"""
    if not isinstance(value, dict):
        raise ValueError('内容领域模板快照必须是对象')
    code = validate_industry_code(value.get('code'))
    label = value.get('label')
    if not isinstance(label, str) or not label.strip():
        raise ValueError('模板显示名必须是非空字符串')
    if len(label) > MAX_LABEL:
        raise ValueError('模板显示名超过 %d 码点上限' % MAX_LABEL)
    version = value.get('template_version')
    if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
        raise ValueError('template_version 必须是正整数')
    snapshot = {'code': code, 'label': label, 'template_version': version}
    for key in ARRAY_FIELDS:
        snapshot[key] = _string_list(value.get(key), key)
    for key in value:
        if key not in REQUIRED_FIELDS:
            snapshot[key] = copy.deepcopy(value[key])
    return snapshot


def build_snapshot(code):
    """按 code 生成完整快照（深拷贝）；模板常量只在生成时读取。"""
    code = validate_industry_code(code)
    template = TEMPLATES[code]
    snapshot = {'code': code, 'label': template['label'],
                'template_version': template['version']}
    for key in ARRAY_FIELDS:
        snapshot[key] = list(template[key])
    return validate_snapshot(snapshot)


def resolve_code(explicit=_MISSING, inherited=None):
    """本次 code：显式选择 > 继承快照 code > 通用；显式错类型直接拒绝，不回退。"""
    if explicit is not _MISSING:
        return validate_industry_code(explicit)
    if inherited is not None:
        return validate_industry_code(inherited)
    return DEFAULT_CODE


def render_prompt(snapshot):
    """从完整快照渲染提示段：只用快照自身内容，不按 code 再取常量。"""
    snapshot = validate_snapshot(snapshot)
    lines = [
        '内容领域模板（保存时冻结：%s · %s · template_version v%d）' % (
            snapshot['code'], snapshot['label'], snapshot['template_version']),
        '- 本段只提供提问、证据检查与表达约束，不是事实、证据、资质、需求强度或策略许可；',
        '  不能替代 basis/来源/策略确认，也不分配引用号。',
        '',
        '需要询问的问题：',
    ]
    lines.extend('- %s' % item for item in snapshot['questions'])
    lines.extend(['', '证据检查：'])
    lines.extend('- %s' % item for item in snapshot['evidence_checks'])
    lines.extend(['', '表达要求：'])
    lines.extend('- %s' % item for item in snapshot['expression_guidelines'])
    lines.extend(['', '边界（不能从模板推出）：'])
    lines.extend('- %s' % item for item in snapshot['boundaries'])
    return '\n'.join(lines)


def to_json(snapshot):
    """规范化 JSON（紧凑、键排序），供 E2 计入 context 预算与落库。"""
    return json.dumps(validate_snapshot(snapshot), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))
