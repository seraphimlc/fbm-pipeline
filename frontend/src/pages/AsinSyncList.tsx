import React, { useEffect, useState } from 'react';
import { Button, Space, Table, Tag, Typography, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { getAsinSyncBatch, listAsinSyncBatches } from '../api';
import type { AsinSyncBatch, AsinSyncItem } from '../api';

const { Title, Text } = Typography;

const statusTag = (status: string) => {
  const map: Record<string, { color: string; text: string }> = {
    pending: { color: 'default', text: '等待中' },
    running: { color: 'processing', text: '同步中' },
    completed: { color: 'success', text: '完成' },
    partial: { color: 'warning', text: '部分完成' },
    failed: { color: 'error', text: '失败' },
    success: { color: 'success', text: '已同步' },
    not_found: { color: 'warning', text: '未查到' },
    multiple_found: { color: 'warning', text: '多匹配' },
    skipped: { color: 'default', text: '跳过' },
  };
  const item = map[status] || { color: 'default', text: status };
  return <Tag color={item.color}>{item.text}</Tag>;
};

const AsinSyncList: React.FC = () => {
  const [items, setItems] = useState<AsinSyncBatch[]>([]);
  const [details, setDetails] = useState<Record<number, AsinSyncItem[]>>({});
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const fetchBatches = async () => {
    setLoading(true);
    try {
      const { data } = await listAsinSyncBatches({ page, page_size: pageSize });
      setItems(data.items);
      setTotal(data.total);
    } catch {
      message.error('加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchBatches(); }, [page, pageSize]);

  const loadDetail = async (batch: AsinSyncBatch) => {
    if (details[batch.id]) return;
    try {
      const { data } = await getAsinSyncBatch(batch.id);
      setDetails((prev) => ({ ...prev, [batch.id]: data.items }));
    } catch {
      message.error('同步明细加载失败');
    }
  };

  const detailColumns = [
    { title: '商品资料ID', dataIndex: 'catalog_product_id', width: 110 },
    { title: '任务ID', dataIndex: 'product_id', width: 90 },
    { title: '查询值', dataIndex: 'lookup_code', width: 150, render: (value: string) => value || '-' },
    { title: '查询类型', dataIndex: 'lookup_type', width: 100, render: (value: string) => value || '-' },
    { title: '真实ASIN', dataIndex: 'amazon_asin', width: 140, render: (value: string) => value || '-' },
    { title: '亚马逊商品状态', dataIndex: 'amazon_product_status', width: 150, render: (value: string) => value || '-' },
    { title: '状态', dataIndex: 'status', width: 100, render: statusTag },
    { title: '错误信息', dataIndex: 'error_message', render: (value: string) => value || '-' },
  ];

  const columns = [
    { title: '批次ID', dataIndex: 'id', width: 90 },
    { title: '店铺', dataIndex: 'store', width: 130 },
    { title: '状态', dataIndex: 'status', width: 110, render: statusTag },
    { title: '总数', dataIndex: 'total_count', width: 80 },
    { title: '成功', dataIndex: 'success_count', width: 80 },
    { title: '未查到/多匹配', dataIndex: 'not_found_count', width: 120 },
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
        <Title level={4} style={{ margin: 0 }}>ASIN同步记录</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchBatches}>刷新</Button>
        </Space>
      </div>
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

export default AsinSyncList;
