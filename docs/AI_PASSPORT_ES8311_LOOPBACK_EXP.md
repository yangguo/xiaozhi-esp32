# AI Passport ES8311 回环可行性实验（阶段 2b）

本实验默认不编译，仅适用于 `folotoy/ai-passport`（ESP32-C3、无 PSRAM、单麦单喇叭）。
不改引脚、板身份、分区、协议或 NVS，不实现 AEC，也不把参考声道发往服务器。
这是设计文档 §7.1、§8 阶段 2b 的测量工具；通过编译不等于通过硬件验收。

## 构建与刷机

使用 ESP-IDF v6.1（最低 v6.0.1，不支持 5.x）：

```sh
source /path/to/esp-idf/export.sh
idf.py --version
python3 scripts/build.py folotoy/ai-passport --config loopback-exp.json --name ai-passport
python3 scripts/passport_firmware_report.py --build-dir build --report-only
idf.py -p /dev/ttyACM0 flash
```

`loopback-exp.json` 是 build.py 的独立配置文件，复用原板名称、目标、8 MB 分区和全部默认选项，
额外打开 `CONFIG_PASSPORT_ES8311_LOOPBACK_EXP=y` 与
`CONFIG_PASSPORT_LOOPBACK_EXPORT_PCM=y`。标准 `config.json` 完全不变。
也可在自有配置 JSON 的 `sdkconfig_append` 中启用上述符号；不要直接编辑生成的 sdkconfig。
仅编入实验、不输出 PCM 时，省略后一个选项（默认 n），仍有每秒统计。

时长符号 `CONFIG_PASSPORT_LOOPBACK_SECONDS` 默认 10 秒，范围 1–3600；
连续验收时在配置 JSON 中追加 `CONFIG_PASSPORT_LOOPBACK_SECONDS=600`（或更长），重新构建。
实验中固定 16 kHz、16 位、双声道；结束后恢复 config.h 的 24 kHz 正常音频路径。

CI 的独立 `loopback-experiment` job 使用同一配置，生成
`ai-passport-loopback-exp-<sha>` artifact，其中 `recovery/merged-binary.bin` 为全镜像，
`incremental/` 包含 app、assets、bootloader、partition-table 和 `flash_args`。
默认 job 和默认门限保持原样；实验 `--report-only` 只报告体积，不应用默认增长门限，
文件/解析错误仍使报告失败。

从下载的 artifact 刷写（确认设备端口和目标镜像；全镜像覆盖对应区域）：

```sh
python -m esptool --chip esp32c3 --port /dev/ttyACM0 write-flash 0x0 recovery/merged-binary.bin
# 或在 incremental 目录按附带 flash_args 的地址增量刷写：
cd incremental
python -m esptool --chip esp32c3 --port /dev/ttyACM0 write-flash @flash_args
```

恢复标准固件：重新用 `config.json` 构建并刷写，或使用标准 CI recovery/incremental。
无需迁移/清除实验 NVS；实验没有持久化状态。

## 触发与采集

1. 结束对话，等待回到空闲且音频会话关闭。菜单原有空闲/可休眠检查继续生效。
2. 双击 OK 打开设置，用上下键选 ASCII 条目 `Loopback Test`，短按 OK。
3. 菜单关闭，进入 `audio_testing` 状态。正常对话、唤醒、通知音频暂停；不支持中途按键取消，
   等配置时长结束。系统网络错误仍可显示，但不能把状态切回对话。
4. 日志出现 `LBK_BEGIN` 后播放 800 ms 的 200–3200 Hz 对数扫频，随后 200 ms 静音，循环。
   峰值约 4000/32768（约 -18 dBFS），叠加设备当前音量和输入增益。
   实验前用原有上下键调音量，运行中勿改音量；各档单独运行并记录物理条件。
5. `LBK_END` 后关闭测试音，恢复音频服务及空闲状态，下一次会话可正常建立。
   菜单入口要求已有会话关闭，不会恢复旧会话或重放之前的音频。

优先使用板上 USB Serial/JTAG；16 kHz 双声道 PCM 是 64 kB/s，base64 加行头约 89 kB/s。
115200 波特的物理 UART 不足以完整导出，调高波特率也需确认实际硬件和主机吞吐。
USB 无 UART 引脚改动，但主机/USB 驱动仍可能阻塞。

```sh
# 方法一：IDF monitor，去除终端交互与颜色后保存原始文本
idf.py -p /dev/ttyACM0 monitor --no-reset --disable-address-decoding --no-color | tee passport-loopback.log
# Ctrl+] 退出；若当前 IDF monitor 参数有差异，查看 idf.py monitor --help。

# 方法二：pyserial miniterm，退出使用 Ctrl+]
python -m serial.tools.miniterm /dev/ttyACM0 115200 --raw --dtr 0 --rts 0 | tee passport-loopback.log
```

抓取前启动 monitor，等设备空闲后再触发测试，保存 BEGIN 到 END。
pyserial 可独立保存日志（安装 `pyserial` 后）：

```sh
python - /dev/ttyACM0 passport-loopback.log <<'PY'
import serial, sys
with serial.Serial(sys.argv[1], 115200, timeout=1) as port, open(sys.argv[2], 'wb') as log:
    try:
        while True:
            log.write(port.read(4096))
            log.flush()
    except KeyboardInterrupt:
        pass
PY
```

串口文本协议：

- `LBK_BEGIN rate=16000 channels=2 bits=16 block_frames=160 seconds=... mapping=ADCL_mic_DACR_ref volume=... gain=...`
- `LBK <seq十进制> <字节数十进制> <CRC32八位十六进制> <base64>`：每块 160 帧，640 字节。
  小端交错 `[L0,R0,L1,R1,...]`。CRC32 为标准 IEEE/zlib CRC32，初值/末异或与 zlib 相同。
  seq 从 0 开始，每次尝试采集 10 ms 块递增；超时和导出丢块均留下序号缺口。
- `LBK_STAT` 每秒包含 mic/ref RMS（有符号 16 位 PCM 数值单位）、lag_samples、lag_ms、
  corr、valid、captured、capture_errors、export_drops、rx_overflows、tx_errors。
  正延迟表示 L 麦克风落后 R 参考；相关系数保留极性。
- `LBK_END blocks=...` 给出预期总块数与最终计数，可发现最后一段缺失。

采集和播放分属独立任务，串口/统计在工作任务中消费固定 8 块队列（约 5.2 KB，80 ms）。
队列满时只丢消费/导出块，不阻塞采集；每秒 RMS 来自实际消费到的块，丢块时不是完整一秒 RMS。
设备互相关用每秒扫频中部 40 ms 连续窗口，搜索 ±160 样本（±10 ms），
去均值归一化、保留最大绝对相关系数；缺窗/静音时 valid=0。它是粗诊断，不能取代离线分析。
读取或写入超时/不足记为 capture_errors/tx_errors，不把残帧当有效 PCM；
rx_overflows 是 I2S RX 队列溢出事件数，不是精确丢失样本数。
`lost_samples=unknown` 刻意保留未知：I2S/驱动不提供可靠的逐样本连续性证明。
发生错误、溢出或导出缺块的运行不能验收为“无丢样”。统计模式无需 PCM 串口吞吐。

## 主机分析

只依赖 Python 标准库，纯 Python 相关算法不依赖 numpy：

```sh
python3 scripts/passport_loopback_analyze.py passport-loopback.log \
  --wav passport-loopback.wav --report passport-loopback-report.json
cat passport-loopback.log | python3 scripts/passport_loopback_analyze.py - \
  --wav passport-loopback.wav --report passport-loopback-report.json
```

同一日志有多次运行时默认分析最后一次，`--run 0` 可选第一次。`--max-lag 320` 默认搜索 ±20 ms，
最多可设 4000 样本；搜索触及边界时应扩大范围重新检查。
报告包含 CRC、序号重复/乱序、缺块、RMS、削波样本数、每秒延迟和相对中位数漂移，
并保留设备统计和元数据。WAV 保留线上的 L/R 顺序，绝不按推断交换；
丢失块在原时间位置填零，相关分析跳过包含缺块的窗口。只有统计行时输出统计 JSON，不伪造 WAV。

声道推断依据“参考应领先声学麦克风”的因果假设，并给出两路对已知扫频的相关性。
已知模板的绝对匹配受 TX/RX 启动错位影响；不能用最大相关或较大 RMS 单独证明参考声道身份。
零延迟、静音或不相关数据会标记 ambiguous；必须结合近端单讲和 WAV 人工检查。
离线每秒取扫频的 0.2–0.7 s 窗口；报告的漂移不是时钟频差 ppm。
推荐用 Audacity 等打开 WAV 保存双路波形截图与频谱图，连同 JSON、原始日志归档；
分析脚本的 WAV 本身保存原始波形，JSON 保存相关性/延迟数据。

## 验收与未证实假设

参考源码已核实（只读，不复制 vendor 源码）：

- esp_codec_dev 1.6.2 `device/include/es8311_codec.h` 的 `no_dac_ref`：
  false 表示双声道录音右路填 DAC 输出，true 表示右路空。
- 同版本 `device/es8311/es8311.c` 的初始化：false 写 REG44=0x58，注释 ADCL+DACR；
  true 写 0x08。既有 codec 用零初始化也隐含 false，但原单声道读取未暴露右路。
- esp-webrtc `solutions/openai_demo/main/media_sys.c:111–117`：
  ES8311 参考来自 speaker 右声道，必须输出双声道。
- 实验构建正常工作时 codec 暴露 `input_reference_=true`、输入两路，正常单声道播放分块复制到 L/R；
  lite 引擎继续只发送第一个输入声道。实验时直接读写双路 I2S，不经 Opus、重采样或协议。

尚待真机证明：Passport 上 REG44 设置的实际有效性、L/R 的电气排列、DACR 是否完整跟随实际喇叭，
参考位于音量/数字滤波链的哪个位置、DMA/codec 的固定延迟、启动相位、长时间采样稳定性和 C3 负载。
RX 队列溢出回调只能发现已知事件，无法证明底层从未丢过一个样本；TX 未提供可靠欠载计数，
`tx_errors` 仅检测 API 写失败/短写。不能把这些限制包装为“零丢样已经证实”。

对应设计文档 §8 2b 的实测记录必须包含：

1. 静音、远端播放单讲、近端单讲、双讲与不同音量。可先在扫频/静音交替中分别保持安静或讲话，
   检查参考中扫频清晰、无削波且近端语音不是参考主体；这不替代真实 TTS 语料验收。
   本工具不播放/下载 TTS，也不在线上传参考；真实 TTS 及双讲需另行硬件测量记录，不能因扫频通过而勾选。
2. 连续录制至少 600 秒（10 分钟），完整 BEGIN/END、CRC/序号正常、无已知采集/溢出/导出/写入错误；
   同时检查波形连续性，人工记录启动前后状态及主机吞吐。
3. 映射经人工确认；分窗延迟相对中位数漂移建议 ≤1 ms，相关峰不在搜索边界，
   无异常跳变；保存原始日志、16 位立体声 WAV、波形/频谱截图、JSON 延迟报告及音量/物理布置。
4. 验证结束后普通捕获/播放、PTT、唤醒（若适用）、打断、重连、重复进入实验和无显示能力路径。
   本次没有接入本地 AEC，AEC 模式的真机回归仍须在原功能支持的组合进行。

任一关键项失败，停止硬件回环路线并保留失败证据；回环通过也不意味着 AEC 已实现。
默认固件回归与实验硬件验收分开记录。
