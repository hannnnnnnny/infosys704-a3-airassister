# A3 原始要求核对：数据、反馈、OpenCode 与贡献

日期：2026-10-09。依据用户提供的 **704_A3_2026 Build App_Specificatication and Marking Criteria_V3.docx** 原文、其五个 Hint 超链接和 **Groupwork Management Slide.pptx** 原模板。定位使用原文的栏目名称和评分表条目，避免不同提取方式造成段落编号偏移。

## 真实数据和真实客户反馈

原始V3没有明确要求真实Air New Zealand生产数据、真实客户访谈、一定数量的受访者、正式参与者可用性研究或已测得的业务收益。

App Design条目明确写：**“Apply Design Thinking to build the app.”** 并要求适配客户业务需要、具有视觉吸引力、说明A1/A2方案的修改；提示参考五阶段Design Thinking。原个人A1-D2已有员工材料，A2 V8的Table 1继续使用这些证据：内部可取得部分信息，现有在线表单也已有必填检查，准备问题应关注决策信息的整合和解释，而不只是缺少必填字段。

这些员工材料有间接退款接触及一份AI整理摘要的限制，并与小组成员访谈、GenAI访谈分别区分。它们可以复用为需求依据，但不能证明最终App已获直接Refunds团队接受。A3的实际设计反馈、界面迭代、开发测试和浏览器验收用于说明Prototype/Test；不冒充真实旅客参与者研究。**没有发现本次A3必须新增旅客或退款员工访谈的明文要求，因此不另加该任务。**

App Functionality条目明确写：**“Build a functional app with at least one working feature.”** 并要求遵循Labs中的Development Guidelines。正文对开发工具要求使用 **OpenCode.ai和SAP APIs**。要有真正可运行的功能和实际工具/API使用证据，但没有将生产AirNZ数据或真实付款列为要求。

因此，现有真实SAP公开sandbox读取和明确标识的合成预订可以作为原型证据。真实客户研究、生产数据和收益测量可增强说服力，但其缺席不能自动变成固定扣分项。前次回答将这些补强建议列为确定扣分理由，判断过严，现予更正。

## A3 与此前个人 A2 的关系

A3是四人小组作业；当前已知和复核的A2是用户／一位成员的个人作业，另外三位成员的A2未复核，不能把此前个人成果说成四人共同完成。老师的Option 1／2说明允许沿用一位成员的方案和模型，本次退款切片已获用户授权，不再另设范围审批门槛。

A2评分要求对问题、证据、过程和表达质量有参考意义；**本次强制交付、权重和展示规则以A3 V3及课程更新为准**。A2的个人Word报告、全套章节、视频露脸和20秒PechaKucha不会自动变成A3新增义务。对应连续性表见[Hint核对](A3_Hint_Link_Audit.md)。

## OpenCode 的导出要求

**Deliverables** 确实写了：**“Zip File of the functional App prototype, exported from OpenCode.ai”**，同时要求保留OpenCode内容直到评分结束。**Guidelines and Requirements** 说明需要访问OpenCode.ai，Lab提供访问说明。

文件没有规定特定导出按钮、网页dashboard、CLI命令或完整技术步骤。不能自行增加“必须用某个网页按钮”的条件，也不能仅因没用未规定的按钮就认定不合规。

当前事实：OpenCode CLI实际参与核心后端与测试生成，原生会话导出保留为JSON；包含该代码及后续修复的可运行源码ZIP由本地脚本打包。会话JSON与功能App ZIP是不同文件。对“exported from”的交付说明应保持清楚；当前证据没有证明老师要求某种专用导出方式，是否接受这套打包说明可由课程最终指导确认。这属于要求解释的保留，不是已证实的软件故障或固定扣分。

## Hint 超链接与 PPT 的关系

五个Hint的链接正文已逐一读取，并与主评分要求、实际应用和展示页对应，详见[Hint超链接逐项核对](A3_Hint_Link_Audit.md)。V1.4的[V1.4精修版PPT](AirAssist_A3_Client_Pitch_V1_4_Refined.pptx)中的主要位置为：

| Hint | 展示位置 | 证据口径 |
|---|---|---|
| [Effort Impact Matrix](https://thedigitalprojectmanager.com/productivity/impact-effort-matrix/) | 第 4 页 | 2×2 相对影响/工作量矩阵；属于定性选项判断，不是假装测得 ROI |
| [五阶段 Design Thinking](https://www.interaction-design.org/literature/article/5-stages-in-the-design-thinking-process) | 第3、5页，方案修改见第6页 | 复用个人A1-D2 Appendix C等已有员工材料；展示审核页面过长→分组检查／集中操作→开发复核的真实改进，不增加新访谈义务 |
| [SAP Strategic Approach](https://help.sap.com/docs/build-apps/service-guide/right-way-to-sap-build-apps) | 第 10 页及备注，实际功能见第 7–8 页 | 一般开发方法与逐步构建、测试对应；旧 SAP Build Apps 产品方法不覆盖老师更新的 OpenCode 工具要求 |
| [十项易用性原则](https://www.nngroup.com/articles/ten-usability-heuristics/) | 第8–9页演示及备注、本Hint核对表 | 对应实际状态、检查、操作和恢复机制；V1.3采用紧凑摘要、固定操作栏和可折叠上下文，没有宣称完整无障碍认证或参与者研究 |
| [Presentation techniques](https://slidepeak.com/blog/presenting-techniques) | 五分钟 SCR 主线、操作稿与排练安排 | 用清楚的故事、视觉和演示落实；实际声音、节奏和现场表现仍待观察 |

不需要在主讲中逐字讲完每篇网页。核心理由、设计过程和方案改动在主讲页表达；功能和易用性通过现场操作表达；详细来源和十项对应保留在备注及Hint核对文档供核对。网页的一般建议不能改变作业明文的五分钟限制，尤其不能套用通用 10/20/30 时长规则。

## 四人已确认贡献与老师模板

| 成员 | UPI / username | 已确认贡献 |
|---|---|---:|
| Yi Han | yhan606 | 25% |
| Xiao Lin | xlin031 | 25% |
| Zhuyi Xia | zxia461 | 25% |
| Zihang Zhang | zahz503 | 25% |

合计 **100%**。四人用户名与各25%已由用户于2026-10-09明确确认；不再是暂定值。本表不虚构成员签名或已完成的具体任务。

老师原模板已收到。[已确认声明页](Groupwork_Management_25_Percent_Confirmed.pptx)和V1.4第12页继续保留原声明；该页要求姓名、UPI、贡献百分比与总计100%，Comments可选。没有签名或逐项任务清单的明文要求。新版已使用全部确认资料，可选Comments为空。

演讲、操作、上传负责人按实际安排填写；这些交接责任与已确认贡献比例分开，不增加老师模板的强制字段。

V1.4最终PPT共12页、全部可见、手动翻页，已逐页原生渲染与目视核验，无裁切或重叠；20项[PPT结构／内容核对](PPT_REVIEW_V1_4.json)全部通过。第7页使用真实SAP返回的可编辑原生表格，保留只读来源、捕获时间和数据范围；第8–9页保留实际应用截图。末页老师原文、原生表格、四人姓名／UPI与各25%保留，Comments为空且可选。

完整267词讲稿7页、慢稿212词5页，全部12页视觉核验通过，见[讲稿核对](SCRIPT_REVIEW_V1_4.json)。PPT为7,767,885字节，SHA-256为`a0d177f09ee836ebeb4ca5c666e83e4041b27e1df6780241f6bdb1250cf6ef40`。这些文件检查不替代实际Mac、现场声音或五分钟计时。

## 自评的正确含义

此前185/200是更早的材料准备度估计，182/200是V1.3改进前的模拟复核；都不是老师成绩或V1.3的新评分，不能解释为固定扣15／18分，也不能把未开展新增真实客户研究当作明文缺项。正式评分应看方案理由、设计过程、实际功能、易用性和现场SCR表现的质量。现场语音、时间控制及实际演示尚未观察，因此不能预先保证某个分数。

相关文件：[V1.4精修版PPT](AirAssist_A3_Client_Pitch_V1_4_Refined.pptx) · [Hint链接核对](A3_Hint_Link_Audit.md) · [小组核对](A3_Group_Check.md) · [修订自评](A3_Marker_Self_Review.md)。本轮不部署；四人UPI与各25%已确认。V1.4当前49项后端（22.608秒）、28项前端、15项实际浏览器／收据、讲稿12页视觉核验、10项包检查与11项全新解压运行通过；最终PPT12页原生视觉核验与20项结构／内容核对通过。V1.3记录属于历史。实际Mac、真实演讲和Canvas上传仍与文件验收区分。
