# Apple Silicon 本地适配阶段记录（未完成 Mac 交付）

用户确认：仅 M 系列；无 Mac 电脑；先用 GitHub macOS 构建；只使用免费额度，核实禁止超额扣费后才执行。
起点 main：85f8126。独立工作树：工作树/ice-macos-arm64；分支：feat/macos-arm64。

## 已准备的最小适配

- 桌面入口按系统选择 Cocoa/WKWebView 或原有 EdgeChromium；Mac 用 fcntl 进程锁。
- Mac 数据固定放到 `~/Library/Application Support/ICEOps/data`，视频缓存为同级 downloads，应用包只读。
- Mac 仅使用 keyring 25.7.0 的原生 macOS Keychain 后端，密钥不进入命令行或本地明文文件。本地文件只存随机钥匙串标识；拒绝访问时失败，不回退其他后端。
- 系统资料目录打开和 ASR 路径适配；Windows 仍要求 .exe，Mac 要求本机 ffmpeg、whisper-cli 及执行权限。没有附带 ASR 程序或模型。
- Mac 专用打包脚本只允许原生 Darwin/arm64、干净 Git 提交、源码外新目录；包括现有完整工作流和初始化模板，产出 .app/.dmg、输入哈希、产物哈希、依赖清单。临时签名，不含 Developer ID、公证或私人资料。
- 云端脚本准备原生窗口存在检查、真实系统钥匙串保存/重开/清除、隔离 workspace 创建和备份、只读 DMG 启动回读以及应用包未变校验。这些尚未执行；窗口存在检查也不等同视觉验收。

## 已执行验证

- 改代码前新增平台契约复现：8 项报错、1 项原生环境跳过，确认 Windows 专用入口缺少 Mac 行为。
- 首轮全集：97 项无失败、5 项跳过。
- 增补构建拒绝/清单测试后全集：99 项无失败、5 项跳过；最后将双进程互斥测试改为当前真实 Windows 也执行，11 项平台专项全部通过；最终全集重跑99项无失败、4项既有环境跳过。
- Windows 真实本地服务/Chrome 新客户表单创建、两主题及320/390/768/1280宽度、备份下载、本地合成视频导入、策略确认门禁、保存关闭重开通过。视频为明确合成的技术素材，供应商请求 0。
- 首次 UI 验收调用漏传测试工具 ICE_FFMPEG，测试脚本报错；原日志保留。补齐环境变量后在全新目录 r2 重跑通过，未修改产品绕过检查。
- Python 语法检查、工作流 YAML 结构解析与 git diff --check 通过。
- 本机证据目录：E:/leida-build/macos-arm64-20261030/。包含 unit-stage1.log、unit-final.log、platform-contracts.log、windows-source-ui.log、windows-source-ui-r2.log 和 windows-source-ui-r2/result.json/截图。

## 费用与启动门禁

已通过 GitHub 只读 API 确认 oliveiraFF/ice- 为私有仓库；Actions 开启、允许 Actions，当前凭据有仓库管理/推送权限，查询时工作流和历史运行均为 0。
账单用量与预算 API 返回404，当前凭据没有可见账单权限，不能据此认为额度为0、免费额度充足或已经禁止超额消费。

官方当前说明：私有库的标准 Mac 计算使用账户内含额度，超出后标价 US$0.062/分钟；产物存储另有额度及费用。30分钟超时限制不是“免费保证”。
参考：[GitHub计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)、[标准ARM64机型](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)、[预算停止设置](https://docs.github.com/en/billing/how-tos/set-up-budgets)。

真正启动前必须核实适用于此仓库的 Actions 付费预算为 US$0 且启用“Stop usage when budget limit is reached”，覆盖计算与相关存储；仅告警不算停止保护。
不能读取设置时，需用户在 https://github.com/settings/billing/budgets 核实实际状态；不得自动提高预算、购买额度或把仓库改为公开。

工作流不响应普通提交/PR/定时事件。仅手动 workflow_dispatch 或维护者显式推送 `ice-macos-test-*` 构建标签可触发，而且仓库变量 `ICE_MACOS_FREE_BILLING_VERIFIED` 必须为 true。变量只是核实状态记录，不能代替账户账单保护。
标签触发用于在不提前合入 main 的情况下测试候选提交；标签和变量本轮均未创建。只有有意识地创建标签才表示启动本次构建。
只用标准 macos-14 ARM64，单次超时30分钟、不自动重试、不缓存依赖，成功产物保留1天。若免费额度不足即停。

## 未完成门槛

1. 核实账户免费及超额停止保护；本轮没有发起云端任务，也没有产生构建费用。
2. 原生 Mac 构建、签名及架构校验、原生窗口/钥匙串/只读DMG重开技术验证。
3. Mac 视觉与实际用户使用验收；在线供应商/模型、ASR真实识别尚未在 Mac 执行，不沿用 Windows 证据冒充。
4. 验证通过后再合 main、主干复验、安全注销工作树并交付真实 DMG。

当前仅为本地准备阶段，不称分支闭环、Mac安装包完成或完整P0通过。现有Windows安装包、正式数据及其他工作树未覆盖。

## 干净提交的 Windows 冻结版回归

功能准备提交：02b547b1b2e2a621977b070c5849b1ec9bf77f2d，构建时source_dirty=false。独立 Windows 程序仅用于回归，不是 Mac 包，也未覆盖现有安装。179项程序输入与当前工作树匹配、275项分发文件哈希通过、初始data为空；实际EXE与Chrome账号创建、备份、合成视频导入、策略确认门禁、退出重开通过，错误及外部请求为0。本目录保留全集日志、专项日志、源码和EXE UI结果、构建身份及两张实际EXE关联界面截图。首轮漏传ffmpeg的失败证据仍在外部验收目录。Mac原生冒烟脚本另作校正：必须连同临时挂载及测试钥匙串清理全部成功之后才写入通过回执。
