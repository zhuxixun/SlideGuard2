# SlideGuard MVP 技术实现方案（评审稿 v0.3）

## 1. 方案结论

SlideGuard MVP 采用单进程 Python 桌面应用：

- **语言与运行时**：Python 3.13 x64；
- **本地服务**：FastAPI、Uvicorn；
- **用户界面**：HTML、CSS、原生 JavaScript，通过 Microsoft Edge 应用模式打开；
- **PPTX 常规解析**：python-pptx；
- **底层 XML 解析和最小修复**：lxml、zipfile；
- **页面预览**：SVG；
- **文字测量**：Pillow `ImageFont`，使用 Windows 系统微软雅黑字体；
- **图片处理**：Pillow；
- **HTML 报告**：内置 Jinja2 模板；
- **Excel 报告**：openpyxl；
- **绿色版发布**：PyInstaller `onedir`，产物压缩为 ZIP。

本方案不依赖 Microsoft Office，不使用商业 PPT 组件，不访问互联网。Python 仅监听 `127.0.0.1` 随机端口，浏览器负责展示和交互；PyInstaller 将 Python 解释器和全部依赖一起打包，用户无需安装 Python。

## 2. 设计原则

1. python-pptx 用于读取常规对象和构建业务模型，不把第三方对象直接传给前端或规则层。
2. 自动修复不直接调用 `Presentation.save()` 重写整份文件，而是使用 zipfile 和 lxml 对目标 XML 节点做最小修改。
3. 页面预览以“满足定位和高亮”为目标，由后端生成 SVG 描述，不承诺与 PowerPoint 像素级一致。
4. SmartArt、OLE、视频、复杂艺术字等未支持对象保留原始 XML 和关联文件，预览中使用占位框表示。
5. 文本溢出是最大技术风险，正式开发前必须先验证 Pillow/FreeType 与 PowerPoint 的排版误差。
6. 相同PPTX、规则版本、程序版本和敏感词库内容必须产生相同检测结果。

## 3. 总体架构

```text
┌──────────────────── Microsoft Edge / Browser ─────────────────────┐
│ HTML / CSS / JavaScript / SVG Preview / State / WebSocket Client  │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ HTTP + WebSocket
                               │ 127.0.0.1 + Session Token
┌────────────────────────── SlideGuard.exe ──────────────────────────┐
│ FastAPI / Uvicorn / Native File Dialog / Lifecycle Controller     │
├─────────────────────────────────────────────────────────────────────┤
│ Scan Orchestrator / Cancellation / Progress                        │
├──────────────┬────────────────┬──────────────┬─────────────────────┤
│ PPTX Parser  │ SVG Preview    │ Rule Engine  │ Report Exporter     │
│ python-pptx  │ Pillow Metrics │ R002-R010    │ HTML / XLSX         │
├──────────────┴────────────────┼──────────────┴─────────────────────┤
│ lxml + zipfile XML Reader / Minimal Patcher / Output Validator     │
└─────────────────────────────────────────────────────────────────────┘
```

扫描在线程池中执行，进度和问题数量通过 WebSocket 推送到浏览器。PPTX 解析对象不跨线程共享；取消使用协作式取消标记，规则和页面循环在安全边界检查取消状态。

## 4. 项目目录

```text
SlideGuard2/
  pyproject.toml
  uv.lock
  src/slideguard/
    __main__.py
    app.py
    server/
      app.py
      api.py
      websocket.py
      security.py
      lifecycle.py
      native_dialog.py
    frontend/
      index.html
      css/
      js/
      assets/
    application/
      scan_orchestrator.py
      repair_service.py
      report_service.py
      session.py
    domain/
      models.py
      issues.py
      rules.py
      fix_plan.py
    pptx/
      importer.py
      parser.py
      xml_reader.py
      effective_format.py
      object_locator.py
      patcher.py
      validator.py
    preview/
      svg_builder.py
      text_layout.py
      overlays.py
    rules/
      blank_slide.py
      off_slide.py
      font.py
      font_size.py
      text_overflow.py
      alignment.py
      text_margin.py
      title.py
      sensitive_text.py
    reporting/
      html_exporter.py
      excel_exporter.py
      templates/
    infrastructure/
      logging.py
      paths.py
      cleanup.py
  rules/
    builtin-rules-v1.0.json
  data/
    config/
      sensitive-terms.txt
  tests/
    unit/
    integration/
    golden/
    performance/
  test-data/
    generated/
    manifests/
    private/             # 不入库
  packaging/
    slideguard.spec
```

## 5. 核心数据模型

### 5.1 文档模型

```python
@dataclass(frozen=True)
class PresentationSnapshot:
    file_identity: FileIdentity
    slide_width_pt: float
    slide_height_pt: float
    slides: tuple[SlideSnapshot, ...]
    text_occurrences: tuple[TextOccurrence, ...]
    unsupported_objects: tuple[UnsupportedObject, ...]

@dataclass(frozen=True)
class SlideSnapshot:
    slide_index: int
    slide_part: str
    layout_part: str | None
    hidden: bool
    objects: tuple[SlideObject, ...]
    parse_status: ParseStatus

@dataclass(frozen=True)
class SlideObject:
    key: ObjectKey
    object_type: ObjectType
    bounds_pt: Rect
    rotation: float
    visible: bool
    from_master: bool
    placeholder_type: str | None
    text_frame: TextFrameSnapshot | None
    children: tuple["SlideObject", ...]

@dataclass(frozen=True)
class TextOccurrence:
    key: ObjectKey
    slide_index: int
    source: TextSource
    text: str
    visible: bool
    character_map: tuple[CharacterLocation, ...]
```

`text_occurrences` 统一保存页面、母版、版式、表格、图表和演讲者备注中的可识别文本。不可见或位于画布外的文本也保留，供R010检查；`character_map` 将合并后的文本索引映射回XML节点和字符位置。`PresentationSnapshot` 构建完成后不可修改。规则只读取 Snapshot，修复通过单独的 FixPlan 操作源 PPTX 的工作副本。

### 5.2 稳定对象标识

```text
{source-part-uri}:{source-kind}:{owner-id-or-path}:{table-cell}:{paragraph}:{run}
```

对象名称可能重复，不能作为唯一标识。普通shape的 owner ID 来自 Open XML 的 `cNvPr@id`；母版、版式、图表和备注等没有shape ID的文本使用其部件内稳定XML路径。表格单元格、段落和run在所有者内继续按稳定路径定位。

### 5.3 问题模型

```python
@dataclass(frozen=True)
class Issue:
    issue_id: str
    fact_key: str
    rule_id: str
    slide_index: int
    object_keys: tuple[ObjectKey, ...]
    severity: Severity
    status: IssueStatus
    actual_value: str
    expected_value: str
    standard_source: str
    evidence: str
    suggestion: str
    can_auto_fix: bool
    fix_proposal: FixProposal | None
    introduced_by_repair: bool = False
```

`fact_key = rule_id + slide + object_keys + property`，用于保证同一事实只报告一次。

## 6. PPTX 导入与资源防护

导入步骤：

1. 只接受单个 `.pptx`；
2. 检查文件大小不超过 200MB；
3. 检查 ZIP 文件头，不能只判断扩展名；
4. 检查 `[Content_Types].xml`、`ppt/presentation.xml` 和关系文件；
5. 拒绝 `.ppt`、`.pptm`、加密、受保护和损坏文件；
6. 限制 ZIP 条目数、单条目大小、总解压大小和压缩比，防止 ZIP Bomb；
7. XML 解析禁止 DTD 和外部实体；
8. 限制图片最大像素数，防止小文件解码后耗尽内存；
9. 计算内部 SHA-256，只用于当前会话识别，不展示、不写日志；
10. 关闭导入文件句柄，后续解析按需重新只读打开。

## 7. PPTX 解析

### 7.1 python-pptx 负责

- 幻灯片、母版和版式关系；
- 占位符类型；
- 文本框、形状、图片、组合对象；
- 表格和图表框；
- 对象 ID、位置、尺寸和旋转；
- 段落、run、字号和直接字体格式；
- 演讲者备注及其与页面的关系；
- SmartArt、OLE、媒体等未支持对象的识别。

### 7.2 lxml 补充负责

- 主题、母版、版式、占位符和 run 的格式继承；
- 最终生效字体和字号解析；
- python-pptx 未公开的 XML 属性；
- 精确字符路径和稳定对象定位；
- 母版、版式、图表及备注中的可识别文本抽取；
- 未支持对象及关联部件清单；
- 自动修复时的目标节点修改。

### 7.3 有效格式优先级

文字有效格式按以下顺序合并：

```text
run直接格式
  > 段落默认格式
  > 当前占位符格式
  > 版式占位符格式
  > 母版占位符格式
  > 主题字体
  > 内置规则默认值
```

每个最终值记录来源，供问题详情中的“标准来源”和“判断依据”展示。

### 7.4 敏感词库

- 发布包在 `data/config/sensitive-terms.txt` 提供空的UTF-8词库文件，但该文件只是内部存储，用户通过主UI维护词条，不需要直接访问或编辑文件。
- 后端提供读取和整体保存接口；前端完成搜索、逐条新增/编辑/删除和按行批量粘贴，保存前计算并展示新增、修改和删除数量。
- 后端保存时再次去除首尾空白、忽略空行并按完整字符串去重，不能只信任前端校验；使用同目录临时文件写入并刷新后原子替换，失败时保留原词库。
- 每次扫描开始时读取一次，去除词条行首尾空白并忽略空行，随后形成不可变内存快照；扫描过程中修改文件只影响下一次扫描。
- 词库内容的SHA-256只保存在当前Session内存中，用于结果一致性判断，不显示、不写日志、不写报告；报告只包含实际命中的词条和位置，不附带完整词库。
- 文件缺失、无法读取或不是有效UTF-8时，R010执行失败；空词库允许扫描，但前端和报告必须显示PRD规定的风险提示。
- 匹配器使用基于Unicode码点的字面量多模式匹配，不做文本归一化、正则表达式或大小写转换；输出通过 `character_map` 映射回对象和字符范围。

## 8. 浏览器 UI 与页面预览

### 8.1 本地服务启动

1. `SlideGuard.exe` 选择一个随机空闲端口，只绑定 `127.0.0.1`；
2. 生成一次性256位 Session Token；
3. 启动 Uvicorn，不开启 reload、访问日志或远程管理接口；
4. 优先使用 Microsoft Edge `--app` 模式打开页面，失败时回退系统默认浏览器；
5. Token 放在 URL fragment 中，JavaScript 读取后立即从地址栏移除，后续请求通过 `X-SlideGuard-Token` Header 发送；
6. WebSocket 使用 `Sec-WebSocket-Protocol` 携带并验证Token，因为浏览器WebSocket API不能添加自定义Header；服务端验证后只回显固定协议名，不把Token写入日志；
7. 页面关闭、WebSocket 断开且超过15秒无活动时关闭服务；页面“退出 SlideGuard”按钮可立即关闭。

### 8.2 本地文件对话框

普通 HTML 文件选择框不会提供真实路径，而且会把200MB文件通过 HTTP 再传一遍，因此不使用网页上传作为主流程。

- 浏览器调用 `/api/dialog/open-pptx`；
- Python 在专用对话框线程中创建并持有隐藏的 tkinter root，通过线程安全队列调用Windows原生打开对话框；所有Tk调用都在该线程完成；
- 后端获得真实路径后直接只读打开；
- 保存修复文件和报告使用对应的原生保存对话框；
- 对话框操作串行执行，扫描期间禁止再次打开文件；
- HTML 页面始终使用“打开文件”，不使用“上传”。

### 8.3 SVG 自绘范围

后端按 PPT 坐标生成 SVG：

- 页面背景；
- 普通文本框和占位符；
- 基础形状、填充、边框和旋转；
- 图片；
- 组合对象；
- 表格；
- 图表、SmartArt、OLE、视频、艺术字等复杂对象显示带类型名称的占位框；
- SVG 中所有文本和属性必须转义，不允许插入 PPTX 内的原始 XML 或 HTML。

预览用于页面识别、问题定位和高亮，不作为 PowerPoint 最终视觉效果的证明。

### 8.4 坐标体系

- PPTX 原始位置为 EMU；
- 业务模型统一转换为 pt；
- SVG `viewBox` 使用逻辑 pt 坐标；
- 浏览器使用 CSS 控制缩放和平移；
- 高亮 Overlay 使用独立 SVG 图层，与对象共用 viewBox，不修改 PPTX 和基础预览。

### 8.5 缓存

优先保留轻量 SVG，不为每页生成大尺寸 Bitmap。图片资源转换为 Session 内受控 URL，响应必须验证 Token；HTML 报告导出时再转为 Data URI。Session 结束后删除中间资源。

## 9. 文本排版与溢出

使用 Pillow `ImageFont`，字体固定从 Windows 系统取得微软雅黑：

1. 解析文本框有效宽高和内边距；
2. 解析段落、run、字号、加粗、行距、段前段后和文字方向；
3. 使用 `getlength()`、`getbbox()` 和 Unicode 断行规则按有效宽度逐行布局；
4. 合并所有行矩形形成实际文字边界；
5. 与文本框有效区域比较；
6. 使用 PRD 规定的 2pt 容差；
7. 自动缩小时计算实际使用字号；
8. 字体缺失、竖排、艺术字或公式无法可靠测量时返回“不可判定”。

Pillow/FreeType 与 PowerPoint 排版可能存在差异。Phase 0 必须使用 PowerPoint 人工标注样例统计误差；如果95分位误差超过2pt，必须回到PRD调整标准，不能在实现中静默放宽阈值。

## 10. 规则引擎

```python
class Rule(Protocol):
    rule_id: str
    scope: RuleScope
    can_auto_fix: bool

    def evaluate(
        self,
        context: RuleContext,
        cancel: CancellationToken,
    ) -> list[Issue]: ...
```

执行管线：

```text
导入验证
  -> 构建不可变 Snapshot
  -> 建立SVG预览模型和文字边界
  -> 单页规则 R002/R003/R004/R006/R008/R010
  -> 跨对象/跨页规则 R005/R007/R009
  -> Issue 去重
  -> 汇总与排序
```

快速检查：R002、R003、R004、R006、R009、R010。

标准检查：R002—R010。

自定义检查：按选择发布 R002—R010 的问题；内部可以复用公共计算，但未选择规则不得发布 Issue。

### 10.1 规则实现

| 规则 | 实现 | 自动修复 |
|---|---|---|
| R002 空白页面 | 排除背景、Logo、页脚、页码和不可见对象后，主体对象数为0 | 否 |
| R003 页面外元素 | 旋转后边界与页面矩形求交；部分越界文字委托R006 | 否 |
| R004 字体 | 合并有效字体不是微软雅黑的连续字符范围 | 是 |
| R005 字号 | 固定下限 + 同类样本70%主流值 | 有明确主流值时 |
| R006 文本溢出 | Pillow文字布局边界与有效文本框比较，容差2pt | 否 |
| R007 元素对齐 | 候选分组、参考线聚类、70%支持率 | 是 |
| R008 文字安全边距 | 实际文字边界与页面四侧3%区域比较 | 否 |
| R009 标题一致性 | 标题占位符、固定样式、版式参考线、冒号后缩小 | 是 |
| R010 敏感及残留文本 | 对全部可识别文本执行本地词库字面量匹配，定位字符范围 | 否 |

### 10.2 R007 对齐算法

1. 按对象类型分组；
2. 宽高差异均不超过10%的对象形成候选；
3. 至少3个对象才继续；
4. 判断横向或纵向主轴；
5. 排除阶梯、斜线、环形和自由布局；
6. 对六类边/中心参考线按3pt聚类；
7. 只保留支持率不低于70%的参考线；
8. 按支持数最多、总误差最小选择唯一参考线；
9. 偏差超过3pt的对象生成S3问题。

## 11. 扫描与取消

扫描状态：

```text
Idle -> Loading -> Ready -> Scanning
     -> Completed | Incomplete | Failed
```

阶段固定为：

1. 解析文件；
2. 生成页面预览；
3. 执行检查；
4. 汇总结果。

使用 `concurrent.futures.ThreadPoolExecutor` 执行页面解析和规则任务，通过 WebSocket 发送阶段、页码和问题计数。取消后：

- 立即停止调度新任务；
- 当前小任务在安全点结束；
- 3秒内浏览器页面进入 Incomplete；
- 已发现问题可以查看和导出；
- Incomplete Session 禁止自动修复。

规则或对象失败只产生 Diagnostic，不终止其他规则；失败范围不得显示为检查通过。

## 12. 自动修复

### 12.1 FixPlan

修复前先生成不可变计划：

```python
@dataclass(frozen=True)
class FixOperation:
    object_key: ObjectKey
    property_name: str
    original_value: str
    target_value: str
    xml_locator: XmlLocator

@dataclass(frozen=True)
class FixPlan:
    source_identity: FileIdentity
    rule_set_version: str
    operations: tuple[FixOperation, ...]
```

执行前重新验证源文件哈希、目标 XML 节点和原值；任一前置条件不成立时停止，不对错误版本文件应用旧计划。

### 12.2 修复白名单

- R004：字体改为微软雅黑；
- R005：在主流值明确时统一字号；
- R007：只修改对象 x/y，不改尺寸、旋转和层级；
- R009：修改标题字体、字号、加粗、颜色、位置；必要时拆分冒号后的 run 并缩小到不低于14pt。

R002、R003、R006、R008、R010 不支持自动修复。

### 12.3 最小 XML 修改

- 字体：修改目标 run 的 Latin、EastAsia、ComplexScript 字体声明；
- 字号：Open XML 使用百分之一 pt 写入；
- 标题颜色：写入 `srgbClr=C00000`；
- 加粗：写入明确的 bold 属性；
- 位置：只修改 shape transform 的 offset；
- 冒号拆分：复制原 run 的全部属性，只改变拆分后部分字号。

不调用 python-pptx 的整文件 `save()` 完成正式修复，避免无关 XML 被重写。

### 12.4 安全落盘

1. 在输出目录创建随机临时文件；
2. 复制源 PPTX；
3. 对工作副本应用 XML 补丁；
4. 验证 ZIP 和必要 XML；
5. 验证页数、关系和未支持部件哈希；
6. 使用 python-pptx 重新打开；
7. 验证通过后原子重命名为正式文件；
8. 失败或取消时删除临时文件；
9. 对输出执行完整标准检查；
10. 验收环境使用 PowerPoint 打开输出文件，生产程序不调用 PowerPoint。

## 13. Web UI 页面与状态

```text
首页
  -> 扫描设置
  -> 扫描中
  -> 结果首页
  -> 问题工作区
  -> 修复确认
  -> 修复中
  -> 修复前后对比
```

前端使用原生 ES Modules，不依赖 CDN，不要求 Node.js 运行时。问题工作区：

- 左侧为页面缩略图；
- 中间为 SVG 页面预览；
- 右侧为问题列表和问题详情；
- 红色表示异常对象；
- 蓝色表示参考对象和参考线；
- 切换问题只更新 SVG Overlay，不重新解析 PPTX。

扫描设置页显示敏感词库状态、有效词条数和“管理敏感词库”按钮，不显示内部文件路径。点击后在主UI内打开管理弹窗，支持搜索、逐条新增/编辑/删除和按行批量粘贴；关闭未保存的弹窗前二次确认。保存前展示新增、修改和删除数量，确认成功后刷新词条数。词库为空时显示风险提示；读取失败时仍允许发起扫描，但R010必须返回规则失败，标准检查结果必须标记为未完整完成。P0不提供词库文件导入导出、词条分类、权限管理或云同步。

只有 `Completed + Standard + 有可修复选中项` 时才允许进入修复确认。按钮状态由后端 Session 状态和前端路由守卫共同控制，后端必须再次校验，不能信任浏览器按钮状态。

### 13.1 API

```text
GET  /                         # 前端入口
POST /api/dialog/open-pptx     # 原生打开对话框
GET  /api/lexicon              # 读取词条、可用状态和数量
PUT  /api/lexicon              # 校验并原子保存完整词条列表
POST /api/scan                 # 开始扫描
POST /api/scan/cancel          # 取消扫描
GET  /api/session              # 当前Session摘要
GET  /api/slides/{index}       # SVG页面模型
GET  /api/issues               # 筛选、分页
POST /api/issues/{id}/ignore   # 忽略/取消忽略
POST /api/fix/plan             # 生成修复计划
POST /api/fix/apply            # 原生保存对话框后修复
POST /api/report/html          # 导出HTML
POST /api/report/excel         # 导出Excel
POST /api/exit                 # 退出
WS   /ws                       # 进度和状态事件
```

所有 `/api`、Session资源和 WebSocket 请求都必须验证 Token。接口不接收任意文件系统路径；文件路径只能由原生对话框产生，或来自当前 Session 已登记的路径。

词库接口不接收文件路径。`PUT /api/lexicon` 采用后端当前词库摘要作为并发前置条件；若打开管理弹窗后词库已被其他标签修改，则拒绝覆盖并要求刷新。保存请求和响应设置`Cache-Control: no-store`，词条不得进入访问日志或异常日志。

## 14. 报告

### 14.1 HTML

- Jinja2 模板作为程序资源随包发布；
- CSS、JavaScript 和缩略图全部内嵌；
- Jinja2 自动转义保持开启；
- 设置 Content Security Policy，禁止外部资源和网络连接；
- JavaScript 只做本地筛选和展开；
- 未完成报告在页首显示警告。
- R010命中项只输出实际命中的词条、来源和字符范围，不嵌入或附加完整敏感词库；空词库时显示风险提示。

### 14.2 Excel

- openpyxl 创建“扫描摘要”和“问题清单”；
- 所有来自 PPT 的内容显式写为文本；
- 以 `= + - @` 开头的文本前置单引号；
- 不创建公式、宏、图片或外部链接；
- 保存后重新打开工作簿验证结构。

## 15. 本地数据和隐私

```text
SlideGuard/
  SlideGuard.exe
  _internal/
  rules/
  data/
    config/
      sensitive-terms.txt
    logs/
    sessions/
    temp/
```

- Session 使用随机 ID，不使用 PPT 文件名；
- 日志只记录时间、版本、阶段、错误码、规则 ID 和对象类型；
- 不记录 PPT 正文、图片、完整路径或文件哈希；
- 不记录敏感词库内容、词库哈希或命中的文本上下文；
- 不使用 requests、httpx、WebEngine、更新器或遥测 SDK；
- Session 结束、取消和下次启动时清理过期临时文件；
- 删除前验证绝对路径必须位于 data 根目录；
- “清除日志”只操作 `data/logs`。

### 15.1 localhost 安全

- 服务器只绑定IPv4回环地址`127.0.0.1`，不绑定`0.0.0.0`、IPv6通配地址或局域网地址；
- 每次启动随机端口和随机Token；
- 校验`Host`只能是启动时确定的`127.0.0.1:{port}`；
- 校验`Origin`，不配置CORS，不接受第三方网页调用；
- 所有修改状态的接口只接受POST并验证Token；
- 设置`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`和严格CSP；
- 前端资源不得引用CDN、在线字体、远程图片或外部脚本；
- Uvicorn关闭访问日志，业务日志不记录Token、URL查询参数和文件路径；
- 同一进程只允许一个活动Session，第二个浏览器标签不能创建并发扫描任务。

## 16. 打包发布

使用 PyInstaller `onedir`：

```powershell
pyinstaller packaging/slideguard.spec --noconfirm --clean
```

选择 `onedir` 而不是 `onefile`：

- 不需要每次启动解压依赖；
- 更容易满足5秒冷启动；
- 不产生 PyInstaller `_MEI` 临时运行目录残留；
- 更符合 PRD 的绿色 ZIP 交付方式；
- 排查缺失 DLL、Tcl/Tk 原生对话框资源和前端静态文件更直接。

发布流程：

1. 锁定 Python 和所有依赖版本；
2. 在 Windows x64 构建；
3. 运行单元、集成、离线和冒烟测试；
4. 检查打包目录不存在开发文件、测试数据和外部联网组件；
5. 检查 `data/config/sensitive-terms.txt` 存在、为空且编码为UTF-8，不将内部测试词库打入发布包；
6. 生成依赖及许可证清单；
7. 压缩为 `SlideGuard-{version}-win-x64.zip`；
8. 在全新 Windows 10 22H2 和 Windows 11 环境解压验收。

## 17. 性能设计

- Uvicorn事件循环只处理短请求和WebSocket事件，CPU/文件任务进入线程池；
- PPTX 解压和解析在工作线程执行；
- 页面任务使用有界线程池，默认 `min(cpu_count - 1, 4)`；
- lxml Element 不跨线程共享；
- SVG页面模型按需创建并可回收；
- 图片使用缩略图，查看当前页时再解码较大版本；
- 大文件开始前检查临时磁盘空间；
- 性能日志只记录阶段耗时和内存，不记录文件信息。

初始性能预算：

| 阶段 | 50页快速 | 50页标准 |
|---|---:|---:|
| 导入与XML解析 | 3s | 3s |
| SVG与文字布局 | 9s | 9s |
| 规则执行 | 5s | 35s |
| 汇总与首屏 | 2s | 4s |
| 预留 | 1s | 9s |
| 合计 | 20s | 60s |

## 18. 测试策略

### 18.1 单元测试

- EMU、pt、SVG viewBox坐标转换；
- 主题和母版字体继承；
- 14pt、10pt、2pt、3pt、3%、70%边界；
- 字体别名和异常字符范围合并；
- 对齐候选分组和唯一参考线；
- Issue 去重和排序；
- FixPlan 冲突与前置条件；
- HTML 转义和 Excel 公式注入。
- 敏感词库增删改查、搜索、批量粘贴、未保存关闭确认、UTF-8读取、原子保存与失败回退、并发修改冲突、首尾空白、空行、字面量匹配、大小写差异、重复及重叠命中。

### 18.2 Golden PPTX

每条规则维护最小 PPTX 和 JSON 预期结果，不比较整个 ZIP 二进制，只比较 Issue、目标对象和关键 XML 节点。

### 18.3 修复回归

- 源文件字节不变；
- 只有白名单 XML 节点变化；
- 未支持部件哈希不变；
- 输出可由 zipfile、lxml、python-pptx 和 PowerPoint 打开；
- 目标问题消失；
- 不新增 S1/S2；
- 新增 S3/S4 明确标记。

### 18.4 性能与稳定性

- 冷启动3次；
- 50页快速和标准各3次；
- 199—200MB文件；
- 20份样例各扫描3次；
- 每个扫描阶段取消；
- 磁盘满、无权限、文件占用、损坏对象；
- 中文、空格、符号和长路径；
- 断网与联网结果一致；
- 峰值内存不超过2GB。
- R010覆盖正文、标题、表格、图表、母版/版式、备注、不可见及画布外文本，并覆盖空、缺失、损坏词库和图片文字不可检查状态。

另外覆盖localhost安全测试：无Token、错误Token、伪造Host、第三方Origin、重复POST、第二标签页、WebSocket断开、浏览器直接关闭和空闲超时。

## 19. 分阶段实施

### Phase 0：技术验证

只验证最难能力，不搭建完整业务 UI：

- python-pptx 与 lxml 对象 ID 映射；
- 主题/母版/版式后的有效字体；
- Pillow文字测量与PowerPoint人工结果误差；
- 基础SVG页面预览和高亮；
- FastAPI随机端口、Token、WebSocket和生命周期；
- 浏览器触发Windows原生打开/保存对话框；
- XML 最小修改字体、标题和位置；
- 未支持部件哈希保持不变；
- 50页解析、布局耗时和峰值内存；
- 全文本来源抽取、字符位置回映射和敏感词库不可变快照；
- PyInstaller onedir 在干净 Windows 环境运行。

退出条件：

- 支持对象稳定映射率100%；
- 文本布局误差满足PRD 2pt容差，或形成回到PRD评审的实测结论；
- 修复输出可由PowerPoint打开；
- 未支持部件不变；
- 性能具备达到20/60秒目标的可行性。
- Edge应用模式和默认浏览器回退可用，关闭页面后服务能自动退出。

### Phase 1：扫描内核

- 工程骨架和不可变 Snapshot；
- R001—R006、R008—R010；
- 规则配置、Issue 和基础测试；
- 扫描进度与取消。

### Phase 2：完整 Web UI 与标准检查

- R007 对齐；
- 快速、标准和自定义模式；
- 首页、扫描设置、扫描、结果和问题工作区；
- 报告导出。

### Phase 3：自动修复

- FixPlan；
- R004、R005、R007、R009；
- 安全落盘、复检和前后对比；
- 修复确认页面。

### Phase 4：发布与验收

- PyInstaller ZIP；
- Windows 10/11；
- 离线、性能、稳定性和易用性验收；
- 真实/脱敏测试集效果评估。

## 20. 主要风险

| 风险 | 应对 |
|---|---|
| Pillow与PowerPoint文本布局不同 | Phase 0人工样例测量；不满足2pt则回评PRD |
| 自绘预览无法还原复杂效果 | 明确预览定位用途；复杂对象显示占位框 |
| python-pptx 未公开完整继承格式 | lxml 解析底层XML并建立回归样例 |
| 自动修复破坏复杂对象 | 不整文件save；最小XML补丁；未支持部件哈希验证 |
| 对齐分组误判 | 保守条件、唯一参考线、Golden与真实集调优 |
| localhost接口被其他网页调用 | 随机Token、Host/Origin校验、无CORS、严格CSP |
| 浏览器关闭但后端残留 | WebSocket断开检测、15秒空闲超时、退出接口 |
| 浏览器差异影响交互 | Edge应用模式优先，默认浏览器只作回退并执行兼容测试 |
| PyInstaller遗漏Tcl/Tk或静态资源 | 固定spec文件，在干净Win10/11虚拟机冒烟测试 |
| 50页性能不达标 | SVG按需创建、图片延迟解码、有界线程池、阶段性能预算 |

## 21. 下一步

先实施 Phase 0 技术验证。Phase 0 通过后再创建完整Web UI，避免在文本溢出、SVG预览或浏览器生命周期不可行时返工。

## 22. 技术依据

- [python-pptx 文档](https://python-pptx.readthedocs.io/en/latest/)
- [python-pptx 形状支持](https://python-pptx.readthedocs.io/en/latest/user/understanding-shapes.html)
- [python-pptx 占位符](https://python-pptx.readthedocs.io/en/develop/user/placeholders-using.html)
- [PyInstaller 运行模式](https://pyinstaller.org/en/latest/operating-mode.html)
- [PyInstaller 使用说明](https://pyinstaller.org/en/stable/usage.html)
- [FastAPI WebSocket](https://fastapi.tiangolo.com/advanced/websockets/)
- [浏览器本地文件选择限制](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/file)
- [浏览器本地网络访问安全](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Local_network_access)
