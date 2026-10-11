# AirAssist A3 - 五分钟讲稿与操作稿

- 主讲英文总词数：267，停顿提醒、中文说明和故障备用句不计入。
- 总时间计划：5:00；包含90秒现场操作。必须在实际Mac上排练校准。
- A3不是A2的20秒自动PechaKucha；使用手动翻页。
- 朗读英文，`【停1秒】`、`【操作时停讲】`和中文说明不读。
- 主讲：第1-11页及最后第12页老师声明；新版没有隐藏附录。
- 对应PPT：[V1.4精修版](AirAssist_A3_Client_Pitch_V1_4_Refined.pptx)。完整PDF：[操作稿](A3_Speaking_Script_V1_4.pdf)，慢语速PDF：[精简稿](A3_Speaking_Script_Slow_V1_4.pdf)。

## 课程边界与已有访谈

A3是四人小组作业，真正约束本次提交的是A3评分标准和课堂更新。已知A2文件仅为用户个人作业，不能代表其他三位成员的A2，也不能把个人A2的评分要求套在四人的A3上。沿用A1/A2已有员工访谈与旅程分析作为设计依据，保留原材料的证据限制；开发反馈和测试也如实区分。A3不要求本次重新找真实旅客或退款员工验证，因此没有安排、承诺或宣称完成新的访谈研究。

## 精确时间表

### 第1页 | 0:00 - 0:17 | AirAssist

**用途：** 开场：说明这是退款案件准备原型，并承诺展示完整案例。

Good morning. 【停1秒】 AirAssist prepares refund cases for Air New Zealand. I will show one request reaching its review team.

**操作提醒：** 看向观众，不读封面上的全部文字。

### 第2页 | 0:17 - 0:34 | Direct-booking refund requests

**用途：** Situation：把当前范围放回小组更大的航班变更自助服务方案。

Our group idea supports passengers after flight changes. 【停1秒】 This first part handles direct-booking refunds. Travel-agent bookings follow another path.

**操作提醒：** 指向 Direct bookings；说明是小组方案第一部分。

### 第3页 | 0:34 - 0:53 | Refund case preparation

**用途：** Complication：表单已有必填项；沿用员工输入解释错误信息、复杂案件及交接准备。

Existing forms have required fields. 【停1秒】 Earlier staff input describes wrong details and complex cases. Our checklist and named review route prepare the handoff.

**操作提醒：** 不是只增加必填字段；整合准备信息，不宣称直接退款团队验证。

### 第4页 | 0:53 - 1:11 | Implementation scope

**用途：** Resolution：说明为什么先做准备和分流，而不是直接实施全部付款。

Case preparation offers useful impact with a manageable scope. 【停1秒】 Staff retain refund decisions and approval. Actual payment needs later airline integration.

**操作提醒：** 影响/工作量为定性判断；支付集成仍待开发。

### 第5页 | 1:11 - 1:32 | Design Thinking

**用途：** 设计：五阶段沿用已有员工输入；操作集中后实际复查交接和草稿恢复。

We used five design stages. 【停1秒】 Earlier staff input shaped the checks. We grouped review actions, then checked handoff and draft recovery.

**操作提醒：** 展示实际审查改进：长审核页、集中操作、交接与草稿复查。开发检查不冒充新参与者研究。

### 第6页 | 1:32 - 1:53 | What changed for A3

**用途：** 方案调整：解释 Option 2 下的部分匹配，保留流程并调整数据和边界。

The SAP API partly fits. 【停1秒】 We kept the refund process, used sample journeys, and saved SAP financial references. These are our Option Two changes.

**操作提醒：** 分清合成旅程、本地案件、真实 SAP 财务参考。

### 第7页 | 1:53 - 2:15 | SAP financial reference

**用途：** 真实连接：说明个人 SAP 账号的只读调用、来源和时间，并说明数据限制。

The app reads Credit Memo Request through a personal SAP account. 【停1秒】 Staff save its source, time, and reference note. Booking payment remains unverified.

**操作提醒：** 指向 GET、Source/time、Booking match: Not verified。

### 第8页 | 2:15 - 3:45 | From request to handoff

**用途：** 演示：从未完成检查的已保存申请开始，完成案件准备和本地分流闭环。

Here is a saved request. 【停1秒】 Missing checks block handoff. 【操作时停讲】 I add the SAP reference. The checks stay unchanged. 【操作时停讲】 I record and save the manual review. 【操作时停讲】 Now I send the case to its queue. 【操作时停讲】 Tracking shows the same status. The refund decision remains pending.

**操作提醒：** 切到新建且尚未审核的案件。先Query and save reference，再完成人工检查并Save review，最后Send to standard queue；展示同一案件的Track与Download receipt。操作时停讲。

### 第9页 | 3:45 - 4:05 | Review status and recovery

**用途：** 可用性：已保存状态和审核操作并列；草稿恢复、版本警告及专家队列。

Staff see saved status beside review actions. 【停1秒】 Draft recovery and version warnings protect work. Complex cases show their specialist and queue.

**操作提醒：** 指向保存状态及 Save/Send；手机响应布局已检查，不宣称真实Mac实体机验收。

### 第10页 | 4:05 - 4:27 | Workflow verification

**用途：** 开发证据：明确 OpenCode 的实际贡献及测试范围，避免宣称零缺陷。

OpenCode helped build the core workflow. 【停1秒】 We checked saved records, SAP errors, review recovery, and the app package.

**操作提醒：** 不声称零漏洞；OpenCode 核心贡献与后续修改分开。

### 第11页 | 4:27 - 4:52 | Next step: a small pilot

**用途：** 向客户提出决定：同意小范围试点，先确认检查规则，再测量实际效果。

A small pilot is next. 【停1秒】 The process owner agrees the checks. We measure readiness, repeated work, and handling time. Today, we seek agreement on this scope.

**操作提醒：** 提出试点决定；按下一页到第12页老师声明，再结束放映。

### 第12页 | 4:52 - 5:00 | Groupwork management disclaimer

**用途：** 最后一页：展示已确认的小组贡献声明并致谢。

Our group contribution is twenty-five percent each. 【停1秒】 Thank you.

**操作提醒：** 老师原模板继续保留。Yi Han/yhan606、Xiao Lin/xlin031、Zhuyi Xia/zxia461、Zihang Zhang/zahz503，各25%已由用户确认，总计100%。

## 第8页：90秒操作表

| 时间 | 操作 | 评分人看到的证据 |
|---|---|---|
| 2:15 - 2:27 | 切到 Staff review，打开提前保存的新案件。指向状态栏、Missing 和禁用的分流按钮。 | 已保存状态和操作并列；检查未完成，不能交接。 |
| 2:27 - 2:49 | 打开 SAP financial reference，输入 60000002 和 Capture note，按 Query and save reference。此时未编辑人工审核草稿。 | 真实只读 SAP 来源/时间；保存后人工检查仍未自动勾选。 |
| 2:49 - 3:14 | 勾选三项人工检查；输入演示付款证据参考和 Review note；按 Save review。 | 人工记录与 SAP 参考分开；已保存结果变成可分流。 |
| 3:14 - 3:27 | 按 Send to standard queue。 | 案件进入本地队列，出现明确队列和责任角色。 |
| 3:27 - 3:45 | 切到 Track request，查询同一案件。展示队列状态，按 Download receipt。 | 跟踪页和 JSON 收据来自同一保存记录；退款决定仍未完成。 |

先打开 SAP financial reference 并保存参考，再编辑人工审核草稿；人工审核先Save后Send。整个闭环是案件准备和本地分流，退款审批及付款仍未完成。

## Mac启动与个人账号

1. Python 3.10或以上；解压App ZIP，在Terminal进入应用目录。
2. 运行 `sh start.command`，打开 `http://127.0.0.1:8789/`。
3. 按 `.env.example` 创建本机 `.env`：必须设 `AIRASSIST_SAP_MODE=live`，保留 `AIRASSIST_SAP_ACCOUNT_TYPE=personal` 和原 `AIRASSIST_SAP_BASE_URL`；填写你个人账号的 `AIRASSIST_SAP_API_KEY` 后停止并重启服务。只填密钥、仍保持 `unconfigured` 不会连接。课堂临时账号仅查看教程。
4. 不要分享 `.env`、SAP密钥或私人数据库。该应用运行不需要Node/npm。
5. 现场前用实际Mac完整排练。不要将Windows验收当成已经完成Mac原生启动验证。

## 演示案件与可复制内容

- Booking: `NZ7K2H`
- Family name: `Taylor`
- Reason: `Flight cancelled`
- Additional details: `Synthetic pitch case. No real passenger or payment data.`
- 新演示邮箱示例：`pitch.demo.20261009@example.com`；每轮完整演示使用新的合成邮箱，避免返回重复旧申请。
- 保存系统生成的AF-申请编号，提前在Staff review打开；另一个标签页打开Track request。
- SAP document: `60000002`
- Capture note: `Public SAP sample for demonstration only. Booking and payment are not verified.`
- Payment evidence reference: `DEMO-PAYMENT-REVIEW-NZ7K2H`
- Review note: `Synthetic evidence review for demonstration. Approval and payment remain pending.`

这些人工检查和付款参考仅为合成演示，不证明真实支付、退款资格或批准。

### 当前Windows电脑上的案例，不随ZIP交付

- ZIP排除私人数据库；Mac需重新创建新申请，不可直接输入这些编号并预期找到它。

## SAP超时备用（额外词，不属于267词主稿）

超过10秒还未返回时，说明当前调用不可用。显示提前准备且明确标注`Recorded response`的真实验收图，再继续本地审核流程。不要称旧响应为当前Live，不自动补造SAP数据。关闭或取消等待。

> The live query is unavailable. Here is a recorded response from our test.

SAP参考不自动完成任何人工检查；没有参考也不能冒充已经验证付款。

## 难词注音

大写部分是重读。采用音标和英文分音节提示，避免中文近似读音改变原词。

| 稿中词语 | 音标 | 重读提示 | 中文意思 |
|---|---|---|---|
| refund | /ˈriːfʌnd/ | REE-fund | 退款（名词读法） |
| request | /rɪˈkwest/ | ri-KWEST | 请求 / 申请 |
| passengers | /ˈpæsɪndʒəz/ | PASS-in-juhz | 旅客 |
| staff | /stɑːf/ | STAHF | 员工（只有一个音节） |
| input | /ˈɪnpʊt/ | IN-put | 已有输入 / 意见 |
| complex | /ˈkɒmpleks/ | KOM-pleks | 复杂的 |
| approval | /əˈpruːvəl/ | uh-PROO-vuhl | 批准 |
| integration | /ˌɪntɪˈɡreɪʃən/ | in-ti-GRAY-shun | 系统集成 |
| Credit Memo | /ˈkredɪt ˈmeməʊ/ | KRED-it MEM-oh | 贷项通知单 |
| reference | /ˈrefərəns/ | REF-uh-runs | 参考 / 引用 |
| financial | /faɪˈnænʃəl/ | fy-NAN-shuhl | 财务的 |
| unverified | /ˌʌnˈverɪfaɪd/ | un-VER-i-fyd | 尚未核实 |
| queue | /kjuː/ | KYOO | 队列（只有一个音节） |
| specialist | /ˈspeʃəlɪst/ | SPESH-uh-list | 专家 |
| workflow | /ˈwɜːkfləʊ/ | WORK-floh | 工作流程 |
| pilot | /ˈpaɪlət/ | PY-luht | 小范围试点 |
| readiness | /ˈredinəs/ | RED-ee-nuhs | 准备就绪程度 |
| contribution | /ˌkɒntrɪˈbjuːʃən/ | kon-tri-BYOO-shun | 贡献 |

## 提交前最后检查

- 自己按这份稿子计时至少一轮；必须在五分钟内，切页和操作算在总时间内。
- 第12页保留老师原模板。Yi Han/yhan606、Xiao Lin/xlin031、Zhuyi Xia/zxia461、Zihang Zhang/zahz503，各25%已由用户确认，总计100%；不要求签名。
- SAP数据来自个人账户访问的公开sandbox，是财务参考，不是AirNZ真实机票、已付金额或退款金额。
- 开发检查、浏览器验收和解压包启动各有边界；本轮V1.4结果详见小组核对及发布记录，不把旧版计数当新版通过。
- 已保留真实OpenCode原生构建会话导出和可运行App源码ZIP。原文要求App ZIP exported from OpenCode.ai，但没有规定某个导出按钮或命令；不能臆造特定按钮要求。
- 沿用已有员工访谈；没有新增A3真实旅客/员工研究要求，也没有新增研究承诺。不宣称客户批准或实际收益试点已经完成。

## 可选精简版：约60词/分钟

此版本为212词（同样不含提示），减少句子长度，仍覆盖同一12个主讲块。PPT和演示步骤不变。不要主稿、精简稿一起读；选择一种，从头计时排练。

按60词/分钟的理论估算，每个非演示块都留有停顿空间。五分钟和90秒操作是排练计划，尚未实测用户的实际演讲用时；最终以Mac排练计时为准。翻页可与句末停顿一起做，避免再添加一段长等待。词数不能替代计时。

### 精简第1页 | 0:00 - 0:17

AirAssist prepares refund cases for Air New Zealand. 【停1秒】 Here is one case.

### 精简第2页 | 0:17 - 0:34

After flight changes, 【停1秒】 we start with direct-booking refunds. Agent bookings follow another path.

### 精简第3页 | 0:34 - 0:53

Forms already have required fields. 【停1秒】 Earlier staff input shaped our checks and named review route.

### 精简第4页 | 0:53 - 1:11

Case preparation has a manageable scope. 【停1秒】 Staff retain decisions and approval. Payment needs later airline integration.

### 精简第5页 | 1:11 - 1:32

We used five design stages. 【停1秒】 Staff input shaped checks. We grouped actions and tested handoff and recovery.

### 精简第6页 | 1:32 - 1:53

The SAP API partly fits. 【停1秒】 Option Two keeps our refund process, sample journeys, and SAP financial references.

### 精简第7页 | 1:53 - 2:15

We read Credit Memo Request through a personal SAP account. 【停1秒】 Staff save source, time, and note. Payment stays unverified.

### 精简第8页 | 2:15 - 3:45

Here is a saved request. 【停1秒】 Missing checks block handoff. 【操作时停讲】 I add the SAP reference. The checks stay unchanged. 【操作时停讲】 I record and save the manual review. 【操作时停讲】 Now I send the case to its queue. 【操作时停讲】 Tracking shows the same status. The refund decision remains pending.

### 精简第9页 | 3:45 - 4:05

Saved status sits beside actions. 【停1秒】 Draft and version warnings protect work. Complex cases have specialist queues.

### 精简第10页 | 4:05 - 4:27

OpenCode helped build the workflow. 【停1秒】 We checked saved records, SAP errors, review recovery, and the app package.

### 精简第11页 | 4:27 - 4:52

A small pilot is next. 【停1秒】 The owner agrees the checks. We measure readiness, repeated work, and time. Please agree this scope.

### 精简第12页 | 4:52 - 5:00

Our statement is shown. 【停1秒】 Thank you.
