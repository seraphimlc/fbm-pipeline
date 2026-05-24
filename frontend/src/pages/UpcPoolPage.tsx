import React, { useEffect, useState } from 'react';
import { Button, Card, Col, Form, Input, Row, Select, Space, Table, Tag, Typography, message } from 'antd';
import { PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { importUpcPool, listUpcPool } from '../api';
import type { UpcPoolItem, UpcPoolSummary } from '../api';

const { Title, Text } = Typography;

const UpcPoolPage: React.FC = () => {
  const [items, setItems] = useState<UpcPoolItem[]>([]);
  const [summary, setSummary] = useState<UpcPoolSummary>({ total: 0, available: 0, bound: 0 });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<string | undefined>();
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [form] = Form.useForm<{ text: string }>();

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { data } = await listUpcPool({
        page,
        page_size: pageSize,
        status,
        q: q.trim() || undefined,
      });
      setItems(data.items);
      setSummary(data.summary);
      setTotal(data.total);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'UPC池子加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems();
  }, [page, pageSize, status, q]);

  const handleAdd = async (values: { text: string }) => {
    setSaving(true);
    try {
      const { data } = await importUpcPool(values.text);
      setSummary(data.summary);
      form.resetFields();
      message.success(`已加入 ${data.added} 个UPC${data.duplicated ? `，跳过重复 ${data.duplicated} 个` : ''}`);
      if (data.invalid.length) {
        message.warning(`有 ${data.invalid.length} 个格式不正确，已跳过`);
      }
      setPage(1);
      fetchItems();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'UPC加入失败');
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    {
      title: 'UPC',
      dataIndex: 'upc',
      width: 180,
      render: (value: string) => <Text copyable>{value}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: string) => value === 'bound' ? <Tag color="success">已绑定</Tag> : <Tag color="blue">可用</Tag>,
    },
    {
      title: '商品Code',
      dataIndex: 'bound_item_code',
      width: 160,
      render: (value: string | null) => value || '-',
    },
    {
      title: '来源商品ID',
      dataIndex: 'bound_source_product_id',
      width: 150,
      render: (value: string | null) => value || '-',
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 120,
      render: (value: string | null) => value || '-',
    },
    {
      title: '任务ID',
      dataIndex: 'product_id',
      width: 100,
      render: (value: number | null) => value ? <a href={`/products/${value}`}>{value}</a> : '-',
    },
    {
      title: '绑定时间',
      dataIndex: 'bound_at',
      width: 180,
      render: (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '-',
    },
    {
      title: '加入时间',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '-',
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, gap: 12, flexWrap: 'wrap' }}>
        <Title level={4} style={{ margin: 0 }}>UPC池子</Title>
        <Button icon={<ReloadOutlined />} onClick={fetchItems}>刷新</Button>
      </div>

      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={8}>
          <Card size="small"><Text type="secondary">全部UPC</Text><Title level={3} style={{ margin: 0 }}>{summary.total}</Title></Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small"><Text type="secondary">可用UPC</Text><Title level={3} style={{ margin: 0 }}>{summary.available}</Title></Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small"><Text type="secondary">已绑定</Text><Title level={3} style={{ margin: 0 }}>{summary.bound}</Title></Card>
        </Col>
      </Row>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Form form={form} layout="vertical" onFinish={handleAdd}>
          <Form.Item
            label="批量加入UPC"
            name="text"
            rules={[{ required: true, message: '请输入UPC' }]}
            extra="支持一次粘贴多行，也可以用空格、逗号或分号分隔。"
          >
            <Input.TextArea rows={5} placeholder="714532191586&#10;714532191593&#10;714532191609" />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={saving}>
            加入池子
          </Button>
        </Form>
      </Card>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <Select
          allowClear
          placeholder="状态"
          value={status}
          onChange={(value) => { setStatus(value); setPage(1); }}
          style={{ width: 140 }}
          options={[
            { value: 'available', label: '可用' },
            { value: 'bound', label: '已绑定' },
          ]}
        />
        <Input
          allowClear
          placeholder="搜索 UPC / 商品Code / 来源商品ID"
          value={qInput}
          onChange={(event) => setQInput(event.target.value)}
          onPressEnter={() => { setQ(qInput.trim()); setPage(1); }}
          style={{ width: 300 }}
        />
        <Button icon={<SearchOutlined />} type="primary" onClick={() => { setQ(qInput.trim()); setPage(1); }}>搜索</Button>
      </div>

      <Table
        dataSource={items}
        columns={columns}
        rowKey="id"
        loading={loading}
        scroll={{ x: 1180 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (nextPage, nextPageSize) => { setPage(nextPage); setPageSize(nextPageSize); },
        }}
      />
    </div>
  );
};

export default UpcPoolPage;
