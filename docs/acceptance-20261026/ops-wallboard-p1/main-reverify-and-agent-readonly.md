# 主干复验与 Agent 只读连接记录

日期：2026-10-26

功能提交：`f1efdd25cff66dea3e739d25748701ca1bacf761`（`feat/ops-wallboard`）。复验主干：`f5741ce99d17117ebe4c099f23da9319bb47ce13`，复验后加入的仅为本文件等验收材料。

## 主干源码服务与浏览器

- `unittest discover -s tests -p 'test_*.py' -v`：32 项通过，0 跳过。
- `node tests/test_ui_truth.cjs`：通过；六种状态门禁保持通过。
- Python 编译、wallboard 和 Playwright 脚本语法检查、Git 空白检查：通过。
- 真实 Chromium 加载主干源码服务：空资料场景 8 个视口、11 项导航、空态、首次离线、刷新失败保留旧数据均通过；0 页面错误；模板文件哈希前后不变。
- 合成数值副本显示 `0、3、2、0` 与 `4、3、2、1、0`；明确标记为合成，副本哈希前后不变。

## Agent workspace 只读实测

- 使用本机 Agent workspace，路径因属于用户资料而不写入本仓库。它具有 `project.manifest.json`、presentation、work 与 runs 等桥接输入结构。
- 主干本地服务的 `/api/agent/view-model` 返回 HTTP 200、连接状态 ready、4 个 KPI 行、5 个流水线行、0 个读取错误；4 个 KPI 和 5 个流水线项均带来源/时间字段。
- 实际资料中没有可显示的经营数值，UI 如实展示“待接入”，并提示运营总览资料尚未生成；没有把合成值混入真实页。
- 测试由本机 GET 读取触发，ICE 测试数据库放在独立临时目录；没有运行 Agent 脚本、调用模型/TikHub 或向 workspace 写入数据。

## Windows 打包与重启验证

打包细节见 `../workbench-p0/desktop-package-reverify.md`。同一个桌面包在隔离数据目录启动后，wallboard 通过本机桥读取上述 workspace；浏览器可见“已连接”和真实资料时间，缺失指标仍显示“待接入”。

桌面包复验完成演示研究稿 v1→v2、页面下载、隔离进程重启后按 UID 恢复 v2；页面只访问本机，没有 JS 错误或外部请求。该运行实例由进程环境传入 workspace 路径；当前还没有在 UI 中提供 workspace 路径设置页。未来正常启动若没有该环境配置，会显示未连接。此项是当前产品交付边界，不作为已完成的真实业务数据接入。

## 未覆盖范围

本次是只读桥与产品 UI P0 的验收。P1 动作桥（优化、TikHub 抓取、拆解、启动 Agent workflow）尚未开放或测试；未进行真实模型、TikHub 付费请求、实拍内容质量评审或十主题批测。
