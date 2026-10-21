# AI Passport 实时对话与服务器端 AEC 设计

状态：设计草案；未实现、未构建、未经真机验证。本文是本次唯一新增文件，不授权修改固件、服务端或 CI。

原核查日期：2026-10-18；新增证据核查日期：2026-10-21。代码快照：本仓库 `c22fdb2`，分支 `cursor/passport-realtime-aec-design`；`folo-xz` 为 `72da544`；`xz-server` 为 `eb9dc8c`；`mqttgw` 为 `c5e3235`。下文 `本仓库:` 指 `/workspace/xz-realtime/`，其它前缀分别指用户提供的三个只读参考仓库。新增前缀 `esp-webrtc:` 指 `/workspace/esp-webrtc/`（`espressif/esp-webrtc-solution @38b1750`），`esp-sr:` 指 `/workspace/ref/esp-sr-2.4.7/`（组件注册表 2.4.7 原包），`esp_capture:` 指 `/workspace/ref/esp_capture/`（1.1.1 原包，用户提供的 `~1.1` 解析版本；包内版本见 `esp_capture:idf_component.yml:40`）。行号均取自实际读取的文件；代码事实、设计建议、估算和未证实事项分开表述。

## 1 背景 / 目标 / 非目标

Passport 是 ESP32-C3、8 MB flash、无 PSRAM 的小型设备，音频为 ES8311 共时钟 I2S 全双工；板级定义见 `本仓库:main/boards/folotoy/ai-passport/config.h:9`、`本仓库:main/boards/folotoy/ai-passport/config.h:16`、`本仓库:main/boards/folotoy/ai-passport/config.h:19`。当前变体关闭唤醒词、启用多行字幕，见 `本仓库:main/boards/folotoy/ai-passport/config.json:4`、`本仓库:main/boards/folotoy/ai-passport/config.json:9`、`本仓库:main/boards/folotoy/ai-passport/config.json:12`、`本仓库:main/boards/folotoy/ai-passport/config.json:14`。

目标是在不改变其它板子行为的前提下，增加可选的“实时对话（实验）”：用户主动开始会话后，Listening 和 TTS Speaking 期间持续上传麦克风，由兼容服务器消除回声并检测插话。出厂、缺失设置和不支持的连接均保持现有非实时行为；按住 OK 1 秒说话仍可使用。持续上传不等于空闲时常开麦克风，也不等于服务器已经支持 AEC。

非目标：在 C3 上移植完整 AFE、第一阶段不做设备端 AEC/VAD、添加唤醒词、修改引脚/板身份/分区、扩大音频队列、承诺所有服务器兼容、把传统 ASR→LLM→TTS 自动变成端到端语音模型。本次仅交付设计，所有后续代码、测试和配置修改均属于未来实施任务。

## 2 现状分析与假设核实

### 2.1 硬件、构建与 UI

| 核实结论 | 实际证据 |
| --- | --- |
| C3、8 MB、无 PSRAM；板级采集/播放均为 24 kHz，共享 MCLK/BCLK/WS | `本仓库:main/boards/folotoy/ai-passport/config.h:9`、`本仓库:main/boards/folotoy/ai-passport/config.h:16`、`本仓库:main/boards/folotoy/ai-passport/config.h:19`；变体目标及 flash 见 `本仓库:main/boards/folotoy/ai-passport/config.json:4`、`本仓库:main/boards/folotoy/ai-passport/config.json:9` |
| Passport 使用 ES8311 派生 codec，驱动同时工作于输入输出模式；单麦单喇叭是本任务硬件前提，物理接线未进行真机核验 | `本仓库:main/boards/folotoy/ai-passport/ai_passport_board.cc:149`、`本仓库:main/boards/folotoy/ai-passport/ai_passport_board.cc:1260`；`本仓库:main/audio/codecs/es8311_audio_codec.cc:21`、`本仓库:main/audio/codecs/es8311_audio_codec.cc:49` |
| 当前有 1 秒 PTT，也有短按切换聊天；“默认按住说话”不能误写成“当前只允许按住说话” | `本仓库:main/boards/folotoy/ai-passport/passport_ptt.h:12`；`本仓库:main/boards/folotoy/ai-passport/ai_passport_board.cc:451`、`本仓库:main/boards/folotoy/ai-passport/ai_passport_board.cc:456`、`本仓库:main/boards/folotoy/ai-passport/ai_passport_board.cc:587`、`本仓库:main/boards/folotoy/ai-passport/ai_passport_board.cc:605`、`本仓库:main/boards/folotoy/ai-passport/ai_passport_board.cc:683` |
| 设置列表目前是亮度、主题、返回；亮度使用原有 display/brightness，主题持久化到 display/theme | `本仓库:main/boards/folotoy/ai-passport/passport_display.cc:609`、`本仓库:main/boards/folotoy/ai-passport/passport_display.cc:524`、`本仓库:main/boards/folotoy/ai-passport/passport_display.cc:568`；`本仓库:main/display/display.cc:45` |
| 字幕沿用现有分页布局，板工厂只有一个 | `本仓库:main/boards/folotoy/ai-passport/passport_display.cc:324`、`本仓库:main/boards/folotoy/ai-passport/passport_display.cc:338`；`本仓库:main/boards/folotoy/ai-passport/ai_passport_board.cc:1294` |
| CI 镜像需纠正：Passport 是 v6.1，Build Boards 是 release-v6.1，并非两者都写 v6.1 | `本仓库:.github/workflows/ai-passport.yml:22`；`本仓库:.github/workflows/build.yml:1`、`本仓库:.github/workflows/build.yml:22` |
| Passport CI 已执行主机测试、规范变体构建、体积报告；增长门限含 DRAM 8192 B、flash/固件 65536 B | `本仓库:.github/workflows/ai-passport.yml:27`、`本仓库:.github/workflows/ai-passport.yml:34`、`本仓库:.github/workflows/ai-passport.yml:41`；`本仓库:scripts/passport_size_baseline.json:9`、`本仓库:scripts/passport_size_baseline.json:11`、`本仓库:scripts/passport_size_baseline.json:12` |

### 2.2 Kconfig：假设基本成立，但设备 AEC 还有板型白名单

- `USE_AUDIO_PROCESSOR` 直接依赖 `(ESP32S3 || ESP32P4 || ESP32S31) && SPIRAM`，是完整 AFE 路径开关；此限制不能外推为 esp-sr 的独立 AEC/VAD/NS 算法均不支持 C3。证据：`本仓库:main/Kconfig.projbuild:988`、`本仓库:main/Kconfig.projbuild:991`。
- `USE_SERVER_AEC` 依赖 `USE_AUDIO_PROCESSOR`，所以间接受到相同芯片/PSRAM 限制；并不是服务器 AEC 算法理论上需要设备 PSRAM。证据：`本仓库:main/Kconfig.projbuild:1011`、`本仓库:main/Kconfig.projbuild:1014`。
- `USE_DEVICE_AEC` 同时要求 `USE_AUDIO_PROCESSOR` 和一组板型白名单，不能概括成满足芯片和 PSRAM 即可。证据：`本仓库:main/Kconfig.projbuild:997`、`本仓库:main/Kconfig.projbuild:1000`。
- 参考官方 Passport 固件同样保留这些依赖，不能以其存在为 C3 实时 AEC 已获支持的证据：`folo-xz:main/Kconfig.projbuild:451`、`folo-xz:main/Kconfig.projbuild:454`、`folo-xz:main/Kconfig.projbuild:463`、`folo-xz:main/Kconfig.projbuild:474`、`folo-xz:main/Kconfig.projbuild:477`。该参考变体目标/flash 见 `folo-xz:main/boards/folotoy/ai-passport/config.json:4`、`folo-xz:main/boards/folotoy/ai-passport/config.json:9`，ES8311 实例见 `folo-xz:main/boards/folotoy/ai-passport/ai_passport_board.cc:229`。

依赖精确锁定 `espressif/esp-sr ==2.4.7`：`本仓库:main/idf_component.yml:43`。本次实际读取原包，确认以下 C3 接口与构建证据：

| 核查项 | 实际证据与结论 |
| --- | --- |
| 独立 AEC 生命周期与块处理 | `afe_aec_create`、`afe_aec_process`、`afe_aec_get_chunksize`、`afe_aec_destroy` 分别声明于 `esp-sr:include/esp32c3/esp_afe_aec.h:46`、`esp-sr:include/esp32c3/esp_afe_aec.h:58`、`esp-sr:include/esp32c3/esp_afe_aec.h:65`、`esp-sr:include/esp32c3/esp_afe_aec.h:75`；create 接收输入格式、整数 filter_length、afe_type_t、afe_mode_t。输入只选首个麦克风和首个播放参考通道，见同文件 `esp-sr:include/esp32c3/esp_afe_aec.h:25` 至 `esp-sr:include/esp32c3/esp_afe_aec.h:35`；chunksize 注释表示每帧采样点数，见 `esp-sr:include/esp32c3/esp_afe_aec.h:61` |
| filter_length 注释与 C3 推荐值边界 | 同文件 `esp-sr:include/esp32c3/esp_afe_aec.h:38` 至 `esp-sr:include/esp32c3/esp_afe_aec.h:40` 只说明滤波器越长 CPU 负载越高，推荐 S3/P4 用 4、C5 用 2；**没有给出 C3 专属推荐值**，也未在此注明物理单位、合法范围。不能将 C5 的 2 写成 C3 推荐值；§7.1 的 1–2 仅为待验证试验建议 |
| 类型与低成本模式 | `AFE_MODE_LOW_COST=0` 见 `esp-sr:include/esp32c3/esp_afe_config.h:29`；`AFE_TYPE_VC=1` 注释为语音通信、16 kHz 输入、包含非线性噪声抑制，见 `esp-sr:include/esp32c3/esp_afe_config.h:36` |
| CMake 的 C3 目标与预编译库 | `esp-sr:CMakeLists.txt:1` 明确包含 esp32c3，`esp-sr:CMakeLists.txt:2` 将 TARGET_LIB_PATH 设为 IDF_TARGET；`esp-sr:CMakeLists.txt:57`、`esp-sr:CMakeLists.txt:58` 分别注册 libesp_audio_processor.a 和 libesp_audio_front_end.a |

本次实际执行符号检查（静态库没有可引用的源码行号，`T` 表示已定义的代码符号）：

```sh
nm -A -g --defined-only /workspace/ref/esp-sr-2.4.7/lib/esp32c3/*.a | rg ' (afe_aec_|vad_|ns_)'
```

结果：`libesp_audio_front_end.a` 的 `esp_afe_aec.c.obj` 定义 `afe_aec_create/process/get_chunksize/destroy`；`libesp_audio_processor.a` 定义 `vad_create`、`vad_create_with_param`、`vad_destroy`、`vad_process`、`vad_process_with_trigger`、`vad_reset_trigger`、`vad_trigger_alloc/detect/free/reset`，以及 `ns_create`、`ns_destroy`、`ns_pro_create`、`ns_process`、`ns_free`、`ns_init`、`ns_pro`，匹配项均为 `T`。这证实 C3 原包含候选独立算法接口及库内定义，**尚未编译链接、未真机测量**；不能据此断言依赖已完整链接或实时性能可用。

### 2.3 Application：SetAecMode“从未调用”是假设错误

| 项目 | 核实结果与证据 |
| --- | --- |
| aec_mode_ 初始化 | 构造函数按 CONFIG_USE_DEVICE_AEC / CONFIG_USE_SERVER_AEC 选择设备端/服务器端，否则 Off，两编译选项互斥；`本仓库:main/application.cc:25`、`本仓库:main/application.cc:28`、`本仓库:main/application.cc:35` |
| 默认 listening mode | AEC Off 对应 auto，其它 AEC 模式对应 realtime；`本仓库:main/application.cc:1275` |
| SetAecMode 调用 | **纠正**：仓库中已有大量调用，例如郑辰相机按键 `本仓库:main/boards/zhengchen/cam/zhengchen_cam_board.cc:149`，云聊启动恢复 `本仓库:main/boards/yunliao-s3/yunliao_s3.cc:237`。本次检索 Passport 无调用 |
| SetAecMode 行为 | 先直接写 aec_mode_，再 Schedule 切换设备 AEC、提示并关闭音频通道；不保存 NVS、不直接设置 listening_mode_；`本仓库:main/application.cc:1420`、`本仓库:main/application.cc:1422`、`本仓库:main/application.cc:1440`。因此调用者仍须在主任务调度，避免前面的直接写发生于按键任务 |
| Speaking 麦克风门控 | 非 realtime 时关闭 voice processing；realtime 只是保留此前已运行的上行，不能凭此保证任意路径进入 Speaking 都已启动采集；`本仓库:main/application.cc:1044`、`本仓库:main/application.cc:1059`、`本仓库:main/application.cc:1062` |
| PTT 模式 | StartListening 的事件处理显式使用 manual，不受 GetDefaultListeningMode 影响；Speaking 时先 AbortSpeaking 再 manual；StopListening 发 stop 并回 idle；`本仓库:main/application.cc:879`、`本仓库:main/application.cc:883`、`本仓库:main/application.cc:886`、`本仓库:main/application.cc:887`、`本仓库:main/application.cc:902` |
| TTS 状态 | tts.start 调度进入 Speaking；tts.stop 在 manual 下回 idle，否则回 Listening；`本仓库:main/application.cc:637`、`本仓库:main/application.cc:642`。Speaking 的下行才入解码队列，见 `本仓库:main/application.cc:567` |
| 打断缺口 | AbortSpeaking 只置标志和发消息，未自行清空播放队列；`本仓库:main/application.cc:1262`。实时 TTS stop 返回 Listening 时，如果音频处理已运行，也未必再次启动/重置解码；`本仓库:main/application.cc:1044`、`本仓库:main/application.cc:1055` |
| 上行发送 | 主循环在音频发送事件中取队列并调用 SendAudio，发送失败会清掉剩余队列；并非仅 Listening 才发送；`本仓库:main/application.cc:246`、`本仓库:main/application.cc:247`、`本仓库:main/application.cc:252` |
| 断连和状态 | 通道关闭回调调度回 idle；Listening↔Speaking 和回 idle 是合法转换；`本仓库:main/application.cc:583`；`本仓库:main/device_state_machine.cc:87`、`本仓库:main/device_state_machine.cc:92` |

### 2.4 AudioService 与 lite 路径

1. C3 选择 `LiteAudioEngine`，不是 AFE：`本仓库:main/audio/audio_service.cc:82`。lite 的 Feed 在 voice processing 开启时输出原始音频；多通道仅取首通道，按帧聚合，不实现回声消除；EnableDeviceAec(true) 仅警告。证据：`本仓库:main/audio/engines/lite_audio_engine.cc:35`、`本仓库:main/audio/engines/lite_audio_engine.cc:70`、`本仓库:main/audio/engines/lite_audio_engine.cc:168`、`本仓库:main/audio/engines/lite_audio_engine.cc:174`。OnVadStateChange 只是保存回调，本文件未触发它，故 lite 无实际 VAD：`本仓库:main/audio/engines/lite_audio_engine.cc:110`。
2. 输入、输出是独立任务；C3 分支栈分别 4096 B、2048 B；只有一个 `opus_codec` 任务同时编解码，栈 24576 B、优先级 2，并非一个编码任务加一个解码任务。证据：`本仓库:main/audio/audio_service.cc:143`、`本仓库:main/audio/audio_service.cc:151`、`本仓库:main/audio/audio_service.cc:160`、`本仓库:main/audio/audio_service.cc:163`、`本仓库:main/audio/audio_service.cc:170`。循环先尝试解码，再尝试编码，见 `本仓库:main/audio/audio_service.cc:393`、`本仓库:main/audio/audio_service.cc:465`；双工会增加同一任务负荷。
3. “播放时间戳记录仅在 CONFIG_USE_SERVER_AEC 下编译”**成立，但只针对入时间戳队列**：OutputData 后将非零 task.timestamp 放入有界 FIFO；`本仓库:main/audio/audio_service.cc:351`、`本仓库:main/audio/audio_service.cc:359`。下行 timestamp→解码任务、FIFO→编码任务、编码任务→上行包的赋值本身没有该宏保护，见 `本仓库:main/audio/audio_service.cc:405`、`本仓库:main/audio/audio_service.cc:579`、`本仓库:main/audio/audio_service.cc:475`。时间戳是服务器下行标记的回传，不是设备自行生成的采集时钟。
4. 帧长 60 ms、编码/播放 PCM 队列各 2 帧、解码队列 20 包、发送队列 40 包、时间戳 FIFO 3 项；编码满时丢最旧帧而不阻塞。证据：`本仓库:main/audio/audio_service.h:40` 至 `本仓库:main/audio/audio_service.h:46`；`本仓库:main/audio/audio_service.cc:585`。固定容量不意味着延迟必然合格。
5. EnableVoiceProcessing(true) 会 ResetDecoder 并重置重采样器，不能每个 TTS 包或每次 UI 刷新都调用；ResetDecoder 会增加播放 generation、清时间戳及待播队列，但无法撤回已经写入硬件的 PCM。证据：`本仓库:main/audio/audio_service.cc:713`、`本仓库:main/audio/audio_service.cc:720`、`本仓库:main/audio/audio_service.cc:802`、`本仓库:main/audio/audio_service.cc:806`、`本仓库:main/audio/audio_service.cc:812`；输出在锁外执行，见 `本仓库:main/audio/audio_service.cc:339`、`本仓库:main/audio/audio_service.cc:351`。
6. 官方参考固件同样只在服务器 AEC 宏下记录下行时间戳，并在编码任务回填：`folo-xz:main/audio/audio_service.cc:359`、`folo-xz:main/audio/audio_service.cc:405`、`folo-xz:main/audio/audio_service.cc:475`、`folo-xz:main/audio/audio_service.cc:579`；不能将这些共用代码视为其 C3 路径已启用 AEC。

### 2.5 hello、listen 与二进制协议

hello 的 `features.aec=true` 当前由编译宏决定，而非运行时 GetAecMode：WebSocket 见 `本仓库:main/protocols/websocket_protocol.cc:215` 至 `本仓库:main/protocols/websocket_protocol.cc:220`；MQTT 见 `本仓库:main/protocols/mqtt_protocol.cc:394`、`本仓库:main/protocols/mqtt_protocol.cc:395`。`listen.start` 的 mode 在 Protocol 共用实现中分别序列化为 realtime/auto/manual：`本仓库:main/protocols/protocol.cc:82` 至 `本仓库:main/protocols/protocol.cc:93`。参考固件相同语义见 `folo-xz:main/protocols/websocket_protocol.cc:205`、`folo-xz:main/protocols/protocol.cc:82`。

| 传输 | 线上格式、字节偏移（从 0 开始） | 证据 |
| --- | --- | --- |
| WebSocket v1（当前发送实现的其它版本分支也是裸数据） | 无自定义二进制头，整条 binary message 是 Opus；下行 timestamp=0 | `本仓库:main/protocols/websocket_protocol.cc:51`、`本仓库:main/protocols/websocket_protocol.cc:133` |
| WebSocket v2 | 16 B：version u16@0，type u16@2，reserved u32@4，timestamp u32@8，payload_size u32@12，payload@16；多字节有效字段为网络序，音频 type=0 | `本仓库:main/protocols/protocol.h:19`；`本仓库:main/protocols/websocket_protocol.cc:29`、`本仓库:main/protocols/websocket_protocol.cc:111` |
| WebSocket v3 | 4 B：type u8@0，reserved u8@1，payload_size u16@2，payload@4；没有 timestamp，下行置 0 | `本仓库:main/protocols/protocol.h:28`；`本仓库:main/protocols/websocket_protocol.cc:41`、`本仓库:main/protocols/websocket_protocol.cc:123` |
| MQTT/UDP | MQTT 控制，UDP 音频头 16 B：type u8@0，flags u8@1，payload_len u16@2，ssrc/连接标识 u32@4，timestamp u32@8，sequence u32@12；多字节字段网络序，头用于 AES-CTR nonce，随后是加密 Opus | `本仓库:main/protocols/mqtt_protocol.cc:228`、`本仓库:main/protocols/mqtt_protocol.cc:238`、`本仓库:main/protocols/mqtt_protocol.cc:303`、`本仓库:main/protocols/mqtt_protocol.cc:317`、`本仓库:main/protocols/mqtt_protocol.cc:351` |

WebSocket 版本读自 `websocket/version` 并写 Protocol-Version 请求头，不能只改 hello.version 期待自动协商：`本仓库:main/protocols/websocket_protocol.cc:79`、`本仓库:main/protocols/websocket_protocol.cc:83`、`本仓库:main/protocols/websocket_protocol.cc:104`。当前 v2/v3 下行解析直接转换头并使用声明长度，尚未先验证头长和 payload 边界：`本仓库:main/protocols/websocket_protocol.cc:108` 至 `本仓库:main/protocols/websocket_protocol.cc:138`；未来触碰该路径必须补齐输入校验，不把服务端视为可信内存来源。

### 2.6 为何不采用 esp-webrtc-solution

本设计保留小智协议和服务器端路线，仅借鉴音频参考路径，不整体移植 WebRTC 方案。

| 核查项 | 实际证据与结论 |
| --- | --- |
| `esp_peer` 预编译库无 esp32c3 | 实查 `components/esp_peer/libs/` 仅有 esp32、esp32s2、esp32s3、esp32s31、esp32p4、esp32c5、esp32c6、esp32c61，未见 esp32c3；构建按 `${IDF_TARGET}` 直接引用 `libpeer_default.a`，见 `esp-webrtc:components/esp_peer/CMakeLists.txt:30`、`esp-webrtc:components/esp_peer/CMakeLists.txt:32`。目录缺项没有可引用的源码行号；本次未尝试 C3 构建 |
| OpenAI demo 的 S3/P4 + SPIRAM 前提 | 默认板为 S3-Korvo-2：`esp-webrtc:solutions/openai_demo/README.md:19`；公共配置启用 SPIRAM：`esp-webrtc:solutions/openai_demo/sdkconfig.defaults:3`；S3/P4 配置分别设置 PSRAM：`esp-webrtc:solutions/openai_demo/sdkconfig.defaults.esp32s3:8`、`esp-webrtc:solutions/openai_demo/sdkconfig.defaults.esp32p4:5`。这些证明现成配置面向 S3/P4 + SPIRAM；“仅允许这两个目标”的硬性检查**未证实**，不把示例配置等同于库的全目标限制 |
| `capture_audio_aec_src.c` 限定 S3/P4/S31 | 已确认 1.1.1 原包的 `esp_capture:impl/capture_audio_src/capture_audio_aec_src.c:10` 为 `#if CONFIG_IDF_TARGET_ESP32S3 \|\| CONFIG_IDF_TARGET_ESP32P4 \|\| CONFIG_IDF_TARGET_ESP32S31`，该实现受此编译限定，不含 C3；这不否定 esp-sr 的 C3 独立 AEC 接口。依赖约束 `~1.1` 见 `esp-webrtc:components/esp_webrtc/idf_component.yml:8`；demo 调用 AEC capture source 见 `esp-webrtc:solutions/openai_demo/main/media_sys.c:70`、`esp-webrtc:solutions/openai_demo/main/media_sys.c:78` |
| WebRTC 传输不能直接替换小智协议 | `esp_peer` 使用 ICE/DTLS/SCTP/RTP/SRTP：`esp-webrtc:components/esp_peer/README.md:11` 至 `esp-webrtc:components/esp_peer/README.md:14`；demo 使用 SDP 和 Realtime HTTP 信令：`esp-webrtc:solutions/openai_demo/README.md:7`。小智使用 listen JSON 和自定义音频头：`本仓库:main/protocols/protocol.cc:82`、`本仓库:main/protocols/protocol.h:19`，另见 2.5 的 WebSocket 与 MQTT/UDP 格式。因此不能直接互通，整体采用需要另做服务端/协议适配 |
| OpenAI demo 的插话打断在服务器端 | **仍未证实**：本次再次递归搜索整个 `solutions/openai_demo`（含隐藏及忽略文件），`turn_detection`、`server_vad`、`input_audio_buffer`、`speech_started`、`interrupt_response`、`response.cancel`、`vad`、`interrupt` 均无匹配，命令见下。实际会话更新设置 realtime、output_modalities、instructions、tool_choice 和 tools，见 `esp-webrtc:solutions/openai_demo/main/webrtc.c:285` 至 `esp-webrtc:solutions/openai_demo/main/webrtc.c:302`；信令配置只显式给出 token/model/voice，见 `esp-webrtc:solutions/openai_demo/main/webrtc.c:654` 至 `esp-webrtc:solutions/openai_demo/main/webrtc.c:658`。JSON 分发处理 error、session.updated、函数调用、response.done，见 `esp-webrtc:solutions/openai_demo/main/webrtc.c:475`、`esp-webrtc:solutions/openai_demo/main/webrtc.c:484`、`esp-webrtc:solutions/openai_demo/main/webrtc.c:491`、`esp-webrtc:solutions/openai_demo/main/webrtc.c:504`。未发现显式打断配置/事件处理，不能从缺项推断服务器默认行为；demo 自身启用了本地 AEC capture，不能作为“无需本地 AEC”的证据 |

复查 demo 的实际命令（无匹配，`rg` 退出码为 1；负面搜索没有源码行号）：

```sh
rg --hidden --no-ignore -n -i 'turn_detection|server_vad|input_audio_buffer|speech_started|interrupt_response|response\.cancel|vad|interrupt' /workspace/esp-webrtc/solutions/openai_demo
```

### 2.7 许可

- **esp-sr**：已实际读取 2.4.7 原包 LICENSE：标题为 ESPRESSIF MIT License（`esp-sr:LICENSE:1`），授权适用于乐鑫产品（`esp-sr:LICENSE:5` 至 `esp-sr:LICENSE:10`），要求保留版权及许可声明（`esp-sr:LICENSE:12` 至 `esp-sr:LICENSE:13`），按原样提供并免责（`esp-sr:LICENSE:15` 至 `esp-sr:LICENSE:20`）。C3 算法以预编译静态库交付的证据见 §2.2 的 CMake 与 nm 核查；此结论不等同于已证明全部实现源码的公开状态，也不构成实时性能保证。
- **esp_capture 等多媒体组件**：本次实际读到 `av_render`、`codec_board`、`media_lib_utils` 的 LICENSE，均为 Espressif Modified MIT，限与乐鑫产品一起使用，保留版权及许可声明，并禁止面向非乐鑫产品再分发。证据分别为 `esp-webrtc:components/av_render/LICENSE:1`、`esp-webrtc:components/av_render/LICENSE:5`、`esp-webrtc:components/av_render/LICENSE:9` 至 `esp-webrtc:components/av_render/LICENSE:13`；`esp-webrtc:components/codec_board/LICENSE:1`、`esp-webrtc:components/codec_board/LICENSE:9` 至 `esp-webrtc:components/codec_board/LICENSE:13`；`esp-webrtc:components/media_lib_utils/LICENSE:1`、`esp-webrtc:components/media_lib_utils/LICENSE:9` 至 `esp-webrtc:components/media_lib_utils/LICENSE:13`。本次另行读取 `esp_capture` 1.1.1 原包 LICENSE，标题为 Espressif Modified MIT License（`esp_capture:LICENSE:1`），明确仅限乐鑫产品（`esp_capture:LICENSE:5`、`esp_capture:LICENSE:9`），须保留版权及许可声明（`esp_capture:LICENSE:10` 至 `esp_capture:LICENSE:11`），禁止为非乐鑫产品使用而再分发源代码或二进制（`esp_capture:LICENSE:12` 至 `esp_capture:LICENSE:13`）；免责条款见 `esp_capture:LICENSE:15` 至 `esp_capture:LICENSE:20`，SPDX 标识见 `esp_capture:LICENSE:22`。

## 3 目标服务器与兼容性

### 3.1 xiaozhi.me 官方服务

**未证实**：官方部署是否凭 `hello.features.aec=true` 加 `listen.mode=realtime` 对 Passport 原始麦克风做服务器 AEC，以及当前账号/模型/传输是否开放。本次所读固件只能证明客户端发信号，不能证明服务端执行算法。公开客户端文档确实涉及 AEC/realtime，因此“没有任何公开文档”也不准确；没有找到足以确认官方部署算法、时间戳语义和兼容范围的公开服务端契约。[公开上游说明](https://github.com/78/xiaozhi-esp32/blob/main/README.md)提及全双工与端到端模型，但不构成上述服务端 AEC 保证。

以真机抓包和双讲实验验收；优先确认 MQTT/UDP 或 WebSocket v2 是否提供非零下行时间戳。hello 成功或收到 realtime 回复均不算 AEC 成功。不支持时显示不可用并保持 PTT，不能静默以裸麦克风全双工替代。

### 3.2 xinnan-tech/xiaozhi-esp32-server

以下结论仅针对实际读取的 `eb9dc8c`。用户所述“v0.9.6+ 均如此”的版本范围**未证实**，本次未逐版本核验。

- 连接路径以字面 `endswith("?from=mqtt_gateway")` 判断，额外参数或参数顺序改变可能不命中：`xz-server:main/xiaozhi-server/core/connection.py:226` 至 `xz-server:main/xiaozhi-server/core/connection.py:230`。不是任意 WebSocket v2 客户端都能触发。
- hello.features.aec 设置 client_aec：`xz-server:main/xiaozhi-server/core/handle/helloHandle.py:50` 至 `xz-server:main/xiaozhi-server/core/handle/helloHandle.py:59`。网关来源且包长至少 16 时读取 @8 的时间戳、跳过 16 B 头、解 Opus，只有 timestamp>0 且 client_aec 才调用 _apply_aec：`xz-server:main/xiaozhi-server/core/connection.py:374` 至 `xz-server:main/xiaozhi-server/core/connection.py:409`。
- 算法 docstring 宣称互相关/Wiener/谱减，但实际所读主要实现是时间戳近邻起点、前后各两帧的对数功率谱匹配、频谱过减及残余压低。不能仅按注释称为成熟自适应 AEC：`xz-server:main/xiaozhi-server/core/connection.py:417`、`xz-server:main/xiaozhi-server/core/connection.py:439`、`xz-server:main/xiaozhi-server/core/connection.py:449`、`xz-server:main/xiaozhi-server/core/connection.py:490`、`xz-server:main/xiaozhi-server/core/connection.py:508`、`xz-server:main/xiaozhi-server/core/connection.py:516`。没有参考、参考不足两帧或低能量会原样返回，见 `xz-server:main/xiaozhi-server/core/connection.py:423`、`xz-server:main/xiaozhi-server/core/connection.py:429`、`xz-server:main/xiaozhi-server/core/connection.py:433`。
- 仅网关路径生成下行时间戳并缓存已解码下行 PCM，直连下行发裸 Opus；timestamp 实际取发送时刻的 Unix 毫秒模 2^32，并不是精确 DAC 播放时钟：`xz-server:main/xiaozhi-server/core/handle/sendAudioHandle.py:95` 至 `xz-server:main/xiaozhi-server/core/handle/sendAudioHandle.py:116`、`xz-server:main/xiaozhi-server/core/handle/sendAudioHandle.py:270` 至 `xz-server:main/xiaozhi-server/core/handle/sendAudioHandle.py:277`。
- **纠正“忽略 v2/v3 头”的含义**：直连不是正确去掉头后忽略其字段，而是把整条 binary 当 Opus 解码，固件带头帧可能解码失败；也没有按 hello.version 构造对应下行头。证据：`xz-server:main/xiaozhi-server/core/connection.py:375`、`xz-server:main/xiaozhi-server/core/connection.py:380`；`xz-server:main/xiaozhi-server/core/handle/sendAudioHandle.py:275`。
- VAD 立即打断要求 client_aec、have_voice、client_is_speaking、listen mode 非 manual；普通识别文本触发的打断是另一条稍晚路径：`xz-server:main/xiaozhi-server/core/handle/receiveAudioHandle.py:17` 至 `xz-server:main/xiaozhi-server/core/handle/receiveAudioHandle.py:34`、`xz-server:main/xiaozhi-server/core/handle/receiveAudioHandle.py:90`。服务端打断清队列并只发普通 tts.stop：`xz-server:main/xiaozhi-server/core/handle/abortHandle.py:9` 至 `xz-server:main/xiaozhi-server/core/handle/abortHandle.py:19`。

设计基线为“设备 MQTT/UDP → 网关 → 指定提交服务端”，直连该服务端的 WebSocket v1 可作 PTT 对照；v2/v3 不列入已兼容项。给直连 URL 人工加网关标记不是完整协议适配，不推荐作为正式方案。

### 3.3 78/xiaozhi-mqtt-gateway

已确认双向透传时间戳，但不是逐字节透传整个头：

| 方向 | 实际行为与证据 |
| --- | --- |
| 下行 WS→UDP | 读 WS @8 timestamp、@12 Opus 长度、取 @16 payload，再交 sendUdpMessage；`mqttgw:app.js:85` 至 `mqttgw:app.js:91`。新 UDP 头在 @8 写回 timestamp，@12 写自己的 sequence，然后加密；`mqttgw:app.js:338` 至 `mqttgw:app.js:357` |
| 上行 UDP→WS | UDP 收包读取 @8、@12 并传入连接；`mqttgw:app.js:651` 至 `mqttgw:app.js:661`。解密后 bridge.sendAudio(payload,timestamp)，创建 16 B 头并在 @8 写 timestamp、@12 写 Opus 长度；`mqttgw:app.js:442` 至 `mqttgw:app.js:459`、`mqttgw:app.js:125` 至 `mqttgw:app.js:131` |
| hello | 桥接保留 audio_params/features，宣称 version=2；`mqttgw:app.js:60` 至 `mqttgw:app.js:82` |

网关创建的上行头前 8 B 为零，并非固件严格 v2 的 version/type 头；服务端的网关专用头也不等同于严格 v2，不能混用解析器。网关连接直接使用配置的 chatServer URL，未在此处自动追加来源标记：`mqttgw:app.js:73`；部署必须核验实际 URL 的字面后缀。

## 4 方案设计

本章均为未来实施建议，不表示当前功能已经存在。

### 4.1 Passport 专属编译能力与共用边界

新增建议符号 `PASSPORT_REALTIME_AEC_EXPERIMENTAL`，默认 n，依赖 `BOARD_TYPE_FOLOTOY_AI_PASSPORT && IDF_TARGET_ESP32C3 && !SPIRAM && !USE_DEVICE_AEC`。不 select USE_AUDIO_PROCESSOR，不放宽既有 AFE/设备 AEC 依赖。编译为 y 只提供菜单与能力，运行时仍默认关闭；验证稳定后是否在标准 Passport 变体编入能力，由用户决定。

预期实施触点为 Kconfig、Passport board/display、共用 Application/AudioService/Protocol 的最小能力接口；core 不包含具体 Passport 类或 config.h。共用行为分支须由此能力且运行时生效条件约束，原 USE_SERVER_AEC 板子仍维持原行为。若增加发布变体，必须补齐 config.json→build.py→Kconfig→CMake 的选择链，并维持同硬件 OTA 身份与唯一 DECLARE_BOARD；本方案不需要新硬件板身份。

明确三种值：编译能力、NVS 用户偏好、当前会话有效模式。有效条件为能力开启、用户偏好开启、传输/服务器配置已验证。未知服务器默认不进入有效 realtime；用受控的服务器配置档描述时间戳和 stop 语义，不仅按域名推断。不支持时不改写用户偏好，但当次以 Off/PTT 启动并提示。

### 4.2 运行时开关、NVS 与 hello

设置增加“实时对话（实验）”，关闭/开启；说明开启后需再主动开始会话。新增 namespace/key 建议 `passport/rt_aec`，u8 布尔默认 false，仅用户确认改变时写入，缺失/非法值按 false。旧版本忽略新键；不迁移或覆盖 display/brightness、display/theme。现有 Settings 的 bool 读写和析构提交语义见 `本仓库:main/settings.cc:70`、`本仓库:main/settings.cc:82`、`本仓库:main/settings.cc:12`；后续实现必须设计写失败的提示/恢复，不能把当前 ESP_ERROR_CHECK 当成可恢复错误返回。

菜单只在空闲且无活动录音/待响应会话时切换。按键回调调度到主任务，依次取消 PTT arm/旧手势、保存偏好、调用 `SetAecMode(kAecOnServerSide 或 kAecOff)`；能力初始化完成后再恢复偏好，首次 hello 前完成生效。SetAecMode 自身已有内部 Schedule，外层不能立即假定关闭已完成，也不得在其间发新 hello；增加完成状态或在通道关闭回调后解除切换锁。启动恢复避免无意义提示/重复关通道。

Passport 的 hello 在会话有效服务器 AEC 时才发 features.aec=true，关闭时省略；WebSocket 与 MQTT 共用同一判定，旧板子的编译宏语义不变。模式切换必须关闭并重建会话，不能只发 listen.start，因为所查服务端 hello 只会把 client_aec 置 true，未见清 false 的分支。必要时重新创建协议连接以确保服务端连接对象重置。显示偏好与实际会话状态的差别，不能显示“AEC 成功”。

### 4.3 lite 路径时间戳与对齐

复用现有 `AudioStreamPacket.timestamp` 和有界 FIFO，不引入 PCM 回声参考缓存到设备，也不生成设备 uptime 代替服务器标记：

1. 在原 `CONFIG_USE_SERVER_AEC` 之外，为 Passport 编译能力提供记录路径；Passport 仅有效实时会话记录，其它板子的条件保持原样。
2. WS v2 或 MQTT/UDP 接收下行标记，经解码/重采样保留到 AudioTask；在实际 OutputData 边界记录“已提交播放”的下行标记，再随原始麦克风 60 ms 帧进入编码任务、Opus 包和上行头。v1/v3 没有时间戳，不能宣称实现了这个 AEC 路径，也不私自扩展其头。
3. 第一阶段采用现有至多 3 项 FIFO 回传语义，overflow 丢最旧，underflow 发 0，零值不排队；不重复无限复用最后一个 timestamp。服务器无参考、播放开始/结尾、抖动时的零标记单独统计。60 ms 下行帧长是基线，帧长不一致时不直接声称一对一对齐，需固定协商帧长或进入后续基于时间窗口的匹配方案。
4. timestamp 表示回声参考帧标签，不是可信绝对采集时间，也不能简单把本机时间与服务器 Unix 时间相减作为延迟。OutputData 返回并不等于声波到达麦克风；I2S DMA、codec、声学传播和采集聚帧存在偏差，必须测量 FIFO 策略能否落在服务端 ±2 帧搜索范围内。
5. 开关、断连、通道重开、PTT 切换、abort、ResetDecoder 均清掉旧 timestamp 和旧会话音频；为锁外 OutputData 的迟到完成附会话/播放 generation 校验，防止 ResetDecoder 后旧任务重新放入标记。发送/编码中的旧帧也须有会话归属或明确清理，不能只清 FIFO。
6. 32 位标记按不透明值回传，客户端不进行有符号时间排序。服务器近邻算法目前按普通绝对差比较，绕回场景需服务端修复或测试确认；不以客户端自增编号绕过问题。

WebSocket v2 进入实验前校验 len≥16、version/type、payload_size 与剩余长度一致及合理上限；v3 原兼容路径校验 len≥4 和长度。拒绝截断、超长、错误类型帧并计数，不原地改写只读接收数据。UDP 保持已有长度/类型/序列检查与 AES nonce 布局。协议层负责线上格式，AudioService 负责播放与采集关联，板层只管理偏好/UI。

### 4.4 实时会话、按键与结束语义

| 场景 | 建议行为 |
| --- | --- |
| 实验关闭 | 保留当前短按聊天和 1 秒 PTT；PTT 为 manual，松开结束上传；默认体验不变 |
| 实验开启但尚未开始 | idle 不上传；OK 短按开始有效 realtime 会话 |
| 实时 Listening | 持续上行，服务端 VAD/ASR 切句；OK 短按结束会话并关通道，不以 manual stop 代替结束 |
| 实时 Speaking | 保持上行；服务器插话事件停止当前播放并回 Listening；OK 短按作为确定可用的人工打断，清待播音频、通知服务器，继续 Listening |
| 实时下长按 OK 1 秒 | 显式进入当次 manual PTT：先结束旧 realtime 通道/清队列，再以 aec=false 的新连接开始 manual；松开停止，当前 manual 回复期间关闭上行。偏好仍为开启，下次短按才回 realtime |
| 长按连接中松开 | 记住 release，连接成功不遗留持续采集；复用/扩展现有 PTT 取消规则，并吞掉该长按产生的 click |
| 设置、上下键、软睡眠 | 保留双击菜单和音量/亮度等原规则；菜单手势不能误开麦。活动实时会话禁止软睡眠；断网/错误/用户结束后先停采集、清队列再恢复省电，不自动重开麦 |

实时保留采集必须覆盖所有会话入口，不依赖前一状态“碰巧启用”。不对系统通知、配网测试、升级等非会话播放开放上传。所有状态变化经 SetDeviceState 与状态机，所有回调涉及应用状态都先 Schedule；UI 显示“等待中”不新增 Thinking 设备状态。

### 4.5 服务器打断与正常 stop 的歧义

当前 xz-server 的 abort 和正常结束均用 tts.stop；设备无法可靠区分，不能通过“刚才麦克风有声音”推断，因为 lite 没有 VAD。把 stop 一律立即清队列会截掉预缓冲的正常尾音；一律 drain 则插话仍可能继续播约秒级积压。

设计采用按服务器配置档选择策略，并把该问题列为启用门槛：

- 推荐明确的服务器打断原因/播放段标识：双方约定独立 abort 消息或 tts.stop 的可选 reason，打断清队列，正常 stop drain；这是未来服务端适配，不是当前所查服务器已有能力。JSON 缺失字段沿原兼容逻辑，不影响其它板子。
- 对未经修改的 eb9dc8c，实验配置档只能选择“realtime 的所有 tts.stop 立即清队列”。必须测正常尾音损失；若超过第 6 节门限，则判该组合不通过，保持 PTT，不能带着已知截音宣称完成支持。另一备选是服务端按已播放进度发送正常 stop，仍需服务端改动，单靠网络发送完毕不够。
- 清队列复用 ResetDecoder 的 generation 保护并覆盖锁外输出、重采样和时间戳；中断声卡已提交 PCM 的上限需测量。人工 OK 打断明确意图，可以本地立即清队列，无需等服务端 stop。旧连接/旧段迟到音频不得进入新会话。

因此“持续上传”可先验收，“自然语音打断且无截音”须额外通过端到端验收，二者不是同一完成标准。

### 4.6 状态栏与中文字形核查

沿用现有状态栏，不增加占用字幕区的第二行。开启偏好用短标记 `RT`；实际实时录音显示 `RT 聆听中...`，播放且仍上传显示 `RT 说话中...`；无活动会话仅标记偏好，不暗示麦克风已开。错误/电池告警优先，时钟刷新不得覆盖活动提示。菜单完整名称拟为“实时对话（实验）”，提示拟为“开启 / 关闭”；字形不齐时回退 `Realtime (Exp.)`、`On / Off`，不得靠网络字幕动态补字保证本地设置可读。

实际检查结果：CMake 选择 `font_noto_sans_basic_20_4`，依赖声明为 `78/xiaozhi-fonts: ~2.0.0`，见 `本仓库:main/CMakeLists.txt:848` 至 `本仓库:main/CMakeLists.txt:852`、`本仓库:main/idf_component.yml:40`。本地两个固件仓库及 /tmp、/opt 中未找到该字体源文件/生成的 cmap，managed_components 未展开。因此本次无法直接验证**本地最终链接版本**。

为尽量完成字形核查，另外只读检查了字体上游 [basic 字符集（890 个码点）](https://raw.githubusercontent.com/78/xiaozhi-fonts/main/charsets/basic.json)与 [20px/4bpp 字体源的生成字符范围](https://raw.githubusercontent.com/78/xiaozhi-fonts/main/src/font_noto_sans_basic_20_4.c)。以下结果来自该上游 main 快照，不伪装成本地字体文件行号，也不代表将来构建解析到的精确版本。文案存在不等于有字形。

| 文案所需字（去重） | 上游 basic 核查结果；本地精确版本均待复验 |
| --- | --- |
| 实、时、对、话、验 | 有：时、话；缺：实 U+5B9E、对 U+5BF9、验 U+9A8C |
| 开、启、关、闭 | 均有；本地文案见 `本仓库:main/assets/locales/zh-CN/language.json:50`、`本仓库:main/assets/locales/zh-CN/language.json:51` |
| 聆、听、中、说、话 | 均有；本地状态文案见上述 language.json `本仓库:main/assets/locales/zh-CN/language.json:26`、`本仓库:main/assets/locales/zh-CN/language.json:27` |
| 等、待 | 均有，与 `本仓库:main/boards/folotoy/ai-passport/README.md:205` 至 `本仓库:main/boards/folotoy/ai-passport/README.md:207` 的记录一致 |
| 思、考 | 均缺：思 U+601D、考 U+8003。README 同处记录公共资产字体包含，但本次未核验公共资产字体；继续用“等待中...” |
| 设、置、亮、度、主、题、返、回、短、按、确、认、上、下、选、择、长 | 有：设、度、下；其余缺失。字符串来源为 `本仓库:main/boards/folotoy/ai-passport/passport_display.cc:23` 至 `本仓库:main/boards/folotoy/ai-passport/passport_display.cc:34`，说明原菜单也需要资产字体或补字 |
| ASCII RT、点号、括号 / 全角（ ） | ASCII 均有；全角 U+FF08/U+FF09 均缺，使用 ASCII 括号可避开这两个缺字 |

实施第一阶段必须在依赖下载后的只读字体 cmap 或 LVGL `get_glyph_dsc` 中逐字符检查，分别关闭 fallback、启用实际资产字体后检查，并记录组件精确版本、缺字列表。对“实时对话（实验）”至少准备“实、对、验”及括号的补字/回退方案；其它本地菜单也要统一核查。内置字体缺字时只补最小自有字体资源或用 ASCII 回退，不手改 managed_components/生成 mmap。资产字体更换/缺失/启动未加载时都要可读。最终链接版本复验前，不承诺菜单中文能够完整显示。

### 4.7 调试计数器

建议固定大小计数，按会话清零并保留累计值，每 5 秒或会话结束聚合日志，禁用逐帧日志和原始录音落盘。覆盖：Speaking 采集/上行帧数、timestamp 非零/零/溢出/欠载/过期丢弃、编码/发送/解码丢帧、队列峰值、收包校验失败、Opus 编解码耗时最大值/分桶、手动/服务器打断次数、stop 到播放静默耗时、空闲误上传、最小空闲堆/最大连续块/任务栈余量。只有明确 reason 时才能准确计“服务器打断”；旧服务端普通 stop 计为“stop 原因未知”。

## 5 C3 资源与性能评估

以下新增资源/吞吐/延迟均为**估算**，不是实测承诺。静态链接体积与运行时堆必须分开看。

| 项目 | 估算及依据 |
| --- | --- |
| 16 kHz、单声道、16 位上行 PCM | **估算** 32,000 B/s，60 ms 一帧 1,920 B；2 帧编码积压约 3,840 B，不含 vector/队列元数据 |
| 24 kHz 硬件 PCM | **估算** 每个方向 48,000 B/s、60 ms 2,880 B；两路 PCM 约 96,000 B/s，不等于 I2S 总线实际 slot 比特率 |
| 下行待播 PCM | **估算** 2 帧约 5,760 B，加正在输出的一帧约 2,880 B；解码瞬时及重采样临时缓冲另计 |
| Opus 网络 | 若采用 24–32 kbit/s 负载作为假定，**估算** 每方向 3–4 KB/s，双向 6–8 KB/s；实际编码码率尚待运行时测量，不把该假定当配置事实 |
| 头部 | 60 ms 约 16.7 包/s；v2/UDP 各 16 B 头，**估算** 每方向约 267 B/s，不含 IP/TCP/UDP/TLS/MQTT 开销 |
| 时间戳与计数 | 复用 3 项 FIFO，纯值 12 B；**估算** 新计数、generation/标志和模式状态约 0.25–1 KiB 静态 DRAM，不新增任务栈 |
| 运行时增量 | **估算** 相对半双工多出的重叠 PCM/编码/重采样/网络缓冲峰值约 8–24 KiB，须用堆和连续块实测推翻或确认；不由 DRAM +8 KiB 链接门限覆盖 |
| flash | **估算** 控制/UI/计数逻辑约 +8–32 KiB；最小补字约 +2–16 KiB，总目标小于 +64 KiB；不引入 AFE/大模型 |
| CPU | C3 同一 Opus 任务承担双向工作。**估算** 以 60 ms 为预算，编解码合计 P95 宜低于 30 ms，P99 低于 45 ms 以留网络/UI 余量；实际占用未测，不给确定百分比 |
| 插话时间 | **估算** 由聚帧 0–60 ms、网络往返、服务端 AEC/VAD/排队、设备消息调度、已提交 DMA 残余组成；良好局域网目标 200–500 ms，外网可能更高，必须分别报告 |

现有静态基线为 DRAM 109716 B、flash 2285060 B、固件 2365328 B，见 `本仓库:scripts/passport_size_baseline.json:5`、`本仓库:scripts/passport_size_baseline.json:7`、`本仓库:scripts/passport_size_baseline.json:8`。原记录的 DRAM remain 不是运行时可用堆，见该文件 `本仓库:scripts/passport_size_baseline.json:4`；不能据此断言还能分配约 200 KiB。ESP32-C3 基线 IRAM 为 null，不能伪造 IRAM 增长通过结果。

不靠加队列掩盖 CPU 不足；优先减少 UI 刷新、复用短缓冲、减少音频路径分配并测重采样开销。若仍不能达到实时期限，保留 PTT，另行评估低复杂度编码或服务端帧长适配，不能无验证地改帧长或换 SDK。

可选本地轻量 AEC 的 CPU/RAM **必须真机测量**，不沿用上述服务器端路线估算，也不从静态库大小推算运行时 RAM。对相同音量、网络和双向 Opus 负载，分别测禁用基线与启用后的 AEC 每块处理耗时 P95/P99、CPU 增量、最小内部空闲堆、最大连续块、栈余量及丢帧；包括重采样、双通道缓冲和参考对齐成本。建议放弃门限：AEC 及其配套处理持续占用单核 CPU >40%，或处理 P99 超过一个输入块时长，或最小内部空闲堆低于基线校准后预先冻结的门限（初始建议 32 KiB、最大连续块 16 KiB，见 6.3），即停止本地 AEC 试验并回退服务器端路线/PTT；不得为保留算法而放宽门限。40% 是试验预算，不是已测占用或 SDK 性能指标。

## 6 测试计划

本次文档任务未运行构建/主机测试；以下均为后续实施计划。使用 ESP-IDF v6.1，最低 v6.0.1，不测试或支持 IDF 5.x。

### 6.1 主机测试

- 在临时构建环境运行 `python3 -m unittest discover -s scripts/tests -v`，保留现有 Passport PTT、activity、显示、体积报告测试。
- 增加真正验证契约的测试：能力关/开、偏好缺失/非法、实际会话降级、两个传输 hello aec 与 listen mode 的组合；旧板子序列化输出保持一致。
- 二进制固定字节向量核对 v2 与 UDP @8、网络序、v1/v3 无 timestamp；截断、长度不符、未知类型、超长、零时间戳与绕回值；禁止只用同一实现编码再解码作唯一断言。
- 有界 FIFO 满/空、编码丢帧关联、断连/重置/锁外输出迟到、旧连接数据、开关期间重连、PTT release-before-connect；保证旧标记不泄漏到下一会话。
- 模拟 TTS start/正常 stop/abort/迟到数据、手动打断，验证队列 generation、空闲零上传及正常尾音策略。模拟服务器时明确区分严格 v2、网关私有头、裸 Opus。
- 对所有本地固定文案执行字形检查；无资产/fallback 和有资产两套，缺字须补字或稳定回退。

### 6.2 CI 和构建

后续必须让 Build AI Passport 验证编译能力关闭与开启两种构建，并分别给出体积报告；运行时默认均关闭。规范构建入口为 `python3 scripts/build.py folotoy/ai-passport --name ai-passport`，实验构建采用未来明确的受控选项/变体，不手改 sdkconfig。当前 CI 尚未包含该实验构建，本次不改 CI。

Build Boards 覆盖代表性 C3 lite 非 Passport、S3 AFE/设备 AEC、P4、无显示/OLED/LVGL 及 WebSocket/MQTT 路径；确认原 Kconfig 依赖、原 hello 行为和唯一板工厂。基于同一基线门限做检查：DRAM ≤+8 KiB，flash/固件 ≤+64 KiB，分区与资产容量均通过；不得仅为通过新增功能而抬高 baseline。构建通过不视为真机通过。

### 6.3 真机矩阵与验收

每次记录固件 SHA、IDF/字体精确版本、服务器 SHA/模型/VAD 参数、网关 SHA/URL 后缀、音量、距离、噪声、网络 RTT/丢包、采样率及帧长。两种服务器分别建立结果，未拿到官方权限/能力时明确阻塞该兼容声明。

| 场景 | 采集指标与建议验收门限（待用户确认） |
| --- | --- |
| 默认 PTT 回归 | 按住 1 秒、松手、短按、双击设置、联网中松手、断网和软睡眠唤醒，行为与基线一致；无遗留采集 |
| TTS 单讲，无真人 | 音量 25/50/75/100%，各 ≥100 段，安静/背景声各一轮；自我打断率=被自身回声触发打断的段数/总段数，建议 ≤1%；记录误 ASR/自问自答，不只看 stop |
| 双讲插话 | 近/远距离、轻声/正常声、不同音量各 ≥30 次；有效打断率建议 ≥95%；语音起点到扬声器静默 P50/P95，建议局域网 P95 ≤500 ms；同时检查插话首字不丢 |
| 正常 TTS 结束 | 带数字/尾词/长尾静音的已知文本 ≥100 段；建议无可闻截词，波形尾部损失不超过 1 个 60 ms 帧；一律清 stop 若不满足，判该配置档不可发布 |
| 静默与参考匹配 | Speaking 上行帧连续、非零标记覆盖率及偏差分布；零值、FIFO 欠载、开头至少两帧参考缺失独立记录，不把“有时间戳”当消回声有效 |
| 卡顿与丢帧 | 连续对话 ≥30 分钟，正常网络无可闻卡顿；编码/发送丢帧目标 0，记录所有队列峰值/编解码耗时；1/5% 丢包、延迟抖动、服务端慢发送下不得死锁或无界积压 |
| 内存与栈 | ≥2 小时压力测试，周期记录最小堆、最大连续块和栈余量；建议最小内部空闲堆 ≥32 KiB、最大连续块 ≥16 KiB、任务栈余量 ≥25%，需按当前基线校准；无持续下降、无 OOM/重启 |
| 状态/回滚 | Listening/Speaking/等待/错误/提示/菜单、亮暗主题、未加载资产时字形完整；关闭实验后下一会话不带 aec、不在 Speaking 上传，NVS 重启恢复正确 |
| 两服务器 | xiaozhi.me 的实际可用传输；eb9dc8c+网关 MQTT/UDP；开源服务端直连 WS v1 作 PTT 对照、v2/v3 作拒绝/降级负例；每组合分别给结论 |

另外测 AEC 关闭对照、插话后重连、快速反复开关、服务器重启、TTS stop 与下一 start 交错、时间戳 32 位绕回、输入暖机和通知播放。电流/温升/续航也需真机记录，本文无续航改善或成本承诺。

## 7 风险 / 备选方案 / 回滚

- **双讲误消除与自我打断**：当前谱减及高相关压低可能同时压掉真人，单帧 VAD 又可能误触发。备选在服务端增加双讲门限、持续若干帧判定、残余回声判别、参考能量/相干度门控及打断冷却；参数必须用真实扬声器和房间调优。设备不能仅凭静音门限假装 AEC；调低音量与 PTT 是直接备选。
- **WebSocket 格式不兼容**：开源直连需要双向解析/生成严格 v2 并缓存参考，也需要长度校验和 stop/abort 契约。推荐独立服务器适配阶段；网关路径先行，不能因都是 16 B 就混用头。
- **时间戳不等于精确对齐**：FIFO、DMA 和回声尾部偏差可能超出服务端搜索范围；备选是小型有界的播放标记时间窗口，或服务端更稳健延迟估计。必须保留回传标签与本地测量时间的区别。
- **stop 歧义**：普通结束与打断无区别，见 4.5。若无法同时通过插话延迟和尾音完整性，要求服务器增加明确打断语义；否则不给该组合启用实验功能。
- **端到端模型**：具备原生音频双工/打断能力的模型可以减少传统链路延迟，但不必然能抵抗同机喇叭回声。需确认模型接受的音频格式、回声参考、控制事件、成本与隐私，适配现有协议；不能把切换模型当成 AEC 已解决。
- **C3 CPU/堆/功耗**：第一阶段不上完整 AFE、不新增大 PCM 缓存/任务；超资源门限先优化或撤回能力，不扩大队列/基线。活动实时会话持续耗电，必须有手动结束和服务器空闲关闭策略。
- **兼容声明漂移**：锁定服务端、网关、模型和传输组合；换模型/版本重跑双讲验收。官方服务未证实前保持可选且不默认启用。

### 7.1 备选：C3 本地轻量 AEC

仅作为阶段 2a 服务器端联调、阶段 2b 回环验证之后的可选阶段 2c 试验：在 lite 路径接入独立 `afe_aec_*`，拟用 `AFE_TYPE_VC`、`AFE_MODE_LOW_COST`、`filter_length=1–2` 起步，而非启用完整 AFE。参数符号、类型及函数声明已由 §2.2 的原包行号核实；`AFE_TYPE_VC` 注释对应 16 kHz。`filter_length=1–2` 是设计试验值，原包 `esp_afe_aec.h` 没有给 C3 专属推荐值，也未注明其物理单位和合法范围，不能将 C5 推荐 2 当作 C3 依据；先最小编译链接，再以 `afe_aec_get_chunksize` 返回值组织固定缓冲，并验证采样率、麦克风/参考排列和生命周期。现有 lite 直接输出原始音频、启用设备 AEC 只报警，见 `本仓库:main/audio/engines/lite_audio_engine.cc:35`、`本仓库:main/audio/engines/lite_audio_engine.cc:70`，接入属于未来功能。

优先试验 ES8311 DAC 回环到右声道的参考路径：demo 明确注释参考来自 ES8311 speaker 右声道，并设置 16 kHz、双声道、16 位播放，见 `esp-webrtc:solutions/openai_demo/main/media_sys.c:111` 至 `esp-webrtc:solutions/openai_demo/main/media_sys.c:117`。这提供参考设计线索，尚不能证明 Passport 接线及寄存器配置支持同样回环。本仓库 `input_reference_` 当前固定 false、`input_channels_=1`，见 `本仓库:main/audio/codecs/es8311_audio_codec.cc:13`、`本仓库:main/audio/codecs/es8311_audio_codec.cc:14`；codec 打开时仍是单声道，见 `本仓库:main/audio/codecs/es8311_audio_codec.cc:94` 至 `本仓库:main/audio/codecs/es8311_audio_codec.cc:101`。I2S slot 虽为双声道（`本仓库:main/audio/codecs/es8311_audio_codec.cc:141`），也不能仅翻转 `input_reference_` 就宣称参考可用；需验证真正的麦克风/右声道参考采集和立体声播放，不修改原板引脚。

备选为软件参考：从实际送往播放的 PCM 取固定有界缓冲，显式对齐重采样、播放队列、I2S DMA 延迟及中断/丢帧；比硬件回环更难，不用服务器时间戳代替本地采样对齐。若 DAC 回环未通过阶段 2b，不把软件参考视为自动可用的补救。

后续设计独立的 Passport/C3 Kconfig（建议 `PASSPORT_LOCAL_AEC_EXPERIMENTAL`，默认 n），不 select `USE_AUDIO_PROCESSOR`、不放宽完整 AFE 的芯片/PSRAM 或板型限制。保持独立开关及有界缓冲，避免与服务器端 AEC 未经验证地叠加；关闭时维持既有 lite 行为。本地模式是否声明服务器 aec 能力须另验协议语义。达到第 5 节任一放弃门限即撤回本地试验；通过编译、链接仍须双讲、插话、重连、资源和功耗真机验收。

### 7.2 回滚

回滚顺序：用户关闭菜单→调度停止采集、关通道、清所有会话音频/标记、SetAecMode(Off) 并保存 false→下一会话使用原模式。严重故障可构建禁用编译能力的同硬件固件；即使 NVS 保存 true 也必须被忽略。不改板身份或分区，不删除亮度/主题设置；退回旧固件后新键被忽略，再升级是否恢复偏好须在恢复说明中明确。保留已有恢复镜像交付路径，不在本次执行刷机或发布。

## 8 分阶段任务与验收标准

| 阶段 | 后续任务 | 完成标准 |
| --- | --- | --- |
| 0：协议与字体门禁 | 确认服务器组合、网关 URL、双向头、stop/abort 策略；取得实际字体 cmap；确认用户选择 | 输出可复现抓包/参考标记路径和逐字覆盖表；未知项不能被标为已兼容；默认 PTT 无变化 |
| 1：能力与运行时接线 | Passport Kconfig、NVS/menu、主任务切换、两传输 hello；PTT/短按规则 | 能力关/开均构建；其它板子序列化不变；首次开机关闭、主动开会话才上传；切换无竞争和旧连接状态残留 |
| 2a：lite 播放控制与开源服务器端 AEC 联调 | 先完成有界标记、输入校验、generation、计数器、人工打断与 stop 配置档，再联调 eb9dc8c+网关；必要的服务端适配另行授权实施 | 固定字节向量和并发/断连测试通过；Speaking 持续上行；旧帧不泄漏；人工打断可确定停止；单讲/双讲/尾音/延迟均通过，任一不通过则保留 PTT，不把“能上传”标为 AEC 完成 |
| 2b（可选）：ES8311 回环可行性实验 | 在阶段 2a 服务器端 AEC 联调之后验证 DAC 右声道回环；录制原始麦克风/参考双通道、带采样率和声道说明的 16 位立体声 WAV，离线分析；不改协议，不在线上传参考声道 | 覆盖静音、TTS 单讲、近端单讲和双讲及不同音量；确认声道映射正确，TTS 在参考通道可辨、无削波，近端语音不成为参考主体；连续录制 ≥10 分钟无丢样，分窗互相关延迟相对中位数漂移建议 ≤1 ms；保存波形、频谱、相关性及延迟报告；失败则停止硬件回环路线，不能称 AEC 已实现 |
| 2c（可选）：C3 本地轻量 AEC 试验 | 通过阶段 2b 后，独立默认关闭的 Kconfig 接入 lite/afe_aec；先最小 C3 编译链接，再真机比较原始/处理后音频 | 原包 API/许可核查完成；单讲回声衰减建议 ≥10 dB，双讲近端不丢首字、不出现明显吞音；通过 6.3 的误打断/插话/尾音标准及第 5 节 CPU/堆放弃门限；连续 ≥2 小时无泄漏/重启，失败回退服务器端/PTT；软件参考须单独通过同等对齐验收 |
| 3：官方联调与资源验收 | xiaozhi.me 实际传输/模型测试；持续负载、功耗、字幕 UI；全 CI | 官方结果明确为通过或未证实；DRAM/flash 门限通过；两小时堆/栈无泄漏；测试记录注明物理条件 |
| 4：实验发布与回滚演练 | 决定标准变体是否编入能力，保持运行默认关闭；写使用/恢复说明 | 开关及同身份固件回滚验证通过；仅发布已通过组合；其它板子回归通过；没有未披露的尾音损失 |

阶段 2b 的默认关闭实验工具、构建/抓取/分析命令及未证实假设见 [ES8311 回环实验操作说明](AI_PASSPORT_ES8311_LOOPBACK_EXP.md)。工具落地不代表阶段 2a 或 2b 的真机验收通过。

阶段 2 统一细分为 2a（服务器端联调，含 lite 时间戳与播放控制前置任务）、2b（回环）、2c（本地 AEC），按此顺序推进，不再单列原“阶段 2”。阶段可分批评审，但阶段 2a 内的接线/播放控制完成不能替代该阶段及阶段 3 的实际消回声能力验证；可选阶段 2b/2c 不阻塞已通过验收的服务器端路线，回环可用也不等于本地 AEC 通过。若官方条件不可得，允许只发布明确限定的开源网关实验配置，需用户决定。

## 9 待用户决定的问题

1. 优先支持 `eb9dc8c + MQTT 网关`，还是必须首版同时验证 xiaozhi.me？官方服务条件不可得时，是否接受限定开源组合的实验版本？
2. 是否同意本设计的按键语义：实时下短按 Listening 结束、Speaking 打断继续；长按 1 秒切换当次 manual PTT，偏好保留？若希望长按也启动锁定实时会话，需要不同的松手语义。
3. 能否接受未来单独修改自建服务端以增加明确 abort reason/严格 WS v2？若不接受且原版 stop 策略截尾，不发布实时功能是否符合预期？
4. 编译能力稳定后放入标准 Passport 变体且运行默认关闭，还是始终维持独立实验构建？
5. 是否采纳第 6 节的自我打断 ≤1%、插话成功 ≥95%、局域网 P95 ≤500 ms 和内存门限？测试距离、最高音量、房间噪声及外网延迟应以何种使用环境为准？
6. 若内置字体缺少“实时对话（实验）”，优先小型补字资源还是 ASCII 回退？菜单名称保留“实验”，不使用“AEC 已生效”表述。
7. 实时会话的无语音自动关闭时长、重连后是否需再次按键开始，以及可用于测试的官方模型/账号/设备由谁提供？建议断网后不自动恢复上传。

以上问题不影响本文作为设计交付；在确定相应行为之前，不应进入依赖这些选择的发布步骤。
