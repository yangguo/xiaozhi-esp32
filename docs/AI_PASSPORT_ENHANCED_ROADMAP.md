# AI Agent Passport Enhanced 开发路线图

> 状态：设计与开发计划，尚未实现增强固件。核实日期：2026-10-05。本文的预算与验收阈值是拟定工程门槛，不是实测性能承诺。

## 1. 项目目标与定位

以 FoloToy AI Passport 为随身 Push-to-Talk（PTT）Agent 终端：按键说话、显示用户转写与回答、可靠恢复网络、切换服务器及 Agent。模型推理、长期记忆、工具权限与执行在服务器完成；ESP32 负责音频、显示、输入、连接和少量配置。

V1.0 优先可靠性、可读性与可恢复性。General、Coding、Japanese、Home Assistant、GitHub 等是服务器可配置的角色示例，不表示固件自带这些服务或其凭据。任何具有外部副作用的 Agent 工具，应由服务器执行权限控制与确认。

本次仅添加路线图和任务清单，不改变板卡、协议、固件、分区或上游仓库。

## 2. 基线与选择理由

- 上游：[78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)。基线 `main`：`0d576d3d4c049c6f55eaf879725dc23e516511b4`。
- 核实目录：[`main/boards/folotoy/ai-passport`](../main/boards/folotoy/ai-passport/README.md) 已存在。
- SDK：仓库 `AGENTS.md` 要求优先 ESP-IDF 6.1，最低 6.0.1；不支持 5.x。不得把旧社区 fork 的 SDK 配置直接搬过来。
- upstream 已包含板卡、三档省电、共享音频/协议/MCP/OTA 框架和构建 CI。复用现有模块比维护旧版核心分叉更容易同步修复。
- FoloToy 2.5.0 系列 fork 是屏幕适配等局部改动的参考来源，不能把它当作当前 upstream 的等价替代。后续移植先固定其提交并比较具体实现；版本号本身不证明稳定性。
- 本计划不沿用此前对“社区实现比例”或“无人实现 Profile”的未经完整调查结论。社区来源仅是候选实现，需核查兼容性、许可证及实际测试证据。

源码链接使用上述固定提交，可从 [基线树](https://github.com/78/xiaozhi-esp32/tree/0d576d3d4c049c6f55eaf879725dc23e516511b4) 定位各文件。后续更新本文必须记录新的基线 SHA。

## 3. 硬件约束与功能边界

| 项目 | 基线事实 | 对设计的约束 |
| --- | --- | --- |
| MCU | ESP32-C3，8 MB flash，无 PSRAM | 单核资源紧张，内部 SRAM 与 DMA 内存必须单独计量 |
| 屏幕 | ST7789/ST7789P3，240×320，SPI | RGB565 全屏约 150 KiB，不分配全屏双缓冲；圆角安全区真机校准 |
| 音频 | ES8311，输入/输出 24 kHz，共享 I2S 时钟 | 保持现有 codec 管理；默认半双工 PTT，播放时不持续采集 |
| 功放 | PA enable 未接 MCU | 无法通过固件保证关闭功放静态电流 |
| 电量 | CW2017，I2C 0x63，允许缺失 | 缺失显示未知，不阻塞启动；不能据 SOC 推断充电状态 |
| 按键 | UP/DOWN/OK，GPIO0 ADC 电阻梯 | 不是三条数字 GPIO；抖动、释放、长按与睡眠唤醒共享处理 |
| 接口 | USB Serial/JTAG，GPIO18/19 | 不改引脚，不误用 GPIO21 背光为默认 UART TX |

具体引脚、ADC 电压窗、LCD 极性以板卡 `config.h` 为准。ES8311 codec 默认地址宏为 8-bit 形式，直接 I2C 访问必须使用 7-bit 地址，沿用当前实现的转换。

明确不做：默认开启 wake word；AEC；camera；charging detect；4G/Ethernet；本地 LLM；无限聊天历史；背景音乐；大动画/商业角色素材；V1.0 动态安装插件或在设备保存 GitHub/家居平台长期凭据。未来改变此范围需单独评审硬件和资源证据。

## 4. 已核实的 upstream 能力

| 能力 | 源码入口 | 复用方式/限制 |
| --- | --- | --- |
| 板卡与构建参数 | `main/boards/folotoy/ai-passport/{config.h,config.json,ai_passport_board.cc}` | esp32c3、8 MB、PM enable、wake word 关闭；保持板卡身份与 OTA 兼容 |
| 音量/按钮 | `ai_passport_board.cc` | OK 当前是点击切换聊天；UP/DOWN 点击调音量，长按最大/静音；尚不是本计划的按住说话 UX |
| 省电与唤醒保护 | 同上、板卡 README | 60/360/2160 秒阶段；保留外围关闭顺序与整次唤醒按键吞掉机制 |
| 文本显示 | `main/display/lcd_display.cc` | `CONFIG_USE_MULTILINE_CHAT_MESSAGE` 分支已有换行；不等于 Passport 默认布局已满足安全区/分页需求 |
| 网络与协议 | `main/protocols/{protocol,websocket_protocol,mqtt_protocol}.*` | WebSocket 和 MQTT/UDP；共享语义放 Protocol，不能只改一个传输 |
| STT/TTS 与状态 | `main/application.*`、`main/device_state_machine.*` | 复用已有事件，UI 的 Thinking 是派生状态 |
| 配置/OTA | `main/settings.*`、`main/ota.*` | Settings 包装 NVS；OTA 可写 websocket/mqtt 命名空间，Profile 必须处理覆盖冲突 |
| MCP | `main/mcp_server.*`、`docs/mcp-protocol.md` | 是已有设备侧 MCP 框架，不证明服务器已支持 Agent 切换 |
| CI | `.github/workflows/build.yml`、`scripts/tests/` | 已有构建工具 host tests 和 board matrix；新功能仍需专门的 host/硬件测试 |

板卡 README 报告过部分真机验证，但也明确指出新版按键保护若干路径待重测、各阶段电流未实测。估算约 20 mA 软睡眠不能作为本 fork 的功耗验收数据。

## 5. 候选复用来源与移植纪律

| 来源 | 要研究的内容 | 决策原则 |
| --- | --- | --- |
| [FoloToy/folo-ai-passport-xiaozhi](https://github.com/FoloToy/folo-ai-passport-xiaozhi) | rounded display、安全边距与硬件适配 | 仅移植 upstream 缺少的布局差异，不覆盖新版电源/驱动 |
| [kuyu132/xiaozhi-esp32-folotoy-ai-passport](https://github.com/kuyu132/xiaozhi-esp32-folotoy-ai-passport) | multiline/responsive chat、文字适配 | 先比较当前 LVGL 换行；优先改进有界显示，不复制整套核心 |
| [Kanna1930/folo-ai-passport-xiaozhi-new-ui](https://github.com/Kanna1930/folo-ai-passport-xiaozhi-new-ui) | settings UX、音量/亮度、配网与唤醒交互 | 参考 UI guide 与代码；重新映射新版状态机，不把 host tests 当硬件验收 |
| [larens/ai-passport-xiaozhi-animalcrossing](https://github.com/larens/ai-passport-xiaozhi-animalcrossing) | 文本换行、气泡布局、左对齐思路 | 不搬背景音乐/角色资产；按字体实际宽度处理文字，不固定中文十字一行 |

每次复用前登记：源仓库、commit SHA、文件/函数、license、原创修改、验证结果和维护责任。本文列出的是研究方向，并不保证这些实现当前已完整验证或可直接编译；固定来源快照见文末。

## 6. V1.0 scope 与架构

V1.0 必须交付：可复现 Passport 构建与测量基线；圆角安全区及有界多行 STT/回答；Listening/Thinking/Speaking 与可恢复错误；PTT 按键；轻量 Settings（Volume/Brightness/Theme/Wi-Fi/Server/AI Profile/About）；至多 3 个 Server Profile、6 个 Agent Profile；原有省电与唤醒不退化；OTA、配置恢复与回滚方案。

建议新增板卡内 `passport_ui.*`、`passport_input.*`、`passport_profiles.*`；让 UI 和配置纯逻辑可在 host 测试。板卡只负责适配硬件。生命周期变更通过 `Application::Schedule()` 进入主任务，状态变化使用 `Application::SetDeviceState()`。核心不包含具体板卡头文件。

Profile 若需跨板卡能力，先定义通用小接口，再在 Application/Protocol 中接入；不把 Passport 页面对象放进核心。新源码要显式核查 `main/CMakeLists.txt` 的编译发现规则。共享改动必须验证其他受影响芯片/显示/传输路径。

## 7. Server Profile 设计

Server Profile 表示连接环境，包含：`id`、`name`、`transport`、`endpoint`、`credential_ref`、`provision_mode`、可选 `ota_url`、默认 Agent id。默认导入现有配置为 `legacy`；不能改变设备 UUID/板卡标识来模拟角色。

- V1.0 自定义新增连接先支持 WSS；现有 MQTT/UDP Profile 保留和验证。任意 MQTT broker/topic 的完整编辑放 P2，避免在小屏维护大量连接字段。
- `provision_mode` 明确为 `legacy_ota` 或 `manual`。前者允许激活流程获取协议配置；后者只使用配置过的 endpoint，并定义 OTA 只更新固件、不悄悄覆盖手工连接。API/实现需明确隔离当前 `ota.cc` 对全局命名空间的写入。
- 编辑 URL/凭据通过已有配网页面扩展完成，不用三键输入长地址。校验 scheme、长度和证书；生产默认拒绝明文 WS，开发例外须显式配置且 UI 可见。
- 切换只在 Idle、非 OTA、非配网执行；活跃对话提示结束后再切换。主任务停止采集/播放、关闭旧音频通道与传输、清队列，增加本地 session generation，再创建新连接。
- 候选连通、握手完成后才提交 active Profile。超时/认证失败恢复旧连接，展示原因；设备激活绑定失败须提示，不能假定不同服务共享 token。
- 按 generation + session id 丢弃旧回调/晚到音频。候选试用先留 RAM，重启恢复已提交配置；重试 1/2/4 秒，最多 3 次，之后等待人工重试，避免后台反复耗电。
- endpoint、token、设备 ID 对日志做脱敏；重连不得显示凭据。

## 8. AI/Agent Profile 设计

Agent Profile 包含 `id`、`name`、`server_id`、`agent_id`、`theme_id`、`locale`、`enabled`。模型、system prompt、MCP tools、memory namespace 和权限均由服务器将 `agent_id` 映射到自己的配置；固件不接收任意可执行提示或直接授予工具权限。

一个服务器可对应多个 Agent。菜单只显示当前服务器可用的配置；不存在的 server/agent 引用不能保存。切换采用先请求、等待 ACK、再修改当前显示和 NVS 的流程；重启后重握手，不能把本地名称当服务器确认。

V1.0 支持自建服务器的可选协商扩展。旧服务没有能力声明时，禁用同服务器 Agent 切换并提示“不支持”；仍可切到不同 Server Profile 的默认角色。不得宣称现有官方服务支持任意 `agent_id`。

## 9. 协议扩展建议（未实现）

先阅读 `docs/websocket.md`、`docs/mqtt-udp.md`、`docs/mcp-protocol.md`。保持原 hello、listen、abort、STT、TTS 和音频帧格式不变。拟定可选 capability `agent_profile_v1`，客户端和服务端双方确认后才发送：

```json
{"type":"agent_profile","action":"select","version":1,"request_id":"r42","session_id":"s1","agent_id":"coding"}
```

```json
{"type":"agent_profile","action":"selected","version":1,"request_id":"r42","session_id":"s1","agent_id":"coding"}
```

服务器也可返回 `action: "error"` 与稳定 `code`（unsupported/unauthorized/not_found/busy），不把内部异常直接放到屏幕。超时初值 5 秒；只接受匹配请求/当前会话 ACK。重复 request id 幂等；服务器先检查认证用户的 Agent 权限、隔离记忆，再确认切换。

在 Protocol 定义共享消息，WS 与 MQTT 控制消息都测试；UDP 音频格式保持不变。字段类型、消息大小（新扩展初值上限 1 KiB）、标识长度、UTF-8 和所有权都校验。未知字段兼容忽略，未知消息类型不得改变状态。若社区服务器已有等价协议，优先适配既有约定，避免维护第二套重复协议。

## 10. 状态机与并发

设备状态复用 `main/device_state.h`：Starting → Activating → Idle；需要配网走 WifiConfiguring；Idle → Connecting → Listening → Speaking → Idle 或 Listening，具体合法边由 `device_state_machine.cc` 决定。Upgrading/AudioTesting/Notifying 保留现有语义。

单独的 UI 状态 `Home/Menu/ProfileSelecting/Thinking/Error` 不新增到 DeviceState 枚举。Thinking 在本轮采集结束且等待响应期间派生，收到 TTS/abort/错误后清除；失败要通过合法状态转换回 Idle，不能直接从任意状态赋值。

Profile transaction 使用 `Idle → Validating → Disconnecting → Connecting → Committing`，失败进入 `RollingBack → Idle`；与 UI 状态独立。统一由主任务推进，网络/按键回调只排队；事件队列有界，过期 generation 丢弃，析构先取消回调，防止 use-after-free。

睡眠状态 `Active/Dim/SoftSleep/DeepSleep` 保持板卡管理。菜单交互重置活动时间，Profile 事务持有带超时的睡眠阻止条件，完成/失败必须释放；网络永不回复不能让设备永久保持高功耗。

## 11. NVS 配置模型与迁移

当前 NVS 分区仅 `0x4000`（16 KiB），不能无界保存 JSON。新增 namespace `passport`，所有 namespace/key 名 ≤15 字节；保持已有 `wifi`、`mqtt`、`websocket`、音量和亮度配置契约。

建议初版用 Settings 已有 string/int API：两个有界 JSON bank `cfg_a`/`cfg_b`，整数选择器 `active`。每个 bank 包含 `schema`、`generation`、payload 与完整性校验；单 bank 序列化上限初值 2 KiB。限 3 server/6 agent；name ≤48 UTF-8 bytes、id ≤32 ASCII bytes、endpoint ≤192 bytes、总 payload 上限优先于条目上限。

1. 启动校验 active bank 的 schema/长度/校验和/引用关系；损坏时读另一个有效 bank，均损坏则使用 legacy 默认并提示恢复。
2. 写 inactive bank、提交 NVS、读回验证，再写 active selector 并提交；断电测试每一步。CRC 只检测损坏，不提供认证。
3. Settings 当前析构提交且写 API 无错误返回；实现前补足可观察的写入/提交错误或建立直接 NVS 仓储，不假定成功。NVS page 耗尽要保留旧配置。
4. 首次迁移只读旧 namespace 生成 legacy Profile；重复启动幂等。未知高版本 schema 只读回退，不清空配置；迁移前保留可回退 bank。
5. volume/brightness 连续调整仅更新 RAM，停止操作后合并写入；显式保存和掉电行为写入 UX。

凭据通过独立短引用关联当前安全存储策略，不能借 JSON 预算无限扩张。评估 NVS encryption/flash encryption/secure boot、生产烧录流程及容量；未启用时 NVS 不提供秘密保护。凭据不导出到备份/About/日志，不提交到 Git。清 Wi-Fi 只清网络配置；恢复 Passport 设置只清其 namespace；全量恢复出厂需明确列出影响与二次确认。

## 12. UI 与三键交互

240×320 布局建议：顶部连接/电量/当前 Agent；中间小静态头像与 Listening/Thinking/Speaking 文本；底部最近 STT/回答区域。圆角安全边距从 12–16 px 开始真机校准，顶部图标与底部文字均必须完整可见。

使用 LVGL 字体实际像素宽度和 `LV_LABEL_LONG_WRAP`；中文、Latin 长词、emoji/缺字、混合标点测试；限制文字区域高度，采用分页/滚动，不让长回答遮挡顶部。保留最近一个 user/assistant turn，assistant 上限初值 2 KiB（按 UTF-8 边界截断并显示省略），不保存音频历史。合并快速 text 更新，减少 LVGL 重排。

| 场景 | UP/DOWN | OK | 长按/说明 |
| --- | --- | --- | --- |
| Home | 音量 ±10 | 按下采集，松开结束本轮 | 长按 UP 进入 Settings；取消原长按 UP 最大音量，写入迁移说明 |
| Speaking | 音量 | 按下中断并开始下一轮 PTT | 确保旧音频已停止；事件去重 |
| Menu | 移动/调整 | 点击确认 | 长按 OK 返回；此场景不启动 PTT |
| Profile 列表 | 选择 | 确认切换 | 长按 OK 取消；切换时输入锁定且可超时 |
| 文本浏览 | 明确进入浏览模式后翻页 | 退出浏览 | 避免同一按键同时调音量与翻页 |
| 软/深睡眠唤醒 | 任意键仅唤醒 | 任意键仅唤醒 | 吞掉整个按下至释放序列，随后新按键才能执行操作 |

PTT 与长按 OK 菜单冲突，因此 Home 进入菜单采用长按 UP。冷启动 OK 配网入口与上游一致；Home DOWN 长按静音可保留。只注册一套输入路由，避免旧 click 回调在 release 后又 toggle chat。ADC 多键不视为组合键；识别不确定时不动作。

Settings 的 Wi-Fi 页面先显示当前状态，再确认清除并重新配网；About 显示固件版本/基线、板卡、heap 和脱敏连接状态。Theme V1 只做内置轻量 light/dark。明确区分无网络、服务器不可达、认证失败、Agent 不支持和配置损坏。

## 13. 功耗策略

直接复用基线：最后按键后 60 秒降到 10% 背光、360 秒 soft sleep、2160 秒 deep sleep。均遵循 `CanEnterSleepMode()`；soft sleep 保持 Wi-Fi 与会话、CPU 最低 40 MHz，自动 light sleep 禁用。现有计时器 `skip_unhandled_events` 与自动 light sleep 组合会改变墙钟期限，不能直接打开该选项。

禁止在 UI 中直接抢 codec 开关；音频服务负责空闲释放。深睡保留 CW2017、ES8311、I2S/I2C 引脚释放、LCD、背光、GPIO holds 的关闭/恢复顺序。GPIO0 唤醒使用位掩码，不假设 C3 支持 EXT0/EXT1。

wake word 默认关闭；板卡文档报告打开后 heap 大幅下降，不适合 V1.0。配网非 Idle 状态可能持续亮屏，单独纳入测量；新方案若要降低配网功耗必须评审共享状态机。

真机测量 Active/Dim/Soft/Deep 的电流、连续语音电流及唤醒延迟；记录仪表、电池/USB供电、固件 SHA、Wi-Fi 条件与采样时间。未测量前不发布续航天数。唤醒短按、持续长按、深睡按键提前释放、冷启动 OK 均重新验证。

## 14. 内存与 Flash 预算（初值，基线测量后修订）

| 项目 | 设计预算/门槛 | 测量方式 |
| --- | --- | --- |
| LCD draw buffer | 保留当前 240×20×2=9600 B 单缓冲 | `lcd_display.cc` + heap caps；不分配 150 KiB framebuffer |
| 新 UI/Profiles 常驻增量 | ≤16 KiB，临时增量 ≤8 KiB | 相同场景与基线对比，包含对象/JSON/栈 |
| 文本/事件 | 2 KiB assistant，1 KiB user，事件队列初值 16 项 | 队列满时合并文本/丢过期事件，控制消息可靠处理 |
| 最低内部 free heap | 初值 ≥32 KiB，且较基线降低 ≤16 KiB | TLS 握手、录音、播放、切换、OTA 各场景采样 |
| 最大内部空闲块 | 初值 ≥16 KiB，并大于实际峰值单次请求 | heap_caps 最大块、分配失败回调、碎片化压力测试 |
| OTA app | 每槽 `0x2f0000`=3008 KiB；留 ≥128 KiB 余量 | ELF/map、app bin 与分区自动比对 |
| assets | 2 MiB，留 ≥10% 余量 | 构建产物计量，最小字体/图标 |
| NVS | 16 KiB，双 bank 与旧配置共同预算 | `nvs_get_stats`、最大配置与磨损/断电测试 |

不把 flash 8 MB 当运行内存。内存门槛若基线已经无法达到，先记录实测并评审修订，不能隐藏失败；优先减少资产、条目和临时 JSON，而不是扩大分区破坏 OTA。记录任务 stack high-water mark、内部/DMA heap、峰值队列与 OOM 情况。

## 15. CI 与测试计划

- 沿用 `python3 -m unittest discover -s scripts/tests -v`；新增 host tests 针对 UTF-8 截断/分页、按键事件路由、wake guard、Profile 事务/重入/超时、NVS 迁移/损坏/断电、协议字段/ACK/旧会话丢弃。
- 固定 ESP-IDF 6.1 镜像与构建配置，运行 `python scripts/build.py folotoy/ai-passport --name ai-passport`。先核查默认字体/资产/配置，再确定 enhanced variant；若增加 variant，同步 config.json/Kconfig/CMake/文档，保证唯一 `DECLARE_BOARD`。
- Passport PR：host tests + Passport 编译 + firmware/asset/partition size 报告；改共享代码再构建代表性 C3/S3 与受影响显示/传输。不要把全板矩阵每次作为最低 gate，按上游 CI selection 扩展。
- mock server 测试 WSS 与 MQTT/UDP：无扩展旧服务、成功 ACK、拒绝、延迟/重复/错 session ACK、断网、无效 JSON、超长消息、不同服务器激活约束。mock 结果和真实服务结果分别报告。
- 真机：ADC 校准、PTT、STT/TTS、音量/静音、菜单、圆角/字体、电量缺失、配网、断网恢复、三档省电、升级与降级。机密录音不作为公开 CI artifact。
- fork Actions 是否启用、是否允许手动运行和实际 workflow 结果需单独确认；本次 docs 分支推送不宣称 firmware build 已通过。

## 16. 里程碑与发布门槛

| 阶段 | 交付 | 退出门槛 |
| --- | --- | --- |
| M0 基线 | 固定 SHA/SDK/配置、固件与 ELF、heap/flash/电流记录模板 | 可复现构建，真机完成一次按键语音和软/深睡醒后语音；列明未测项目 |
| M1 可读与可靠输入 | 圆角安全区、有限多行文本、PTT、状态/错误、按键测试 | 文本不越界、wake press 无误触、音频压力不 OOM |
| M2 Settings | 音量/亮度/主题/About/重新配网、配置恢复 | 重启保留、清除范围正确、睡眠与菜单不冲突 |
| M3 Server Profile | legacy 迁移、手工 WSS、事务切换/回滚 | 旧连接恢复、OTA 配置不覆盖、旧数据不串入新会话 |
| M4 Agent Profile | 协商协议、ACK、权限/记忆隔离测试 | 支持服务器可切换；旧服务器清楚降级；双传输回归 |
| M5 V1.0 | size/资源报告、24h soak、发布说明/回滚包 | 全部验收签字并保留旧版可烧录固件 |

开发依赖：M0 → M1 → M2 → M3 → M4 → M5。P2 趣味 UI 不阻塞 V1.0，不用日期承诺代替硬件验收。

## 17. 风险与回滚

| 风险 | 防护与回滚 |
| --- | --- |
| 无 PSRAM + TLS/字体导致 OOM | 固定上限、资源 gate；关闭 enhanced UI 回到 stock layout，保留基线固件 |
| 旧 fork 与 IDF/LVGL API 不兼容 | 小块移植、不整仓 cherry-pick；按功能单独提交可 revert |
| Profile 与 OTA/认证耦合 | legacy 为默认；手工配置隔离；切换失败恢复旧 Profile |
| ADC 长按/唤醒误触 | 按下至释放测试；保留当前省电 guard，不使用固定短时间窗替代 |
| NVS 页耗尽/迁移断电 | 双 bank、容量预检、写后读回；不擦旧 namespace |
| 固件 downgrade 不认识配置 | 新 schema 仅隔离 namespace，旧固件可忽略；保留旧凭据和分区 |
| server 忽略扩展或工具越权 | capability + ACK + 服务端授权；禁用不支持的 Agent 切换 |
| 资产授权不清 | 用原创/明确授权资产；无法核实不合入 |

OTA 回滚先核查当前 bootloader rollback 配置与分区行为，再决定是否启用启动自检/mark-valid；未验证前不承诺自动回滚。始终提供 USB Serial/JTAG 重新烧录说明、分区匹配的已验证基线包和脱敏配置备份。不得自动恢复未经用户同意的跨服务器凭据。

## 18. V1.0 验收标准

1. 从干净 checkout 在指定 IDF 版本构建 Passport；产物记录 SHA/配置/size，两个 OTA 槽均可容纳 app，资源预算达标。
2. 中英混合/emoji/长段落至少 20 个固定输入用例，圆角无裁切、状态栏不覆盖、UTF-8 不破坏；长文本有明确截断/翻页。
3. 100 次 PTT 循环、100 次菜单进入退出、100 次 Profile 切换，无误触、崩溃、旧会话串音；不支持服务器不会显示“切换成功”。
4. 连通受控测试服务器时 Profile 握手目标 ≤10 秒；失败/超时 ≤15 秒进入清楚的回滚结果，不无限等待。真实网络性能单独记录。
5. 配置最大条目、满 NVS、两个 bank 损坏、每个写入步骤断电，均能保留旧配置或进入可配网默认状态，秘密不泄露。
6. 60/360/2160 秒在合法 Idle 条件下符合设定（容差 ±5 秒，不含启动时间）；各睡眠路径唤醒后完成语音，首次按键不动作；软睡唤醒显示目标 ≤1.5 秒。
7. 24 小时混合使用 soak 无 watchdog/reset/OOM；预热后重复相同静态场景，free heap 无持续下滑（初值总漂移 ≤4 KiB）；保存原始日志与故障计数。
8. 真机电流数据可重复，增强版软/深睡功耗不高于基线的 10%（同仪表/条件、考虑测量误差）；未实测不可发布续航结论。
9. 至少一个实际 WS 服务与一个实际 MQTT/UDP 服务完成语音回归；Agent 扩展在受控支持服务器通过 ACK/权限测试。mock 不替代实服务或硬件。
10. 许可证来源登记、回滚包、恢复说明、已知限制齐全。所有未通过项显式列出，不能标为 V1.0 完成。

## 19. 上游同步策略

本 fork `main` 保留为跟踪 upstream 的干净分支，本次文档在 `docs/roadmap`。未来增强代码用 `passport/enhanced`，小功能分支合入该开发线；只向 fork 推送。建议每两周及上游安全/协议修复时同步，不在本任务创建上游 PR。

```sh
git fetch upstream main
git switch main
git merge --ff-only upstream/main
git push origin main
git switch passport/enhanced
git merge main
```

`passport/enhanced` 首次需从 fork main 创建。仅未共享的工作分支允许 rebase；共享开发线默认 merge，不 force push。main 若存在用户独有改动，停止 fast-forward 自动流程并保留现状，不能 hard reset 覆盖。

同步后审查板卡省电、音频、状态机、Protocol、OTA、NVS、IDF/LVGL 变化；运行对应 gate，重记基线与预算。将通用 bugfix 与 Passport UX 分开，未来是否贡献 upstream 另行决定。

## 20. License / NOTICE 与来源管理

当前 upstream `LICENSE` 为 MIT，保留版权与许可文本。复制社区代码前核实该固定提交的 LICENSE、文件头及依赖；没有 license 或存在不兼容条款的内容不直接复制。仓库级许可证不能代替字体、图片、音频与角色资产的单独授权。

实际引入第三方代码/资产时新增 `docs/AI_PASSPORT_THIRD_PARTY_NOTICES.md`（或项目统一 NOTICE），记录 source URL、commit、原路径、作者、license、修改及必需声明；MIT 需要保留版权/许可，并非所有来源都要求根 NOTICE。仅研究思路与直接复制代码分开登记。Animal Crossing/西施惠等素材不因仓库开源而自动可再分发。

在当前阶段没有复制社区固件代码或素材，因此不添加声称已使用这些代码的 NOTICE。下面的来源清单用于后续核查与固定引用，不是已验证的集成清单。

### 当前来源核查记录

- kuyu：`main` 固定提交 `505b1d5307753d0d4aac6e8588bacc662b16334b`；读取 LICENSE（MIT）及 `main/boards/folotoy/ai-passport/ai_passport_board.cc`，确认回复区域宽度、左对齐、换行与超高滚动处理。可从 [固定源码](https://github.com/kuyu132/xiaozhi-esp32-folotoy-ai-passport/blob/505b1d5307753d0d4aac6e8588bacc662b16334b/main/boards/folotoy/ai-passport/ai_passport_board.cc) 复核。
- 通过远程 Git HEAD 固定候选快照：FoloToy `72da544d1b51678f5d88967adc299b3aec956946`；Kanna `7956ebf2ff1e39cde869cc3c4d6fbd0222d3b342`；larens `5d37484f016e4d6dc2db47a40ba1d446e905ec2f`。
- FoloToy/Kanna/larens：保留为候选研究来源；本次远程文件内容获取遇到 TLS 超时，未完成文件级/许可证核查。固定 HEAD 不等于验证代码功能；后续 P0-02 完成前不将其行为或素材视为可直接移植的已验证能力。

关联执行清单：[AI_PASSPORT_ENHANCED_TASKS.md](AI_PASSPORT_ENHANCED_TASKS.md)。
