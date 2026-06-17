import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Dropdown, Input, Modal, Progress, Select, Space, Table, Tag, Typography, message } from 'antd';
import { DownloadOutlined, MoreOutlined, ReloadOutlined, RedoOutlined, ThunderboltOutlined, WarningOutlined } from '@ant-design/icons';
import { useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import {
  cancelTaskRun,
  downloadTaskRunResult,
  getTaskRun,
  listTaskRuns,
  markTaskRunInterrupted,
  retryFailedTaskRunSteps,
  retryTaskStep,
  wakeTaskRun,
} from '../api';
import type { TaskGroup, TaskRun, TaskRunDetail, TaskStep } from '../api';

const { Title, Text } = Typography;

const statusLabel = (status: string) => {
  const map: Record<string, { color: string; label: string }> = {
    pending: { color: 'default', label: '待执行' },
    queued: { color: 'processing', label: '已入队' },
    ready: { color: 'processing', label: '待领取' },
    running: { color: 'processing', label: '执行中' },
    succeeded: { color: 'success', label: '已完成' },
    done: { color: 'success', label: '已完成' },
    failed: { color: 'error', label: '失败' },
    partial_failed: { color: 'warning', label: '部分失败' },
    interrupted: { color: 'warning', label: '已中断' },
    paused: { color: 'warning', label: '已挂起' },
    skipped: { color: 'default', label: '已跳过' },
    submitted: { color: 'processing', label: '已提交' },
  };
  const item = map[status] || { color: 'default', label: status };
  return <Tag color={item.color}>{item.label}</Tag>;
};

const displayStatusTag = (record: { display_status?: string | null; display_status_label?: string | null; status: string }) => {
  const status = record.display_status || record.status;
  const map: Record<string, string> = {
    planned: 'default',
    waiting_dependency: 'default',
    queued: 'processing',
    running: 'processing',
    stale_running: 'warning',
    failed: 'error',
    partial_failed: 'warning',
    interrupted: 'warning',
    paused: 'warning',
    cancel_requested: 'warning',
    canceled: 'default',
    superseded: 'default',
    succeeded: 'success',
  };
  return <Tag color={map[status] || 'default'}>{record.display_status_label || status}</Tag>;
};

const groupLabel = (key: string) => {
  const map: Record<string, string> = {
    plan: '规划',
    details: '详情',
    inventory: '库存',
    prices: '价格',
    finalize: '校验',
    aggregate: '聚合',
    materialize: '生成草稿',
    image_analysis: '图片分析',
    listing: 'Listing 生成',
    export_file: '导出文件',
    aplus_generate: 'A+生成',
    inventory_sync: '库存同步',
    price_sync: '价格同步',
    product_bulk_advance: '批量提交',
  };
  return map[key] || key;
};

const stepLabel = (type: string) => {
  const map: Record<string, string> = {
    giga_pull_plan: '规划 SKU',
    giga_pull_detail_chunk: 'SKU 详情',
    giga_pull_inventory_chunk: 'SKU 库存',
    giga_pull_price_chunk: 'SKU 价格',
    giga_pull_finalize_snapshot: '快照校验',
    giga_pull_aggregate_items: '聚合 Item/Group',
    giga_pull_materialize_products: '生成商品草稿',
    product_image_analysis: '图片分析',
    product_listing_generation: 'Listing 生成',
    catalog_export_template: '导出文件',
    aplus_generate_product: 'A+生成',
    giga_inventory_sync: '库存同步',
    giga_price_sync: '价格同步',
    product_bulk_advance_product: '商品推进',
  };
  return map[type] || type;
};

const taskTypeLabel = (type: string) => {
  const map: Record<string, string> = {
    giga_pull: 'GIGA 拉品',
    product_image_analysis: '图片分析',
    product_listing_generation: 'Listing 生成',
    catalog_export: '导出文件',
    aplus_generate: 'A+生成',
    giga_inventory_sync: 'GIGA 库存同步',
    giga_price_sync: 'GIGA 价格同步',
    product_bulk_advance: '批量提交生成',
  };
  return map[type] || type;
};

const formatTime = (value: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-';

const parseJson = (value: string | null) => {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const heartbeatText = (value: string | null) => {
  if (!value) return '无心跳';
  const seconds = dayjs().diff(dayjs(value), 'second');
  if (!Number.isFinite(seconds)) return '无心跳';
  if (seconds < 60) return `${seconds} 秒前`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `${minutes} 分钟前` : `${Math.floor(minutes / 60)} 小时前`;
};

const initialViewFromParams = (params: URLSearchParams): 'current' | 'history' | 'all' => {
  const value = params.get('view');
  return value === 'history' || value === 'all' ? value : 'current';
};

const UNSUPPORTED_LIST_DISPLAY_STATUSES = new Set(['stale_running', 'waiting_dependency', 'planned']);

const sanitizeDisplayStatusParam = (value: string | null) => (
  value && !UNSUPPORTED_LIST_DISPLAY_STATUSES.has(value) ? value : undefined
);

const latestResultLabel = (value?: string | null) => {
  const map: Record<string, { color: string; label: string }> = {
    export_ready: { color: 'success', label: '已到待导出' },
    image_analysis_queued: { color: 'processing', label: '图片分析已提交' },
    listing_queued: { color: 'processing', label: 'Listing 已提交' },
    in_progress: { color: 'processing', label: '后续生成中' },
    blocked: { color: 'warning', label: '仍阻塞' },
    failed: { color: 'error', label: '后续失败' },
    paused: { color: 'warning', label: '已挂起' },
    missing: { color: 'default', label: '商品缺失' },
  };
  const item = map[value || ''] || { color: 'default', label: value || '-' };
  return <Tag color={item.color}>{item.label}</Tag>;
};

const runSummary = (record: TaskRun) => {
  if (record.display_reason || record.error_summary) {
    return (
      <Text title={record.error_summary || record.display_reason || ''} ellipsis style={{ maxWidth: 400, display: 'block' }}>
        {record.error_summary || record.display_reason}
      </Text>
    );
  }
  const summary: any = parseJson(record.summary_json);
  if (!Object.keys(summary).length) return <Text type="secondary">-</Text>;
  return (
    <Space size={4} wrap>
      {summary.data_source_name ? <Tag>{summary.data_source_name}</Tag> : null}
      {summary.sku_count !== undefined ? <Tag color="blue">SKU {summary.sku_count}</Tag> : null}
      {summary.item_count !== undefined ? <Tag color="cyan">Item {summary.item_count}</Tag> : null}
      {summary.price_count !== undefined ? <Tag>价格 {summary.price_count}</Tag> : null}
      {summary.inventory_count !== undefined ? <Tag>库存 {summary.inventory_count}</Tag> : null}
      {summary.product_created !== undefined ? <Tag color="success">新建 {summary.product_created}</Tag> : null}
      {summary.product_updated !== undefined ? <Tag color="processing">更新 {summary.product_updated}</Tag> : null}
      {summary.skipped_existing_count ? <Tag color="warning">跳过历史 {summary.skipped_existing_count}</Tag> : null}
      {summary.product_id !== undefined ? <Tag color="blue">商品 #{summary.product_id}</Tag> : null}
      {summary.item_code ? <Tag>{summary.item_code}</Tag> : null}
      {summary.status === 'image_analysis_done' ? <Tag color="success">图片分析完成</Tag> : null}
      {summary.status === 'listing_done' ? <Tag color="success">Listing 完成</Tag> : null}
      {summary.status === 'aplus_done' ? <Tag color="success">A+完成</Tag> : null}
      {summary.filename ? <Tag color="blue">{summary.filename}</Tag> : null}
      {summary.success_count !== undefined ? <Tag color="success">成功 {summary.success_count}</Tag> : null}
      {summary.skipped_count !== undefined ? <Tag color="warning">跳过 {summary.skipped_count}</Tag> : null}
      {summary.failed_count !== undefined ? <Tag color="error">失败 {summary.failed_count}</Tag> : null}
      {summary.report_count !== undefined ? <Tag>报告 {summary.report_count}</Tag> : null}
      {summary.category_count !== undefined ? <Tag>{summary.category_count} 类目</Tag> : null}
      {summary.total_skus !== undefined ? <Tag color="blue">SKU {summary.success_count || 0}/{summary.total_skus}</Tag> : null}
      {summary.alert_count !== undefined ? <Tag>异动 {summary.alert_count}</Tag> : null}
      {summary.rows !== undefined ? <Tag>明细 {Array.isArray(summary.rows) ? summary.rows.length : 0}</Tag> : null}
      {summary.started_count !== undefined ? <Tag color="success">入队 {summary.started_count}</Tag> : null}
      {summary.next_step !== undefined ? <Tag color="processing">下一步 Step {summary.next_step}</Tag> : null}
    </Space>
  );
};

const groupProgress = (group: TaskGroup) => {
  const total = group.progress_total || group.steps?.length || 0;
  const current = group.progress_current || 0;
  const percent = total > 0 ? Math.round((current / total) * 100) : 0;
  return <Progress percent={group.status === 'succeeded' ? 100 : percent} size="small" status={group.status === 'failed' ? 'exception' : undefined} />;
};

const TaskRunCenter: React.FC = () => {
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState<TaskRun[]>([]);
  const [details, setDetails] = useState<Record<number, TaskRunDetail>>({});
  const [loading, setLoading] = useState(false);
  const [retryingId, setRetryingId] = useState<number | null>(null);
  const [downloadingRunId, setDownloadingRunId] = useState<number | null>(null);
  const [actingRunId, setActingRunId] = useState<number | null>(null);
  const [view, setView] = useState<'current' | 'history' | 'all'>(() => initialViewFromParams(searchParams));
  const [displayStatus, setDisplayStatus] = useState<string | undefined>(() => sanitizeDisplayStatusParam(searchParams.get('display_status')));
  const [taskType, setTaskType] = useState<string | undefined>(() => searchParams.get('task_type') || undefined);
  const [correlationKey, setCorrelationKey] = useState<string | undefined>(() => searchParams.get('correlation_key') || undefined);
  const [queryInput, setQueryInput] = useState(() => searchParams.get('q') || '');
  const [query, setQuery] = useState(() => searchParams.get('q') || '');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [baseTotal, setBaseTotal] = useState<number | null>(null);
  const [filteredTotal, setFilteredTotal] = useState<number | null>(null);
  const [isLimited, setIsLimited] = useState(false);
  const [scanLimit, setScanLimit] = useState<number | null>(null);
  const [expandedRowKeys, setExpandedRowKeys] = useState<React.Key[]>([]);
  const detailsRef = useRef<Record<number, TaskRunDetail>>({});

  const hasActiveRun = useMemo(() => items.some((item) => ['planned', 'waiting_dependency', 'queued', 'running', 'stale_running', 'cancel_requested'].includes(item.display_status || item.status)), [items]);

  const fetchRuns = useCallback(async (silent = false, targetPage = page, targetPageSize = pageSize) => {
    if (!silent) setLoading(true);
    try {
      const { data } = await listTaskRuns({
        page: targetPage,
        page_size: targetPageSize,
        view,
        display_status: displayStatus,
        task_type: taskType,
        correlation_key: correlationKey,
        q: query || undefined,
      });
      setItems(data.items);
      setTotal(data.total);
      setBaseTotal(data.base_total ?? null);
      setFilteredTotal(data.filtered_total ?? null);
      setIsLimited(Boolean(data.is_limited));
      setScanLimit(data.scan_limit ?? null);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载新任务中心失败');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [correlationKey, displayStatus, page, pageSize, query, taskType, view]);

  const fetchDetail = useCallback(async (runId: number) => {
    try {
      const { data } = await getTaskRun(runId);
      setDetails((prev) => ({ ...prev, [runId]: data }));
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载任务详情失败');
    }
  }, []);

  const retryRun = async (runId: number) => {
    setRetryingId(runId);
    try {
      const { data } = await retryFailedTaskRunSteps(runId);
      setDetails((prev) => ({ ...prev, [runId]: data }));
      message.success(`已提交失败步骤重跑：#${runId}`);
      await fetchRuns();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '重试失败步骤失败');
    } finally {
      setRetryingId(null);
    }
  };

  const wakeRun = async (runId: number) => {
    setActingRunId(runId);
    try {
      const { data } = await wakeTaskRun(runId);
      setDetails((prev) => ({ ...prev, [runId]: data }));
      message.success(`已唤醒执行器：#${runId}`);
      await fetchRuns(true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '唤醒执行器失败');
    } finally {
      setActingRunId(null);
    }
  };

  const cancelRun = async (runId: number) => {
    setActingRunId(runId);
    try {
      const { data } = await cancelTaskRun(runId, '用户取消');
      setDetails((prev) => ({ ...prev, [runId]: data }));
      message.success(`已提交取消：#${runId}`);
      await fetchRuns(true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '取消任务失败');
    } finally {
      setActingRunId(null);
    }
  };

  const markInterrupted = async (runId: number) => {
    setActingRunId(runId);
    try {
      const { data } = await markTaskRunInterrupted(runId, '人工标记中断');
      setDetails((prev) => ({ ...prev, [runId]: data }));
      message.success(`已标记中断：#${runId}`);
      await fetchRuns(true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '标记中断失败');
    } finally {
      setActingRunId(null);
    }
  };

  const goCurrentRun = async (run: TaskRun) => {
    const targetId = run.superseded_by_run_id || run.current_effective_run_id;
    if (!targetId || targetId === run.id) return;
    setPage(1);
    setView('all');
    setQueryInput(`#${targetId}`);
    setQuery(`#${targetId}`);
  };

  const retryOneStep = async (step: TaskStep) => {
    setRetryingId(step.id);
    try {
      await retryTaskStep(step.id);
      message.success(`已提交 step #${step.id} 重跑`);
      await fetchRuns(true);
      await fetchDetail(step.task_run_id);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '重跑 step 失败');
    } finally {
      setRetryingId(null);
    }
  };

  const showDetail = async (runId: number) => {
    setExpandedRowKeys((prev) => prev.includes(runId) ? prev.filter((key) => key !== runId) : [...prev, runId]);
    if (!details[runId]) await fetchDetail(runId);
  };

  const copyError = async (record: TaskRun) => {
    const text = record.error_summary || record.display_reason || record.latest_event_message || '';
    if (!text) {
      message.info('暂无可复制的错误信息');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      message.success('已复制错误信息');
    } catch {
      message.error('复制失败');
    }
  };

  const saveBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      link.remove();
    }, 1000);
  };

  const extractFilename = (disposition?: string | null, fallback = 'catalog_export.zip') => {
    const matched = disposition?.match(/filename\\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
    const raw = matched?.[1] || matched?.[2];
    if (!raw) return fallback;
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  };

  const downloadRun = async (run: TaskRun) => {
    setDownloadingRunId(run.id);
    try {
      const response = await downloadTaskRunResult(run.id);
      const summary: any = parseJson(run.summary_json);
      saveBlob(response.data, extractFilename(response.headers['content-disposition'], summary.filename || `catalog_export_run_${run.id}.zip`));
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '下载导出文件失败');
    } finally {
      setDownloadingRunId(null);
    }
  };

  const productBulkRowsTable = (record: TaskRun) => {
    const summary: any = parseJson(record.summary_json);
    const rows = Array.isArray(summary.rows) ? summary.rows : [];
    if (record.task_type !== 'product_bulk_advance' || !rows.length) return null;
    return (
      <div style={{ marginBottom: 12 }}>
        <Text strong>逐商品明细</Text>
        <Table
          rowKey={(row: any) => row.product_id}
          size="small"
          pagination={{ pageSize: 8, size: 'small' }}
          dataSource={rows}
          columns={[
            { title: '商品ID', dataIndex: 'product_id', width: 90, render: (value: number) => `#${value}` },
            { title: '商品Code', dataIndex: 'item_code', width: 150, render: (value: string | null) => value || '-' },
            { title: '状态', dataIndex: 'status', width: 110, render: statusLabel },
            { title: '子任务', dataIndex: 'latest_result', width: 140, render: latestResultLabel },
            { title: '步骤', dataIndex: 'latest_step', width: 90, render: (value: number | null, row: any) => value ?? row.current_step ?? '-' },
            { title: '原因', dataIndex: 'latest_reason', ellipsis: true, render: (value: string | null, row: any) => value || row.reason || '-' },
          ]}
        />
      </div>
    );
  };

  const resetPage = () => setPage(1);

  useEffect(() => { detailsRef.current = details; }, [details]);
  useEffect(() => { fetchRuns(); }, [fetchRuns]);
  useEffect(() => {
    if (!hasActiveRun) return;
    const timer = window.setInterval(() => {
      fetchRuns(true);
      Object.keys(detailsRef.current).forEach((runId) => fetchDetail(Number(runId)));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [fetchDetail, fetchRuns, hasActiveRun]);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>任务中心</Title>
          <Text type="secondary">展示任务框架 V1；当前承载 GIGA 拉品、库存/价格同步、图片分析、Listing、批量推进、导出文件和 A+生成。</Text>
        </div>
        <Space>
          <Select
            value={view}
            style={{ width: 120 }}
            onChange={(value) => { resetPage(); setView(value); }}
            options={[
              { value: 'current', label: '当前任务' },
              { value: 'history', label: '历史任务' },
              { value: 'all', label: '全部任务' },
            ]}
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 140 }}
            value={displayStatus}
            onChange={(value) => { resetPage(); setDisplayStatus(value); }}
            options={[
              { value: 'queued', label: '排队中' },
              { value: 'running', label: '执行中' },
              { value: 'failed', label: '失败' },
              { value: 'partial_failed', label: '部分失败' },
              { value: 'interrupted', label: '已中断' },
              { value: 'superseded', label: '已被取代' },
              { value: 'succeeded', label: '已完成' },
            ]}
          />
          <Select
            allowClear
            placeholder="任务类型"
            style={{ width: 160 }}
            value={taskType}
            onChange={(value) => { resetPage(); setTaskType(value); }}
            options={[
              { value: 'giga_pull', label: 'GIGA 拉品' },
              { value: 'product_image_analysis', label: '图片分析' },
              { value: 'product_listing_generation', label: 'Listing 生成' },
              { value: 'catalog_export', label: '导出文件' },
              { value: 'aplus_generate', label: 'A+生成' },
              { value: 'product_bulk_advance', label: '批量提交生成' },
            ]}
          />
          <Input.Search
            allowClear
            placeholder="任务ID / 标题"
            value={queryInput}
            onChange={(event) => setQueryInput(event.target.value)}
            onSearch={(value) => { resetPage(); setQuery(value.trim()); }}
            style={{ width: 180 }}
          />
          <Button icon={<ReloadOutlined />} onClick={() => fetchRuns()}>刷新</Button>
        </Space>
      </div>
      <div style={{ marginBottom: 12 }}>
        <Space size={12}>
          <Text type="secondary">当前筛选 {total} 条</Text>
          {correlationKey ? (
            <Tag closable onClose={() => { resetPage(); setCorrelationKey(undefined); }}>
              关联 {correlationKey}
            </Tag>
          ) : null}
          {baseTotal !== null && filteredTotal !== null && baseTotal !== filteredTotal ? <Text type="secondary">基础 {baseTotal} / 过滤 {filteredTotal}</Text> : null}
          {isLimited ? <Text type="warning">统计基于前 {scanLimit || 0} 条扫描结果</Text> : null}
        </Space>
      </div>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (value) => `共 ${value} 条`,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          },
        }}
        columns={[
          { title: '任务ID', dataIndex: 'id', width: 90, render: (value: number) => `#${value}` },
          { title: '对象', width: 220, render: (_: unknown, record: TaskRun) => `${record.task_type_label || taskTypeLabel(record.task_type)}${record.object_label ? ` / ${record.object_label}` : ''}` },
          { title: '任务', dataIndex: 'title', ellipsis: true },
          { title: '状态', width: 120, render: (_: unknown, record: TaskRun) => displayStatusTag(record) },
          { title: '当前步骤', dataIndex: 'current_step_label', width: 130, render: (value: string | null) => value || '-' },
          {
            title: '进度',
            width: 160,
            render: (_: unknown, record: TaskRun) => (
              <Space direction="vertical" size={0} style={{ width: 130 }}>
                <Text type="secondary">{record.progress_current ?? 0}/{record.progress_total ?? 0}</Text>
                <Progress percent={record.progress_percent || 0} size="small" showInfo={false} status={record.display_status === 'failed' ? 'exception' : undefined} />
              </Space>
            ),
          },
          { title: '摘要', width: 420, render: (_: unknown, record: TaskRun) => runSummary(record) },
          {
            title: '更新时间',
            width: 190,
            render: (_: unknown, record: TaskRun) => (
              <Space direction="vertical" size={0}>
                <Text>{formatTime(record.updated_at)}</Text>
                {record.last_heartbeat_at ? <Text type="secondary">心跳 {heartbeatText(record.last_heartbeat_at)}</Text> : null}
              </Space>
            ),
          },
          {
            title: '操作',
            width: 260,
            render: (_: unknown, record: TaskRun) => {
              const actions = record.available_actions || [];
              const moreItems = [
                actions.includes('cancel') ? { key: 'cancel', label: '取消' } : null,
                actions.includes('refresh') ? { key: 'refresh', label: '刷新' } : null,
                actions.includes('copy_error') ? { key: 'copy_error', label: '复制错误' } : null,
              ].filter(Boolean) as { key: string; label: string }[];
              const moreMenu = moreItems.length ? (
                <Dropdown
                  menu={{
                    items: moreItems,
                    onClick: ({ key }) => {
                      if (key === 'cancel') {
                        Modal.confirm({
                          title: '取消这个任务？',
                          okText: '取消任务',
                          cancelText: '关闭',
                          onOk: () => cancelRun(record.id),
                        });
                      }
                      if (key === 'refresh') fetchRuns(true);
                      if (key === 'copy_error') copyError(record);
                    },
                  }}
                >
                  <Button size="small" icon={<MoreOutlined />} />
                </Dropdown>
              ) : null;
              return (
                <Space size={4}>
                  {actions.includes('download_result') ? (
                    <Button size="small" icon={<DownloadOutlined />} loading={downloadingRunId === record.id} onClick={() => downloadRun(record)}>
                      下载
                    </Button>
                  ) : null}
                  {actions.includes('wake_runtime') ? (
                    <Button size="small" icon={<ThunderboltOutlined />} loading={actingRunId === record.id} onClick={() => wakeRun(record.id)}>
                      唤醒
                    </Button>
                  ) : null}
                  {actions.includes('retry_failed_steps') ? (
                    <Button size="small" icon={<RedoOutlined />} loading={retryingId === record.id} onClick={() => retryRun(record.id)}>
                      重试失败步骤
                    </Button>
                  ) : null}
                  {actions.includes('go_current_run') ? (
                    <Button size="small" onClick={() => goCurrentRun(record)}>当前任务</Button>
                  ) : null}
                  {actions.includes('mark_interrupted') ? (
                    <Button size="small" icon={<WarningOutlined />} loading={actingRunId === record.id} onClick={() => markInterrupted(record.id)}>
                      标记中断
                    </Button>
                  ) : null}
                  <Button size="small" onClick={() => showDetail(record.id)}>详情</Button>
                  {moreMenu}
                </Space>
              );
            },
          },
        ]}
        expandable={{
          expandedRowKeys,
          expandedRowRender: (record) => {
            const detail = details[record.id];
            return (
              <>
                {productBulkRowsTable(detail || record)}
                <Table
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={detail?.groups || []}
                  locale={{ emptyText: detail ? '暂无阶段' : '正在加载阶段...' }}
                  columns={[
                    { title: '阶段', dataIndex: 'group_key', width: 120, render: groupLabel },
                    { title: '标题', dataIndex: 'title', width: 180 },
                    { title: '状态', width: 120, render: (_: unknown, group: TaskGroup) => displayStatusTag(group as any) },
                    { title: '说明', dataIndex: 'display_reason', ellipsis: true, render: (value: string | null) => value || '-' },
                    { title: '进度', width: 180, render: (_: unknown, group: TaskGroup) => groupProgress(group) },
                    { title: '开始', dataIndex: 'started_at', width: 160, render: formatTime },
                    { title: '结束', dataIndex: 'finished_at', width: 160, render: formatTime },
                  ]}
                  expandable={{
                    expandedRowRender: (group) => (
                      <Table
                        rowKey="id"
                        size="small"
                        pagination={{ pageSize: 8, size: 'small' }}
                        dataSource={group.steps || []}
                        columns={[
                          { title: 'Step', dataIndex: 'step_key', width: 140 },
                          { title: '类型', width: 180, render: (_: unknown, step: TaskStep) => step.step_label || stepLabel(step.step_type) },
                          { title: '状态', width: 120, render: (_: unknown, step: TaskStep) => displayStatusTag(step as any) },
                          {
                            title: '进度',
                            width: 150,
                            render: (_: unknown, step: TaskStep) => step.progress_total ? `${step.progress_current}/${step.progress_total}` : '-',
                          },
                          { title: '尝试', width: 90, render: (_: unknown, step: TaskStep) => `${step.attempt_count}/${step.max_attempts}` },
                          {
                            title: '心跳',
                            dataIndex: 'heartbeat_at',
                            width: 120,
                            render: (value: string | null) => heartbeatText(value),
                          },
                          { title: '说明', ellipsis: true, render: (_: unknown, step: TaskStep) => step.error_summary || step.display_reason || '-' },
                          {
                            title: '操作',
                            width: 140,
                            render: (_: unknown, step: TaskStep) => (
                              (step.available_actions || []).includes('retry_step') ? (
                                <Button size="small" icon={<RedoOutlined />} loading={retryingId === step.id} onClick={() => retryOneStep(step)}>
                                  重试此步骤
                                </Button>
                              ) : <Text type="secondary">-</Text>
                            ),
                          },
                        ]}
                        expandable={{
                          expandedRowRender: (step) => (
                            <Table
                              rowKey="id"
                              size="small"
                              pagination={false}
                              dataSource={step.events || []}
                              columns={[
                                { title: '时间', dataIndex: 'created_at', width: 170, render: formatTime },
                                { title: '类型', dataIndex: 'event_type', width: 100 },
                                { title: '消息', dataIndex: 'message', ellipsis: true, render: (value: string | null) => value || '-' },
                                { title: '数据', dataIndex: 'data_json', ellipsis: true, render: (value: string | null) => value || '-' },
                              ]}
                            />
                          ),
                        }}
                      />
                    ),
                  }}
                />
              </>
            );
          },
          onExpand: (expanded, record) => {
            setExpandedRowKeys((prev) => expanded ? [...new Set([...prev, record.id])] : prev.filter((key) => key !== record.id));
            if (expanded && !details[record.id]) fetchDetail(record.id);
          },
        }}
      />
    </div>
  );
};

export default TaskRunCenter;
