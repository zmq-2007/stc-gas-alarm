# -*- coding: utf-8 -*-
"""
wifiap 实训 · 串口监视器
--------------------------------------------------------------------
用途：读取 HiHope NearLink WS63E 核心板 UART 打印，验证「手机连接核心板热点成功」。

用法（在烧录并按 RESET 之后运行）：
    python wifiap_serial_monitor.py --diag          # 【推荐】一键排障：自动选口抓 30 s 并给结论
    python wifiap_serial_monitor.py                 # 自动列出并选择可用串口
    python wifiap_serial_monitor.py --port COM7     # 指定串口
    python wifiap_serial_monitor.py --port COM7 --baud 115200 --until-success
    python wifiap_serial_monitor.py --port COM7 --timeout 30   # 只抓 30 秒
    python wifiap_serial_monitor.py --demo          # 不接板子，回放预期日志（仅演示，标记为模拟）
    python wifiap_serial_monitor.py --verify        # 静态验收：源码/编译注册/固件/日志/网页一致性检查

结束采集时会自动给出「串口排障结论」，按收到的日志判定卡在哪一步（固件没跑 /
WiFi 未初始化 / SoftAP 使能失败 / 热点已开但手机没连），并给出对应处理办法。

输出：终端实时显示 + 同目录 wifiap_serial_YYYYMMDD_HHMMSS.log 全量保存。
依赖：pip install pyserial
"""
import argparse
import datetime
import os
import sys
import time

KEY_LINES = (
    "手机连接热点成功",
    "PHONE CONNECTED HOTSPOT SUCCESS",
    "STA JOIN",
    "[DHCP] phone",
    "LINK UP",
    "Connected stations: 1",
    "RESULT END",
)

DEMO_LOG = """[WIFIAP] ==== WiFi AP (SoftAP) Sample Start  BUILD=v4-wifiinit-fix ====
[WIFIAP] [DIAG] 看不到本行 = 烧错固件 / COM 口选错 / 波特率不是 115200
[WIFIAP] [DIAG] boot delay 5000 ms: wait WiFi device ready (vendor 原版做法)
[WIFIAP] [DIAG] before init: wifi_is_wifi_inited()=0
[WIFIAP] [DIAG] ROOT CAUSE: wifi_get_enable_status() needs init_status=1,
[WIFIAP] [DIAG] but this target has NO startup wifi_init() -> call it here.
[WIFIAP] [DIAG] wifi_init() try 1/10 ret=0 status=1
[WIFIAP] WiFi init OK.
[WIFIAP] [DIAG] after init: wifi_is_wifi_inited()=1
[WIFIAP] [DIAG] register_event_cb ret=0
[WIFIAP] Register event callback OK (sta_join / sta_leave).
[WIFIAP] SSID    : H
[WIFIAP] PASSWORD: 12345678
[WIFIAP] SECURITY: WPA/WPA2-PSK MIX, CHANNEL: 6
[WIFIAP] [DIAG] set_softap_config_advance ret=0 (hidden_ssid_flag=1)
[WIFIAP] [DIAG] wifi_softap_enable try 1/60 ret=0 (init_status=1)
[WIFIAP] SoftAP enabled OK. SSID "H" is now broadcasting.
[WIFIAP] [DIAG] netif_set_addr ret=0
[WIFIAP] [DIAG] dhcps_start ret=0
[WIFIAP] DHCP server started OK (pool 192.168.63.x)
[WIFIAP] netif IP=192.168.63.1 MASK=255.255.255.0 GW=192.168.63.2
[WIFIAP] SoftAp start success.
[WIFIAP] >>> 请用手机 WLAN 搜索热点 "H"，输入密码 12345678 连接 <<<
[WIFIAP] Waiting for phone ... (poll 2000 ms)
[WIFIAP] Connected stations: 0
[WIFIAP] [DIAG] heartbeat: init_status=1, netif=ap0-ready, stations=0
[WIFIAP] Connected stations: 1
[WIFIAP] [EVENT] STA JOIN  MAC=A8:6D:AA:3F:21:70  RSSI=-46 dBm  RATE=65000 kbps
[WIFIAP] ****** 手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS ******
[WIFIAP] SSID=H  PASSWORD=12345678  AP_IP=192.168.63.1
[WIFIAP] [DHCP] phone MAC=A8:6D:AA:3F:21:70  IP=192.168.63.3
[WIFIAP] LINK UP: phone -> AP(H)  AP=192.168.63.1  phone=192.168.63.3
[WIFIAP] ---------------- RESULT / 实训验收 ----------------
[WIFIAP] SSID=H  PASSWORD=12345678  CHANNEL=6  SECURITY=WPA/WPA2-PSK
[WIFIAP] AP=192.168.63.1  phone MAC=A8:6D:AA:3F:21:70  IP=192.168.63.3
[WIFIAP] ****** 手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS ******
[WIFIAP] ---------------- RESULT END ----------------
"""

# 排障阶段：按日志出现顺序判定「卡在哪一步」
DIAG_STAGES = (
    ("boot", "==== WiFi AP (SoftAP) Sample Start", "固件已启动"),
    ("build", "BUILD=v4-wifiinit-fix", "烧录的是 v4 根因修复版固件"),
    ("init", "WiFi init OK", "wifi_init() 成功，init_status=1"),
    ("enable", "wifi_softap_enable try 1/60 ret=0", "SoftAP 使能成功"),
    ("ap", "is now broadcasting", "SSID「H」已开始广播"),
    ("ready", "SoftAp start success", "热点可用（含 DHCP 或降级保活）"),
    ("success", "手机连接热点成功", "手机连接成功"),
)

DIAG_ADVICE = {
    "boot": [
        "串口里完全没有 [WIFIAP] 启动行 -> 固件没跑起来",
        "  1) 确认烧录的是 wifiap_lab/firmware/ws63-liteos-app_all.fwpkg（或 SDK output 的同名 all.fwpkg）",
        "  2) 烧录出现 Connecting, please reset device... 时按一下板卡 RESET，烧完再按一次 RESET 重启",
        "  3) 串口选 DEBUG_UART=UART0，波特率 115200 / 8N1；板载若有多个串口请逐个试",
        "  4) 确认 HiSpark Studio 的 Kconfig 里 support WIFIAP Sample 仍处于选中状态后重新 build",
    ],
    "build": [
        "没有 BUILD=v4-wifiinit-fix 标记 -> 板子里跑的还是旧固件",
        "  必须重新烧录 wifiap_lab/firmware/ws63-liteos-app_all.fwpkg（本次重新编译的版本）",
        "  烧录出现 Connecting, please reset device... 时按 RESET，烧完再按一次 RESET",
    ],
    "init": [
        "有 Start 但没有 WiFi init OK -> wifi_init() 没成功（本 target 的关键根因）",
        "  wifi_softap_enable() 内部 wifi_get_enable_status() 要求 init_status=1；",
        "  而本工程启动链不调用 wifi_init()，所以旧固件（含 vendor 原版）必然 enable 失败。",
        "  v4 固件会主动调用 wifi_init() 并重试 10 次，请看 [DIAG] wifi_init() try ... ret/status：",
        "  1) 若 status 一直 0：烧 *_all.fwpkg（含 ws63_all_nv.bin），重新上电，必要时 rebuild",
        "  2) 也可以在串口助手手动发 AT+WIFIINIT，v4 的持续重试会自动接上",
    ],
    "enable": [
        "WiFi 已初始化，但 wifi_softap_enable ret 非 0 -> 热点没能开启",
        "  1) v4 会持续重试 120 s，请等待并观察 [DIAG] wifi_softap_enable try N/60",
        "  2) 多为 WiFi device 侧固件 / NV 校准数据问题：改烧 *_all.fwpkg 并重新上电",
        "  3) 确认没有别的样例同时占用 AP（g_softap_enble_flag 已置位也会失败）",
    ],
    "ap": [
        "SoftAP 已使能但没看到 SSID 广播/启动成功行 -> 检查后续 netif / DHCP 告警",
        "  新版在 netif 或 DHCP 失败时会保持热点开启，手机仍应能在 WLAN 里搜到 H",
    ],
    "ready": [
        "热点已经开启（串口出现 SoftAp start success），但手机没有连上",
        "  1) 手机 WLAN 里手动「添加网络」：SSID 精确为单个大写字母 H，密码 12345678，安全性 WPA/WPA2-PSK",
        "  2) 只用 2.4 GHz 频段搜索（信道 6），部分手机会折叠隐藏「无互联网」热点，请在列表底部找",
        "  3) 关闭手机「智能切换/WLAN+」，先停用移动数据再连 H",
        "  4) 连接后若提示无互联网属正常（热点没有外网出口），不影响实训验收",
    ],
}


def print_diagnosis(state, log_fp=None):
    """按收到的日志给出排障结论，同时写入日志文件。"""
    lines = ["=" * 72, "串口排障结论（根据本次收到的日志自动判定）", "-" * 72]
    reached = []
    for key, _, label in DIAG_STAGES:
        ok = bool(state.get(key))
        reached.append(ok)
        lines.append("  [%s] %s" % ("OK" if ok else "--", label))
    lines.append("-" * 72)
    if state.get("success"):
        lines.append("  结论：验收通过，串口已收到「手机连接热点成功」。")
    else:
        # 找出第一个未达到的阶段
        idx = reached.index(False) if False in reached else len(DIAG_STAGES) - 1
        key = DIAG_STAGES[idx][0]
        lines.append("  卡点：%s" % DIAG_STAGES[idx][2])
        for tip in DIAG_ADVICE.get(key, []):
            lines.append("  " + tip)
    lines.append("=" * 72)
    text = "\n".join(lines)
    print("\n" + text, flush=True)
    if log_fp is not None:
        log_fp.write("\n" + text + "\n")
        log_fp.flush()


def list_ports():
    try:
        from serial.tools import list_ports as lp
        return [(p.device, p.description) for p in lp.comports()]
    except ImportError:
        return []


def stamp():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def make_log_path():
    d = os.path.dirname(os.path.abspath(__file__))
    name = "wifiap_serial_%s.log" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(d, name)


def handle_line(line, log_fp, state):
    ts = stamp()
    text = line.rstrip("\r\n")
    out = "[%s] %s" % (ts, text)
    print(out, flush=True)
    log_fp.write(out + "\n")
    log_fp.flush()

    # 记录排障阶段（供结束时的自动结论使用）
    for key, needle, _ in DIAG_STAGES:
        if needle in text:
            state[key] = True

    if "手机连接热点成功" in text or "PHONE CONNECTED HOTSPOT SUCCESS" in text:
        state["success"] = True
        if not state.get("banner_shown"):
            state["banner_shown"] = True
            banner = "=" * 68
            print(banner, flush=True)
            print("  验收通过：串口已收到「手机连接热点成功」事件", flush=True)
            print("  SSID=H  密码=12345678  核心板 AP=192.168.63.1", flush=True)
            print(banner, flush=True)
            log_fp.write(banner + "\n  验收通过：手机连接热点成功\n" + banner + "\n")
            log_fp.flush()
    elif "[DHCP] phone" in text and "IP=" in text:
        print("  -> 手机已通过 DHCP 获得 IP，链路建立完成", flush=True)
    elif "[EVENT] STA LEAVE" in text or "PHONE DISCONNECTED" in text:
        state["success"] = False
        print("  -> 手机已断开，可重新连接再次验证", flush=True)

    if "LINK UP" in text:
        state["linkup"] = True
        state["post_linkup"] = 0
    elif "RESULT END" in text:
        state["done"] = True
        print("  验收摘要输出完毕（串口信息已完整记录）", flush=True)
    if state.get("linkup") and not state.get("done"):
        # 旧固件没有 RESULT 摘要段时，LINK UP 之后再收几行就结束
        state["post_linkup"] = state.get("post_linkup", 0) + 1
        if state["post_linkup"] >= 6:
            state["done"] = True


def run_demo(until_success, log_path):
    print("[演示模式] 回放预期串口日志（不是真实板卡数据）", flush=True)
    with open(log_path, "w", encoding="utf-8") as fp:
        fp.write("# wifiap 串口监视日志（演示回放，非真实采集）\n")
        state = {"success": False}
        for line in DEMO_LOG.splitlines():
            handle_line(line, fp, state)
            time.sleep(0.18)
            if until_success and state.get("done"):
                break
        print_diagnosis(state, fp)
    return 0


def run_serial(port, baud, until_success, timeout, log_path):
    try:
        import serial
    except ImportError:
        print("缺少 pyserial，请先执行：pip install pyserial", file=sys.stderr)
        return 2

    print("打开串口 %s @ %d ..." % (port, baud), flush=True)
    try:
        ser = serial.Serial(port=port, baudrate=baud, timeout=0.4,
                            bytesize=8, parity="N", stopbits=1)
    except Exception as e:
        print("打开串口失败：%s" % e, file=sys.stderr)
        print("可用串口：%s" % (list_ports() or "（无）"), file=sys.stderr)
        return 2

    print("等待板卡输出（烧录时按 RESET，随后用手机 WLAN 连接热点 H）...", flush=True)
    print("按 Ctrl+C 结束。\n", flush=True)
    start = time.time()
    buf = b""
    last_line = ""
    with open(log_path, "w", encoding="utf-8") as fp:
        fp.write("# wifiap 串口监视日志  port=%s baud=%d\n" % (port, baud))
        state = {"success": False}
        try:
            while True:
                if timeout and time.time() - start > timeout:
                    print("\n达到超时时间，结束采集。", flush=True)
                    break
                data = ser.read(256)
                if data:
                    buf += data
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        last_line = raw.decode("utf-8", errors="replace")
                        handle_line(last_line, fp, state)
                if until_success and state.get("done"):
                    break
        except KeyboardInterrupt:
            print("\n已停止。", flush=True)
        finally:
            ser.close()
            print_diagnosis(state, fp)
    return 0 if state.get("success") else 1


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def run_verify():
    """静态验收：不接板子，核对源码 / 工程注册 / 编译产物 / 串口日志 / 网页是否一致。"""
    here = os.path.dirname(os.path.abspath(__file__))
    sdk = r"D:/VSCode/fbb_ws63/src"
    checks = []

    def chk(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    src = read_text(os.path.join(here, "softap_sample.c"))
    chk("源码：wifi_softap_enable() 开启热点", "wifi_softap_enable" in src)
    chk("源码：注册 sta_join / sta_leave 事件", "wifi_event_softap_sta_join" in src and
        "wifi_event_softap_sta_leave" in src)
    chk("源码：查询站点与 DHCP 地址", "wifi_softap_get_sta_list" in src and
        "netifapi_dhcps_get_client_ip" in src)
    chk("源码：打印「手机连接热点成功」", "手机连接热点成功" in src and
        "PHONE CONNECTED HOTSPOT SUCCESS" in src)
    chk("源码：RESULT 验收摘要段", "RESULT / 实训验收" in src and "RESULT END" in src)
    chk("源码：有限等待 + wifi_init 兜底（不再无限死等）",
        "softap_wait_init" in src and "wifi_init()" in src and
        "while (wifi_is_wifi_inited() == 0) {" not in src)
    chk("源码：v4 主动 wifi_init() 根因修复与 BUILD 标记",
        "softap_ensure_wifi_init" in src and "v4-wifiinit-fix" in src
        and "WIFI_SOFTAP_ENABLE_RETRY    60" in src)
    chk("源码：显式不隐藏 SSID 且附属失败不关热点",
        "hidden_ssid_flag = 1" in src and "(void)wifi_softap_disable()" not in src)
    chk("源码：热点参数 H / 12345678 / CH6", 'WIFI_SOFTAP_SSID            "H"' in src and
        'WIFI_SOFTAP_PASSWORD        "12345678"' in src and "WIFI_SOFTAP_CHANNEL         6" in src)

    cm = read_text(os.path.join(here, "CMakeLists.txt"))
    chk("样例 CMakeLists 收录 softap_sample.c", "softap_sample.c" in cm and "PARENT_SCOPE" in cm)
    periph = read_text(os.path.join(sdk, "application/samples/peripheral/CMakeLists.txt"))
    kcfg = read_text(os.path.join(sdk, "application/samples/peripheral/Kconfig"))
    cfg = read_text(os.path.join(sdk, "build/config/target_config/ws63/menuconfig/acore/ws63_liteos_app.config"))
    mcfg = read_text(os.path.join(sdk, "output/ws63/acore/ws63-liteos-app/mconfig.h"))
    chk("工程注册：add_subdirectory_if_exist(wifiap)", "add_subdirectory_if_exist(wifiap)" in periph)
    chk("工程注册：Kconfig SAMPLE_SUPPORT_WIFIAP", "SAMPLE_SUPPORT_WIFIAP" in kcfg)
    chk("工程注册：.config 与 mconfig.h 已启用", "CONFIG_SAMPLE_SUPPORT_WIFIAP=y" in cfg and
        "CONFIG_SAMPLE_SUPPORT_WIFIAP 1" in mcfg)
    sdk_src = read_text(os.path.join(sdk, "application/samples/peripheral/wifiap/softap_sample.c"))
    chk("工程源码与交付源码一致", bool(sdk_src) and sdk_src == src)

    blog = read_text(os.path.join(here, "build.log"))
    chk("编译日志：重新编译 wifiap/softap_sample.c.obj", "wifiap/softap_sample.c.obj" in blog)
    chk("编译日志：Build target success + packet success!",
        "Build target:ws63_liteos_app success" in blog and "packet success!" in blog)
    chk("编译日志：无 error / FAILED", "error:" not in blog and "FAILED" not in blog)
    app_bin = os.path.join(here, "firmware", "ws63-liteos-app.bin")
    chk("固件：ws63-liteos-app.bin 存在且 > 1 MB",
        os.path.isfile(app_bin) and os.path.getsize(app_bin) > 1000000,
        "%d B" % (os.path.getsize(app_bin) if os.path.isfile(app_bin) else 0))
    if os.path.isfile(app_bin):
        with open(app_bin, "rb") as f:
            app_bytes = f.read()
        chk("固件：二进制内含 [WIFIAP] / 12345678 标记",
            b"[WIFIAP]" in app_bytes and b"12345678" in app_bytes)
    fwpkg = os.path.join(here, "firmware", "ws63-liteos-app_all.fwpkg")
    chk("烧录包：*_all.fwpkg 齐全（含 NV 射频校准数据）",
        os.path.isfile(fwpkg) and os.path.getsize(fwpkg) > 1000000,
        "%d B" % (os.path.getsize(fwpkg) if os.path.isfile(fwpkg) else 0))
    bins = [f for f in os.listdir(os.path.join(here, "firmware"))] if os.path.isdir(os.path.join(here, "firmware")) else []
    chk("固件：7 个分区镜像齐全", len([b for b in bins if b.endswith(".bin")]) >= 7,
        "%d 个 .bin" % len([b for b in bins if b.endswith(".bin")]))

    log = read_text(os.path.join(here, "预期串口日志.txt"))
    chk("预期串口日志：成功标志 / DHCP IP / RESULT END",
        "手机连接热点成功" in log and "IP=192.168.63.3" in log and "RESULT END" in log)
    demo_log = read_text(os.path.join(here, "串口输出_手机连接热点成功.log"))
    chk("串口脚本回放日志：成功标志 / RESULT END",
        "手机连接热点成功" in demo_log and "RESULT END" in demo_log)
    html = read_text(os.path.join(here, "..", "index.html"))
    chk("网页：结果区与串口成功标志", "wifiResult" in html and "PHONE CONNECTED HOTSPOT SUCCESS" in html)
    chk("网页：手动添加网络三项选择（安全性 / 隐私 / 隐藏的网络）",
        "wifiManualForm" in html and "WPA/WPA2-Personal" in html
        and "使用设备 MAC" in html and "hidden_ssid_flag=1" in html)

    print("=" * 72)
    print("wifiap 实训 · 一键静态验收（不替代真实烧录、RESET 与手机 WLAN 连接）")
    print("=" * 72)
    for name, ok, detail in checks:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -> " + detail) if detail else ""))
    passed = sum(1 for _, ok, _ in checks if ok)
    print("-" * 72)
    print("  结果：%d / %d 项通过" % (passed, len(checks)))
    print("  真实验收仍需：烧录按 RESET -> 手机连 H/12345678 -> 串口收到「手机连接热点成功」")
    print("=" * 72)
    return 0 if passed == len(checks) else 1


def main():
    ap = argparse.ArgumentParser(description="wifiap 实训串口监视器")
    ap.add_argument("--port", help="串口号，例如 COM7；不填则列出可用串口")
    ap.add_argument("--baud", type=int, default=115200, help="波特率，默认 115200")
    ap.add_argument("--until-success", action="store_true", help="收到连接成功+DHCP 后自动结束")
    ap.add_argument("--timeout", type=int, default=0, help="采集秒数，0 表示不限")
    ap.add_argument("--demo", action="store_true", help="回放预期日志（仅演示，不接板子）")
    ap.add_argument("--verify", action="store_true", help="静态验收：源码/注册/固件/日志/网页一致性检查")
    ap.add_argument("--diag", action="store_true",
                    help="一键排障：自动选串口、抓 30 s、给出卡点结论并保存日志")
    args = ap.parse_args()

    if args.verify:
        return run_verify()
    if args.diag:
        args.timeout = 30
        args.until_success = True

    log_path = make_log_path()
    if args.demo:
        code = run_demo(args.until_success, log_path)
    else:
        ports = list_ports()
        print("可用串口：")
        for dev, desc in ports:
            print("   %-6s %s" % (dev, desc))
        if not args.port:
            # 优先选 CH340 / FTDI 这类 USB 转串口，排除蓝牙虚拟串口
            prefer = [d for d, s in ports if "CH340" in s or "USB Serial" in s or "FTDI" in s]
            if prefer:
                args.port = prefer[0]
                print("自动选择：%s" % args.port, flush=True)
            else:
                print("未发现 USB 串口，请用 --port COMx 指定。", flush=True)
                return 1
        code = run_serial(args.port, args.baud, args.until_success, args.timeout, log_path)
    print("\n完整日志已保存：%s" % log_path, flush=True)
    if args.diag and code != 0:
        print("请把上面【串口排障结论】和本 .log 文件前 30 行发回，即可按对照表定位。", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
