# 后台常驻会话

[返回项目入口](README.cn.md) · [文件 Bridge](bridge-file.md) · [设计文档](../StarBridge.md)

会话 Runner 让 STAR 后台加载一次工作副本，后续读取、修改和另存都连接这个服务。每次请求仍启动一个临时 Java 批处理客户端，客户端退出后服务继续保留算例及未保存修改。常驻 Java 适配器留待后续研究。

当前仅支持本机 Linux、Python 3.11 或更新版本；默认绑定 STAR 2602 Build 21.02.007，2510 的选择与验证范围见[版本说明](catalog-versions.md)。需要可用的安装、许可证和兼容算例。默认调用 `PATH` 中的 `starccm+`，启动时可用 `--star` 指定路径。

## 启动并操作

在仓库根目录执行，输入文件、会话目录及输出路径按实际情况替换：

```bash
python3 bridge/runner/session_bridge.py start 'Base.sim~' \
  --session-dir outputs/my-session --port 49001

python3 bridge/runner/session_bridge.py status \
  --session-dir outputs/my-session

python3 bridge/runner/session_bridge.py inspect \
  --session-dir outputs/my-session

python3 bridge/runner/session_bridge.py set-scalar \
  --session-dir outputs/my-session \
  --name _AirfoilPitchAmplitude --value 6 --unit deg

python3 bridge/runner/session_bridge.py inspect \
  --session-dir outputs/my-session

python3 bridge/runner/session_bridge.py save \
  --session-dir outputs/my-session --output outputs/Base_session_example.sim
```

`start` 要求会话目录尚不存在。它把输入复制为目录内的 `working.sim`，以单进程计算配置启动独立 STAR 服务，并用一次读取确认服务可用。原输入不作为保存目标；每次请求完成后都会核对原输入的 SHA256。若用户在外部修改原输入，检查也会失败，此后需查看日志并处理会话。

`status` 只读取本地记录并核对进程身份，不启动 Java 客户端；其中 `modified` 是上次成功请求的值。`inspect` 通过随附快照布局和共享目录读取服务的当前状态，并精确核对当前 server 版本。快照字段、读取错误及覆盖范围见 [Inspector 对象快照](inspector.md)。

表达式和标签修改使用 `modify --request`，预期旧状态检查、回读与拒绝处理见 [Modifier 单项修改](modifier.md)。它也只修改内存。兼容 `modify` 和 `set-scalar` 自动加载该会话绑定版本的随附目录，使用统一准备、写入及回读流程，无需生成目录或修改旧命令；当前 server 必须精确匹配 2602 Build 21.02.007。显式指定目录的 schema 2 用法见[目录修改](catalog-modifier.md)。

`set-scalar` **只修改内存，不保存文件**。它将已有标量设置为数值常量，替换原表达式，检查单位量纲并回读目标数值与单位。它没有调用者提供的 `expected`，内部按当前值准备修改不会保护陈旧请求。临时客户端退出后，另一次 `inspect` 仍能读到该修改。

`save` 显式另存当前会话；目标必须是不存在的 `.sim` 文件，父目录必须存在。保存后，会话记录随 STAR 的当前文件路径更新。该命令在保存前检查快照目录版本，确认保存调用、文件存在及会话路径，不自动重新加载。需要独立核对磁盘值时，可使用文件入口：

```bash
python3 bridge/runner/file_bridge.py inspect outputs/Base_session_example.sim \
  --work-dir outputs/check-session-save
```

## 关闭会话

```bash
python3 bridge/runner/session_bridge.py stop --session-dir outputs/my-session
```

普通 `stop` 先通过目录快照查询 STAR 的 `isModified()`；只要 STAR 报告存在未保存修改，就拒绝关闭。**本机实测中，另存完成后这个标志仍为真，原因尚未确定。** 程序保留该保护，不擅自把它清零。核对另存文件后，或明确不需要剩余内存状态时，使用：

```bash
python3 bridge/runner/session_bridge.py stop \
  --session-dir outputs/my-session --discard
```

`--discard` 放弃服务中尚未落盘的状态；不会删除输入、已保存的输出或请求记录。服务会收到终止信号，程序按记录核对并清理其 MPI 子进程；必要时对身份仍匹配的遗留进程强制结束。它不等同于 STAR GUI 的交互式退出。

## 身份、隔离与失败处理

启动使用固定端口和 `-portrange 1`，端口被占用时失败。每次请求连接 `localhost` 和记录的端口，并核对当前算例文件路径。启动器与实际服务的 PID、Linux 启动时刻和系统启动标识共同确定身份，避免 PID 复用后连接或停止别的服务。

同一会话的 Bridge 请求通过文件锁串行执行。每次请求使用 `-batch` 和 `-noexit`：宏执行完后客户端退出，后台服务保留。客户端使用会话专属 `-nbuserdir`，子进程使用 `en_US.UTF-8`，不改动用户全局客户端配置或区域设置。

除 `status` 外，命令的 `--timeout` 默认是 180 秒；启动的等待和首次读取共用这一时间预算。请求超时或执行失败时，操作可能已经生效，记录会进入 `uncertain`，或保留 `active_request` 标记；后续操作会被阻止，只有 `status` 和 `stop --discard` 可继续。不要自动重试修改；先查看请求日志、结果及可能已生成的文件。当前没有会话恢复或重新接管接口。`inspect`、`save`、`modify` 和 `set-scalar` 的明确版本拒绝，以及修改的写入前拒绝，返回 `rejected` 并保持已有会话 `ready`，不属于未知写入结果。`start` 的首次目录检查被拒绝会清理刚启动的服务；普通 `stop` 的关闭前检查被拒绝会保留服务。`status` 与 `stop --discard` 不加载目录，仍可在目录失效时查询和清理本次拥有的服务。

此实现只管理自己启动的后台服务，不连接用户已有 GUI 会话。独立进程、文件与客户端目录用于区分运行状态，但仍共享机器资源和许可证。`-loc` 仅控制 STAR 的服务发现范围，不能当作网络防火墙；此原型不提供远程访问或额外的端口安全配置。

## 运行产物与实现

所有命令成功时输出 JSON。读取、设置和保存结果包含当前快照及对应 `result.json` 的路径。兼容 `modify` 和 `set-scalar` 还返回 `catalog_before`、`catalog` 与 `catalog_diff`；原有快照、修改请求和 `snapshot_diff` 字段按各命令原契约保留。目录结果含目标类型全部已配属性，字段和引用比较规则见[目录结果与差异](catalog-modifier.md#结果与差异)。

| 路径 | 内容 |
|---|---|
| `session.json` | 服务身份、输入摘要、当前文件、最近请求及生命周期状态 |
| `working.sim` | 输入的初始工作副本；内存修改不会自动写入此文件 |
| `server-command.json` / `server.log` | 服务启动参数与日志 |
| `requests/<请求 ID>/` | 每次客户端的命令、宏、日志、修改前后快照及目录结果；兼容写入口另存 `legacy-plan.json`，快照操作另存 `snapshot-plan.json` |
| `client-settings/` | 当前会话的临时客户端配置与缓存 |
| `session.lock` | Bridge 请求互斥锁 |

[session_bridge.py](../bridge/runner/session_bridge.py) 管理生命周期；[file_bridge.py](../bridge/runner/file_bridge.py) 生成宏并运行客户端；两者共用 [BridgeFileMacro.java](../bridge/java/BridgeFileMacro.java)。这些是原型脚本，尚未封装为正式 `starbridge` CLI 或 MCP 服务。

## 已确认的范围

本机 `Base.sim~` 读取到 32 个标量参数。跨独立客户端把 `_AirfoilPitchAmplitude` 从 `5 deg` 设置为 `6 deg` 并再次读取，期间服务 PID 不变、算例只加载一次，原输入及工作副本摘要未变化。另存文件重新加载后参数快照一致，服务关闭后记录的进程退出、端口释放。

以上只确认参数读写、保存和生命周期；没有执行网格或求解，没有验证向量分支、GUI 共享会话、异常恢复、其他主机或 STAR 版本。

扩展对象快照的文件与会话对照结果及未实测分支见 [Inspector 验证范围](inspector.md#验证范围)。

迁入共享目录后的兼容写入口、写入前拒绝与会话另存重载结果见 [Modifier 验证范围](modifier.md#已确认的范围)。
