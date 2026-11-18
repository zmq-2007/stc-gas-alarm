# stc-gas-alarm

## 蜂鸣器 PWM 交互式实训网页

按《实训指导任务书》的 8 个步骤一比一还原真实开发流程：新建 beep 样例文件夹、拷贝 vendor 样例、修改 CMakeLists.txt / Kconfig、menuconfig 勾选、build 编译、编译与烧写、现象验收。代码可在线编辑并提交，**只有网页内编译通过**才会解锁虚拟蜂鸣器实验台。

- 在线打开：<https://zmq-2007.github.io/stc-gas-alarm/>
- 源文件：[index.html](index.html)（单文件、零外部依赖，也可下载后用浏览器直接打开）
- 实验台包含：单调响声 + 实时 PWM 波形、《数鸭子》音乐演奏 + 同步 PWM 波形、关键控制代码逐段分析

> 网页同时存在于 `main`（默认分支，GitHub Pages 部署源）与 `master` 分支。
