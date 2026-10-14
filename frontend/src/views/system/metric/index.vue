<script lang="ts" setup>
import { nextTick, onMounted, reactive, ref, unref } from 'vue'
import icon_add_outlined from '@/assets/svg/icon_add_outlined.svg'
import IconOpeEdit from '@/assets/svg/icon_edit_outlined.svg'
import IconOpeDelete from '@/assets/svg/icon_delete.svg'
import icon_searchOutline_outlined from '@/assets/svg/icon_search-outline_outlined.svg'
import EmptyBackground from '@/views/dashboard/common/EmptyBackground.vue'
import { useI18n } from 'vue-i18n'
import { cloneDeep } from 'lodash-es'
import { convertFilterText } from '@/components/filter-text'
import { DrawerMain } from '@/components/drawer-main'
import iconFilter from '@/assets/svg/icon-filter_outlined.svg'
import { metricApi } from '@/api/metric'
import { datasourceApi } from '@/api/datasource'
import { formatTimestamp } from '@/utils/date'

const { t } = useI18n()

const activeTab = ref('metric')

// ========= 指标列表状态 =========
const multipleSelectionAll = ref<any[]>([])
const keywords = ref('')
const oldKeywords = ref('')
const searchLoading = ref(false)
const multipleTableRef = ref()
const isIndeterminate = ref(true)
const checkAll = ref(false)
const fieldList = ref<any>([])
const drawerMainRef = ref()
const allDsList = ref<any[]>([])
const dimensionOptions = ref<any[]>([])
const metricOptions = ref<any[]>([])
const pageInfo = reactive({
  currentPage: 1,
  pageSize: 10,
  total: 0,
})
const state = reactive<any>({
  conditions: [],
  filterTexts: [],
})

const selectable = () => {
  return true
}

const defaultForm = {
  id: null,
  metric_name: null,
  description: null,
  business_domain: null,
  specific_ds: false,
  datasource_ids: [] as number[],
  datasource_names: [] as string[],
  // ========= 【改造标记 METRIC-CENTER】↓ 问题2方案A：表所属数据源 =========
  source_ds_id: null as number | null,
  // ========= 【改造标记 METRIC-CENTER】↑ 表单字段新增结束 =========
  source_table: null,
  source_column: null,
  aggregation: null,
  filter_rule: null,
  time_field: null,
  metric_type: 'atomic',
  unit: null,
  normal_range: { min: null, max: null },
  additivity: 'additive',
  status: 'active',
  version: 1,
  enabled: true,
  aliases: [''] as string[],
  dimension_ids: [] as number[],
  dimension_names: [] as string[],
  dependencies: [] as any[],
}

const pageForm = ref<any>(cloneDeep(defaultForm))
const dialogFormVisible = ref<boolean>(false)
const dialogTitle = ref('')
const updateLoading = ref(false)
const metricFormRef = ref()

const rules = {
  metric_name: [
    {
      required: true,
      message: t('datasource.please_enter') + t('common.empty') + t('metric.metric_name'),
    },
  ],
  description: [
    {
      required: true,
      message: t('datasource.please_enter') + t('common.empty') + t('metric.metric_description'),
    },
  ],
}

const loadOptions = () => {
  datasourceApi.list().then((res) => {
    allDsList.value = res
    filterOption.value[0].option = [...res]
  })
  metricApi.getDimensionList('').then((res: any) => {
    dimensionOptions.value = res || []
  })
  metricApi.getList(1, 200, '').then((res: any) => {
    metricOptions.value = res?.data || []
  })
}

// ========= 【改造标记 METRIC-CENTER】↓ 问题2：数据源→表→字段级联（表元数据 core_table / 字段元数据 core_field） =========
const tableOptions = ref<any[]>([])
const fieldOptions = ref<any[]>([])
const tableLoading = ref(false)
const fieldLoading = ref(false)
const AGGREGATION_OPTIONS = ['sum', 'avg', 'count', 'min', 'max']

const loadTableOptions = (dsId: number | null) => {
  tableOptions.value = []
  fieldOptions.value = []
  if (!dsId) {
    return Promise.resolve()
  }
  tableLoading.value = true
  return datasourceApi
    .tableList(dsId)
    .then((res: any) => {
      tableOptions.value = res || []
    })
    .finally(() => {
      tableLoading.value = false
    })
}

const loadFieldOptions = (dsId: number | null, tableName: string | null) => {
  fieldOptions.value = []
  if (!dsId || !tableName) {
    return Promise.resolve()
  }
  const table = tableOptions.value.find((item: any) => item.table_name === tableName)
  if (!table) {
    // 手动输入的表不在已同步元数据中：字段候选为空，仍可手动输入（allow-create）
    return Promise.resolve()
  }
  fieldLoading.value = true
  return datasourceApi
    .fieldList(dsId, table.id)
    .then((res: any) => {
      fieldOptions.value = res || []
    })
    .finally(() => {
      fieldLoading.value = false
    })
}

const handleSourceDsChange = (dsId: number | null) => {
  pageForm.value.source_table = null
  pageForm.value.source_column = null
  pageForm.value.time_field = null
  loadTableOptions(dsId)
}

const handleSourceTableChange = (tableName: string | null) => {
  pageForm.value.source_column = null
  pageForm.value.time_field = null
  loadFieldOptions(pageForm.value.source_ds_id, tableName)
}

// 打开编辑抽屉时按已存值恢复级联候选
const initCascadeFromForm = () => {  if (!pageForm.value.source_ds_id) {
    return
  }
  loadTableOptions(pageForm.value.source_ds_id).then(() => {
    if (pageForm.value.source_table) {
      loadFieldOptions(pageForm.value.source_ds_id, pageForm.value.source_table)
    }
  })
}

// 详情抽屉展示：source_ds_id → 数据源名
const dsNameOf = (dsId: number | null) => {
  if (!dsId) {
    return ''
  }
  const ds = allDsList.value.find((item: any) => item.id === dsId)
  return ds ? ds.name : ''
}
// ========= 【改造标记 METRIC-CENTER】↑ 级联函数结束 =========

onMounted(() => {
  loadOptions()
  search()
})

const configParams = () => {
  let str = ''
  if (keywords.value) {
    str += `name=${keywords.value}`
  }
  state.conditions.forEach((ele: any) => {
    ele.value.forEach((itx: any) => {
      str += str ? `&${ele.field}=${itx}` : `${ele.field}=${itx}`
    })
  })
  if (str.length) {
    str = `?${str}`
  }
  return str
}

const search = ($event: any = {}) => {
  if ($event?.isComposing) {
    return
  }
  searchLoading.value = true
  oldKeywords.value = keywords.value
  metricApi
    .getList(pageInfo.currentPage, pageInfo.pageSize, configParams())
    .then((res) => {
      toggleRowLoading.value = true
      fieldList.value = res.data
      pageInfo.total = res.total_count
      searchLoading.value = false
      nextTick(() => {
        handleToggleRowSelection()
      })
    })
    .finally(() => {
      searchLoading.value = false
    })
}

const toggleRowLoading = ref(false)

const handleSelectionChange = (val: any[]) => {
  if (toggleRowLoading.value) return
  const arr = fieldList.value.filter(selectable)
  const ids = arr.map((ele: any) => ele.id)
  multipleSelectionAll.value = [
    ...multipleSelectionAll.value.filter((ele: any) => !ids.includes(ele.id)),
    ...val,
  ]
  isIndeterminate.value = !(val.length === 0 || val.length === arr.length)
  checkAll.value = val.length === arr.length
}

const handleCheckAllChange = (val: any) => {
  isIndeterminate.value = false
  handleSelectionChange(val ? fieldList.value.filter(selectable) : [])
  if (val) {
    handleToggleRowSelection()
  } else {
    multipleTableRef.value.clearSelection()
  }
}

const handleToggleRowSelection = (check: boolean = true) => {
  toggleRowLoading.value = true
  const arr = fieldList.value.filter(selectable)
  let i = 0
  const ids = multipleSelectionAll.value.map((ele: any) => ele.id)
  for (const key in arr) {
    if (ids.includes((arr[key] as any).id)) {
      i += 1
      multipleTableRef.value.toggleRowSelection(arr[key], check)
    }
  }
  toggleRowLoading.value = false
  checkAll.value = i === arr.length
  isIndeterminate.value = !(i === 0 || i === arr.length)
}

const cancelDelete = () => {
  handleToggleRowSelection(false)
  multipleSelectionAll.value = []
  checkAll.value = false
  isIndeterminate.value = false
}

const deleteBatch = () => {
  ElMessageBox.confirm(
    t('metric.selected_2_metrics', { msg: multipleSelectionAll.value.length }),
    {
      confirmButtonType: 'danger',
      confirmButtonText: t('dashboard.delete'),
      cancelButtonText: t('common.cancel'),
      customClass: 'confirm-no_icon',
      autofocus: false,
    }
  ).then(() => {
    metricApi.deleteEmbedded(multipleSelectionAll.value.map((ele) => ele.id)).then(() => {
      ElMessage({
        type: 'success',
        message: t('dashboard.delete_success'),
      })
      multipleSelectionAll.value = []
      search()
    })
  })
}

const deleteHandler = (row: any) => {
  ElMessageBox.confirm(t('metric.the_metric_gmv', { msg: row.metric_name }), {
    confirmButtonType: 'danger',
    confirmButtonText: t('dashboard.delete'),
    cancelButtonText: t('common.cancel'),
    customClass: 'confirm-no_icon',
    autofocus: false,
  }).then(() => {
    metricApi.deleteEmbedded([row.id]).then(() => {
      multipleSelectionAll.value = multipleSelectionAll.value.filter((ele) => row.id !== ele.id)
      ElMessage({
        type: 'success',
        message: t('dashboard.delete_success'),
      })
      search()
    })
  })
}

const editHandler = (row: any) => {
  pageForm.value = cloneDeep(defaultForm)
  if (row) {
    pageForm.value = cloneDeep({ ...cloneDeep(defaultForm), ...row })
    if (!pageForm.value.aliases.length) {
      pageForm.value.aliases = ['']
    }
    if (!pageForm.value.normal_range) {
      pageForm.value.normal_range = { min: null, max: null }
    }
    if (!pageForm.value.dependencies.length) {
      pageForm.value.dependencies = []
    }
  }
  loadOptions()
  // ========= 【改造标记 METRIC-CENTER】↓ 编辑时按已存 source_ds_id 恢复表/字段候选 =========
  initCascadeFromForm()
  // ========= 【改造标记 METRIC-CENTER】↑ 恢复结束 =========
  dialogTitle.value = row?.id ? t('metric.editing_metric') : t('metric.create_new_metric')
  dialogFormVisible.value = true
}

const onFormClose = () => {
  pageForm.value = cloneDeep(defaultForm)
  // ========= 【改造标记 METRIC-CENTER】↓ 关闭指标抽屉时清空级联候选 =========
  tableOptions.value = []
  fieldOptions.value = []
  // ========= 【改造标记 METRIC-CENTER】↑ 清空结束 =========
  dialogFormVisible.value = false
}

const addAliasItem = () => {
  pageForm.value.aliases.push('')
}

const deleteAliasItem = (idx: number) => {
  pageForm.value.aliases = pageForm.value.aliases!.filter((_: any, index: number) => index !== idx)
}

const addDependencyItem = () => {
  pageForm.value.dependencies.push({ depends_on_metric_id: null, expression_hint: '' })
}

const deleteDependencyItem = (idx: number) => {
  pageForm.value.dependencies = pageForm.value.dependencies.filter(
    (_: any, index: number) => index !== idx
  )
}

const saveHandler = () => {
  metricFormRef.value.validate((res: any) => {
    if (res) {
      const filledAliases = pageForm.value.aliases.filter((ele: any) => !!ele)
      if (filledAliases.length !== new Set(filledAliases).size) {
        return ElMessage.error(t('metric.cannot_be_repeated'))
      }
      const obj: any = cloneDeep(unref(pageForm))
      if (!obj.id) {
        delete obj.id
      }
      obj.aliases = filledAliases
      obj.dependencies = (obj.dependencies || []).filter(
        (dep: any) => !!dep.depends_on_metric_id
      )
      const range = obj.normal_range || {}
      if (
        (range.min === null || range.min === undefined || range.min === '') &&
        (range.max === null || range.max === undefined || range.max === '')
      ) {
        obj.normal_range = null
      } else {
        obj.normal_range = {
          min: range.min === null || range.min === undefined || range.min === '' ? null : range.min,
          max: range.max === null || range.max === undefined || range.max === '' ? null : range.max,
        }
      }
      updateLoading.value = true
      metricApi
        .updateEmbedded(obj)
        .then(() => {
          ElMessage({
            type: 'success',
            message: t('common.save_success'),
          })
          search()
          loadOptions()
          onFormClose()
        })
        .finally(() => {
          updateLoading.value = false
        })
    }
  })
}

const handleSizeChange = (val: number) => {
  pageInfo.currentPage = 1
  pageInfo.pageSize = val
  search()
}

const handleCurrentChange = (val: number) => {
  pageInfo.currentPage = val
  search()
}

const rowInfoDialog = ref(false)

const handleRowClick = (row: any) => {
  pageForm.value = cloneDeep({ ...cloneDeep(defaultForm), ...row })
  rowInfoDialog.value = true
}

const onRowFormClose = () => {
  pageForm.value = cloneDeep(defaultForm)
  rowInfoDialog.value = false
}

const changeStatus = (id: any, val: any) => {
  metricApi
    .enable(id, val + '')
    .then(() => {
      ElMessage({
        message: t('common.save_success'),
        type: 'success',
      })
    })
    .finally(() => {
      search()
    })
}

const filterOption = ref<any[]>([
  {
    type: 'select',
    option: [],
    field: 'ds_list',
    title: t('ds.title'),
    operate: 'in',
    property: { placeholder: t('common.empty') + t('ds.title') },
  },
])

const fillFilterText = () => {
  const textArray = state.conditions?.length
    ? convertFilterText(state.conditions, filterOption.value)
    : []
  state.filterTexts = [...textArray]
  Object.assign(state.filterTexts, textArray)
}

const searchCondition = (conditions: any) => {
  state.conditions = conditions
  fillFilterText()
  search()
  drawerMainClose()
}

const clearFilter = (params?: number) => {
  let index = params ? params : 0
  if (isNaN(index)) {
    state.filterTexts = []
  } else {
    state.filterTexts.splice(index, 1)
  }
  drawerMainRef.value.clearFilter(index)
}

const drawerMainOpen = async () => {
  drawerMainRef.value.init()
}

const drawerMainClose = () => {
  drawerMainRef.value.close()
}

// ========= 维度（dimension）tab 状态 =========
const dimKeywords = ref('')
const dimLoading = ref(false)
const dimList = ref<any[]>([])
const dimDialogVisible = ref(false)
const dimDialogTitle = ref('')
const dimFormRef = ref()
const dimUpdateLoading = ref(false)
const defaultDimForm = {
  id: null,
  dimension_name: null,
  aliases: [''] as string[],
  // ========= 【改造标记 METRIC-CENTER】↓ 问题4：维度落点三元组（随表单提交/编辑回显，原独立辅助变量弃用） =========
  source_ds_id: null,
  source_table: null,
  column_name: null,
  // ========= 【改造标记 METRIC-CENTER】↑ 问题4 结束（原 default_column） =========
  description: null,
}
const dimForm = ref<any>(cloneDeep(defaultDimForm))
const dimRules = {
  dimension_name: [
    {
      required: true,
      message:
        t('datasource.please_enter') + t('common.empty') + t('metric.dimension_name'),
    },
  ],
}

// ========= 【改造标记 METRIC-CENTER】↓ 问题4：维度落点三元组（原 dimCascadeDsId/dimCascadeTable 独立变量已并入 dimForm，提交入库） =========
const dimTableOptions = ref<any[]>([])
const dimFieldOptions = ref<any[]>([])
const dimTableLoading = ref(false)
const dimFieldLoading = ref(false)

const resetDimCascade = () => {
  dimForm.value.source_ds_id = null
  dimForm.value.source_table = null
  dimTableOptions.value = []
  dimFieldOptions.value = []
}

const loadDimTableOptions = (dsId: number | null) => {
  dimTableOptions.value = []
  dimFieldOptions.value = []
  if (!dsId) {
    return Promise.resolve()
  }
  dimTableLoading.value = true
  return datasourceApi
    .tableList(dsId)
    .then((res: any) => {
      dimTableOptions.value = res || []
    })
    .finally(() => {
      dimTableLoading.value = false
    })
}

const handleDimDsChange = (dsId: number | null) => {
  dimForm.value.source_table = null
  loadDimTableOptions(dsId)
}

const handleDimTableChange = (tableName: string | null) => {
  dimFieldOptions.value = []
  if (!dimForm.value.source_ds_id || !tableName) {
    return
  }
  const table = dimTableOptions.value.find((item: any) => item.table_name === tableName)
  if (!table) {
    return
  }
  dimFieldLoading.value = true
  datasourceApi
    .fieldList(dimForm.value.source_ds_id, table.id)
    .then((res: any) => {
      dimFieldOptions.value = res || []
    })
    .finally(() => {
      dimFieldLoading.value = false
    })
}
// ========= 【改造标记 METRIC-CENTER】↑ 问题4 维度弱联动结束 =========

const searchDimension = () => {
  dimLoading.value = true
  metricApi
    .getDimensionList(dimKeywords.value ? `?name=${dimKeywords.value}` : '')
    .then((res: any) => {
      dimList.value = res || []
    })
    .finally(() => {
      dimLoading.value = false
    })
}

const editDimHandler = (row: any) => {
  dimForm.value = cloneDeep(defaultDimForm)
  // ========= 【改造标记 METRIC-CENTER】↓ 打开维度抽屉时重置弱联动候选 =========
  resetDimCascade()
  // ========= 【改造标记 METRIC-CENTER】↑ 重置结束 =========
  if (row) {
    dimForm.value = cloneDeep({ ...cloneDeep(defaultDimForm), ...row })
    if (!dimForm.value.aliases.length) {
      dimForm.value.aliases = ['']
    }
    // ========= 【改造标记 METRIC-CENTER】↓ 问题4：编辑时按已存落点恢复级联候选（表候选 + 字段候选预加载） =========
    if (dimForm.value.source_ds_id) {
      const savedTable = dimForm.value.source_table
      loadDimTableOptions(dimForm.value.source_ds_id).then(() => {
        if (savedTable) {
          handleDimTableChange(savedTable)
        }
      })
    }
    // ========= 【改造标记 METRIC-CENTER】↑ 问题4 恢复结束 =========
  }
  dimDialogTitle.value = row?.id
    ? t('metric.editing_dimension')
    : t('metric.create_new_dimension')
  dimDialogVisible.value = true
}

const onDimClose = () => {
  dimForm.value = cloneDeep(defaultDimForm)
  // ========= 【改造标记 METRIC-CENTER】↓ 关闭维度抽屉时重置弱联动候选 =========
  resetDimCascade()
  // ========= 【改造标记 METRIC-CENTER】↑ 重置结束 =========
  dimDialogVisible.value = false
}

const addDimAliasItem = () => {
  dimForm.value.aliases.push('')
}

const deleteDimAliasItem = (idx: number) => {
  dimForm.value.aliases = dimForm.value.aliases!.filter(
    (_: any, index: number) => index !== idx
  )
}

const saveDimHandler = () => {
  dimFormRef.value.validate((res: any) => {
    if (res) {
      const obj = unref(dimForm)
      if (!obj.id) {
        delete obj.id
      }
      obj.aliases = (obj.aliases || []).filter((ele: any) => !!ele)
      dimUpdateLoading.value = true
      metricApi
        .updateDimension(obj)
        .then(() => {
          ElMessage({
            type: 'success',
            message: t('common.save_success'),
          })
          searchDimension()
          loadOptions()
          onDimClose()
        })
        .finally(() => {
          dimUpdateLoading.value = false
        })
    }
  })
}

const deleteDimHandler = (row: any) => {
  ElMessageBox.confirm(t('metric.the_dimension_gmv', { msg: row.dimension_name }), {
    confirmButtonType: 'danger',
    confirmButtonText: t('dashboard.delete'),
    cancelButtonText: t('common.cancel'),
    customClass: 'confirm-no_icon',
    autofocus: false,
  }).then(() => {
    metricApi.deleteDimension([row.id]).then(() => {
      ElMessage({
        type: 'success',
        message: t('dashboard.delete_success'),
      })
      searchDimension()
      loadOptions()
    })
  })
}

const handleTabChange = () => {
  if (activeTab.value === 'dimension') {
    searchDimension()
  }
}
</script>

<template>
  <div v-loading="searchLoading || dimLoading" class="metric-page">
    <div class="tool-left">
      <span class="page-title">{{ $t('metric.metric_management') }}</span>
      <el-tabs v-model="activeTab" class="metric-tabs" @tab-change="handleTabChange">
        <el-tab-pane :label="$t('metric.tab_metric')" name="metric" />
        <el-tab-pane :label="$t('metric.tab_dimension')" name="dimension" />
      </el-tabs>
    </div>

    <!-- ========= 指标 tab ========= -->
    <template v-if="activeTab === 'metric'">
      <div class="tool-row flex-gap-fallback">
        <el-input
          v-model="keywords"
          style="width: 240px; margin-right: 12px"
          :placeholder="$t('metric.search_metric')"
          clearable
          @keydown.enter.exact.prevent="search"
        >
          <template #prefix>
            <el-icon>
              <icon_searchOutline_outlined />
            </el-icon>
          </template>
        </el-input>
        <el-button class="no-margin" secondary @click="drawerMainOpen">
          <template #icon>
            <iconFilter></iconFilter>
          </template>
          {{ $t('user.filter') }}
        </el-button>
        <el-button class="no-margin" type="primary" @click="editHandler(null)">
          <template #icon>
            <icon_add_outlined></icon_add_outlined>
          </template>
          {{ $t('metric.create_new_metric') }}
        </el-button>
      </div>

      <div
        v-if="!searchLoading"
        class="table-content"
        :class="multipleSelectionAll.length ? 'show-pagination_height' : ''"
      >
        <filter-text
          :total="pageInfo.total"
          :filter-texts="state.filterTexts"
          @clear-filter="clearFilter"
        />
        <div class="preview-or-schema">
          <el-table
            ref="multipleTableRef"
            :data="fieldList"
            style="width: 100%"
            @row-click="handleRowClick"
            @selection-change="handleSelectionChange"
          >
            <el-table-column :selectable="selectable" type="selection" width="55" />
            <el-table-column prop="metric_name" :label="$t('metric.metric_name')" width="220">
              <template #default="scope">
                {{ scope.row.metric_name }}
                <span style="display: inline-block; width: 8px; height: 1px"></span>
                {{
                  scope.row.aliases && scope.row.aliases.length
                    ? `(${scope.row.aliases.join(',')})`
                    : ''
                }}
              </template>
            </el-table-column>
            <el-table-column :label="$t('metric.metric_type')" width="120">
              <template #default="scope">
                {{
                  scope.row.metric_type === 'derived'
                    ? $t('metric.metric_type_derived')
                    : scope.row.metric_type === 'composite'
                      ? $t('metric.metric_type_composite')
                      : $t('metric.metric_type_atomic')
                }}
              </template>
            </el-table-column>
            <el-table-column :label="$t('metric.metric_description')" min-width="240">
              <template #default="scope">
                <div class="field-comment_d">
                  <span :title="scope.row.description" class="notes-in_table">{{
                    scope.row.description
                  }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column
              prop="aggregation"
              :label="$t('metric.aggregation')"
              width="120"
            />
            <el-table-column prop="unit" :label="$t('metric.unit')" width="100" />
            <el-table-column :label="$t('training.effective_data_sources')" min-width="200">
              <template #default="scope">
                <div v-if="scope.row.specific_ds" class="field-comment_d">
                  <span :title="scope.row.datasource_names" class="notes-in_table">{{
                    scope.row.datasource_names.join(',')
                  }}</span>
                </div>
                <div v-else>{{ t('training.all_data_sources') }}</div>
              </template>
            </el-table-column>
            <el-table-column :label="t('ds.status')" width="120">
              <template #default="scope">
                <div style="display: flex; align-items: center" @click.stop>
                  <el-switch
                    v-model="scope.row.enabled"
                    size="small"
                    @change="(val: any) => changeStatus(scope.row.id, val)"
                  />
                </div>
              </template>
            </el-table-column>
            <el-table-column
              prop="create_time"
              sortable
              :label="$t('dashboard.create_time')"
              width="180"
            >
              <template #default="scope">
                <span>{{ formatTimestamp(scope.row.create_time, 'YYYY-MM-DD HH:mm:ss') }}</span>
              </template>
            </el-table-column>
            <el-table-column fixed="right" width="80" :label="t('ds.actions')">
              <template #default="scope">
                <div class="field-comment">
                  <el-tooltip
                    :offset="14"
                    effect="dark"
                    :content="$t('datasource.edit')"
                    placement="top"
                  >
                    <el-icon class="action-btn" size="16" @click.stop="editHandler(scope.row)">
                      <IconOpeEdit></IconOpeEdit>
                    </el-icon>
                  </el-tooltip>
                  <el-tooltip
                    :offset="14"
                    effect="dark"
                    :content="$t('dashboard.delete')"
                    placement="top"
                  >
                    <el-icon class="action-btn" size="16" @click.stop="deleteHandler(scope.row)">
                      <IconOpeDelete></IconOpeDelete>
                    </el-icon>
                  </el-tooltip>
                </div>
              </template>
            </el-table-column>
            <template #empty>
              <EmptyBackground
                v-if="!oldKeywords && !fieldList.length"
                :description="$t('metric.no_metric')"
                img-type="noneWhite"
              />
              <EmptyBackground
                v-if="!!oldKeywords && !fieldList.length"
                :description="$t('datasource.relevant_content_found')"
                img-type="tree"
              />
            </template>
          </el-table>
        </div>
      </div>

      <div v-if="fieldList.length" class="pagination-container">
        <el-pagination
          v-model:current-page="pageInfo.currentPage"
          v-model:page-size="pageInfo.pageSize"
          :page-sizes="[10, 20, 30]"
          :background="true"
          layout="total, sizes, prev, pager, next, jumper"
          :total="pageInfo.total"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
      <div v-if="multipleSelectionAll.length" class="bottom-select">
        <el-checkbox
          v-model="checkAll"
          :indeterminate="isIndeterminate"
          @change="handleCheckAllChange"
        >
          {{ $t('datasource.select_all') }}
        </el-checkbox>
        <button class="danger-button" @click="deleteBatch">{{ $t('dashboard.delete') }}</button>
        <span class="selected">{{
          $t('user.selected_2_items', { msg: multipleSelectionAll.length })
        }}</span>
        <el-button text @click="cancelDelete">{{ $t('common.cancel') }}</el-button>
      </div>
    </template>

    <!-- ========= 维度 tab ========= -->
    <template v-else>
      <div class="tool-row flex-gap-fallback">
        <el-input
          v-model="dimKeywords"
          style="width: 240px; margin-right: 12px"
          :placeholder="$t('metric.search_dimension')"
          clearable
          @keydown.enter.exact.prevent="searchDimension"
        >
          <template #prefix>
            <el-icon>
              <icon_searchOutline_outlined />
            </el-icon>
          </template>
        </el-input>
        <el-button class="no-margin" type="primary" @click="editDimHandler(null)">
          <template #icon>
            <icon_add_outlined></icon_add_outlined>
          </template>
          {{ $t('metric.create_new_dimension') }}
        </el-button>
      </div>

      <div v-if="!dimLoading" class="table-content">
        <div class="preview-or-schema">
          <el-table :data="dimList" style="width: 100%">
            <el-table-column
              prop="dimension_name"
              :label="$t('metric.dimension_name')"
              width="220"
            />
            <el-table-column :label="$t('metric.dimension_aliases')" min-width="200">
              <template #default="scope">
                {{ (scope.row.aliases || []).join(',') }}
              </template>
            </el-table-column>
            <el-table-column
              prop="column_name"
              :label="$t('metric.dimension_column_name')"
              min-width="180"
            />
            <el-table-column :label="$t('metric.dimension_description')" min-width="240">
              <template #default="scope">
                <div class="field-comment_d">
                  <span :title="scope.row.description" class="notes-in_table">{{
                    scope.row.description
                  }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column
              prop="metric_count"
              :label="$t('metric.dimension_metric_count')"
              width="120"
            />
            <el-table-column fixed="right" width="80" :label="t('ds.actions')">
              <template #default="scope">
                <div class="field-comment">
                  <el-tooltip
                    :offset="14"
                    effect="dark"
                    :content="$t('datasource.edit')"
                    placement="top"
                  >
                    <el-icon
                      class="action-btn"
                      size="16"
                      @click.stop="editDimHandler(scope.row)"
                    >
                      <IconOpeEdit></IconOpeEdit>
                    </el-icon>
                  </el-tooltip>
                  <el-tooltip
                    :offset="14"
                    effect="dark"
                    :content="$t('dashboard.delete')"
                    placement="top"
                  >
                    <el-icon
                      class="action-btn"
                      size="16"
                      @click.stop="deleteDimHandler(scope.row)"
                    >
                      <IconOpeDelete></IconOpeDelete>
                    </el-icon>
                  </el-tooltip>
                </div>
              </template>
            </el-table-column>
            <template #empty>
              <EmptyBackground
                v-if="!dimKeywords && !dimList.length"
                :description="$t('metric.no_dimension')"
                img-type="noneWhite"
              />
              <EmptyBackground
                v-if="!!dimKeywords && !dimList.length"
                :description="$t('datasource.relevant_content_found')"
                img-type="tree"
              />
            </template>
          </el-table>
        </div>
      </div>
    </template>
  </div>

  <!-- ========= 指标新建/编辑抽屉 ========= -->
  <el-drawer
    v-model="dialogFormVisible"
    :title="dialogTitle"
    destroy-on-close
    size="680px"
    :before-close="onFormClose"
    modal-class="metric-add_drawer"
  >
    <el-form
      ref="metricFormRef"
      :model="pageForm"
      label-width="180px"
      label-position="top"
      :rules="rules"
      class="form-content_error"
      @submit.prevent
    >
      <el-form-item prop="metric_name" :label="t('metric.metric_name')">
        <el-input
          v-model="pageForm.metric_name"
          :placeholder="
            $t('datasource.please_enter') + $t('common.empty') + $t('metric.metric_name')
          "
          autocomplete="off"
          maxlength="100"
          clearable
        />
      </el-form-item>
      <el-form-item prop="description" :label="t('metric.metric_description')">
        <el-input
          v-model="pageForm.description"
          :placeholder="$t('datasource.please_enter')"
          :autosize="{ minRows: 3.636, maxRows: 11.09 }"
          type="textarea"
        />
      </el-form-item>
      <el-form-item :label="t('metric.business_domain')">
        <el-input
          v-model="pageForm.business_domain"
          :placeholder="$t('datasource.please_enter')"
          maxlength="100"
          clearable
        />
      </el-form-item>
      <div class="form-inline_row">
        <el-form-item :label="t('metric.metric_type')" class="form-inline_item">
          <el-select v-model="pageForm.metric_type" style="width: 100%">
            <el-option
              :label="$t('metric.metric_type_atomic')"
              value="atomic"
            />
            <el-option
              :label="$t('metric.metric_type_derived')"
              value="derived"
            />
            <el-option
              :label="$t('metric.metric_type_composite')"
              value="composite"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('metric.additivity')" class="form-inline_item">
          <el-select v-model="pageForm.additivity" style="width: 100%">
            <el-option :label="$t('metric.additivity_additive')" value="additive" />
            <el-option :label="$t('metric.additivity_semi')" value="semi" />
            <el-option :label="$t('metric.additivity_non')" value="non" />
          </el-select>
        </el-form-item>
      </div>
      <div class="form-inline_row">
        <el-form-item :label="t('metric.aggregation')" class="form-inline_item">
          <!-- ========= 【改造标记 METRIC-CENTER】↓ 问题2附带：聚合方式固定下拉（allow-create 兼容存量） ========= -->
          <el-select
            v-model="pageForm.aggregation"
            filterable
            allow-create
            clearable
            style="width: 100%"
            :placeholder="$t('datasource.Please_select')"
          >
            <el-option v-for="item in AGGREGATION_OPTIONS" :key="item" :label="item" :value="item" />
          </el-select>
          <!-- ========= 【改造标记 METRIC-CENTER】↑ 聚合下拉结束 ========= -->
        </el-form-item>
        <el-form-item :label="t('metric.unit')" class="form-inline_item">
          <el-input
            v-model="pageForm.unit"
            :placeholder="$t('datasource.please_enter')"
            clearable
          />
        </el-form-item>
      </div>
      <div class="form-inline_row">
        <!-- ========= 【改造标记 METRIC-CENTER】↓ 问题2：数据源→表级联（allow-create 兜底手输） ========= -->
        <el-form-item :label="t('metric.source_datasource')" class="form-inline_item">
          <el-select
            v-model="pageForm.source_ds_id"
            filterable
            clearable
            style="width: 100%"
            :placeholder="$t('datasource.Please_select')"
            @change="handleSourceDsChange"
          >
            <el-option
              v-for="item in allDsList"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('metric.source_table')" class="form-inline_item">
          <el-select
            v-model="pageForm.source_table"
            filterable
            allow-create
            clearable
            :loading="tableLoading"
            :disabled="!pageForm.source_ds_id"
            style="width: 100%"
            :placeholder="
              pageForm.source_ds_id
                ? $t('datasource.Please_select')
                : $t('metric.select_source_ds_first')
            "
            @change="handleSourceTableChange"
          >
            <el-option
              v-for="item in tableOptions"
              :key="item.id"
              :label="item.table_name"
              :value="item.table_name"
            />
          </el-select>
        </el-form-item>
        <!-- ========= 【改造标记 METRIC-CENTER】↑ 表级联结束 ========= -->
      </div>
      <div class="form-inline_row">
        <!-- ========= 【改造标记 METRIC-CENTER】↓ 表→字段级联（source_column/time_field） ========= -->
        <el-form-item :label="t('metric.source_column')" class="form-inline_item">
          <el-select
            v-model="pageForm.source_column"
            filterable
            allow-create
            clearable
            :loading="fieldLoading"
            :disabled="!pageForm.source_table"
            style="width: 100%"
            :placeholder="
              pageForm.source_table
                ? $t('datasource.Please_select')
                : $t('metric.select_source_table_first')
            "
          >
            <el-option
              v-for="item in fieldOptions"
              :key="item.id"
              :label="item.field_name"
              :value="item.field_name"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('metric.time_field')" class="form-inline_item">
          <el-select
            v-model="pageForm.time_field"
            filterable
            allow-create
            clearable
            :loading="fieldLoading"
            :disabled="!pageForm.source_table"
            style="width: 100%"
            :placeholder="
              pageForm.source_table
                ? $t('datasource.Please_select')
                : $t('metric.select_source_table_first')
            "
          >
            <el-option
              v-for="item in fieldOptions"
              :key="item.id"
              :label="item.field_name"
              :value="item.field_name"
            />
          </el-select>
        </el-form-item>
        <!-- ========= 【改造标记 METRIC-CENTER】↑ 字段级联结束 ========= -->
      </div>
      <el-form-item :label="t('metric.normal_range')">
        <div class="normal-range">
          <el-input-number
            v-model="pageForm.normal_range.min"
            :placeholder="$t('metric.normal_range_min')"
            :controls="false"
          />
          <span class="range-sep">-</span>
          <el-input-number
            v-model="pageForm.normal_range.max"
            :placeholder="$t('metric.normal_range_max')"
            :controls="false"
          />
        </div>
      </el-form-item>
      <el-form-item :label="t('metric.filter_rule')">
        <el-input
          v-model="pageForm.filter_rule"
          :placeholder="$t('datasource.please_enter')"
          :autosize="{ minRows: 2, maxRows: 6 }"
          type="textarea"
        />
      </el-form-item>
      <el-form-item :label="t('training.effective_data_sources')">
        <el-radio-group v-model="pageForm.specific_ds">
          <el-radio :value="false">{{ $t('training.all_data_sources') }}</el-radio>
          <el-radio :value="true">{{ $t('training.partial_data_sources') }}</el-radio>
        </el-radio-group>
        <el-select
          v-if="pageForm.specific_ds"
          v-model="pageForm.datasource_ids"
          multiple
          filterable
          :placeholder="$t('datasource.Please_select') + $t('common.empty') + $t('ds.title')"
          style="width: 100%; margin-top: 8px"
        >
          <el-option v-for="item in allDsList" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <template #label>
          <div style="display: flex; align-items: center">
            <span>{{ t('metric.aliases') }}</span>
            <span class="btn" @click="addAliasItem">
              <el-icon style="margin-right: 4px" size="16">
                <icon_add_outlined></icon_add_outlined>
              </el-icon>
              {{ $t('model.add') }}
            </span>
          </div>
        </template>
        <div class="alias-list">
          <el-scrollbar>
            <div v-for="(_, index) in pageForm.aliases" :key="index" class="scrollbar-item">
              <el-input
                v-model="pageForm.aliases[index]"
                style="width: 560px"
                :placeholder="
                  $t('datasource.please_enter') + $t('common.empty') + $t('metric.aliases')
                "
                maxlength="100"
                clearable
              />
              <el-tooltip
                :offset="14"
                effect="dark"
                :content="$t('dashboard.delete')"
                placement="top"
              >
                <el-icon
                  class="hover-icon_with_bg"
                  size="16"
                  style="color: #646a73"
                  @click.stop="deleteAliasItem(index)"
                >
                  <IconOpeDelete></IconOpeDelete>
                </el-icon>
              </el-tooltip>
            </div>
          </el-scrollbar>
        </div>
      </el-form-item>
      <el-form-item :label="t('metric.dimensions')">
        <el-select
          v-model="pageForm.dimension_ids"
          multiple
          filterable
          :placeholder="$t('datasource.Please_select')"
          style="width: 100%"
        >
          <el-option
            v-for="item in dimensionOptions"
            :key="item.id"
            :label="item.dimension_name"
            :value="item.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item>
        <template #label>
          <div style="display: flex; align-items: center">
            <span>{{ t('metric.dependencies') }}</span>
            <span class="btn" @click="addDependencyItem">
              <el-icon style="margin-right: 4px" size="16">
                <icon_add_outlined></icon_add_outlined>
              </el-icon>
              {{ $t('model.add') }}
            </span>
          </div>
        </template>
        <div class="dependency-list">
          <el-scrollbar>
            <div
              v-for="(_, index) in pageForm.dependencies"
              :key="index"
              class="scrollbar-item dependency-item"
            >
              <el-select
                v-model="pageForm.dependencies[index].depends_on_metric_id"
                filterable
                :placeholder="$t('datasource.Please_select') + $t('common.empty') + $t('metric.dependencies')"
                style="width: 240px"
              >
                <el-option
                  v-for="item in metricOptions.filter((m) => m.id !== pageForm.id)"
                  :key="item.id"
                  :label="item.metric_name"
                  :value="item.id"
                />
              </el-select>
              <el-input
                v-model="pageForm.dependencies[index].expression_hint"
                :placeholder="$t('datasource.please_enter') + $t('common.empty') + $t('metric.expression_hint')"
                clearable
              />
              <el-tooltip
                :offset="14"
                effect="dark"
                :content="$t('dashboard.delete')"
                placement="top"
              >
                <el-icon
                  class="hover-icon_with_bg"
                  size="16"
                  style="color: #646a73"
                  @click.stop="deleteDependencyItem(index)"
                >
                  <IconOpeDelete></IconOpeDelete>
                </el-icon>
              </el-tooltip>
            </div>
          </el-scrollbar>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <div v-loading="updateLoading" class="dialog-footer">
        <el-button secondary @click="onFormClose">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" @click="saveHandler">{{ $t('common.save') }}</el-button>
      </div>
    </template>
  </el-drawer>

  <!-- ========= 指标详情抽屉 ========= -->
  <el-drawer
    v-model="rowInfoDialog"
    :title="$t('metric.metric_details')"
    destroy-on-close
    size="600px"
    :before-close="onRowFormClose"
    modal-class="metric-detail_drawer"
  >
    <el-form label-width="180px" label-position="top" class="form-content_error" @submit.prevent>
      <el-form-item :label="t('metric.metric_name')">
        <div class="content">{{ pageForm.metric_name }}</div>
      </el-form-item>
      <el-form-item :label="t('metric.aliases')">
        <div class="content">{{ (pageForm.aliases || []).join(',') }}</div>
      </el-form-item>
      <el-form-item :label="t('metric.metric_description')">
        <div class="content">{{ pageForm.description }}</div>
      </el-form-item>
      <el-form-item :label="t('metric.business_domain')">
        <div class="content">{{ pageForm.business_domain }}</div>
      </el-form-item>
      <!-- ========= 【改造标记 METRIC-CENTER】↓ 问题2：详情展示表所属数据源与来源表/字段 ========= -->
      <el-form-item :label="t('metric.source_datasource')">
        <div class="content">{{ dsNameOf(pageForm.source_ds_id) }}</div>
      </el-form-item>
      <el-form-item :label="t('metric.source_table')">
        <div class="content">{{ pageForm.source_table }}</div>
      </el-form-item>
      <el-form-item :label="t('metric.source_column')">
        <div class="content">{{ pageForm.source_column }}</div>
      </el-form-item>
      <el-form-item :label="t('metric.time_field')">
        <div class="content">{{ pageForm.time_field }}</div>
      </el-form-item>
      <!-- ========= 【改造标记 METRIC-CENTER】↑ 详情字段结束 ========= -->
      <el-form-item :label="t('metric.aggregation')">
        <div class="content">{{ pageForm.aggregation }}</div>
      </el-form-item>
      <el-form-item :label="t('metric.filter_rule')">
        <div class="content">{{ pageForm.filter_rule }}</div>
      </el-form-item>
      <el-form-item :label="t('metric.dimensions')">
        <div class="content">{{ (pageForm.dimension_names || []).join(',') }}</div>
      </el-form-item>
      <el-form-item :label="t('training.effective_data_sources')">
        <div class="content">
          {{
            pageForm.specific_ds
              ? pageForm.datasource_names.join(',')
              : t('training.all_data_sources')
          }}
        </div>
      </el-form-item>
    </el-form>
  </el-drawer>

  <!-- ========= 维度新建/编辑抽屉 ========= -->
  <el-drawer
    v-model="dimDialogVisible"
    :title="dimDialogTitle"
    destroy-on-close
    size="600px"
    :before-close="onDimClose"
    modal-class="metric-add_drawer"
  >
    <el-form
      ref="dimFormRef"
      :model="dimForm"
      label-width="180px"
      label-position="top"
      :rules="dimRules"
      class="form-content_error"
      @submit.prevent
    >
      <el-form-item prop="dimension_name" :label="t('metric.dimension_name')">
        <el-input
          v-model="dimForm.dimension_name"
          :placeholder="
            $t('datasource.please_enter') + $t('common.empty') + $t('metric.dimension_name')
          "
          autocomplete="off"
          maxlength="100"
          clearable
        />
      </el-form-item>
      <!-- ========= 【改造标记 METRIC-CENTER】↓ 问题4：维度落点三元组（数据源/表/字段，随表单提交入库） ========= -->
      <el-form-item :label="t('metric.source_datasource')">
        <el-select
          v-model="dimForm.source_ds_id"
          filterable
          clearable
          style="width: 100%"
          :placeholder="$t('datasource.Please_select')"
          @change="handleDimDsChange"
        >
          <el-option
            v-for="item in allDsList"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('metric.source_table')">
        <el-select
          v-model="dimForm.source_table"
          filterable
          allow-create
          clearable
          :loading="dimTableLoading"
          :disabled="!dimForm.source_ds_id"
          style="width: 100%"
          :placeholder="
            dimForm.source_ds_id
              ? $t('datasource.Please_select')
              : $t('metric.select_source_ds_first')
          "
          @change="handleDimTableChange"
        >
          <el-option
            v-for="item in dimTableOptions"
            :key="item.id"
            :label="item.table_name"
            :value="item.table_name"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('metric.dimension_column_name')">
        <el-select
          v-model="dimForm.column_name"
          filterable
          allow-create
          clearable
          :loading="dimFieldLoading"
          style="width: 100%"
          :placeholder="$t('metric.dimension_column_hint')"
        >
          <el-option
            v-if="
              dimForm.column_name &&
              !dimFieldOptions.some((item: any) => item.field_name === dimForm.column_name)
            "
            :label="dimForm.column_name"
            :value="dimForm.column_name"
          />
          <el-option
            v-for="item in dimFieldOptions"
            :key="item.id"
            :label="item.field_name"
            :value="item.field_name"
          />
        </el-select>
      </el-form-item>
      <!-- ========= 【改造标记 METRIC-CENTER】↑ 问题4 维度落点三元组结束 ========= -->
      <el-form-item :label="t('metric.dimension_description')">
        <el-input
          v-model="dimForm.description"
          :placeholder="$t('datasource.please_enter')"
          :autosize="{ minRows: 3, maxRows: 8 }"
          type="textarea"
        />
      </el-form-item>
      <el-form-item>
        <template #label>
          <div style="display: flex; align-items: center">
            <span>{{ t('metric.dimension_aliases') }}</span>
            <span class="btn" @click="addDimAliasItem">
              <el-icon style="margin-right: 4px" size="16">
                <icon_add_outlined></icon_add_outlined>
              </el-icon>
              {{ $t('model.add') }}
            </span>
          </div>
        </template>
        <div class="alias-list">
          <el-scrollbar>
            <div v-for="(_, index) in dimForm.aliases" :key="index" class="scrollbar-item">
              <el-input
                v-model="dimForm.aliases[index]"
                style="width: 528px"
                :placeholder="
                  $t('datasource.please_enter') +
                  $t('common.empty') +
                  $t('metric.dimension_aliases')
                "
                maxlength="100"
                clearable
              />
              <el-tooltip
                :offset="14"
                effect="dark"
                :content="$t('dashboard.delete')"
                placement="top"
              >
                <el-icon
                  class="hover-icon_with_bg"
                  size="16"
                  style="color: #646a73"
                  @click.stop="deleteDimAliasItem(index)"
                >
                  <IconOpeDelete></IconOpeDelete>
                </el-icon>
              </el-tooltip>
            </div>
          </el-scrollbar>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <div v-loading="dimUpdateLoading" class="dialog-footer">
        <el-button secondary @click="onDimClose">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" @click="saveDimHandler">{{ $t('common.save') }}</el-button>
      </div>
    </template>
  </el-drawer>

  <drawer-main
    ref="drawerMainRef"
    :filter-options="filterOption"
    @trigger-filter="searchCondition"
  />
</template>

<style lang="less" scoped>
.no-margin {
  margin: 0;
}
.metric-page {
  height: 100%;
  position: relative;

  :deep(.ed-table__cell) {
    cursor: pointer;
  }

  .tool-left {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;

    .page-title {
      font-weight: 500;
      font-size: 20px;
      line-height: 28px;
    }
  }

  .metric-tabs {
    :deep(.ed-tabs__header) {
      margin-bottom: 8px;
    }
  }

  .tool-row {
    display: flex;
    align-items: center;
    flex-direction: row;
    --gap-size: 8px;
    gap: 8px;
    margin-bottom: 16px;
  }

  .pagination-container {
    display: flex;
    justify-content: end;
    align-items: center;
    margin-top: 16px;
  }

  .table-content {
    max-height: calc(100% - 140px);
    overflow-y: auto;

    &.show-pagination_height {
      max-height: calc(100% - 200px);
    }

    .preview-or-schema {
      .field-comment_d {
        display: flex;
        align-items: center;
        min-height: 24px;
      }
      .notes-in_table {
        max-width: 100%;
        display: -webkit-box;
        max-height: 66px;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 3;
        overflow: hidden;
        text-overflow: ellipsis;
        word-break: break-word;
      }

      .field-comment {
        height: 24px;

        .ed-icon {
          position: relative;
          cursor: pointer;
          margin-top: 4px;

          &::after {
            content: '';
            background-color: #1f23291a;
            position: absolute;
            border-radius: 6px;
            width: 24px;
            height: 24px;
            transform: translate(-50%, -50%);
            top: 50%;
            left: 50%;
            display: none;
          }

          &:not(.not-allow):hover {
            &::after {
              display: block;
            }
          }
        }
        .ed-icon + .ed-icon {
          margin-left: 12px;
        }
      }
    }
  }

  .bottom-select {
    position: absolute;
    height: 64px;
    width: calc(100% + 48px);
    left: -24px;
    bottom: -16px;
    border-top: 1px solid #1f232926;
    display: flex;
    background-color: #fff;
    align-items: center;
    padding-left: 24px;
    z-index: 10;

    .danger-button {
      border: 1px solid var(--ed-color-danger);
      color: var(--ed-color-danger);
      border-radius: var(--ed-border-radius-base);
      min-width: 80px;
      height: 32px;
      line-height: 32px;
      text-align: center;
      cursor: pointer;
      margin: 0 16px;
      background-color: transparent;
    }

    .selected {
      font-weight: 400;
      font-size: 14px;
      line-height: 22px;
      color: #646a73;
      margin-right: 12px;
    }
  }
}
</style>
<style lang="less">
.metric-add_drawer {
  .ed-form-item__label {
    color: #646a73;
  }
  .ed-textarea__inner {
    line-height: 22px;
  }

  .ed-form-item__label:has(.btn) {
    padding-right: 0;
    width: 100%;
  }

  .scrollbar-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-right: 4px;
    margin-bottom: 8px;
    gap: 8px;
  }

  .dependency-item {
    justify-content: flex-start;
  }

  .alias-list {
    position: relative;
    width: 100%;
  }

  .dependency-list {
    position: relative;
    width: 100%;
  }

  .form-inline_row {
    display: flex;
    gap: 16px;

    .form-inline_item {
      flex: 1;
      min-width: 0;
    }
  }

  .normal-range {
    display: flex;
    align-items: center;
    width: 100%;
    gap: 8px;

    .ed-input-number {
      flex: 1;
      min-width: 0;
    }

    .range-sep {
      color: #646a73;
    }
  }

  .btn {
    margin-left: auto;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 4px;
    border-radius: 6px;
    margin-right: -4px;
    cursor: pointer;

    &:hover {
      background-color: #1f23291a;
    }
  }
}

.metric-detail_drawer {
  .ed-form-item--label-top .ed-form-item__label {
    margin-bottom: 4px;
  }

  .ed-form-item__label {
    color: #646a73;
  }

  .content {
    width: 100%;
    line-height: 22px;
    word-break: break-all;
  }
}
</style>
