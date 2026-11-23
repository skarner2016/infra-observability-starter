# 适配 rootless Docker 环境

> 方案文档。状态:已实施(2026-11-23,rootful 环境已回归验证;rootless 主机实测待进行)。

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
| `compose.d/logging.yaml` | Alloy 挂载 `/var/run/docker.sock` | 路径需参数化 |

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
  - 新增 `prometheus.scrape` 抓取其导出目标,与现有日志采集共用同一个 Alloy 实例。
- 抓取结果经 `prometheus.remote_write` 推送到 Prometheus;Prometheus 已启用 `--web.enable-remote-write-receiver`(core.yaml)。
- Alloy 服务补充该组件所需的 cgroup/sys 只读挂载;`/dev/kmsg` 能力在 rootless 下缺失,相关指标自然降级。

### 4. Socket 路径参数化(日志采集暂维持 Alloy)

- 日志链路本次不改架构(接收端方案待 TODO#2 决策),仅将 `/var/run/docker.sock` 统一改为 `${DOCKER_SOCKET:-/var/run/docker.sock}`。
- rootless 下在 `.env` 设置 `DOCKER_SOCKET=$XDG_RUNTIME_DIR/docker.sock`。
- 这是 rootful 下唯一的残留 socket 用户(日志采集),风险与现状一致,待日志链路替换后一并消除。

### 5. 配置与工具

- `.env.example` 新增 `ROOTLESS`、`DOCKER_SOCKET` 变量及取值说明。
- `Makefile`:
  - `setup` 保持 0777 数据目录方案(rootless 下容器内 uid 映射为 subuid,仍需可写权限)。
  - 新增 `make doctor` 目标:检测是否 rootless、socket 路径是否存在,并输出 `DOCKER_SOCKET` 配置提示。
- README 新增「rootless 运行」章节:启用方式、双模式差异表、已知限制;更新 TODO(#1 完成、#2 缩小为仅日志链路)。

## 双模式行为差异

| 项目 | rootful | rootless |
|------|---------|----------|
| docker.sock | `/var/run/docker.sock`(root 级,待日志链路替换后移除) | `$XDG_RUNTIME_DIR/docker.sock`(用户级) |
| node-exporter | 完整采集 | 部分 collector 降级 |
| cadvisor | Alloy 内嵌 + 宿主 cgroup 读取 | 同左;cgroup 读取受限程度需实测 |
| Prometheus | 非 root,无 socket | 同左 |
| 数据目录 | `make setup` 0777 | 同左 |

## 验证计划

- rootful(当前环境):
  - 重建全栈,回归指标、日志、Grafana 仪表盘;
  - 确认无 `privileged`、无 `pid: host`、Prometheus 非 root、静态目标全 up。
- rootless(有 rootless 主机时):
  - `make doctor` 通过 → `make up`;
  - 验证容器以用户 uid 运行、日志入 Loki、主机指标可查、内嵌 cadvisor 提供容器指标。
- 降级对照:记录 rootless 下 node-exporter/cadvisor 缺失的 collector 清单,写入 README。

## 已知限制与降级

- rootless 下 cgroup 读取受限,内嵌 cadvisor 的容器指标可能不全;不可用时降级为「仅主机指标 + 文档标注」。
- 启用 containerd image store 的 Docker(如 Docker 29 的 `io.containerd.snapshotter.v1`)不再维护传统 `layerdb/mounts` 路径,内嵌 cAdvisor 会持续输出 `read-write layer ID` 警告、无法归因镜像层,容器 CPU/内存/网络等 cgroup 指标不受影响;经典 graphdriver 环境无此问题。
- rootless 使用 fuse-overlayfs/slirp4netns,存储与网络性能低于 rootful,属运行时特性,不在本方案内处理。

## 假设与后续

- 假设:双模式兼容(非 rootless-only)。
- 假设:日志接收端替换(TODO#2 剩余部分)本次不做,维持 Alloy docker 采集。
- 后续:日志链路替换(候选:fluentd 驱动 + fluent-bit,或 syslog 驱动 + Alloy)决策后,一并消除 rootful 下残留的 socket 依赖。
