/** 为 DSH 注册插件自带的 MCP 入口和 Skill，沿用宿主已有的工具与技能服务。 */
import { fileURLToPath } from 'node:url';
import * as mcp from '@deepseek-ai/dsh-mcp-client';
import * as filesystem from '@deepseek-ai/dsh-skill-filesystem';

export const name = 'starbridge';
export const inject = ['tools', 'skills'];

/** config 可设置 python、env 和 toolCallTimeoutMs；许可证变量由用户配置传入。 */
export async function apply(ctx, config = {}) {
  const root = new URL('../../', import.meta.url);
  // 1. MCP 使用共享启动器；初始化只启动协议服务，不打开 STAR 算例。
  await ctx.plugin(mcp, mcp.Config({
    serverName: 'starbridge', transport: 'stdio',
    command: config.python ?? 'python3',
    args: [fileURLToPath(new URL('integrations/plugin/launch.py', root))],
    env: config.env ?? {},
    toolCallTimeoutMs: config.toolCallTimeoutMs ?? 600000,
    failOnStartupError: true,
  }));
  // 2. 独立 provider 只扫描包内 Skill，不重复扫描或替换用户已有的技能目录。
  await ctx.plugin(filesystem, {
    providerName: 'starbridge', includeDefaultRoots: false,
    bundledSkillDir: fileURLToPath(new URL('skills/', root)), watch: false,
  });
}
