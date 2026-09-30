import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  defaults: { baseURL: '/api/v2/' as string | undefined },
}))
const paging = vi.hoisted(() => ({ fetchAllPages: vi.fn() }))

vi.mock('../request', () => ({ default: http }))
vi.mock('@/utils/fetch-all-pages', () => ({ fetchAllPages: paging.fetchAllPages }))

import * as deviceApi from '../device'
import * as maintenanceApi from '../maintenance'

describe('device and maintenance API contracts', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    http.get.mockResolvedValue(undefined)
    http.post.mockResolvedValue(undefined)
    http.put.mockResolvedValue(undefined)
    http.patch.mockResolvedValue(undefined)
    http.delete.mockResolvedValue(undefined)
  })

  it('maps device search results and supports trimmed all-page searches', async () => {
    const full = {
      id: 1, name: 'scope', status: 'IDLE', need_approval: true, max_reservation_days: 3,
      brand: 'b', model: 'm', specs: 'spec', image_url: '/scope.png', category_id: 2,
      category_name: 'scope', lab_id: 3, lab_name: 'lab', college_id: 4, college_name: 'college',
      tags: ['laser'], accessory_checklist: ['power'], description: 'description', asset_code: 'asset',
      serial_number: 'serial', purchase_date: '2025-01-01', warranty_until: '2027-01-01',
      allow_external_loan: true, risk_level: 'HIGH', requires_safety_ack: true,
      requires_qualification: true, max_advance_days: 12, maintenance_warning: 'soon',
    }
    const minimal = {
      id: 2, name: 'blank', status: 'IDLE', need_approval: false, max_reservation_days: 8,
      category_id: null, category_name: '', lab_id: null, lab_name: '', college_id: null,
      college_name: '', tags: null, accessory_checklist: null, description: '', asset_code: '',
      serial_number: '', purchase_date: null, warranty_until: null, allow_external_loan: false,
      risk_level: '', requires_safety_ack: false, requires_qualification: false,
      max_advance_days: null, maintenance_warning: '',
    }
    http.get.mockResolvedValueOnce({
      items: [full, minimal], total: 2, page: 2, page_size: 10, pages: 1, truncated: true,
    })
    await expect(deviceApi.searchDevices({ page: 2, size: 10, keyword: 'scope', labId: 3, status: '' }))
      .resolves.toMatchObject({
        records: [
          expect.objectContaining({
            id: 1, categoryId: 2, labId: 3, collegeId: 4, needApproval: 1,
            maxReservationHours: 72, tags: ['laser'], accessoryChecklist: ['power'],
            allowExternalLoan: true, riskLevel: 'HIGH', maxAdvanceDays: 12,
          }),
          expect.objectContaining({
            id: 2, categoryId: null, categoryName: undefined, needApproval: 0,
            accessoryChecklist: [], allowExternalLoan: false, riskLevel: 'STANDARD', maxAdvanceDays: undefined,
          }),
        ],
        total: 2, size: 10, current: 2, pages: 1, truncated: true,
      })
    expect(http.get).toHaveBeenCalledWith('/devices', {
      params: { page: 2, page_size: 10, search: 'scope', lab_id: 3, status: undefined },
    })

    http.get.mockResolvedValueOnce({
      items: [], total: 0, page: 1, page_size: 10, pages: 0, truncated: false,
    })
    await deviceApi.searchDevices({ search: 'fallback-search', status: 'IDLE' })
    expect(http.get).toHaveBeenNthCalledWith(2, '/devices', {
      params: { page: undefined, page_size: undefined, search: 'fallback-search', lab_id: undefined, status: 'IDLE' },
    })

    paging.fetchAllPages.mockImplementationOnce(async (fetchPage, pageSize) => {
      expect(pageSize).toBe(7)
      const page = await fetchPage(1, pageSize)
      return page.records
    })
    http.get.mockResolvedValueOnce({
      items: [], total: 0, page: 1, page_size: 7, pages: 0, truncated: false,
    })
    await expect(deviceApi.searchAllDevices('  laser  ', 7)).resolves.toEqual([])
    expect(paging.fetchAllPages).toHaveBeenCalledOnce()
    expect(paging.fetchAllPages.mock.calls[0][1]).toBe(7)
    const fetchPage = paging.fetchAllPages.mock.calls[0][0]
    http.get.mockResolvedValueOnce({
      items: [minimal], total: 1, page: 1, page_size: 7, pages: 1, truncated: false,
    })
    await expect(fetchPage(1, 7)).resolves.toMatchObject({ records: [expect.objectContaining({ id: 2 })] })

    paging.fetchAllPages.mockClear()
    await expect(deviceApi.searchAllDevices('   ')).resolves.toEqual([])
    expect(paging.fetchAllPages).not.toHaveBeenCalled()
  })

  it('maps device detail and availability, and filters available calendar days', async () => {
    const device = {
      id: 4, name: 'scope', status: 'IDLE', need_approval: false, max_reservation_days: 2,
    }
    http.get.mockResolvedValueOnce(device).mockResolvedValueOnce([
      { date: '2026-09-30', available: true },
      { date: '2026-10-01', available: false, reservation_id: 11, status: '', reason: '' },
      { date: '2026-10-02', available: false, reservation_id: null, status: 'MAINTENANCE', reason: 'repair' },
    ]).mockResolvedValueOnce([
      { date: '2026-09-29', available: true },
      { date: '2026-09-30', available: false, reservation_id: 11, status: null, reason: null },
      { date: '2026-10-01', available: false, reservation_id: null, status: 'MAINTENANCE', reason: 'repair' },
    ]).mockResolvedValueOnce([])

    await expect(deviceApi.getDevice(4)).resolves.toMatchObject({
      id: 4, name: 'scope', maxReservationHours: 48,
    })
    await expect(deviceApi.deviceAvailability(4, '2026-09-30')).resolves.toEqual([
      { date: '2026-09-30', available: true, reservationId: null, status: null, reason: null },
      { date: '2026-10-01', available: false, reservationId: 11, status: '', reason: '' },
      { date: '2026-10-02', available: false, reservationId: null, status: 'MAINTENANCE', reason: 'repair' },
    ])
    await expect(deviceApi.deviceCalendar(4, '2026-10-01', '2026-10-03')).resolves.toEqual([
      { date: '2026-09-30', reservationId: 11, status: 'BLOCKED', reason: undefined },
      { date: '2026-10-01', reservationId: null, status: 'MAINTENANCE', reason: 'repair' },
    ])
    await expect(deviceApi.deviceCalendar(4, '2026-10-04')).resolves.toEqual([])
    expect(http.get).toHaveBeenNthCalledWith(2, '/devices/4/availability', {
      params: { start_date: '2026-09-30', end_date: '2026-09-30' },
    })
    expect(http.get).toHaveBeenNthCalledWith(3, '/devices/4/availability', {
      params: { start_date: '2026-10-01', end_date: '2026-10-03' },
    })
  })

  it('serializes create/update device payload defaults and status actions', async () => {
    const populated = {
      name: 'scope', labId: 1, categoryId: 2, brand: 'b', model: 'm', specs: 's',
      imageUrl: '/a.png', description: 'd', needApproval: true, maxReservationDays: 4,
      tags: ['laser'], accessoryChecklist: ['power'], assetCode: 'A1', serialNumber: 'S1',
      purchaseDate: '2024-01-01', warrantyUntil: '2027-01-01', allowExternalLoan: true,
      riskLevel: 'HIGH', requiresSafetyAck: true, requiresQualification: true, maxAdvanceDays: 30,
    }
    await deviceApi.createDevice(populated)
    await deviceApi.createDevice({ name: 'minimal', maxReservationDays: 0, riskLevel: '' })
    await deviceApi.updateDevice(9, {
      name: 'blank', needApproval: 0, maxReservationDays: 0, allowExternalLoan: false,
      riskLevel: '', requiresSafetyAck: false, requiresQualification: false,
    })
    await deviceApi.deleteDevice(9)
    await deviceApi.patchDeviceStatus(9, 'MAINTENANCE')
    expect(http.post).toHaveBeenCalledWith('/devices', {
      name: 'scope', lab_id: 1, category_id: 2, brand: 'b', model: 'm', specs: 's',
      image_url: '/a.png', description: 'd', need_approval: true, max_reservation_days: 4,
      tags: ['laser'], accessory_checklist: ['power'], asset_code: 'A1', serial_number: 'S1',
      purchase_date: '2024-01-01', warranty_until: '2027-01-01', allow_external_loan: true,
      risk_level: 'HIGH', requires_safety_ack: true, requires_qualification: true, max_advance_days: 30,
    })
    expect(http.post).toHaveBeenNthCalledWith(2, '/devices', {
      name: 'minimal', lab_id: undefined, category_id: undefined, brand: undefined, model: undefined,
      specs: undefined, image_url: undefined, description: undefined, need_approval: false,
      max_reservation_days: 8, tags: undefined, accessory_checklist: undefined, asset_code: undefined,
      serial_number: undefined, purchase_date: undefined, warranty_until: undefined,
      allow_external_loan: false, risk_level: 'STANDARD', requires_safety_ack: false,
      requires_qualification: false, max_advance_days: undefined,
    })
    expect(http.put).toHaveBeenCalledWith('/devices/9', {
      name: 'blank', lab_id: undefined, category_id: undefined, brand: undefined, model: undefined,
      specs: undefined, image_url: undefined, description: undefined, need_approval: false,
      max_reservation_days: 8, tags: undefined, accessory_checklist: undefined, asset_code: undefined,
      serial_number: undefined, purchase_date: undefined, warranty_until: undefined,
      allow_external_loan: false, risk_level: 'STANDARD', requires_safety_ack: false,
      requires_qualification: false, max_advance_days: undefined,
    })
    expect(http.delete).toHaveBeenCalledWith('/devices/9')
    expect(http.patch).toHaveBeenCalledWith('/devices/9/status', { status: 'MAINTENANCE' })
  })

  it('maps device documents, uploads and downloads evidence', async () => {
    const row = {
      id: 1, device_id: 2, document_type: 'SAFETY', title: 'guide', version: '', requires_ack: true,
      original_name: 'guide.pdf', content_type: 'application/pdf', size_bytes: 20, url: '/docs/1',
      created_by: 3, created_at: 'created', published_at: null,
    }
    http.get.mockResolvedValueOnce([row]).mockResolvedValueOnce(new Blob(['guide']))
    await expect(deviceApi.listDeviceDocuments(2)).resolves.toEqual([{
      id: 1, deviceId: 2, documentType: 'SAFETY', title: 'guide', version: '1.0', requiresAck: true,
      originalName: 'guide.pdf', contentType: 'application/pdf', sizeBytes: 20, url: '/docs/1',
      createdBy: 3, createdAt: 'created', publishedAt: undefined,
    }])
    const file = new File(['guide'], 'guide.pdf', { type: 'application/pdf' })
    http.post.mockResolvedValueOnce({ ...row, version: '2.0', requires_ack: false, published_at: 'published' })
    await expect(deviceApi.uploadDeviceDocument(2, {
      documentType: 'MANUAL', title: 'guide', file,
    })).resolves.toMatchObject({ version: '2.0', publishedAt: 'published', requiresAck: false })
    const form = http.post.mock.calls[0][1] as FormData
    expect(form.get('document_type')).toBe('MANUAL')
    expect(form.get('title')).toBe('guide')
    expect(form.get('version')).toBe('1.0')
    expect(form.get('requires_ack')).toBe('false')
    expect(form.get('file')).toBe(file)
    await deviceApi.archiveDeviceDocument(2, 1)

    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const urlDescriptor = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    const revokeDescriptor = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    const createObjectURL = vi.fn(() => 'blob:document')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    try {
      await deviceApi.downloadDeviceDocument({
        id: 1, deviceId: 2, documentType: 'MANUAL', title: 'guide', version: '1.0', requiresAck: false,
        originalName: 'guide.pdf', contentType: 'application/pdf', sizeBytes: 20, url: '/docs/1', createdBy: 3,
      })
      expect(http.get).toHaveBeenNthCalledWith(2, '/docs/1', { responseType: 'blob' })
      expect(click).toHaveBeenCalledOnce()
      expect(createObjectURL).toHaveBeenCalledOnce()
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:document')
    } finally {
      if (urlDescriptor) Object.defineProperty(URL, 'createObjectURL', urlDescriptor)
      else Reflect.deleteProperty(URL, 'createObjectURL')
      if (revokeDescriptor) Object.defineProperty(URL, 'revokeObjectURL', revokeDescriptor)
      else Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })

  it('covers safety acknowledgements and qualification lifecycle mappings', async () => {
    http.get.mockResolvedValueOnce([{
      id: 1, device_id: 2, document_type: 'SOP', title: 'SOP', version: '1', requires_ack: false,
      original_name: 'sop.pdf', content_type: 'application/pdf', size_bytes: 5, url: '/sop', created_by: 3,
    }]).mockResolvedValueOnce({
      safety_required: true, safety_acknowledged: false, qualification_required: true,
      qualification_approved: false, safety_document_version: null,
    }).mockResolvedValueOnce(null).mockResolvedValueOnce({
      id: 4, device_id: 2, user_id: 5, status: 'APPROVED', qualification_type: 'TRAINING',
      asset_id: null, valid_until: null, reviewed_by: null, reviewed_at: null, note: null,
    }).mockResolvedValueOnce([])
    await expect(deviceApi.listSafetyDocuments(2)).resolves.toMatchObject([{ documentType: 'SOP' }])
    await expect(deviceApi.getDeviceAccess(2)).resolves.toEqual({
      safetyRequired: true, safetyAcknowledged: false, qualificationRequired: true,
      qualificationApproved: false, safetyDocumentVersion: undefined,
    })
    await deviceApi.acknowledgeSafety(2, 8)
    await deviceApi.acknowledgeSafety(2)
    const material = new File(['proof'], 'proof.pdf', { type: 'application/pdf' })
    http.post.mockResolvedValueOnce({ asset_id: 9, url: '/proof', name: 'proof.pdf' })
    await deviceApi.uploadQualificationMaterial(2, material)
    const form = http.post.mock.calls.at(-1)?.[1] as FormData
    expect(form.get('file')).toBe(material)

    http.post.mockResolvedValueOnce({
      id: 5, device_id: 2, user_id: 5, status: 'PENDING', qualification_type: 'TRAINING', asset_id: 0,
    })
    await expect(deviceApi.submitQualification(2, { qualificationType: '', assetId: null }))
      .resolves.toMatchObject({ id: 5, qualificationType: 'TRAINING', assetId: 0, validUntil: null })
    await expect(deviceApi.myQualification(2)).resolves.toBeNull()
    await expect(deviceApi.myQualification(2)).resolves.toMatchObject({ id: 4, assetId: null, note: null })
    await expect(deviceApi.listQualifications(2)).resolves.toEqual([])
    http.patch.mockResolvedValueOnce({
      id: 6, device_id: 2, user_id: 7, status: 'REJECTED', qualification_type: 'CERT',
      asset_id: 2, valid_until: '2027-01-01', reviewed_by: 3, reviewed_at: 'now', note: 'expired',
    })
    await expect(deviceApi.reviewQualification(2, 6, {
      status: 'REJECTED', validUntil: '2027-01-01', note: 'expired',
    })).resolves.toMatchObject({ id: 6, assetId: 2, reviewedBy: 3, note: 'expired' })
    expect(http.post).toHaveBeenNthCalledWith(1, '/devices/2/safety-ack', { reservation_id: 8 })
    expect(http.post).toHaveBeenNthCalledWith(2, '/devices/2/safety-ack', {})
    expect(http.post).toHaveBeenNthCalledWith(4, '/devices/2/qualifications', {
      qualification_type: 'TRAINING', asset_id: undefined, note: undefined,
    })
    expect(http.patch).toHaveBeenCalledWith('/devices/2/qualifications/6', {
      status: 'REJECTED', valid_until: '2027-01-01', note: 'expired',
    })
  })

  it('maps maintenance devices, plans and cycle records and serializes uploads', async () => {
    http.get.mockResolvedValueOnce({
      items: [
        {
          id: 1, name: 'scope', status: 'IDLE', brand: 'b', model: 'm', specs: 's', image_url: '/x',
          category_id: 2, category_name: 'category', lab_id: 3, lab_name: 'lab', college_id: 4,
          college_name: 'college', need_approval: true, max_reservation_days: 2, asset_code: 'A',
          maintenance_warning: 'soon',
        },
        { id: 2, name: 'blank', status: 'IDLE', need_approval: false, max_reservation_days: 1,
          category_id: null, lab_id: null, college_id: null },
      ], total: 2, page: 1, page_size: 20, pages: 1, truncated: false,
    }).mockResolvedValueOnce({
      items: [], total: 0, page: 1, page_size: 100, pages: 0, truncated: false,
    }).mockResolvedValueOnce({
      items: [{
        id: 4, device_id: 1, device_name: 'scope', device_asset_code: 'A', college_id: 2,
        plan_type: 'ROUTINE', title: 'inspection', interval_value: 1, interval_unit: 'MONTH',
        due_date: '2026-10-01', downtime_start: null, downtime_end: null, active: true,
        temporarily_unbookable: false, unbookable_reason: null, created_at: 'created', updated_at: 'updated',
      }], total: 1, page: 1, page_size: 50, pages: 1, truncated: false,
    }).mockResolvedValueOnce({
      items: [{
        id: 5, plan_id: 4, device_id: 1, college_id: 2, cycle_due_date: '2026-10-01',
        completed_date: '2026-10-01', downtime_start: null, downtime_end: null, result: 'PASSED',
        notes: null, performed_by: 7, performed_by_name: 'Manager', evidence_asset_token: null,
        evidence_name: null, evidence_content_type: null, evidence_size_bytes: null, evidence_url: null,
        repair_report_id: null, created_at: 'now',
      }], total: 1, page: 2, page_size: 20, pages: 1, truncated: false,
    })
    await expect(maintenanceApi.listMaintenanceDevices({ search: '  scope  ' })).resolves.toMatchObject({
      records: [
        expect.objectContaining({ id: 1, categoryId: 2, needApproval: 1, assetCode: 'A' }),
        expect.objectContaining({ id: 2, categoryId: null, labId: null, collegeId: null, needApproval: 0 }),
      ], total: 2, size: 20, current: 1,
    })
    expect(http.get).toHaveBeenNthCalledWith(1, '/maintenance-devices', {
      params: { page: 1, page_size: 100, search: 'scope', device_id: undefined, active: undefined },
    })
    await maintenanceApi.listMaintenanceDevices({ search: '   ' })
    expect(http.get).toHaveBeenNthCalledWith(2, '/maintenance-devices', {
      params: { page: 1, page_size: 100, search: undefined, device_id: undefined, active: undefined },
    })

    await expect(maintenanceApi.listMaintenancePlans({ page: 0, pageSize: 0, deviceId: 1, active: false }))
      .resolves.toMatchObject({ items: [expect.objectContaining({ id: 4, deviceId: 1 })] })
    expect(http.get).toHaveBeenNthCalledWith(3, '/maintenance-plans', {
      params: { page: 1, page_size: 50, device_id: 1, active: false },
    })
    await expect(maintenanceApi.listMaintenanceRecords(4, 2)).resolves.toMatchObject({
      items: [expect.objectContaining({ id: 5, planId: 4, performedByName: 'Manager', evidenceUrl: null })],
    })
  })

  it('serializes plan cycles and downloads maintenance evidence from base-relative or absolute URLs', async () => {
    const plan = {
      planType: 'CALIBRATION' as const, title: 'calibrate', intervalValue: 6,
      intervalUnit: 'MONTH' as const, dueDate: '2026-11-01', downtimeStart: '', downtimeEnd: '', active: true,
    }
    const mapped = {
      id: 10, device_id: 2, device_name: 'scope', college_id: 1, plan_type: 'CALIBRATION',
      title: 'calibrate', interval_value: 6, interval_unit: 'MONTH', due_date: '2026-11-01',
      downtime_start: null, downtime_end: null, active: true, temporarily_unbookable: false,
      unbookable_reason: null,
    }
    http.post.mockResolvedValueOnce(mapped).mockResolvedValueOnce({
      id: 11, plan_id: 10, device_id: 2, college_id: 1, cycle_due_date: '2026-11-01',
      completed_date: '2026-11-01', result: 'PASSED', performed_by: 7,
    }).mockResolvedValueOnce({ asset_token: 'asset', name: 'proof', content_type: 'image/png', size_bytes: 10, url: '/asset' })
    http.put.mockResolvedValueOnce(mapped)
    await expect(maintenanceApi.createMaintenancePlan(2, plan)).resolves.toMatchObject({ id: 10, planType: 'CALIBRATION' })
    await maintenanceApi.updateMaintenancePlan(10, { ...plan, downtimeStart: '08:00', downtimeEnd: '09:00' })
    expect(http.post).toHaveBeenNthCalledWith(1, '/devices/2/maintenance-plans', {
      plan_type: 'CALIBRATION', title: 'calibrate', interval_value: 6, interval_unit: 'MONTH',
      due_date: '2026-11-01', downtime_start: null, downtime_end: null, active: true,
    })
    expect(http.put).toHaveBeenCalledWith('/maintenance-plans/10', {
      plan_type: 'CALIBRATION', title: 'calibrate', interval_value: 6, interval_unit: 'MONTH',
      due_date: '2026-11-01', downtime_start: '08:00', downtime_end: '09:00', active: true,
    })

    const file = new File(['proof'], 'proof.png', { type: 'image/png' })
    await maintenanceApi.uploadMaintenanceEvidence(2, file)
    expect((http.post.mock.calls[1][1] as FormData).get('file')).toBe(file)
    await maintenanceApi.completeMaintenanceCycle(10, {
      cycleDueDate: '2026-11-01', completedDate: '2026-11-01', result: 'PASSED', notes: '',
    }, 'key-1')
    expect(http.post).toHaveBeenNthCalledWith(3, '/maintenance-plans/10/records', {
      cycle_due_date: '2026-11-01', completed_date: '2026-11-01', result: 'PASSED',
      notes: null, evidence_asset_token: null,
    }, { headers: { 'Idempotency-Key': 'key-1' } })
    http.post.mockResolvedValueOnce({
      id: 12, plan_id: 10, device_id: 2, college_id: 1, cycle_due_date: '2026-12-01',
      completed_date: '2026-12-02', result: 'FAILED', performed_by: 7,
    })
    await maintenanceApi.completeMaintenanceCycle(10, {
      cycleDueDate: '2026-12-01', completedDate: '2026-12-02', result: 'FAILED',
      notes: 'retest', evidenceAssetToken: 'asset-1',
    }, 'key-2')
    expect(http.post).toHaveBeenNthCalledWith(4, '/maintenance-plans/10/records', {
      cycle_due_date: '2026-12-01', completed_date: '2026-12-02', result: 'FAILED',
      notes: 'retest', evidence_asset_token: 'asset-1',
    }, { headers: { 'Idempotency-Key': 'key-2' } })

    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const urlDescriptor = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    const revokeDescriptor = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    const createObjectURL = vi.fn(() => 'blob:evidence')
    const revokeObjectURL = vi.fn()
    const configuredBaseURL = http.defaults.baseURL
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    http.get.mockResolvedValue(new Blob(['evidence']))
    try {
      await maintenanceApi.downloadMaintenanceEvidence('/api/v2/files/1', 'proof.pdf')
      await maintenanceApi.downloadMaintenanceEvidence('https://cdn.test/files/1', 'external.pdf')
      expect(http.get).toHaveBeenNthCalledWith(1, '/files/1', { responseType: 'blob' })
      expect(http.get).toHaveBeenNthCalledWith(2, 'https://cdn.test/files/1', { responseType: 'blob' })
      http.defaults.baseURL = undefined
      await maintenanceApi.downloadMaintenanceEvidence('/files/raw/1', 'raw.pdf')
      expect(http.get).toHaveBeenNthCalledWith(3, '/files/raw/1', { responseType: 'blob' })
      expect(click).toHaveBeenCalledTimes(3)
      expect(createObjectURL).toHaveBeenCalledTimes(3)
      expect(revokeObjectURL).toHaveBeenCalledTimes(3)
    } finally {
      http.defaults.baseURL = configuredBaseURL
      if (urlDescriptor) Object.defineProperty(URL, 'createObjectURL', urlDescriptor)
      else Reflect.deleteProperty(URL, 'createObjectURL')
      if (revokeDescriptor) Object.defineProperty(URL, 'revokeObjectURL', revokeDescriptor)
      else Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })
})
