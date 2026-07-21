# SlideGuard Phase 0 验证记录

## 当前状态

| 验证项 | 状态 | 证据 |
|---|---|---|
| Python 3.13 与 uv 工程 | 通过 | Python 3.13.14、uv.lock、自动化测试 |
| localhost Token、Host、Origin | 自动化通过 | HTTP与WebSocket测试 |
| 浏览器断线及显式退出 | 自动化通过 | 生命周期测试；待实际浏览器冒烟 |
| PPTX文本部件抽取 | 探针通过 | 页面、版式、母版、图表、备注及页码关系测试 |
| R010本地词库 | 后端探针通过 | UTF-8、去重、原子保存、并发冲突及精确匹配测试 |
| SVG预览与高亮 | 基础探针通过 | 坐标、分层与转义测试；待真实复杂页面 |
| Open XML最小修复 | 基础探针通过 | 真实PPTX重开及非目标部件内容不变测试 |
| 微软雅黑文本测量 | WPS预验证中 | 已建立288 DPI Pillow基线和WPS COM测量；待PowerPoint人工终验 |
| PyInstaller onedir | 本机通过 | 48.23MB、82个文件、完整依赖EXE自检退出码0；待干净Win10/11冒烟 |
| 50页性能与2GB内存 | 未验证 | 待基准样例 |

## WPS文字测量预验证结果

- 环境：WPS演示12.1.0.26899，微软雅黑系统字体；
- 样本：8个，覆盖24pt中文、混合中英文、粗体、14pt正文及文本框宽度-3/-2/-1/0/+2pt边界；
- Pillow基准：288 DPI；
- 最大绝对误差：0.9pt；
- 8个样本均不超过2pt；
- 此结果只证明WPS预验证通过，仍需在PowerPoint验收机上完成最终95分位误差统计。

## PyInstaller本机预验证结果

- PyInstaller 6.21.0、Python 3.13.14，`onedir`窗口模式构建成功；
- 发布目录共82个文件、48.23MB；
- `SlideGuard.exe --self-test`确认前端资源、空敏感词库、微软雅黑字体、python-pptx、lxml、openpyxl和Jinja2均可用，退出码为0；
- 完整依赖包连续3次自检耗时为7166ms、3042ms、3115ms，中位数3115ms；
- 自检耗时不等同于“启动至首页可操作”，仍需实际浏览器启动计时；
- 构建日志仅提示可选`tzdata`未找到，当前Windows本地时区和离线功能不依赖该包；
- 尚需在干净Windows 10 22H2和Windows 11环境验证无需Python及额外运行库。

## PowerPoint文字测量对照

当前开发机未安装PowerPoint，不能在本机完成最终2pt误差验收。

本机WPS演示12.1.0.26899可通过`KWPP.Application` COM接口读取文本边界，用作预验证，但其结果不能替代PowerPoint终验。执行WPS预验证：

```powershell
powershell -ExecutionPolicy Bypass -File tools/measure_text_metric_probe_wps.ps1 `
  -PptxPath .\test-data\generated\text-metrics\text-metric-probe.pptx `
  -CsvPath .\test-data\generated\text-metrics\text-metric-probe.csv
```

在装有PowerPoint的验收机上执行：

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
uv run python tools/generate_text_metric_probe.py .\test-data\generated\text-metrics
```

打开生成的`text-metric-probe.pptx`，逐页测量或记录PowerPoint中的实际可见宽度，将结果填入同目录CSV的`powerpoint_visible_width_pt`、`absolute_error_pt`和`review_result`。至少统计最大误差和95分位绝对误差；95分位超过2pt时必须回到PRD评审，不得在代码中静默放宽阈值。
