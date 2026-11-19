# -*- coding: utf-8 -*-
"""
wifiap 实训 · 串口监视器
--------------------------------------------------------------------
用途：读取 HiHope NearLink WS63E 核心板 UART 打印，验证「手机连接核心板热点成功」。

用法（在烧录并按 RESET 之后运行）：
    python wifiap_serial_monitor.py                 # 自动列出并选择可用串口
    python wifiap_serial_monitor.py --port COM7     # 指定串口
    python wifiap_serial_monitor.py --port COM7 --baud 115200 --until-success
    python wifiap_serial_monitor.py --demo          # 不接板子，回放预期日志（仅演示，标记为模拟）

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
)

DEMO_LOG = """[WIFIAP] ==== WiFi AP (SoftAP) Sample Start ====
[WIFIAP] WiFi init OK.
[WIFIAP] Register event callback OK (sta_join / sta_leave).
[WIFIAP] SSID    : H
[WIFIAP] PASSWORD: 12345678
[WIFIAP] SECURITY: WPA/WPA2-PSK MIX, CHANNEL: 6
[WIFIAP] SoftAP try enable ...
[WIFIAP] SoftAP enabled OK.
[WIFIAP] netif ap0 IP=192.168.63.1 MASK=255.255.255.0 GW=192.168.63.2
[WIFIAP] DHCP server started OK (pool 192.168.63.x)
[WIFIAP] SoftAp start success.
[WIFIAP] >>> 请用手机 WLAN 搜索热点 "H"，输入密码 12345678 连接 <<<
[WIFIAP] Waiting for phone ... (poll 2000 ms)
[WIFIAP] Connected stations: 0
[WIFIAP] Connected stations: 1
[WIFIAP] [EVENT] STA JOIN  MAC=A8:6D:AA:3F:21:70  RSSI=-46 dBm  RATE=65000 kbps
[WIFIAP] ****** 手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS ******
[WIFIAP] SSID=H  PASSWORD=12345678  AP_IP=192.168.63.1
[WIFIAP] [DHCP] phone MAC=A8:6D:AA:3F:21:70  IP=192.168.63.3
[WIFIAP] LINK UP: phone -> AP(H)  AP=192.168.63.1  phone=192.168.63.3
"""


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

    if "手机连接热点成功" in text or "PHONE CONNECTED HOTSPOT SUCCESS" in text:
        state["success"] = True
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


def run_demo(until_success, log_path):
    print("[演示模式] 回放预期串口日志（不是真实板卡数据）", flush=True)
    with open(log_path, "w", encoding="utf-8") as fp:
        fp.write("# wifiap 串口监视日志（演示回放，非真实采集）\n")
        state = {"success": False}
        for line in DEMO_LOG.splitlines():
            handle_line(line, fp, state)
            time.sleep(0.18)
            if until_success and state["success"] and "LINK UP" in line:
                break
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
                if until_success and state["success"] and "LINK UP" in last_line:
                    break
        except KeyboardInterrupt:
            print("\n已停止。", flush=True)
        finally:
            ser.close()
    return 0 if state.get("success") else 1


def main():
    ap = argparse.ArgumentParser(description="wifiap 实训串口监视器")
    ap.add_argument("--port", help="串口号，例如 COM7；不填则列出可用串口")
    ap.add_argument("--baud", type=int, default=115200, help="波特率，默认 115200")
    ap.add_argument("--until-success", action="store_true", help="收到连接成功+DHCP 后自动结束")
    ap.add_argument("--timeout", type=int, default=0, help="采集秒数，0 表示不限")
    ap.add_argument("--demo", action="store_true", help="回放预期日志（仅演示，不接板子）")
    args = ap.parse_args()

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
    return code


if __name__ == "__main__":
    sys.exit(main())
