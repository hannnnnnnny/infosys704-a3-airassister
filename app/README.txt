AirAssist — A3 functional prototype V1.4
2026-10-09

本版可运行：查询示例预订 → 申请并保存 → 案件资料审核 → 标准/专家分流与交接 → 乘客查询同步状态 → 下载申请记录。
外观沿用已批准的 V2；保留 V1.2 异步查询、审核草稿、版本冲突保护和案件内的真实 SAP 财务参考记录。V1.4 沿用已批准的布局方向，改用更克制的字体、薄分隔线、白底表单和自然的操作名称；减少重复卡片与标签，禁用交接按钮呈灰色。人工检查、已保存状态与下一步操作放在一起，补充资料、SAP详情和事件历史按需展开。
这不是航空公司的正式系统。示例旅程、票价和联系人是合成数据；申请保存在本机。
它不会取消机票、决定退款资格、批准退款或付款。

Mac 启动
1. 解压 ZIP，进入 AirAssist_V1 文件夹。
2. 使用 Python 3.10 或更新版本。在终端输入 python3 --version 确认。
3. 在该文件夹打开终端，输入：sh start.command
4. 浏览器打开：http://127.0.0.1:8789/?view=journey
保持终端运行；结束时按 Control+C。不要直接双击 index.html，它需要本地服务。
没有 npm 依赖，也不需要为了这个本地版本发布到互联网。
Windows：在文件夹运行 powershell -File start.ps1；也可 python server.py --port 8789。

演示顺序
Booking reference：NZ7K2H；Family name：Taylor。
点 Request a refund，选择原因，使用示例邮箱（例如 demo@example.com），填写可选说明。
点 Review request，勾选确认框，再点 Submit request。
复制生成的 AF- 开头编号。Track request 中输入该编号和提交时的同一邮箱。
刷新页面仍可查询；终端重启后 SQLite 中的申请仍保留。
同一预订和邮箱再次提交会返回原申请，并明确提示原内容未修改。
代理预订示例 NZ8T3H / Taylor 会显示旅行社说明，不能通过直订表单提交。

案件审核演示
进入 Staff review，用刚保存的申请编号和同一邮箱查询；Use last saved request 可填入本浏览器保存的最近申请。
检查预订、联系信息及付款证据/规则/补充说明审核项。未完成必要审核项时，不能交接。
可先填写备注并 Save review，保存资料不足的状态；每次修改都需要备注。
用 DEMO-RECEIPT-NZ7K2H 等明确的示例参考，记录人工原型检查，再勾选已检查项目并保存。
页面解释 Standard review / Complex review 的原因、拟定本地队列和责任角色。
Send to standard/specialist queue 完成本地交接后，编辑会锁定；要改动，填写 Reopening note 再 Reopen review。
Specialist review required 可示范异常案件分流；Other 原因也进入专家审核。
每次保存、交接、重新打开都有版本和时间记录。旧版本不能覆盖新版本。
未保存的审核草稿按申请编号、邮箱和版本保留在当前浏览器会话中；刷新不会自动提交。
若服务器版本已变化，先核对最新检查项和事件，再选择保留并审查草稿或丢弃草稿。
有草稿时先保存或丢弃，再进行 SAP 参考保存；交接必须使用已保存的最新审核。
Track request 和 Download receipt 使用同一份持久化审核记录，展示当前本地状态和历史。
这些人工检查和路由不是航空公司的真实政策、付款核验或批准决定；真实订票/票据/付款/航变对账仍需正式接口。

SAP 查询
Staff review 内的 SAP financial reference 提供 Credit Memo Request (A2X) 的只读财务记录查询与本地参考保存；另有独立查询工作区。
在尚未交接的案件中输入 60000002，填写说明如何使用这条演示财务参考，再点 Query and save reference。
服务器实际查询 SAP 并保存返回字段、来源、获取时间、案件版本及备注；每次保存产生一条本地事件，历史快照保留。
SAP 参考保存不勾选人工审核项，不核验付款，不关联真实机票，也不自动确定可退金额；交接后的案件要先重新打开。
当前开发机已在用户明确授权后连接个人 SAP API Hub 账号，实际 GET 查询返回 HTTP 200。
这是 SAP sandbox 的真实接口与样例财务数据，不是 Air New Zealand 的生产数据或个人 S/4HANA 租户。
不存在的文档已实际返回 HTTP 404；断线或查询失败时不会用固定示例替代真实返回。
交付包只含无密钥的 .env.example；在另一台电脑运行时，默认未连接。
另机配置：复制 .env.example 为 .env，填入自己的个人 API Hub key，设置 AIRASSIST_SAP_MODE=live，再重启。
准确服务根地址已经写在 .env.example。可查询 sandbox 中已验证的文档 60000002。
SAP 数据是通用财务样例，并不与示例旅程自动关联。净额不是机票实付款，也不代表已退款。
文档流程代码不能单独用于推断审批或付款结果。本原型不向 SAP 写入。
课堂临时账号仅供教程练习，不能用于这个项目的配置、连接或部署。
不要把 .env、API key、.data/ 或真实个人信息放进作业 ZIP、代码仓库、截图或模型提示。

验证和评分证据
tests/ 含实际运行的行为测试；运行 python3 -m unittest discover -s tests -v。
evidence/TEST_RESULTS_V1_4.txt 为本版后端自动测试结果；TEST_RESULTS.txt 和 TEST_RESULTS_V1_2.txt 保留历史结果。V1_4_BROWSER_ACCEPTANCE.json 为本版实际浏览器验收与收据一致性记录，RUNTIME_ACCEPTANCE.txt 为历史浏览器记录。
evidence/REQUIREMENTS_AUDIT.txt 和 RUBRIC_TRACEABILITY.txt 为要求与证据对应。
evidence/SAP_LIVE_QUERY.json 记录真实 SAP 查询结果；截图另附于 outputs 的 screenshots 文件夹。
49 项后端行为测试全部通过，包含旧数据迁移、并发版本冲突、资料不足阻止交接、状态/收据一致性、参考快照历史及 SAP 边界。
28 项前端状态回归检查全部通过：运行 node tests/frontend-state.cjs（需要 Node.js）；实际输出见 evidence/FRONTEND_TEST_RESULTS_V1_4.txt。
本版实际浏览器验收使用合成案例 AF-CC7A93DA2007：失败的 SAP 查询不改变已保存案件；审核草稿刷新恢复；标准交接、说明理由后重开、专家交接完成；最终 v6 / 7 个事件，下载收据与查询状态一致。390×844 浏览器布局无横向溢出；没有声称 Mac 或 iPhone 实机验收。
OpenCode CLI 1.18.35 实际生成 V1.1 核心案件审核后端和 11 项测试；独立审查修复后集成。V1.2 财务参考及 V1.3/V1.4 前端/说明改进为本地后续开发，贡献来源分别保留。
evidence/OPENCODE_CASE_SESSION.json 是实际原生会话导出；OPENCODE_CASE_BUILD.txt 保留当时贡献、审查和历史哈希。SOURCE_MANIFEST.json 记录当前版本。
evidence/OPENCODE_SESSION.json / OPENCODE_BUILD.txt 是前一版收据功能的历史证据，保留至评分结束。
当前 AirAssist_A3_V1_4.zip 是包含上述 OpenCode 贡献的项目源码包，由本地打包脚本生成；会话 JSON 与 App ZIP 是两个不同产物。
ZIP 的哈希、内容检查与重新解压后的独立运行结果见交付目录 PACKAGE_CHECK_V1_4.json 和 PACKAGE_SMOKE_V1_4.json。
保留完整源码、OpenCode 会话和开发记录直至评分完成。课堂若规定特定 App ZIP 导出操作，最终提交仍需按该操作核对。
功能第一版与后续正式评分提交应分开核验：并不承诺满分，也不把目标收益当作已测结果。
配套展示为 AirAssist_A3_Client_Pitch_V1_4_Refined.pptx，12页无隐藏附录，五分钟SCR主线、90秒现场演示、手动翻页，最后为老师原版声明模板。主稿267词，慢速稿212词。成员及贡献已由用户确认：Yi Han / yhan606、Xiao Lin / xlin031、Zhuyi Xia / zxia461、Zihang Zhang / zahz503，各25%，合计100%。现场语速、Mac实机启动及自己的SAP key配置仍需实际排练。A3是四人小组作业；所参考A2是一位成员的个人基线，最终评分以A3为准。

本地记录位置：.data/airassist.sqlite3（启动后自动创建）。没有航空公司身份验证或邮件验证。
查询采用随机编号+邮箱作为原型访问门槛，不能替代正式登录；本地服务只监听 127.0.0.1。
最终生产化需要真实航空公司接口、身份验证、审批和支付权限、运维设计。

Official references
SAP: https://api.sap.com/api/sap-s4-CE_CREDITMEMOREQUEST_0001-v1/overview
OpenCode: https://opencode.ai/docs/cli/
