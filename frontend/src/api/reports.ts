import request from './request'

export type ReportExportType = 'devices' | 'reservations' | 'repairs'

export interface ReportFilters {
  startDate?: string
  endDate?: string
  status?: string
  collegeId?: number
}

export interface ReportSummaryVO {
  range: { startDate: string; endDate: string }
  deviceCount: number
  reservationCount: number
  reservationStatus: Record<string, number>
  repairCount: number
  repairStatus: Record<string, number>
  utilizationRate: number
  occupancyRate: number
  actualUsageRate: number
  bookableDeviceDays: number
  occupiedDeviceDays: number
  actualUsageDeviceDays: number
  maintenanceDowntimeDays: number
  averageApprovalHours: number
  waitlistRequests: number
  waitlistConverted: number
  waitlistConversionRate: number
  noShowRate: number
  violationRate: number
}

export interface ExportTaskVO {
  id: number
  export_type: ReportExportType
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | string
  row_count: number
  download_url?: string | null
  error?: string | null
  created_at?: string
  completed_at?: string | null
}

function params(filters: ReportFilters) {
  return {
    start_date: filters.startDate || undefined,
    end_date: filters.endDate || undefined,
    status: filters.status || undefined,
    college_id: filters.collegeId || undefined,
  }
}

export const getReportSummary = (filters: ReportFilters = {}) =>
  request.get<unknown, ReportSummaryVO>('/reports/summary', { params: params(filters) })

export async function downloadReport(type: ReportExportType, filters: ReportFilters = {}) {
  const blob = await request.get<Blob, Blob>(`/reports/export/${type}`, {
    params: params(filters),
    responseType: 'blob',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `lab-${type}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}

export const createReportExport = (type: ReportExportType, filters: ReportFilters = {}) =>
  request.post<unknown, ExportTaskVO>('/reports/exports', {
    export_type: type,
    start_date: filters.startDate,
    end_date: filters.endDate,
    status: filters.status,
    college_id: filters.collegeId,
  })

export const getReportExport = (id: number) =>
  request.get<unknown, ExportTaskVO>(`/reports/exports/${id}`)

export const downloadReportExport = async (id: number, type: ReportExportType) => {
  const blob = await request.get<Blob, Blob>(`/reports/exports/${id}/download`, {
    responseType: 'blob',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `lab-${type}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}
