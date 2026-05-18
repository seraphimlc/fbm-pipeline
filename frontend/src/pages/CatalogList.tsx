import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, DatePicker, Input, message, Modal, Select, Space, Table, Tag, Typography } from 'antd';
import { CloudSyncOutlined, DownloadOutlined, HistoryOutlined, PictureOutlined, ReloadOutlined, SearchOutlined, SyncOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { createAplusUploadBatch, createAsinSyncBatch, exportCatalogProducts, getWorkbenchOverview, listCatalogProducts, updateCatalogAsin } from '../api';
import type { CatalogProduct, WorkbenchOverview } from '../api';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

const CatalogList: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<CatalogProduct[]>([]);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [syncingAsin, setSyncingAsin] = useState(false);
  const [uploadingAplus, setUploadingAplus] = useState(false);
  const [asinModalOpen, setAsinModalOpen] = useState(false);
  const [asinSaving, setAsinSaving] = useState(false);
  const [asinTarget, setAsinTarget] = useState<CatalogProduct | null>(null);
  const [manualAsin, setManualAsin] = useState('');
  const [selectedIds, setSelectedIds] = useState<React.Key[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [itemIdInput, setItemIdInput] = useState('');
  const [asinInput, setAsinInput] = useState('');
  const [amazonAsinInput, setAmazonAsinInput] = useState('');
  const [asinSyncStatusInput, setAsinSyncStatusInput] = useState<string | undefined>();
  const [aplusUploadStatusInput, setAplusUploadStatusInput] = useState<string | undefined>();
  const [stockSyncStatusInput, setStockSyncStatusInput] = useState<string | undefined>();
  const [templateRiskInput, setTemplateRiskInput] = useState<string | undefined>();
  const [upcInput, setUpcInput] = useState('');
  const [categoryInput, setCategoryInput] = useState('');
  const [dateRangeInput, setDateRangeInput] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [stockSyncedRangeInput, setStockSyncedRangeInput] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [filters, setFilters] = useState<{
    item_id?: string;
    competitor_asin?: string;
    amazon_asin?: string;
    asin_sync_status?: string;
    aplus_upload_status?: string;
    stock_sync_status?: string;
    template_risk_level?: string;
    upc?: string;
    category?: string;
    imported_from?: string;
    imported_to?: string;
    stock_synced_from?: string;
    stock_synced_to?: string;
  }>({});
  const [overview, setOverview] = useState<WorkbenchOverview | null>(null);

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { data } = await listCatalogProducts({
        page,
        page_size: pageSize,
        ...filters,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch {
      message.error('加载失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchOverview = async () => {
    try {
      const { data } = await getWorkbenchOverview();
      setOverview(data);
    } catch {
      // 概览失败不影响商品列表。
    }
  };

  useEffect(() => { fetchItems(); }, [page, pageSize, filters]);
  useEffect(() => { fetchOverview(); }, []);

  const search = () => {
    setFilters({
      item_id: itemIdInput.trim() || undefined,
      competitor_asin: asinInput.trim() || undefined,
      amazon_asin: amazonAsinInput.trim() || undefined,
      asin_sync_status: asinSyncStatusInput,
      aplus_upload_status: aplusUploadStatusInput,
      stock_sync_status: stockSyncStatusInput,
      template_risk_level: templateRiskInput,
      upc: upcInput.trim() || undefined,
      category: categoryInput.trim() || undefined,
      imported_from: dateRangeInput?.[0].startOf('day').toISOString(),
      imported_to: dateRangeInput?.[1].endOf('day').toISOString(),
      stock_synced_from: stockSyncedRangeInput?.[0].startOf('day').toISOString(),
      stock_synced_to: stockSyncedRangeInput?.[1].endOf('day').toISOString(),
    });
    setPage(1);
  };

  const reset = () => {
    setItemIdInput('');
    setAsinInput('');
    setAmazonAsinInput('');
    setAsinSyncStatusInput(undefined);
    setAplusUploadStatusInput(undefined);
    setStockSyncStatusInput(undefined);
    setTemplateRiskInput(undefined);
    setUpcInput('');
    setCategoryInput('');
    setDateRangeInput(null);
    setStockSyncedRangeInput(null);
    setFilters({});
    setPage(1);
  };

  const saveBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  const exportSelected = async () => {
    if (!selectedIds.length) {
      message.warning('请先选择商品');
      return;
    }
    const selectedSet = new Set(selectedIds.map(Number));
    const blocked = items.filter((item) => selectedSet.has(item.id) && item.amazon_asin);
    if (blocked.length) {
      message.warning(`已有关联真实 ASIN 的商品不能导出：${blocked.map((item) => item.item_code || item.id).slice(0, 5).join('、')}`);
      return;
    }
    setExporting(true);
    try {
      const { data } = await exportCatalogProducts(selectedIds.map(Number));
      saveBlob(data, `amazon_import_templates_${dayjs().format('YYYYMMDD_HHmmss')}.zip`);
      message.success('已导出 Amazon 导入表格压缩包');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '导出失败');
    } finally {
      setExporting(false);
    }
  };

  const syncSelectedAsins = async () => {
    if (!selectedIds.length) {
      message.warning('请先选择商品');
      return;
    }
    try {
      setSyncingAsin(true);
      const { data } = await createAsinSyncBatch(selectedIds.map(Number));
      message.success(`已创建 ASIN 同步批次 #${data.id}`);
      setSelectedIds([]);
      fetchItems();
      fetchOverview();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'ASIN 同步批次创建失败');
    } finally {
      setSyncingAsin(false);
    }
  };

  const asinStatusTag = (status?: string | null, asin?: string | null) => {
    if (asin && status === 'manual_linked') return <Tag color="success">手动关联</Tag>;
    if (asin) return <Tag color="success">已同步</Tag>;
    if (status === 'pending' || status === 'running') return <Tag color="processing">同步中</Tag>;
    if (status === 'not_found') return <Tag color="warning">未查到</Tag>;
    if (status === 'multiple_found') return <Tag color="warning">多匹配</Tag>;
    if (status === 'failed') return <Tag color="error">失败</Tag>;
    if (status === 'manual_linked') return <Tag color="success">手动关联</Tag>;
    if (status === 'skipped') return <Tag>跳过</Tag>;
    return <Tag>未同步</Tag>;
  };

  const aplusStatusTag = (status?: string | null) => {
    if (status === 'pending' || status === 'running') return <Tag color="processing">上传中</Tag>;
    if (status === 'submitted') return <Tag color="success">已提交</Tag>;
    if (status === 'draft_saved') return <Tag color="success">已保存草稿</Tag>;
    if (status === 'failed') return <Tag color="error">失败</Tag>;
    if (status === 'skipped') return <Tag>跳过</Tag>;
    return <Tag>未上传</Tag>;
  };

  const stockStatusTag = (status?: string | null, error?: string | null) => {
    const content = (() => {
      if (status === 'pending' || status === 'running') return <Tag color="processing">同步中</Tag>;
      if (status === 'synced') return <Tag color="success">已同步</Tag>;
      if (status === 'unavailable') return <Tag color="warning">不可售</Tag>;
      if (status === 'failed') return <Tag color="error">失败</Tag>;
      if (status === 'skipped') return <Tag>跳过</Tag>;
      return <Tag>未同步</Tag>;
    })();
    return (
      <Space direction="vertical" size={2}>
        {content}
        {error && <Text type="secondary" ellipsis style={{ maxWidth: 150 }}>{error}</Text>}
      </Space>
    );
  };

  const riskTag = (risk?: string | null, count?: number | null) => {
    const suffix = count ? ` · ${count}条` : '';
    if (risk === 'pass') return <Tag color="success">可复核{suffix}</Tag>;
    if (risk === 'warning') return <Tag color="warning">需复核{suffix}</Tag>;
    if (risk === 'high_risk') return <Tag color="error">高风险{suffix}</Tag>;
    return <Tag>未检查</Tag>;
  };

  const nextAction = (record: CatalogProduct) => {
    if (!record.amazon_asin) {
      if (record.asin_sync_status === 'not_found') return <Tag color="warning">人工确认 ASIN</Tag>;
      if (record.asin_sync_status === 'multiple_found') return <Tag color="warning">人工处理多匹配</Tag>;
      if (record.asin_sync_status === 'pending' || record.asin_sync_status === 'running') return <Tag color="processing">等待 ASIN 同步</Tag>;
      return <Tag color="blue">同步 ASIN</Tag>;
    }
    if (record.template_risk_level === 'high_risk') return <Tag color="error">复核上架风险</Tag>;
    if (!record.aplus_upload_status || record.aplus_upload_status === 'not_uploaded') return <Tag color="blue">上传 A+</Tag>;
    if (record.aplus_upload_status === 'failed') return <Tag color="error">查看 A+ 失败</Tag>;
    if (record.aplus_upload_status === 'pending' || record.aplus_upload_status === 'running') return <Tag color="processing">等待 A+ 上传</Tag>;
    return <Tag color="success">可持续运营</Tag>;
  };

  const applyQuickFilter = (nextFilters: typeof filters) => {
    setFilters(nextFilters);
    setPage(1);
  };

  const uploadSelectedAplus = async () => {
    if (!selectedIds.length) {
      message.warning('请先选择商品');
      return;
    }
    setUploadingAplus(true);
    try {
      const { data } = await createAplusUploadBatch(selectedIds.map(Number));
      message.success(`已创建 A+ 上传批次 #${data.id}`);
      setSelectedIds([]);
      fetchItems();
      fetchOverview();
      navigate('/aplus-upload');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'A+ 上传批次创建失败');
    } finally {
      setUploadingAplus(false);
    }
  };

  const openAsinModal = (record: CatalogProduct) => {
    setAsinTarget(record);
    setManualAsin(record.amazon_asin || '');
    setAsinModalOpen(true);
  };

  const saveManualAsin = async () => {
    if (!asinTarget) return;
    const asin = manualAsin.trim().toUpperCase();
    if (!/^B0[A-Z0-9]{8}$/.test(asin)) {
      message.warning('ASIN 格式不正确，应为 B0 开头的 10 位编码');
      return;
    }
    setAsinSaving(true);
    try {
      await updateCatalogAsin(asinTarget.id, asin);
      message.success('真实 ASIN 已更新');
      setAsinModalOpen(false);
      setAsinTarget(null);
      setManualAsin('');
      fetchItems();
      fetchOverview();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更新 ASIN 失败');
    } finally {
      setAsinSaving(false);
    }
  };

  const columns = [
    {
      title: '商品资料ID',
      dataIndex: 'id',
      width: 110,
    },
    {
      title: '任务ID',
      dataIndex: 'source_product_id',
      width: 90,
      render: (id: number) => <a onClick={() => navigate(`/products/${id}`)}>{id}</a>,
    },
    {
      title: '来源商品ID',
      dataIndex: 'gigab2b_product_id',
      width: 130,
      render: (value: string, record: CatalogProduct) => (record.source_item_id || value) ? <a onClick={() => navigate(`/products/${record.source_product_id}`)}>{record.source_item_id || value}</a> : '-',
    },
    {
      title: '商品Code',
      dataIndex: 'item_code',
      width: 140,
      render: (value: string) => value || '-',
    },
    {
      title: '运营库存',
      dataIndex: 'stock',
      width: 100,
      render: (value: number | null) => value === null || value === undefined ? '-' : value,
    },
    {
      title: '标题',
      dataIndex: 'title',
      ellipsis: true,
      render: (value: string) => value || '-',
    },
    {
      title: '类目',
      dataIndex: 'leaf_category',
      width: 180,
      render: (value: string) => value ? <Tag>{value}</Tag> : '-',
    },
    {
      title: '竞品ASIN',
      dataIndex: 'competitor_asin',
      width: 140,
      render: (value: string) => value || '-',
    },
    {
      title: '真实ASIN',
      dataIndex: 'amazon_asin',
      width: 140,
      render: (value: string) => value || '-',
    },
    {
      title: 'ASIN同步',
      dataIndex: 'asin_sync_status',
      width: 120,
      render: (value: string, record: CatalogProduct) => asinStatusTag(value, record.amazon_asin),
    },
    {
      title: 'A+上传',
      dataIndex: 'aplus_upload_status',
      width: 120,
      render: (value: string, record: CatalogProduct) => (
        <Space direction="vertical" size={2}>
          {aplusStatusTag(value)}
          {record.aplus_upload_error && <Text type="secondary" ellipsis style={{ maxWidth: 150 }}>{record.aplus_upload_error}</Text>}
        </Space>
      ),
    },
    {
      title: '库存同步',
      dataIndex: 'stock_sync_status',
      width: 120,
      render: (value: string, record: CatalogProduct) => stockStatusTag(value, record.stock_sync_error),
    },
    {
      title: '库存同步时间',
      dataIndex: 'stock_synced_at',
      width: 170,
      render: (value: string) => value ? new Date(value).toLocaleString('zh-CN') : '-',
    },
    {
      title: '上架检查',
      dataIndex: 'template_risk_level',
      width: 130,
      render: (value: string, record: CatalogProduct) => riskTag(value, record.template_warnings_count),
    },
    {
      title: '下一步',
      width: 150,
      render: (_: unknown, record: CatalogProduct) => nextAction(record),
    },
    {
      title: 'UPC',
      dataIndex: 'upc',
      width: 150,
      render: (value: string) => value || '-',
    },
    {
      title: '导入时间',
      dataIndex: 'imported_at',
      width: 170,
      render: (value: string) => value ? new Date(value).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      width: 190,
      render: (_: unknown, record: CatalogProduct) => (
        <Space size="small">
          <Button size="small" onClick={() => navigate(`/products/${record.source_product_id}`)}>详情</Button>
          <Button size="small" onClick={() => openAsinModal(record)}>
            {record.amazon_asin ? '重新关联ASIN' : '关联ASIN'}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>商品列表</Title>
        <Space>
          <Text type="secondary">最多显示 1000 个商品</Text>
          <Button icon={<ReloadOutlined />} onClick={fetchItems}>刷新</Button>
          <Button icon={<CloudSyncOutlined />} onClick={() => navigate('/inventory-sync')}>库存同步</Button>
          <Button icon={<HistoryOutlined />} onClick={() => navigate('/asin-sync')}>同步记录</Button>
          <Button icon={<SyncOutlined />} loading={syncingAsin} disabled={!selectedIds.length} onClick={syncSelectedAsins}>
            同步ASIN{selectedIds.length ? `(${selectedIds.length})` : ''}
          </Button>
          <Button icon={<PictureOutlined />} loading={uploadingAplus} disabled={!selectedIds.length} onClick={uploadSelectedAplus}>
            上传A+{selectedIds.length ? `(${selectedIds.length})` : ''}
          </Button>
          <Button type="primary" icon={<DownloadOutlined />} loading={exporting} disabled={!selectedIds.length} onClick={exportSelected}>
            导出Amazon表格{selectedIds.length ? `(${selectedIds.length})` : ''}
          </Button>
        </Space>
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <Button size="small" onClick={() => applyQuickFilter({})}>全部商品</Button>
        <Button size="small" onClick={() => applyQuickFilter({ asin_sync_status: 'not_synced' })}>
          可同步ASIN{overview ? `(${overview.asin_not_synced})` : ''}
        </Button>
        <Button size="small" onClick={() => applyQuickFilter({ asin_sync_status: 'not_found' })}>ASIN未查到</Button>
        <Button size="small" onClick={() => applyQuickFilter({ asin_sync_status: 'multiple_found' })}>ASIN多匹配</Button>
        <Button size="small" onClick={() => applyQuickFilter({ aplus_upload_status: 'not_uploaded' })}>可上传A+</Button>
        <Button size="small" onClick={() => applyQuickFilter({ aplus_upload_status: 'failed' })}>
          A+失败{overview ? `(${overview.aplus_failed})` : ''}
        </Button>
        <Button size="small" onClick={() => applyQuickFilter({ stock_sync_status: 'not_synced' })}>库存未同步</Button>
        <Button size="small" onClick={() => applyQuickFilter({ stock_sync_status: 'failed' })}>库存同步失败</Button>
        <Button size="small" onClick={() => applyQuickFilter({ template_risk_level: 'high_risk' })}>
          上架高风险{overview ? `(${overview.listing_high_risk})` : ''}
        </Button>
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <Input
          allowClear
          placeholder="搜索商品ID / Code"
          value={itemIdInput}
          onChange={(event) => setItemIdInput(event.target.value)}
          onPressEnter={search}
          style={{ width: 220 }}
        />
        <Input
          allowClear
          placeholder="搜索竞品 ASIN"
          value={asinInput}
          onChange={(event) => setAsinInput(event.target.value)}
          onPressEnter={search}
          style={{ width: 180 }}
        />
        <Input
          allowClear
          placeholder="搜索真实 ASIN"
          value={amazonAsinInput}
          onChange={(event) => setAmazonAsinInput(event.target.value)}
          onPressEnter={search}
          style={{ width: 180 }}
        />
        <Select
          allowClear
          placeholder="是否同步 ASIN"
          value={asinSyncStatusInput}
          onChange={setAsinSyncStatusInput}
          style={{ width: 170 }}
          options={[
            { value: 'synced', label: '已同步' },
            { value: 'not_synced', label: '未同步' },
            { value: 'manual_linked', label: '手动关联' },
            { value: 'not_found', label: '未查到' },
            { value: 'multiple_found', label: '多匹配' },
            { value: 'failed', label: '失败' },
          ]}
        />
        <Select
          allowClear
          placeholder="A+上传状态"
          value={aplusUploadStatusInput}
          onChange={setAplusUploadStatusInput}
          style={{ width: 170 }}
          options={[
            { value: 'not_uploaded', label: '未上传' },
            { value: 'pending', label: '等待上传' },
            { value: 'running', label: '上传中' },
            { value: 'submitted', label: '已提交' },
            { value: 'draft_saved', label: '已保存草稿' },
            { value: 'failed', label: '失败' },
            { value: 'skipped', label: '跳过' },
          ]}
        />
        <Select
          allowClear
          placeholder="库存同步状态"
          value={stockSyncStatusInput}
          onChange={setStockSyncStatusInput}
          style={{ width: 170 }}
          options={[
            { value: 'synced', label: '已同步' },
            { value: 'not_synced', label: '未同步' },
            { value: 'pending', label: '等待同步' },
            { value: 'running', label: '同步中' },
            { value: 'unavailable', label: '不可售' },
            { value: 'failed', label: '失败' },
            { value: 'skipped', label: '跳过' },
          ]}
        />
        <Select
          allowClear
          placeholder="上架检查"
          value={templateRiskInput}
          onChange={setTemplateRiskInput}
          style={{ width: 150 }}
          options={[
            { value: 'pass', label: '可复核' },
            { value: 'warning', label: '需复核' },
            { value: 'high_risk', label: '高风险' },
          ]}
        />
        <Input
          allowClear
          placeholder="搜索 UPC"
          value={upcInput}
          onChange={(event) => setUpcInput(event.target.value)}
          onPressEnter={search}
          style={{ width: 180 }}
        />
        <Input
          allowClear
          placeholder="搜索类目"
          value={categoryInput}
          onChange={(event) => setCategoryInput(event.target.value)}
          onPressEnter={search}
          style={{ width: 180 }}
        />
        <RangePicker
          placeholder={['导入开始', '导入结束']}
          value={dateRangeInput}
          onChange={(value) => setDateRangeInput(value as [dayjs.Dayjs, dayjs.Dayjs] | null)}
          style={{ width: 260 }}
        />
        <RangePicker
          placeholder={['库存同步开始', '库存同步结束']}
          value={stockSyncedRangeInput}
          onChange={(value) => setStockSyncedRangeInput(value as [dayjs.Dayjs, dayjs.Dayjs] | null)}
          style={{ width: 300 }}
        />
        <Button icon={<SearchOutlined />} type="primary" onClick={search}>搜索</Button>
        <Button onClick={reset}>重置</Button>
      </div>
      <Table
        dataSource={items}
        columns={columns}
        rowKey="id"
        loading={loading}
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: setSelectedIds,
          preserveSelectedRowKeys: true,
          getCheckboxProps: (record) => ({
            disabled: Boolean(record.amazon_asin),
          }),
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: [20, 50, 100, 500, 1000],
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(Math.min(nextPageSize, 1000));
          },
        }}
      />
      <Modal
        title={asinTarget?.amazon_asin ? '重新关联真实 ASIN' : '关联真实 ASIN'}
        open={asinModalOpen}
        okText="保存 ASIN"
        cancelText="取消"
        confirmLoading={asinSaving}
        onOk={saveManualAsin}
        onCancel={() => {
          if (!asinSaving) {
            setAsinModalOpen(false);
            setAsinTarget(null);
            setManualAsin('');
          }
        }}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text type="secondary">
            这会直接替换真实 ASIN，不会创建同步任务。已有真实 ASIN 的商品不会再参与 Amazon 导入表格导出。
          </Text>
          <Input
            value={manualAsin}
            onChange={(event) => setManualAsin(event.target.value.toUpperCase())}
            placeholder="B0XXXXXXXX"
            maxLength={10}
          />
        </Space>
      </Modal>
    </div>
  );
};

export default CatalogList;
