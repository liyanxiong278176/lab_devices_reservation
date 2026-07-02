import 'axios'
import type { InternalAxiosRequestConfig } from 'axios'

declare module 'axios' {
  // Augment config with a retry marker used by the 401 refresh interceptor.
  interface InternalAxiosRequestConfig {
    __retried?: boolean
  }
}

export {}
