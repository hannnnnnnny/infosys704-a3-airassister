AirAssist — A3 functional prototype
2026-10-15

本版可运行：乘客登录后在 My trips 中一键申请全额退款 → 员工登录后查看全部申请并批准或拒绝 → 乘客在 My trips 查看结果并下载收据。
退款金额来自 SAP Credit Memo Request API 的实时只读查询（NZ7K2H 对应文档 60000073）；预置的演示申请使用已记录的 SAP 快照。退款一律退回原支付方式。
这不是航空公司的正式系统。示例旅程、票价和联系人是合成数据；申请保存在本机。
它不会取消机票，也不会付款；绝不向 SAP 写入。

Mac 启动
1. 解压 ZIP，进入 AirAssist_V1 文件夹。
2. 使用 Python 3.10 或更新版本。在终端输入 python3 --version 确认。
3. 在该文件夹打开终端，输入：sh start.command
4. 浏览器打开：http://127.0.0.1:8789/?view=journey
保持终端运行；结束时按 Control+C。不要直接双击 index.html，它需要本地服务。
没有 npm 依赖，也不需要为了这个本地版本发布到互联网。
Windows：在文件夹运行 powershell -File start.ps1；也可 python server.py --port 8789。
修改后端代码后请重启服务再验证。

Demo accounts
Passenger: Mark.don / password123! — requests a full refund.
Staff: admin / admin123! — approves or declines refunds.
Public demo credentials for synthetic data only. Locally they come from AIRASSIST_PASSENGER_PASSWORD and AIRASSIST_STAFF_PASSWORD in local config; the deployed demo uses the same values as Vercel environment variables.

演示顺序
乘客用 Mark.don 登录，打开 My trips，选择 NZ7K2H，确认实时查到的退款金额，填写 mobile 联系方式（邮箱可选），勾选确认后提交全额退款申请。
员工用 admin 登录，在申请列表中找到该申请，可展开查看航班、SAP 行与联系方式，点 Approve 批准或点 Decline 并填写理由拒绝。
回到 Mark.don 的 My trips 即看到最新结果；状态页可下载收据。
员工端的 Reset demo data 可恢复初始演示数据。
同一预订再次提交会返回原申请，并明确提示原内容未修改。

SAP 查询
退款金额在打开申请页时实时读取 SAP Credit Memo Request，只读，不写入。
NZ7K2H 对应文档 60000073；预置的演示申请使用已记录的 SAP 快照并明确标注。
这是 SAP sandbox 的真实接口与样例财务数据，不是 Air New Zealand 的生产数据或个人 S/4HANA 租户。
查询失败会显示错误并提供重试，不会用固定示例替代真实返回。
交付包只含无密钥的 .env.example；在另一台电脑运行时，默认未连接。
另机配置：复制 .env.example 为 .env，填入自己的个人 API Hub key，设置 AIRASSIST_SAP_MODE=live，再重启。
准确服务根地址已经写在 .env.example。SAP 数据是通用财务样例，净额不是机票实付款，也不代表已付款。
课堂临时账号仅供教程练习，不能用于这个项目的配置、连接或部署。
不要把 .env、API key、.data/ 或真实个人信息放进作业 ZIP、代码仓库、截图或模型提示。

验证和评分证据
tests/ 含实际运行的行为测试；在仓库根目录运行 python -B -m unittest discover -s app/tests -t app/tests。
evidence/TEST_RESULTS_V1_5.txt 为当前后端自动测试结果，evidence/FRONTEND_TEST_RESULTS_V1_5.txt 为当前前端检查结果；更早的 V1.x 文件是原 V1.4 历史验收基线。
84 项后端行为测试全部通过，覆盖登录鉴权、乘客申请、员工审批/拒绝、收据一致性、演示数据重置及 SAP 边界。
53 项前端状态回归检查全部通过：运行 node app/tests/frontend-state.cjs（需要 Node.js）。
Vercel 云端部署的环境变量（只写变量名，不写值）：AIRASSIST_PASSENGER_PASSWORD、AIRASSIST_STAFF_PASSWORD、AIRASSIST_SESSION_SECRET、AIRASSIST_SAP_MODE、AIRASSIST_SAP_BASE_URL、AIRASSIST_SAP_API_KEY。
OpenCode CLI 1.18.35 实际生成 V1.1 核心案件审核后端和 11 项测试；独立审查修复后集成。V1.2 财务参考及 V1.3/V1.4 前端/说明改进为本地后续开发，贡献来源分别保留。
evidence/OPENCODE_CASE_SESSION.json 是实际原生会话导出；OPENCODE_CASE_BUILD.txt 保留当时贡献、审查和历史哈希。SOURCE_MANIFEST.json 记录当前版本。
evidence/OPENCODE_SESSION.json / OPENCODE_BUILD.txt 是前一版收据功能的历史证据，保留至评分结束。
当前 AirAssist_A3_V1_4.zip 是包含上述 OpenCode 贡献的项目源码包，由本地打包脚本生成；会话 JSON 与 App ZIP 是两个不同产物。
ZIP 的哈希、内容检查与重新解压后的独立运行结果见交付目录 PACKAGE_CHECK_V1_4.json 和 PACKAGE_SMOKE_V1_4.json。
保留完整源码、OpenCode 会话和开发记录直至评分完成。课堂若规定特定 App ZIP 导出操作，最终提交仍需按该操作核对。
功能第一版与后续正式评分提交应分开核验：并不承诺满分，也不把目标收益当作已测结果。
配套展示为 AirAssist_A3_Client_Pitch_V1_4_Refined.pptx，12页无隐藏附录，五分钟SCR主线、90秒现场演示、手动翻页，最后为老师原版声明模板。主稿267词，慢速稿212词。成员及贡献已由用户确认：Yi Han / yhan606、Xiao Lin / xlin031、Zhuyi Xia / zxia461、Zihang Zhang / zahz503，各25%，合计100%。现场语速、Mac实机启动及自己的SAP key配置仍需实际排练。A3是四人小组作业；所参考A2是一位成员的个人基线，最终评分以A3为准。

本地记录位置：.data/airassist.sqlite3（启动后自动创建）。乘客与员工使用演示账号登录；本地服务只监听 127.0.0.1。
最终生产化需要真实航空公司接口、身份验证、审批和支付权限、运维设计。

Official references
SAP: https://api.sap.com/api/sap-s4-CE_CREDITMEMOREQUEST_0001-v1/overview
OpenCode: https://opencode.ai/docs/cli/
