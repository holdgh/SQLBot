// ========= 【改造标记 METRIC-CENTER】↓ 指标中心 API（镜像 professional.ts，裁剪 export/upload） =========
import { request } from '@/utils/request'

export const metricApi = {
  getList: (pageNum: any, pageSize: any, params: any) =>
    request.get(`/system/metric/page/${pageNum}/${pageSize}${params}`),
  updateEmbedded: (data: any) => request.put('/system/metric', data),
  deleteEmbedded: (params: any) => request.delete('/system/metric', { data: params }),
  enable: (id: any, enabled: any) => request.get(`/system/metric/${id}/enable/${enabled}`),
  getDimensionList: (params: any) => request.get(`/system/metric/dimension/list${params}`),
  updateDimension: (data: any) => request.put('/system/metric/dimension', data),
  deleteDimension: (params: any) => request.delete('/system/metric/dimension', { data: params }),
}
// ========= 【改造标记 METRIC-CENTER】↑ 指标中心 API 结束 =========
