# ice运营台

面向短视频内容运营的本地工作台，将资料整理、账号策略、选题研究、文稿优化、成片审阅、任务提醒和发布反馈放在同一个工作空间。

## 能做什么

- 整理本地导入或手动获取的内容资料，辅助发现选题和研究方向。
- 保存账号策略与运营建议，建立研究主题、候选方案和参考适配记录。
- 根据选定资料生成研究稿，按指定版本优化文稿，保留来源、版本和导出记录。
- 使用内置行业模板辅助研究；提供视频分析、改编和成片审阅入口。
- 管理内容任务、本地提醒、发布登记和反馈复盘。

模型分析和在线采集需要另行配置服务与权限。软件不会自动发布内容，内置模板暂不支持自行增删。

## 从源码运行

本次交付使用 Python 3.12.14 验证。浏览器版使用 Python 标准库，无需 Node.js。

```powershell
git clone https://github.com/oliveiraFF/ice-.git
cd ice-
python app.py --port 8765 --open-browser
```

也可以双击 Windows 下的 `启动.bat`，然后访问 `http://127.0.0.1:8765`。按 Ctrl+C 停止服务；端口被占用时更换 `--port`。

运行数据写入 `data/`，下载缓存写入 `downloads/`，二者均不提交到仓库。随包 `_ops/` 是默认工作流来源，无需开发机的 D/E 盘项目；通常不要设置 `OPS_PROJECT_ROOT`。

## Windows 桌面版构建

桌面版要求 Windows 10/11 x64、Microsoft Edge WebView2 Runtime 和 .NET Framework 4.6.2 或更高版本。建议使用独立虚拟环境，以下依赖版本与本次桌面构建一致：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install PyInstaller==6.22.3 pywebview==6.2.1 pythonnet==3.2.1
.\.venv\Scripts\python.exe build_desktop.py --output ..\ice-builds
```

完整保留输出文件夹后运行其中的 `ice运营台.exe`，不能只复制 EXE。最终用户使用已打包桌面版时，无需安装 Python 或 Node.js。

## 配置和使用说明

首次使用、模型配置、可选采集服务、全部功能、数据备份及常见问题，请阅读：

- [完整使用说明](使用说明.txt)
- [Markdown 使用说明](M05-使用说明.md)
- [源码运行补充说明](README-内测说明.md)

API 密钥不应写入源码或提交到 Git。真实模型调用需要自行配置服务并满足程序的独立调用许可和本次确认；保存配置本身不发送模型请求。

## 源码基线

本仓库首次源码提交对应 `20261022-codex-ice-ui1-docs1`，含新版说明书及打包脚本的说明复制修正。产品文件与已交付 DOCS1 源码包逐字节一致；另外补充仓库首页、忽略规则和构建输入记录。

`SOURCE.json`、`release.marker`、`MANIFEST.sha256` 保留该交付快照的身份与校验信息；分发清单不覆盖仓库新增的管理文件或后续修改。字体及相关第三方资源许可随对应资源目录提供。
