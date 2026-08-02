import React, { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Table, Button, Tag, Space, Typography, message, Popconfirm, Input, InputNumber, Modal, DatePicker, Image, Radio, Select, Tooltip } from 'antd';
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
  resumePipeline,
  retryStep,
  STEP_LABELS,
} from '../api';
import type { GigaSyncBatch, Product, TaskRunDetail, TikTokChannelStatus, WorkbenchOverview } from '../api';
import type { ProductDataSource } from '../api';
import type { MutationCallsiteId } from '../api/mutationInventory.generated.ts';
import { runMutationWithUX } from '../api/mutationRunner.ts';
import {
  dispatchProductWorkflowAction,
  getProductWorkflowAction,
  reportUnknownProductWorkflowAction,
  type ProductWorkflowApiClientExport,
} from '../workflow/productWorkflowActionRegistry';
import { ProductWorkflowUnknownAction } from '../workflow/ProductWorkflowUnknownAction';

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

const PRODUCT_LIST_WORKFLOW_CALLSITE_IDS = {
  resumePipeline: 'resumePipeline|frontend/src/pages/ProductList.tsx|runProductWorkflowAction',
  retryProductAutoImageSelection: 'retryProductAutoImageSelection|frontend/src/pages/ProductList.tsx|runProductWorkflowAction',
  retryProductCompetitorSearch: 'retryProductCompetitorSearch|frontend/src/pages/ProductList.tsx|runProductWorkflowAction',
  retryProductCompetitorVisualMatch: 'retryProductCompetitorVisualMatch|frontend/src/pages/ProductList.tsx|runProductWorkflowAction',
  retryStep: 'retryStep|frontend/src/pages/ProductList.tsx|runProductWorkflowAction',
} satisfies Record<ProductWorkflowApiClientExport, MutationCallsiteId>;

type WorkStatus =
  | 'needs_initialization'
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
  needs_initialization: { label: 'Workflow 待初始化', shortLabel: '待初始化', color: 'default', action: '查看详情' },
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
  'needs_initialization',
  'auto_select_images',
  'select_images',
  'select_competitor',
  'competitor_searching',
  'capture_detail',
  'ready_to_generate',
  'running',
  'export_ready',
  'exported',
  'failed',
];

const TIKTOK_CHANNEL_STATUSES: TikTokChannelStatus[] = [
  'failed',
  'draft',
  'missing_required_info',
  'unsupported',
];

const TIKTOK_CHANNEL_STATUS_META: Record<TikTokChannelStatus, {
  label: string;
  shortLabel: string;
  color: string;
  reason: string;
}> = {
  failed: { label: '失败', shortLabel: '失败', color: 'error', reason: '商品处理失败' },
  draft: { label: '草稿', shortLabel: '草稿', color: 'default', reason: '暂无可展示 SKU' },
  missing_required_info: { label: '资料不完整', shortLabel: '资料不完整', color: 'warning', reason: '缺少采购价或分仓库存' },
  unsupported: {
    label: '资料已齐 · 导出暂未接入',
    shortLabel: '资料已齐 · 导出暂未接入',
    color: 'blue',
    reason: 'TikTok 导出/发布尚未接入',
  },
};

const channelStatusParam = (value: string | null): 'all' | TikTokChannelStatus => (
  value && TIKTOK_CHANNEL_STATUSES.includes(value as TikTokChannelStatus)
    ? value as TikTokChannelStatus
    : 'all'
);

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
  const [channelStatusFilter, setChannelStatusFilter] = useState<'all' | TikTokChannelStatus>(
    channelStatusParam(initialSearch.get('channel_status'))
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
  const [pullScope, setPullScope] = useState<'limited' | 'all'>('limited');
  const [pullNewSkuLimit, setPullNewSkuLimit] = useState(100);
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
    if ((product.sales_channel || '').toLowerCase() === 'tiktok') {
      return product.channel_status === 'failed' ? 'failed' : 'running';
    }
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
    if (!isTikTokSource && statusFilter) params.set('status', statusFilter);
    if (isTikTokSource && channelStatusFilter !== 'all') params.set('channel_status', channelStatusFilter);
    if (!isTikTokSource && generationStatusFilter !== 'all') params.set('work_status', generationStatusFilter);
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

  const handleWorkStatusClick = (value: 'all' | WorkStatus) => {
    setGenerationStatusFilter(value);
    setPage(1);
  };

  const handleChannelStatusClick = (value: 'all' | TikTokChannelStatus) => {
    setChannelStatusFilter(value);
    setPage(1);
  };

  const fetchProducts = async () => {
    if (!selectedDataSourceId || !activeDataSource) return;
    setLoading(true);
    try {
      const { data } = await listProducts({
        page,
        page_size: pageSize,
        item_id: itemId.trim() || undefined,
        competitor_asin: isTikTokSource ? undefined : competitorAsin.trim() || undefined,
        upc: isTikTokSource ? undefined : upc.trim() || undefined,
        status: isTikTokSource ? undefined : statusFilter,
        work_status: !isTikTokSource && generationStatusFilter !== 'all' ? generationStatusFilter : undefined,
        channel_status: isTikTokSource && channelStatusFilter !== 'all' ? channelStatusFilter : undefined,
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
    if (!selectedDataSourceId || !activeDataSource) return;
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

  useEffect(() => { fetchProducts(); }, [page, pageSize, itemId, competitorAsin, upc, statusFilter, generationStatusFilter, channelStatusFilter, dateRange, selectedDataSourceId, activeDataSource?.id, isTikTokSource]);
  useEffect(() => { fetchDataSources(); }, []);
  useEffect(() => { fetchOverview(); }, [selectedDataSourceId, activeDataSource?.id, isTikTokSource]);
  useEffect(() => {
    if (!activeDataSource) return;
    if (isTikTokSource) {
      setStatusFilter(undefined);
      setGenerationStatusFilter('all');
    } else {
      setChannelStatusFilter('all');
    }
  }, [activeDataSource?.id, isTikTokSource]);
  useEffect(() => {
    if (!activeGigaSyncBatch && !['pending', 'running'].includes(latestGigaPullTask?.status || '')) return;
    const timer = window.setInterval(() => {
      refreshTaskHints();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [activeGigaSyncBatch?.batch_id, latestGigaPullTask?.id, latestGigaPullTask?.status, selectedDataSourceId, activeSite]);
  useEffect(() => {
    if (!activeDataSource) return;
    const params = new URLSearchParams();
    if (page > 1) params.set('page', String(page));
    if (pageSize !== 20) params.set('page_size', String(pageSize));
    if (!isTikTokSource && statusFilter) params.set('status', statusFilter);
    if (isTikTokSource && channelStatusFilter !== 'all') params.set('channel_status', channelStatusFilter);
    if (!isTikTokSource && generationStatusFilter !== 'all') params.set('work_status', generationStatusFilter);
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
  }, [page, pageSize, itemId, competitorAsin, upc, statusFilter, generationStatusFilter, channelStatusFilter, dateRange, skuCode, activeDataSource?.id, isTikTokSource, location.pathname, location.search, navigate]);

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
    setChannelStatusFilter('all');
    setPage(1);
  };

  const openPullModal = () => {
    setSelectedPullDataSourceIds(selectedDataSourceId ? [selectedDataSourceId] : []);
    setPullScope('limited');
    setPullNewSkuLimit(100);
    setPullModalOpen(true);
  };

  const pullMissingGigaProducts = async () => {
    if (!selectedPullDataSourceIds.length) {
      message.warning('请选择要同步的大健店铺');
      return;
    }
    if (pullScope === 'limited' && (!pullNewSkuLimit || pullNewSkuLimit < 1)) {
      message.warning('请输入本次新增同步数量');
      return;
    }
    setPullingGigaProducts(true);
    await runMutationWithUX(
      'createGigaPullTaskRuns|frontend/src/pages/ProductList.tsx|pullMissingGigaProducts',
      async (metadata) => {
        const { data } = await createGigaPullTaskRuns({
          data_source_ids: selectedPullDataSourceIds,
          new_sku_limit: pullScope === 'all' ? null : pullNewSkuLimit,
        }, metadata);
        const firstRun = data.runs[0];
        message.success(`已提交新任务中心：${data.runs.map((run) => `#${run.id}`).join('、')}`);
        const detail = await getTaskRun(firstRun.id);
        setLatestGigaPullTask(detail.data);
        setPullModalOpen(false);
        await refreshWorkbenchRows();
        // A one-SKU pull can complete before navigation finishes.  Pin the
        // newly created run in the all-history view so it never appears to
        // disappear merely because the default "current" view hides completed
        // tasks.
        navigate(`/task-runs?view=all&q=%23${firstRun.id}`);
      },
      {
        errorFallback: '提交店铺商品同步失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setPullingGigaProducts(false),
      },
    ).catch(() => undefined);
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
        await runMutationWithUX(
          'createProductBulkAdvanceTaskByFilter|frontend/src/pages/ProductList.tsx|onOk',
          async (metadata) => {
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
            }, metadata);
            const result = parseJson<{ requested_count?: number; started_count?: number; skipped_count?: number }>(data.summary_json, {});
            message.success(`已创建任务中心 #${data.id}：提交 ${result.requested_count || 0}，入队 ${result.started_count || 0}，跳过 ${result.skipped_count || 0}`);
            await refreshWorkbenchRows();
            navigate('/task-runs');
          },
          {
            errorFallback: '创建批量推进任务失败',
            onError: (errorMessage) => message.error(errorMessage),
            clearLoading: () => {
              hideLoading();
              setCreatingBulkAdvanceTask(false);
            },
          },
        ).catch(() => undefined);
      },
    });
  };

  const handleDeleteProduct = async (record: Product) => {
    setDeletingId(record.id);
    await runMutationWithUX(
      'deleteProduct|frontend/src/pages/ProductList.tsx|handleDeleteProduct',
      async (metadata) => {
        await deleteProduct(record.id, metadata);
        message.success('商品已删除');
        if (products.length === 1 && page > 1) setPage(page - 1);
        await refreshWorkbenchRows();
      },
      {
        errorFallback: '删除失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setDeletingId(null),
      },
    ).catch(() => undefined);
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
    setRerunningId(productId);
    await runMutationWithUX(
      'pausePipeline|frontend/src/pages/ProductList.tsx|suspendProductTask',
      async (metadata) => {
        await pausePipeline(productId, metadata);
        message.success('已挂起，后续自动流程不会继续执行');
        await refreshWorkbenchRows();
      },
      {
        errorFallback: '挂起失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setRerunningId(null),
      },
    ).catch(() => undefined);
  };

  const resumeProductTask = async (productId: number) => {
    setRerunningId(productId);
    await runMutationWithUX(
      'resumePipeline|frontend/src/pages/ProductList.tsx|resumeProductTask',
      async (metadata) => {
        await resumePipeline(productId, metadata);
        message.success('已继续执行');
        await refreshWorkbenchRows();
      },
      {
        errorFallback: '继续失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setRerunningId(null),
      },
    ).catch(() => undefined);
  };

  const runProductWorkflowAction = async (product: Product, action: string) => {
    const definition = getProductWorkflowAction(action);
    const isApiAction = definition?.kind === 'api';
    if (isApiAction) setRerunningId(product.id);
    const dispatchContext = {
        productId: product.id,
        relatedCorrelationKey: product.workflow?.related_correlation_key,
        navigate: (target: string) => {
          if (target === `/products/${product.id}`) {
            openProductDetail(product.id);
          } else if (target.startsWith('/products/image-review')) {
            window.open(target, '_blank', 'noopener,noreferrer');
          } else {
            navigate(target);
          }
        },
    };
    if (!definition || definition.kind !== 'api') {
      try {
        await dispatchProductWorkflowAction(action, dispatchContext);
      } catch (error: any) {
        message.error(error?.response?.data?.detail || '操作失败');
      }
      return;
    }
    await runMutationWithUX(
      PRODUCT_LIST_WORKFLOW_CALLSITE_IDS[definition.client_export],
      async (metadata) => {
        const result = await dispatchProductWorkflowAction(action, {
          ...dispatchContext,
          mutationMetadata: metadata,
        });
        if (result.status === 'handled') {
          await refreshWorkbenchRows();
          message.success(product.workflow?.primary_action_label ? `已提交：${product.workflow.primary_action_label}` : '已提交处理');
        }
      },
      {
        errorFallback: '操作失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setRerunningId(null),
      },
    ).catch(() => undefined);
  };

  const workStatusTag = (status: WorkStatus) => {
    const meta = WORK_STATUS_META[status];
    return <Tag color={meta.color}>{meta.label}</Tag>;
  };

  const tiktokChannelStatusTag = (product: Product) => {
    const status = product.channel_status;
    if (!status) return <Tag>未分类</Tag>;
    const meta = TIKTOK_CHANNEL_STATUS_META[status];
    return <Tag color={meta.color}>{product.channel_status_label || meta.label}</Tag>;
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
      if (record.channel_status === 'failed' && record.error_message) return `失败：${record.error_message}`;
      return record.channel_status_reason
        || (record.channel_status ? TIKTOK_CHANNEL_STATUS_META[record.channel_status].reason : null)
        || record.current_task_status
        || '-';
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
      const definition = getProductWorkflowAction(workflowAction);
      if (!definition) {
        reportUnknownProductWorkflowAction(workflowAction);
        return <ProductWorkflowUnknownAction action={workflowAction} surface="product-list" size="small" />;
      }
      const label = workflowActionLabel || definition.default_label;
      const icon = definition.kind === 'api'
        ? (workflowAction === 'resume' ? <PlayCircleOutlined /> : <RedoOutlined />)
        : undefined;
      return (
        <Button
          size="small"
          type={workflowAction === 'open_task_center' ? 'default' : 'primary'}
          icon={icon}
          loading={definition.kind === 'api' && rerunningId === product.id}
          onClick={() => void runProductWorkflowAction(product, definition.action)}
        >
          {label}
        </Button>
      );
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
          onClick={async () => {
            setRerunningId(product.id);
            await runMutationWithUX(
              'retryStep|frontend/src/pages/ProductList.tsx|renderPrimaryRowAction|1',
              async (metadata) => {
                await retryStep(product.id, metadata);
                await refreshWorkbenchRows();
              },
              {
                errorFallback: '重试失败',
                onError: (errorMessage) => message.error(errorMessage),
                clearLoading: () => setRerunningId(null),
              },
            ).catch(() => undefined);
          }}
        >
          重试
        </Button>
      );
    }
    if (product.status === 'paused' || product.status === 'pending_review') {
      return (
        <Button size="small" type="primary" icon={<PlayCircleOutlined />} loading={rerunningId === product.id} onClick={() => resumeProductTask(product.id)}>
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
        <Button
          size="small"
          type="primary"
          icon={<RedoOutlined />}
          loading={rerunningId === product.id}
          onClick={async () => {
            setRerunningId(product.id);
            await runMutationWithUX(
              'retryStep|frontend/src/pages/ProductList.tsx|renderPrimaryRowAction|2',
              async (metadata) => {
                await retryStep(product.id, metadata);
                await refreshWorkbenchRows();
              },
              {
                errorFallback: '重试失败',
                onError: (errorMessage) => message.error(errorMessage),
                clearLoading: () => setRerunningId(null),
              },
            ).catch(() => undefined);
          }}
        >
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
        return tiktokChannelStatusTag(row.product);
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
              <Button size="small" icon={<EditOutlined />} onClick={() => void runProductWorkflowAction(product, 'manual_adjust_images')}>
                手动调图
              </Button>
            ) : null}
            {canRestartCompetitorSearch ? (
              <Button
                size="small"
                icon={<RedoOutlined />}
                loading={rerunningId === product.id}
                onClick={() => void runProductWorkflowAction(product, 'restart_competitor_search')}
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
                <Button size="small" icon={<PauseOutlined />} loading={rerunningId === product.id}>挂起</Button>
              </Popconfirm>
            ) : null}
            {canRestartProduct && (
              <Popconfirm
                title="确定重新开始流程？"
                description="会保留已使用图片，清空旧候选竞品、已选竞品和后续生成结果；有主图时会重新搜索候选竞品。"
                okText="重新开始"
                cancelText="取消"
                onConfirm={async () => {
                  setRerunningId(product.id);
                  await runMutationWithUX(
                    'restartPipeline|frontend/src/pages/ProductList.tsx|render',
                    async (metadata) => {
                      await restartPipeline(product.id, metadata);
                      await refreshWorkbenchRows();
                    },
                    {
                      errorFallback: '重新开始失败',
                      onError: (errorMessage) => message.error(errorMessage),
                      clearLoading: () => setRerunningId(null),
                    },
                  ).catch(() => undefined);
                }}
              >
                <Tooltip title="重新开始流程">
                  <Button size="small" icon={<RedoOutlined />} loading={rerunningId === product.id} />
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
    const overviewCounts = overview as unknown as Partial<Record<WorkStatus, number>>;
    return Number(overviewCounts[status] ?? pageStatusCounts(status));
  };
  const channelStatusCount = (status: TikTokChannelStatus) => (
    Number(overview?.channel_status_counts?.[status] ?? products.filter((product) => product.channel_status === status).length)
  );
  const activeFilterCount = [
    itemId,
    isTikTokSource ? null : competitorAsin,
    isTikTokSource ? null : upc,
    skuCode,
    isTikTokSource ? null : statusFilter,
    isTikTokSource
      ? channelStatusFilter !== 'all' ? channelStatusFilter : null
      : generationStatusFilter !== 'all' ? generationStatusFilter : null,
    dateRange,
  ].filter(Boolean).length;
  const tableSummary = isTikTokSource
    ? channelStatusFilter === 'all'
      ? `表格当前筛选 ${total} 条`
      : `${TIKTOK_CHANNEL_STATUS_META[channelStatusFilter].label}：当前筛选 ${total} 条`
    : generationStatusFilter === 'all'
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
              setChannelStatusFilter('all');
              setStatusFilter(undefined);
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

        {isTikTokSource ? (
          <div className="product-metric-grid">
            {TIKTOK_CHANNEL_STATUSES.map((status) => {
              const meta = TIKTOK_CHANNEL_STATUS_META[status];
              return (
                <button
                  key={status}
                  type="button"
                  data-testid={`tiktok-channel-metric-${status}`}
                  className={`product-metric ${channelStatusFilter === status ? 'is-active' : ''}`}
                  onClick={() => handleChannelStatusClick(status)}
                >
                  <span className="product-metric-label">{meta.shortLabel}</span>
                  <strong>{channelStatusCount(status)}</strong>
                  <span className="product-metric-action">筛选查看</span>
                </button>
              );
            })}
          </div>
        ) : (
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
        {isTikTokSource ? (
          <Select
            allowClear
            data-testid="tiktok-channel-filter"
            placeholder="TikTok 渠道状态"
            style={{ width: 220 }}
            value={channelStatusFilter === 'all' ? undefined : channelStatusFilter}
            onChange={(value) => handleChannelStatusClick(value || 'all')}
            options={TIKTOK_CHANNEL_STATUSES.map((value) => ({
              value,
              label: TIKTOK_CHANNEL_STATUS_META[value].label,
            }))}
          />
        ) : (
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
        )}
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
          <div>
            <Text strong>本次新增同步</Text>
            <Radio.Group
              value={pullScope}
              onChange={(event) => setPullScope(event.target.value)}
              style={{ display: 'block', marginTop: 8 }}
            >
              <Space direction="vertical">
                <Radio value="limited">指定数量</Radio>
                <Radio value="all">全部新增 SKU</Radio>
              </Space>
            </Radio.Group>
            <InputNumber
              min={1}
              max={10000}
              value={pullNewSkuLimit}
              disabled={pullScope === 'all'}
              onChange={(value) => setPullNewSkuLimit(value || 0)}
              addonAfter="个新增 SKU"
              style={{ width: '100%', marginTop: 8 }}
            />
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              仅同步尚未拉取过的 SKU；指定数量时按店铺分别取前 N 个，选择全部则同步所有新增 SKU。
            </Text>
          </div>
        </Space>
      </Modal>
    </div>
  );
};

export default ProductList;
