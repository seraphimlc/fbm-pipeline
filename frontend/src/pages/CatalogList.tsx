import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Empty, Input, message, Modal, Popconfirm, Segmented, Select, Space, Table, Tag, Typography } from 'antd';
import { CloudSyncOutlined, CopyOutlined, DeleteOutlined, DownloadOutlined, FileExcelOutlined, HistoryOutlined, PictureOutlined, ReloadOutlined, SyncOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { clearCatalogAsin, createAplusUploadBatch, createAsinSyncBatch, createInventorySyncBatch, deleteProduct, exportCatalogProductsByCategory, exportInventoryUpdateTemplate, getWorkbenchOverview, listCatalogExportCategories, listCatalogProducts, updateCatalogAsin } from '../api';
import type { CatalogExportCategorySummary, CatalogProduct, WorkbenchOverview } from '../api';

const { Title, Text } = Typography;

const CatalogList: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<CatalogProduct[]>([]);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [inventoryExporting, setInventoryExporting] = useState(false);
  const [syncingInventory, setSyncingInventory] = useState(false);
  const [syncingAsin, setSyncingAsin] = useState(false);
  const [uploadingAplus, setUploadingAplus] = useState(false);
  const [asinModalOpen, setAsinModalOpen] = useState(false);
  const [asinSaving, setAsinSaving] = useState(false);
  const [asinTarget, setAsinTarget] = useState<CatalogProduct | null>(null);
  const [manualAsin, setManualAsin] = useState('');
  const [selectedIds, setSelectedIds] = useState<React.Key[]>([]);
  const [selectedItemMap, setSelectedItemMap] = useState<Record<number, CatalogProduct>>({});
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [exportStatus, setExportStatus] = useState<'pending' | 'exported'>('pending');
  const [selectedCategory, setSelectedCategory] = useState<string | undefined>();
  const [exportCategories, setExportCategories] = useState<{ pending: CatalogExportCategorySummary[]; exported: CatalogExportCategorySummary[] }>({ pending: [], exported: [] });
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [overview, setOverview] = useState<WorkbenchOverview | null>(null);

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { data } = await listCatalogProducts({
        page,
        page_size: pageSize,
        export_status: exportStatus,
        category: selectedCategory,
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
      // 概览失败不影响导出中心使用。
    }
  };

  const fetchExportCategories = async () => {
    setCategoriesLoading(true);
    try {
      const { data } = await listCatalogExportCategories();
      setExportCategories(data);
    } catch {
      message.error('导出类目加载失败');
    } finally {
      setCategoriesLoading(false);
    }
  };

  useEffect(() => { fetchItems(); }, [page, pageSize, exportStatus, selectedCategory]);
  useEffect(() => { fetchOverview(); }, []);
  useEffect(() => { fetchExportCategories(); }, []);
  useEffect(() => {
    const categories = exportStatus === 'pending' ? exportCategories.pending : exportCategories.exported;
    if (selectedCategory && categories.some((item) => item.category === selectedCategory)) return;
    setSelectedCategory(categories[0]?.category);
    setPage(1);
  }, [exportCategories, exportStatus]);
  useEffect(() => {
    if (!selectedIds.length) return;
    const selectedSet = new Set(selectedIds.map(Number));
    const selectedItemsOnPage = items.filter((item) => selectedSet.has(item.id));
    if (!selectedItemsOnPage.length) return;
    setSelectedItemMap((prev) => {
      const next = { ...prev };
      selectedItemsOnPage.forEach((item) => {
        next[item.id] = item;
      });
      return next;
    });
  }, [items, selectedIds]);

  const selectExportStatus = (status: 'pending' | 'exported') => {
    setExportStatus(status);
    setSelectedCategory(undefined);
    setPage(1);
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

  const extractDownloadError = async (error: any, fallback: string) => {
    const payload = error?.response?.data;
    if (payload instanceof Blob) {
      const text = await payload.text();
      if (!text) return fallback;
      try {
        const parsed = JSON.parse(text);
        return parsed?.detail || text;
      } catch {
        return text;
      }
    }
    return payload?.detail || error?.message || fallback;
  };

  const currentCategoryOptions = exportStatus === 'pending' ? exportCategories.pending : exportCategories.exported;
  const selectedCategorySummary = currentCategoryOptions.find((item) => item.category === selectedCategory);

  const categoryOptionLabel = (item: CatalogExportCategorySummary) => (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      <Space wrap>
        <Text strong>{item.category}</Text>
        <Tag color={item.template_available ? 'success' : 'warning'}>
          {item.template_available ? '有模板' : '缺模板'}
        </Tag>
        <Tag color={exportStatus === 'pending' ? 'blue' : 'default'}>
          {exportStatus === 'pending' ? `${item.exportable_count} 个待导出` : `${item.count} 个已导出`}
        </Tag>
      </Space>
      <Text type="secondary" ellipsis>
        {item.template_available ? item.template_name : item.template_error || '未匹配到模板'}
      </Text>
    </Space>
  );

  const exportSelected = async () => {
    const category = currentCategoryOptions.find((item) => item.category === selectedCategory);
    if (!category) {
      message.warning('请先选择待导出类目');
      return;
    }
    if (exportStatus !== 'pending') {
      message.warning('已导出类目只用于查看，不会再次生成 Amazon 导入表格');
      return;
    }
    if (!category.template_available) {
      message.warning(category.template_error || '当前类目没有可用模板');
      return;
    }
    setExporting(true);
    const hideLoading = message.loading(`正在导出「${category.category}」Amazon 表格，生成完成后会自动下载...`, 0);
    try {
      const { data } = await exportCatalogProductsByCategory(category.category);
      saveBlob(data, `amazon_import_${category.category}_${dayjs().format('YYYYMMDD_HHmmss')}.zip`);
      message.success('已导出 Amazon 导入表格压缩包');
      fetchItems();
      fetchExportCategories();
    } catch (error: any) {
      message.error(await extractDownloadError(error, '导出失败'));
    } finally {
      hideLoading();
      setExporting(false);
    }
  };

  const copyText = async (text: string) => {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    document.execCommand('copy');
    textarea.remove();
  };

  const copySelectedAmazonAsins = async () => {
    if (!selectedIds.length) {
      message.warning('请先选择商品');
      return;
    }
    const selectedRecords = selectedIds
      .map((id) => selectedItemMap[Number(id)] || items.find((item) => item.id === Number(id)))
      .filter(Boolean) as CatalogProduct[];
    const asins = selectedRecords
      .filter((item) => item.amazon_asin?.trim() && !isUnavailableAmazonStatus(item.amazon_product_status))
      .map((item) => item.amazon_asin?.trim())
      .filter((asin): asin is string => Boolean(asin));
    if (!asins.length) {
      message.info('没有可复制的真实 ASIN，空 ASIN 或不可售商品已跳过');
      return;
    }
    try {
      await copyText(asins.join('\n'));
      const missingCount = selectedIds.length - asins.length;
      message.success(`已复制 ${asins.length} 个真实 ASIN${missingCount ? `，跳过 ${missingCount} 个空 ASIN 或不可售商品` : ''}`);
    } catch {
      message.error('复制失败，请检查浏览器剪贴板权限');
    }
  };

  const exportInventorySelected = async () => {
    if (!selectedIds.length) {
      message.warning('请先选择商品');
      return;
    }
    const selectedSet = new Set(selectedIds.map(Number));
    const missingAsinItems = items.filter((item) => selectedSet.has(item.id) && !item.amazon_asin);
    if (missingAsinItems.length) {
      message.info(`缺少真实 ASIN 的商品会自动跳过：${missingAsinItems.map((item) => item.item_code || item.id).slice(0, 5).join('、')}`);
    }
    setInventoryExporting(true);
    const hideLoading = message.loading('正在导出库存模板，生成完成后会自动下载...', 0);
    try {
      const { data } = await exportInventoryUpdateTemplate(selectedIds.map(Number));
      saveBlob(data, `inventory_update_templates_${dayjs().format('YYYYMMDD_HHmmss')}.zip`);
      message.success('已导出库存同步模板');
    } catch (error: any) {
      message.error(await extractDownloadError(error, '库存模板导出失败'));
    } finally {
      hideLoading();
      setInventoryExporting(false);
    }
  };

  const syncSelectedInventory = async () => {
    if (!selectedIds.length) {
      navigate('/inventory-sync');
      return;
    }
    setSyncingInventory(true);
    try {
      const { data } = await createInventorySyncBatch(selectedIds.map(Number));
      message.success(`已创建库存同步批次 #${data.id}`);
      setSelectedIds([]);
      setSelectedItemMap({});
      fetchItems();
      fetchOverview();
      navigate('/inventory-sync');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '库存同步批次创建失败');
    } finally {
      setSyncingInventory(false);
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
      message.success(`已创建 ASIN/亚马逊商品状态同步批次 #${data.id}`);
      setSelectedIds([]);
      setSelectedItemMap({});
      fetchItems();
      fetchOverview();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'ASIN/亚马逊商品状态同步批次创建失败');
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

  const isUnavailableAmazonStatus = (status?: string | null) => {
    const normalized = String(status || '').toLowerCase();
    return ['不可售', '停售', '已删除', '下架', 'suppressed', 'inactive', 'deleted', 'not sellable', 'unavailable'].some((keyword) => normalized.includes(keyword));
  };

  const amazonProductStatusTag = (status?: string | null, error?: string | null, record?: CatalogProduct) => {
    const text = status || (record?.amazon_asin || record?.asin_sync_status === 'synced' ? '状态未返回' : '未同步');
    const normalized = String(status || '').toLowerCase();
    const sellable = ['售卖', '在售', '可售', 'active', 'buyable', '正常'].some((keyword) => normalized.includes(keyword));
    const unavailable = isUnavailableAmazonStatus(status);
    return (
      <Space direction="vertical" size={2}>
        <Tag color={sellable ? 'success' : unavailable ? 'error' : status ? 'warning' : 'default'}>{text}</Tag>
        {error && <Text type="secondary" ellipsis style={{ maxWidth: 150 }}>{error}</Text>}
      </Space>
    );
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
      setSelectedItemMap({});
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

  const deleteCatalogRecord = async (record: CatalogProduct) => {
    try {
      await deleteProduct(record.source_product_id);
      message.success('商品已删除');
      setSelectedIds((prev) => prev.filter((id) => Number(id) !== record.id));
      setSelectedItemMap((prev) => {
        const next = { ...prev };
        delete next[record.id];
        return next;
      });
      if (items.length === 1 && page > 1) {
        setPage(page - 1);
      } else {
        fetchItems();
      }
      fetchOverview();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除失败');
    }
  };

  const clearAsin = async (record: CatalogProduct) => {
    try {
      await clearCatalogAsin(record.id);
      message.success('真实 ASIN 已清除');
      fetchItems();
      fetchOverview();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '清除 ASIN 失败');
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
      title: '亚马逊商品状态',
      dataIndex: 'amazon_product_status',
      width: 150,
      render: (value: string, record: CatalogProduct) => amazonProductStatusTag(value, record.amazon_product_status_error, record),
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
      width: 330,
      render: (_: unknown, record: CatalogProduct) => (
        <Space size="small">
          <Button size="small" onClick={() => navigate(`/products/${record.source_product_id}`)}>详情</Button>
          <Button size="small" onClick={() => openAsinModal(record)}>
            {record.amazon_asin ? '重新关联ASIN' : '关联ASIN'}
          </Button>
          {record.amazon_asin && (
            <Popconfirm
              title="确定清除真实 ASIN？"
              description="清除后这个商品会回到可同步 ASIN 状态。"
              okText="清除"
              cancelText="取消"
              onConfirm={() => clearAsin(record)}
            >
              <Button size="small">清除ASIN</Button>
            </Popconfirm>
          )}
          <Popconfirm
            title="确定删除这个商品？"
            description="会删除对应任务和商品资料。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => deleteCatalogRecord(record)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>导出中心</Title>
        <Space>
          <Text type="secondary">最多显示 1000 个商品</Text>
          <Button icon={<ReloadOutlined />} onClick={() => { fetchItems(); fetchExportCategories(); }}>刷新</Button>
          <Button icon={<CloudSyncOutlined />} loading={syncingInventory} onClick={syncSelectedInventory}>
            库存同步{selectedIds.length ? `(${selectedIds.length})` : ''}
          </Button>
          <Button icon={<HistoryOutlined />} onClick={() => navigate('/asin-sync')}>同步记录</Button>
          <Button icon={<SyncOutlined />} loading={syncingAsin} disabled={!selectedIds.length} onClick={syncSelectedAsins}>
            同步ASIN/状态{selectedIds.length ? `(${selectedIds.length})` : ''}
          </Button>
          <Button icon={<CopyOutlined />} disabled={!selectedIds.length} onClick={copySelectedAmazonAsins}>
            提取真实ASIN{selectedIds.length ? `(${selectedIds.length})` : ''}
          </Button>
          <Button icon={<PictureOutlined />} loading={uploadingAplus} disabled={!selectedIds.length} onClick={uploadSelectedAplus}>
            上传A+{selectedIds.length ? `(${selectedIds.length})` : ''}
          </Button>
          <Button icon={<FileExcelOutlined />} loading={inventoryExporting} disabled={!selectedIds.length} onClick={exportInventorySelected}>
            导出库存模板{selectedIds.length ? `(${selectedIds.length})` : ''}
          </Button>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            loading={exporting}
            disabled={exportStatus !== 'pending' || !selectedCategorySummary?.template_available || !selectedCategorySummary.exportable_count}
            onClick={exportSelected}
          >
            导出Amazon表格{selectedCategorySummary?.exportable_count ? `(${selectedCategorySummary.exportable_count})` : ''}
          </Button>
        </Space>
      </div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Space style={{ justifyContent: 'space-between', width: '100%' }}>
            <Segmented
              value={exportStatus}
              onChange={(value) => selectExportStatus(value as 'pending' | 'exported')}
              options={[
                { label: `待导出类目 ${exportCategories.pending.length}`, value: 'pending' },
                { label: `已导出类目 ${exportCategories.exported.length}`, value: 'exported' },
              ]}
            />
            <Button size="small" icon={<ReloadOutlined />} loading={categoriesLoading} onClick={fetchExportCategories}>刷新类目</Button>
          </Space>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 420px) minmax(0, 1fr)', gap: 16, alignItems: 'start' }}>
            <Select
              loading={categoriesLoading}
              value={selectedCategory}
              placeholder={exportStatus === 'pending' ? '选择待导出商品所在类目' : '选择已导出商品所在类目'}
              onChange={(value) => { setSelectedCategory(value); setPage(1); }}
              style={{ width: '100%' }}
              options={currentCategoryOptions.map((item) => ({
                value: item.category,
                label: `${item.category} · ${exportStatus === 'pending' ? item.exportable_count : item.count}个 · ${item.template_available ? '有模板' : '缺模板'}`,
              }))}
            />
            {selectedCategorySummary ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(110px, 1fr))', gap: 8 }}>
                <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 12 }}>{categoryOptionLabel(selectedCategorySummary)}</div>
                <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 12 }}>
                  <Text type="secondary">商品数</Text>
                  <div style={{ fontSize: 18, fontWeight: 600 }}>{selectedCategorySummary.count}</div>
                </div>
                <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 12 }}>
                  <Text type="secondary">可导出</Text>
                  <div style={{ fontSize: 18, fontWeight: 600 }}>{selectedCategorySummary.exportable_count}</div>
                </div>
                <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 12 }}>
                  <Text type="secondary">样例</Text>
                  <Typography.Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0 }}>
                    {selectedCategorySummary.sample_item_codes.join('、') || '-'}
                  </Typography.Paragraph>
                </div>
              </div>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={exportStatus === 'pending' ? '暂无待导出类目' : '暂无已导出类目'} />
            )}
          </div>
        </Space>
      </Card>
      <Table
        dataSource={items}
        columns={columns}
        rowKey="id"
        loading={loading}
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: (keys, selectedRows) => {
            setSelectedIds(keys);
            setSelectedItemMap((prev) => {
              const next: Record<number, CatalogProduct> = {};
              keys.forEach((key) => {
                const id = Number(key);
                const latestRow = selectedRows.find((row) => row.id === id);
                const currentPageRow = items.find((item) => item.id === id);
                const cachedRow = prev[id];
                if (latestRow || currentPageRow || cachedRow) {
                  next[id] = latestRow || currentPageRow || cachedRow;
                }
              });
              return next;
            });
          },
          preserveSelectedRowKeys: true,
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
