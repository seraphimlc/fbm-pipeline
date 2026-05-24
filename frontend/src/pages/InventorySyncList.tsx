import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Modal, Popconfirm, Space, Table, Tag, Typography, message } from 'antd';
import { CloudSyncOutlined, ReloadOutlined } from '@ant-design/icons';
import { createInventorySyncBatch, getInventorySyncBatch, listInventorySyncBatches } from '../api';
import type { InventorySyncBatch, InventorySyncItem } from '../api';

const { Title, Text } = Typography;

const statusTag = (status: string) => {
  const map: Record<string, { color: string; text: string }> = {
    pending: { color: 'default', text: '等待中' },
    running: { color: 'processing', text: '同步中' },
    completed: { color: 'success', text: '完成' },
    partial: { color: 'warning', text: '部分完成' },
    failed: { color: 'error', text: '失败' },
    success: { color: 'success', text: '已同步' },
    unavailable: { color: 'warning', text: '不可售' },
    skipped: { color: 'default', text: '跳过' },
  };
  const item = map[status] || { color: 'default', text: status };
  return <Tag color={item.color}>{item.text}</Tag>;
};

const stockText = (value?: number | null) => value === null || value === undefined ? '-' : value;

const InventorySyncList: React.FC = () => {
  const [items, setItems] = useState<InventorySyncBatch[]>([]);
  const [details, setDetails] = useState<Record<number, InventorySyncItem[]>>({});
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const hasRunningBatch = useMemo(
    () => items.some((item) => item.status === 'pending' || item.status === 'running'),
    [items],
  );

  const fetchBatches = async () => {
    setLoading(true);
    try {
      const { data } = await listInventorySyncBatches({ page, page_size: pageSize });
      setItems(data.items);
      setTotal(data.total);
    } catch {
      message.error('加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchBatches(); }, [page, pageSize]);

  useEffect(() => {
    if (!hasRunningBatch) return;
    const timer = window.setInterval(fetchBatches, 5000);
    return () => window.clearInterval(timer);
  }, [hasRunningBatch, page, pageSize]);

  const createBatch = async () => {
    setCreating(true);
    try {
      const { data } = await createInventorySyncBatch();
      message.success(`已创建库存同步批次 #${data.id}`);
      setPage(1);
      await fetchBatches();
    } catch (error: any) {
      const detail = error?.response?.data?.detail || '库存同步批次创建失败';
      if (String(detail).includes('大建云仓未登录') || String(detail).includes('登录态')) {
        Modal.error({
          title: '库存同步批次未创建',
          content: detail,
        });
      } else {
        message.error(detail);
      }
    } finally {
      setCreating(false);
    }
  };

  const loadDetail = async (batch: InventorySyncBatch) => {
    if (details[batch.id]) return;
    try {
      const { data } = await getInventorySyncBatch(batch.id);
      setDetails((prev) => ({ ...prev, [batch.id]: data.items }));
    } catch {
      message.error('同步明细加载失败');
    }
  };

  const detailColumns = [
    { title: '商品资料ID', dataIndex: 'catalog_product_id', width: 110 },
    { title: '任务ID', dataIndex: 'product_id', width: 90 },
    { title: '大建商品ID', dataIndex: 'gigab2b_product_id', width: 130, render: (value: string) => value || '-' },
    { title: '商品Code', dataIndex: 'item_code', width: 140, render: (value: string) => value || '-' },
    { title: '旧库存', dataIndex: 'old_stock', width: 90, render: stockText },
    { title: '新库存', dataIndex: 'new_stock', width: 90, render: stockText },
    { title: '状态', dataIndex: 'status', width: 100, render: statusTag },
    { title: '错误信息', dataIndex: 'error_message', render: (value: string) => value || '-' },
  ];

  const columns = [
    { title: '批次ID', dataIndex: 'id', width: 90 },
    { title: '状态', dataIndex: 'status', width: 110, render: statusTag },
    { title: '总数', dataIndex: 'total_count', width: 80 },
    { title: '成功', dataIndex: 'success_count', width: 80 },
    { title: '不可售', dataIndex: 'unavailable_count', width: 80 },
    { title: '失败', dataIndex: 'failed_count', width: 80 },
    { title: '跳过', dataIndex: 'skipped_count', width: 80 },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (value: string) => value ? new Date(value).toLocaleString('zh-CN') : '-',
    },
    {
      title: '完成时间',
      dataIndex: 'finished_at',
      width: 170,
      render: (value: string) => value ? new Date(value).toLocaleString('zh-CN') : '-',
    },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      render: (value: string) => value ? <Text type="danger">{value}</Text> : '-',
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>库存同步</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchBatches}>刷新</Button>
          <Popconfirm
            title="同步全部已确认商品的库存？"
            okText="开始同步"
            cancelText="取消"
            onConfirm={createBatch}
          >
            <Button type="primary" icon={<CloudSyncOutlined />} loading={creating}>
              同步全部库存
            </Button>
          </Popconfirm>
        </Space>
      </div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="创建同步批次前会先检查大建云仓登录态；如果 Chrome 登录已失效，系统不会创建批次。"
      />
      <Table
        rowKey="id"
        dataSource={items}
        columns={columns}
        loading={loading}
        expandable={{
          onExpand: (expanded, record) => { if (expanded) loadDetail(record); },
          expandedRowRender: (record) => (
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              columns={detailColumns}
              dataSource={details[record.id] || []}
            />
          ),
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          },
        }}
      />
    </div>
  );
};

export default InventorySyncList;
