# 适配 rootless Docker 环境

> 方案文档。状态:已实施(2026-11-23,rootful 环境已回归验证;rootless 主机实测待进行)。
> 日志链路已完成 docker.sock 去依赖(改用 docker syslog 驱动 → Alloy);`docker.sock` 仅剩内嵌 cAdvisor 的容器元数据用途。

## 目标

- 整套栈在 rootless Docker 下以普通用户完整运行,不引入任何新的特权要求。
- rootful Docker 保持可用(双模式兼容)。
- 消除对 `privileged`、`pid: host` 及 Prometheus 以 root 运行的依赖。

## 背景:当前与 rootless 不兼容的点

| 位置 | 现状 | rootless 下的问题 |
|------|------|-------------------|
| `compose.d/core.yaml` | Prometheus `user: root` + 挂载 `/var/run/docker.sock`(docker_sd) | socket 路径不同;rootful socket 风险高 |
| `compose.d/exporters.yaml` | node-exporter `pid: host` | rootless 不支持 `pid: host` |
| `compose.d/exporters.yaml` | cadvisor `privileged` + `/dev/kmsg` + `/var/lib/docker` 挂载 | rootless 下 `privileged` 无效,宿主目录挂载受限 |
| `compose.d/logging.yaml` | Alloy 经 `/var/run/docker.sock` 采集容器日志(`loki.source.docker`) | rootless socket 路径不同;rootful 下 socket 权限过高 |

rootless 下 socket 位于 `$XDG_RUNTIME_DIR/docker.sock`(如 `/run/user/1000/docker.sock`),属主为普通用户,挂载进容器后的风险等级为**用户级**而非 root 级。

## 方案设计

### 1. Prometheus 服务发现改静态配置

- `config/prometheus/prometheus.yml` 删除 `docker_sd` 任务,新增静态任务:
  - `demo-web:8080`、`nginx-exporter:9113`、`caddy:2019`
- `compose.d/core.yaml` 移除 docker.sock 挂载与 `user: root`,Prometheus 恢复默认非 root 用户。
- `compose.d/examples.yaml` 删除全部 `prometheus.io/*` 标签。
- 代价:示例服务未启动时,Prometheus 目标页对应目标显示 DOWN(可接受)。

### 2. node-exporter rootless 兼容

- 移除 `pid: host`;保留 `/proc`、`/sys`、`/` 只读挂载。
- 进程指标经 `--path.procfs=/host/proc` 继续可用。
- 文档注明 rootless 下部分 collector(温度、hwmon、systemd 单元等)可能降级或缺失。

### 3. cadvisor 统一内嵌进 Alloy

- 删除独立 cadvisor 容器(`privileged`、`/dev/kmsg`、`/var/lib/docker` 挂载在 rootless 下不可用)。
- Alloy 配置新增 `prometheus.exporter.cadvisor`(v1.4.2 已内置,GA):
  - `docker_host` 指向参数化 socket;
  - 新增 `prometheus.scrape` 抓取其导出目标,与日志接收共用同一个 Alloy 实例。
- 抓取结果经 `prometheus.remote_write` 推送到 Prometheus;Prometheus 已启用 `--web.enable-remote-write-receiver`(core.yaml)。
- Alloy 服务补充该组件所需的 cgroup/sys 只读挂载;`/dev/kmsg` 能力在 rootless 下缺失,相关指标自然降级。

### 4. 日志链路:docker syslog 驱动 → Alloy(不再使用 docker.sock)

- 全部服务(除 Alloy 自身)配置 `logging: driver: syslog`,RFC5424/TCP,`syslog-address: tcp://127.0.0.1:1514`;Alloy 发布 `127.0.0.1:${ALLOY_SYSLOG_PORT:-1514}:1514`(仅回环,不对外)。
- 日志驱动运行在宿主 dockerd,回环连接与 rootful/rootless 均兼容,无 socket 依赖。
- Alloy 配置改用 `loki.source.syslog`(v1.4.2 已 GA),自动识别 docker 的 octet-counting TCP 帧;各服务 `tag`(RFC5424 APP-NAME)经 relabel 映射为 Loki 的 `service` 标签。
- 启动顺序:syslog 驱动在容器创建时即需连上接收端,故其余服务 `depends_on: alloy(condition: service_healthy)`;Alloy 以 bash `/dev/tcp` 探活 1514 作为健康检查,并移除其对 loki 的启动依赖(日志由 WAL 缓冲,无循环依赖)。
- Alloy 自身保留默认 json-file 驱动,避免日志回环;Alloy 停机期间,其他服务新产生的日志会被 docker 丢弃(驱动同步模式),Alloy 恢复后自动续传。
- `docker.sock` 挂载仅保留给内嵌 cAdvisor 的容器元数据(rootless 下指向 `$XDG_RUNTIME_DIR/docker.sock`,属用户级 socket)。

### 5. 配置与工具

- `.env.example` 新增 `ROOTLESS`、`DOCKER_SOCKET` 变量及取值说明。
- `Makefile`:
  - `setup` 保持 0777 数据目录方案(rootless 下容器内 uid 映射为 subuid,仍需可写权限)。
  - 新增 `make doctor` 目标:检测是否 rootless、socket 路径是否存在,并输出 `DOCKER_SOCKET` 配置提示。
- README 新增「rootless 运行」章节:启用方式、双模式差异表、已知限制;更新 TODO(#1 完成、#2 缩小为仅日志链路)。

## 双模式行为差异

| 项目 | rootful | rootless |
|------|---------|----------|
| docker.sock | 仅内嵌 cAdvisor 容器元数据使用(root 级) | 仅内嵌 cAdvisor 容器元数据使用(用户级) |
| 容器日志 | docker syslog 驱动 → 127.0.0.1:1514 → Alloy | 同左(驱动运行在用户级 dockerd,回环发送) |
| node-exporter | 完整采集 | 部分 collector 降级 |
| cadvisor | Alloy 内嵌 + 宿主 cgroup 读取 | 同左;cgroup 读取受限程度需实测 |
| Prometheus | 非 root,无 socket | 同左 |
| 数据目录 | `make setup` 0777 | 同左 |

## 验证计划

- rootful(当前环境):
  - 重建全栈,回归指标、日志、Grafana 仪表盘(已完成:syslog 日志入库 0 解析错误、cAdvisor remote_write 正常、静态目标全 up);
  - 已实测:Alloy 停机时运行中服务不受影响、日志丢失,Alloy 恢复后自动续传;caddy profile 依赖链正常。
- rootless(有 rootless 主机时):
  - `make doctor` 通过 → `make up`;
  - 验证容器以用户 uid 运行、syslog 日志入 Loki、主机指标可查、内嵌 cadvisor 提供容器指标。
- 降级对照:记录 rootless 下 node-exporter/cadvisor 缺失的 collector 清单,写入 README。

## 已知限制与降级

- rootless 下 cgroup 读取受限,内嵌 cadvisor 的容器指标可能不全;不可用时降级为「仅主机指标 + 文档标注」。
- 启用 containerd image store 的 Docker(如 Docker 29 的 `io.containerd.snapshotter.v1`)不再维护传统 `layerdb/mounts` 路径,内嵌 cAdvisor 会持续输出 `read-write layer ID` 警告、无法归因镜像层,容器 CPU/内存/网络等 cgroup 指标不受影响;经典 graphdriver 环境无此问题。
- rootless 使用 fuse-overlayfs/slirp4netns,存储与网络性能低于 rootful,属运行时特性,不在本方案内处理。
- 日志链路为「尽力而为」:Alloy 停机期间的日志丢失,且启动新容器时若 Alloy 未就绪会失败(depends_on 已规避,宿主重启场景由 restart 重试自愈)。

## 假设与后续

- 假设:双模式兼容(非 rootless-only)。
- 日志链路替换已完成(docker syslog 驱动 + `loki.source.syslog`),TODO#2 关闭。
- 后续(可选):内嵌 cAdvisor 的容器元数据去 socket 化(候选:containerd socket 或静态 cgroup 映射),彻底移除 `docker.sock` 挂载。
