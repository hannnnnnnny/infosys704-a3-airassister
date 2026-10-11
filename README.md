# AirAssist · INFOSYS 704 A3

四人小组的 A3 可运行原型与演示材料。当前基线为 **V1.4（2026-10-09）**；这个私有仓库用于组员查看、修改和审阅，**没有云部署**。GitHub 保存文件，不会替你启动应用，也不会连接 SAP。

## 从哪里开始

| 要做的事 | 打开的位置 |
| --- | --- |
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

浏览器打开 **http://127.0.0.1:8789/?view=journey**。保持终端运行，结束时按 `Control+C`。不要直接打开 `index.html`；它依赖本地服务。Windows 可在 `app` 目录运行 `python -B server.py --port 8789` 或 `powershell -File start.ps1`。

这个版本不需要 npm 安装或云服务。若端口被其他程序占用，可运行 `python3 -B server.py --port 8791`，并使用对应的浏览器端口。

## 快速演示与 SAP 配置

示例订票号 **NZ7K2H**，姓氏 **Taylor**。使用自己的演示邮箱提交申请，记录生成的 `AF-` 编号，然后在 `Case review` 中使用同一编号和邮箱查询。完整操作顺序见 [`app/README.txt`](app/README.txt)。

原型的闭环为：查询示例预订 → 保存申请 → 人工资料审核 → 标准/专家队列交接 → 查询同步状态 → 下载申请记录。旅程和申请为合成演示数据，申请保存在本机；它不会取消真实机票、批准退款或付款。

SAP 使用 **Credit Memo Request (A2X)** 的真实只读 sandbox 查询。仓库不含个人密钥；其他电脑默认显示未配置，不能把未配置状态当作真实 SAP 成功。需要连接时：

```sh
cd app
cp .env.example .env
```

在本机 `.env` 中设置 `AIRASSIST_SAP_MODE=live`，填写**自己的个人 SAP API Hub key**，再重启服务。服务根地址已写在模板中，已验证的公开样例文档号为 `60000002`。课堂临时账号只供教程练习，不能用作项目配置。不要提交 `.env`、密钥、`.data/` 或真实个人记录；根目录与 `app/` 的忽略规则会保护常见本机文件，但提交前仍需检查 Git 的文件列表。

SAP 返回通用财务样例，不是 Air New Zealand 生产机票、支付或审批数据。保存 SAP 参考不会自动勾选人工审核项目；查询失败会显示错误，不会悄悄替换成模拟成功。

## 评分依据与保留的证据

最终依据是老师的 **A3 V3 specification**，总分 **200**：App Rationale 10、App Design 30、App Functionality 60、App Usability / Ease of Use 50、App Presentation 50。A3 是四人小组作业；此前参考的 A2 是一位成员的个人方案，不能用它替代 A3 的评分标准。

- 当前演示为 **12 页、五分钟 SCR 结构**，含 90 秒现场操作，手动翻页；最后一页保留老师的 Groupwork Management 声明模板。它不是 A2 的 PechaKucha 演示。
- 提交包含可运行 App ZIP 和展示 slides。GitHub 协作不能代替 Canvas 提交或课堂 pitch，也没有额外添加生产部署、真实旅客调研或付费服务要求。
- V1.4 验收记录为 **49 项后端测试、28 项前端状态检查**全部通过，另有实际浏览器与重新解压运行核查。这些是已完成基线的事实，不代表此后每次修改都已验收，也不保证课堂评分。
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
  start.command       Mac 启动脚本
  start.ps1           Windows 启动脚本
A3_Presentation/      可编辑 PPTX、讲稿、组员核对 Markdown、展示 QA
A3_App_V1/            已验收 App ZIP、软件 QA 和实际界面截图
START_HERE.txt        原 V1.4 交付包入口
REVIEW_MANIFEST.json  原交付包文件校验记录
```

## English quick start

This private repository contains the editable AirAssist coursework prototype and presentation materials. Run `cd app` and `sh start.command` on macOS with Python 3.10+, then open `http://127.0.0.1:8789/`. There is no cloud deployment. The app uses synthetic booking data and a personal-account, read-only SAP sandbox connection when configured locally. Never commit credentials or local databases. Keep the accepted V1.4 archives and evidence as the historical baseline, and use branches and pull requests for changes.
