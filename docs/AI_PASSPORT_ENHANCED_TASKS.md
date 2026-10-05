# AI Agent Passport Enhanced 可执行任务清单

**Goal:** 在最新 upstream 的 Passport 上交付可读、可恢复的 PTT 与 Server/Agent 切换。

**Architecture:** 板卡内 UI/输入/配置模块适配硬件；Application 主任务拥有生命周期；Protocol 拥有跨传输语义；服务器拥有 Agent 权限与记忆。

**Tech Stack:** ESP-IDF 6.1（最低 6.0.1）、ESP32-C3、C++、LVGL、NVS、WebSocket、MQTT/UDP、Python host tests。

实施可使用 `superpowers:executing-plans` 按任务推进。本文是开发 backlog，不表示已完成或已有新增测试。每项以独立、可回滚提交完成；先编写能揭示风险的测试，再实现。预计时间在 M0 实测后制定。

基线：`0d576d3d4c049c6f55eaf879725dc23e516511b4`。详细设计、上限及验收：[路线图](AI_PASSPORT_ENHANCED_ROADMAP.md)。

## 优先级与当前状态

- P0：建立基线、保护音频/电源/配置、保证输入与显示可用，阻塞后续开发。
- P1：V1.0 所需 Settings、Server/Agent Profile 与发布 gate；依赖 P0。
- P2：可选增强；不阻塞 V1.0，不含路线图明确排除的功能。
- 当前仅两份开发文档已交付；以下全部实现任务均未开始。

## P0：第一批任务

### P0-01 可复现构建与资源/真机基线（最推荐首先实现）

**负责范围：** 新增 `docs/AI_PASSPORT_BASELINE.md`、`scripts/check_passport_budget.py`、`scripts/tests/test_passport_budget.py`；核查板卡 `config.json`、`partitions/v2/8m.csv` 与 `.github/workflows/build.yml`。本项先不改硬件/UI行为。

- [ ] 阅读[官方 Agent 开发教程](https://ai-passport.folotoy.cn/guides/create-a-play-with-agent/)及路线图第 21 节；区分编程 Agent 与运行时 Agent Profile，记录 FoloToy BSP 对照与本 fork 构建边界。
- [ ] 记录 upstream SHA、IDF 实际版本、Python/工具链版本、板卡/variant、配置与资产哈希；读取当前 sdkconfig 中 multiline/音频/OTA 相关开关。
- [ ] 在已安装的 IDF 环境执行 `idf.py --version` 与 `python scripts/build.py folotoy/ai-passport --name ai-passport`，保存 app/merged bin、ELF/map 与 sha256；没有 SDK 时明确记录阻碍，不用静态审查冒充编译。
- [ ] 对预算检查器先写超槽、余量不足、资产超限、合法配置的 host fixtures；解析分区和实际产物大小，输出可读报告，越界返回非零。
- [ ] 运行 `python3 -m unittest discover -s scripts/tests -v`，确认 host tests；只读报告接入 CI，首轮测量后启用合适 gate。
- [ ] 保留可恢复固件；确认 USB 数据线与串口权限、刷写偏移及配置影响。先展示固件和目标设备，取得刷写授权后再执行；社区固件预检为可选项。
- [ ] 真机完成当前点击聊天与音量、配网、断网恢复；测 internal/DMA heap、最大块、stack、TLS/录音/播放/OTA 峰值。
- [ ] 真机执行 60/360/2160 秒以及短按/长按/提前释放唤醒测试；电流无法测时留空并列入未验收，不填估计值。

**完成证据：** 可重建产物与资源表；一段完整语音与睡眠恢复日志；所有缺失测量标注。资源门槛不达标先调整预算/范围再进入 P0-02。建议提交：`test(passport): establish reproducible build and resource baseline`。

### P0-02 来源差异与授权审计

**负责范围：** 新增 `docs/AI_PASSPORT_REUSE_AUDIT.md`；实际复制代码后才创建 `docs/AI_PASSPORT_THIRD_PARTY_NOTICES.md`。

- [ ] 固定 FoloToy/kuyu/Kanna/larens SHA；列出 rounded display、多行文本、Settings 与按键相关路径。
- [ ] 与当前 `lcd_display.cc`、板卡及状态机逐项比较，区分已合入/可借鉴/不适用。
- [ ] 核查 LICENSE、文件头、字体/角色/音乐资产许可及 SDK/LVGL 依赖。
- [ ] 给每项写出最小移植方案与测试，拒绝无许可代码和未授权资产。

**完成证据：** 文件级差异与 license 登记，无整仓覆盖。依赖 P0-01。

### P0-03 圆角安全区与有界多行文字

**负责范围：** 新增 `main/boards/folotoy/ai-passport/passport_ui.{h,cc}`；必要时窄改 `main/display/lcd_display.{h,cc}` 与 `main/CMakeLists.txt`；新增 `tests/passport/text_layout_test.cc`、`tests/passport/CMakeLists.txt`。

- [ ] 先明确 host 测试 harness，纯逻辑与 LVGL/IDF 分离；验证 UTF-8 边界截断、空文本、长词、缺字及混合标点。
- [ ] 核查上游多行配置和现有单缓冲，复用换行；实现安全边距、最大文字区、翻页/滚动与最近 turn 上限。
- [ ] 检查最终中文字体与混合文本覆盖；以单个 PTT/STT/回答闭环验证第一版 UI，再加菜单/Profile。
- [ ] 用 20 个固定文本与真机截图核查顶栏/圆角/底部；测峰值 heap，不增加 framebuffer。
- [ ] 跑 host 测试、Passport 编译及 size gate；改共享显示则补代表性显示路径构建。

**完成证据：** 用例、截图、heap/size 对比；旧布局可通过配置回退。依赖 P0-01/02。

### P0-04 PTT 与按键/睡眠输入路由

**负责范围：** 新增 `passport_input.{h,cc}`、`tests/passport/input_test.cc`；修改 `ai_passport_board.cc` 的按钮注册；如必要窄改 `main/application.{h,cc}` 暴露按下/释放入口。

- [ ] 写事件序列测试：抖动、press/release、长按 UP 菜单、menu OK、同按键长按后 click、未知 ADC、多次唤醒。
- [ ] Home OK 按下开始采集、松开结束；菜单只确认；Speaking OK 先中断旧音频。
- [ ] 保留冷启动配网与整次 wake press guard；避免旧 click handler 重复 toggle。
- [ ] 100 次 PTT/菜单、软睡短按/长按、深睡提前释放验证；检查无误触和队列增长。

**完成证据：** 输入测试、真机循环与音频日志；按键变化写入用户文档。依赖 P0-01，和 P0-03 集成。

### P0-05 状态、错误与恢复

**负责范围：** `passport_ui.*`、`passport_input.*`、`tests/passport/ui_state_test.cc`；复用 `main/application.*` 与 `main/device_state_machine.*`。

- [ ] Listening/Thinking/Speaking 派生映射测试，覆盖 abort/超时/断网/认证错误。
- [ ] Thinking 不加入核心 DeviceState；合法转换与主任务调度，不从回调直接改 UI/状态。
- [ ] Wi-Fi、电量未知、服务器状态显示；恢复动作与超时明确，错误不永久阻止睡眠。

**完成证据：** mock 故障矩阵、真机拔网恢复，日志无凭据。依赖 P0-03/04。

## P1：V1.0 功能与交付

### P1-01 Settings 与持久化基础

**负责范围：** `passport_ui.*`；新增 `passport_profiles.{h,cc}`、`tests/passport/config_store_test.cc`；必要时修改 `main/settings.{h,cc}` 暴露写入错误。

- [ ] 双 bank/selector、schema、边界/引用校验、坏 bank 回退与未知版本行为先写 host tests。
- [ ] 真机 NVS 满页与每步断电；读回确认后提交 selector，失败保留旧 bank。
- [ ] Volume/Brightness/Theme/About 与 Wi-Fi 配网入口；调整合并写入，确认清除范围。
- [ ] 核查 16 KiB NVS 与 legacy 配置的共存容量；UI 不显示秘密。

**完成证据：** 掉电/损坏恢复、重启保留、写频率与容量记录。依赖全部 P0。

### P1-02 Server Profile 与 legacy/OTA 隔离

**负责范围：** `passport_profiles.*`、`tests/passport/server_switch_test.cc`；窄改 `main/application.*`、`main/ota.*`、`main/protocols/protocol.*`；配网页面具体路径在实现前从依赖定位并登记。

- [ ] legacy 迁移幂等；manual 与 legacy_ota 模式；URL/条目/总量校验。
- [ ] 先测试状态事务、busy 拒绝、认证失败、超时回滚、过期 generation 与析构回调。
- [ ] 主任务停止旧音频/连接、尝试新连接、成功再提交；失败恢复已知配置。
- [ ] OTA 不覆盖手工 Profile；保留现有 MQTT/UDP，用 WSS 完成初版新增服务器能力。
- [ ] 两个实际测试服务器来回切换 100 次，重启/断网/升级验证。

**完成证据：** 切换与回滚日志、凭据脱敏、旧 Profile/OTA 回归；没有服务端实测列为未验收。依赖 P1-01。

### P1-03 AI/Agent Profile 协商

**负责范围：** `passport_profiles.*`、`main/protocols/{protocol,websocket_protocol,mqtt_protocol}.*`；新增 `tests/passport/agent_profile_test.cc`、`tests/passport/mock_server.py`；更新协议文档的可选扩展章节。

- [ ] 固定 capability/request/ACK/error 规范；先确认目标服务器已有等价接口。
- [ ] 测旧服务器、unsupported、拒绝、重复/错 session/迟到 ACK、无效/超长消息。
- [ ] 双方协商后才发送，ACK 后才保存；不支持时禁用入口并说明。
- [ ] 服务端 fixture 独立检查权限与记忆隔离；服务器实现不混入固件仓库的模型逻辑。
- [ ] 验证 WS 与 MQTT 控制通道，UDP 音频不变；真实支持服务器验收至少一个。

**完成证据：** 双传输协议测试、旧服务兼容、实际 Agent 路由/授权记录。依赖 P1-02。

### P1-04 功耗/内存回归与 CI

**负责范围：** `.github/workflows/build.yml` 或新增独立 Passport workflow（实现前确定触发范围）、`scripts/check_passport_budget.py`、`tests/passport/CMakeLists.txt`、基线报告。

- [ ] 接入 host tests、Passport 构建、app/asset/partition budget artifacts；明确 docs-only 分支是否跳过编译。
- [ ] 共享代码变化补 C3/S3/显示/双协议构建，遵循上游 selection，不覆盖原 CI。
- [ ] UI/Profile 临时 allocation、最大内部块、stack、100 次切换、24h soak；按相同条件对比基线。
- [ ] 真机三档功耗、唤醒、电量缺失、配网常亮与超时退回；不把 CI build 当真机合格。

**完成证据：** 远端 workflow 结果、资源对比、soak 与仪表原始数据。依赖 P1-01/02/03。

### P1-05 V1.0 发布与恢复

**负责范围：** 新增 `docs/AI_PASSPORT_RELEASE_CHECKLIST.md`、`docs/AI_PASSPORT_RECOVERY.md`；板卡 README 的增强版入口；必要的第三方 NOTICE。

- [ ] 按路线图 10 条验收标准逐条收集证据，未通过项明确列出。
- [ ] 实测双 OTA 槽、启动验证/rollback 配置、USB 恢复、旧固件读取旧配置；不得先宣称自动回滚。
- [ ] 生成基线/增强固件校验和、配置与版本说明，排除秘密和未授权资产；交付可从 `0x0` 刷写的 merged bin，核对 bootloader/partition/app/资产布局，并分开说明合并刷写与 OTA 的配置保留行为。
- [ ] 真机完成屏幕/按键/声音/连接检查，再做离开电脑的单手使用验证；按版本保存固件、源码 SHA 和异常记录。
- [ ] 先候选版本，再完成真机验收后标记 V1.0；发布外部服务/上游 PR 的范围另行确认。

**完成证据：** 可用恢复包与操作记录、NOTICE、签字验收清单。依赖 P1-04。

## P2：可选增强

| ID | 任务与拟定路径 | 前提/验收 |
| --- | --- | --- |
| P2-01 | Profile 脱敏导入/导出；`passport_profiles.*` 与配网页面 | 无秘密导出，严格 schema/总量校验，拒绝未知引用 |
| P2-02 | 高级 MQTT broker/topic 编辑与独立 provisioning；协议/配网页面 | 服务激活约束清楚，实际 MQTT/UDP 回归与回滚 |
| P2-03 | 少量原创轻量主题；`passport_ui.*` 与资产构建 | license 清楚，flash/heap gate 通过，无背景音乐 |
| P2-04 | 可选延长待机时停止 Wi-Fi；板卡电源/协议 | 先重设计重连静默与计时器，电流实测有收益，无睡眠告警/自唤醒 |
| P2-05 | 通用修复独立贡献候选 | 从增强 UX 中分离，维护双协议/其他板卡；上游推送/PR 需另行授权 |

## 开发与证据规则

- 文件路径为拟定责任边界；新增路径需在实现前确认无冲突。不要编辑生成/vendor 文件，不改变现有引脚或板卡 OTA identity。
- 纯 C++ host tests 的 harness 在 P0-03 建立；在此之前不能把不存在的 test 命令当作已经可运行。Python build-tool 测试命令在基线存在。
- 每个任务提交记录：具体行为、固定源码来源、host/build/真机分别结果、资源对比、已知限制、回滚方式。
- gate 失败停止推进依赖任务；小块 revert，保留最佳已验证固件；不覆盖 fork main 的用户改动。
- 每两周或重要上游修复后同步并重跑受影响 gate。不要以任务勾选代替真实产物和日志。
