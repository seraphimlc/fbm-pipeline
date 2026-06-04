import React, { useEffect, useState } from 'react';
import { Button, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography, message } from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  createProductDataSource,
  deleteProductDataSource,
  listProductDataSources,
  updateProductDataSource,
} from '../api';
import type { ProductDataSource } from '../api';

const { Title, Text } = Typography;

const fulfillmentLabel = (mode: string) => {
  if (mode === 'self_ship') return <Tag color="blue">自发货</Tag>;
  if (mode === 'dropship') return <Tag color="green">代发货</Tag>;
  return <Tag>{mode}</Tag>;
};

const ProductDataSourceList: React.FC = () => {
  const [items, setItems] = useState<ProductDataSource[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ProductDataSource | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { data } = await listProductDataSources({ page: 1, page_size: 200 });
      setItems(data.items);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载店铺失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchItems(); }, []);

  const openCreate = () => {
    setEditing(null);
    form.setFieldsValue({
      platform: 'giga',
      site: 'US',
      fulfillment_mode: 'dropship',
      api_base: 'https://openapi.gigab2b.com',
      enabled: true,
    });
    setModalOpen(true);
  };

  const openEdit = (record: ProductDataSource) => {
    setEditing(record);
    form.setFieldsValue({
      ...record,
      enabled: Boolean(record.enabled),
      client_secret: '',
    });
    setModalOpen(true);
  };

  const save = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const payload = {
        ...values,
        client_secret: values.client_secret?.trim() || undefined,
      };
      if (editing) {
        await updateProductDataSource(editing.id, payload);
        message.success('店铺已更新');
      } else {
        await createProductDataSource(payload);
        message.success('店铺已创建');
      }
      setModalOpen(false);
      await fetchItems();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '保存店铺失败');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (record: ProductDataSource) => {
    try {
      const { data } = await deleteProductDataSource(record.id);
      message.success(data.enabled ? '店铺已删除' : '店铺已有同步记录，已停用');
      await fetchItems();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除店铺失败');
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>店铺维护</Title>
          <Text type="secondary">维护大健云仓或其它来源店铺，商品同步时按店铺隔离 AK/SK、站点和履约方式。</Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchItems}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增店铺</Button>
        </Space>
      </div>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={false}
        columns={[
          { title: '名称', dataIndex: 'name', width: 180 },
          { title: '平台', dataIndex: 'platform', width: 90, render: (value: string) => <Tag>{value.toUpperCase()}</Tag> },
          { title: '站点', dataIndex: 'site', width: 90 },
          { title: '履约方式', dataIndex: 'fulfillment_mode', width: 110, render: fulfillmentLabel },
          { title: 'AK', dataIndex: 'client_id', ellipsis: true, render: (value: string | null) => value || '-' },
          { title: 'SK', dataIndex: 'client_secret_masked', width: 110, render: (value: string | null) => value || '-' },
          { title: '状态', dataIndex: 'enabled', width: 90, render: (value: boolean) => value ? <Tag color="success">启用</Tag> : <Tag>停用</Tag> },
          {
            title: '操作',
            width: 150,
            fixed: 'right' as const,
            render: (_: unknown, record: ProductDataSource) => (
              <Space>
                <Button size="small" onClick={() => openEdit(record)}>编辑</Button>
                <Popconfirm
                  title="删除或停用店铺？"
                  description="已有同步记录的店铺不会物理删除，只会停用。"
                  okText="确认"
                  cancelText="取消"
                  onConfirm={() => remove(record)}
                >
                  <Button size="small" danger>{record.enabled ? '停用' : '删除'}</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
        scroll={{ x: 960 }}
      />

      <Modal
        title={editing ? '编辑店铺' : '新增店铺'}
        open={modalOpen}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        onOk={save}
        onCancel={() => setModalOpen(false)}
        width={720}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item label="名称" name="name" rules={[{ required: true, message: '请输入店铺名称' }]}>
            <Input placeholder="例如：大健美国代发货" />
          </Form.Item>
          <Space style={{ width: '100%' }} size={12}>
            <Form.Item label="平台" name="platform" style={{ flex: 1 }} rules={[{ required: true }]}>
              <Select options={[{ value: 'giga', label: 'GIGA 大健云仓' }]} />
            </Form.Item>
            <Form.Item label="站点" name="site" style={{ flex: 1 }} rules={[{ required: true }]}>
              <Select options={[{ value: 'US', label: 'US' }, { value: 'JP', label: 'JP' }]} />
            </Form.Item>
          </Space>
          <Form.Item label="Open API 地址" name="api_base" rules={[{ required: true, message: '请输入 Open API 地址' }]}>
            <Input placeholder="https://openapi.gigab2b.com" />
          </Form.Item>
          <Space style={{ width: '100%' }} size={12}>
            <Form.Item label="AK / Client ID" name="client_id" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
            <Form.Item
              label={editing ? `SK / Client Secret（留空保持不变，当前 ${editing.client_secret_masked || '未配置'}）` : 'SK / Client Secret'}
              name="client_secret"
              style={{ flex: 1 }}
              rules={editing ? [] : [{ required: true, message: '请输入 SK' }]}
            >
              <Input.Password />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} size={12}>
            <Form.Item label="履约方式" name="fulfillment_mode" style={{ flex: 1 }} rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'dropship', label: '代发货' },
                  { value: 'self_ship', label: '自发货' },
                ]}
              />
            </Form.Item>
            <Form.Item label="启用" name="enabled" valuePropName="checked" style={{ width: 120 }}>
              <Switch />
            </Form.Item>
          </Space>
          <Form.Item label="备注" name="remark">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ProductDataSourceList;
