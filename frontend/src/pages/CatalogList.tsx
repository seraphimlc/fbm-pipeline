import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Empty, message, Popconfirm, Segmented, Select, Space, Table, Tabs, Tag, Typography, Upload } from 'antd';
import { DeleteOutlined, DownloadOutlined, PauseCircleOutlined, PlayCircleOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import {
  createCatalogExportOfflineTasks,
  deleteCatalogTemplateFile,
  downloadOfflineTaskResult,
  downloadCatalogTemplateFile,
  listCatalogExportCategories,
  listCatalogProducts,
  listCatalogTemplateCategories,
  listCatalogTemplateFiles,
  updateCatalogTemplateFileStatus,
  uploadCatalogCategoryTemplate,
} from '../api';
import type { CatalogExportCategorySummary, CatalogProduct, CatalogTemplateFileSummary } from '../api';

const { Title, Text } = Typography;
const ALL_CATEGORIES = '__all__';

const CatalogList: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<CatalogProduct[]>([]);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [exportStatus, setExportStatus] = useState<'pending' | 'exported'>('pending');
  const [selectedCategory, setSelectedCategory] = useState<string>(ALL_CATEGORIES);
  const [exportCategories, setExportCategories] = useState<{ pending: CatalogExportCategorySummary[]; exported: CatalogExportCategorySummary[] }>({ pending: [], exported: [] });
  const [templateCategories, setTemplateCategories] = useState<CatalogExportCategorySummary[]>([]);
  const [templateFiles, setTemplateFiles] = useState<CatalogTemplateFileSummary[]>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [templateUploading, setTemplateUploading] = useState(false);
  const [templateDownloadingFileId, setTemplateDownloadingFileId] = useState<string | null>(null);
  const [templateFileMutatingId, setTemplateFileMutatingId] = useState<string | null>(null);
  const [exportDownloadingTaskId, setExportDownloadingTaskId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<React.Key[]>([]);
  const [selectedItemMap, setSelectedItemMap] = useState<Record<number, CatalogProduct>>({});
  const [activeTab, setActiveTab] = useState('export');
  const itemRequestId = useRef(0);

  const currentCategoryOptions = exportStatus === 'pending' ? exportCategories.pending : exportCategories.exported;
  const isAllCategories = selectedCategory === ALL_CATEGORIES;
  const selectedCategorySummary = isAllCategories ? undefined : currentCategoryOptions.find((item) => item.category === selectedCategory);
  const aggregateSummary = currentCategoryOptions.reduce(
    (acc, item) => ({
      count: acc.count + item.count,
      exportableCount: acc.exportableCount + item.exportable_count,
      categoryCount: acc.categoryCount + 1,
      templateReadyCount: acc.templateReadyCount + (item.template_available ? 1 : 0),
      blockedCount: acc.blockedCount + item.blocked_count,
    }),
    { count: 0, exportableCount: 0, categoryCount: 0, templateReadyCount: 0, blockedCount: 0 },
  );
  const uncoveredTemplateCategoryRows = templateCategories
    .filter((summary) => !summary.template_available)
    .map((summary) => ({
      key: summary.category,
      category: summary.category,
      summary,
    }));

  const fetchItems = async () => {
    const requestId = itemRequestId.current + 1;
    itemRequestId.current = requestId;
    setLoading(true);
    try {
      const { data } = await listCatalogProducts({
        page,
        page_size: pageSize,
        export_status: exportStatus,
        category: isAllCategories ? undefined : selectedCategory,
      });
      if (requestId !== itemRequestId.current) return;
      if (!data.items.length && data.total > 0 && page > 1) {
        setPage(1);
        return;
      }
      setItems(data.items);
      setTotal(data.total);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载导出商品失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchExportCategories = async () => {
    setCategoriesLoading(true);
    try {
      const { data } = await listCatalogExportCategories();
      setExportCategories(data);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '导出类目加载失败');
    } finally {
      setCategoriesLoading(false);
    }
  };

  const fetchTemplateCategories = async () => {
    setCategoriesLoading(true);
    try {
      const { data } = await listCatalogTemplateCategories();
      setTemplateCategories(data);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '模板类目加载失败');
    } finally {
      setCategoriesLoading(false);
    }
  };

  const fetchTemplateFiles = async () => {
    setCategoriesLoading(true);
    try {
      const { data } = await listCatalogTemplateFiles();
      setTemplateFiles(data);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '模板文件加载失败');
    } finally {
      setCategoriesLoading(false);
    }
  };

  const refreshExportCenterData = async () => {
    await Promise.all([fetchExportCategories(), fetchTemplateCategories(), fetchTemplateFiles()]);
  };

  useEffect(() => { refreshExportCenterData(); }, []);
  useEffect(() => { fetchItems(); }, [page, pageSize, exportStatus, selectedCategory]);
  useEffect(() => {
    const categories = exportStatus === 'pending' ? exportCategories.pending : exportCategories.exported;
    if (selectedCategory === ALL_CATEGORIES || categories.some((item) => item.category === selectedCategory)) return;
    setSelectedCategory(ALL_CATEGORIES);
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
    setSelectedCategory(ALL_CATEGORIES);
    setSelectedIds([]);
    setSelectedItemMap({});
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

  const extractFilename = (disposition?: string | null, fallback = 'amazon_category_template.xlsm') => {
    const matched = disposition?.match(/filename\\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
    const raw = matched?.[1] || matched?.[2];
    if (!raw) return fallback;
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  };

  const categoryTemplateTag = (summary?: CatalogExportCategorySummary) => {
    if (!summary) return <Tag>未选择类目</Tag>;
    if (summary.template_available) {
      return <Tag color="success">有模板</Tag>;
    }
    if (summary.uploaded_template_name) {
      return <Tag color="warning">已上传但未接入映射</Tag>;
    }
    return <Tag color="warning">缺模板</Tag>;
  };

  const templateTag = (summary?: CatalogExportCategorySummary) => {
    if (isAllCategories) {
      if (!aggregateSummary.categoryCount) return <Tag>无类目</Tag>;
      if (aggregateSummary.templateReadyCount === aggregateSummary.categoryCount) return <Tag color="success">全部类目有模板</Tag>;
      return <Tag color="warning">{aggregateSummary.categoryCount - aggregateSummary.templateReadyCount} 个类目缺模板</Tag>;
    }
    return categoryTemplateTag(summary);
  };

  const createExportTasksByIds = async (ids: number[], label: string) => {
    if (!ids.length) {
      message.warning('没有可导出的商品');
      return;
    }
    if (ids.length > 1000) {
      message.warning('单次最多导出 1000 个商品，请缩小筛选范围');
      return;
    }
    setExporting(true);
    const hideLoading = message.loading(`正在为${label}创建导出任务，系统会按模板拆分...`, 0);
    try {
      const { data } = await createCatalogExportOfflineTasks(ids);
      if (data.tasks.length) {
        message.success(`已创建 ${data.tasks.length} 个导出任务，请到任务中心下载结果`);
      } else {
        message.warning('没有创建导出任务，请检查类目模板和商品状态');
      }
      if (data.errors?.length) {
        message.warning(`有 ${data.errors.length} 个商品未进入导出任务，可在任务中心任务详情或接口返回中查看原因`);
      }
      await refreshExportCenterData();
      await fetchItems();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '创建导出任务失败');
    } finally {
      hideLoading();
      setExporting(false);
    }
  };

  const exportCatalog = async () => {
    if (selectedIds.length) {
      await createExportTasksByIds(selectedIds.map(Number), `选中的 ${selectedIds.length} 个商品`);
      return;
    }
    const currentActionCount = exportStatus === 'pending'
      ? (isAllCategories ? aggregateSummary.exportableCount : selectedCategorySummary?.exportable_count || 0)
      : (isAllCategories ? aggregateSummary.count : selectedCategorySummary?.count || 0);
    if (!isAllCategories && selectedCategorySummary && !currentActionCount) {
      message.warning(exportStatus === 'pending' ? '当前类目没有可导出的商品' : '当前类目没有历史导出商品');
      return;
    }
    if (isAllCategories && !currentActionCount) {
      message.warning(exportStatus === 'pending' ? '当前没有待导出的商品' : '当前没有已导出商品');
      return;
    }
    setExporting(true);
    try {
      const { data } = await listCatalogProducts({
        page: 1,
        page_size: 1000,
        export_status: exportStatus,
        category: isAllCategories ? undefined : selectedCategory,
      });
      await createExportTasksByIds(
        data.items.map((item) => item.id),
        isAllCategories
          ? (exportStatus === 'pending' ? '全部待导出商品' : '全部已导出商品的新导出尝试')
          : `「${selectedCategory}」下的${exportStatus === 'pending' ? '商品' : '已导出商品新导出尝试'}`,
      );
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载待导出商品失败');
      setExporting(false);
    }
  };

  const uploadTemplateForCategory = async (category: string, file: File) => {
    if (!category) {
      message.warning('请先选择一个具体类目');
      return;
    }
    const suffix = file.name.split('.').pop()?.toLowerCase();
    if (!suffix || !['xls', 'xlsx', 'xlsm'].includes(suffix)) {
      message.warning('只支持上传 .xls / .xlsx / .xlsm 模板文件');
      return;
    }
    setTemplateUploading(true);
    try {
      const { data } = await uploadCatalogCategoryTemplate(category, file);
      message.success(`模板已上传 OSS，并缓存到本地：${data.filename}`);
      await refreshExportCenterData();
      await fetchItems();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '模板上传失败');
    } finally {
      setTemplateUploading(false);
    }
  };

  const downloadTemplateFile = async (record: CatalogTemplateFileSummary) => {
    setTemplateDownloadingFileId(record.file_id);
    try {
      const response = await downloadCatalogTemplateFile(record.file_id);
      saveBlob(response.data, extractFilename(response.headers['content-disposition'], record.file_name || 'amazon_template.xlsm'));
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '下载模板失败');
    } finally {
      setTemplateDownloadingFileId(null);
    }
  };

  const downloadExportTaskResult = async (record: CatalogProduct) => {
    if (!record.export_task_id) {
      message.warning('当前商品没有关联导出任务');
      return;
    }
    setExportDownloadingTaskId(record.export_task_id);
    try {
      const response = await downloadOfflineTaskResult(record.export_task_id);
      const fallback = record.export_file_path?.split('/').pop() || `catalog_export_${record.export_task_id}.zip`;
      saveBlob(response.data, extractFilename(response.headers['content-disposition'], fallback));
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '下载导出文件失败');
    } finally {
      setExportDownloadingTaskId(null);
    }
  };

  const toggleTemplateFile = async (record: CatalogTemplateFileSummary) => {
    setTemplateFileMutatingId(record.file_id);
    try {
      await updateCatalogTemplateFileStatus(record.file_id, !record.enabled);
      message.success(record.enabled ? '模板已停用' : '模板已启用');
      await refreshExportCenterData();
      await fetchItems();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更新模板状态失败');
    } finally {
      setTemplateFileMutatingId(null);
    }
  };

  const deleteTemplateFile = async (record: CatalogTemplateFileSummary) => {
    setTemplateFileMutatingId(record.file_id);
    try {
      await deleteCatalogTemplateFile(record.file_id);
      message.success('模板文件已删除');
      await refreshExportCenterData();
      await fetchItems();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除模板失败');
    } finally {
      setTemplateFileMutatingId(null);
    }
  };

  const riskTag = (risk?: string | null, count?: number | null) => {
    const suffix = count ? ` · ${count}条` : '';
    if (risk === 'pass') return <Tag color="success">通过{suffix}</Tag>;
    if (risk === 'warning') return <Tag color="warning">需复核{suffix}</Tag>;
    if (risk === 'high_risk') return <Tag color="error">高风险{suffix}</Tag>;
    return <Tag>未检查</Tag>;
  };

  const panelStyle: React.CSSProperties = {
    background: '#fff',
    border: '1px solid #eef0f4',
    borderRadius: 8,
  };

  const selectedItems = selectedIds.map((id) => selectedItemMap[Number(id)]).filter(Boolean) as CatalogProduct[];
  const templateSplitKey = (summary?: CatalogExportCategorySummary) =>
    summary?.template_path || summary?.template_name || summary?.uploaded_template_object_key || summary?.category || '';
  const selectedCategories = new Set(selectedItems.map((item) => item.leaf_category || '未分类'));
  const selectedTemplateCount = new Set(
    currentCategoryOptions
      .filter((summary) => selectedCategories.has(summary.category) && summary.template_available)
      .map((summary) => templateSplitKey(summary))
      .filter(Boolean),
  ).size;
  const currentSplitCount = isAllCategories
    ? new Set(currentCategoryOptions.filter((summary) => summary.template_available && summary.exportable_count > 0).map((summary) => templateSplitKey(summary))).size
    : selectedCategorySummary?.template_available ? 1 : 0;
  const exportButtonText = selectedIds.length
    ? `导出选中(${selectedIds.length})`
    : `${exportStatus === 'pending' ? '导出当前筛选' : '新建导出任务'}${isAllCategories
      ? `(${exportStatus === 'pending' ? aggregateSummary.exportableCount : aggregateSummary.count})`
      : selectedCategorySummary
        ? `(${exportStatus === 'pending' ? selectedCategorySummary.exportable_count : selectedCategorySummary.count})`
        : ''}`;
  const exportDisabled = !selectedIds.length && (isAllCategories
    ? (exportStatus === 'pending' ? !aggregateSummary.exportableCount : !aggregateSummary.count) || aggregateSummary.templateReadyCount === 0
    : (exportStatus === 'pending' ? !selectedCategorySummary?.exportable_count : !selectedCategorySummary?.count) || !selectedCategorySummary?.template_available);

  const columns = [
    {
      title: '商品Code',
      dataIndex: 'item_code',
      width: 150,
      render: (value: string | null, record: CatalogProduct) => (
        <a onClick={() => navigate(`/products/${record.source_product_id}`)}>
          {record.source_item_id || value || record.source_product_id}
        </a>
      ),
    },
    {
      title: '标题',
      dataIndex: 'title',
      ellipsis: true,
      render: (value: string | null) => (
        <Typography.Text ellipsis style={{ maxWidth: 360 }}>
          {value || '-'}
        </Typography.Text>
      ),
    },
    {
      title: 'Amazon类目',
      dataIndex: 'leaf_category',
      width: 260,
      render: (value: string | null) => value ? (
        <Typography.Text ellipsis style={{ maxWidth: 240 }}>
          {value}
        </Typography.Text>
      ) : '-',
    },
    {
      title: 'UPC',
      dataIndex: 'upc',
      width: 150,
      render: (value: string | null) => value || '-',
    },
    {
      title: '风险检查',
      dataIndex: 'template_risk_level',
      width: 130,
      render: (value: string | null, record: CatalogProduct) => riskTag(value, record.template_warnings_count),
    },
    {
      title: '导出状态',
      width: 120,
      render: (_: unknown, record: CatalogProduct) => (
        <Space size={4} wrap>
          {exportStatus === 'pending' ? <Tag color="blue">待导出</Tag> : <Tag color="success">历史文件</Tag>}
          {record.amazon_asin ? <Tag color="purple">真实 ASIN</Tag> : null}
        </Space>
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 170,
      render: (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      width: 150,
      render: (_: unknown, record: CatalogProduct) => (
        <Space size="small">
          <Button size="small" onClick={() => navigate(`/products/${record.source_product_id}`)}>商品详情</Button>
          {exportStatus === 'exported' && record.export_task_id ? (
            <Button
              size="small"
              icon={<DownloadOutlined />}
              loading={exportDownloadingTaskId === record.export_task_id}
              onClick={() => downloadExportTaskResult(record)}
            >
              下载
            </Button>
          ) : null}
        </Space>
      ),
    },
  ];
  const templateFileStatusTag = (record: CatalogTemplateFileSummary) => {
    if (!record.enabled || record.file_status === 'disabled') return <Tag color="default">已停用</Tag>;
    if (record.file_status === 'unmapped') return <Tag color="warning">未接入</Tag>;
    return <Tag color="success">启用中</Tag>;
  };

  const templateFileColumns = [
    {
      title: '文件编号',
      dataIndex: 'file_no',
      width: 240,
      render: (value: string, record: CatalogTemplateFileSummary) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{value}</Typography.Text>
          <Typography.Text type="secondary" ellipsis style={{ maxWidth: 220 }}>
            {record.file_name}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '文件状态',
      dataIndex: 'file_status',
      width: 120,
      render: (_: string, record: CatalogTemplateFileSummary) => templateFileStatusTag(record),
    },
    {
      title: '支持类目',
      width: 620,
      render: (_: unknown, record: CatalogTemplateFileSummary) => (
        <Space size={[4, 4]} wrap>
          {record.support_categories.map((category) => <Tag key={category}>{category}</Tag>)}
        </Space>
      ),
    },
    {
      title: '模板下载',
      width: 120,
      render: (_: unknown, record: CatalogTemplateFileSummary) => (
        <Button
          size="small"
          icon={<DownloadOutlined />}
          disabled={!record.can_download}
          loading={templateDownloadingFileId === record.file_id}
          onClick={() => downloadTemplateFile(record)}
        >
          下载
        </Button>
      ),
    },
    {
      title: '模板启用/停用',
      width: 150,
      render: (_: unknown, record: CatalogTemplateFileSummary) => (
        <Button
          size="small"
          icon={record.enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
          loading={templateFileMutatingId === record.file_id}
          onClick={() => toggleTemplateFile(record)}
        >
          {record.enabled ? '停用' : '启用'}
        </Button>
      ),
    },
    {
      title: '文件删除',
      width: 120,
      render: (_: unknown, record: CatalogTemplateFileSummary) => (
        <Popconfirm
          title="删除模板文件"
          description="只删除上传模板记录和本地缓存，不会删除商品数据。"
          okText="删除"
          cancelText="取消"
          disabled={!record.can_delete}
          onConfirm={() => deleteTemplateFile(record)}
        >
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            disabled={!record.can_delete}
            loading={templateFileMutatingId === record.file_id}
          >
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];
  const uncoveredCategoryColumns = [
    {
      title: '未覆盖类目',
      dataIndex: 'category',
      width: 260,
      render: (value: string) => (
        <Typography.Text ellipsis style={{ maxWidth: 240 }}>
          {value}
        </Typography.Text>
      ),
    },
    {
      title: '状态',
      width: 180,
      render: () => <Tag color="warning">未被现有模板覆盖</Tag>,
    },
    {
      title: '处理建议',
      render: () => <Text type="secondary">请到 Amazon 重新下载包含该类目的导入模板，上传后再配置/确认 mapping</Text>,
    },
    {
      title: '上传模板',
      width: 150,
      render: (_: unknown, record: any) => (
        <Upload
          showUploadList={false}
          accept=".xls,.xlsx,.xlsm"
          customRequest={({ file, onSuccess, onError }) => {
            uploadTemplateForCategory(record.category, file as File)
              .then(() => onSuccess?.('ok'))
              .catch((error) => onError?.(error));
          }}
        >
          <Button size="small" icon={<UploadOutlined />} loading={templateUploading}>
            上传模板
          </Button>
        </Upload>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, marginBottom: 16 }}>
        <div style={{ minWidth: 0 }}>
          <Title level={4} style={{ margin: 0 }}>导出中心</Title>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => { fetchItems(); refreshExportCenterData(); }}>查询</Button>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'export',
            label: '商品导出',
            children: (
              <>
                <div style={{ ...panelStyle, padding: 16, marginBottom: 16 }}>
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
                      <Space wrap>
                        {selectedIds.length > 0 && (
                          <Button onClick={() => { setSelectedIds([]); setSelectedItemMap({}); }}>
                            清空选择
                          </Button>
                        )}
                        <Button
                          type="primary"
                          icon={<DownloadOutlined />}
                          loading={exporting}
                          disabled={exportDisabled}
                          onClick={exportCatalog}
                        >
                          {exportButtonText}
                        </Button>
                      </Space>
                    </Space>
                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 520px) minmax(0, 1fr)', gap: 20, alignItems: 'start' }}>
                      <Select
                        loading={categoriesLoading}
                        value={selectedCategory}
                        placeholder={exportStatus === 'pending' ? '选择待导出商品所在类目' : '选择已导出商品所在类目'}
                        onChange={(value) => { setSelectedCategory(value); setPage(1); }}
                        style={{ width: '100%' }}
                        options={[
                          {
                            value: ALL_CATEGORIES,
                            label: `${exportStatus === 'pending' ? '全部待导出商品' : '全部已导出商品'} · ${exportStatus === 'pending' ? aggregateSummary.exportableCount : aggregateSummary.count}个 · ${aggregateSummary.categoryCount}个类目`,
                          },
                          ...currentCategoryOptions.map((item) => ({
                            value: item.category,
                            label: `${item.category} · ${exportStatus === 'pending' ? item.exportable_count : item.count}个 · ${item.template_available ? '有模板' : item.uploaded_template_name ? '已上传未接入' : '缺模板'}`,
                          })),
                        ]}
                      />
                      {currentCategoryOptions.length ? (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(110px, 1fr))', gap: 16 }}>
                          <div>
                            <Text type="secondary">模板覆盖</Text>
                            <div style={{ marginTop: 6 }}>{templateTag(selectedCategorySummary)}</div>
                          </div>
                          <div>
                            <Text type="secondary">{exportStatus === 'pending' ? '待导出商品' : '已导出商品'}</Text>
                            <div style={{ fontSize: 20, fontWeight: 600 }}>
                              {isAllCategories ? aggregateSummary.count : selectedCategorySummary?.count || 0}
                            </div>
                          </div>
                          <div>
                            <Text type="secondary">导出拆分</Text>
                            <div style={{ fontSize: 20, fontWeight: 600 }}>{selectedIds.length ? selectedTemplateCount : currentSplitCount} 个模板</div>
                          </div>
                        </div>
                      ) : (
                        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={exportStatus === 'pending' ? '暂无待导出类目' : '暂无已导出类目'} />
                      )}
                    </div>
                  </Space>
                </div>

                <div style={panelStyle}>
                  <Table
                    dataSource={items}
                    columns={columns}
                    rowKey="id"
                    loading={loading}
                    size="middle"
                    scroll={{ x: 1120 }}
                    rowSelection={{
                      selectedRowKeys: selectedIds,
                      preserveSelectedRowKeys: true,
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
                </div>
              </>
            ),
          },
          {
            key: 'templates',
            label: '类目模板管理',
            children: (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <div style={panelStyle}>
                  <Table
                    rowKey="file_id"
                    dataSource={templateFiles}
                    columns={templateFileColumns}
                    loading={categoriesLoading}
                    scroll={{ x: 1210 }}
                    pagination={false}
                    locale={{ emptyText: '暂无模板文件' }}
                  />
                </div>
                <div style={panelStyle}>
                  <div style={{ padding: '12px 16px', borderBottom: '1px solid #eef0f4', fontWeight: 600 }}>
                    未覆盖类目
                  </div>
                  <Table
                    rowKey="category"
                    dataSource={uncoveredTemplateCategoryRows}
                    columns={uncoveredCategoryColumns}
                    loading={categoriesLoading}
                    scroll={{ x: 980 }}
                    pagination={false}
                    locale={{ emptyText: '当前没有未覆盖类目' }}
                  />
                </div>
              </Space>
            ),
          },
        ]}
      />

    </div>
  );
};

export default CatalogList;
