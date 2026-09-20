import type { AxiosInstance } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import router from '@/router'
import { useUserStore } from '@/stores/user'
import service from '../request'

vi.mock('@/router', () => ({ default: { push: vi.fn() } }))
vi.mock('@/stores/user', () => ({ useUserStore: vi.fn() }))

describe('request authentication recovery', () => {
  const mockedUseUserStore = vi.mocked(useUserStore)
  const mockedRouter = vi.mocked(router)
  let userStore: {
    accessToken: string
    refreshToken: string
    refresh: ReturnType<typeof vi.fn>
    logout: ReturnType<typeof vi.fn>
  }

  beforeEach(() => {
    vi.clearAllMocks()
    userStore = {
      accessToken: 'expired-access-token',
      refreshToken: 'expired-refresh-token',
      refresh: vi.fn(),
      logout: vi.fn(),
    }
    mockedUseUserStore.mockReturnValue(userStore as never)
    ;(service as AxiosInstance).defaults.adapter = async (config) => {
      return Promise.reject({
        config,
        response: { status: 401, data: { message: 'Unauthorized' } },
      })
    }
  })

  it('does not hang when the refresh token is also rejected', async () => {
    userStore.refresh.mockImplementation(async () => {
      await service.post('/auth/refresh', { refresh_token: userStore.refreshToken })
    })

    const outcome = await Promise.race([
      service.get('/auth/me').then(
        () => 'resolved',
        () => 'rejected',
      ),
      new Promise<'timed-out'>((resolve) => {
        setTimeout(() => resolve('timed-out'), 300)
      }),
    ])

    expect(outcome).toBe('rejected')
    expect(userStore.logout).toHaveBeenCalledOnce()
    expect(mockedRouter.push).toHaveBeenCalledWith('/login')
  })
})
