import React, { useEffect, useMemo, useState } from 'react';
import { Button, Progress, Space, Table, Tag, Typography, message } from 'antd';
import { DownloadOutlined, PauseOutlined, PlayCircleOutlined, ReloadOutlined, RedoOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { downloadOfflineTaskResult, getOfflineTask, listOfflineTasks, pauseOfflineTask, rerunOfflineTask, resumeOfflineTask } from '../api';
import type { OfflineTask, OfflineTaskDetail, OfflineTaskStep } from '../api';

const { Title, Text } = Typography;

const statusLabel = (status: string) => {
  const map: Record<string, { color: string; label: string }> = {
    pending: { color: 'default', label: '待执行' },
    running: { color: 'processing', label: '执行中' },
    done: { color: 'success', label: '已完成' },
    failed: { color: 'error', label: '失败' },
    partial_failed: { color: 'warning', label: '部分失败' },
    interrupted: { color: 'warning', label: '已中断' },
    paused: { color: 'warning', label: '已挂起' },
  };
  const item = map[status] || { color: 'default', label: status };
  return <Tag color={item.color}>{item.label}</Tag>;
};

const taskTypeLabel = (type: string) => {
  if (type === 'giga_pull') return '同步店铺商品';
  if (type === 'giga_inventory_sync') return '同步大健库存';
  if (type === 'giga_price_sync') return '同步大健价格';
  if (type === 'aplus_generate') return 'A+生成';
  if (type === 'catalog_export') return 'Amazon表格导出';
  if (type === 'product_bulk_advance') return '批量推进商品';
  return type;
};

const stepTypeLabel = (type: string) => {
  if (type === 'giga_sync') return '同步商品';
  if (type === 'giga_image_download') return '历史图片下载';
  if (type === 'giga_inventory_sync') return '库存同步';
  if (type === 'giga_price_sync') return '价格同步';
  if (type === 'aplus_generate_product') return 'A+生成';
  if (type === 'catalog_export_template') return '模板导出';
  if (type === 'product_bulk_advance_product') return '商品推进';
  return type;
};

const latestResultLabel = (value?: string | null) => {
  const map: Record<string, { color: string; label: string }> = {
    export_ready: { color: 'success', label: '已到待导出' },
    in_progress: { color: 'processing', label: '后续推进中' },
    blocked: { color: 'warning', label: '仍阻塞' },
    failed: { color: 'error', label: '后续失败' },
    paused: { color: 'warning', label: '已挂起' },
    missing: { color: 'default', label: '商品缺失' },
  };
  const item = map[value || ''] || { color: 'default', label: value || '-' };
  return <Tag color={item.color}>{item.label}</Tag>;
};

const formatTime = (value: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-';

const heartbeatSeconds = (value: string | null) => {
  if (!value) return null;
  const seconds = dayjs().diff(dayjs(value), 'second');
  return Number.isFinite(seconds) ? seconds : null;
};

const heartbeatText = (value: string | null) => {
  const seconds = heartbeatSeconds(value);
  if (seconds === null) return '无心跳';
  if (seconds < 60) return `${seconds} 秒前`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  return `${Math.floor(minutes / 60)} 小时前`;
};

const isStaleRunning = (record: Pick<OfflineTask | OfflineTaskStep, 'status' | 'updated_at'>) => (
  record.status === 'running' && (heartbeatSeconds(record.updated_at) ?? 0) >= 300
);

const phaseLabel = (phase?: string | null) => {
  const map: Record<string, string> = {
    fetching_sku_list: '读取 SKU 列表',
    filtering_existing: '过滤已存在 SKU',
    fetching_sku_details: '查询 SKU 详情',
    fetching_prices: '查询价格',
    fetching_inventory: '查询库存',
    writing_sku_snapshot: '写入 SKU 快照',
    aggregating_items: '统一聚合商品',
    materializing_product_drafts: '生成商品草稿',
    done: '完成',
  };
  return phase ? (map[phase] || phase) : '-';
};

const progressText = (record: OfflineTaskStep) => {
  const result = parseResult(record.result_json);
  if (record.step_type === 'giga_sync') {
    const scanned = Number((result as any).scanned_sku_count ?? record.progress_current ?? 0);
    const total = Number(record.progress_total || (result as any).progress_total || 0);
    return total > 0 ? `扫描 SKU ${scanned}/${total}` : `已扫描 SKU ${scanned}，总量统计中`;
  }
  if (record.step_type === 'giga_image_download' && record.progress_total > 0) {
    return `已下载 ${record.progress_current}/${record.progress_total}`;
  }
  if (['giga_inventory_sync', 'giga_price_sync'].includes(record.step_type) && record.progress_total > 0) {
    return `SKU ${record.progress_current}/${record.progress_total}`;
  }
  if (record.step_type === 'aplus_generate_product' && record.progress_total > 0) {
    const stageMap: Record<number, string> = {
      0: '等待规划',
      1: '规划完成',
      2: '脚本完成',
      3: '出图完成',
    };
    return `${stageMap[record.progress_current] || '生成中'} ${record.progress_current}/${record.progress_total}`;
  }
  if (record.step_type === 'catalog_export_template' && record.progress_total > 0) {
    return `商品 ${record.progress_current}/${record.progress_total}`;
  }
  if (record.step_type === 'product_bulk_advance_product' && record.progress_total > 0) {
    return `节点 ${record.progress_current}/${record.progress_total}`;
  }
  return record.status === 'running' ? '执行中，正在统计...' : '-';
};

const parseResult = (value: string | null) => {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const liveResult = (record: OfflineTask | OfflineTaskStep) => {
  const result = parseResult(record.result_json);
  const live = (result as any).live;
  return live && typeof live === 'object' ? { ...result, ...live } : result;
};

const resultSummary = (record: OfflineTask) => {
  const result = liveResult(record);
  if (record.task_type === 'giga_pull') {
    const scanned = Number((result as any).scanned_sku_count || 0);
    const total = Number((result as any).progress_total || 0);
    const synced = Number((result as any).synced_sku_count || 0);
    const detail = Number((result as any).detail_count || 0);
    const price = Number((result as any).price_count || 0);
    const inventory = Number((result as any).inventory_count || 0);
    const images = Number((result as any).image_url_count || 0);
    const skipped = Number((result as any).skipped_existing_count || 0);
    const failed = Number((result as any).failed_sku_count || 0);
    const currentMessage = String((result as any).current_message || '').trim();
    return (
      <Space size={4} wrap>
        {isStaleRunning(record) ? <Tag color="warning">疑似卡住</Tag> : record.status === 'running' ? <Tag color="processing">执行中</Tag> : null}
        <Tag>{phaseLabel((result as any).current_phase)}</Tag>
        <Tag color="blue">{total > 0 ? `扫描SKU ${scanned}/${total}` : `已扫描SKU ${scanned} · 总量统计中`}</Tag>
        {synced ? <Tag color="cyan">同步SKU {synced}</Tag> : null}
        {detail ? <Tag>详情 {detail}</Tag> : null}
        {price ? <Tag>价格 {price}</Tag> : null}
        {inventory ? <Tag>库存 {inventory}</Tag> : null}
        {images ? <Tag>图片URL {images}</Tag> : null}
        {skipped ? <Tag color="warning">跳过 {skipped}</Tag> : null}
        {failed ? <Tag color="error">失败 {failed}</Tag> : null}
        {currentMessage ? <Text type="secondary" ellipsis style={{ maxWidth: 260 }}>{currentMessage}</Text> : null}
        <Tag>心跳 {heartbeatText(record.updated_at)}</Tag>
      </Space>
    );
  }
  if (record.task_type === 'catalog_export' && Object.keys(result).length) {
    const exported = Number((result as any).exported_count || 0);
    const skipped = Number((result as any).skipped_count || 0);
    const report = Number((result as any).report_count || 0);
    return (
      <Space size={4} wrap>
        <Tag color="success">导出 {exported}</Tag>
        {skipped ? <Tag color="warning">跳过 {skipped}</Tag> : null}
        {report ? <Tag>报告 {report}</Tag> : null}
      </Space>
    );
  }
  if (record.task_type === 'product_bulk_advance' && Object.keys(result).length) {
    const started = Number((result as any).started_count || 0);
    const skipped = Number((result as any).skipped_count || 0);
    const rows = Array.isArray((result as any).rows) ? (result as any).rows.length : 0;
    const latestCounts = (result as any).latest_counts || {};
    const exportReady = Number((result as any).export_ready_count || latestCounts.export_ready || 0);
    const inProgress = Number(latestCounts.in_progress || 0);
    return (
      <Space size={4} wrap>
        <Tag color="success">启动 {started}</Tag>
        {exportReady ? <Tag color="success">已到待导出 {exportReady}</Tag> : null}
        {inProgress ? <Tag color="processing">后续推进中 {inProgress}</Tag> : null}
        {skipped ? <Tag color="warning">跳过 {skipped}</Tag> : null}
        {rows ? <Tag>明细 {rows}</Tag> : null}
      </Space>
    );
  }
  if (record.error_message) {
    return <Typography.Text type="danger" ellipsis style={{ maxWidth: 220 }}>{record.error_message}</Typography.Text>;
  }
  return <Text type="secondary">-</Text>;
};

const taskProgress = (record: OfflineTask) => {
  if (record.task_type === 'giga_pull') {
    const result = liveResult(record);
    const scanned = Number((result as any).scanned_sku_count || 0);
    const total = Number((result as any).progress_total || 0);
    if (total > 0) {
      const percent = Math.min(100, Math.round((scanned / total) * 100));
      return <Progress percent={percent} size="small" status={record.failed_steps ? 'exception' : undefined} />;
    }
    return (
      <Space direction="vertical" size={0} style={{ width: '100%' }}>
        <Progress percent={record.status === 'done' ? 100 : 0} size="small" showInfo={false} status="active" />
        <Text type="secondary">已扫描 {scanned}，总量统计中</Text>
      </Space>
    );
  }
  const percent = record.total_steps > 0 ? Math.round((record.success_steps / record.total_steps) * 100) : 0;
  return <Progress percent={percent} size="small" status={record.failed_steps ? 'exception' : undefined} />;
};

const resultRows = (record: OfflineTask) => {
  const result = parseResult(record.result_json);
  const rows = (result as any).rows;
  return Array.isArray(rows) ? rows : [];
};

const OfflineTaskCenter: React.FC = () => {
  const [items, setItems] = useState<OfflineTask[]>([]);
  const [details, setDetails] = useState<Record<number, OfflineTaskDetail>>({});
  const [loading, setLoading] = useState(false);
  const [rerunningId, setRerunningId] = useState<number | null>(null);
  const [pausingId, setPausingId] = useState<number | null>(null);
  const [resumingId, setResumingId] = useState<number | null>(null);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const hasActiveTask = useMemo(() => items.some((item) => ['pending', 'running'].includes(item.status)), [items]);

  const fetchTasks = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const { data } = await listOfflineTasks({ page: 1, page_size: 50 });
      setItems(data.items);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载任务中心失败');
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const fetchDetail = async (taskId: number) => {
    try {
      const { data } = await getOfflineTask(taskId);
      setDetails((prev) => ({ ...prev, [taskId]: data }));
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载任务详情失败');
    }
  };

  const rerunTask = async (taskId: number) => {
    setRerunningId(taskId);
    try {
      const { data } = await rerunOfflineTask(taskId);
      setDetails((prev) => ({ ...prev, [taskId]: data }));
      message.success(`已重跑任务 #${taskId}`);
      await fetchTasks();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '重跑失败');
    } finally {
      setRerunningId(null);
    }
  };

  const pauseTask = async (taskId: number) => {
    setPausingId(taskId);
    try {
      const { data } = await pauseOfflineTask(taskId);
      setDetails((prev) => ({ ...prev, [taskId]: data }));
      message.success(`已挂起任务 #${taskId}`);
      await fetchTasks();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '挂起失败');
    } finally {
      setPausingId(null);
    }
  };

  const resumeTask = async (taskId: number) => {
    setResumingId(taskId);
    try {
      const { data } = await resumeOfflineTask(taskId);
      setDetails((prev) => ({ ...prev, [taskId]: data }));
      message.success(`已恢复任务 #${taskId}`);
      await fetchTasks();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '恢复失败');
    } finally {
      setResumingId(null);
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

  const downloadTask = async (task: OfflineTask) => {
    setDownloadingId(task.id);
    try {
      const result = parseResult(task.result_json);
      const filename = String((result as any).filename || `catalog_export_${task.id}.zip`);
      const { data } = await downloadOfflineTaskResult(task.id);
      saveBlob(data, filename);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '下载导出文件失败');
    } finally {
      setDownloadingId(null);
    }
  };

  useEffect(() => { fetchTasks(); }, []);
  useEffect(() => {
    if (!hasActiveTask) return;
    const timer = window.setInterval(() => {
      fetchTasks(true);
      Object.keys(details).forEach((taskId) => fetchDetail(Number(taskId)));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [hasActiveTask, details]);

  const stepColumns = [
    { title: '步骤', dataIndex: 'title', width: 220 },
    { title: '类型', dataIndex: 'step_type', width: 110, render: stepTypeLabel },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (_: string, record: OfflineTaskStep) => (
        isStaleRunning(record) ? <Tag color="warning">疑似卡住</Tag> : statusLabel(record.status)
      ),
    },
    { title: '店铺', dataIndex: 'data_source_name', width: 180, render: (value: string | null) => value || '-' },
    { title: '站点', dataIndex: 'site', width: 80, render: (value: string | null) => value || '-' },
    { title: 'Batch', dataIndex: 'batch_id', ellipsis: true, render: (value: string | null) => value || '-' },
    {
      title: '进度',
      width: 160,
      render: (_: unknown, record: OfflineTaskStep) => progressText(record),
    },
    { title: '错误', dataIndex: 'error_message', ellipsis: true, render: (value: string | null) => value || '-' },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 190,
      render: (value: string | null, record: OfflineTaskStep) => (
        <Space direction="vertical" size={0}>
          <span>{formatTime(value)}</span>
          {record.status === 'running' ? <Text type={isStaleRunning(record) ? 'warning' : 'secondary'}>{heartbeatText(value)}</Text> : null}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>任务中心</Title>
          <Text type="secondary">承载店铺商品同步、库存同步、价格同步、A+生成、历史图片下载、导出等离线操作；商品工作台只负责提交和查看商品状态。</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => fetchTasks()}>刷新</Button>
      </div>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={false}
        columns={[
          { title: '任务ID', dataIndex: 'id', width: 90, render: (value: number) => `#${value}` },
          { title: '任务', dataIndex: 'title', ellipsis: true },
          { title: '类型', dataIndex: 'task_type', width: 130, render: taskTypeLabel },
          {
            title: '状态',
            dataIndex: 'status',
            width: 110,
            render: (_: string, record: OfflineTask) => (
              isStaleRunning(record) ? <Tag color="warning">疑似卡住</Tag> : statusLabel(record.status)
            ),
          },
          {
            title: '进度',
            width: 180,
            render: (_: unknown, record: OfflineTask) => taskProgress(record),
          },
          {
            title: '步骤统计',
            width: 180,
            render: (_: unknown, record: OfflineTask) => (
              <Text type="secondary">
                成功 {record.success_steps} / 失败 {record.failed_steps} / 总计 {record.total_steps}
              </Text>
            ),
          },
          {
            title: '结果',
            width: 360,
            render: (_: unknown, record: OfflineTask) => resultSummary(record),
          },
          { title: '创建时间', dataIndex: 'created_at', width: 170, render: formatTime },
          {
            title: '更新时间',
            dataIndex: 'updated_at',
            width: 190,
            render: (value: string | null, record: OfflineTask) => (
              <Space direction="vertical" size={0}>
                <span>{formatTime(value)}</span>
                {record.status === 'running' ? <Text type={isStaleRunning(record) ? 'warning' : 'secondary'}>{heartbeatText(value)}</Text> : null}
              </Space>
            ),
          },
          {
            title: '操作',
            width: 220,
            render: (_: unknown, record: OfflineTask) => {
              const canPause = ['pending', 'running'].includes(record.status);
              const canResume = record.status === 'paused';
              const canRerun = ['failed', 'partial_failed', 'interrupted'].includes(record.status);
              const canDownload = record.task_type === 'catalog_export' && ['done', 'partial_failed'].includes(record.status);
              return (
                <Space size="small">
                  {canPause && (
                    <Button
                      size="small"
                      icon={<PauseOutlined />}
                      loading={pausingId === record.id}
                      onClick={() => pauseTask(record.id)}
                    >
                      挂起
                    </Button>
                  )}
                  {canResume && (
                    <Button
                      size="small"
                      type="primary"
                      icon={<PlayCircleOutlined />}
                      loading={resumingId === record.id}
                      onClick={() => resumeTask(record.id)}
                    >
                      恢复
                    </Button>
                  )}
                  {canRerun && (
                    <Button
                      size="small"
                      icon={<RedoOutlined />}
                      loading={rerunningId === record.id}
                      onClick={() => rerunTask(record.id)}
                    >
                      重跑
                    </Button>
                  )}
                  {canDownload && (
                    <Button
                      size="small"
                      type="primary"
                      icon={<DownloadOutlined />}
                      loading={downloadingId === record.id}
                      onClick={() => downloadTask(record)}
                    >
                      下载
                    </Button>
                  )}
                </Space>
              );
            },
          },
        ]}
        expandable={{
          expandedRowRender: (record) => {
            const detail = details[record.id];
            const rows = resultRows(detail || record);
            return (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Table
                  rowKey="id"
                  size="small"
                  pagination={false}
                  columns={stepColumns}
                  dataSource={detail?.steps || []}
                  locale={{ emptyText: detail ? '暂无步骤' : '正在加载步骤...' }}
                />
                {rows.length ? (
                  <Table
                    rowKey={(row) => `${row.catalog_id || row.product_id || row.item_code}-${row.status}-${row.reason}`}
                    size="small"
                    pagination={{ pageSize: 10, size: 'small' }}
                    dataSource={rows}
                    columns={[
                      { title: '商品ID', dataIndex: 'product_id', width: 90, render: (value: number | null) => value || '-' },
                      { title: '商品资料ID', dataIndex: 'catalog_id', width: 110, render: (value: number | null) => value || '-' },
                      { title: '商品Code', dataIndex: 'item_code', width: 160, render: (value: string | null) => value || '-' },
                      { title: '状态', dataIndex: 'status', width: 110, render: (value: string) => statusLabel(value === 'started' ? 'done' : value) },
                      { title: '当前结果', dataIndex: 'latest_result', width: 130, render: latestResultLabel },
                      {
                        title: '当前状态',
                        width: 130,
                        render: (_: unknown, row: any) => row.latest_status ? `${row.latest_status} / Step ${row.latest_step ?? '-'}` : '-',
                      },
                      { title: '原因', dataIndex: 'reason', ellipsis: true, render: (value: string | null) => value || '-' },
                      { title: '当前说明', dataIndex: 'latest_reason', ellipsis: true, render: (value: string | null) => value || '-' },
                    ]}
                  />
                ) : null}
              </Space>
            );
          },
          onExpand: (expanded, record) => {
            if (expanded && !details[record.id]) fetchDetail(record.id);
          },
        }}
      />
    </div>
  );
};

export default OfflineTaskCenter;
