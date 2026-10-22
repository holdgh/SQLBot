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

const plan = computed(() => payload.value.plan ?? {})
const failed = computed(() => payload.value.status !== 'ok')
const hasCalculation = computed(() => {
  const calc = plan.value.calculation
  return !!calc && (calc.type !== 'none' || !!calc.expr)
})

const pct = (v: any) => `${Math.round(Number(v || 0) * 100)}%`
const fmtValue = (v: any) => (typeof v === 'string' ? v : JSON.stringify(v))
</script>

<template>
  <BaseContent class="base-container">
    <template v-if="item?.error">
      {{ error }}
    </template>
    <template v-else-if="failed">
      <div class="inner-title">{{ t('chat.plan.failed') }}</div>
      <div class="inner-text">{{ payload.error || error }}</div>
    </template>
    <template v-else>
      <div class="row">
        <div class="inner-title">{{ t('chat.plan.query_type') }}</div>
        <div class="inner-value">{{ t('chat.plan.type.' + plan.query_type) }}</div>
      </div>

      <div v-if="plan.metrics?.length" class="row">
        <div class="inner-title">{{ t('chat.plan.metrics') }}</div>
        <div class="inner-value">
          <div v-for="(ele, index) in plan.metrics" :key="index" class="inner-item">
            {{ ele.metric_name }}<span v-if="ele.aggregation" class="sub">（{{ ele.aggregation }}）</span>
          </div>
        </div>
      </div>

      <div v-if="plan.dimensions?.length" class="row">
        <div class="inner-title">{{ t('chat.plan.dimensions') }}</div>
        <div class="inner-value">{{ plan.dimensions.join('、') }}</div>
      </div>

      <div v-if="plan.filters?.length" class="row">
        <div class="inner-title">{{ t('chat.plan.filters') }}</div>
        <div class="inner-value">
          <div v-for="(ele, index) in plan.filters" :key="index" class="inner-item">
            {{ ele.field }} {{ ele.operator }} {{ fmtValue(ele.value)
            }}<span v-if="ele.logic" class="sub">（{{ ele.logic }}）</span>
          </div>
        </div>
      </div>

      <div v-if="plan.time_range" class="row">
        <div class="inner-title">{{ t('chat.plan.time_range') }}</div>
        <div class="inner-value">
          <div class="inner-item">
            {{ t('chat.plan.current') }}：{{ plan.time_range.current?.start }} ~
            {{ plan.time_range.current?.end }}
          </div>
          <div v-if="plan.time_range.previous" class="inner-item">
            {{ t('chat.plan.previous') }}：{{ plan.time_range.previous.start }} ~
            {{ plan.time_range.previous.end }}
          </div>
        </div>
      </div>

      <div v-if="hasCalculation" class="row">
        <div class="inner-title">{{ t('chat.plan.calculation') }}</div>
        <div class="inner-value">
          {{ t('chat.plan.calc.' + plan.calculation.type) }}
          <span v-if="plan.calculation.expr" class="sub">（{{ plan.calculation.expr }}）</span>
        </div>
      </div>

      <div v-if="plan.confidence" class="row">
        <div class="inner-title">{{ t('chat.plan.confidence') }}</div>
        <div class="inner-value">
          {{ pct(plan.confidence.metric_confidence) }}
          <div v-if="plan.confidence.signals" class="sub">
            {{ t('chat.plan.llm_self') }} {{ pct(plan.confidence.signals.llm_self) }} ·
            {{ t('chat.plan.recall_gap') }} {{ pct(plan.confidence.signals.recall_gap) }} ·
            {{ t('chat.plan.hit_factor') }} {{ pct(plan.confidence.signals.hit_factor) }}
          </div>
        </div>
      </div>

      <div v-if="plan.ambiguity?.need_clarification" class="ambiguity">
        <div class="inner-title">{{ t('chat.plan.need_clarification') }}</div>
        <div class="inner-value">{{ plan.ambiguity.reason }}</div>
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

.inner-item {
  line-height: 22px;
}

.inner-text {
  color: #1f2329;
  font-size: 14px;
  line-height: 22px;
  white-space: pre-wrap;
  word-break: break-all;
}

.sub {
  color: #646a73;
  font-size: 12px;
}

.ambiguity {
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
