import React, { useEffect, useState } from 'react';
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
  return type;
};

const stepTypeLabel = (type: string) => {
  if (type === 'giga_sync') return '同步商品';
  if (type === 'giga_image_download') return '下载图片';
  if (type === 'giga_inventory_sync') return '库存同步';
  if (type === 'giga_price_sync') return '价格同步';
  if (type === 'aplus_generate_product') return 'A+生成';
  if (type === 'catalog_export_template') return '模板导出';
  return type;
};

const formatTime = (value: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-';

const progressText = (record: OfflineTaskStep) => {
  if (record.step_type === 'giga_image_download' && record.progress_total > 0) {
    return `已下载 ${record.progress_current}/${record.progress_total}`;
  }
  if (record.step_type === 'giga_sync' && record.progress_total > 0) {
    return `SKU ${record.progress_current}/${record.progress_total}`;
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

const OfflineTaskCenter: React.FC = () => {
  const [items, setItems] = useState<OfflineTask[]>([]);
  const [details, setDetails] = useState<Record<number, OfflineTaskDetail>>({});
  const [loading, setLoading] = useState(false);
  const [rerunningId, setRerunningId] = useState<number | null>(null);
  const [pausingId, setPausingId] = useState<number | null>(null);
  const [resumingId, setResumingId] = useState<number | null>(null);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const { data } = await listOfflineTasks({ page: 1, page_size: 50 });
      setItems(data.items);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载任务中心失败');
    } finally {
      setLoading(false);
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

  const stepColumns = [
    { title: '步骤', dataIndex: 'title', width: 220 },
    { title: '类型', dataIndex: 'step_type', width: 110, render: stepTypeLabel },
    { title: '状态', dataIndex: 'status', width: 100, render: statusLabel },
    { title: '店铺', dataIndex: 'data_source_name', width: 180, render: (value: string | null) => value || '-' },
    { title: '站点', dataIndex: 'site', width: 80, render: (value: string | null) => value || '-' },
    { title: 'Batch', dataIndex: 'batch_id', ellipsis: true, render: (value: string | null) => value || '-' },
    {
      title: '进度',
      width: 160,
      render: (_: unknown, record: OfflineTaskStep) => progressText(record),
    },
    { title: '错误', dataIndex: 'error_message', ellipsis: true, render: (value: string | null) => value || '-' },
    { title: '更新时间', dataIndex: 'updated_at', width: 170, render: formatTime },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>任务中心</Title>
          <Text type="secondary">承载店铺商品同步、库存同步、价格同步、A+生成、图片下载、导出等离线操作；商品工作台只负责提交和查看商品状态。</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={fetchTasks}>刷新</Button>
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
          { title: '状态', dataIndex: 'status', width: 110, render: statusLabel },
          {
            title: '进度',
            width: 180,
            render: (_: unknown, record: OfflineTask) => {
              const percent = record.total_steps > 0 ? Math.round((record.success_steps / record.total_steps) * 100) : 0;
              return <Progress percent={percent} size="small" status={record.failed_steps ? 'exception' : undefined} />;
            },
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
          { title: '创建时间', dataIndex: 'created_at', width: 170, render: formatTime },
          { title: '更新时间', dataIndex: 'updated_at', width: 170, render: formatTime },
          {
            title: '操作',
            width: 220,
            render: (_: unknown, record: OfflineTask) => {
              const canPause = ['pending', 'running'].includes(record.status);
              const canResume = record.status === 'paused';
              const canRerun = ['failed', 'partial_failed', 'interrupted'].includes(record.status);
              const canDownload = record.task_type === 'catalog_export' && record.status === 'done';
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
                  <Button
                    size="small"
                    icon={<RedoOutlined />}
                    loading={rerunningId === record.id}
                    disabled={!canRerun}
                    onClick={() => rerunTask(record.id)}
                  >
                    重跑
                  </Button>
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
            return (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                columns={stepColumns}
                dataSource={detail?.steps || []}
                locale={{ emptyText: detail ? '暂无步骤' : '正在加载步骤...' }}
              />
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
