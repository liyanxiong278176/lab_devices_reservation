import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}))
const fetchAllPages = vi.hoisted(() => vi.fn())

vi.mock('../request', () => ({ default: http }))
vi.mock('@/utils/fetch-all-pages', () => ({ fetchAllPages }))

import * as authApi from '../auth'
import * as labApi from '../lab'
import { categoryTree } from '../category'

describe('identity, lab and category API contracts', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    http.get.mockResolvedValue(undefined)
    http.post.mockResolvedValue(undefined)
    http.put.mockResolvedValue(undefined)
  })

  it('calls each authentication endpoint with the expected payload', async () => {
    await authApi.getCsrf()
    await authApi.listRegistrationColleges()
    await authApi.login({ username: 'student', password: 'secret' })
    await authApi.register({ username: 'new', password: 'secret', real_name: 'New User', college_id: 3 })
    await authApi.refresh()
    await authApi.getMe()
    await authApi.logout()

    expect(http.get.mock.calls).toEqual([
      ['/auth/csrf'],
      ['/auth/colleges'],
      ['/auth/me'],
    ])
    expect(http.post.mock.calls).toEqual([
      ['/auth/login', { username: 'student', password: 'secret' }],
      ['/auth/register', { username: 'new', password: 'secret', real_name: 'New User', college_id: 3 }],
      ['/auth/refresh', {}],
      ['/auth/logout', {}],
    ])
  })

  it('maps nullable lab fields and forwards page metadata', async () => {
    http.get.mockResolvedValue({
      records: [
        {
          id: 1, name: 'Physics', location: 'Building A', description: 'optics', status: 'ACTIVE',
          createdAt: 'created', updatedAt: 'updated', college_id: 7, college_name: 'Science',
          manager_id: 8, manager_name: 'Manager',
        },
        {
          id: 2, name: 'Chemistry', location: '', description: '', status: 'ACTIVE',
          createdAt: 'created-2', updatedAt: 'updated-2', college_id: null, college_name: null,
        },
      ],
      total: 2, size: 20, current: 1, pages: 1, truncated: false,
    })

    await expect(labApi.listLabs(1, 20)).resolves.toEqual({
      records: [
        {
          id: 1, name: 'Physics', location: 'Building A', description: 'optics', status: 'ACTIVE',
          createdAt: 'created', updatedAt: 'updated', collegeId: 7, collegeName: 'Science',
          managerId: 8, managerName: 'Manager',
        },
        {
          id: 2, name: 'Chemistry', location: '', description: '', status: 'ACTIVE',
          createdAt: 'created-2', updatedAt: 'updated-2', collegeId: null, collegeName: null,
          managerId: null, managerName: null,
        },
      ],
      total: 2, size: 20, current: 1, pages: 1, truncated: false,
    })
    expect(http.get).toHaveBeenCalledWith('/labs', { params: { page: 1, size: 20 } })
  })

  it('uses list defaults and passes list-all pagination through the shared pager', async () => {
    http.get.mockResolvedValue({ records: [], total: 0, size: 100, current: 1, truncated: false })
    await labApi.listLabs()
    expect(http.get).toHaveBeenCalledWith('/labs', { params: { page: 1, size: 100 } })

    fetchAllPages.mockImplementation(async (load: (page: number, size: number) => unknown, size: number) => {
      await load(1, size)
      return []
    })
    await expect(labApi.listAllLabs(25)).resolves.toEqual([])
    expect(fetchAllPages).toHaveBeenCalledWith(expect.any(Function), 25)
    expect(http.get).toHaveBeenLastCalledWith('/labs', { params: { page: 1, size: 25 } })
  })

  it('normalizes optional lab write fields to null and preserves supplied values', async () => {
    await labApi.createLab({ collegeId: 1, name: 'new lab', location: '', managerId: undefined, description: '' })
    await labApi.updateLab(9, {
      collegeId: 2, name: 'updated lab', location: 'North Wing', managerId: 4, description: 'research',
    })

    expect(http.post).toHaveBeenCalledWith('/labs', {
      college_id: 1, name: 'new lab', location: null, manager_id: null, description: null,
    })
    expect(http.put).toHaveBeenCalledWith('/labs/9', {
      college_id: 2, name: 'updated lab', location: 'North Wing', manager_id: 4, description: 'research',
    })
  })

  it('loads the device category tree from the canonical endpoint', async () => {
    http.get.mockResolvedValue([{ id: 1, name: 'Optics', children: [] }])
    await expect(categoryTree()).resolves.toEqual([{ id: 1, name: 'Optics', children: [] }])
    expect(http.get).toHaveBeenCalledWith('/device-categories')
  })
})
