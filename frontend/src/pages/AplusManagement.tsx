import React, { useEffect, useMemo, useState } from 'react';
import { Button, Card, Drawer, Image, Input, Space, Spin, Table, Tag, Tabs, Typography, message } from 'antd';
import { EyeOutlined, ExportOutlined, PictureOutlined, RedoOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { createAplusGenerateBatch, getProduct, listCatalogProducts } from '../api';
import type { CatalogProduct, ProductDetail } from '../api';

const { Title, Text } = Typography;

const APLUS_STATUS: Record<string, { color: string; text: string }> = {
  queued: { color: 'processing', text: '排队中' },
  planning: { color: 'processing', text: '规划中' },
  scripting: { color: 'processing', text: '脚本中' },
  imaging: { color: 'processing', text: '出图中' },
  done: { color: 'success', text: '已生成' },
  failed: { color: 'error', text: '生成失败' },
  regen_queued: { color: 'processing', text: '重图排队' },
  regen_script_running: { color: 'processing', text: '重写脚本' },
  regen_image_running: { color: 'processing', text: '重新出图' },
  regen_done: { color: 'success', text: '重图完成' },
  regen_failed: { color: 'error', text: '重图失败' },
  regen_interrupted: { color: 'warning', text: '重图中断' },
};

const activeStatuses = new Set(['queued', 'planning', 'scripting', 'imaging', 'regen_queued', 'regen_script_running', 'regen_image_running']);

const parseJson = (value: string | null | undefined, fallback: any) => {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
};

const imageUrl = (item: any) => item?.display_url || item?.oss_url || item?.url || item?.provider_url || item?.path || '';

const statusTag = (status?: string | null, imageCount?: number | null) => {
  if (!status) return <Tag>未生成</Tag>;
  const item = APLUS_STATUS[status] || { color: 'default', text: status };
  return (
    <Space size={4}>
      <Tag color={item.color}>{item.text}</Tag>
      {imageCount ? <Text type="secondary">{imageCount}/5</Text> : null}
    </Space>
  );
};

const exportStatusTag = (row: CatalogProduct) => {
  if (row.exported_at || row.export_task_id || row.export_file_path) {
    return <Tag color="success">有历史导出</Tag>;
  }
  return <Tag color="blue">待导出</Tag>;
};

const AplusManagement: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<CatalogProduct[]>([]);
  const [selectedIds, setSelectedIds] = useState<React.Key[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewProduct, setPreviewProduct] = useState<ProductDetail | null>(null);
  const [itemId, setItemId] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { data } = await listCatalogProducts({
        page,
        page_size: pageSize,
        item_id: itemId.trim() || undefined,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'A+商品列表加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchItems(); }, [page, pageSize]);

  const selectedCount = selectedIds.length;
  const selectedRows = useMemo(
    () => items.filter((item) => selectedIds.includes(item.id)),
    [items, selectedIds],
  );
  const hasActiveSelected = selectedRows.some((item) => activeStatuses.has(item.aplus_status || ''));
  const previewAplus = previewProduct?.aplus || null;
  const previewPlan = parseJson(previewAplus?.aplus_plan, {});
  const previewPlanModules = Array.isArray(previewPlan?.modules) ? previewPlan.modules : [];
  const previewScriptsPayload = parseJson(previewAplus?.aplus_scripts, {});
  const previewScripts = Array.isArray(previewScriptsPayload?.scripts) ? previewScriptsPayload.scripts : [];
  const previewImages = parseJson(previewAplus?.aplus_images, []);

  const openPreview = async (row: CatalogProduct) => {
    setPreviewOpen(true);
    setPreviewLoading(true);
    setPreviewProduct(null);
    try {
      const { data } = await getProduct(row.source_product_id);
      setPreviewProduct(data);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'A+内容加载失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  const submitGenerate = async (force = false, ids = selectedIds as number[]) => {
    if (!ids.length) {
      message.warning('请先选择商品');
      return;
    }
    setSubmitting(true);
    try {
      const { data } = await createAplusGenerateBatch(ids, force);
      if (data.started) {
        message.success(`已创建任务中心任务：${data.started} 个商品生成 A+`);
      }
      if (data.errors?.length) {
        message.warning(data.errors.slice(0, 3).join('；'));
      }
      setSelectedIds([]);
      await fetchItems();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'A+生成任务创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const columns = [
    { title: '商品资料ID', dataIndex: 'id', width: 110 },
    {
      title: '商品Code',
      dataIndex: 'item_code',
      width: 150,
      render: (value: string, row: CatalogProduct) => value || row.gigab2b_product_id || '-',
    },
    {
      title: '标题',
      dataIndex: 'title',
      ellipsis: true,
      render: (value: string) => value || '-',
    },
    { title: '类目', dataIndex: 'leaf_category', width: 150, render: (value: string) => value || '-' },
    {
      title: '导出状态',
      width: 110,
      render: (_: unknown, row: CatalogProduct) => exportStatusTag(row),
    },
    {
      title: '真实 ASIN',
      dataIndex: 'amazon_asin',
      width: 130,
      render: (value: string | null) => value ? <Tag color="purple">{value}</Tag> : <Tag>未同步</Tag>,
    },
    {
      title: 'A+状态',
      width: 140,
      render: (_: unknown, row: CatalogProduct) => statusTag(row.aplus_status, row.aplus_image_count),
    },
    {
      title: 'A+上传',
      dataIndex: 'aplus_upload_status',
      width: 110,
      render: (value: string) => value ? <Tag>{value}</Tag> : <Tag>未上传</Tag>,
    },
    {
      title: '操作',
      width: 260,
      fixed: 'right' as const,
      render: (_: unknown, row: CatalogProduct) => {
        const active = activeStatuses.has(row.aplus_status || '');
        return (
          <Space size="small">
            <Button size="small" icon={<EyeOutlined />} onClick={() => openPreview(row)}>
              查看
            </Button>
            <Button
              size="small"
              type="primary"
              icon={<PictureOutlined />}
              disabled={active || row.aplus_status === 'done'}
              loading={submitting && selectedIds.includes(row.id)}
              onClick={() => submitGenerate(false, [row.id])}
            >
              生成
            </Button>
            <Button
              size="small"
              icon={<RedoOutlined />}
              disabled={active}
              onClick={() => submitGenerate(true, [row.id])}
            >
              重跑
            </Button>
            <Button
              size="small"
              icon={<ExportOutlined />}
              onClick={() => navigate(`/products/${row.source_product_id}`, { state: { from: '/aplus' } })}
            >
              详情
            </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, gap: 12 }}>
        <Title level={4} style={{ margin: 0 }}>A+管理</Title>
        <Space wrap>
          <Input.Search
            allowClear
            placeholder="商品Code"
            value={itemId}
            onChange={(event) => setItemId(event.target.value)}
            onSearch={() => { setPage(1); fetchItems(); }}
            style={{ width: 220 }}
          />
          <Button icon={<ReloadOutlined />} onClick={fetchItems}>刷新</Button>
          <Button
            type="primary"
            icon={<PictureOutlined />}
            disabled={!selectedCount || hasActiveSelected}
            loading={submitting}
            onClick={() => submitGenerate(false)}
          >
            批量生成{selectedCount ? `(${selectedCount})` : ''}
          </Button>
          <Button
            icon={<RedoOutlined />}
            disabled={!selectedCount || hasActiveSelected}
            loading={submitting}
            onClick={() => submitGenerate(true)}
          >
            强制重跑
          </Button>
        </Space>
      </div>
      <Table
        rowKey="id"
        dataSource={items}
        columns={columns}
        loading={loading}
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: setSelectedIds,
          getCheckboxProps: (record) => ({ disabled: activeStatuses.has(record.aplus_status || '') }),
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
        scroll={{ x: 1230 }}
      />
      <Drawer
        title={previewProduct ? `A+内容 · ${previewProduct.gigab2b_product_id || previewProduct.id}` : 'A+内容'}
        width={920}
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        extra={previewProduct && (
          <Button
            icon={<ExportOutlined />}
            onClick={() => navigate(`/products/${previewProduct.id}`, { state: { from: '/aplus' } })}
          >
            去商品详情
          </Button>
        )}
      >
        {previewLoading && <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />}
        {!previewLoading && (
          <Tabs
            items={[
              {
                key: 'plan',
                label: '规划',
                children: (
                  <Space direction="vertical" style={{ width: '100%' }} size={12}>
                    <Typography.Paragraph style={{ marginBottom: 0 }}>
                      {previewAplus?.aplus_plan_summary || previewPlan?.plan_summary || '暂无 A+规划'}
                    </Typography.Paragraph>
                    <Table
                      size="small"
                      rowKey={(record: any, index) => record.position || record.module_position || index}
                      dataSource={previewPlanModules}
                      pagination={false}
                      locale={{ emptyText: '暂无规划模块' }}
                      columns={[
                        { title: '模块', width: 80, render: (_: unknown, record: any, index: number) => record.position || record.module_position || index + 1 },
                        { title: '标题', dataIndex: 'headline', width: 220, render: (value: any, record: any) => value || record.module_type || '-' },
                        { title: '转化目标', dataIndex: 'conversion_goal', render: (value: any, record: any) => value || record.key_message || '-' },
                        { title: '证据来源', dataIndex: 'evidence_source', render: (value: any) => value || '-' },
                      ]}
                    />
                  </Space>
                ),
              },
              {
                key: 'script',
                label: '脚本',
                children: (
                  <Table
                    size="small"
                    rowKey={(record: any, index) => record.module_position || record.position || index}
                    dataSource={previewScripts}
                    pagination={false}
                    locale={{ emptyText: '暂无脚本' }}
                    columns={[
                      { title: '模块', width: 80, render: (_: unknown, record: any, index: number) => record.module_position || record.position || index + 1 },
                      { title: '用途', dataIndex: 'conversion_goal', width: 180, render: (value: any, record: any) => value || record.experience_angle || '-' },
                      {
                        title: 'Prompt',
                        dataIndex: 'prompt',
                        render: (value: any) => (
                          <Typography.Paragraph copyable ellipsis={{ rows: 4 }} style={{ marginBottom: 0 }}>
                            {value || '-'}
                          </Typography.Paragraph>
                        ),
                      },
                    ]}
                  />
                ),
              },
              {
                key: 'content',
                label: '内容',
                children: (
                  <Space direction="vertical" style={{ width: '100%' }} size={12}>
                    {Array.isArray(previewImages) && previewImages.length ? previewImages.map((item: any, index: number) => {
                      const url = imageUrl(item);
                      return (
                        <Card
                          key={`${item.position || index}-${url}`}
                          size="small"
                          title={`模块 ${item.position || item.module_position || index + 1}`}
                          extra={<Tag color={item.status === 'done' ? 'success' : item.status === 'failed' ? 'error' : 'default'}>{item.status || '-'}</Tag>}
                        >
                          {url ? (
                            <Image src={url} width={520} alt={`A+模块${index + 1}`} style={{ maxWidth: '100%' }} />
                          ) : (
                            <Text type="secondary">暂无图片 URL</Text>
                          )}
                          {item.error && <Typography.Paragraph type="danger" style={{ marginTop: 8 }}>{item.error}</Typography.Paragraph>}
                        </Card>
                      );
                    }) : <Text type="secondary">暂无 A+图片内容</Text>}
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Drawer>
    </div>
  );
};

export default AplusManagement;
