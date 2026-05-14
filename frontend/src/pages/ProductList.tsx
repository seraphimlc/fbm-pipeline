import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Button, Tag, Space, Typography, message, Popconfirm } from 'antd';
import { PlusOutlined, ReloadOutlined, PlayCircleOutlined, PauseOutlined, RedoOutlined, DeleteOutlined } from '@ant-design/icons';
import { listProducts, deleteProduct, startPipeline, retryStep, STEP_LABELS, STATUS_COLORS } from '../api';
import type { Product } from '../api';

const { Title } = Typography;

const ProductList: React.FC = () => {
  const navigate = useNavigate();
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const fetchProducts = async () => {
    setLoading(true);
    try {
      const { data } = await listProducts({ page, page_size: pageSize });
      setProducts(data.items);
      setTotal(data.total);
    } catch {
      message.error('加载失败');
    }
    setLoading(false);
  };

  useEffect(() => { fetchProducts(); }, [page, pageSize]);

  const getStatusTag = (status: string, step: number) => {
    if (status === 'failed') return <Tag color="error">失败</Tag>;
    if (status === 'completed') return <Tag color="success">✅ 完成</Tag>;
    if (status === 'paused') return <Tag color="warning">已暂停</Tag>;
    if (status === 'created') return <Tag>待处理</Tag>;
    const color = STATUS_COLORS[status] || 'processing';
    return <Tag color={color}>{STEP_LABELS[step] || status}</Tag>;
  };

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 60,
      render: (id: number) => <a onClick={() => navigate(`/products/${id}`)}>{id}</a>,
    },
    {
      title: '商品链接',
      dataIndex: 'gigab2b_url',
      ellipsis: true,
      render: (url: string) => <a href={url} target="_blank" rel="noreferrer">{url.split('/').pop()}</a>,
    },
    {
      title: '竞品ASIN',
      dataIndex: 'competitor_asin',
      width: 140,
      render: (v: string) => v || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (status: string, record: Product) => getStatusTag(status, record.current_step),
    },
    {
      title: '当前步骤',
      width: 100,
      render: (_: unknown, record: Product) => `${record.current_step}/9`,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      width: 200,
      render: (_: unknown, record: Product) => (
        <Space size="small">
          <Button size="small" onClick={() => navigate(`/products/${record.id}`)}>详情</Button>
          {record.status === 'created' && (
            <Button size="small" type="primary" icon={<PlayCircleOutlined />}
              onClick={async () => { await startPipeline(record.id); fetchProducts(); }}>
              启动
            </Button>
          )}
          {record.status === 'failed' && (
            <Button size="small" icon={<RedoOutlined />}
              onClick={async () => { await retryStep(record.id); fetchProducts(); }}>
              重试
            </Button>
          )}
          <Popconfirm title="确定删除？" onConfirm={async () => { await deleteProduct(record.id); fetchProducts(); }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>商品任务</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchProducts}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/products/new')}>
            创建任务
          </Button>
        </Space>
      </div>
      <Table
        dataSource={products}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }}
      />
    </div>
  );
};

export default ProductList;
