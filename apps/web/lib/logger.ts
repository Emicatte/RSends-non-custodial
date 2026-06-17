/**
 * Logger condizionale per RSend.
 * In development: logga tutto su console.
 * In production: logga solo errori, MAI dati sensibili.
 */

const isDev = process.env.NODE_ENV === 'development'

type LogLevel = 'debug' | 'info' | 'warn' | 'error'

interface LogEntry {
  level: LogLevel
  module: string
  message: string
  // MAI loggare: private keys, firme, nonce Oracle completi, importi esatti
  data?: Record<string, unknown>
}

function sanitize(data: Record<string, unknown>): Record<string, unknown> {
  const sanitized = { ...data }
  const SENSITIVE_KEYS = [
    'oracleSignature', 'signature', 'sig', 'privateKey', 'private_key',
    'secret', 'hmac', 'apiKey', 'api_key', 'password', 'seed',
  ]
  for (const key of Object.keys(sanitized)) {
    if (SENSITIVE_KEYS.some(s => key.toLowerCase().includes(s.toLowerCase()))) {
      sanitized[key] = '[REDACTED]'
    }
    // Tronca nonce e hash per sicurezza
    if (typeof sanitized[key] === 'string') {
      const val = sanitized[key] as string
      if (val.startsWith('0x') && val.length > 20) {
        sanitized[key] = `${val.slice(0, 10)}...${val.slice(-6)}`
      }
    }
  }
  return sanitized
}

function log(entry: LogEntry) {
  if (!isDev && entry.level === 'debug') return

  const safe = entry.data ? sanitize(entry.data) : undefined
  const prefix = `[RSend:${entry.module}]`

  switch (entry.level) {
    case 'debug': console.debug(prefix, entry.message, safe ?? ''); break
    case 'info':  console.info(prefix, entry.message, safe ?? '');  break
    case 'warn':  console.warn(prefix, entry.message, safe ?? '');  break
    case 'error': console.error(prefix, entry.message, safe ?? ''); break
  }

  // In produzione: qui puoi mandare a Sentry
  // if (!isDev && entry.level === 'error') {
  //   Sentry.captureMessage(entry.message, { extra: safe })
  // }
}

export const logger = {
  debug: (module: string, msg: string, data?: Record<string, unknown>) =>
    log({ level: 'debug', module, message: msg, data }),
  info: (module: string, msg: string, data?: Record<string, unknown>) =>
    log({ level: 'info', module, message: msg, data }),
  warn: (module: string, msg: string, data?: Record<string, unknown>) =>
    log({ level: 'warn', module, message: msg, data }),
  error: (module: string, msg: string, data?: Record<string, unknown>) =>
    log({ level: 'error', module, message: msg, data }),
}
