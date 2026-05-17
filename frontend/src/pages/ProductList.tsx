import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Table, Button, Tag, Space, Typography, message, Popconfirm, Input, Modal, Upload, DatePicker, Checkbox, Select } from 'antd';
import { PlusOutlined, ReloadOutlined, PlayCircleOutlined, RedoOutlined, DeleteOutlined, SearchOutlined, UploadOutlined, DownloadOutlined, CheckOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { listProducts, deleteProduct, startPipeline, restartPipeline, retryStep, resumePipeline, confirmProduct, STEP_LABELS, STATUS_COLORS, importProducts, downloadImportTemplate, bulkStartPipelines, getWorkbenchOverview } from '../api';
import type { Product, WorkbenchOverview } from '../api';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;
const PRODUCT_LIST_RETURN_KEY = 'fbm.productList.returnPath';

const positiveIntParam = (value: string | null, fallback: number) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

const parseDateRangeParams = (search: URLSearchParams) => {
  const createdFrom = search.get('created_from');
  const createdTo = search.get('created_to');
  if (!createdFrom || !createdTo) return null;
  const from = dayjs(createdFrom);
  const to = dayjs(createdTo);
  return from.isValid() && to.isValid() ? [from, to] as [dayjs.Dayjs, dayjs.Dayjs] : null;
};

const ProductList: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const initialSearch = new URLSearchParams(location.search);
  const initialDateRange = parseDateRangeParams(initialSearch);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(positiveIntParam(initialSearch.get('page'), 1));
  const [pageSize, setPageSize] = useState(positiveIntParam(initialSearch.get('page_size'), 20));
  const [itemIdInput, setItemIdInput] = useState(initialSearch.get('item_id') || '');
  const [competitorAsinInput, setCompetitorAsinInput] = useState(initialSearch.get('competitor_asin') || '');
  const [upcInput, setUpcInput] = useState(initialSearch.get('upc') || '');
  const [itemId, setItemId] = useState(initialSearch.get('item_id') || '');
  const [competitorAsin, setCompetitorAsin] = useState(initialSearch.get('competitor_asin') || '');
  const [upc, setUpc] = useState(initialSearch.get('upc') || '');
  const [dateRangeInput, setDateRangeInput] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(initialDateRange);
  const [dateRange, setDateRange] = useState<[string, string] | null>(
    initialDateRange ? [initialDateRange[0].startOf('day').toISOString(), initialDateRange[1].endOf('day').toISOString()] : null
  );
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<React.Key[]>([]);
  const [bulkStarting, setBulkStarting] = useState(false);
  const [autoStartAfterImport, setAutoStartAfterImport] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(initialSearch.get('status') || undefined);
  const [overview, setOverview] = useState<WorkbenchOverview | null>(null);

  const buildListPath = () => {
    const params = new URLSearchParams();
    if (page > 1) params.set('page', String(page));
    if (pageSize !== 20) params.set('page_size', String(pageSize));
    if (statusFilter) params.set('status', statusFilter);
    if (itemId) params.set('item_id', itemId);
    if (competitorAsin) params.set('competitor_asin', competitorAsin);
    if (upc) params.set('upc', upc);
    if (dateRange) {
      params.set('created_from', dateRange[0]);
      params.set('created_to', dateRange[1]);
    }
    const search = params.toString();
    return `${location.pathname}${search ? `?${search}` : ''}`;
  };

  const openProductDetail = (productId: number) => {
    const returnPath = buildListPath();
    window.localStorage.setItem(PRODUCT_LIST_RETURN_KEY, returnPath);
    navigate(`/products/${productId}`, { state: { from: returnPath } });
  };

  const fetchProducts = async () => {
    setLoading(true);
    try {
      const { data } = await listProducts({
        page,
        page_size: pageSize,
        item_id: itemId.trim() || undefined,
        competitor_asin: competitorAsin.trim() || undefined,
        upc: upc.trim() || undefined,
        status: statusFilter,
        created_from: dateRange?.[0],
        created_to: dateRange?.[1],
      });
      setProducts(data.items);
      setTotal(data.total);
    } catch {
      message.error('加载失败');
    }
    setLoading(false);
  };

  const fetchOverview = async () => {
    try {
      const { data } = await getWorkbenchOverview();
      setOverview(data);
    } catch {
      // 概览失败不影响列表使用。
    }
  };

  useEffect(() => { fetchProducts(); }, [page, pageSize, itemId, competitorAsin, upc, statusFilter, dateRange]);
  useEffect(() => { fetchOverview(); }, []);
  useEffect(() => {
    const params = new URLSearchParams();
    if (page > 1) params.set('page', String(page));
    if (pageSize !== 20) params.set('page_size', String(pageSize));
    if (statusFilter) params.set('status', statusFilter);
    if (itemId) params.set('item_id', itemId);
    if (competitorAsin) params.set('competitor_asin', competitorAsin);
    if (upc) params.set('upc', upc);
    if (dateRange) {
      params.set('created_from', dateRange[0]);
      params.set('created_to', dateRange[1]);
    }
    const nextSearch = params.toString();
    const nextPath = `${location.pathname}${nextSearch ? `?${nextSearch}` : ''}`;
    window.localStorage.setItem(PRODUCT_LIST_RETURN_KEY, nextPath);
    const currentSearch = location.search.startsWith('?') ? location.search.slice(1) : location.search;
    if (nextSearch !== currentSearch) {
      navigate({ pathname: location.pathname, search: nextSearch ? `?${nextSearch}` : '' }, { replace: true });
    }
  }, [page, pageSize, itemId, competitorAsin, upc, statusFilter, dateRange, location.pathname, location.search, navigate]);

  const handleSearch = () => {
    setItemId(itemIdInput.trim());
    setCompetitorAsin(competitorAsinInput.trim());
    setUpc(upcInput.trim());
    setDateRange(dateRangeInput ? [dateRangeInput[0].startOf('day').toISOString(), dateRangeInput[1].endOf('day').toISOString()] : null);
    setPage(1);
  };

  const handleReset = () => {
    setItemIdInput('');
    setCompetitorAsinInput('');
    setUpcInput('');
    setItemId('');
    setCompetitorAsin('');
    setUpc('');
    setDateRangeInput(null);
    setDateRange(null);
    setStatusFilter(undefined);
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

  const handleTemplateDownload = async () => {
    try {
      const { data } = await downloadImportTemplate();
      saveBlob(data, 'fbm_task_import_template.xlsx');
    } catch {
      message.error('模板下载失败');
    }
  };

  const handleImport = async (file: File) => {
    setImporting(true);
    try {
      const { data } = await importProducts(file);
      message.success(`导入完成：新建 ${data.created} 个任务`);
      if (data.errors.length) message.warning(data.errors.slice(0, 3).join('；'));
      if (autoStartAfterImport && data.product_ids.length) {
        const startResult = await bulkStartPipelines(data.product_ids);
        message.success(`已自动启动 ${startResult.data.started} 个任务`);
        if (startResult.data.errors.length) message.warning(startResult.data.errors.slice(0, 3).join('；'));
      }
      setImportOpen(false);
      setSelectedIds([]);
      setPage(1);
      fetchProducts();
      fetchOverview();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '导入失败');
    } finally {
      setImporting(false);
    }
    return false;
  };

  const bulkStartSelected = async () => {
    if (!selectedIds.length) {
      message.warning('请先选择待处理任务');
      return;
    }
    setBulkStarting(true);
    try {
      const { data } = await bulkStartPipelines(selectedIds.map(Number));
      message.success(`已启动 ${data.started} 个任务`);
      if (data.errors.length) message.warning(data.errors.slice(0, 3).join('；'));
      setSelectedIds([]);
      fetchProducts();
      fetchOverview();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '批量启动失败');
    } finally {
      setBulkStarting(false);
    }
  };

  const getStatusTag = (status: string, step: number) => {
    if (status === 'failed') return <Tag color="error">失败</Tag>;
    if (status === 'source_unavailable') return <Tag color="default">原商品下架</Tag>;
    if (status === 'unavailable') return <Tag color="default">不可售</Tag>;
    if (status === 'completed') return <Tag color="success">✅ 完成</Tag>;
    if (status === 'pending_review') return <Tag color="warning">待人工确认</Tag>;
    if (status === 'paused') return <Tag color="warning">已暂停</Tag>;
    if (status === 'created') return <Tag>待处理</Tag>;
    const color = STATUS_COLORS[status] || 'processing';
    return <Tag color={color}>{STEP_LABELS[step] || status}</Tag>;
  };

  const runningStatuses = [
    'step1_collecting',
    'step2_pricing',
    'step3_keywords',
    'step4_category',
    'step5_listing',
    'step6_curating',
    'step7_aplus_plan',
    'step8_aplus_script',
    'step9_aplus_image',
    'step10_amazon_template',
  ];

  const nextAction = (record: Product) => {
    if (runningStatuses.includes(record.status)) return <Tag color="processing">等待运行完成</Tag>;
    if (record.status === 'created') return <Tag color="blue">启动任务</Tag>;
    if (record.status === 'failed') return <Tag color="error">查看错误并重试</Tag>;
    if (record.status === 'paused') return <Tag color="warning">继续任务</Tag>;
    if (record.status === 'pending_review' && record.current_step === 1) return <Tag color="warning">补采集问题</Tag>;
    if (record.status === 'pending_review' && record.current_step === 3) return <Tag color="warning">手动登录卖家精灵</Tag>;
    if (record.status === 'pending_review' && record.current_step === 4) return <Tag color="warning">补 Amazon 类目</Tag>;
    if (record.status === 'pending_review' && record.current_step < 10) return <Tag color="warning">处理后继续</Tag>;
    if (record.status === 'pending_review') return <Tag color="green">确认入库</Tag>;
    if (record.status === 'completed') return <Tag color="success">进入商品列表运营</Tag>;
    if (record.status === 'source_unavailable') return <Tag>停止采集</Tag>;
    if (record.status === 'unavailable') return <Tag>不用处理</Tag>;
    return <Tag>查看详情</Tag>;
  };

  const currentTaskStatus = (record: Product) => {
    if (record.current_task_status) return record.current_task_status;
    if (record.status === 'failed' && record.error_message) return `失败：${record.error_message}`;
    if (record.status === 'pending_review' && record.error_message) return `待人工处理：${record.error_message}`;
    if (record.status === 'source_unavailable' && record.error_message) return `原商品下架停止采集：${record.error_message}`;
    if (record.status === 'unavailable' && record.error_message) return `商品已下架：${record.error_message}`;
    return STEP_LABELS[record.current_step] || record.status || '-';
  };

  const applyStatusQuickFilter = (status?: string) => {
    setStatusFilter(status);
    setPage(1);
  };

  const columns = [
    {
      title: '任务ID',
      dataIndex: 'id',
      width: 60,
      render: (id: number) => <a onClick={() => openProductDetail(id)}>{id}</a>,
    },
    {
      title: '来源商品ID',
      dataIndex: 'gigab2b_product_id',
      width: 120,
      render: (v: string, record: Product) => (record.source_item_id || v) ? <a onClick={() => openProductDetail(record.id)}>{record.source_item_id || v}</a> : '-',
    },
    {
      title: '商品Code',
      dataIndex: 'item_code',
      width: 140,
      render: (v: string, record: Product) => v ? <a onClick={() => openProductDetail(record.id)}>{v}</a> : '-',
    },
    {
      title: '标题',
      dataIndex: 'title',
      width: 360,
      ellipsis: true,
      render: (v: string) => v || '-',
    },
    {
      title: '竞品ASIN',
      dataIndex: 'competitor_asin',
      width: 140,
      render: (v: string) => v || '-',
    },
    {
      title: 'UPC',
      dataIndex: 'upc',
      width: 150,
      render: (v: string) => v || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (status: string, record: Product) => getStatusTag(status, record.current_step),
    },
    {
      title: '当前任务状态',
      dataIndex: 'current_task_status',
      width: 260,
      ellipsis: true,
      render: (_: string | null, record: Product) => {
        const text = currentTaskStatus(record);
        return <Text title={text} style={{ maxWidth: 240, display: 'block' }} ellipsis>{text}</Text>;
      },
    },
    {
      title: '下一步',
      width: 150,
      render: (_: unknown, record: Product) => nextAction(record),
    },
    {
      title: '当前步骤',
      width: 100,
      render: (_: unknown, record: Product) => `${record.current_step}/10`,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      width: 280,
      fixed: 'right' as const,
      render: (_: unknown, record: Product) => (
        <Space size="small">
          <Button size="small" onClick={() => openProductDetail(record.id)}>详情</Button>
          {record.status === 'created' && (
            <Button size="small" type="primary" icon={<PlayCircleOutlined />}
              onClick={async () => { await startPipeline(record.id); fetchProducts(); fetchOverview(); }}>
              启动
            </Button>
          )}
          {record.status === 'failed' && (
            <Button size="small" icon={<RedoOutlined />}
              onClick={async () => { await retryStep(record.id); fetchProducts(); fetchOverview(); }}>
              重试
            </Button>
          )}
          {record.status === 'paused' && (
            <Button size="small" type="primary" icon={<PlayCircleOutlined />}
              onClick={async () => { await resumePipeline(record.id); fetchProducts(); fetchOverview(); }}>
              继续
            </Button>
          )}
          {record.status === 'pending_review' && record.current_step < 10 && (
            <Button size="small" type="primary" icon={<PlayCircleOutlined />}
              onClick={async () => { await resumePipeline(record.id); fetchProducts(); fetchOverview(); }}>
              继续
            </Button>
          )}
          {record.status === 'pending_review' && record.current_step >= 10 && (
            <Popconfirm
              title="确认同步到商品列表？"
              description="确认后，这个商品会进入商品列表，可继续同步 ASIN 和上传 A+。"
              okText="确认入库"
              cancelText="再看看"
              onConfirm={async () => { await confirmProduct(record.id); message.success('已同步到商品列表'); fetchProducts(); fetchOverview(); }}
            >
              <Button size="small" type="primary" icon={<CheckOutlined />}>确认入库</Button>
            </Popconfirm>
          )}
          {!['step1_collecting', 'step2_pricing', 'step3_keywords', 'step4_category', 'step5_listing', 'step6_curating', 'step7_aplus_plan', 'step8_aplus_script', 'step9_aplus_image', 'step10_amazon_template'].includes(record.status) && (
            <Popconfirm
              title="确定重新开始？"
              description="会删除旧素材文件和已生成结果，并从商品采集重新拉取。"
              okText="重新开始"
              cancelText="取消"
              onConfirm={async () => { await restartPipeline(record.id); fetchProducts(); fetchOverview(); }}
            >
              <Button size="small" icon={<RedoOutlined />}>重新开始</Button>
            </Popconfirm>
          )}
          <Popconfirm title="确定删除？" onConfirm={async () => { await deleteProduct(record.id); fetchProducts(); fetchOverview(); }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>商品生成任务</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchProducts}>刷新</Button>
          <Button
            icon={<PlayCircleOutlined />}
            loading={bulkStarting}
            disabled={!selectedIds.length}
            onClick={bulkStartSelected}
          >
            批量启动{selectedIds.length ? `(${selectedIds.length})` : ''}
          </Button>
          <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>导入</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/products/new')}>
            创建任务
          </Button>
        </Space>
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <Button size="small" onClick={() => applyStatusQuickFilter(undefined)}>全部任务</Button>
        <Button size="small" onClick={() => applyStatusQuickFilter('created')}>待启动</Button>
        <Button size="small" onClick={() => applyStatusQuickFilter('pending_review')}>
          待人工处理{overview ? `(${overview.manual_review_tasks + overview.confirmable_tasks})` : ''}
        </Button>
        <Button size="small" onClick={() => applyStatusQuickFilter('failed')}>失败{overview ? `(${overview.failed_tasks})` : ''}</Button>
        <Button size="small" onClick={() => applyStatusQuickFilter('completed')}>已入库</Button>
        {overview && (
          <Text type="secondary" style={{ lineHeight: '24px' }}>
            运行中 {overview.running_tasks} · 可确认 {overview.confirmable_tasks}
          </Text>
        )}
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <Select
          allowClear
          placeholder="任务状态"
          value={statusFilter}
          onChange={(value) => { setStatusFilter(value); setPage(1); }}
          style={{ width: 170 }}
          options={[
            { value: 'created', label: '待启动' },
            { value: 'pending_review', label: '待人工处理' },
            { value: 'failed', label: '失败' },
            { value: 'paused', label: '已暂停' },
            { value: 'completed', label: '已入库' },
            { value: 'source_unavailable', label: '原商品下架' },
            { value: 'unavailable', label: '不可售' },
          ]}
        />
        <Input
          allowClear
          placeholder="搜索商品ID / Code"
          value={itemIdInput}
          onChange={(event) => setItemIdInput(event.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 220 }}
        />
        <Input
          allowClear
          placeholder="搜索竞品 ASIN"
          value={competitorAsinInput}
          onChange={(event) => setCompetitorAsinInput(event.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 220 }}
        />
        <Input
          allowClear
          placeholder="搜索 UPC"
          value={upcInput}
          onChange={(event) => setUpcInput(event.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 180 }}
        />
        <RangePicker
          value={dateRangeInput}
          onChange={(value) => setDateRangeInput(value as [dayjs.Dayjs, dayjs.Dayjs] | null)}
          style={{ width: 260 }}
        />
        <Button icon={<SearchOutlined />} type="primary" onClick={handleSearch}>搜索</Button>
        <Button onClick={handleReset}>重置</Button>
      </div>
      <Table
        className="product-list-table"
        dataSource={products}
        columns={columns}
        rowKey="id"
        loading={loading}
        scroll={{ x: 1980 }}
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: setSelectedIds,
          getCheckboxProps: (record) => ({
            disabled: record.status !== 'created',
          }),
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }}
      />
      <Modal
        title="批量导入任务"
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        footer={[
          <Button key="template" icon={<DownloadOutlined />} onClick={handleTemplateDownload}>导出模板</Button>,
          <Button key="close" onClick={() => setImportOpen(false)}>关闭</Button>,
        ]}
      >
        <Checkbox
          checked={autoStartAfterImport}
          onChange={(event) => setAutoStartAfterImport(event.target.checked)}
          style={{ marginBottom: 12 }}
        >
          导入后自动启动新任务
        </Checkbox>
        <Upload.Dragger
          accept=".xlsx,.xlsm"
          maxCount={1}
          showUploadList={false}
          beforeUpload={handleImport}
          disabled={importing}
        >
          <p className="ant-upload-drag-icon"><UploadOutlined /></p>
          <p className="ant-upload-text">选择或拖入本地 Excel</p>
          <p className="ant-upload-hint">模板列为：原始数据链接、竞品ASIN、UPC</p>
        </Upload.Dragger>
      </Modal>
    </div>
  );
};

export default ProductList;
