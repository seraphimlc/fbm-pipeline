import React, { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Table, Button, Tag, Space, Typography, message, Popconfirm, Input, Modal, DatePicker, Image, Select, Tooltip } from 'antd';
import { EditOutlined, ReloadOutlined, PlayCircleOutlined, RedoOutlined, DeleteOutlined, CloudDownloadOutlined, PauseOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  createGigaPullTaskRuns,
  createProductBulkAdvanceTaskByFilter,
  deleteProduct,
  getTaskRun,
  getProduct,
  getWorkbenchOverview,
  listGigaBatches,
  listTaskRuns,
  listProductDataSources,
  listProducts,
  pausePipeline,
  restartPipeline,
  retryProductAutoImageSelection,
  retryProductCompetitorSearch,
  retryProductCompetitorVisualMatch,
  resumePipeline,
  retryStep,
  STEP_LABELS,
} from '../api';
import type { GigaSyncBatch, Product, TaskRunDetail, WorkbenchOverview } from '../api';
import type { ProductDataSource } from '../api';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;
const PRODUCT_LIST_RETURN_KEY = 'fbm.productList.returnPath';
const PRODUCT_DATA_SOURCE_KEY = 'fbm.productList.dataSourceId';
const RUNNING_STATUSES = [
  'step1_collecting',
  'step2_pricing',
  'step3_keywords',
  'step4_category',
  'step5_listing',
  'step6_curating',
];

type WorkStatus =
  | 'auto_select_images'
  | 'select_images'
  | 'competitor_searching'
  | 'select_competitor'
  | 'capture_detail'
  | 'ready_to_generate'
  | 'running'
  | 'interrupted'
  | 'suspended'
  | 'manual_review'
  | 'export_ready'
  | 'exported'
  | 'failed';

type ProductRow = {
  key: string;
  product: Product;
  workStatus: WorkStatus;
};

type SkuState = {
  loading: boolean;
  items: any[];
};

const WORK_STATUS_META: Record<WorkStatus, { label: string; shortLabel: string; color: string; action: string }> = {
  auto_select_images: { label: '自动选图中', shortLabel: '自动选图', color: 'processing', action: '任务中心' },
  select_images: { label: '待确认商品图片', shortLabel: '确认图片', color: 'cyan', action: '去确认图片' },
  competitor_searching: { label: '搜索候选竞品中', shortLabel: '搜索中', color: 'processing', action: '等待搜索' },
  select_competitor: { label: '待搜索/选择竞品', shortLabel: '选竞品', color: 'purple', action: '去选竞品' },
  capture_detail: { label: '抓取竞品详情中', shortLabel: '抓详情', color: 'processing', action: '等待抓取' },
  ready_to_generate: { label: '待自动生成 Listing', shortLabel: '待自动生成', color: 'warning', action: '自动入队' },
  running: { label: '生成中', shortLabel: '生成中', color: 'processing', action: '等待完成' },
  interrupted: { label: '已中断', shortLabel: '已中断', color: 'warning', action: '重试' },
  suspended: { label: '已挂起', shortLabel: '已挂起', color: 'default', action: '继续' },
  manual_review: { label: '待人工处理', shortLabel: '人工处理', color: 'warning', action: '继续' },
  export_ready: { label: '待导出', shortLabel: '待导出', color: 'success', action: '去导出' },
  exported: { label: '已导出可重导', shortLabel: '已导出', color: 'green', action: '去重导' },
  failed: { label: '失败', shortLabel: '失败', color: 'error', action: '查看错误' },
};

const WORK_STATUS_FILTERS: Array<'all' | WorkStatus> = [
  'all',
  'auto_select_images',
  'select_images',
  'select_competitor',
  'competitor_searching',
  'capture_detail',
  'ready_to_generate',
  'running',
  'interrupted',
  'suspended',
  'manual_review',
  'export_ready',
  'exported',
  'failed',
];

const PRIMARY_WORK_STATUS: WorkStatus[] = [
  'auto_select_images',
  'select_images',
  'select_competitor',
  'ready_to_generate',
  'running',
  'export_ready',
  'failed',
];

const workStatusParam = (value: string | null): 'all' | WorkStatus => (
  value && WORK_STATUS_FILTERS.includes(value as WorkStatus) ? (value as 'all' | WorkStatus) : 'all'
);

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

const parseJson = <T,>(value: string | null | undefined, fallback: T): T => {
  if (!value) return fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
};

const moneyText = (value: number | null | undefined, currency?: string | null) => {
  if (value === null || value === undefined) return '-';
  return `${currency || 'USD'} ${Number(value).toFixed(2)}`;
};

const imageProxyUrl = (localPath: string | null | undefined) => (
  localPath ? `/api/images/${localPath}` : ''
);

const taskRunStatusSummary = (task: TaskRunDetail | null) => {
  if (!task) return null;
  const summary = parseJson<Record<string, any>>(task.summary_json, {});
  const sourceName = summary.data_source_name || '店铺';
  if (['failed', 'interrupted'].includes(task.status)) {
    const failedGroup = task.groups.find((group) => ['failed', 'interrupted'].includes(group.status));
    const failedStep = failedGroup?.steps?.find((step) => ['failed', 'interrupted'].includes(step.status));
    return {
      color: 'error',
      title: '店铺商品同步失败',
      text: `${sourceName} 同步没有完成：${failedStep?.error_message || '请到新任务中心查看错误原因'}`,
    };
  }
  if (task.status === 'running') {
    const runningGroup = task.groups.find((group) => group.status === 'running');
    return {
      color: 'processing',
      title: '正在同步店铺商品',
      text: `${sourceName} 正在执行 ${runningGroup?.title || '任务图'}；SKU ${summary.sku_count ?? '-'}，严格串行执行。`,
    };
  }
  if (task.status === 'succeeded') {
    return {
      color: 'success',
      title: '店铺商品同步完成',
      text: `${sourceName} 已同步 SKU ${summary.sku_count ?? '-'}、Item ${summary.item_count ?? '-'}，新建 ${summary.product_created ?? 0}，更新 ${summary.product_updated ?? 0}。`,
    };
  }
  return null;
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
  const [skuInput, setSkuInput] = useState(initialSearch.get('sku_code') || '');
  const [itemId, setItemId] = useState(initialSearch.get('item_id') || '');
  const [competitorAsin, setCompetitorAsin] = useState(initialSearch.get('competitor_asin') || '');
  const [upc, setUpc] = useState(initialSearch.get('upc') || '');
  const [skuCode, setSkuCode] = useState(initialSearch.get('sku_code') || '');
  const [dateRangeInput, setDateRangeInput] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(initialDateRange);
  const [dateRange, setDateRange] = useState<[string, string] | null>(
    initialDateRange ? [initialDateRange[0].startOf('day').toISOString(), initialDateRange[1].endOf('day').toISOString()] : null
  );
  const [statusFilter, setStatusFilter] = useState<string | undefined>(initialSearch.get('status') || undefined);
  const [generationStatusFilter, setGenerationStatusFilter] = useState<'all' | WorkStatus>(
    workStatusParam(initialSearch.get('work_status'))
  );
  const [overview, setOverview] = useState<WorkbenchOverview | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [dataSources, setDataSources] = useState<ProductDataSource[]>([]);
  const [selectedDataSourceId, setSelectedDataSourceId] = useState<number | undefined>(() => {
    const saved = Number(window.localStorage.getItem(PRODUCT_DATA_SOURCE_KEY) || '');
    return Number.isFinite(saved) && saved > 0 ? saved : undefined;
  });
  const [gigaSyncBatches, setGigaSyncBatches] = useState<GigaSyncBatch[]>([]);
  const [latestGigaPullTask, setLatestGigaPullTask] = useState<TaskRunDetail | null>(null);
  const [expandedRowKeys, setExpandedRowKeys] = useState<React.Key[]>([]);
  const [skuState, setSkuState] = useState<Record<string, SkuState>>({});
  const [creatingBulkAdvanceTask, setCreatingBulkAdvanceTask] = useState(false);
  const [rerunningId, setRerunningId] = useState<number | null>(null);
  const [pullingGigaProducts, setPullingGigaProducts] = useState(false);
  const [pullModalOpen, setPullModalOpen] = useState(false);
  const [selectedPullDataSourceIds, setSelectedPullDataSourceIds] = useState<number[]>([]);
  const activeDataSource = useMemo(
    () => dataSources.find((source) => source.id === selectedDataSourceId),
    [dataSources, selectedDataSourceId],
  );
  const activeSalesChannel = (activeDataSource?.sales_channel || 'amazon').toLowerCase();
  const isTikTokSource = activeSalesChannel === 'tiktok';
  const activeSite = activeDataSource?.site || 'US';
  const activeGigaSyncBatch = useMemo(
    () => gigaSyncBatches.find((batch) => ['pending', 'running'].includes(batch.status)),
    [gigaSyncBatches],
  );
  const latestGigaPullTaskMatchesSelectedSource = useMemo(() => {
    if (!latestGigaPullTask || !selectedDataSourceId) return Boolean(latestGigaPullTask);
    const payload = parseJson<Record<string, any>>(latestGigaPullTask.payload_json, {});
    return Number(payload.data_source_id || 0) === selectedDataSourceId;
  }, [latestGigaPullTask, selectedDataSourceId]);
  const latestGigaPullSummary = useMemo(
    () => taskRunStatusSummary(latestGigaPullTaskMatchesSelectedSource ? latestGigaPullTask : null),
    [latestGigaPullTask, latestGigaPullTaskMatchesSelectedSource],
  );

  const isProductExported = (product: Product) => Boolean(product.catalog_exported_at || product.catalog_export_task_id);
  const isInterruptedProduct = (product: Product) => (
    RUNNING_STATUSES.includes(product.status)
    && /运行状态已中断|未在当前服务中运行/.test(product.current_task_status || '')
  );

  const productWorkStatus = (product: Product): WorkStatus => {
    const workflowStatus = product.workflow?.work_status;
    if (workflowStatus && WORK_STATUS_FILTERS.includes(workflowStatus as WorkStatus)) return workflowStatus as WorkStatus;
    if (product.status === 'failed') return 'failed';
    if (product.status === 'paused') return 'suspended';
    if (product.status === 'competitor_searching') return 'competitor_searching';
    if (product.status === 'step5_listing' && /竞品.*抓取中|Listing.*抓取中/i.test(product.error_message || '')) return 'capture_detail';
    if (isInterruptedProduct(product)) return 'interrupted';
    if (RUNNING_STATUSES.includes(product.status)) return 'running';
    if (product.status === 'completed') return isProductExported(product) ? 'exported' : 'export_ready';
    if (product.status === 'pending_review') return 'manual_review';
    if (product.status === 'created' && (product.current_step || 0) <= 0) return 'select_images';
    if (product.status === 'created' && !product.competitor_asin) return 'select_competitor';
    if (product.status === 'created') return 'ready_to_generate';
    return 'running';
  };

  const rows = useMemo<ProductRow[]>(() => (
    products
      .map((product) => ({ key: `product:${product.id}`, product, workStatus: productWorkStatus(product) }))
  ), [products]);

  const visibleRows = rows;

  const buildListPath = () => {
    const params = new URLSearchParams();
    if (page > 1) params.set('page', String(page));
    if (pageSize !== 20) params.set('page_size', String(pageSize));
    if (statusFilter) params.set('status', statusFilter);
    if (generationStatusFilter !== 'all') params.set('work_status', generationStatusFilter);
    if (itemId) params.set('item_id', itemId);
    if (competitorAsin) params.set('competitor_asin', competitorAsin);
    if (upc) params.set('upc', upc);
    if (skuCode) params.set('sku_code', skuCode);
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
    const detailPath = isTikTokSource ? `/tiktok/products/${productId}` : `/products/${productId}`;
    window.open(detailPath, '_blank', 'noopener,noreferrer');
  };

  const reviewPath = (path: string, productId?: number) => {
    const params = new URLSearchParams();
    if (selectedDataSourceId) params.set('data_source_id', String(selectedDataSourceId));
    if (productId) params.set('product_id', String(productId));
    return `${path}${params.toString() ? `?${params.toString()}` : ''}`;
  };

  const openReviewPage = (path: string, productId?: number) => {
    window.open(reviewPath(path, productId), '_blank', 'noopener,noreferrer');
  };

  const retryAutoImageSelection = async (productId: number) => {
    setRerunningId(productId);
    try {
      await retryProductAutoImageSelection(productId);
      await refreshWorkbenchRows();
      message.success('已创建或复用自动选图任务');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '重试自动选图失败');
    } finally {
      setRerunningId(null);
    }
  };

  const retryCompetitorSearch = async (productId: number) => {
    setRerunningId(productId);
    try {
      await retryProductCompetitorSearch(productId);
      await refreshWorkbenchRows();
      message.success('已创建或复用自动竞品搜索任务');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '启动自动竞品搜索失败');
    } finally {
      setRerunningId(null);
    }
  };

  const retryCompetitorVisualMatch = async (productId: number) => {
    setRerunningId(productId);
    try {
      await retryProductCompetitorVisualMatch(productId);
      await refreshWorkbenchRows();
      message.success('已创建或复用竞品视觉初筛任务');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '启动竞品视觉初筛失败');
    } finally {
      setRerunningId(null);
    }
  };

  const handleWorkStatusClick = (value: 'all' | WorkStatus) => {
    setGenerationStatusFilter(value);
    setPage(1);
  };

  const fetchProducts = async () => {
    if (!selectedDataSourceId) return;
    setLoading(true);
    try {
      const { data } = await listProducts({
        page,
        page_size: pageSize,
        item_id: itemId.trim() || undefined,
        competitor_asin: isTikTokSource ? undefined : competitorAsin.trim() || undefined,
        upc: isTikTokSource ? undefined : upc.trim() || undefined,
        status: statusFilter,
        work_status: generationStatusFilter === 'all' ? undefined : generationStatusFilter,
        sku_code: skuCode.trim() || undefined,
        data_source_id: selectedDataSourceId,
        created_from: dateRange?.[0],
        created_to: dateRange?.[1],
      });
      setProducts(data.items);
      setTotal(data.total);
    } catch {
      message.error('加载失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchOverview = async () => {
    if (!selectedDataSourceId) return;
    try {
      const { data } = await getWorkbenchOverview({ data_source_id: selectedDataSourceId });
      setOverview(data);
    } catch {
      // 概览失败不影响列表。
    }
  };

  const fetchDataSources = async () => {
    try {
      const { data } = await listProductDataSources({ platform: 'giga', enabled: true, page: 1, page_size: 100 });
      setDataSources(data.items);
      setSelectedDataSourceId((current) => {
        if (current && data.items.some((source) => source.id === current)) return current;
        const first = data.items[0]?.id;
        if (first) window.localStorage.setItem(PRODUCT_DATA_SOURCE_KEY, String(first));
        return first;
      });
    } catch {
      message.error('加载店铺失败');
    }
  };

  const fetchGigaSyncBatches = async () => {
    if (!selectedDataSourceId) {
      setGigaSyncBatches([]);
      return;
    }
    try {
      const { data } = await listGigaBatches({
        site: activeSite,
        data_source_id: selectedDataSourceId,
        page: 1,
        page_size: 6,
      });
      setGigaSyncBatches(data.items);
    } catch {
      // 只作为提示，不影响商品列表。
    }
  };

  const fetchLatestGigaPullTask = async () => {
    try {
      const { data } = await listTaskRuns({ task_type: 'giga_pull', page: 1, page_size: 1 });
      const latest = data.items[0];
      if (!latest) {
        setLatestGigaPullTask(null);
        return;
      }
      const detail = await getTaskRun(latest.id);
      setLatestGigaPullTask(detail.data);
    } catch {
      // 新任务提示不影响主流程。
    }
  };

  const refreshWorkbenchRows = async () => {
    await Promise.all([
      fetchProducts(),
      fetchOverview(),
    ]);
  };

  const refreshTaskHints = async () => {
    await Promise.all([
      fetchGigaSyncBatches(),
      fetchLatestGigaPullTask(),
    ]);
  };

  const refreshWorkbenchWithHints = async () => {
    await Promise.all([
      fetchProducts(),
      fetchOverview(),
      fetchGigaSyncBatches(),
      fetchLatestGigaPullTask(),
    ]);
  };

  useEffect(() => { fetchProducts(); }, [page, pageSize, itemId, competitorAsin, upc, statusFilter, generationStatusFilter, dateRange, selectedDataSourceId, isTikTokSource]);
  useEffect(() => { fetchDataSources(); }, []);
  useEffect(() => { fetchOverview(); }, [selectedDataSourceId]);
  useEffect(() => {
    if (!activeGigaSyncBatch && !['pending', 'running'].includes(latestGigaPullTask?.status || '')) return;
    const timer = window.setInterval(() => {
      refreshTaskHints();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [activeGigaSyncBatch?.batch_id, latestGigaPullTask?.id, latestGigaPullTask?.status, selectedDataSourceId, activeSite]);
  useEffect(() => {
    const params = new URLSearchParams();
    if (page > 1) params.set('page', String(page));
    if (pageSize !== 20) params.set('page_size', String(pageSize));
    if (statusFilter) params.set('status', statusFilter);
    if (generationStatusFilter !== 'all') params.set('work_status', generationStatusFilter);
    if (itemId) params.set('item_id', itemId);
    if (competitorAsin) params.set('competitor_asin', competitorAsin);
    if (upc) params.set('upc', upc);
    if (skuCode) params.set('sku_code', skuCode);
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
  }, [page, pageSize, itemId, competitorAsin, upc, statusFilter, generationStatusFilter, dateRange, skuCode, location.pathname, location.search, navigate]);

  const handleSearch = () => {
    setItemId(itemIdInput.trim());
    setCompetitorAsin(competitorAsinInput.trim());
    setUpc(upcInput.trim());
    setSkuCode(skuInput.trim());
    setDateRange(dateRangeInput ? [dateRangeInput[0].startOf('day').toISOString(), dateRangeInput[1].endOf('day').toISOString()] : null);
    setPage(1);
  };

  const resetFilters = () => {
    setItemIdInput('');
    setCompetitorAsinInput('');
    setUpcInput('');
    setSkuInput('');
    setItemId('');
    setCompetitorAsin('');
    setUpc('');
    setSkuCode('');
    setDateRangeInput(null);
    setDateRange(null);
    setStatusFilter(undefined);
    setGenerationStatusFilter('all');
    setPage(1);
  };

  const openPullModal = () => {
    setSelectedPullDataSourceIds(selectedDataSourceId ? [selectedDataSourceId] : []);
    setPullModalOpen(true);
  };

  const pullMissingGigaProducts = async () => {
    if (!selectedPullDataSourceIds.length) {
      message.warning('请选择要同步的大健店铺');
      return;
    }
    setPullingGigaProducts(true);
    try {
      const { data } = await createGigaPullTaskRuns({ data_source_ids: selectedPullDataSourceIds });
      const firstRun = data.runs[0];
      message.success(`已提交新任务中心：${data.runs.map((run) => `#${run.id}`).join('、')}`);
      const detail = await getTaskRun(firstRun.id);
      setLatestGigaPullTask(detail.data);
      setPullModalOpen(false);
      await refreshWorkbenchRows();
      navigate('/task-runs');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '提交店铺商品同步失败');
    } finally {
      setPullingGigaProducts(false);
    }
  };

  const serverFilterSummary = () => {
    const statusLabels: Record<string, string> = {
      created: '待处理',
      competitor_searching: '搜索候选竞品中',
      paused: '已挂起',
      pending_review: '待人工确认',
      completed: '已生成 Listing',
      failed: '失败',
    };
    const lines = [
      '预计提交商品：当前服务端筛选命中的前 1000 个商品',
      `店铺：${activeDataSource?.name || (selectedDataSourceId ? `店铺 #${selectedDataSourceId}` : '全部店铺')}`,
      `处理状态：${statusFilter ? statusLabels[statusFilter] || statusFilter : '全部'}`,
      `工作状态：${generationStatusFilter === 'all' ? '全部' : WORK_STATUS_META[generationStatusFilter].label}`,
    ];
    if (itemId.trim()) lines.push(`Item ID：${itemId.trim()}`);
    if (competitorAsin.trim()) lines.push(`竞品 ASIN：${competitorAsin.trim()}`);
    if (upc.trim()) lines.push(`UPC：${upc.trim()}`);
    if (skuCode.trim()) lines.push(`SKU / Item Code 关键词：${skuCode.trim()}`);
    if (dateRange) lines.push(`创建时间：${dayjs(dateRange[0]).format('YYYY-MM-DD')} 至 ${dayjs(dateRange[1]).format('YYYY-MM-DD')}`);
    lines.push('工作状态会按服务端同一口径筛选，避免只提交当前页。');
    return lines;
  };

  const createBulkAdvanceTaskForCurrentFilter = async () => {
    Modal.confirm({
      title: '确认创建批量推进审计任务？',
      content: (
        <Space direction="vertical" size={6}>
          {serverFilterSummary().map((line) => <Text key={line} type={line.startsWith('下方') ? 'secondary' : undefined}>{line}</Text>)}
          <Text type="secondary">任务只会启动满足前置条件的商品；未确认图片、未选竞品等商品会写入 rows/report，不会被直接改到待导出。</Text>
        </Space>
      ),
      okText: '创建任务',
      cancelText: '取消',
      onOk: async () => {
        setCreatingBulkAdvanceTask(true);
        const hideLoading = message.loading('正在按当前筛选创建批量推进审计任务...', 0);
        try {
          const { data } = await createProductBulkAdvanceTaskByFilter({
            item_id: itemId.trim() || undefined,
            competitor_asin: competitorAsin.trim() || undefined,
            upc: upc.trim() || undefined,
            status: statusFilter,
            work_status: generationStatusFilter === 'all' ? undefined : generationStatusFilter,
            data_source_id: selectedDataSourceId,
            created_from: dateRange?.[0],
            created_to: dateRange?.[1],
            sku_keyword: skuCode.trim() || undefined,
            limit: 1000,
          });
          const result = parseJson<{ requested_count?: number; started_count?: number; skipped_count?: number }>(data.summary_json, {});
          message.success(`已创建任务中心 #${data.id}：提交 ${result.requested_count || 0}，入队 ${result.started_count || 0}，跳过 ${result.skipped_count || 0}`);
          await refreshWorkbenchRows();
          navigate('/task-runs');
        } catch (error: any) {
          message.error(error?.response?.data?.detail || '创建批量推进任务失败');
        } finally {
          hideLoading();
          setCreatingBulkAdvanceTask(false);
        }
      },
    });
  };

  const handleDeleteProduct = async (record: Product) => {
    setDeletingId(record.id);
    try {
      await deleteProduct(record.id);
      message.success('商品已删除');
      if (products.length === 1 && page > 1) setPage(page - 1);
      await refreshWorkbenchRows();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  const fetchRowSkus = async (row: ProductRow) => {
    const existing = skuState[row.key];
    if (existing?.loading || existing?.items.length) return;
    setSkuState((prev) => ({ ...prev, [row.key]: { loading: true, items: prev[row.key]?.items || [] } }));
    try {
      const { data } = await getProduct(row.product.id);
      const variants = parseJson<any[]>(data.data?.variants, []);
      setSkuState((prev) => ({ ...prev, [row.key]: { loading: false, items: Array.isArray(variants) ? variants : [] } }));
    } catch {
      message.error('加载商品 SKU 明细失败');
      setSkuState((prev) => ({ ...prev, [row.key]: { loading: false, items: [] } }));
    }
  };

  const suspendProductTask = async (productId: number) => {
    try {
      await pausePipeline(productId);
      message.success('已挂起，后续自动流程不会继续执行');
      await refreshWorkbenchRows();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '挂起失败');
    }
  };

  const resumeProductTask = async (productId: number) => {
    try {
      await resumePipeline(productId);
      message.success('已继续执行');
      await refreshWorkbenchRows();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '继续失败');
    }
  };

  const workStatusTag = (status: WorkStatus) => {
    const meta = WORK_STATUS_META[status];
    return <Tag color={meta.color}>{meta.label}</Tag>;
  };

  const workflowStatusTag = (product: Product, fallback: WorkStatus) => {
    const workflow = product.workflow;
    if (!workflow) return workStatusTag(fallback);
    return (
      <Tooltip title={workflow.action_reason || workflow.label}>
        <Tag color={workflow.color || WORK_STATUS_META[fallback]?.color || 'default'}>{workflow.label}</Tag>
      </Tooltip>
    );
  };

  const currentTaskStatus = (record: Product) => {
    if (isTikTokSource) {
      if (record.status === 'failed' && record.error_message) return `失败：${record.error_message}`;
      if (record.catalog_exported_at || record.catalog_export_task_id) return '已导出，可在 TikTok 导出链路接入后再次导出';
      if (record.status === 'completed') return '待 TikTok 导出';
      if (record.status === 'created') return '待补资料或待定价';
      return record.current_task_status || record.status || '-';
    }
    if (record.workflow?.action_reason) return record.workflow.action_reason;
    if (record.status === 'completed' && isProductExported(record)) {
      return record.catalog_export_task_id
        ? `已导出，可在导出中心再次导出（任务 #${record.catalog_export_task_id}）`
        : '已导出，可在导出中心再次导出';
    }
    if (record.current_task_status) return record.current_task_status;
    if (record.status === 'paused') return '已挂起：不会继续执行后续自动流程';
    if (record.status === 'failed' && record.error_message) return `失败：${record.error_message}`;
    if (record.status === 'pending_review' && record.error_message) return `待人工处理：${record.error_message}`;
    if (record.status === 'source_unavailable' && record.error_message) return `原商品下架停止采集：${record.error_message}`;
    if (record.status === 'unavailable' && record.error_message) return `商品已下架：${record.error_message}`;
    return STEP_LABELS[record.current_step] || record.status || '-';
  };

  const renderSkuExpandedRow = (row: ProductRow) => {
    const state = skuState[row.key] || { loading: false, items: [] };
    return (
      <Table
        size="small"
        rowKey={(sku) => sku.sku || sku.title || JSON.stringify(sku)}
        columns={[
          {
            title: '图',
            dataIndex: 'main_image_url',
            width: 72,
            render: (value: string | null) => value ? (
              <Image src={value.startsWith('/') ? imageProxyUrl(value) : value} width={44} height={44} style={{ objectFit: 'cover', borderRadius: 4 }} />
            ) : '-',
          },
          {
            title: 'SKU',
            dataIndex: 'sku',
            width: 150,
            render: (value: string, record: any) => (
              <Space size={4}>
                <Text strong={Boolean(record.item_code && record.sku === record.item_code)}>{value || '-'}</Text>
                {record.item_code && record.sku === record.item_code ? <Tag color="green">主</Tag> : null}
              </Space>
            ),
          },
          {
            title: '变体属性',
            dataIndex: 'variation_attributes',
            width: 320,
            render: (value: any) => {
              const entries = Object.entries(value || {}).filter(([, v]) => v);
              return entries.length ? <Space wrap>{entries.map(([k, v]) => <Tag key={k}>{k}: {String(v)}</Tag>)}</Space> : '-';
            },
          },
          { title: '价格', width: 110, render: (_: unknown, record: any) => moneyText(record.price, record.currency || 'USD') },
          { title: '运费', width: 110, render: (_: unknown, record: any) => moneyText(record.shipping_fee, record.currency || 'USD') },
          { title: '库存', dataIndex: 'stock', width: 90, render: (value: number | null) => value ?? '-' },
          { title: 'SKU 标题', dataIndex: 'title', ellipsis: true, render: (value: string | null) => value || '-' },
        ]}
        dataSource={state.items}
        loading={state.loading}
        pagination={false}
        scroll={{ x: 1200 }}
        locale={{ emptyText: '暂无 Product SKU 明细' }}
      />
    );
  };

  const renderPrimaryRowAction = (row: ProductRow) => {
    const product = row.product;
    if (isTikTokSource) return null;
    const workflowAction = product.workflow?.primary_action;
    const workflowActionLabel = product.workflow?.primary_action_label;
    if (workflowAction) {
      const label = workflowActionLabel || '处理';
      if (workflowAction === 'open_image_review') {
        return <Button size="small" type="primary" onClick={() => openReviewPage('/products/image-review', product.id)}>{label}</Button>;
      }
      if (workflowAction === 'open_task_center') {
        const correlationKey = product.workflow?.related_correlation_key;
        const target = correlationKey ? `/task-runs?correlation_key=${encodeURIComponent(correlationKey)}` : '/task-runs';
        return <Button size="small" onClick={() => navigate(target)}>{label}</Button>;
      }
      if (workflowAction === 'retry_auto_image_selection') {
        return (
          <Button
            size="small"
            type="primary"
            icon={<RedoOutlined />}
            loading={rerunningId === product.id}
            onClick={() => retryAutoImageSelection(product.id)}
          >
            {label}
          </Button>
        );
      }
      if (workflowAction === 'start_competitor_search' || workflowAction === 'retry_competitor_search' || workflowAction === 'restart_competitor_search') {
        return (
          <Button
            size="small"
            type="primary"
            icon={<RedoOutlined />}
            loading={rerunningId === product.id}
            onClick={() => retryCompetitorSearch(product.id)}
          >
            {label}
          </Button>
        );
      }
      if (workflowAction === 'retry_competitor_visual_match') {
        return (
          <Button
            size="small"
            type="primary"
            icon={<RedoOutlined />}
            loading={rerunningId === product.id}
            onClick={() => retryCompetitorVisualMatch(product.id)}
          >
            {label}
          </Button>
        );
      }
      if (workflowAction === 'manual_adjust_images') {
        return <Button size="small" onClick={() => openReviewPage('/products/image-review', product.id)}>{label}</Button>;
      }
      if (workflowAction === 'open_export_center') {
        return <Button size="small" type="primary" onClick={() => navigate('/export-center')}>{label}</Button>;
      }
      if (workflowAction === 'retry') {
        return (
          <Button
            size="small"
            type="primary"
            icon={<RedoOutlined />}
            loading={rerunningId === product.id}
            onClick={async () => { setRerunningId(product.id); try { await retryStep(product.id); await refreshWorkbenchRows(); } finally { setRerunningId(null); } }}
          >
            {label}
          </Button>
        );
      }
      if (workflowAction === 'resume') {
        return <Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={() => resumeProductTask(product.id)}>{label}</Button>;
      }
      if (workflowAction === 'open_detail') {
        return <Button size="small" type="primary" onClick={() => openProductDetail(product.id)}>{label}</Button>;
      }
      return null;
    }
    if (product.workflow) return null;
    if (row.workStatus === 'select_images') {
      return (
        <Button size="small" type="primary" onClick={() => openReviewPage('/products/image-review', product.id)}>
          确认图片
        </Button>
      );
    }
    if (row.workStatus === 'select_competitor') {
      return (
        <Button size="small" type="primary" onClick={() => openProductDetail(product.id)}>
          查看
        </Button>
      );
    }
    if (row.workStatus === 'ready_to_generate') {
      return <Button size="small" onClick={() => navigate('/task-runs')}>任务中心</Button>;
    }
    if (row.workStatus === 'interrupted') {
      return (
        <Button
          size="small"
          type="primary"
          icon={<RedoOutlined />}
          loading={rerunningId === product.id}
          onClick={async () => { setRerunningId(product.id); try { await retryStep(product.id); await refreshWorkbenchRows(); } finally { setRerunningId(null); } }}
        >
          重试
        </Button>
      );
    }
    if (product.status === 'paused' || product.status === 'pending_review') {
      return (
        <Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={() => resumeProductTask(product.id)}>
          继续
        </Button>
      );
    }
    if (row.workStatus === 'export_ready' || row.workStatus === 'exported') {
      return (
        <Button size="small" type="primary" onClick={() => navigate('/export-center')}>
          {row.workStatus === 'exported' ? '重导' : '导出'}
        </Button>
      );
    }
    if (product.status === 'failed' && product.current_step > 1) {
      return (
        <Button size="small" type="primary" icon={<RedoOutlined />} onClick={async () => { await retryStep(product.id); await refreshWorkbenchRows(); }}>
          重试
        </Button>
      );
    }
    return null;
  };

  const columns = [
    {
      title: '商品Code',
      width: 150,
      render: (_: unknown, row: ProductRow) => (
        <a onClick={() => openProductDetail(row.product.id)}>
          {row.product.item_code || row.product.source_item_id || row.product.gigab2b_product_id || row.product.id}
        </a>
      ),
    },
    !isTikTokSource ? {
      title: '参考竞品',
      width: 150,
      render: (_: unknown, row: ProductRow) => row.product.competitor_asin || <Text type="secondary">未选</Text>,
    } : null,
    !isTikTokSource ? {
      title: 'UPC',
      width: 150,
      render: (_: unknown, row: ProductRow) => row.product.upc || '-',
    } : null,
    {
      title: '标题',
      width: 360,
      ellipsis: true,
      render: (_: unknown, row: ProductRow) => row.product.title || '-',
    },
    {
      title: '状态',
      width: 140,
      render: (_: unknown, row: ProductRow) => {
        if (!isTikTokSource) return workflowStatusTag(row.product, row.workStatus);
        if (row.product.status === 'failed') return <Tag color="error">失败</Tag>;
        if (row.product.catalog_exported_at || row.product.catalog_export_task_id) return <Tag color="green">已导出</Tag>;
        if (row.product.status === 'completed') return <Tag color="success">待导出</Tag>;
        if (row.product.status === 'created') return <Tag color="warning">待补资料</Tag>;
        return <Tag color="processing">{row.product.status || '处理中'}</Tag>;
      },
    },
    {
      title: '状态说明',
      width: 260,
      ellipsis: true,
      render: (_: unknown, row: ProductRow) => {
        const text = currentTaskStatus(row.product);
        return <Text title={text} style={{ maxWidth: 240, display: 'block' }} ellipsis>{text}</Text>;
      },
    },
    {
      title: '创建时间',
      width: 170,
      render: (_: unknown, row: ProductRow) => row.product.created_at ? new Date(row.product.created_at).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      width: 340,
      fixed: 'right' as const,
      render: (_: unknown, row: ProductRow) => {
        const product = row.product;
        const workflowAllowedActions = product.workflow?.allowed_actions || [];
        const hasWorkflow = !isTikTokSource && Boolean(product.workflow);
        const canRestartProduct = hasWorkflow
          ? workflowAllowedActions.includes('restart')
          : !isTikTokSource && !RUNNING_STATUSES.includes(product.status) && row.workStatus !== 'select_images';
        const canSuspendProduct = hasWorkflow
          ? workflowAllowedActions.includes('pause')
          : !isTikTokSource && (
            ['ready_to_generate', 'manual_review', 'failed'].includes(row.workStatus)
            || (row.workStatus === 'suspended' && product.status !== 'paused')
          );
        const primaryIsDetail = !isTikTokSource && product.workflow?.primary_action === 'open_detail';
        const canManualAdjustImages = hasWorkflow
          && workflowAllowedActions.includes('manual_adjust_images')
          && product.workflow?.primary_action !== 'manual_adjust_images';
        const canRestartCompetitorSearch = hasWorkflow
          && workflowAllowedActions.includes('restart_competitor_search')
          && product.workflow?.primary_action !== 'restart_competitor_search';
        const primaryAction = renderPrimaryRowAction(row);
        return (
          <Space size="small">
            {primaryAction}
            {canManualAdjustImages ? (
              <Button size="small" icon={<EditOutlined />} onClick={() => openReviewPage('/products/image-review', product.id)}>
                手动调图
              </Button>
            ) : null}
            {canRestartCompetitorSearch ? (
              <Button
                size="small"
                icon={<RedoOutlined />}
                loading={rerunningId === product.id}
                onClick={() => retryCompetitorSearch(product.id)}
              >
                重搜竞品
              </Button>
            ) : null}
            {!primaryIsDetail ? <Button size="small" onClick={() => openProductDetail(product.id)}>详情</Button> : null}
            {canSuspendProduct ? (
              <Popconfirm
                title="挂起这个商品？"
                description="挂起后不会继续执行后续自动流程，之后可以点继续恢复。"
                okText="挂起"
                cancelText="取消"
                onConfirm={() => suspendProductTask(product.id)}
              >
                <Button size="small" icon={<PauseOutlined />}>挂起</Button>
              </Popconfirm>
            ) : null}
            {canRestartProduct && (
              <Popconfirm
                title="确定重新开始流程？"
                description="会保留已使用图片，清空旧候选竞品、已选竞品和后续生成结果；有主图时会重新搜索候选竞品。"
                okText="重新开始"
                cancelText="取消"
                onConfirm={async () => { await restartPipeline(product.id); await refreshWorkbenchRows(); }}
              >
                <Tooltip title="重新开始流程">
                  <Button size="small" icon={<RedoOutlined />} />
                </Tooltip>
              </Popconfirm>
            )}
            <Popconfirm title="确定删除？" okText="删除" cancelText="取消" onConfirm={() => handleDeleteProduct(product)}>
              <Tooltip title="删除商品">
                <Button size="small" danger icon={<DeleteOutlined />} loading={deletingId === product.id} />
              </Tooltip>
            </Popconfirm>
          </Space>
        );
      },
    },
  ].filter((column): column is Exclude<typeof column, null> => column !== null);

  const pageStatusCounts = (status: WorkStatus) => rows.filter((row) => row.workStatus === status).length;
  const overviewStatusCounts = (status: WorkStatus) => {
    if (!overview) return pageStatusCounts(status);
    if (status === 'exported') return Number(overview.export_ready_exported ?? pageStatusCounts(status));
    if (status === 'export_ready') return Number(overview.export_ready_unexported ?? overview.export_ready ?? pageStatusCounts(status));
    return Number(overview[status] ?? pageStatusCounts(status));
  };
  const activeFilterCount = [
    itemId,
    isTikTokSource ? null : competitorAsin,
    isTikTokSource ? null : upc,
    skuCode,
    statusFilter,
    generationStatusFilter !== 'all' ? generationStatusFilter : null,
    dateRange,
  ].filter(Boolean).length;
  const tableSummary = generationStatusFilter === 'all'
    ? `表格当前筛选 ${total} 条`
    : `${WORK_STATUS_META[generationStatusFilter].label}：当前筛选 ${total} 条`;

  return (
    <div className="product-workbench">
      <section className="product-workbench-hero">
        <div className="product-workbench-title">
          <Title level={4} style={{ margin: 0 }}>商品工作台</Title>
          <Text type="secondary">{tableSummary} · 全库 {overview?.total_products ?? total} 条</Text>
        </div>
        <Space className="product-workbench-actions" wrap>
          <Select
            placeholder="选择店铺"
            style={{ width: 220 }}
            value={selectedDataSourceId}
            options={dataSources.map((source) => ({
              value: source.id,
              label: `${source.name} · ${(source.sales_channel || 'amazon').toUpperCase()}`,
            }))}
            onChange={(value) => {
              const nextSource = dataSources.find((source) => source.id === value);
              setSelectedDataSourceId(value);
              window.localStorage.setItem(PRODUCT_DATA_SOURCE_KEY, String(value));
              setPage(1);
              setGenerationStatusFilter('all');
              if ((nextSource?.sales_channel || 'amazon').toLowerCase() === 'tiktok') {
                setCompetitorAsin('');
                setCompetitorAsinInput('');
                setUpc('');
                setUpcInput('');
              }
            }}
          />
          {!isTikTokSource && (
            <>
              <Button onClick={() => openReviewPage('/products/image-review')}>图片确认</Button>
              <Button onClick={() => navigate('/task-runs')}>任务中心</Button>
              <Button onClick={() => navigate('/export-center')}>导出中心</Button>
            </>
          )}
          <Button icon={<CloudDownloadOutlined />} loading={pullingGigaProducts} onClick={openPullModal}>
            同步店铺商品
          </Button>
          <Button icon={<ReloadOutlined />} onClick={refreshWorkbenchRows}>刷新</Button>
        </Space>

        {!isTikTokSource && (
          <div className="product-metric-grid">
            {PRIMARY_WORK_STATUS.map((status) => {
              const meta = WORK_STATUS_META[status];
              const count = overviewStatusCounts(status);
              return (
                <button
                  key={status}
                  type="button"
                  className={`product-metric ${generationStatusFilter === status ? 'is-active' : ''}`}
                  onClick={() => handleWorkStatusClick(status)}
                >
                  <span className="product-metric-label">{meta.shortLabel}</span>
                  <strong>{count}</strong>
                  <span className="product-metric-action">{meta.action}</span>
                </button>
              );
            })}
          </div>
        )}

        {(latestGigaPullSummary || activeGigaSyncBatch) && (
          <div className="product-task-hints">
            {latestGigaPullSummary && (
              <Space size={8} wrap>
                <Tag color={latestGigaPullSummary.color}>{latestGigaPullSummary.title}</Tag>
                <Text type="secondary">{latestGigaPullSummary.text}</Text>
                <Button size="small" onClick={() => navigate('/task-runs')}>查看任务中心</Button>
              </Space>
            )}
            {activeGigaSyncBatch && (
              <Space size={8} wrap>
                <Tag color="processing">店铺商品同步中</Tag>
                <Text type="secondary">
                  {activeGigaSyncBatch.batch_id} 正在后台同步商品、价格和库存；主数据完成后会自动分组并生成商品草稿。
                </Text>
              </Space>
            )}
          </div>
        )}
      </section>

      <section className="product-filter-bar">
        <Input
          allowClear
          placeholder="SKU / Item Code / 标题"
          value={skuInput}
          onChange={(event) => setSkuInput(event.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 220 }}
        />
        <Input
          allowClear
          placeholder="Item ID"
          value={itemIdInput}
          onChange={(event) => setItemIdInput(event.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 160 }}
        />
        {!isTikTokSource && (
          <>
            <Input
              allowClear
              placeholder="竞品 ASIN"
              value={competitorAsinInput}
              onChange={(event) => setCompetitorAsinInput(event.target.value)}
              onPressEnter={handleSearch}
              style={{ width: 160 }}
            />
            <Input
              allowClear
              placeholder="UPC"
              value={upcInput}
              onChange={(event) => setUpcInput(event.target.value)}
              onPressEnter={handleSearch}
              style={{ width: 150 }}
            />
          </>
        )}
        <RangePicker value={dateRangeInput} onChange={(value) => setDateRangeInput(value as [dayjs.Dayjs, dayjs.Dayjs] | null)} />
        <Select
          allowClear
          placeholder="处理状态"
          style={{ width: 160 }}
          value={statusFilter}
          onChange={(value) => {
            setStatusFilter(value);
            setGenerationStatusFilter('all');
            setPage(1);
          }}
          options={[
            { value: 'created', label: '待处理' },
            { value: 'competitor_searching', label: '搜索候选竞品中' },
            { value: 'paused', label: '已挂起' },
            { value: 'pending_review', label: '待人工确认' },
            { value: 'completed', label: '已生成 Listing' },
            { value: 'failed', label: '失败' },
          ]}
        />
        <Button type="primary" onClick={handleSearch}>查询</Button>
        <Button disabled={!activeFilterCount} onClick={resetFilters}>清空</Button>
      </section>

      <Table
        className="product-list-table"
        dataSource={visibleRows}
        columns={columns}
        rowKey={(record) => record.key}
        loading={loading}
        scroll={{ x: 1800 }}
        expandable={{
          expandedRowKeys,
          expandedRowRender: renderSkuExpandedRow,
          onExpand: (expanded, record) => {
            setExpandedRowKeys((prev) => (
              expanded ? prev.includes(record.key) ? prev : [...prev, record.key] : prev.filter((key) => key !== record.key)
            ));
            if (expanded) fetchRowSkus(record);
          },
        }}
        title={() => (
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            {!isTikTokSource ? (
              <>
                <Space wrap>
                  <Text type="secondary">全库状态</Text>
                  {WORK_STATUS_FILTERS.map((value) => {
                    const label = value === 'all' ? '全部' : WORK_STATUS_META[value].shortLabel;
                    const count = value === 'all' ? (overview?.total_products ?? total) : overviewStatusCounts(value);
                    return (
                      <Button
                        key={value}
                        size="small"
                        danger={value === 'failed' && generationStatusFilter === 'failed'}
                        type={generationStatusFilter === value ? 'primary' : 'default'}
                        onClick={() => handleWorkStatusClick(value as 'all' | WorkStatus)}
                      >
                        {label} {count}
                      </Button>
                    );
                  })}
                </Space>
                <Space>
                  <Button
                    icon={<PlayCircleOutlined />}
                    loading={creatingBulkAdvanceTask}
                    disabled={loading || creatingBulkAdvanceTask}
                    onClick={createBulkAdvanceTaskForCurrentFilter}
                  >
                    批量推进当前筛选
                  </Button>
                </Space>
              </>
            ) : (
              <Text type="secondary">TikTok 店铺只展示商品、SKU 和后续 TikTok 详情；Amazon 竞品、Listing、批量推进入口已隐藏。</Text>
            )}
          </div>
        )}
        pagination={{
          current: page,
          total,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (nextTotal, range) => `${range[0]}-${range[1]} / ${nextTotal} 条`,
          pageSize,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          },
        }}
      />

      <Modal
        title="同步店铺商品"
        open={pullModalOpen}
        okText="提交任务中心"
        cancelText="取消"
        confirmLoading={pullingGigaProducts}
        onOk={pullMissingGigaProducts}
        onCancel={() => setPullModalOpen(false)}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Text type="secondary">请选择要同步的大健店铺。多选时系统会在任务中心创建一个同步任务，并按店铺分别执行。</Text>
          <Text type="secondary">商品草稿创建时 UPC 会自动从 UPC池子领取。</Text>
          <Select
            mode="multiple"
            placeholder="选择一个或多个店铺"
            style={{ width: '100%' }}
            value={selectedPullDataSourceIds}
            options={dataSources.map((source) => ({
              value: source.id,
              label: `${source.name} · ${(source.sales_channel || 'amazon').toUpperCase()}`,
            }))}
            onChange={(value) => setSelectedPullDataSourceIds(value)}
          />
        </Space>
      </Modal>
    </div>
  );
};

export default ProductList;
