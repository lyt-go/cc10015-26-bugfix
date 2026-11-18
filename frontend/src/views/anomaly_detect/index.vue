<template>
  <section class="page" data-module="anomaly_detect">
    <header class="page-head">
      <div>
        <h2>异常检测管理</h2>
        <p class="page-desc">维护检测规则的输入、执行约束与结果记录，为异常检测提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记检测规则</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出异常检测清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" :data-testid="`detect-${row.id}`" @click="openDetect(row)">执行检测</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无异常检测数据，可先登记检测规则</td>
        </tr>
      </tbody>
    </table>

    <header class="page-head">
      <div>
        <h3>异常检测信号表</h3>
        <p class="page-desc">每次检测的判定信号：零方差判定与规则版本同时落库，列表与详情同源。</p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="process-pending" type="button" @click="processPending">处理待办信号</button>
        <button class="btn ghost" data-testid="reload-signals" type="button" @click="loadSignals">刷新信号</button>
      </div>
    </header>

    <table class="data-table" data-testid="signal-table">
      <thead>
        <tr>
          <th v-for="column in signalColumns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="signal in signals" :key="String(signal.id)" :data-testid="`signal-${signal.id}`">
          <td v-for="column in signalColumns" :key="column">{{ formatSignalCell(signal, column) }}</td>
          <td class="row-actions">
            <button class="link" type="button" :data-testid="`signal-detail-${signal.id}`" @click="openSignalDetail(signal)">详情</button>
            <button
              v-if="signal['状态'] === '待重试'"
              class="link"
              type="button"
              :data-testid="`signal-retry-${signal.id}`"
              @click="openRetry(signal)"
            >重试</button>
          </td>
        </tr>
        <tr v-if="!signals.length">
          <td :colspan="signalColumns.length + 1" class="empty-state">暂无检测信号，可对规则执行检测</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记检测规则</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="detectRule" class="modal-backdrop" data-testid="detect-modal">
      <form class="modal" @submit.prevent="submitDetect">
        <h3>执行检测 · {{ detectRule['规则编号'] }}</h3>
        <label class="create-field">
          <span>历史监控序列（逗号分隔，最后一个为最新值）</span>
          <input v-model="detectText" data-testid="detect-values" placeholder="如 0.5,0.5,0.5,0.9" />
        </label>
        <p v-if="detectMessage" class="error-text" data-testid="detect-message">{{ detectMessage }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="closeDetect">关闭</button>
          <button class="btn primary" data-testid="submit-detect" type="submit" :disabled="detecting">
            {{ detecting ? '检测中…' : (detectMessage ? '重试检测' : '开始检测') }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="retrySignal" class="modal-backdrop" data-testid="retry-modal">
      <form class="modal" @submit.prevent="submitRetry">
        <h3>重试信号 · {{ retrySignal['信号编号'] }}</h3>
        <p class="page-desc">上次原因：{{ retrySignal['原因'] || '—' }}</p>
        <label class="create-field">
          <span>历史监控序列（逗号分隔，最后一个为最新值）</span>
          <input v-model="retryText" data-testid="retry-values" placeholder="如 0.5,0.5,0.5,0.9" />
        </label>
        <p v-if="retryMessage" class="error-text" data-testid="retry-message">{{ retryMessage }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="retrySignal = null">关闭</button>
          <button class="btn primary" data-testid="submit-retry" type="submit" :disabled="retrying">
            {{ retrying ? '重试中…' : '确认重试' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="signalDetail" class="modal-backdrop" data-testid="signal-detail-modal">
      <div class="modal">
        <h3>信号详情 · {{ signalDetail['信号编号'] }}</h3>
        <dl class="detail-list">
          <template v-for="column in signalColumns" :key="column">
            <dt>{{ column }}</dt>
            <dd :data-testid="`detail-${column}`">{{ formatSignalCell(signalDetail, column) }}</dd>
          </template>
        </dl>
        <div class="page-actions">
          <button class="btn" type="button" @click="signalDetail = null">关闭</button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条异常检测记录 · {{ signals.length }} 条检测信号</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/anomaly_detect'
const columns = ["规则编号", "监控指标", "检测算法", "基线窗口", "波动阈值", "告警级别", "静默时段", "规则版本"]
const actions = ["提交校验", "标记生效", "停用规则"]
const statuses = ["草稿", "待校验", "已生效", "已停用"]
const metricNames = ["检测规则总数", "待校验规则", "已生效规则"]
const signalColumns = ["信号编号", "规则编号", "监控指标", "规则版本", "最新值", "偏离度", "零方差", "判定", "状态", "原因", "检测时间"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const signals = ref<Row[]>([])
const signalDetail = ref<Row | null>(null)
const detectRule = ref<Row | null>(null)
const detectText = ref('')
const detectMessage = ref('')
const detecting = ref(false)
const retrySignal = ref<Row | null>(null)
const retryText = ref('')
const retryMessage = ref('')
const retrying = ref(false)
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

function formatSignalCell(signal: Row, column: string): string {
  const value = signal[column]
  if (column === '偏离度') {
    if (signal['零方差'] && (value === null || value === undefined)) return '∞'
    return value === null || value === undefined ? '—' : String(value)
  }
  if (column === '零方差') return signal['零方差'] ? '是' : '否'
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function parseValues(text: string): number[] {
  return text
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map(Number)
    .filter((num) => Number.isFinite(num))
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'anomaly_detect.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('异常检测动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '异常检测操作失败'
  }
}

function openDetect(row: Row) {
  detectRule.value = row
  detectText.value = ''
  detectMessage.value = ''
}

function closeDetect() {
  detectRule.value = null
  detectMessage.value = ''
}

async function submitDetect() {
  if (!detectRule.value) return
  detecting.value = true
  detectMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${detectRule.value.id}/detect`, {
      method: 'POST',
      body: JSON.stringify({ values: parseValues(detectText.value) }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 没有数据、失败或中断：展示原因，留待重试
      detectMessage.value = payload.message || '检测未完成，请重试'
      return
    }
    detectMessage.value = `${payload.message}（判定：${payload.verdict}）`
    await loadSignals()
  } catch (error) {
    detectMessage.value = error instanceof Error ? error.message : '检测请求失败，请重试'
  } finally {
    detecting.value = false
  }
}

function openRetry(signal: Row) {
  retrySignal.value = signal
  retryText.value = ''
  retryMessage.value = ''
}

async function submitRetry() {
  if (!retrySignal.value) return
  retrying.value = true
  retryMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/signals/${retrySignal.value.id}/retry`, {
      method: 'POST',
      body: JSON.stringify({ values: parseValues(retryText.value) }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      retryMessage.value = payload.message || '重试未完成'
      return
    }
    retryMessage.value = payload.message
    await loadSignals()
  } catch (error) {
    retryMessage.value = error instanceof Error ? error.message : '重试请求失败'
  } finally {
    retrying.value = false
  }
}

async function openSignalDetail(signal: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/signals/${signal.id}`)
    if (!response.ok) throw new Error('信号详情读取失败')
    // 详情与列表同源：直接展示接口返回的同一条记录
    signalDetail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '信号详情读取失败'
  }
}

async function processPending() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/signals/process_pending`, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '待办处理失败')
    errorMessage.value = payload.message
    await loadSignals()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '待办处理失败'
  }
}

async function loadSignals() {
  try {
    const response = await request(`${ENDPOINT}/signals?size=200`)
    if (!response.ok) throw new Error('检测信号列表读取失败')
    const payload = await response.json()
    signals.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检测信号列表读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('检测规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '异常检测列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSignals()
})
</script>

<style scoped>
.detail-list {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 6px 16px;
  margin: 12px 0;
}
.detail-list dt {
  color: var(--muted, #666);
}
.detail-list dd {
  margin: 0;
  font-weight: 500;
}
</style>
