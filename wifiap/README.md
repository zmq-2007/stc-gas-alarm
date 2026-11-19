# wifiap（本实训改造版）

> 基于 `vendor/HiHope_NearLink_DK_WS63E_V03/demo/wifiap`，按《星闪实验指导手册》wifiap 章节 11 步流程新建并编译。
> 改造重点：**把「手机连接热点成功」实时打印到串口**，方便用串口助手验证实验现象。

## 改造点

1. 保留任务书规定参数：SSID = `H`，密码 = `12345678`，WPA/WPA2-PSK 混合加密，6 信道，AP IP `192.168.63.1`。
2. 用 `wifi_register_event_cb()` 注册 `wifi_event_softap_sta_join` / `wifi_event_softap_sta_leave` / `wifi_event_softap_state_changed`：
   手机一连上就打印 MAC、RSSI、速率以及 `手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS`；断开时打印 `PHONE DISCONNECTED`。
3. 用 `wifi_softap_get_sta_list()` 每 2 s 轮询在线站点，用 `netifapi_dhcps_get_client_ip()` 查询 DHCP 分配给手机的 IP，
   打印 `[DHCP] phone MAC=... IP=192.168.63.x` 与 `LINK UP: phone -> AP(H)`。
4. 串口波特率 115200（DEBUG_UART / UART0）。
5. **v4 根因修复（本版，针对实测「连续三次连不上」）**：开机固定 5 s 等 WiFi device 就绪后，
   **由样例主动调用 `wifi_init()`**（带返回码/status 打印、重试 10 次），随后 `wifi_softap_enable()`
   持续重试 120 s，中途 init 状态丢失会自动重新初始化；每 10 s 打印心跳状态；
   启动行带 `BUILD=v4-wifiinit-fix`，可据此确认烧的是不是新固件。
6. 保留的稳健性改动：显式 `hidden_ssid_flag=1`（不隐藏 SSID）；事件回调 / netif / DHCP 失败只告警，
   绝不 `wifi_softap_disable()` 把已起来的热点关掉；每一步都打印 `[DIAG]` 返回码。

## 为什么之前一直连不上（确定性根因）

`wifi_softap_enable()` 内部第一步调用 `wifi_get_enable_status()`（`soc_wifi_service_api.c:3057-3074`），
该函数在 `uapi_wifi_get_init_status() != 1` 时直接返回 `ERRCODE_FAIL`。这个状态只能由 `wifi_init()` 置位，
而全工程 `wifi_init()` 的调用点只有三处：`AT+WIFIINIT`（`at_wifi.c:1599`）、PM 唤醒恢复（`pm_porting.c:659`）、
`plat_reset_board()` —— **系统启动链里没有任何一处调用它**（本 target `# CONFIG_ENABLE_WIFI_SAMPLE is not set`）。

因此 vendor 原版「固定 5 s 延时后直接 `wifi_softap_enable()`」在这个工程配置下必然失败，SSID 永远不会广播；
把它改成「等 `wifi_is_wifi_inited()`」同样是死路，因为没人去置位。**手机侧安全性、隐私、隐藏网络怎么填都救不了这一层。**

已排除的误判：固件二进制确实含 `[WIFIAP]` / `WiFiSoftAPTask` / `12345678`，编译宏含 `-DWIFI_TASK_EXIST`（WiFi host 任务存在），
`all.fwpkg` 的镜像清单本身就不含 `ws63-liteos-mfg.bin`（官方文档默认烧录包即如此）—— 都不是根因。

## 手机「手动添加网络」怎么选（安全性 / 隐私 / 隐藏的网络）

| 字段 | 应选 | 依据与说明 |
| --- | --- | --- |
| 网络名称 SSID | `H` | 单个大写字母，区分大小写，不要带空格或引号 |
| 密码 | `12345678` | 8 位纯数字，对应 `WIFI_SOFTAP_PASSWORD` |
| **安全性** | **WPA/WPA2-Personal**（WPA2-PSK / WPA/WPA2-PSK） | 固件 `hapd_conf.security_type = WIFI_SEC_TYPE_WPA2_WPA_PSK_MIX`；**不要选** WPA3/SAE、开放(无)、企业级 EAP |
| **隐私** | **使用设备 MAC** | 固件不限制 MAC，随机 MAC 也能连；但设备 MAC 便于与串口 `STA JOIN MAC=` 对照，且规避个别手机在 WPA/WPA2 混合下反复认证失败 |
| **隐藏的网络** | **否 / 不勾选** | 固件 `hidden_ssid_flag = 1`，服务层转成 `conf.ssid_hidden = 0`，即 SSID 正常广播；勾「是」反而连不上 |
| IP 设置 / 代理 | DHCP（动态） / 无 | 固件运行 `netifapi_dhcps_start()`，手机自动获得 `192.168.63.x`，网关 `192.168.63.1` |
| 频段 / 信道 | 2.4 GHz / CH6 | 核心板只有 2.4 GHz；关掉 5 GHz 优先与 WLAN+ 智能切换 |
| 弹出「无互联网，是否保持连接」 | **保持连接 / 仍然连接** | 板卡只有 AP + DHCP，没有外网出口，这是正常现象；建议先临时关闭移动数据，否则手机会自动切回蜂窝网络 |

连上后的判据：手机 WLAN 详情显示「已连接」且 IP 形如 `192.168.63.3`；串口依次出现
`[EVENT] STA JOIN` → `手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS` → `[DHCP] ... IP=192.168.63.3` → `RESULT / 实训验收`。

若一直停在「正在获取 IP 地址」或反复断开：长按热点「忘记网络」后按上表重填；确认串口已有
`SSID "H" is now broadcasting` 与 `SoftAp start success.`（没有则是板卡侧问题）；关闭移动数据；换另一台手机交叉验证。

> **复测三步（必做）**：① 烧 `wifiap/ws63-liteos-app_all.fwpkg`（本次 v4 重新编译的版本，
> `1 468 456 B`），出现 `Connecting, please reset device...` 按 RESET，**烧完再按一次 RESET**；
> ② 打开串口（115200 / 8N1），确认第一行是 `==== WiFi AP (SoftAP) Sample Start  BUILD=v4-wifiinit-fix ====`，
> 没有这个标记说明板子里还是旧固件；③ 运行 `python wifiap_serial_monitor.py --diag`，
> 自动选串口抓 30 s 并打印「串口排障结论」，日志存为 `wifiap_serial_*.log`。
> 先看串口有没有 `SSID "H" is now broadcasting` 与 `SoftAp start success.`：**没有就是板卡侧问题**，手机侧不用再试。
> 完整对照表见 `预期串口日志.txt`，网页里也有「排障：热点 H 为什么没出现」板块。

## 预期串口日志（v4 精简版；完整版见 `预期串口日志.txt`）

```
[WIFIAP] ==== WiFi AP (SoftAP) Sample Start  BUILD=v4-wifiinit-fix ====
[WIFIAP] [DIAG] boot delay 5000 ms / before init: wifi_is_wifi_inited()=0
[WIFIAP] [DIAG] ROOT CAUSE: 本 target 启动链不调用 wifi_init()，init_status 恒为 0
[WIFIAP] [DIAG] wifi_init() try 1/10 ret=0 status=1
[WIFIAP] WiFi init OK.
[WIFIAP] [DIAG] after init: wifi_is_wifi_inited()=1
[WIFIAP] Register event callback OK (sta_join / sta_leave).
[WIFIAP] SSID    : H
[WIFIAP] PASSWORD: 12345678
[WIFIAP] SECURITY: WPA/WPA2-PSK MIX, CHANNEL: 6
[WIFIAP] [DIAG] set_softap_config_advance ret=0 (hidden_ssid_flag=1)
[WIFIAP] [DIAG] wifi_softap_enable try 1/60 ret=0 (init_status=1)
[WIFIAP] SoftAP enabled OK. SSID "H" is now broadcasting.
[WIFIAP] [DIAG] netif_set_addr ret=0   dhcps_start ret=0
[WIFIAP] DHCP server started OK (pool 192.168.63.x)
[WIFIAP] netif IP=192.168.63.1 MASK=255.255.255.0 GW=192.168.63.2
[WIFIAP] SoftAp start success.
[WIFIAP] >>> 请用手机 WLAN 搜索热点 "H"，输入密码 12345678 连接 <<<
[WIFIAP] Waiting for phone ... (poll 2000 ms)
[WIFIAP] [DIAG] heartbeat: init_status=1, netif=ap0-ready, stations=0
[WIFIAP] Connected stations: 1
[WIFIAP] [EVENT] STA JOIN  MAC=xx:xx:xx:xx:xx:xx  RSSI=-45 dBm  RATE=65000 kbps
[WIFIAP] ****** 手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS ******
[WIFIAP] [DHCP] phone MAC=xx:xx:xx:xx:xx:xx  IP=192.168.63.3
[WIFIAP] LINK UP: phone -> AP(H)  AP=192.168.63.1  phone=192.168.63.3
[WIFIAP] ---------------- RESULT / 实训验收 ----------------
[WIFIAP] ****** 手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS ******
[WIFIAP] ---------------- RESULT END ----------------
```

> 注：MAC / IP / RSSI 为实际手机的值；烧录后按 RESET，打开串口监视器（115200）即可看到。

---

# wifiap

## 1.1 介绍

**功能介绍：** 实现手机等其他设备连接核心板热点，案例核心板热点需要设置为SSID：H， 密码：12345678。

**硬件概述：** 核心板。硬件搭建要求如图所示：

<img src="../../doc/media/ultrasonic/image-20240415144302434.png" alt="image-20240415144302434" style="zoom:67%;" />

## 1.2 约束与限制

### 1.2.1 支持应用运行的芯片和开发板

本示例支持开发板：HiHope_NearLink_DK3863E_V03

### 1.2.2 支持API版本、SDK版本

本示例支持版本号：1.10.101及以上

### 1.2.3 支持IDE插件版本

本示例支持IDE插件版本号：1.0.1及以上；

## 1.3 效果预览

手机WLAN搜索热点H，搜索成功后，输入密码：”12345678“进行连接。

![image-20240418174657120](../../doc/media/wifiap/image-20240418174657120.png)

## 1.4 接口介绍

### 1.4.1 wifi_softap_enable()


| **定义：**   | errcode_t wifi_softap_enable(const softap_config_stru *config); |
| ------------ | --------------------------------------------------------------- |
| **功能：**   | 开启SoftAP                                                      |
| **参数：**   | config：SoftAp的配置                                            |
| **返回值：** | ERROCODE_SUCC：成功    Other：失败                              |
| **依赖：**   | include\middleware\services\wifi\wifi_hotspot.h                 |

### 1.4.2 netifapi_netif_set_addr()


| **定义：**   | err_t netifapi_netif_set_addr(struct netif *netif, const ip4_addr_t *ipaddr, const ip4_addr_t *netmask, const ip4_addr_t *gw); |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| **功能：**   | 设置网络接口的IP地址                                                                                                           |
| **返回值：** | ERROCODE_SUCC：成功    Other：失败                                                                                             |
| **依赖：**   | open_source\lwip\lwip_v2.1.3\src\include\lwip\netifapi.h                                                                       |

### 1.4.3 netifapi_dhcps_start()


| **定义：**   | err_t netifapi_dhcps_start(struct netif *netif, char *start_ip, u16_t ip_num); |
| ------------ | ------------------------------------------------------------------------------ |
| **功能：**   | 启动dhcp服务                                                                   |
| **返回值：** | ERROCODE_SUCC：成功    Other：失败                                             |
| **依赖：**   | open_source\lwip\lwip_v2.1.3\src\include\lwip\netifapi.h                       |

## 1.5 具体实现

步骤一：初始化WiFi。

步骤二：启动WiFi AP模式。

步骤三：配置DHCP服务器。

## 1.6 实验流程

- 步骤一：在xxx\src\application\samples\peripheral文件夹新建一个sample文件夹，在peripheral上右键选择“新建文件夹”，创建Sample文件夹，例如名称”wifiap“。

  ![image-70551992](../../doc/media/beep/image-20240801170551992.png)
- 步骤二：将xxx\vendor\HiHope_NearLink_DK_WS63E_V03\wifiap文件里面内容拷贝到**步骤一创建的Sample文件夹中”wifiap“**下。

  ![image-20240418174149411](../../doc/media/wifiap/image-20240418174149411.png)
- 步骤三：在xxx\src\application\samples\peripheral\CMakeLists.txt文件中新增编译案例，具体如下图所示（如果不知道在哪个地方加的，可以在“set(SOURCES "${SOURCES}" PARENT_SCOPE)”上面一行添加）。

  ![image-20240805112605157](../../doc/media/wifiap/image-20240805112605157.png)
- 步骤四：在xxx\src\application\samples\peripheral\Kconfig文件中新增编译案例，具体如下图所示（如果不知道在哪个地方加，可以在最后一行添加）。

  ![image-20240805112623523](../../doc/media/wifiap/image-20240805112623523.png)
- 步骤五：点击如下图标，选择KConfig，具体选择路径“Application/Enable the Sample of peripheral”，在弹出框中选择“support WIFIAP Sample”，点击Save，关闭弹窗。

  <img src="../../doc/media/beep/image-20240801171406113.png" alt="image-20240801171406113" style="zoom: 67%;" /><img src="../../doc/media/wifiap/image-20240205105234692-17119401758316.png" alt="image-20240205105234692" style="zoom: 50%;" /><img src="../../doc/media/wifiap/image-20240418174332350.png" alt="image-20240418174332350" style="zoom:67%;" />
- 步骤六：点击“build”或者“rebuild”编译

  ![image-20250716163653427](../../doc/media/readme/image-20250716163653427.png)
- 步骤七：编译完成如下图所示。

  ![image-20250307164622717](../../doc/media/readme/image-20250307164622717.png)
- 步骤八：在HiSpark Studio工具中点击“工程配置”按钮，选择“程序加载”，传输方式选择“serial”，端口选择“comxxx”，com口在设备管理器中查看（如果找不到com口，请参考windows环境搭建）。

  ![image-20250716164922699](../../doc/media/readme/image-20250716164922699.png)
- 步骤九：配置完成后，点击工具“程序加载”按钮烧录。

  ![image-20250716170835615](../../doc/media/readme/image-20250716170835615.png)
- 步骤十：出现“Connecting, please reset device...”字样时，复位开发板，等待烧录结束。

  ![image-20240801174230202](../../doc/media/led/image-20240801174230202.png)
- 步骤十一：手机WLAN搜索热点H，搜索成功后，输入密码：”12345678“进行连接。

  ![image-20240418174657120](../../doc/media/wifiap/image-20240418174657120.png)
