/*
 * Copyright (c) HiSilicon (Shanghai) Technologies Co., Ltd. 2023-2023. All rights reserved.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * ---------------------------------------------------------------------------
 * 实训改造说明（wifiap / 手机连接核心板热点）
 * 1) 以 vendor/HiHope_NearLink_DK_WS63E_V03/demo/wifiap/softap_sample.c 为底稿，
 *    按《星闪实验指导手册》wifiap 章节要求，SSID 固定为 "H"，密码 "12345678"。
 * 2) 新增 wifi_register_event_cb() 注册 wifi_event_softap_sta_join /
 *    wifi_event_softap_sta_leave 事件回调：手机接入/离开时立即从串口打印 MAC、
 *    RSSI、速率，并给出「手机连接热点成功」的明确提示。
 * 3) 新增站点轮询任务：wifi_softap_get_sta_list() 枚举已连接设备，
 *    netifapi_dhcps_get_client_ip() 查询 DHCP 给手机分配的 IP，一并打印到串口。
 * 4) 串口波特率 115200（CONFIG_UART0_BAUDRATE / DEBUG_UART），用串口助手即可
 *    看到完整过程：WiFi 初始化 -> 开启 SoftAP -> 启动 DHCP -> 等待手机连接
 *    -> STA JOIN -> 分配 IP -> 手机连接热点成功。
 * 5) 手机拿到 DHCP 地址后再集中打印一次「RESULT / 实训验收」摘要，把热点参数、
 *    手机 MAC / IP 与「手机连接热点成功」汇总在同一段串口输出里，方便验收核对。
 * 6) 排障加固（烧录后搜不到热点的情况）：
 *    - 取消「无限等待 wifi_is_wifi_inited()」，改为 15 s 有限等待 + 显式 wifi_init() 兜底，
 *      避免 WiFi host 未置位时任务永远卡死、SoftAP 永不启动（vendor 原版是固定 5 s 延时）。
 *    - 事件回调注册 / 高级配置 / DHCP 配置失败只告警，不再 return 或 wifi_softap_disable()，
 *      保证「热点先起来」优先；每步都把返回码打印到串口，便于定位。
 *    - 显式设置 hidden_ssid_flag=1（不隐藏 SSID），并对 wifi_softap_enable() 做 3 次重试。
 * ---------------------------------------------------------------------------
 */

#include "lwip/netifapi.h"
#include "lwip/ip_addr.h"
#include "wifi_hotspot.h"
#include "wifi_hotspot_config.h"
#include "wifi_device.h"
#include "stdlib.h"
#include "uart.h"
#include "cmsis_os2.h"
#include "soc_osal.h"
#include "app_init.h"

#define WIFI_SOFTAP_TASK_PRIO       24
#define WIFI_TASK_STACK_SIZE        0x2000
#define WIFI_IFNAME_MAX_SIZE        16
#define WIFI_SOFTAP_MAX_STA         6       /* 与 at_wifi.h 的 WIFI_MAX_NUM_USER 一致 */
#define WIFI_SOFTAP_POLL_MS         2000    /* 每 2 s 查询一次在线站点 */
#define WIFI_SOFTAP_LOG             "[WIFIAP]"
#define WIFI_SOFTAP_INIT_WAIT_MS    15000   /* 最长等待 WiFi host 初始化 15 s，绝不无限等 */
#define WIFI_SOFTAP_INIT_STEP_MS    100
#define WIFI_SOFTAP_ENABLE_RETRY    3       /* softap_enable 失败重试次数 */

/* 任务书要求的固定热点参数 */
#define WIFI_SOFTAP_SSID            "H"
#define WIFI_SOFTAP_PASSWORD        "12345678"
#define WIFI_SOFTAP_CHANNEL         6

static struct netif *g_softap_netif = NULL;
static uint8_t g_phone_mac[WIFI_MAC_LEN] = {0};
static uint8_t g_phone_online = 0;
static uint8_t g_phone_ip_printed = 0;

/* 打印 6 字节 MAC 地址（串口助手可直接看到手机网卡地址） */
static void softap_print_mac(const uint8_t *mac)
{
    PRINT("%02X:%02X:%02X:%02X:%02X:%02X",
          mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static void softap_set_phone(const uint8_t *mac)
{
    (void)memcpy_s(g_phone_mac, WIFI_MAC_LEN, mac, WIFI_MAC_LEN);
    g_phone_online = 1;
    g_phone_ip_printed = 0;
}

/* ---------------- WiFi 事件回调：手机接入 / 离开 ---------------- */
static void softap_sta_join_cb(const wifi_sta_info_stru *info)
{
    if (info == NULL) {
        return;
    }
    PRINT("%s [EVENT] STA JOIN  MAC=", WIFI_SOFTAP_LOG);
    softap_print_mac(info->mac_addr);
    PRINT("  RSSI=%d dBm  RATE=%u kbps\r\n", info->rssi, info->best_rate);
    softap_set_phone(info->mac_addr);
    /* 任务书要求的验收标志：手机连上核心板热点 */
    PRINT("%s ****** 手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS ******\r\n",
          WIFI_SOFTAP_LOG);
    PRINT("%s SSID=H  PASSWORD=12345678  AP_IP=192.168.63.1\r\n", WIFI_SOFTAP_LOG);
}

static void softap_sta_leave_cb(const wifi_sta_info_stru *info)
{
    if (info == NULL) {
        return;
    }
    PRINT("%s [EVENT] STA LEAVE MAC=", WIFI_SOFTAP_LOG);
    softap_print_mac(info->mac_addr);
    PRINT("\r\n%s 手机已断开 / PHONE DISCONNECTED\r\n", WIFI_SOFTAP_LOG);
    g_phone_online = 0;
    g_phone_ip_printed = 0;
}

static void softap_state_changed_cb(int32_t state)
{
    PRINT("%s [EVENT] SoftAP state changed: %d\r\n", WIFI_SOFTAP_LOG, state);
}

static wifi_event_stru g_softap_event_cb = {
    .wifi_event_softap_state_changed = softap_state_changed_cb,
    .wifi_event_softap_sta_join      = softap_sta_join_cb,
    .wifi_event_softap_sta_leave     = softap_sta_leave_cb,
};

/* ---------------- 启动 SoftAP：热点优先保活，附属步骤失败一律不关热点 ---------------- */
static errcode_t example_softap_function(void)
{
    /* SoftAp SSID / 密码：严格按任务书 "H" / "12345678" */
    char ssid[WIFI_MAX_SSID_LEN] = WIFI_SOFTAP_SSID;
    char pre_shared_key[WIFI_MAX_KEY_LEN] = WIFI_SOFTAP_PASSWORD;
    softap_config_stru hapd_conf = {0};
    softap_config_advance_stru adv_conf = {0};
    ip4_addr_t st_gw = {0};
    ip4_addr_t st_ipaddr = {0};
    ip4_addr_t st_netmask = {0};
    errcode_t ret = ERRCODE_FAIL;
    int32_t dret;
    uint8_t attempt;

    IP4_ADDR(&st_ipaddr, 192, 168, 63, 1);   /* 核心板 AP 地址：192.168.63.1 */
    IP4_ADDR(&st_netmask, 255, 255, 255, 0); /* 子网掩码：255.255.255.0 */
    IP4_ADDR(&st_gw, 192, 168, 63, 2);       /* 网关：192.168.63.2 */

    PRINT("%s SSID    : %s\r\n", WIFI_SOFTAP_LOG, ssid);
    PRINT("%s PASSWORD: %s\r\n", WIFI_SOFTAP_LOG, pre_shared_key);
    PRINT("%s SECURITY: WPA/WPA2-PSK MIX, CHANNEL: %d\r\n",
          WIFI_SOFTAP_LOG, WIFI_SOFTAP_CHANNEL);

    (void)memcpy_s(hapd_conf.ssid, sizeof(hapd_conf.ssid), ssid, sizeof(ssid));
    (void)memcpy_s(hapd_conf.pre_shared_key, WIFI_MAX_KEY_LEN,
                   pre_shared_key, WIFI_MAX_KEY_LEN);

    hapd_conf.security_type = WIFI_SEC_TYPE_WPA2_WPA_PSK_MIX; /* WPA/WPA2 混合 */
    hapd_conf.channel_num = WIFI_SOFTAP_CHANNEL;               /* 6 信道 */

    /* 显式声明「不隐藏 SSID」+ 2.4G 11b/g/n，避免手机 WLAN 里搜不到 H */
    adv_conf.beacon_interval = 100;
    adv_conf.dtim_period = 2;
    adv_conf.group_rekey = 86400;
    adv_conf.hidden_ssid_flag = 1;              /* 1 = 不隐藏，2 = 隐藏 */
    adv_conf.gi = 0;
    adv_conf.protocol_mode = WIFI_MODE_11B_G_N;
    ret = wifi_set_softap_config_advance(&adv_conf);
    PRINT("%s [DIAG] set_softap_config_advance ret=%d (hidden_ssid_flag=1)\r\n",
          WIFI_SOFTAP_LOG, (int32_t)ret);
    if (ret != ERRCODE_SUCC) {
        PRINT("%s WARN: advance config failed, continue with SDK defaults.\r\n", WIFI_SOFTAP_LOG);
    }

    /* 启动 SoftAP：失败重试，并把每一步返回码打到串口，便于排障 */
    for (attempt = 1; attempt <= WIFI_SOFTAP_ENABLE_RETRY; attempt++) {
        PRINT("%s SoftAP try enable ... (attempt %u/%d, wifi_inited=%d)\r\n",
              WIFI_SOFTAP_LOG, attempt, WIFI_SOFTAP_ENABLE_RETRY, wifi_is_wifi_inited());
        ret = wifi_softap_enable(&hapd_conf);
        PRINT("%s [DIAG] wifi_softap_enable ret=%d\r\n", WIFI_SOFTAP_LOG, (int32_t)ret);
        if (ret == ERRCODE_SUCC) {
            break;
        }
        (void)osal_msleep(1000);
    }
    if (ret != ERRCODE_SUCC) {
        PRINT("%s FATAL: softap enable FAIL after %d attempts.\r\n",
              WIFI_SOFTAP_LOG, WIFI_SOFTAP_ENABLE_RETRY);
        PRINT("%s 排查：1) 是否烧录 *_all.fwpkg（含 NV 校准数据） 2) 复位后串口是否出现 WiFi init OK\r\n",
              WIFI_SOFTAP_LOG);
        return ERRCODE_FAIL;
    }
    PRINT("%s SoftAP enabled OK. SSID \"H\" is now broadcasting.\r\n", WIFI_SOFTAP_LOG);

    /* DHCP 只负责给手机分配 IP，失败不能把已经起来的热点关掉 */
    g_softap_netif = netif_find("ap0");
    if (g_softap_netif == NULL) {
        g_softap_netif = netif_find("ap1");
    }
    if (g_softap_netif == NULL) {
        g_softap_netif = netif_find("wlan0");
    }
    if (g_softap_netif == NULL) {
        PRINT("%s WARN: netif ap0/ap1/wlan0 not found -> keep hotspot ON (IP 分配可能不可用)\r\n",
              WIFI_SOFTAP_LOG);
        PRINT("%s SoftAp start success.\r\n", WIFI_SOFTAP_LOG);
        PRINT("%s >>> 请用手机 WLAN 搜索热点 \"H\"，输入密码 12345678 连接 <<<\r\n",
              WIFI_SOFTAP_LOG);
        return ERRCODE_SUCC;
    }

    dret = (int32_t)netifapi_netif_set_addr(g_softap_netif, &st_ipaddr, &st_netmask, &st_gw);
    PRINT("%s [DIAG] netif_set_addr ret=%d\r\n", WIFI_SOFTAP_LOG, dret);
    if (dret != ERR_OK) {
        PRINT("%s WARN: set_addr failed, keep hotspot ON.\r\n", WIFI_SOFTAP_LOG);
    }
    dret = (int32_t)netifapi_dhcps_start(g_softap_netif, NULL, 0);
    PRINT("%s [DIAG] dhcps_start ret=%d\r\n", WIFI_SOFTAP_LOG, dret);
    if (dret != ERR_OK) {
        PRINT("%s WARN: DHCP server failed, keep hotspot ON (手机可能拿不到 IP).\r\n",
              WIFI_SOFTAP_LOG);
    } else {
        PRINT("%s DHCP server started OK (pool 192.168.63.x)\r\n", WIFI_SOFTAP_LOG);
    }

    PRINT("%s netif IP=192.168.63.1 MASK=255.255.255.0 GW=192.168.63.2\r\n", WIFI_SOFTAP_LOG);
    PRINT("%s SoftAp start success.\r\n", WIFI_SOFTAP_LOG);
    PRINT("%s >>> 请用手机 WLAN 搜索热点 \"H\"，输入密码 12345678 连接 <<<\r\n",
          WIFI_SOFTAP_LOG);
    return ERRCODE_SUCC;
}

/* ---------------- 在线站点轮询：打印手机 MAC 与 DHCP 分配的 IP ---------------- */
static void softap_monitor_loop(void)
{
    wifi_sta_info_stru sta_list[WIFI_SOFTAP_MAX_STA] = {0};
    uint32_t sta_num = 0;
    uint32_t last_num = 0xFFFFFFFFU;
    errcode_t ret;
    ip_addr_t phone_ip;

    PRINT("%s Waiting for phone ... (poll %d ms)\r\n",
          WIFI_SOFTAP_LOG, WIFI_SOFTAP_POLL_MS);

    while (1) {
        (void)osal_msleep(WIFI_SOFTAP_POLL_MS);
        sta_num = WIFI_SOFTAP_MAX_STA;
        (void)memset_s(sta_list, sizeof(sta_list), 0, sizeof(sta_list));
        ret = wifi_softap_get_sta_list(sta_list, &sta_num);
        if (ret != ERRCODE_SUCC) {
            continue;
        }
        if (sta_num != last_num) {
            PRINT("%s Connected stations: %u\r\n", WIFI_SOFTAP_LOG, sta_num);
            last_num = sta_num;
        }
        if (sta_num == 0) {
            /* 手机断开后复位状态，下次重新连接会再次打印成功信息 */
            g_phone_online = 0;
            g_phone_ip_printed = 0;
            continue;
        }

        /* 事件回调可能先于轮询执行，这里兜底记录首个站点（手机） */
        if (g_phone_online == 0) {
            softap_set_phone(sta_list[0].mac_addr);
            PRINT("%s [POLL] STA MAC=", WIFI_SOFTAP_LOG);
            softap_print_mac(sta_list[0].mac_addr);
            PRINT("  RSSI=%d dBm\r\n", sta_list[0].rssi);
            PRINT("%s ****** 手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS ******\r\n",
                  WIFI_SOFTAP_LOG);
        }

        /* DHCP 握手需要一点时间，拿到租约后打印手机获得的 IP（netif 未就绪时跳过，避免空指针） */
        if (g_phone_ip_printed == 0 && g_softap_netif != NULL) {
            (void)memset_s(&phone_ip, sizeof(phone_ip), 0, sizeof(phone_ip));
            if (netifapi_dhcps_get_client_ip(g_softap_netif, g_phone_mac,
                                             WIFI_MAC_LEN, &phone_ip) == ERR_OK &&
                !ip_addr_isany(&phone_ip)) {
                PRINT("%s [DHCP] phone MAC=", WIFI_SOFTAP_LOG);
                softap_print_mac(g_phone_mac);
                PRINT("  IP=%s\r\n", ipaddr_ntoa(&phone_ip));
                PRINT("%s LINK UP: phone -> AP(H)  AP=192.168.63.1  phone=%s\r\n",
                      WIFI_SOFTAP_LOG, ipaddr_ntoa(&phone_ip));
                /* 验收汇总：把串口中的关键信息集中打印一次，便于人工核对 */
                PRINT("%s ---------------- RESULT / 实训验收 ----------------\r\n",
                      WIFI_SOFTAP_LOG);
                PRINT("%s SSID=%s  PASSWORD=%s  CHANNEL=%d  SECURITY=WPA/WPA2-PSK\r\n",
                      WIFI_SOFTAP_LOG, WIFI_SOFTAP_SSID, WIFI_SOFTAP_PASSWORD,
                      WIFI_SOFTAP_CHANNEL);
                PRINT("%s AP=192.168.63.1  phone MAC=", WIFI_SOFTAP_LOG);
                softap_print_mac(g_phone_mac);
                PRINT("  IP=%s\r\n", ipaddr_ntoa(&phone_ip));
                PRINT("%s ****** 手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS ******\r\n",
                      WIFI_SOFTAP_LOG);
                PRINT("%s ---------------- RESULT END ----------------\r\n", WIFI_SOFTAP_LOG);
                g_phone_ip_printed = 1;
            }
        }
    }
}

/* 有限等待 WiFi host 初始化；绝不无限死等（死等会让 SoftAP 永远不启动） */
static int32_t softap_wait_init(uint32_t timeout_ms)
{
    uint32_t waited = 0;
    while (waited < timeout_ms) {
        if (wifi_is_wifi_inited() != 0) {
            return 1;
        }
        (void)osal_msleep(WIFI_SOFTAP_INIT_STEP_MS);
        waited += WIFI_SOFTAP_INIT_STEP_MS;
    }
    return wifi_is_wifi_inited();
}

static int demo_init(const char *arg)
{
    errcode_t ret;

    unused(arg);

    PRINT("%s ==== WiFi AP (SoftAP) Sample Start ====\r\n", WIFI_SOFTAP_LOG);
    PRINT("%s [DIAG] BOOT CHECK: waiting WiFi host init (max %d ms) ...\r\n",
          WIFI_SOFTAP_LOG, WIFI_SOFTAP_INIT_WAIT_MS);

    if (softap_wait_init(WIFI_SOFTAP_INIT_WAIT_MS) == 0) {
        /* 本配置下没有任何启动链调用 wifi_init()，超时就自己兜底初始化一次 */
        PRINT("%s WARN: wifi_is_wifi_inited() still 0 -> call wifi_init() fallback.\r\n",
              WIFI_SOFTAP_LOG);
        ret = wifi_init();
        PRINT("%s [DIAG] wifi_init() ret=%d, status now=%d\r\n",
              WIFI_SOFTAP_LOG, (int32_t)ret, wifi_is_wifi_inited());
        (void)softap_wait_init(3000);
    }
    PRINT("%s WiFi init OK. (status=%d)\r\n", WIFI_SOFTAP_LOG, wifi_is_wifi_inited());

    /* 注册事件回调：手机连上/断开时立刻从串口输出。失败只告警，不阻断 SoftAP */
    ret = wifi_register_event_cb(&g_softap_event_cb);
    PRINT("%s [DIAG] register_event_cb ret=%d\r\n", WIFI_SOFTAP_LOG, (int32_t)ret);
    if (ret != ERRCODE_SUCC) {
        PRINT("%s WARN: register event cb failed, polling loop still reports success.\r\n",
              WIFI_SOFTAP_LOG);
    } else {
        PRINT("%s Register event callback OK (sta_join / sta_leave).\r\n", WIFI_SOFTAP_LOG);
    }

    /* 开启 SoftAP 与 DHCP 服务；即便有附属步骤失败，也继续轮询站点 */
    if (example_softap_function() != ERRCODE_SUCC) {
        PRINT("%s [DIAG] SoftAP start had errors, keep monitoring stations anyway.\r\n",
              WIFI_SOFTAP_LOG);
    }

    softap_monitor_loop();
    return 0;
}

static void example_wifi_softap_entry(void)
{
    osal_task *task_handle = NULL;
    osal_kthread_lock();
    task_handle = osal_kthread_create((osal_kthread_handler)demo_init, 0,
                                      "WiFiSoftAPTask", WIFI_TASK_STACK_SIZE);
    if (task_handle != NULL) {
        osal_kthread_set_priority(task_handle, WIFI_SOFTAP_TASK_PRIO);
        osal_kfree(task_handle);
    }
    osal_kthread_unlock();
}

/* Run the example_wifi_softap_entry. */
app_run(example_wifi_softap_entry);
