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

const isDsl = computed(() => payload.value.route === 'dsl')
const reason = computed(() => payload.value.reason || '')
const hasMismatch = computed(() => (payload.value.agg_mismatch ?? []).length > 0)
</script>

<template>
  <BaseContent class="base-container">
    <template v-if="item?.error">
      {{ error }}
    </template>
    <template v-else>
      <div class="row">
        <div class="inner-title">{{ t('chat.dsl.route') }}</div>
        <div class="inner-value">
          {{ isDsl ? t('chat.dsl.route_dsl') : t('chat.dsl.route_llm_fallback') }}
        </div>
      </div>

      <div v-if="reason" class="row">
        <div class="inner-title">{{ t('chat.dsl.fallback_reason') }}</div>
        <div class="inner-value">{{ t('chat.dsl.reason.' + reason) }}</div>
      </div>

      <template v-if="isDsl">
        <div v-if="payload.query_type" class="row">
          <div class="inner-title">{{ t('chat.plan.query_type') }}</div>
          <div class="inner-value">{{ t('chat.plan.type.' + payload.query_type) }}</div>
        </div>

        <div v-if="payload.metric" class="row">
          <div class="inner-title">{{ t('chat.plan.metrics') }}</div>
          <div class="inner-value">{{ payload.metric }}</div>
        </div>

        <div v-if="payload.dimensions?.length" class="row">
          <div class="inner-title">{{ t('chat.plan.dimensions') }}</div>
          <div class="inner-value">{{ payload.dimensions.join('、') }}</div>
        </div>

        <div v-if="payload.table" class="row">
          <div class="inner-title">{{ t('chat.dsl.table') }}</div>
          <div class="inner-value">{{ payload.table }}</div>
        </div>

        <div v-if="payload.chart_type" class="row">
          <div class="inner-title">{{ t('chat.dsl.chart_type') }}</div>
          <div class="inner-value">{{ payload.chart_type }}</div>
        </div>

        <div v-if="payload.sql" class="row">
          <div class="inner-title">{{ t('chat.dsl.sql') }}</div>
          <div class="inner-value sql">{{ payload.sql }}</div>
        </div>

        <div v-if="hasMismatch" class="mismatch">
          <div class="inner-title">{{ t('chat.dsl.agg_mismatch') }}</div>
          <div class="inner-value">
            <div v-for="(ele, index) in payload.agg_mismatch" :key="index" class="inner-item">
              {{ ele.metric }}：{{ t('chat.dsl.mismatch_plan') }} {{ ele.plan }} →
              {{ t('chat.dsl.mismatch_resolved') }} {{ ele.resolved }}
            </div>
          </div>
        </div>
      </template>
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

.inner-item {
  line-height: 22px;
}

.sql {
  font-family: monospace;
  font-size: 12px;
  background: #f5f6f7;
  border-radius: 4px;
  padding: 6px 8px;
}

.mismatch {
  margin-top: 8px;
  border: 1px solid #f5a623;
  border-radius: 8px;
  padding: 8px 12px;
  background: #fff8ec;

  .inner-title {
    color: #b4720e;
    font-size: 12px;
    line-height: 20px;
    font-weight: 500;
  }

  .inner-value {
    color: #1f2329;
    font-size: 14px;
    line-height: 22px;
    white-space: pre-wrap;
    word-break: break-all;
  }
}
</style>
