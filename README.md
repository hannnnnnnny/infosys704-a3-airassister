# AirAssist · INFOSYS 704 A3

AirAssist 是 INFOSYS 704 A3 四人小组的退款原型：乘客登录后在 My trips 中一键申请全额退款（金额来自 SAP Credit Memo Request API 的实时只读查询），员工登录后查看全部申请并批准或拒绝。不付款、不向 SAP 写入任何数据。

**[打开 AirAssist 在线演示](https://infosys704-a3-airassist.vercel.app/?view=journey)** · [本地运行](#在-mac-运行) · [部署说明](#vercel-部署)

原验收基线为 **V1.4（2026-10-09）**；**2026-10-14** 增加 Vercel 云端适配。这个公开仓库用于小组查看、修改和审阅，也保存课堂演示材料。任何人均可查看和下载；组员接受协作邀请后可以直接提交修改。

## 在线演示

1. 乘客用 **Mark.don** 登录，打开 `My trips`，为 **NZ7K2H** 申请全额退款并填写 mobile 联系方式。
2. 员工用 **admin** 登录，在申请列表中批准（Approve）或拒绝（Decline）该申请；拒绝需填写理由。
3. 回到 Mark.don 的 `My trips` 查看结果；员工端的 `Reset demo data` 可恢复初始演示数据。

在线演示无需安装 Python，也无需 Vercel 登录。

线上申请保存在 **私有 Vercel Blob 的 SQLite 快照**中，可以在云端实例重启后继续使用；与本机 SQLite 完全分开。乘客与员工均使用下方的演示账号登录，**只使用合成信息，不输入真实旅客或付款数据**。原型不会付款；SAP 金额为只读查询，绝不写入。

私有快照适合小规模课堂演示：读取绕过缓存，写入使用 ETag 条件更新，避免多个云端实例覆盖彼此的修改；单个快照限制为 5 MiB。繁忙、存储故障或版本冲突会明确报错，不能将它视为正式航空业务数据库。

## Demo accounts

- Passenger: **Mark.don** / `password123!` — requests a full refund.
- Staff: **admin** / `admin123!` — approves or declines refunds.

Public demo credentials for synthetic data only. Locally they come from `AIRASSIST_PASSENGER_PASSWORD` and `AIRASSIST_STAFF_PASSWORD` in local config; the deployed demo uses the same values as Vercel environment variables.

## 从哪里开始

| 要做的事 | 打开的位置 |
| --- | --- |
| 直接体验应用 | [Vercel 在线演示](https://infosys704-a3-airassist.vercel.app/?view=journey) |
| 运行或修改应用 | [`app/`](app/)；后端 `server.py`，前端 `public/` |
| 修改课堂演示 PPT | [主 PPT](A3_Presentation/AirAssist_A3_Client_Pitch_V1_4_Refined.pptx) |
| 核对老师的最后一页模板 | [已填写贡献页](A3_Presentation/Groupwork_Management_25_Percent_Confirmed.pptx) |
| 修改讲稿 | [可编辑 Markdown](A3_Presentation/A3_Speaking_Script.md)；[慢速 PDF](A3_Presentation/A3_Speaking_Script_Slow_V1_4.pdf) |
| 按评分要求检查 | [小组核对清单](A3_Presentation/A3_Group_Check.md)、[要求说明](A3_Presentation/A3_Requirements_Clarification.md)、[Hint 核查](A3_Presentation/A3_Hint_Link_Audit.md) |
| 查看功能与测试证据 | [`app/evidence/`](app/evidence/) 和 [`A3_App_V1/`](A3_App_V1/) |
| 取得已经验收的源码 ZIP | [V1.4 App ZIP](A3_App_V1/AirAssist_A3_V1_4.zip) |

GitHub 对 PPTX 的在线预览有限，请下载到 PowerPoint 编辑；代码和 Markdown 可以直接查看、比较版本或提交修改。

`A3_Presentation/content.json` 与 `requirements.json` 另附可编辑的逐页内容和展示要求，便于讨论、检索和核对。**它们不会自动渲染或更新 PPT**；PPT 仍在 PowerPoint 中直接编辑，并与 JSON/讲稿手动同步。本仓库不依赖开发机的私有 PPT 生成脚本或本机工具路径。

## 在 Mac 运行

需要 **Python 3.10 或更新版本**。使用 GitHub 的 `Code → Download ZIP`，或用 Git/GitHub Desktop 克隆仓库，然后在仓库目录的终端运行：

```sh
cd app
sh start.command
```

也可以运行：

```sh
cd app
python3 -B server.py --port 8789
```

浏览器打开 [AirAssist 本地页面](http://127.0.0.1:8789/?view=journey)。保持终端运行，结束时按 `Control+C`。不要直接打开 `index.html`；它依赖本地服务。Windows 可在 `app` 目录运行 `python -B server.py --port 8789` 或 `powershell -File start.ps1`。修改后端代码后请重启服务再验证。

这个版本不需要 npm 安装或云服务。若端口被其他程序占用，可运行 `python3 -B server.py --port 8791`，并使用对应的浏览器端口。

## 快速演示与 SAP 配置

演示账号见下文 [Demo accounts](#demo-accounts)。乘客 Mark.don 的 My trips 列出其全部行程：打开 NZ7K2H，确认实时查到的退款金额后填写联系方式并提交；员工 admin 在列表中批准或拒绝，乘客端 My trips 同步显示结果，状态页可下载收据。

原型的闭环为：乘客一键申请全额退款 → 员工批准或拒绝 → 乘客查看结果。旅程和申请为合成演示数据；本地运行使用本机 SQLite，线上演示使用私有云快照。它不会取消真实机票，也不会付款。

SAP 使用 **Credit Memo Request** 的真实只读 sandbox 查询：NZ7K2H 的退款金额来自文档 **60000073** 的实时读取；预置的演示申请使用已记录的 SAP 快照。退款一律退回原支付方式。本原型绝不向 SAP 写入，也不执行付款。仓库不含个人密钥；其他电脑默认显示未配置，不能把未配置状态当作真实 SAP 成功。需要连接时：

```sh
cd app
cp .env.example .env
```

在本机 `.env` 中设置 `AIRASSIST_SAP_MODE=live`，填写**自己的个人 SAP API Hub key**，再重启服务。

在本机 `.env` 中设置 `AIRASSIST_SAP_MODE=live`，填写**自己的个人 SAP API Hub key**，再重启服务。服务根地址已写在模板中，NZ7K2H 对应的文档号为 `60000073`。课堂临时账号只供教程练习，不能用作项目配置。不要提交 `.env`、密钥、`.data/` 或真实个人记录；根目录与 `app/` 的忽略规则会保护常见本机文件，但提交前仍需检查 Git 的文件列表。

SAP 返回通用财务样例，不是 Air New Zealand 生产机票、支付或审批数据。查询失败会显示错误并提供重试，不会悄悄替换成模拟成功。

## Vercel 部署

部署入口为 [`api/index.py`](api/index.py)，复用 `app/server.py` 的 HTTP 合约和业务规则；[`vercel.json`](vercel.json) 将网页和 API 请求交给 Python 函数。只有允许的四个前端文件可作为网页访问。[`.vercelignore`](.vercelignore) 排除密钥、本机数据库、测试、证据和 PPT 等文件。

Vercel 项目名为 `infosys704-a3-airassist`，函数和私有 Blob 存储位于 `syd1`。当前公开地址指向 **Preview 部署**。重新部署需要登录有此 Vercel 项目权限的账号，并在仓库根目录运行：

```sh
vercel link --yes --project infosys704-a3-airassist --scope harryhaber606-7483s-projects
vercel deploy --yes --target preview
vercel alias set <新部署域名> infosys704-a3-airassist.vercel.app
```

部署环境必须连接 **Private Blob**，由 Vercel 注入 `BLOB_READ_WRITE_TOKEN`；`AIRASSIST_ALLOWED_HOSTS` 包含 `infosys704-a3-airassist.vercel.app`。演示登录账号的密码与本地共用以下环境变量（只写变量名，不写值）：`AIRASSIST_PASSENGER_PASSWORD`、`AIRASSIST_STAFF_PASSWORD`、`AIRASSIST_SESSION_SECRET`、`AIRASSIST_SAP_MODE`、`AIRASSIST_SAP_BASE_URL`、`AIRASSIST_SAP_API_KEY`。

本次通过已登录账号进行 CLI 部署。**GitHub 自动部署尚未连接**：Vercel 当前无法连接仓库所有者的 GitHub 集成，因此 GitHub push 不会自动更新线上版本。正式生产环境需要另行配置存储和环境变量，不能只复用空的生产配置。

若要在云端连接 SAP，在 Vercel 的 Preview 环境设置以上 `AIRASSIST_SAP_MODE`、`AIRASSIST_SAP_BASE_URL`、`AIRASSIST_SAP_API_KEY` 变量，使用自己的个人 API Hub key，再重新部署。密钥只存于 Vercel 环境变量，不写入 GitHub、README 或网页。

验证命令（在仓库根目录）：

```sh
python3 -B -m unittest discover -s app/tests -p 'test_*.py'
node app/tests/frontend-state.cjs
vercel deploy --dry --json
```

当前版本验证：**84 项后端测试、53 项前端检查通过**，结果见 `app/evidence/TEST_RESULTS_V1_5.txt` 与 `app/evidence/FRONTEND_TEST_RESULTS_V1_5.txt`；额外实际验证了私有 Blob 读写、重新载入和过期 ETag 拒绝。Vercel 构建报告 `READY`。`app/evidence/` 下更早的 V1.x 结果文件是原 V1.4 历史验收基线。

## 评分依据与保留的证据

最终依据是老师的 **A3 V3 specification**，总分 **200**：App Rationale 10、App Design 30、App Functionality 60、App Usability / Ease of Use 50、App Presentation 50。A3 是四人小组作业；此前参考的 A2 是一位成员的个人方案，不能用它替代 A3 的评分标准。

- 当前演示为 **12 页、五分钟 SCR 结构**，含 90 秒现场操作，手动翻页；最后一页保留老师的 Groupwork Management 声明模板。它不是 A2 的 PechaKucha 演示。
- 提交包含可运行 App ZIP 和展示 slides。GitHub 协作不能代替 Canvas 提交或课堂 pitch，也没有额外添加生产部署、真实旅客调研或付费服务要求。
- 当前结果为 `app/evidence/TEST_RESULTS_V1_5.txt`（84 项后端测试）与 `app/evidence/FRONTEND_TEST_RESULTS_V1_5.txt`（53 项前端检查）全部通过；更早的 V1.x 文件是原 V1.4 历史验收基线，另有实际浏览器与重新解压运行核查。这些是已完成基线的事实，不代表此后每次修改都已验收，也不保证课堂评分。
- OpenCode 的实际构建与原生会话导出记录保留在 `app/evidence/`。V1.2–V1.4 的后续本地改进有单独来源记录；不能把全部开发描述成由 OpenCode 完成。
- 原验收 ZIP、manifest 和 QA 记录保留作基线。修改 `app/` 后，它们不会自动更新；新的提交版本需要重新核查并另行导出，不要手改历史测试结果或来源记录。

完整依据、边界和仍需在自己的 Mac 上排练的步骤见 [A3_Group_Check.md](A3_Presentation/A3_Group_Check.md)。老师的原始课程文件没有额外上传到仓库。

## 小组成员

以下为**课程 username**，不是已确认的 GitHub handle。总贡献已由小组确认，各 **25%**，合计 **100%**。

| 成员 | 课程 username | 总贡献 |
| --- | --- | ---: |
| Zihang Zhang | zahz503 | 25% |
| Yi Han | yhan606 | 25% |
| Xiao Lin | xlin031 | 25% |
| Zhuyi Xia | zxia461 | 25% |

修改流程见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 目录

```text
app/                  可编辑、可运行源码，测试和构建证据
  public/             HTML、CSS、JavaScript
  tests/              后端行为与前端状态检查
  evidence/           SAP、OpenCode、要求追踪和验收记录
  manual/             开发与操作说明
  .env.example        无密钥的个人账号配置模板
  server.py           本地 Python 服务
  cloud_store.py      云端私有 SQLite 快照与并发写入保护
  cloud_access.py     云端同源检查和匿名签名会话
  cloud_handler.py    云端 HTTP 与演示文案适配
  start.command       Mac 启动脚本
  start.ps1           Windows 启动脚本
api/index.py          Vercel Python 函数入口
vercel.json           路由和部署区域配置
.vercelignore         云端打包排除规则
A3_Presentation/      可编辑 PPTX、讲稿、组员核对 Markdown、展示 QA
A3_App_V1/            已验收 App ZIP、软件 QA 和实际界面截图
START_HERE.txt        原 V1.4 交付包入口
REVIEW_MANIFEST.json  原交付包文件校验记录
```

## English quick start

Try the **[AirAssist online demo](https://infosys704-a3-airassist.vercel.app/?view=journey)**. Sign in as passenger **Mark.don**, open My trips, request a full refund for **NZ7K2H** with a mobile number; then sign in as staff **admin** to approve or decline it, and check the result back in Mark.don's My trips. Staff can use Reset demo data to restore the starting state. Refund amounts are read live from the SAP Credit Memo Request API (document 60000073 for NZ7K2H); seeded requests use recorded SAP snapshots. Refunds always go to the original payment method; nothing is written to SAP and no payment is made. The Vercel preview stores demo records in private Blob-backed SQLite snapshots. Use synthetic data only.

For local development, run `cd app` and `sh start.command` on macOS with Python 3.10+, then open `http://127.0.0.1:8789/`. Restart the server after backend changes. Local SQLite records and cloud demo records are separate. Never commit credentials or databases. The current results are `app/evidence/*_V1_5.txt`; older V1.x files are the historical V1.4 baseline. Deployment currently uses the Vercel CLI; GitHub automatic deployment is not connected.
