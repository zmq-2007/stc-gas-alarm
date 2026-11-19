# stc-gas-alarm

## 蜂鸣器 PWM 交互式实训网页

按《实训指导任务书》的 8 个步骤一比一还原真实开发流程：新建 beep 样例文件夹、拷贝 vendor 样例、修改 CMakeLists.txt / Kconfig、menuconfig 勾选、build 编译、编译与烧写、现象验收。代码可在线编辑并提交，**只有网页内编译通过**才会解锁虚拟蜂鸣器实验台。

实验台包含：单调响声 + 实时 PWM 波形、《数鸭子》音乐演奏 + 同步 PWM 波形、关键控制代码逐段分析。

## WiFi AP 实训：手机连接核心板热点

按《星闪实验指导手册》wifiap 章节的 11 个步骤一比一还原：新建 wifiap 样例、拷贝 vendor/wifiap、注册编译、menuconfig、build、工程配置 serial、程序加载、按 RESET、手机 WLAN 连接热点 H（密码 12345678）。

- 编译门禁：三份代码提交并通过网页内编译校验后，才解锁虚拟 AP 实验台。
- 串口监视器：逐行还原固件 `PRINT` 输出，手机一连上即出现 `手机连接热点成功 / PHONE CONNECTED HOTSPOT SUCCESS`、STA MAC、RSSI 与 DHCP 分配的 `192.168.63.x`。
- 手机模拟界面：WLAN 扫描 → 选中 H → 输入密码 → 已连接并显示 IP。
- 关键控制代码分析 6 张卡片：热点参数、SoftAP 启动、DHCP、事件回调、站点列表与租约查询、任务入口。

- 在线打开：<https://zmq-2007.github.io/stc-gas-alarm/>
- 源文件：[index.html](index.html)（单文件、零外部依赖，可下载后直接用浏览器打开）
- 板卡源码与串口工具：[wifiap/](wifiap/)（softap_sample.c、CMakeLists.txt、README、串口监视脚本、预期串口日志）

> 网页与实训资料同时存在于 `main`（默认分支，GitHub Pages 部署源）与 `master` 分支。
