<script setup lang="ts">
import BaseContent from './BaseContent.vue'
import { type ChatLogHistoryItem } from '@/api/chat.ts'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = withDefaults(
  defineProps<{
    item?: ChatLogHistoryItem
    error?: string
  }>(),
  {
    item: undefined,
    error: '',
  }
)

const { t } = useI18n()

const payload = computed(() => {
  const list = (props.item?.message as Array<any>) ?? []
  const entry = list.find((ele: any) => ele && ele.type === 'ai') ?? list[0]
  let content = entry?.content
  if (typeof content === 'string') {
    try {
      content = JSON.parse(content)
    } catch {
      content = undefined
    }
  }
  return content ?? {}
})

const isComputed = computed(() => payload.value.computed === true)
const reason = computed(() => payload.value.reason || '')

// reason 独有段优先，_compile 透传码回落 chat.dsl.reason（同码同文案，避免四语言重复抄）
const reasonText = computed(() => {
  const r = reason.value
  if (!r) return ''
  const key = `chat.calc.reason.${r}`
  const v = t(key)
  return v === key ? t(`chat.dsl.reason.${r}`) : v
})

const windowOf = (w: any) => (w?.start && w?.end ? `${w.start} ~ ${w.end}` : '')

const pct = (v: any) => {
  if (v === null || v === undefined) return '—'
  return `${(Number(v) * 100).toFixed(2)}%`
}

const num = (v: any) => (v === null || v === undefined ? '—' : String(v))

const dimsOf = (dims: any) => {
  if (!dims) return ''
  return Object.entries(dims)
    .map(([k, v]) => `${k}: ${v}`)
    .join('，')
}
</script>

<template>
  <BaseContent class="base-container">
    <template v-if="item?.error">
      {{ error }}
    </template>
    <template v-else>
      <div class="row">
        <div class="inner-title">{{ t('chat.calc.status') }}</div>
        <div class="inner-value" :class="isComputed ? 'ok' : 'skip'">
          {{ isComputed ? t('chat.calc.status_computed') : t('chat.calc.status_skipped') }}
        </div>
      </div>

      <div v-if="!isComputed && reason" class="row">
        <div class="inner-title">{{ t('chat.calc.reason_label') }}</div>
        <div class="inner-value">{{ reasonText }}</div>
      </div>

      <div v-if="payload.type" class="row">
        <div class="inner-title">{{ t('chat.calc.type') }}</div>
        <div class="inner-value">{{ t('chat.plan.calc.' + payload.type) }}</div>
      </div>

      <div v-if="payload.query_type" class="row">
        <div class="inner-title">{{ t('chat.plan.query_type') }}</div>
        <div class="inner-value">{{ t('chat.plan.type.' + payload.query_type) }}</div>
      </div>

      <div v-if="payload.window_current" class="row">
        <div class="inner-title">{{ t('chat.calc.window_current') }}</div>
        <div class="inner-value">{{ windowOf(payload.window_current) }}</div>
      </div>

      <div v-if="payload.window_previous" class="row">
        <div class="inner-title">{{ t('chat.calc.window_previous') }}</div>
        <div class="inner-value">{{ windowOf(payload.window_previous) }}</div>
      </div>

      <div v-if="payload.sql_previous" class="row">
        <div class="inner-title">{{ t('chat.calc.sql_previous') }}</div>
        <div class="inner-value sql">{{ payload.sql_previous }}</div>
      </div>

      <template v-if="isComputed && payload.values?.length">
        <div class="values">
          <div class="values-title">
            {{ t('chat.calc.values') }}
            <span v-if="payload.values_truncated" class="truncated">
              （{{ t('chat.calc.truncated', [payload.values.length]) }}）
            </span>
          </div>
          <div v-for="(ele, index) in payload.values" :key="index" class="value-item">
            <div class="value-dims">{{ dimsOf(ele.dims) || t('chat.calc.total') }}</div>
            <div class="value-nums">
              {{ t('chat.calc.v_current') }} {{ num(ele.current) }}
              / {{ t('chat.calc.v_previous') }} {{ num(ele.previous) }}
              / {{ t('chat.calc.v_change') }} {{ num(ele.change) }}
              / {{ t('chat.calc.v_rate') }}
              <span :class="{ zero: ele.note === 'div_zero' }">
                {{ ele.note === 'div_zero' ? t('chat.calc.div_zero') : pct(ele.rate) }}
              </span>
            </div>
          </div>
        </div>
      </template>

      <div v-if="isComputed && payload.row_count !== undefined" class="row">
        <div class="inner-title">{{ t('chat.calc.row_count') }}</div>
        <div class="inner-value">{{ payload.row_count }}</div>
      </div>
    </template>
  </BaseContent>
</template>

<style scoped lang="less">
.row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-top: 8px;

  .inner-title {
    flex: 0 0 96px;
    color: #646a73;
    font-size: 12px;
    line-height: 22px;
    font-weight: 500;
    white-space: nowrap;
  }

  .inner-value {
    flex: 1;
    color: #1f2329;
    font-size: 14px;
    line-height: 22px;
    font-weight: 400;
    word-break: break-all;
    white-space: pre-wrap;
  }
}

.ok {
  color: #2ea44f;
}

.skip {
  color: #b4720e;
}

.sql {
  font-family: monospace;
  font-size: 12px;
  background: #f5f6f7;
  border-radius: 4px;
  padding: 6px 8px;
}

.values {
  margin-top: 8px;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  padding: 8px 12px;

  .values-title {
    color: #646a73;
    font-size: 12px;
    font-weight: 500;
    line-height: 20px;
  }

  .truncated {
    font-weight: 400;
  }

  .value-item {
    margin-top: 6px;
    line-height: 20px;

    .value-dims {
      color: #1f2329;
      font-size: 13px;
      font-weight: 500;
    }

    .value-nums {
      color: #646a73;
      font-size: 12px;
      font-family: monospace;
      white-space: pre-wrap;
      word-break: break-all;

      .zero {
        color: #b4720e;
      }
    }
  }
}
</style>
