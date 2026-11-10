# AGENTS.md

按当前任务需要阅读相关部分：

| 任务涉及 | 阅读入口 |
| --- | --- |
| 当前工作与任务状态 | [TODO.md](<TODO.md>) |
| 项目用法与安装 | [中文说明](<docs/README.cn.md>)、[英文说明](<README.md>) |
| 当前实现、接口与源码分工 | [技术文档索引](<docs/tech/index.md>) |
| 项目定位与需求 | [StarBridge.md](<StarBridge.md>) |
| 后续候选与未来安排 | [路线图](<docs/roadmap.md>) |

## 本地安装与市场同步

- [DSH 本地安装脚本](<scripts/dsh_local_install.py>)：将本地源码打包并安装到指定 DSH profile。
- [市场同步脚本](<scripts/sync_vibekits_release.py>)：根据 GitHub Release 更新 Vibekits 元数据并创建待审查 PR。

## README 维护

- 修改公开内容导致与 README 已有内容产生冲突时，仅同步修正 [README.md](<README.md>) 和 [README.cn.md](<docs/README.cn.md>) 中受影响的已有内容，使其与公共事实对齐；无冲突不顺带修改。未经用户明确授权，不新增内容；删除任何 README 现有内容前须征得用户同意。
- 本次改动产生值得补充或调整的 README 内容时，主动沿用现有章节、格式和语气提出具体修改草案，说明位置与理由，并询问是否同步更新 [README.md](<README.md>) 和 [README.cn.md](<docs/README.cn.md>)；确认前不写入，不仅等待用户提出要求。
