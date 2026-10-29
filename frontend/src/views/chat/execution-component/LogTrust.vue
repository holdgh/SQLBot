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

const status = computed(() => payload.value.status || 'skipped')
const violations = computed(() => (payload.value.violations ?? []) as Array<any>)
</script>

<template>
  <BaseContent class="base-container">
    <template v-if="item?.error">
      {{ error }}
    </template>
    <template v-else>
      <div class="row">
        <div class="inner-title">{{ t('chat.trust.status') }}</div>
        <div class="inner-value" :class="'status-' + status">
          {{ t('chat.trust.status_' + status) }}
        </div>
      </div>

      <div v-if="violations.length" class="violations">
        <div class="violations-title">{{ t('chat.trust.violation_list') }}</div>
        <div v-for="(ele, index) in violations" :key="index" class="violation-item">
          <div v-if="ele.metric_name" class="violation-row">
            <span class="violation-label">{{ t('chat.trust.metric_name') }}</span>
            <span>{{ ele.metric_name }}</span>
          </div>
          <div v-if="ele.rule_type" class="violation-row">
            <span class="violation-label">{{ t('chat.trust.rule_type') }}</span>
            <span>{{ ele.rule_type }}</span>
          </div>
          <div v-if="ele.detail" class="violation-row">
            <span class="violation-label">{{ t('chat.trust.detail') }}</span>
            <span>{{ ele.detail }}</span>
          </div>
        </div>
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
  }
}

.status-passed {
  color: #2ea121;
  font-weight: 500;
}

.status-violations {
  color: #d83931;
  font-weight: 500;
}

.status-skipped {
  color: #646a73;
  font-weight: 500;
}

.violations {
  margin-top: 8px;
  border: 1px solid #f5a623;
  border-radius: 8px;
  padding: 8px 12px;
  background: #fff8ec;

  .violations-title {
    color: #b4720e;
    font-size: 12px;
    line-height: 20px;
    font-weight: 500;
    margin-bottom: 4px;
  }

  .violation-item {
    padding: 4px 0;
    border-top: 1px solid #f5e3c0;

    &:first-of-type {
      border-top: none;
    }

    .violation-row {
      color: #1f2329;
      font-size: 13px;
      line-height: 22px;
      word-break: break-all;

      .violation-label {
        color: #646a73;
        font-size: 12px;
        margin-right: 8px;
      }
    }
  }
}
</style>
