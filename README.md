# SlideGuard

SlideGuard 是一款面向 Windows 的离线 PowerPoint 质量检查工具，用于在交付演示文稿前发现字体、字号、文本溢出、版面对齐、标题格式以及敏感或残留文本等问题。

程序仅处理 `.pptx` 文件，所有解析、检查、修复和报告导出均在本机完成，不需要登录、API Key 或互联网连接。原文件始终只读，自动修复结果会保存为新的 `.pptx` 文件。

## 主要功能

- 通过文件选择器或拖拽导入单个 `.pptx` 文件。
- 提供快速检查、标准检查和自定义检查三种模式。
- 检查空白页面、页面外元素、字体、字号、文本溢出、元素对齐、文字安全边距、标题一致性及敏感文本。
- 按严重程度、页面、规则、可修复性和处理状态筛选问题。
- 在本地页面预览中定位并高亮问题对象。
- 自动修复具有明确目标值的字体、字号、对齐和标题问题。
- 在主界面维护本地敏感词库。
- 导出离线 HTML 和 Excel 检查报告。
- 对解析失败的对象或页面进行隔离，不因局部失败中断整个扫描。

内置规则集版本为 `builtin-rules-v1.0`。完整需求和判断标准见 [PRD.md](PRD.md)，技术设计见 [IMPLEMENTATION.md](IMPLEMENTATION.md)。

## 直接使用

系统要求：

- Windows 10 22H2 x64 或 Windows 11 x64
- 无需安装 Office、Python、Java 或其他运行库
- 支持有效 `.pptx` 文件；不支持 `.ppt`、`.pptm`、加密、受保护或损坏的文件

使用发布包：

1. 解压 `SlideGuard.zip`，不要只从压缩包内直接运行程序。
2. 双击 `SlideGuard.exe`。
3. 程序会启动仅绑定 `127.0.0.1` 的本地服务，并自动打开浏览器操作界面。
4. 选择或拖入 `.pptx` 文件，然后选择扫描模式。
5. 查看问题、导出报告，或对支持自动修复的问题生成新文件。

程序数据位于解压目录下的 `data` 文件夹：

```text
data/
├── config/    # 本地敏感词库
├── logs/      # 本地日志
├── sessions/  # 当前任务的本地会话文件
└── temp/      # 临时文件
```

删除整个程序目录即可卸载。P0 版本不提供安装程序、自动更新或文件关联。

## 检查规则

| 规则 | 检查内容 | 自动修复 |
| --- | --- | --- |
| R002 | 疑似空白页面 | 否 |
| R003 | 页面外元素 | 否 |
| R004 | 非微软雅黑字体 | 是 |
| R005 | 字号过小或同层级字号不一致 | 条件支持 |
| R006 | 文本溢出 | 否 |
| R007 | 重复排列元素的对齐偏差 | 是 |
| R008 | 文字进入页面安全边距 | 否 |
| R009 | 标题样式、位置和超长标题 | 是 |
| R010 | 敏感及残留文本 | 否 |

快速检查执行 R002、R003、R004、R006、R009 和 R010；标准检查执行 R002—R010；自定义检查允许按需选择 R002—R010。只有完整完成的标准检查结果允许自动修复。

## 隐私与安全

- 不向外部网络发送 PPT、报告、使用统计或诊断数据。
- 仅允许浏览器界面与程序之间进行本机回环通信。
- 日志不记录 PPT 正文、图片或完整文件路径。
- 敏感词库保存在本机，不参与规则集版本管理，也不会随报告导出。
- 原文件不会被覆盖、重命名或删除；每次修复均生成新文件。
- 修复结果在落盘前会检查 ZIP 结构、必要 XML 和页面数量。

页面预览用于识别页面、定位对象和展示高亮，不代表 PowerPoint 中最终呈现效果的像素级还原。

## 本地开发

项目使用 Python 3.13 和 [uv](https://docs.astral.sh/uv/) 管理环境与依赖。

```powershell
git clone https://github.com/zhuxixun/SlideGuard2.git
cd SlideGuard2
uv sync
uv run slideguard
```

运行后，SlideGuard 会打开本地浏览器界面。也可以进行运行时自检：

```powershell
uv run slideguard --self-test
```

运行自动化测试：

```powershell
uv run pytest --basetemp=.test-tmp -p no:cacheprovider
```

前端使用原生 HTML、CSS 和 JavaScript，由 FastAPI 提供本地接口；PPTX 解析以 `python-pptx` 为主，并使用 `lxml` 补充处理底层 OOXML。项目不使用 PySide6 或 Electron。

## 构建发布包

在 Windows PowerShell 中执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

构建脚本会从当前 `PATH` 查找 `uv.exe`。运行构建前可通过 `uv --version` 确认 uv 已正确安装并可用。

脚本使用 PyInstaller 生成目录式应用，并创建：

```text
dist/SlideGuard/       # 解压后的可运行目录
dist/SlideGuard.zip    # 最终发布包
```

构建完成后建议执行：

```powershell
dist\SlideGuard\SlideGuard.exe --self-test
```

## 当前验收状态

代码、自动化测试、Windows 打包、真实 EXE 启动、本地 HTTP/WebSocket 链路、性能基准和 WPS 预验证均已完成。当前仍需在装有 Microsoft PowerPoint 的验收机上完成以下最终验收：

- Pillow 文本测量与 PowerPoint 实际排版的误差统计，95 分位绝对误差须不超过 2pt。
- 自动修复输出文件可由 PowerPoint 正常打开并保持语义和未修改内容。
- 约 200MB 有效 PPTX 的容量边界测试。
- 5 名目标用户的无指导易用性测试。

WPS 的预验证结果不能替代 Microsoft PowerPoint 终验。具体记录和操作步骤见 [PHASE0.md](PHASE0.md)。

## 项目结构

```text
src/slideguard/
├── application/  # 会话与应用状态
├── frontend/     # 浏览器界面
├── pptx/         # PPTX 导入、解析和预览
├── repair/       # 修复计划、执行与复检
├── reporting/    # HTML 和 Excel 报告
├── rules/        # R002—R010 检查规则
├── scan/         # 扫描编排、进度与取消
└── server/       # 本地 FastAPI 服务

tests/            # 单元、集成和性能测试
tools/            # 构建及验收辅助脚本
packaging/        # PyInstaller 配置
```
