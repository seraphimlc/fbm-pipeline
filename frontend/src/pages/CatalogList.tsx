import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Empty, message, Modal, Popconfirm, Select, Space, Table, Tabs, Tag, Tooltip, Typography, Upload } from 'antd';
import { DeleteOutlined, DownloadOutlined, PauseCircleOutlined, PlayCircleOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import {
  createCatalogExportTaskRuns,
  deleteCatalogTemplateFile,
  downloadOfflineTaskResult,
  downloadTaskRunResult,
  downloadCatalogTemplateFile,
  listCatalogExportCategories,
  listCatalogExportFiles,
  listCatalogProducts,
  listCatalogTemplateCategories,
  listCatalogTemplateFiles,
  updateCatalogTemplateFileStatus,
  uploadCatalogCategoryTemplate,
} from '../api';
import type { CatalogExportCategorySummary, CatalogExportFile, CatalogProduct, CatalogTemplateFileSummary } from '../api';

const { Title, Text } = Typography;
const ALL_CATEGORIES = '__all__';

const CatalogList: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<CatalogProduct[]>([]);
  const [exportFiles, setExportFiles] = useState<CatalogExportFile[]>([]);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [exportFilesLoading, setExportFilesLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [itemsTotal, setItemsTotal] = useState(0);
  const [exportFilesTotal, setExportFilesTotal] = useState(0);
  const [exportView, setExportView] = useState<'products' | 'files'>('products');
  const [selectedCategory, setSelectedCategory] = useState<string>(ALL_CATEGORIES);
  const [exportCategories, setExportCategories] = useState<{ pending: CatalogExportCategorySummary[]; exported: CatalogExportCategorySummary[] }>({ pending: [], exported: [] });
  const [templateCategories, setTemplateCategories] = useState<CatalogExportCategorySummary[]>([]);
  const [templateFiles, setTemplateFiles] = useState<CatalogTemplateFileSummary[]>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [templateUploading, setTemplateUploading] = useState(false);
  const [templateDownloadingFileId, setTemplateDownloadingFileId] = useState<string | null>(null);
  const [templateFileMutatingId, setTemplateFileMutatingId] = useState<string | null>(null);
  const [exportDownloadingTaskId, setExportDownloadingTaskId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<React.Key[]>([]);
  const [selectedItemMap, setSelectedItemMap] = useState<Record<number, CatalogProduct>>({});
  const [activeTab, setActiveTab] = useState('export');
  const itemRequestId = useRef(0);
  const exportFileRequestId = useRef(0);

  const isProductListView = exportView === 'products';
  const isExportFileView = exportView === 'files';
  const currentCategoryOptions = isExportFileView ? exportCategories.exported : [];
  const currentTotal = isProductListView ? itemsTotal : exportFilesTotal;
  const currentLoading = isProductListView ? itemsLoading : exportFilesLoading;
  const isAllCategories = selectedCategory === ALL_CATEGORIES;
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
    setItemsLoading(true);
    try {
      const params = {
        page,
        page_size: pageSize,
        category: !isAllCategories ? selectedCategory : undefined,
      };
      let { data } = await listCatalogProducts(params);
      if (!data.items.length && data.total > 0 && page > 1) {
        const retry = await listCatalogProducts({ ...params, page: 1 });
        data = retry.data;
        setPage(1);
      }
      if (requestId !== itemRequestId.current) return;
      setItems(data.items);
      setItemsTotal(data.total);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载导出商品失败');
    } finally {
      setItemsLoading(false);
    }
  };

  const fetchExportFiles = async () => {
    const requestId = exportFileRequestId.current + 1;
    exportFileRequestId.current = requestId;
    setExportFilesLoading(true);
    try {
      const exportFilePageSize = Math.min(pageSize, 100);
      const params = {
        page,
        page_size: exportFilePageSize,
        category: isExportFileView && !isAllCategories ? selectedCategory : undefined,
      };
      let { data } = await listCatalogExportFiles(params);
      if (!data.items.length && data.total > 0 && page > 1) {
        const retry = await listCatalogExportFiles({ ...params, page: 1 });
        data = retry.data;
        setPage(1);
      }
      if (requestId !== exportFileRequestId.current) return;
      setExportFiles(data.items);
      setExportFilesTotal(data.total);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载导出文件记录失败');
    } finally {
      setExportFilesLoading(false);
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
    const requests: Promise<void>[] = [];
    if (isExportFileView) {
      requests.push(fetchExportCategories());
    }
    if (activeTab === 'templates') {
      requests.push(fetchTemplateCategories());
      requests.push(fetchTemplateFiles());
    }
    await Promise.all(requests);
  };

  const refreshVisibleExportView = async () => {
    await Promise.all([
      refreshExportCenterData(),
      isProductListView ? fetchItems() : fetchExportFiles(),
    ]);
  };

  const scheduleExportCompletionRefresh = () => {
    [3000, 8000, 15000, 30000, 60000].forEach((delay) => {
      window.setTimeout(() => {
        refreshExportCenterData();
        fetchItems();
        if (isExportFileView) {
          fetchExportFiles();
        }
      }, delay);
    });
  };

  useEffect(() => {
    if (isExportFileView) {
      fetchExportCategories();
    }
  }, [exportView]);
  useEffect(() => {
    if (activeTab === 'templates') {
      fetchTemplateCategories();
      fetchTemplateFiles();
    }
  }, [activeTab]);
  useEffect(() => {
    if (isProductListView) {
      fetchItems();
    } else {
      fetchExportFiles();
    }
  }, [page, pageSize, exportView, selectedCategory]);
  useEffect(() => {
    const categories = isExportFileView ? exportCategories.exported : [];
    if (selectedCategory === ALL_CATEGORIES || categories.some((item) => item.category === selectedCategory)) return;
    setSelectedCategory(ALL_CATEGORIES);
    setPage(1);
  }, [exportCategories, exportView]);
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

  const selectExportView = (view: 'products' | 'files') => {
    setExportView(view);
    setSelectedCategory(ALL_CATEGORIES);
    setSelectedIds([]);
    setSelectedItemMap({});
    setPage(1);
    refreshExportCenterData();
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
      const { data } = await createCatalogExportTaskRuns(ids);
      if (data.runs.length) {
        message.success(`已创建 ${data.runs.length} 个新任务中心导出任务，请到新任务中心或已导出列表下载结果`);
        scheduleExportCompletionRefresh();
      } else {
        message.warning('没有创建导出任务，请检查类目模板和商品状态');
      }
      if (data.errors?.length) {
        message.warning(`有 ${data.errors.length} 个商品未进入导出任务，可在任务中心任务详情或接口返回中查看原因`);
      }
      await refreshVisibleExportView();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '创建导出任务失败');
    } finally {
      hideLoading();
      setExporting(false);
    }
  };

  const exportCatalog = async () => {
    if (!selectedIds.length) {
      message.warning('请先勾选要导出的商品');
      return;
    }
    await createExportTasksByIds(
      selectedIds.map(Number),
      `选中的 ${selectedIds.length} 个商品`,
    );
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
    const downloadKey = `catalog-product:${record.id}:${record.export_task_id}`;
    setExportDownloadingTaskId(downloadKey);
    try {
      let response;
      try {
        response = await downloadTaskRunResult(record.export_task_id);
      } catch {
        response = await downloadOfflineTaskResult(record.export_task_id);
      }
      const fallback = record.export_file_path?.split('/').pop() || `catalog_export_${record.export_task_id}.zip`;
      saveBlob(response.data, extractFilename(response.headers['content-disposition'], fallback));
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '下载导出文件失败');
    } finally {
      setExportDownloadingTaskId(null);
    }
  };

  const downloadExportFileResult = async (record: CatalogExportFile) => {
    const downloadKey = `${record.task_source}:${record.task_id}`;
    setExportDownloadingTaskId(downloadKey);
    try {
      const response = record.task_source === 'task_run'
        ? await downloadTaskRunResult(record.task_id)
        : await downloadOfflineTaskResult(record.task_id);
      saveBlob(response.data, extractFilename(response.headers['content-disposition'], record.filename || `catalog_export_${record.task_id}.zip`));
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '下载导出文件失败');
    } finally {
      setExportDownloadingTaskId(null);
    }
  };

  const reExportFileProducts = async (record: CatalogExportFile) => {
    if (!record.catalog_product_ids.length) {
      message.warning('该任务没有可再次导出的商品快照');
      return;
    }
    Modal.confirm({
      title: '确认基于该历史任务再次导出？',
      content: (
        <Space direction="vertical" size={8}>
          <Text>原任务 #{record.task_id}：{record.task_product_count} 个商品，涉及 {record.category_count} 个类目。</Text>
          <Text type="secondary">这会用该历史任务的商品快照创建新的导出任务和新文件；原文件和任务记录会保留。</Text>
          <Text type="secondary">已有真实 ASIN 或其它业务限制会进入新任务 rows/report，不会静默跳过。</Text>
        </Space>
      ),
      okText: '再次导出',
      cancelText: '取消',
      onOk: () => createExportTasksByIds(record.catalog_product_ids, `任务 #${record.task_id} 的 ${record.catalog_product_ids.length} 个商品`),
    });
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

  const exportTaskStatusTag = (status: string) => {
    if (status === 'done') return <Tag color="success">已完成</Tag>;
    if (status === 'partial_failed') return <Tag color="warning">部分完成</Tag>;
    if (status === 'failed') return <Tag color="error">失败</Tag>;
    return <Tag>{status}</Tag>;
  };

  const isCatalogProductExported = (record: CatalogProduct) =>
    Boolean(record.exported_at || record.export_task_id || record.amazon_asin);

  const panelStyle: React.CSSProperties = {
    background: '#fff',
    border: '1px solid #eef0f4',
    borderRadius: 8,
  };

  const exportButtonText = selectedIds.length
    ? `导出选中(${selectedIds.length})`
    : '导出选中';
  const exportDisabled = !selectedIds.length;

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
          {isCatalogProductExported(record) ? <Tag color="success">已导出</Tag> : <Tag color="blue">待导出</Tag>}
          {record.amazon_asin ? <Tag color="purple">真实 ASIN</Tag> : null}
        </Space>
      ),
    },
    {
      title: '导出任务',
      width: 120,
      render: (_: unknown, record: CatalogProduct) => record.export_task_id ? (
        <Button size="small" type="link" onClick={() => navigate('/task-runs')}>
          #{record.export_task_id}
        </Button>
      ) : <Text type="secondary">-</Text>,
    },
    {
      title: '导出时间',
      dataIndex: 'exported_at',
      width: 170,
      render: (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '-',
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
          {isCatalogProductExported(record) && record.export_task_id ? (
            <Button
              size="small"
              icon={<DownloadOutlined />}
              loading={exportDownloadingTaskId === `catalog-product:${record.id}:${record.export_task_id}`}
              onClick={() => downloadExportTaskResult(record)}
            >
              下载
            </Button>
          ) : null}
        </Space>
      ),
    },
  ];
  const exportFileColumns = [
    {
      title: '任务',
      width: 96,
      render: (_: unknown, record: CatalogExportFile) => (
        <Space direction="vertical" size={4}>
          <Button
            size="small"
            type="link"
            style={{ padding: 0 }}
            onClick={() => navigate(record.task_source === 'task_run' ? '/task-runs' : '/offline-tasks')}
          >
            #{record.task_id}
          </Button>
          <Tag color={record.task_source === 'task_run' ? 'blue' : 'default'}>{record.task_source === 'task_run' ? '新任务' : '旧任务'}</Tag>
          {exportTaskStatusTag(record.task_status)}
        </Space>
      ),
    },
    {
      title: '商品统计',
      width: 150,
      render: (_: unknown, record: CatalogExportFile) => (
        <Space direction="vertical" size={2}>
          <Text>文件 {record.file_product_count} / 任务 {record.task_product_count}</Text>
          <Text type="secondary">成功 {record.success_count} · 跳过 {record.skipped_count} · 失败 {record.failed_count}</Text>
        </Space>
      ),
    },
    {
      title: '涉及类目 / 模板',
      render: (_: unknown, record: CatalogExportFile) => (
        <Space direction="vertical" size={4} style={{ width: '100%', minWidth: 0 }}>
          <Space size={[4, 2]} wrap>
            <Tag>{record.category_count} 类</Tag>
            {record.categories.slice(0, 2).map((category) => (
              <Tooltip key={category} title={category}>
                <Tag style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {category}
                </Tag>
              </Tooltip>
            ))}
            {record.categories.length > 2 ? <Tag>+{record.categories.length - 2}</Tag> : null}
          </Space>
          <Tooltip title={record.template_name || ''}>
            <Typography.Text type="secondary" ellipsis style={{ width: '100%' }}>
              {record.template_name || '-'}
            </Typography.Text>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: '导出时间',
      dataIndex: 'exported_at',
      width: 150,
      render: (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      width: 132,
      render: (_: unknown, record: CatalogExportFile) => (
        <Space size={4}>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            disabled={!record.can_download}
            loading={exportDownloadingTaskId === `${record.task_source}:${record.task_id}`}
            onClick={() => downloadExportFileResult(record)}
          >
              下载
          </Button>
          <Button size="small" onClick={() => reExportFileProducts(record)}>
            再次导出
          </Button>
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
        <Button
          icon={<ReloadOutlined />}
          onClick={refreshVisibleExportView}
        >
          查询
        </Button>
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
                      <Space wrap>
                        <Tabs
                          activeKey={exportView}
                          onChange={(value) => selectExportView(value as 'products' | 'files')}
                          items={[
                            { key: 'products', label: '商品列表' },
                            { key: 'files', label: '已导出列表' },
                          ]}
                          style={{ minWidth: 220 }}
                        />
                      </Space>
                      <Space wrap>
                        {isProductListView && selectedIds.length > 0 && (
                          <Button onClick={() => { setSelectedIds([]); setSelectedItemMap({}); }}>
                            清空选择
                          </Button>
                        )}
                        {isProductListView ? (
                          <Button
                            type="primary"
                            icon={<DownloadOutlined />}
                            loading={exporting}
                            disabled={exporting || currentLoading || exportDisabled}
                            onClick={exportCatalog}
                          >
                            {exportButtonText}
                          </Button>
                        ) : null}
                      </Space>
                    </Space>
                    {isProductListView ? (
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(110px, 1fr))', gap: 16, maxWidth: 560 }}>
                        <div>
                          <Text type="secondary">记录口径</Text>
                          <div style={{ marginTop: 6 }}>
                            <Tag color="processing">商品维度</Tag>
                            <Tag color="success">可创建任务</Tag>
                          </div>
                        </div>
                        <div>
                          <Text type="secondary">可选商品</Text>
                          <div style={{ fontSize: 20, fontWeight: 600 }}>{itemsTotal}</div>
                        </div>
                        <div>
                          <Text type="secondary">已选商品</Text>
                          <div style={{ fontSize: 20, fontWeight: 600 }}>{selectedIds.length}</div>
                        </div>
                        <div style={{ gridColumn: '1 / -1' }}>
                          <Text type="secondary">
                            当前列表按商品维度展示；勾选后会按当前数据创建导出任务，历史文件保留。
                          </Text>
                        </div>
                      </div>
                    ) : (
                      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 520px) minmax(0, 1fr)', gap: 20, alignItems: 'start' }}>
                        <Select
                          loading={categoriesLoading}
                          value={selectedCategory}
                          placeholder="选择导出文件涉及类目"
                          onChange={(value) => { setSelectedCategory(value); setPage(1); }}
                          style={{ width: '100%' }}
                          options={[
                            {
                              value: ALL_CATEGORIES,
                              label: `全部导出文件 · ${exportFilesTotal}个 · ${aggregateSummary.categoryCount}个类目`,
                            },
                            ...currentCategoryOptions.map((item) => ({
                              value: item.category,
                              label: `${item.category} · ${item.count}个文件`,
                            })),
                          ]}
                        />
                        {currentCategoryOptions.length ? (
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(110px, 1fr))', gap: 16 }}>
                            <div>
                              <Text type="secondary">记录口径</Text>
                              <div style={{ marginTop: 6 }}>
                                <Tag color="processing">文件/任务维度</Tag>
                              </div>
                            </div>
                            <div>
                              <Text type="secondary">导出文件</Text>
                              <div style={{ fontSize: 20, fontWeight: 600 }}>{exportFilesTotal}</div>
                            </div>
                            <div>
                              <Text type="secondary">涉及类目</Text>
                              <div style={{ fontSize: 20, fontWeight: 600 }}>{aggregateSummary.categoryCount} 个类目</div>
                            </div>
                          </div>
                        ) : (
                          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无导出文件" />
                        )}
                      </div>
                    )}
                  </Space>
                </div>

                <div style={panelStyle}>
                  {isProductListView ? (
                    <Table
                      dataSource={items}
                      columns={columns}
                      rowKey="id"
                      loading={itemsLoading}
                      size="middle"
                      scroll={{ x: 1360 }}
                      locale={{ emptyText: '暂无商品' }}
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
                        total: itemsTotal,
                        showSizeChanger: true,
                        pageSizeOptions: [20, 50, 100, 500, 1000],
                        onChange: (nextPage, nextPageSize) => {
                          setPage(nextPage);
                          setPageSize(Math.min(nextPageSize, 1000));
                        },
                      }}
                    />
                  ) : (
                    <Table
                      dataSource={exportFiles}
                      columns={exportFileColumns}
                      rowKey={(record) => `${record.task_source}:${record.task_id}`}
                      loading={exportFilesLoading}
                      size="middle"
                      tableLayout="fixed"
                      locale={{ emptyText: '暂无导出文件记录；请刷新或检查导出任务是否已完成' }}
                      pagination={{
                        current: page,
                        pageSize: Math.min(pageSize, 100),
                        total: exportFilesTotal,
                        showSizeChanger: true,
                        pageSizeOptions: [20, 50, 100],
                        showTotal: (value) => `共 ${value} 个导出文件/任务`,
                        onChange: (nextPage, nextPageSize) => {
                          setPage(nextPage);
                          setPageSize(nextPageSize);
                        },
                      }}
                    />
                  )}
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
