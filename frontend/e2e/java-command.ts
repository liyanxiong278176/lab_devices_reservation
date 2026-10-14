import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// Use the same Java executable and database environment as the API under test.
export function javaCommand(action: string, prefix: string, options: Record<string, string | number | boolean> = {}): string {
  const root = fileURLToPath(new URL('../../', import.meta.url))
  const java = process.env.JAVA_HOME ? resolve(process.env.JAVA_HOME, 'bin', process.platform === 'win32' ? 'java.exe' : 'java') : 'java'
  const args = ['-jar', resolve(root, 'backend-java/target/labflow-backend-1.0.0.jar'),
    '--spring.main.web-application-type=none', '--spring.main.banner-mode=off',
    '--logging.level.root=ERROR', `--labflow.fixture=${action}`, `--prefix=${prefix}`,
    ...Object.entries(options).map(([name, value]) => `--${name}=${value}`)]
  const output = execFileSync(java, args, { cwd: root, encoding: 'utf8', timeout: 60_000, stdio: ['ignore', 'pipe', 'pipe'] })
  const result = output.split(/\r?\n/).find(line => line.startsWith('LABFLOW_RESULT='))
  if (!result) throw new Error(`Java fixture ${action} returned no result`)
  return result.slice('LABFLOW_RESULT='.length)
}
