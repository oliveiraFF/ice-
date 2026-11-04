# 抓取关键词输入修补

用户确认：截图中的输入只筛选接口名称，还需要明确填写要抓取的内容。独立分支fix/capture-keyword-input，基于main eb4e97aaa33f1db2ee66911488c74804b090b299。使用finesse-ui组件流程，沿用既有亮暗主题和界面；不新增后端接口、数据库或平台适配器。

## 实现

- 抓取关键词从折叠区移到平台选择下方，直接可见；筛选接口名称另设明确标签。保留原有本地搜索操作。
- 关键词只带入接口明确声明的字符串搜索字段：keyword、search_keyword、search_query、search_word；query/q还要求属于搜索接口。支持查询参数和JSON请求体，不覆盖对象类型查询。
- Instagram按链接获取详情等接口不把关键词当链接；从首页选择进入时清空官方样本查询URL，提示填写自己的帖子/视频链接。用户已填的页面内参数草稿仍保留。
- 不直接执行接口；仍在参数页检查必填和费用、手动执行。关键词不是所有接口的通用参数，用户ID、帖子链接等仍按接口填写。

## 验证与交付

先补Node复现，修补前失败日志保存在E:/leida-build/capture-keyword-20261104/node-red.txt。功能提交f2551ac；核对实际目录后补齐TikTok shop的search_word，提交6224354b0768212f0158b8db7dd406f196995537。

真实本地服务、Chrome和最终Windows EXE验证：无需展开即可填写关键词，YouTube search_query、抖音JSON keyword、TikTok shop search_word实际带入；Instagram post_url为空且提示补链接。保留跨平台多选、参数切换与草稿、刷新、断网恢复、关闭重开、390/1280宽度和亮暗主题检查。接口执行0次、供应商调用0次、账本新增0行，没有读取密钥。

最终包来自干净6224354；181项构建输入与源码一致，278项分发文件及空data目录核验通过。桌面ZIP完整性和SHA256见delivery.json。只更新此前由本会话生成的“ice运营台-全平台接口新版”快捷方式，目标和参数先校验，原快捷方式备份留在外部证据目录；保留E:/ICEOps/data参数，不覆盖旧安装程序和原有主快捷方式。

旧404拦截、禁用按钮、预算与历史不变、文档表单类型和重开回归通过，见exe-market-regression.json。该回归最初两次在初始目录加载处超时，诊断未发现页面异常，同一最终EXE随后通过；原因未确认，未声称修复产品根因。测试增加失败资源/控制台/脚本信息留存，使用独立持久浏览器目录并显式启用JS后完整通过，所有原断言保留。早期失败日志及截图保存在外部final-exe-regression、final-exe-regression-r2目录，不用后来通过抹去失败记录。

截图为最终EXE实际页面。CaptureKeyword.preview.html仅为八种输入状态的静态展示，不是供应商调用证据。其他平台作品收录仍待接入，1480个目录接口并未全部实测；Mac构建和账号经营质量不属于本轮通过范围。

主干合入、复验与安全收尾将在完成后补充main-verification.json。

## 主干闭环

已快速前移合main 078baf39bf289d159d4feb6eb4f4fb0e014cba5d；主干运行91项Python，0失败、4既有跳过；Node合同、真实主干UI及181输入/278分发文件复验通过。分支祖先与工作树干净核验后，验证绝对路径处于E:/ice-worktrees内，由Git安全移除工作树并以-d删除分支。旧本地改动stash保留，主干无业务源码未提交；具体证据见main-verification.json。
