// @ts-nocheck
import React, { useEffect, useState, useRef } from 'react';
import { useLocation, useParams, useNavigate } from 'react-router-dom';
import { Alert, Card, Descriptions, Tag, Steps, Tabs, Button, Space, Typography, Spin, message, Popconfirm, Image, Table, List, Modal, Input, Select, Empty, Tooltip } from 'antd';
import {
  ArrowLeftOutlined, PlayCircleOutlined, RedoOutlined,
  PauseOutlined, ReloadOutlined, DeleteOutlined,
  FolderOpenOutlined, FileZipOutlined, InboxOutlined, FileExcelOutlined,
  CheckOutlined, DragOutlined, CopyOutlined, ExportOutlined,
  PictureOutlined, EyeOutlined, VideoCameraOutlined,
  FilePdfOutlined, FileTextOutlined,
} from '@ant-design/icons';
import { getProduct, getProductSection, getProductImageSection, getProductAplusSection, restartPipeline, retryStep, resumePipeline, pausePipeline, deleteProduct, openProductFile, extractProductZip, regenerateAplusModule, retryAplusRegeneration, generateProductAplus, runProductFromStep, runPipelineStep, updateProduct, updateProductListingImages, listCategoryOptions, getProductMaterialSpreadsheetPreview, productMaterialPreviewUrl } from '../api';
import type { CategoryOption, ProductDetail, ProductMaterialAsset, ProductMaterialSpreadsheetPreview, ProductSectionResponse } from '../api';
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
const PRODUCT_LIST_RETURN_KEY = 'fbm.productList.returnPath';
const DEFAULT_LISTING_IMAGE_LIMIT = 9;
const PRODUCT_DETAIL_WORKFLOW_CALLSITE_IDS = {
  confirmProduct: 'confirmProduct|frontend/src/pages/ProductDetail.tsx|runWorkflowAction',
  resumePipeline: 'resumePipeline|frontend/src/pages/ProductDetail.tsx|runWorkflowAction',
  retryProductMaterialPrepare: 'retryProductMaterialPrepare|frontend/src/pages/ProductDetail.tsx|runWorkflowAction',
  retryProductAutoImageSelection: 'retryProductAutoImageSelection|frontend/src/pages/ProductDetail.tsx|runWorkflowAction',
  retryProductCompetitorSearch: 'retryProductCompetitorSearch|frontend/src/pages/ProductDetail.tsx|runWorkflowAction',
  retryProductCompetitorVisualMatch: 'retryProductCompetitorVisualMatch|frontend/src/pages/ProductDetail.tsx|runWorkflowAction',
  retryProductKeywordResearch: 'retryProductKeywordResearch|frontend/src/pages/ProductDetail.tsx|runWorkflowAction',
  retryStep: 'retryStep|frontend/src/pages/ProductDetail.tsx|runWorkflowAction',
} satisfies Record<ProductWorkflowApiClientExport, MutationCallsiteId>;

const APLUS_REGEN_ACTIVE_STATUSES = ['queued', 'planning', 'scripting', 'imaging', 'regen_queued', 'regen_script_running', 'regen_image_running'];
const APLUS_REGEN_RETRYABLE_STATUSES = ['regen_failed', 'regen_interrupted'];
const WORK_STATUS_META: Record<string, { label: string; shortLabel: string; color: string }> = {
  needs_initialization: { label: 'Workflow 待初始化', shortLabel: '待初始化', color: 'default' },
  auto_select_images: { label: '自动选图中', shortLabel: '自动选图', color: 'processing' },
  select_images: { label: '待确认商品图片', shortLabel: '确认图片', color: 'cyan' },
  competitor_searching: { label: '搜索候选竞品中', shortLabel: '搜索中', color: 'processing' },
  select_competitor: { label: '待搜索/选择竞品', shortLabel: '选竞品', color: 'purple' },
  capture_detail: { label: '抓取竞品详情中', shortLabel: '抓详情', color: 'processing' },
  ready_to_generate: { label: '待自动生成 Listing', shortLabel: '待自动生成', color: 'warning' },
  running: { label: '生成中', shortLabel: '生成中', color: 'processing' },
  confirm_images_aplus: { label: '待确认图片与 A+', shortLabel: '确认图片与 A+', color: 'cyan' },
  export_ready: { label: '待导出', shortLabel: '待导出', color: 'success' },
  exported: { label: '已导出可重导', shortLabel: '已导出', color: 'green' },
  failed: { label: '失败', shortLabel: '失败', color: 'error' },
};
const WORKFLOW_STEP_GROUPS = [
  { key: 'images', title: '素材与图片选择', nodes: ['workflow_uninitialized', 'prepare_materials', 'auto_select_images', 'select_images'] },
  { key: 'search', title: '搜索竞品', nodes: ['search_competitor'] },
  { key: 'visual', title: '视觉初筛', nodes: ['visual_match_competitors'] },
  { key: 'capture', title: '抓取详情', nodes: ['capture_competitor_candidates', 'capture_competitor_detail'] },
  { key: 'competitor', title: '选择竞品', nodes: ['auto_select_competitor', 'select_competitor'] },
  { key: 'keywords', title: '关键词采集', nodes: ['keyword_research'] },
  { key: 'image_analysis', title: '图片分析', nodes: ['image_analysis'] },
  { key: 'customer_mindset', title: '用户心智', nodes: ['customer_mindset'] },
  { key: 'listing', title: 'Listing文案', nodes: ['listing_generation'] },
  { key: 'aplus', title: 'A+ 生图与确认', nodes: ['generate_aplus', 'confirm_images_aplus'] },
  { key: 'export', title: '待导出', nodes: ['flow_done'] },
];
const PRODUCT_NON_RUNNING_STATUSES = [
  'created',
  'completed',
  'pending_review',
  'failed',
  'paused',
  'unavailable',
  'source_unavailable',
  'step1_done',
  'step2_done',
  'step3_4_done',
  'step5_done',
  'step6_done',
  'step7_done',
  'step8_done',
  'step9_done',
  'step10_done',
];
const APLUS_STATUS_LABELS: Record<string, { color: string; text: string }> = {
  done: { color: 'success', text: 'A+已完成' },
  partial: { color: 'warning', text: 'A+部分完成' },
  queued: { color: 'processing', text: 'A+排队中' },
  planning: { color: 'processing', text: 'A+规划中' },
  scripting: { color: 'processing', text: 'A+脚本中' },
  imaging: { color: 'processing', text: 'A+出图中' },
  failed: { color: 'error', text: 'A+生成失败' },
  regen_queued: { color: 'processing', text: '重新生图排队中' },
  regen_script_running: { color: 'processing', text: '正在重写脚本' },
  regen_image_running: { color: 'processing', text: '正在重新生图' },
  regen_done: { color: 'success', text: '重新生图完成' },
  regen_failed: { color: 'error', text: '重新生图失败' },
  regen_interrupted: { color: 'warning', text: '重新生图被中断' },
};
const moduleRegenerationStatus = (generated: any) => {
  const regenerationStatus = String(generated?.regeneration_status || '').trim();
  if (regenerationStatus === 'queued') return { color: 'processing', text: '重新生成排队中' };
  if (regenerationStatus === 'running') return { color: 'processing', text: '正在重新生成' };
  if (regenerationStatus === 'done') return { color: 'success', text: '重新生成完成' };
  if (regenerationStatus === 'failed') return { color: 'error', text: '重新生成失败' };
  if (regenerationStatus === 'interrupted') return { color: 'warning', text: '重新生成中断' };
  if (generated?.status === 'done') return { color: 'success', text: '已生成' };
  if (generated?.status === 'failed') return { color: 'error', text: '生成失败' };
  return { color: 'default', text: '未生成' };
};
const moduleGenerationTime = (generated: any, fallback?: any) => (
  generated?.generated_at || generated?.regeneration_completed_at || generated?.created_at || fallback || null
);
const formatModuleGenerationTime = (value: any) => {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN');
};

/** 将本地文件路径转为后端图片代理URL */
const imgUrl = (localPath: string | null | undefined) => {
  if (!localPath) return '';
  if (/^https?:\/\//i.test(String(localPath))) return String(localPath);
  return `/api/images/${localPath}`;
};
const isRemoteUrl = (value: string | null | undefined) => /^https?:\/\//i.test(String(value || ''));
const fileOpenOperationKey = (path?: string | null, directory = false) => (
  `${directory ? 'directory' : 'file'}:${String(path || '')}`
);

const parseJson = (value: string | null | undefined, fallback: any = null) => {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
};

const productHighlightValues = (value: string | null | undefined) => {
  const parsed = parseJson(value, []);
  if (!Array.isArray(parsed)) return [];
  return parsed.map((item) => String(item || '').trim()).filter(Boolean).slice(0, 1);
};

const productHighlightDrafts = (
  englishValue: string | null | undefined,
  chineseValue: string | null | undefined,
) => {
  const english = productHighlightValues(englishValue);
  const chinese = productHighlightValues(chineseValue);
  return {
    english: [english[0] || ''],
    chinese: [chinese[0] || ''],
  };
};

const MINDSET_STATUS_META: Record<string, { label: string; color: string }> = {
  supported: { label: '有直接支持', color: 'success' },
  inferred: { label: '合理推断', color: 'processing' },
  unknown: { label: '证据不足', color: 'warning' },
  conflicting: { label: '证据冲突', color: 'error' },
};
const MINDSET_CONFIDENCE_META: Record<string, { label: string; color: string }> = {
  high: { label: '高置信度', color: 'success' },
  medium: { label: '中置信度', color: 'processing' },
  low: { label: '低置信度', color: 'warning' },
};
const MINDSET_CONTENT_USE_LABELS: Record<string, string> = {
  title: '标题',
  bullet_1: '五点 1',
  bullet_2: '五点 2',
  bullet_3: '五点 3',
  bullet_4: '五点 4',
  bullet_5: '五点 5',
  listing_image: 'Listing 图片',
  aplus: 'A+',
};

const normalizeComparableImage = (value: string | null | undefined) => String(value || '').trim();

const normalizeImagePath = (item: any) => {
  const path = typeof item === 'string' ? item : item?.path;
  return path ? String(path).trim() : '';
};

const normalizeImageSourceType = (value: string | null | undefined) => String(value || '').trim().toLowerCase();
const isDisplayImageCandidate = (item: any) => {
  if (typeof item === 'string') return false;
  const type = normalizeImageSourceType(item?.image_type || item?.source);
  return ['main', 'gallery'].includes(type);
};
const uniqueImagePaths = (paths: string[]) => paths.filter((path, index) => path && paths.indexOf(path) === index);
const gigaMainImagePathFromOrder = (galleryOrderPaths: any[]) => (
  Array.isArray(galleryOrderPaths)
    ? normalizeImagePath(galleryOrderPaths.find((item: any) => normalizeImageSourceType(item?.image_type || item?.source) === 'main'))
    : ''
);
const imageSourceLabel = (item: any, fallback = '图片素材') => {
  const type = normalizeImageSourceType(item?.image_type || item?.source);
  if (type === 'main') return '大健详情页主图';
  if (type === 'gallery') return '大健详情页 Gallery';
  if (type === 'variant_main') return '其它 SKU 详情页主图';
  if (type === 'variant_gallery') return '其它 SKU 详情页 Gallery';
  if (type === 'file') return '素材包/附件素材';
  if (type === 'brand') return '品牌素材';
  return fallback;
};

const listingImagePathsFromImages = (images: any) => {
  const galleryImagePaths = parseJson(images?.gallery_images, []);
  const galleryOrderPaths = parseJson(images?.gallery_order, []);
  const gigaMainPath = gigaMainImagePathFromOrder(galleryOrderPaths);
  const savedPaths = [
    images?.main_image_path ? String(images.main_image_path).trim() : '',
    ...(Array.isArray(galleryImagePaths) ? galleryImagePaths.map(normalizeImagePath) : []),
  ].filter(Boolean);
  if (savedPaths.length) {
    return uniqueImagePaths([
      gigaMainPath || savedPaths[0],
      ...savedPaths.filter((path) => path !== (gigaMainPath || savedPaths[0])),
    ]).slice(0, DEFAULT_LISTING_IMAGE_LIMIT);
  }
  if (!Array.isArray(galleryOrderPaths)) return [];
  const mainPath = gigaMainPath;
  const galleryPaths = uniqueImagePaths(
    galleryOrderPaths
      .filter((item: any) => normalizeImageSourceType(item?.image_type || item?.source) === 'gallery')
      .map(normalizeImagePath)
      .filter(Boolean)
  ).filter((path) => path !== mainPath);
  return uniqueImagePaths([
    mainPath,
    ...galleryPaths.slice(-(DEFAULT_LISTING_IMAGE_LIMIT - 1)),
  ]).slice(0, DEFAULT_LISTING_IMAGE_LIMIT);
};

const persistedListingImagePathsFromImages = (images: any) => {
  const galleryImagePaths = parseJson(images?.gallery_images, []);
  return uniqueImagePaths([
    images?.main_image_path ? String(images.main_image_path).trim() : '',
    ...(Array.isArray(galleryImagePaths) ? galleryImagePaths.map(normalizeImagePath) : []),
  ].filter(Boolean)).slice(0, DEFAULT_LISTING_IMAGE_LIMIT);
};

const listingImageDraftIsDirty = (images: any, draftPaths: string[]) => {
  const nextPaths = uniqueImagePaths(draftPaths.filter(Boolean)).slice(0, DEFAULT_LISTING_IMAGE_LIMIT);
  const persistedPaths = persistedListingImagePathsFromImages(images);
  return Boolean(nextPaths.length && nextPaths.join('\n') !== persistedPaths.join('\n'));
};

const money = (value: number | null | undefined) => value != null ? `$${value}` : '-';
const numberText = (value: number | null | undefined, unit = '') => value != null ? `${value}${unit}` : '-';
const fileSize = (bytes: number | null | undefined) => {
  if (!bytes) return '-';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};
const valueText = (value: string | null | undefined) => value || '-';
const workflowGroupIndex = (key: string) => WORKFLOW_STEP_GROUPS.findIndex((group) => group.key === key);
const workflowStageIndex = (workflow: any) => {
  const stage = workflow?.stage || workflow?.node_key;
  const directIndex = WORKFLOW_STEP_GROUPS.findIndex((group) => group.nodes.includes(stage));
  const workStatus = workflow?.work_status;
  if (workStatus === 'export_ready' || workStatus === 'exported') return workflowGroupIndex('export');
  if (workStatus === 'select_competitor' && (workflow?.stage_status === 'succeeded' || directIndex < 2)) return 4;
  if (workStatus === 'capture_detail' && (workflow?.stage_status === 'succeeded' || directIndex < 3)) return 3;
  if (directIndex >= 0) {
    if (workStatus === 'ready_to_generate' && workflow?.stage_status === 'succeeded') {
      return Math.min(directIndex + 1, workflowGroupIndex('export'));
    }
    return directIndex;
  }
  if (workStatus === 'needs_initialization' || workStatus === 'auto_select_images' || workStatus === 'select_images') return 0;
  if (workStatus === 'competitor_searching') return 1;
  if (workStatus === 'select_competitor') return 4;
  if (workStatus === 'capture_detail') return 3;
  if (workStatus === 'ready_to_generate' || workStatus === 'running') return workflowGroupIndex('image_analysis');
  if (workStatus === 'export_ready' || workStatus === 'exported') return workflowGroupIndex('export');
  if (workStatus === 'failed') return Math.max(directIndex, 0);
  return 0;
};
const workflowStepStatus = (workflow: any, index: number, currentIndex: number) => {
  const status = workflow?.stage_status;
  const workStatus = workflow?.work_status;
  if (index < currentIndex) return 'finish';
  if (index > currentIndex) return 'wait';
  if (status === 'failed') return 'error';
  if (workStatus === 'exported') return 'finish';
  return 'process';
};
const buildWorkflowPipelineSteps = (workflow: any) => {
  const currentIndex = workflowStageIndex(workflow);
  const currentDescription = workflow?.action_reason
    || WORK_STATUS_META[workflow?.work_status]?.label
    || workflow?.label;
  return WORKFLOW_STEP_GROUPS.map((group, index) => {
    const isCurrent = index === currentIndex;
    const status = workflowStepStatus(workflow, index, currentIndex);
    return {
      title: group.title,
      description: isCurrent
        ? (currentDescription || group.title)
        : status === 'finish'
          ? '已完成'
          : '等待前置节点完成',
      status,
    };
  });
};
const defaultProductDetailTab = (detail: ProductDetail | null | undefined) => {
  if (!detail) return 'basic';

  const workflow = detail.workflow || null;
  if (workflow) {
    const workflowStage = workflow.stage || workflow.node_key;
    const workflowWorkStatus = workflow.work_status;
    if (['auto_select_images', 'select_images', 'image_analysis'].includes(workflowStage)) return 'images';
    if (workflowStage === 'customer_mindset') return 'mindset';
    if (['needs_initialization', 'auto_select_images', 'select_images'].includes(workflowWorkStatus)) return 'images';
    if ([
      'search_competitor',
      'visual_match_competitors',
      'capture_competitor_candidates',
      'capture_competitor_detail',
      'auto_select_competitor',
      'select_competitor',
    ].includes(workflowStage)) return 'competitor';
    if (['competitor_searching', 'select_competitor', 'capture_detail'].includes(workflowWorkStatus)) return 'competitor';
    if (['listing_generation', 'flow_done'].includes(workflowStage)) {
      return detail.aplus?.aplus_status ? 'aplus' : 'listing';
    }
    if (['ready_to_generate', 'running', 'export_ready', 'exported'].includes(workflowWorkStatus)) {
      return detail.aplus?.aplus_status ? 'aplus' : 'listing';
    }
    return 'basic';
  }

  const selectedAsin = detail.competitor_asin;
  const step = Number(detail.current_step || 0);
  const hasMainImage = Boolean(detail.images?.main_image_path);
  const sectionReady = (key: string) => Boolean(detail.sections?.[key]?.has_content);
  const hasListingContent = Boolean(
    sectionReady('listing')
    ||
    detail.data?.listing_title
    || detail.data?.listing_bullets
    || detail.data?.listing_description
    || detail.data?.listing_search_terms
  );
  const hasAplusOutput = Boolean(
    sectionReady('aplus_plan')
    || sectionReady('aplus_script')
    || sectionReady('aplus_assets')
    ||
    detail.aplus?.aplus_plan
    || detail.aplus?.aplus_scripts
    || detail.aplus?.aplus_images
    || detail.aplus?.aplus_status
  );
  const competitorCaptureMessage = /竞品.*抓取中|Listing.*抓取中|竞品详情|竞品 Listing|Amazon Listing 详情|Amazon Listing 抓取|抓取选中竞品|选中竞品.*抓取|Amazon.*详情抓取/i;
  const imageAnalysisMessage = /图片分析节点未完成|不能进入 Listing 文案|图片分析/i;

  if (!hasMainImage || (detail.status === 'created' && step <= 0)) return 'images';
  if (
    detail.status === 'competitor_searching'
    || (!selectedAsin && hasMainImage)
    || (detail.status === 'failed' && competitorCaptureMessage.test(detail.error_message || ''))
  ) {
    return 'competitor';
  }
  if ((sectionReady('mindset') || detail.data?.customer_mindset) && !hasListingContent) return 'mindset';
  if (
    step === 5
    || detail.status === 'step6_curating'
    || (detail.status === 'failed' && imageAnalysisMessage.test(detail.error_message || ''))
  ) {
    return 'images';
  }
  if (hasAplusOutput) return 'aplus';
  if (step >= 6 || hasListingContent) return 'listing';
  return 'basic';
};

const ProductDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const backTarget = (location.state as any)?.from || window.localStorage.getItem(PRODUCT_LIST_RETURN_KEY) || '/products';
  const [product, setProduct] = useState<ProductDetail | null>(null);
  // Bodies are independent of the summary polling response.  In particular,
  // a compact refresh can never erase an already opened mindset brief.
  const [sectionCache, setSectionCache] = useState<Record<string, ProductSectionResponse>>({});
  const sectionCacheRef = useRef<Record<string, ProductSectionResponse>>({});
  const [loading, setLoading] = useState(true);
  const [regenTarget, setRegenTarget] = useState<any | null>(null);
  const [regenReason, setRegenReason] = useState('');
  const [regenLoading, setRegenLoading] = useState(false);
  const [regenRetryLoading, setRegenRetryLoading] = useState(false);
  const [aplusGenerateLoading, setAplusGenerateLoading] = useState(false);
  const [listingRegenerateLoading, setListingRegenerateLoading] = useState(false);
  const [pipelineRetryLoading, setPipelineRetryLoading] = useState(false);
  const [restartLoading, setRestartLoading] = useState(false);
  const [activeTabKey, setActiveTabKey] = useState('basic');
  const [fullDetailProductId, setFullDetailProductId] = useState<number | null>(null);
  const [fullDetailLoading, setFullDetailLoading] = useState(false);
  const [spreadsheetPreview, setSpreadsheetPreview] = useState<ProductMaterialSpreadsheetPreview | null>(null);
  const [spreadsheetPreviewTitle, setSpreadsheetPreviewTitle] = useState('');
  const [spreadsheetPreviewLoading, setSpreadsheetPreviewLoading] = useState(false);
  const [categoryEditOpen, setCategoryEditOpen] = useState(false);
  const [categoryOptions, setCategoryOptions] = useState<CategoryOption[]>([]);
  const [selectedCategoryKey, setSelectedCategoryKey] = useState<string | undefined>();
  const [categoryOptionsLoading, setCategoryOptionsLoading] = useState(false);
  const [categorySaving, setCategorySaving] = useState(false);
  const [listingEditOpen, setListingEditOpen] = useState(false);
  const [listingTitleInput, setListingTitleInput] = useState('');
  const [listingBulletsInput, setListingBulletsInput] = useState('');
  const [listingProductHighlightsInput, setListingProductHighlightsInput] = useState<string[]>(['']);
  const [listingDescriptionInput, setListingDescriptionInput] = useState('');
  const [listingSearchTermsInput, setListingSearchTermsInput] = useState('');
  const [listingTitleZhInput, setListingTitleZhInput] = useState('');
  const [listingBulletsZhInput, setListingBulletsZhInput] = useState('');
  const [listingProductHighlightsZhInput, setListingProductHighlightsZhInput] = useState<string[]>(['']);
  const [listingDescriptionZhInput, setListingDescriptionZhInput] = useState('');
  const [listingSearchTermsZhInput, setListingSearchTermsZhInput] = useState('');
  const [listingPrimaryKeywordInput, setListingPrimaryKeywordInput] = useState('');
  const [listingSaving, setListingSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [fileOpening, setFileOpening] = useState<string | null>(null);
  const [zipExtractingPath, setZipExtractingPath] = useState<string | null>(null);
  const [imageOrderSaving, setImageOrderSaving] = useState(false);
  const [imageDragPayload, setImageDragPayload] = useState<any | null>(null);
  const [listingImageDraftPaths, setListingImageDraftPaths] = useState<string[]>([]);
  const [listingImageDirty, setListingImageDirty] = useState(false);
  const [listingImageDraftProductId, setListingImageDraftProductId] = useState<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoTabProductIdRef = useRef<number | null>(null);
  const userTouchedTabRef = useRef(false);

  const fetchDetail = async (full = false) => {
    if (!id) return;
    try {
      if (full) setFullDetailLoading(true);
      const { data } = await getProduct(Number(id), { compact: !full });
      setProduct(data);
      if (!full && data.sections) {
        const staleSections = Object.entries(sectionCacheRef.current)
          .filter(([key, cached]) => cached.loaded && data.sections?.[key]?.revision !== cached.revision)
          .map(([key]) => key);
        if (staleSections.length) {
          setSectionCache((previous) => {
            const next = { ...previous };
            staleSections.forEach((section) => {
              if (previous[section]) next[section] = { ...previous[section], stale: true };
            });
            sectionCacheRef.current = next;
            return next;
          });
        }
        for (const section of staleSections) void loadSection(section, true);
      }
      if (full) setFullDetailProductId(data.id);
      const nextDefaultTab = defaultProductDetailTab(data);
      const isNewProduct = autoTabProductIdRef.current !== data.id;
      if (isNewProduct) {
        autoTabProductIdRef.current = data.id;
        userTouchedTabRef.current = false;
        setActiveTabKey(nextDefaultTab);
      } else if (!userTouchedTabRef.current) {
        setActiveTabKey(nextDefaultTab);
      }
      setLoading(false);
    } catch {
      message.error('加载失败');
      setLoading(false);
    } finally {
      if (full) setFullDetailLoading(false);
    }
  };

  const loadFullDetail = async (force = false) => {
    if (!id || fullDetailLoading) return;
    if (!force && fullDetailProductId === Number(id)) return;
    await fetchDetail(true);
  };

  const requestSection = async (section: string) => {
    if (section.startsWith('image_')) return getProductImageSection(Number(id), section.slice(6) as any);
    if (section.startsWith('aplus_')) return getProductAplusSection(Number(id), section.slice(6) as any);
    return getProductSection(Number(id), section === 'export_artifact' ? 'export-artifact' : section);
  };

  const loadSection = async (section: string, force = false) => {
    if (!id || (!force && sectionCacheRef.current[section]?.loaded)) return;
    setSectionCache((previous) => {
      const next = {
        ...previous,
        [section]: { loaded: false, state: 'processing' as const, has_content: false, revision: previous[section]?.revision ?? null, updated_at: previous[section]?.updated_at ?? null, data: previous[section]?.data ?? null, stale: force },
      };
      sectionCacheRef.current = next;
      return next;
    });
    try {
      const { data } = await requestSection(section);
      setSectionCache((previous) => {
        const next = { ...previous, [section]: { ...data, stale: false } };
        sectionCacheRef.current = next;
        return next;
      });
    } catch (error: any) {
      // Pre-cutover databases retain the legacy full-detail path.  This is a
      // read fallback only; it does not invoke a workflow mutation.
      if (error?.response?.status === 409) await loadFullDetail();
      else {
        setSectionCache((previous) => {
          const prior = previous[section];
          const next = {
            ...previous,
            [section]: {
              loaded: true,
              state: 'failed' as const,
              has_content: Boolean(prior?.data),
              revision: prior?.revision ?? null,
              updated_at: prior?.updated_at ?? null,
              data: prior?.data ?? null,
              error_code: error?.response?.data?.detail || 'section_request_failed',
              stale: false,
            },
          };
          sectionCacheRef.current = next;
          return next;
        });
        message.error('加载内容失败');
      }
    }
  };

  useEffect(() => {
    const sectionsByTab: Record<string, string[]> = {
      basic: ['source'],
      mindset: ['mindset'],
      listing: ['listing'],
      images: ['image_analysis', 'image_selection', 'image_compliance'],
      aplus: ['aplus_plan', 'aplus_script', 'aplus_assets'],
      files: ['export_artifact'],
    };
    for (const section of sectionsByTab[activeTabKey] || []) void loadSection(section);
    // Section bodies are keyed by product id and section key.  The cache is
    // intentionally not a dependency: adding it must not re-fetch content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTabKey, id]);

  useEffect(() => {
    setFullDetailProductId(null);
    sectionCacheRef.current = {};
    setSectionCache({});
    fetchDetail();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [id]);

  // 自动轮询：任务运行中时每3秒刷新
  useEffect(() => {
    if (!product) return;
    const workflowIsRunning = product.workflow?.stage_status === 'processing'
      || ['running', 'competitor_searching'].includes(product.workflow?.work_status || '');
    const legacyProductIsRunning = !['completed', 'pending_review', 'failed', 'paused', 'created', 'unavailable', 'source_unavailable'].includes(product.status);
    const isRunning = (product.workflow ? workflowIsRunning : legacyProductIsRunning)
      || APLUS_REGEN_ACTIVE_STATUSES.includes(product.aplus?.aplus_status || '');
    if (isRunning) {
      pollRef.current = setInterval(() => fetchDetail(false), 3000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [product?.status, product?.workflow?.stage_status, product?.workflow?.work_status, product?.aplus?.aplus_status, activeTabKey]);

  useEffect(() => {
    if (!product) return;
    if (listingImageDraftProductId !== product.id || !listingImageDirty) {
      const nextPaths = listingImagePathsFromImages(product.images);
      setListingImageDraftPaths(nextPaths);
      setListingImageDirty(listingImageDraftIsDirty(product.images, nextPaths));
      setListingImageDraftProductId(product.id);
    }
  }, [
    product?.id,
    product?.images?.main_image_path,
    product?.images?.gallery_images,
    product?.images?.gallery_order,
    listingImageDirty,
    listingImageDraftProductId,
  ]);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  if (!product) return <div>商品不存在</div>;

  const jsonField = (value: any) => value == null || typeof value === 'string' ? value : JSON.stringify(value);
  const sectionStatus = (keys: string[]) => {
    const entries = keys.map((key) => sectionCache[key]).filter(Boolean);
    if (entries.some((entry) => entry.stale)) {
      return <Alert type="info" showIcon style={{ marginBottom: 12 }} message="内容已更新，正在刷新" />;
    }
    if (entries.some((entry) => entry.state === 'processing')) {
      return <Alert type="info" showIcon style={{ marginBottom: 12 }} message="正在加载内容" />;
    }
    const unresolved = entries.find((entry) => entry.state === 'unresolved');
    if (unresolved) {
      return <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="历史内容无法解析" description={unresolved.error_code || '请重新生成该部分内容'} />;
    }
    const failed = entries.find((entry) => entry.state === 'failed');
    if (failed) {
      return <Alert type="error" showIcon style={{ marginBottom: 12 }} message="内容加载失败" description={failed.error_code || '请使用对应的重试操作'} />;
    }
    if (entries.length && entries.every((entry) => entry.loaded && (entry.state === 'absent' || !entry.has_content))) {
      return <Alert type="info" showIcon style={{ marginBottom: 12 }} message="暂无内容" />;
    }
    return null;
  };
  const sourceBody = sectionCache.source?.data || {};
  const listingBody = sectionCache.listing?.data || {};
  const imageAnalysisBody = sectionCache.image_analysis?.data || {};
  const data = product.data ? {
    ...product.data,
    ...Object.fromEntries(Object.entries(sourceBody).map(([key, value]) => [key, key === 'description' ? value : jsonField(value)])),
    ...Object.fromEntries(Object.entries(listingBody).map(([key, value]) => [key, ['listing_title', 'listing_search_terms', 'listing_title_zh', 'listing_description', 'listing_description_zh', 'listing_search_terms_zh', 'listing_primary_keyword'].includes(key) ? value : jsonField(value)])),
    customer_mindset: sectionCache.mindset?.data ? jsonField(sectionCache.mindset.data) : product.data.customer_mindset,
  } : product.data;
  const images = product.images ? {
    ...product.images,
    image_analysis: jsonField(imageAnalysisBody.image_analysis ?? imageAnalysisBody),
    image_selling_points: jsonField(imageAnalysisBody.image_selling_points),
    image_selection_analysis: sectionCache.image_selection?.data ? jsonField(sectionCache.image_selection.data) : product.images.image_selection_analysis,
    image_compliance_manifest: sectionCache.image_compliance?.data ? jsonField(sectionCache.image_compliance.data) : product.images.image_compliance_manifest,
  } : product.images;
  const aplus = product.aplus ? {
    ...product.aplus,
    aplus_plan: sectionCache.aplus_plan?.data ? jsonField(sectionCache.aplus_plan.data) : product.aplus.aplus_plan,
    aplus_scripts: sectionCache.aplus_script?.data ? jsonField(sectionCache.aplus_script.data) : product.aplus.aplus_scripts,
    aplus_images: sectionCache.aplus_assets?.data ? jsonField(sectionCache.aplus_assets.data) : product.aplus.aplus_images,
  } : product.aplus;
  const aplusStatus = aplus?.aplus_status ? APLUS_STATUS_LABELS[aplus.aplus_status] : null;
  const isAplusRegenerating = APLUS_REGEN_ACTIVE_STATUSES.includes(aplus?.aplus_status || '');
  const canRetryAplusRegeneration = APLUS_REGEN_RETRYABLE_STATUSES.includes(aplus?.aplus_status || '');
  const workflow = product.workflow || null;
  const hasWorkflow = Boolean(workflow);
  const workflowWorkStatusMeta = workflow?.work_status ? WORK_STATUS_META[workflow.work_status] : null;

  const handleDelete = async () => {
    setDeleting(true);
    await runMutationWithUX(
      'deleteProduct|frontend/src/pages/ProductDetail.tsx|handleDelete',
      async (metadata) => {
        await deleteProduct(product.id, metadata);
        message.success('商品已删除');
        navigate(backTarget);
      },
      {
        errorFallback: '删除失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setDeleting(false),
      },
    ).catch(() => undefined);
  };
  const videoFolder = product.video_folder;
  const aplusFolder = product.aplus_folder;
  const packages = parseJson(data?.packages, []);
  const rawSnapshot = parseJson(data?.gigab2b_raw_snapshot, null);
  const exportPreview = product.amazon_export_preview || null;
  const exportPackage = exportPreview?.package_aggregate || null;
  const rawProductDimensions = rawSnapshot?.specification?.product_dimensions?.assemble_info || {};
  const rawPackageSize = rawSnapshot?.specification?.package_size || {};
  const rawPricing = rawSnapshot?.pricing || {};
  const rawFulfillment = rawPricing?.fulfillment_options || {};
  const rawQuantity = rawPricing?.quantity || {};
  const features = parseJson(data?.features, []);
  const variants = parseJson(data?.variants, []);
  const variantAttributeEntries = (value: any) => (
    value && typeof value === 'object' && !Array.isArray(value)
      ? Object.entries(value).filter(([key, item]) => String(key || '').trim() && String(item ?? '').trim())
      : []
  );
  const variantImageUrl = (record: any) => record?.main_image_url || record?.image_url || record?.image || '';
  const renderVariantTags = (value: any, color: string | undefined = undefined, mutedKeys: string[] = []) => {
    const entries = variantAttributeEntries(value).filter(([key]) => !mutedKeys.includes(String(key)));
    if (!entries.length) return <Text type="secondary">-</Text>;
    return (
      <Space size={[4, 4]} wrap>
        {entries.map(([key, item]) => (
          <Tag key={`${key}-${item}`} color={color} style={{ marginInlineEnd: 0 }}>
            <Text strong style={{ fontSize: 12 }}>{String(key)}: </Text>
            <span>{String(item)}</span>
          </Tag>
        ))}
      </Space>
    );
  };
  const commonVariantAttributeEntries = (() => {
    if (!Array.isArray(variants) || variants.length < 2) return [];
    const variationKeys = new Set<string>();
    variants.forEach((variant: any) => {
      variantAttributeEntries(variant?.variation_attributes).forEach(([key]) => variationKeys.add(String(key)));
    });
    const firstEntries = variantAttributeEntries(variants[0]?.attributes)
      .filter(([key]) => !variationKeys.has(String(key)));
    return firstEntries.filter(([key, value]) => (
      variants.every((variant: any) => String(variant?.attributes?.[String(key)] ?? '') === String(value ?? ''))
    ));
  })();
  const pricingDetail = parseJson(data?.pricing_detail, null);
  const categories = parseJson(data?.categories, []);
  const categoryPath = Array.isArray(categories) ? categories.join(' > ') : (data?.categories || '');
  const listingProductHighlights = productHighlightValues(data?.listing_product_highlights);
  const listingProductHighlightsZh = productHighlightValues(data?.listing_product_highlights_zh);
  const mindsetSection = sectionCache.mindset;
  const customerMindset = mindsetSection?.data || parseJson(data?.customer_mindset, null);
  const customerMindsetQuestions = Array.isArray(customerMindset?.questions) ? customerMindset.questions : [];
  const customerMindsetFixedQuestionCount = customerMindsetQuestions.filter(
    (item: any) => item?.question_type === 'fixed',
  ).length;
  const customerMindsetDynamicQuestionCount = customerMindsetQuestions.filter(
    (item: any) => item?.question_type === 'dynamic',
  ).length;
  const customerMindsetStrategy = customerMindset?.strategy && typeof customerMindset.strategy === 'object'
    ? customerMindset.strategy
    : {};
  const customerMindsetStrategyFieldEvidence = customerMindsetStrategy?.strategy_field_evidence
    && typeof customerMindsetStrategy.strategy_field_evidence === 'object'
    ? customerMindsetStrategy.strategy_field_evidence
    : {};
  const customerMindsetQuality = customerMindset?.quality && typeof customerMindset.quality === 'object'
    ? customerMindset.quality
    : {};
  const customerMindsetEvidence = Array.isArray(customerMindset?.evidence_catalog)
    ? customerMindset.evidence_catalog
    : [];
  const customerMindsetEvidenceById = new Map(
    customerMindsetEvidence.map((item: any) => [String(item?.id || ''), item]),
  );
  const renderMindsetStrategyValue = (field: string, value: string | null | undefined) => {
    const meta = customerMindsetStrategyFieldEvidence[field] || {};
    const statusMeta = MINDSET_STATUS_META[meta.status] || MINDSET_STATUS_META.unknown;
    return (
      <Space wrap size={[4, 4]}>
        <Text>{value || '-'}</Text>
        {meta.status && <Tag color={statusMeta.color}>{statusMeta.label}</Tag>}
        {meta.planning_usable === false && <Tag color="warning">不进入下游策略</Tag>}
        {meta.planning_usable !== false && meta.copy_claim_usable === false && <Tag>仅作策略参考</Tag>}
      </Space>
    );
  };
  const generatedFiles = product.generated_files || [];
  const visibleGeneratedFiles = generatedFiles.filter((file: any) => file?.file_type !== 'amazon_import_template');
  const materialAssets: ProductMaterialAsset[] = product.material_assets || [];
  const materialSummary = product.material_summary || {};
  const materialChildrenByParent = materialAssets.reduce((result: Map<number, ProductMaterialAsset[]>, asset) => {
    if (!asset.parent_asset_id) return result;
    const children = result.get(asset.parent_asset_id) || [];
    children.push(asset);
    result.set(asset.parent_asset_id, children);
    return result;
  }, new Map<number, ProductMaterialAsset[]>());
  const dimensionLine = (length?: number | string | null, width?: number | string | null, height?: number | string | null, unit = 'in') => (
    length != null && width != null && height != null ? `${length} × ${width} × ${height} ${unit}` : '-'
  );
  const imageAnalysisPayload = parseJson(images?.image_analysis, null);
  // Full candidate reviews are retained separately from the selected Listing-image evidence.
  const imageSelectionPayload = parseJson(images?.image_selection_analysis, null);
  const imageComplianceManifest = parseJson(images?.image_compliance_manifest, {});
  const imageComplianceAssets = Array.isArray(imageComplianceManifest?.assets) ? imageComplianceManifest.assets : [];
  const imageReviews = Array.isArray(imageAnalysisPayload)
    ? imageAnalysisPayload
    : (imageAnalysisPayload?.images || []);
  const fullImageReviews = Array.isArray(imageSelectionPayload?.image_reviews)
    ? imageSelectionPayload.image_reviews
    : imageReviews;
  const imageSelectionDiagnostics = imageAnalysisPayload?.selection_diagnostics || {};
  const imageHealth = imageSelectionDiagnostics?.image_health || {};
  const imageGalleryRoles = imageSelectionDiagnostics?.gallery_roles || [];
  const imageEvidenceCoverage = imageSelectionDiagnostics?.gallery_evidence_coverage || [];
  const imageEvidenceCards = imageSelectionDiagnostics?.image_evidence_cards || [];
  const missingGalleryRoles = imageSelectionDiagnostics?.missing_gallery_roles || [];
  const duplicateSuppressed = imageSelectionDiagnostics?.duplicate_suppressed || [];
  const duplicateBackfill = imageSelectionDiagnostics?.duplicate_backfill || [];
  const listingImageAlignment = imageSelectionDiagnostics?.listing_image_alignment || {};
  const missingImageEvidence = listingImageAlignment?.missing_evidence || [];
  const supportedImageClaims = listingImageAlignment?.supported_claims || [];
  const listingImageAlignmentPending = listingImageAlignment?.status === 'pending_listing';
  const legacyContactSheets = imageAnalysisPayload?.contact_sheets || (
    images?.contact_sheet_path ? [{ sheet_page: 1, sheet_path: images.contact_sheet_path, image_ids: imageReviews.map((item) => item.image_id || `#${item.index}`) }] : []
  );
  const fullImageBatches = Array.isArray(imageSelectionPayload?.image_batches)
    ? imageSelectionPayload.image_batches
    : [];
  const imageAnalysisBatches = fullImageBatches.length
    ? fullImageBatches
    : (imageAnalysisPayload?.image_batches || legacyContactSheets);
  const isVirtualImageBatch = (batch: any) => String(batch?.sheet_path || '').startsWith('url_batch:');
  const analysisBatchDisplayUrl = (batch: any) => (
    isVirtualImageBatch(batch)
      ? ''
      : (
        batch?.display_url
        || batch?.oss_url
        || batch?.url
        || imgUrl(batch?.sheet_path)
      )
  );
  const reviewsByImageBatch = imageAnalysisBatches.map((batch) => ({
    ...batch,
    reviews: fullImageReviews.filter((review) => review?.contact_sheet_evidence?.sheet_path === batch.sheet_path || batch.image_ids?.includes(review.image_id)),
  }));
  const galleryImagePaths = parseJson(images?.gallery_images, []);
  const galleryOrderPaths = parseJson((images as any)?.gallery_order, []);
  const galleryOnlyImages = Array.isArray(galleryImagePaths)
    ? galleryImagePaths.filter((item) => {
      const path = normalizeImagePath(item);
      return path && path !== images?.main_image_path;
    })
    : [];
  const imageMetaByPath = new Map<string, string>();
  if (images?.main_image_path) {
    imageMetaByPath.set(images.main_image_path, images?.main_image_source || 'main image');
  }
  galleryOnlyImages.forEach((item) => {
    const path = normalizeImagePath(item);
    if (path) {
      imageMetaByPath.set(path, typeof item === 'string' ? 'gallery image' : (item?.role || item?.label || 'gallery image'));
    }
  });
  const selectedListingImages = listingImageDraftPaths.map((path, index) => ({
    path,
    label: index === 0 ? '主图' : `副图 ${index}`,
    meta: imageMetaByPath.get(path) || (index === 0 ? 'manual selected' : 'gallery image'),
  })).filter((item) => item.path);
  const listingImageCount = selectedListingImages.length || (images?.main_image_path ? 1 + galleryOnlyImages.length : data?.image_count);
  const imageResourceItems = (() => {
    const items: any[] = [];
    const seen = new Set<string>();
    const addItem = (item: any, fallback: any = {}) => {
      const path = typeof item === 'string' ? item : item?.path;
      if (!path || seen.has(path)) return;
      seen.add(path);
      items.push({
        path,
        image_id: item?.image_id || fallback.image_id,
        filename: item?.filename || fallback.filename || String(path).split('/').pop(),
        image_type: item?.image_type || fallback.image_type,
        visible_selling_point: item?.visible_selling_point || fallback.visible_selling_point,
        reason: item?.decision_reason || item?.reason || fallback.reason,
      });
    };
    imageReviews.forEach((item: any) => addItem(item));
    if (Array.isArray(galleryOrderPaths)) {
      galleryOrderPaths.forEach((item: any, index: number) => {
        const path = normalizeImagePath(item);
        addItem({ path }, {
          image_id: `#${index + 1}`,
          image_type: item?.image_type || (index === 0 ? 'main' : 'gallery'),
          reason: imageSourceLabel(item, index === 0 ? '商品展示主图' : '商品展示图'),
        });
      });
    }
    // The supplier package is an independent source of usable image candidates.
    // Its extracted images may not appear in the GIGA page gallery or a prior
    // image-analysis result, but a user should still be able to promote one to
    // the Listing main or gallery image from this review surface.
    materialAssets
      .filter((asset) => asset.asset_kind === 'image' && asset.processing_status !== 'stale')
      .forEach((asset) => addItem({
        path: asset.path,
        filename: asset.original_filename,
        image_type: 'file',
        visible_selling_point: `素材包解压图片（${asset.package_type === 'to_b' ? 'To B' : asset.package_type || '未分类'}）`,
        reason: '供应商素材包',
      }, {
        image_id: `素材 #${asset.id}`,
      }));
    selectedListingImages.forEach((item: any) => addItem(item, { image_type: item.label, reason: item.meta }));
    return items;
  })();
  const selectedListingPathSet = new Set(selectedListingImages.map((item: any) => item.path));
  const unusedImageResourceItems = imageResourceItems.filter((item: any) => item?.path && !selectedListingPathSet.has(item.path));
  const aplusScriptsPayload = parseJson(aplus?.aplus_scripts, null);
  const aplusScripts = Array.isArray(aplusScriptsPayload?.scripts) ? aplusScriptsPayload.scripts.slice(0, 5) : [];
  const aplusPlanPayload = parseJson(aplus?.aplus_plan, {});
  const aplusPlanModules = Array.isArray(aplusPlanPayload?.modules) ? aplusPlanPayload.modules : [];
  const aplusGeneratedImages = parseJson(aplus?.aplus_images, []);
  const aplusPlanReady = Boolean(aplus?.aplus_plan);
  const aplusScriptReady = Boolean(aplus?.aplus_scripts);
  const aplusImageDoneCount = Array.isArray(aplusGeneratedImages)
    ? aplusGeneratedImages.filter((item: any) => item?.status === 'done').length
    : 0;
  const keywordItems = parseJson(data?.keywords_top, []);
  const keywordCopyLine = Array.isArray(keywordItems)
    ? keywordItems
      .map((kw) => typeof kw === 'string' ? kw : kw?.keyword)
      .filter(Boolean)
      .join(', ')
    : '';
  const referenceImagePool = Array.from(new Set([
    ...(Array.isArray(galleryImagePaths) ? galleryImagePaths.map((item) => typeof item === 'string' ? item : item?.path) : []),
    images?.main_image_path,
  ].filter(Boolean)));
  const getModuleReferenceImages = (script: any) => {
    const structuredRefs = Array.isArray(script?.reference_images)
      ? script.reference_images.map((item: any) => typeof item === 'string' ? { path: item } : item).filter((item: any) => item?.path)
      : [];
    if (structuredRefs.length) return structuredRefs.slice(0, 2);

    if (!referenceImagePool.length) return [];
    const start = Math.max((Number(script?.module_position) || 1) - 1, 0) * 2;
    const refs = [];
    const seen = new Set();
    for (let offset = 0; offset < referenceImagePool.length && refs.length < 2; offset += 1) {
      const path = referenceImagePool[(start + offset) % referenceImagePool.length];
      if (path && !seen.has(path)) {
        refs.push({ path, label: String.fromCharCode(65 + refs.length) });
        seen.add(path);
      }
    }
    return refs;
  };
  const aplusModulePositions = Array.from(new Set([
    ...aplusPlanModules.map((item: any) => item?.position || item?.module_position),
    ...aplusScripts.map((item: any) => item?.module_position || item?.position),
    ...(Array.isArray(aplusGeneratedImages) ? aplusGeneratedImages.map((item: any) => item?.position || item?.module_position) : []),
  ].filter(Boolean))).sort((a: any, b: any) => Number(a) - Number(b));
  const aplusModules = aplusModulePositions.map((position: any) => {
    const plan = aplusPlanModules.find((item: any) => item?.position === position || item?.module_position === position) || {};
    const script = aplusScripts.find((item: any) => item?.module_position === position || item?.position === position) || {
      module_position: position,
    };
    return {
      position,
      plan,
      script,
      hasScript: Boolean(script?.prompt),
      references: getModuleReferenceImages(script),
      generated: Array.isArray(aplusGeneratedImages)
        ? aplusGeneratedImages.find((img) => img?.position === position || img?.module_position === position)
        : null,
    };
  });
  const listingCheck = parseJson(data?.listing_check, {});
  const keywordPlan = listingCheck?.keyword_plan || {};
  const positioning = listingCheck?.positioning || {};
  const removedKeywords = parseJson(data?.listing_removed_keywords, []);
  const folderRows = [
    data?.material_dir && {
      key: 'material',
      kind: '素材目录',
      label: '商品素材根目录',
      path: data.material_dir,
      meta: '原始素材、解压文件、生成结果归档',
      directory: true,
    },
    videoFolder?.exists && {
      key: 'video',
      kind: '视频',
      label: '视频素材目录',
      path: videoFolder.path,
      meta: `${videoFolder.file_count} 个视频`,
      directory: true,
    },
    aplusFolder?.exists && {
      key: 'aplus-folder',
      kind: 'A+图片',
      label: 'new a plus',
      path: aplusFolder.path,
      meta: `${aplusFolder.file_count} 张图片`,
      directory: true,
    },
  ].filter(Boolean);
  const imageFileRows = [
    images?.main_image_path && {
      key: 'main-image',
      kind: '主图',
      label: '选定主图',
      path: images.main_image_path,
      url: images.main_image_path,
      previewable: true,
      meta: images?.main_image_source || 'main image',
    },
    ...galleryOnlyImages.map((item, index) => {
      const path = typeof item === 'string' ? item : item?.path;
      return path && {
        key: `gallery-${index}-${path}`,
        kind: '副图',
        label: `副图 ${index + 1}`,
        path,
        url: path,
        previewable: true,
        meta: typeof item === 'string' ? 'gallery image' : (item?.role || item?.label || 'gallery image'),
      };
    }),
    ...legacyContactSheets.map((sheet, index) => sheet?.sheet_path && !isVirtualImageBatch(sheet) && {
      key: `analysis-sheet-${index}-${sheet.sheet_path}`,
      kind: '分析图',
      label: `分析图 ${sheet.sheet_page || index + 1}`,
      path: sheet.sheet_path,
      url: analysisBatchDisplayUrl(sheet),
      oss_url: sheet.oss_url,
      localPath: sheet.sheet_path,
      previewable: true,
      meta: sheet.oss_url ? `OSS · ${sheet.image_ids?.length || 0} 张图` : `${sheet.image_ids?.length || 0} 张图`,
    }),
    ...(Array.isArray(aplusGeneratedImages) ? aplusGeneratedImages.map((item, index) => {
      const displayUrl = item?.display_url || item?.url || item?.oss_url || item?.provider_url || item?.path;
      return displayUrl && {
        key: `aplus-image-${index}-${displayUrl}`,
        kind: 'A+图片',
        label: `A+ 模块 ${item.position || index + 1}`,
        path: displayUrl,
        url: displayUrl,
        oss_url: item?.oss_url,
        localPath: item?.path,
        previewable: true,
        meta: item?.oss_url ? 'OSS' : (item?.status || fileSize(item?.size)),
      };
    }) : []),
  ].filter(Boolean);

  const openPath = async (path?: string, directory = false) => {
    const operationKey = fileOpenOperationKey(path, directory);
    setFileOpening(operationKey);
    await runMutationWithUX(
      'openProductFile|frontend/src/pages/ProductDetail.tsx|openPath',
      async (metadata) => {
        await openProductFile(product.id, path, directory, metadata);
        message.success('已打开');
      },
      {
        errorFallback: '打开失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setFileOpening(null),
      },
    ).catch(() => undefined);
  };

  const isFileOpening = (path?: string | null, directory = false) => (
    fileOpening === fileOpenOperationKey(path, directory)
  );

  const previewSpreadsheet = async (asset: ProductMaterialAsset) => {
    setSpreadsheetPreviewTitle(asset.original_filename || '表格预览');
    setSpreadsheetPreviewLoading(true);
    try {
      const { data: preview } = await getProductMaterialSpreadsheetPreview(product.id, asset.id);
      setSpreadsheetPreview(preview);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '表格预览失败');
    } finally {
      setSpreadsheetPreviewLoading(false);
    }
  };

  const copyText = async (value?: string | null) => {
    const text = String(value || '').trim();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      message.success('已复制');
    } catch {
      message.error('复制失败');
    }
  };

  const extractZip = async (path: string) => {
    setZipExtractingPath(path);
    await runMutationWithUX(
      'extractProductZip|frontend/src/pages/ProductDetail.tsx|extractZip',
      async (metadata) => {
        await extractProductZip(product.id, path, metadata);
        message.success('已解压');
        await fetchDetail(true);
      },
      {
        errorFallback: '解压失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setZipExtractingPath(null),
      },
    ).catch(() => undefined);
  };

  const regenerateAplus = async () => {
    if (!regenTarget) return;
    const reason = regenReason.trim();
    if (!reason) {
      message.warning('先写一下哪里不行，系统会按这个原因重写脚本');
      return;
    }
    setRegenLoading(true);
    await runMutationWithUX(
      'regenerateAplusModule|frontend/src/pages/ProductDetail.tsx|regenerateAplus',
      async (metadata) => {
        const { data: result } = await regenerateAplusModule(product.id, {
          module_position: regenTarget.module_position,
          reason,
        }, metadata);
        message.success(result?.message || '已提交后台重新生成');
        setRegenTarget(null);
        setRegenReason('');
        await fetchDetail();
      },
      {
        errorFallback: 'A+重新生成失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setRegenLoading(false),
      },
    ).catch(() => undefined);
  };

  const retryInterruptedAplus = async () => {
    setRegenRetryLoading(true);
    await runMutationWithUX(
      'retryAplusRegeneration|frontend/src/pages/ProductDetail.tsx|retryInterruptedAplus',
      async (metadata) => {
        const { data: result } = await retryAplusRegeneration(product.id, metadata);
        message.success(result?.message || '已重新排队 A+ 重新生图任务');
        await fetchDetail();
      },
      {
        errorFallback: 'A+重新生图重试失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setRegenRetryLoading(false),
      },
    ).catch(() => undefined);
  };

  const generateAplus = async (force = false) => {
    setAplusGenerateLoading(true);
    await runMutationWithUX(
      'generateProductAplus|frontend/src/pages/ProductDetail.tsx|generateAplus',
      async (metadata) => {
        await generateProductAplus(product.id, force, metadata);
        message.success(force ? '已创建任务中心任务：重新生成 A+' : '已创建任务中心任务：生成 A+');
        await fetchDetail();
      },
      {
        errorFallback: 'A+生成任务创建失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setAplusGenerateLoading(false),
      },
    ).catch(() => undefined);
  };

  const regenerateListing = async () => {
    setListingRegenerateLoading(true);
    await runMutationWithUX(
      'runProductFromStep|frontend/src/pages/ProductDetail.tsx|regenerateListing',
      async (metadata) => {
        await runProductFromStep(product.id, 6, metadata);
        message.success('已提交任务中心：重新生成 Listing 文案，完成后会自动回到待导出');
        await fetchDetail();
      },
      {
        errorFallback: 'Listing 文案重新生成失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setListingRegenerateLoading(false),
      },
    ).catch(() => undefined);
  };

  const generateCustomerMindset = async () => {
    setPipelineRetryLoading(true);
    await runMutationWithUX(
      'runPipelineStep|frontend/src/pages/ProductDetail.tsx|generateCustomerMindset',
      async (metadata) => {
        const { data: result } = await runPipelineStep(product.id, 6, metadata);
        if (result.workflow_node !== 'customer_mindset') {
          message.info('用户心智已完成，后续 Listing 任务已提交');
        } else {
          message.success('已提交任务中心：生成用户心智');
        }
        await fetchDetail();
      },
      {
        errorFallback: '用户心智任务创建失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setPipelineRetryLoading(false),
      },
    ).catch(() => undefined);
  };

  const retryInterruptedPipeline = async () => {
    setPipelineRetryLoading(true);
    await runMutationWithUX(
      'runProductFromStep|frontend/src/pages/ProductDetail.tsx|retryInterruptedPipeline',
      async (metadata) => {
        await runProductFromStep(product.id, Math.max(Number(product.current_step || 5), 5), metadata);
        message.success('已提交任务中心：重试当前节点');
        await fetchDetail();
      },
      {
        errorFallback: '重试当前节点失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setPipelineRetryLoading(false),
      },
    ).catch(() => undefined);
  };

  const setDraftListingImagePaths = (paths: string[]) => {
    setListingImageDraftPaths(paths.filter((path, index) => path && paths.indexOf(path) === index));
    setListingImageDirty(true);
  };

  const saveListingImagePaths = async () => {
    const orderedPaths = listingImageDraftPaths.filter(Boolean);
    if (!orderedPaths.length) return;
    if (orderedPaths.length > DEFAULT_LISTING_IMAGE_LIMIT) {
      message.warning(`已使用图片最多 ${DEFAULT_LISTING_IMAGE_LIMIT} 张，请先移出多余图片`);
      return;
    }
    setImageOrderSaving(true);
    await runMutationWithUX(
      'updateProductListingImages|frontend/src/pages/ProductDetail.tsx|saveListingImagePaths',
      async (metadata) => {
        await updateProductListingImages(product.id, {
          main_image_path: orderedPaths[0],
          gallery_images: orderedPaths.slice(1),
        }, metadata);
        message.success('商品图片已确认');
        setListingImageDirty(false);
        setImageDragPayload(null);
        await fetchDetail();
      },
      {
        errorFallback: '主图/副图保存失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setImageOrderSaving(false),
      },
    ).catch(() => undefined);
  };

  const resetListingImageDraft = () => {
    const nextPaths = listingImagePathsFromImages(images);
    setListingImageDraftPaths(nextPaths);
    setListingImageDirty(listingImageDraftIsDirty(images, nextPaths));
    setImageDragPayload(null);
  };

  const saveListingImageOrder = (nextImages: any[]) => {
    const orderedPaths = nextImages.map((item) => item?.path).filter(Boolean);
    setDraftListingImagePaths(orderedPaths);
  };

  const dragPayloadFromEvent = (event: React.DragEvent) => {
    if (imageDragPayload) return imageDragPayload;
    const raw = event.dataTransfer.getData('application/json');
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  };

  const startListingImageDrag = (event: React.DragEvent, payload: any) => {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/json', JSON.stringify(payload));
    setImageDragPayload(payload);
  };

  const replaceListingImageSlot = (event: React.DragEvent, toIndex: number) => {
    event.preventDefault();
    event.stopPropagation();
    const payload = dragPayloadFromEvent(event);
    if (!payload) return;
    if (payload.source === 'selected') {
      moveListingImage(payload.index, toIndex);
      return;
    }
    const nextPaths = selectedListingImages.map((item: any) => item?.path).filter(Boolean);
    const nextPath = payload.path;
    if (!nextPath) {
      setImageDragPayload(null);
      return;
    }
    const withoutDragged = nextPaths.filter((path) => path !== nextPath);
    withoutDragged.splice(Math.min(toIndex, withoutDragged.length), 0, nextPath);
    setDraftListingImagePaths(withoutDragged);
    setImageDragPayload(null);
  };

  const dropListingImageToSelected = (event: React.DragEvent) => {
    event.preventDefault();
    const payload = dragPayloadFromEvent(event);
    if (!payload) return;
    if (payload.source === 'pool' && payload.path) {
      const nextPaths = selectedListingImages.map((item: any) => item?.path).filter(Boolean);
      if (!nextPaths.includes(payload.path) && nextPaths.length >= DEFAULT_LISTING_IMAGE_LIMIT) {
        message.warning(`已使用图片最多 ${DEFAULT_LISTING_IMAGE_LIMIT} 张，请先移出一张`);
        setImageDragPayload(null);
        return;
      }
      setDraftListingImagePaths([...nextPaths.filter((path) => path !== payload.path), payload.path]);
    }
    setImageDragPayload(null);
  };

  const dropListingImageToUnusedPool = (event: React.DragEvent) => {
    event.preventDefault();
    const payload = dragPayloadFromEvent(event);
    if (!payload) return;
    if (payload.source === 'selected') {
      const nextPaths = selectedListingImages
        .map((item: any) => item?.path)
        .filter((path) => path && path !== payload.path);
      setDraftListingImagePaths(nextPaths);
    }
    setImageDragPayload(null);
  };

  const moveListingImage = (fromIndex: number | null, toIndex: number) => {
    if (fromIndex == null || fromIndex === toIndex) {
      setImageDragPayload(null);
      return;
    }
    const nextImages = [...selectedListingImages];
    const [moved] = nextImages.splice(fromIndex, 1);
    nextImages.splice(toIndex, 0, moved);
    saveListingImageOrder(nextImages);
    setImageDragPayload(null);
  };

  const addListingImageFromPool = (path: string | null | undefined) => {
    if (imageOrderSaving || !path) return;
    const nextPaths = selectedListingImages.map((item: any) => item?.path).filter(Boolean);
    if (!nextPaths.includes(path) && nextPaths.length >= DEFAULT_LISTING_IMAGE_LIMIT) {
      message.warning(`已使用图片最多 ${DEFAULT_LISTING_IMAGE_LIMIT} 张，请先移出一张`);
      return;
    }
    setDraftListingImagePaths([...nextPaths.filter((itemPath) => itemPath !== path), path]);
  };

  const removeListingImageFromSelected = (path: string | null | undefined) => {
    if (imageOrderSaving || !path) return;
    const nextPaths = selectedListingImages
      .map((item: any) => item?.path)
      .filter((itemPath) => itemPath && itemPath !== path);
    setDraftListingImagePaths(nextPaths);
  };

  const handleListingImageDoubleClick = (
    event: React.MouseEvent,
    path: string | null | undefined,
    action: (path: string | null | undefined) => void,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    action(path);
  };

  const openCategoryEditor = async () => {
    setSelectedCategoryKey(undefined);
    setCategoryEditOpen(true);
    setCategoryOptionsLoading(true);
    try {
      const { data: result } = await listCategoryOptions();
      const items = result.items || [];
      setCategoryOptions(items);
      const currentCategories = Array.isArray(categories) ? categories : [];
      const currentKey = currentCategories.join(' > ') || data?.leaf_category || '';
      const matched = items.find((item) => item.key === currentKey || item.label === categoryPath || item.leaf_category === data?.leaf_category);
      if (matched) {
        setSelectedCategoryKey(matched.key);
      }
    } catch {
      message.error('类目列表加载失败');
    } finally {
      setCategoryOptionsLoading(false);
    }
  };

  const saveCategory = async () => {
    const selected = categoryOptions.find((item) => item.key === selectedCategoryKey);
    if (!selected) {
      message.warning('请从已有类目列表中选择 Amazon 类目');
      return;
    }
    setCategorySaving(true);
    await runMutationWithUX(
      'updateProduct|frontend/src/pages/ProductDetail.tsx|saveCategory',
      async (metadata) => {
        await updateProduct(product.id, {
          categories: selected.categories,
          leaf_category: selected.leaf_category,
        }, metadata);
        message.success('类目已保存');
        setCategoryEditOpen(false);
        await fetchDetail();
      },
      {
        errorFallback: '类目保存失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setCategorySaving(false),
      },
    ).catch(() => undefined);
  };

  const openListingEditor = () => {
    const highlightDrafts = productHighlightDrafts(
      data?.listing_product_highlights,
      data?.listing_product_highlights_zh,
    );
    setListingTitleInput(data?.listing_title || '');
    setListingBulletsInput(parseJson(data?.listing_bullets, []).join('\n'));
    setListingProductHighlightsInput(highlightDrafts.english);
    setListingDescriptionInput(data?.listing_description || '');
    setListingSearchTermsInput(data?.listing_search_terms || '');
    setListingTitleZhInput(data?.listing_title_zh || '');
    setListingBulletsZhInput(parseJson(data?.listing_bullets_zh, []).join('\n'));
    setListingProductHighlightsZhInput(highlightDrafts.chinese);
    setListingDescriptionZhInput(data?.listing_description_zh || '');
    setListingSearchTermsZhInput(data?.listing_search_terms_zh || '');
    setListingPrimaryKeywordInput((data?.listing_primary_keyword as string) || '');
    setListingEditOpen(true);
  };

  const updateProductHighlight = (index: number, value: string, chinese = false) => {
    const setter = chinese ? setListingProductHighlightsZhInput : setListingProductHighlightsInput;
    setter((current) => current.map((item, itemIndex) => (itemIndex === index ? value : item)));
  };

  const saveListing = async () => {
    if (!listingTitleInput.trim()) {
      message.warning('请填写标题');
      return;
    }
    if (listingTitleInput.trim().length > 75) {
      message.warning('标题不能超过 75 个字符');
      return;
    }
    const productHighlights = listingProductHighlightsInput.map((item) => item.trim());
    if (productHighlights.length !== 1 || !productHighlights[0]) {
      message.warning('请填写 1 条标题补充');
      return;
    }
    if (productHighlights[0].length > 120) {
      message.warning('标题补充不能超过 120 个字符');
      return;
    }
    const productHighlightsZh = listingProductHighlightsZhInput.map((item) => item.trim());
    const hasChineseProductHighlights = productHighlightsZh.some(Boolean);
    if (hasChineseProductHighlights && !productHighlightsZh[0]) {
      message.warning('中文标题补充填写后，需要与英文标题补充对应');
      return;
    }
    if (productHighlightsZh[0]?.length > 120) {
      message.warning('中文标题补充不能超过 120 个字符');
      return;
    }
    setListingSaving(true);
    await runMutationWithUX(
      'updateProduct|frontend/src/pages/ProductDetail.tsx|saveListing',
      async (metadata) => {
        await updateProduct(product.id, {
          listing_title: listingTitleInput.trim(),
          listing_bullets: listingBulletsInput,
          listing_product_highlights: productHighlights,
          listing_description: listingDescriptionInput.trim(),
          listing_search_terms: listingSearchTermsInput.trim(),
          listing_title_zh: listingTitleZhInput.trim(),
          listing_bullets_zh: listingBulletsZhInput,
          listing_product_highlights_zh: hasChineseProductHighlights ? productHighlightsZh : null,
          listing_description_zh: listingDescriptionZhInput.trim(),
          listing_search_terms_zh: listingSearchTermsZhInput.trim(),
          listing_primary_keyword: listingPrimaryKeywordInput.trim(),
        }, metadata);
        message.success('Listing 已保存');
        setListingEditOpen(false);
        await fetchDetail();
      },
      {
        errorFallback: 'Listing 保存失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setListingSaving(false),
      },
    ).catch(() => undefined);
  };

  const doRestart = async () => {
    setRestartLoading(true);
    await runMutationWithUX(
      'restartPipeline|frontend/src/pages/ProductDetail.tsx|doRestart',
      async (metadata) => {
        await restartPipeline(product.id, metadata);
        await fetchDetail();
        message.success('已重新开始');
      },
      {
        errorFallback: '重新开始失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setRestartLoading(false),
      },
    ).catch(() => undefined);
  };

  const openImageReview = () => {
    navigate(`/products/image-review?product_id=${product.id}`);
  };

  const runWorkflowAction = async (action?: string | null) => {
    if (!action) return;
    const definition = getProductWorkflowAction(action);
    if (!definition) {
      await dispatchProductWorkflowAction(action, { productId: product.id, navigate });
      return;
    }
    const isApiAction = definition.kind === 'api';
    if (isApiAction) setPipelineRetryLoading(true);
    if (!isApiAction) {
      try {
        await dispatchProductWorkflowAction(action, {
          productId: product.id,
          relatedCorrelationKey: workflow?.related_correlation_key,
          navigate,
        });
      } catch (e: any) {
        message.error(e?.response?.data?.detail || '操作失败');
      }
      return;
    }
    await runMutationWithUX(
      PRODUCT_DETAIL_WORKFLOW_CALLSITE_IDS[definition.client_export],
      async (metadata) => {
        const result = await dispatchProductWorkflowAction(action, {
          productId: product.id,
          relatedCorrelationKey: workflow?.related_correlation_key,
          mutationMetadata: metadata,
          navigate,
        });
        if (result.status !== 'handled') return;
        message.success(workflow?.primary_action_label ? `已提交：${workflow.primary_action_label}` : '已提交处理');
        await fetchDetail();
      },
      {
        errorFallback: '操作失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setPipelineRetryLoading(false),
      },
    ).catch(() => undefined);
  };

  const renderWorkflowActionButton = (action?: string | null, label?: string | null, primary = false) => {
    if (!action) return null;
    const definition = getProductWorkflowAction(action);
    if (!definition) {
      reportUnknownProductWorkflowAction(action);
      return <ProductWorkflowUnknownAction action={action} surface="product-detail" />;
    }
    if (action === 'open_detail') return null;
    const icon = action === 'open_task_center' || action === 'resume' ? <PlayCircleOutlined /> : <RedoOutlined />;
    return (
      <Button
        type={primary ? 'primary' : 'default'}
        icon={icon}
        loading={pipelineRetryLoading}
        onClick={() => runWorkflowAction(action)}
      >
        {label || definition.default_label}
      </Button>
    );
  };

  const workflowSecondaryActions = (workflow?.allowed_actions || [])
    .filter((action: string) => action && action !== workflow?.primary_action && action !== 'open_detail')
    .filter((action: string, index: number, actions: string[]) => actions.indexOf(action) === index);

  const packageColumns = [
    { title: '外包装商品', dataIndex: 'code', width: 180, render: (v) => v || '-' },
    { title: '数量', dataIndex: 'qty', width: 90, render: (v) => v || '-' },
    { title: '长', dataIndex: 'length', width: 90, render: (v) => numberText(v) },
    { title: '宽', dataIndex: 'width', width: 90, render: (v) => numberText(v) },
    { title: '高', dataIndex: 'height', width: 90, render: (v) => numberText(v) },
    { title: '重量', dataIndex: 'weight_value', width: 100, render: (v, record) => numberText(v ?? record.weight) },
    { title: '原始文本', dataIndex: 'dimensions', render: (v, record) => v || record.weight || '-' },
  ];

  const materialKindLabel = (kind?: string | null) => ({
    zip: '素材包',
    image: '图片',
    video: '视频',
    spreadsheet: '表格',
    html: 'HTML',
    pdf: 'PDF',
    text: '文本',
    other: '其他',
  }[String(kind || '')] || String(kind || '未知'));

  const materialPackageLabel = (kind?: string | null) => ({
    to_b: 'To B 素材包',
    information: 'Information',
    retail_ready: 'Retail Ready',
  }[String(kind || '')] || String(kind || '未分类'));

  const materialStatusMeta = (status?: string | null, assetKind?: string | null) => {
    const normalizedStatus = String(status || '');
    // `ready` is the persisted ingestion state, not a universal analysis state:
    // ZIPs have already been extracted, while images await visual analysis and
    // supporting documents are merely registered for fact extraction/preview.
    if (normalizedStatus === 'ready') {
      if (assetKind === 'zip') return { color: 'success', label: '已解压' };
      if (assetKind === 'image') return { color: 'processing', label: '待分析' };
      return { color: 'processing', label: '已登记' };
    }
    return ({
      analyzed: { color: 'cyan', label: '已分析' },
      selected: { color: 'success', label: '已选用' },
      rejected: { color: 'error', label: '已拒绝' },
      stale: { color: 'default', label: '历史素材' },
    } as Record<string, { color: string; label: string }>)[normalizedStatus]
      || { color: 'default', label: normalizedStatus || '未知' };
  };

  const materialUsageLabels: Record<string, string> = {
    source_archive: '来源压缩包',
    product_detail_preview: '商品详情预览',
    preview_only: '仅供预览',
    auto_image_selection_candidate: '自动选图候选',
    product_fact_source: '商品事实来源',
    unsupported_for_fact_extraction: '暂不支持事实提取',
    fact_extraction_failed: '事实提取失败',
    contact_sheet_review: 'Contact Sheet 分析',
    listing_main: 'Listing 主图',
    listing_gallery: 'Listing Gallery',
    aplus_reference: 'A+ 参考图',
  };

  const materialPreview = (asset: ProductMaterialAsset) => {
    const url = productMaterialPreviewUrl(product.id, asset.id);
    const suffix = String(asset.original_filename || '').toLowerCase();
    if (asset.asset_kind === 'image') {
      return <Image src={url} width={92} height={68} style={{ objectFit: 'cover', borderRadius: 4 }} />;
    }
    if (asset.asset_kind === 'video') {
      return <video src={url} controls preload="metadata" style={{ width: 190, maxHeight: 112, borderRadius: 4, background: '#111' }} />;
    }
    if (asset.asset_kind === 'spreadsheet' && (suffix.endsWith('.xlsx') || suffix.endsWith('.csv') || suffix.endsWith('.tsv'))) {
      return (
        <Button size="small" icon={<EyeOutlined />} loading={spreadsheetPreviewLoading} onClick={() => previewSpreadsheet(asset)}>
          预览表格
        </Button>
      );
    }
    if (asset.asset_kind === 'pdf' || asset.asset_kind === 'html' || asset.asset_kind === 'text') {
      return (
        <Button size="small" icon={asset.asset_kind === 'pdf' ? <FilePdfOutlined /> : <FileTextOutlined />} onClick={() => window.open(url, '_blank', 'noopener,noreferrer')}>
          浏览器预览
        </Button>
      );
    }
    if (asset.asset_kind === 'zip') {
      return <Text type="secondary">展开查看成员</Text>;
    }
    return <Text type="secondary">使用右侧打开</Text>;
  };

  const materialColumns = [
    {
      title: '类型',
      dataIndex: 'asset_kind',
      width: 110,
      render: (value: string) => <Tag icon={value === 'video' ? <VideoCameraOutlined /> : undefined}>{materialKindLabel(value)}</Tag>,
    },
    {
      title: '文件与来源',
      dataIndex: 'original_filename',
      width: 320,
      render: (value: string, record: ProductMaterialAsset) => (
        <Space direction="vertical" size={2} style={{ maxWidth: 300 }}>
          <Text strong ellipsis={{ tooltip: value }}>{value}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{materialPackageLabel(record.package_type)}</Text>
          <Text type="secondary" copyable style={{ fontSize: 11 }} ellipsis={{ tooltip: record.relative_path || record.path }}>
            {record.relative_path || record.path}
          </Text>
        </Space>
      ),
    },
    {
      title: '预览',
      key: 'preview',
      width: 220,
      render: (_: unknown, record: ProductMaterialAsset) => materialPreview(record),
    },
    {
      title: '文件信息',
      key: 'facts',
      width: 170,
      render: (_: unknown, record: ProductMaterialAsset) => (
        <Space direction="vertical" size={1}>
          <Text>{fileSize(record.file_size)}</Text>
          {record.width && record.height ? <Text type="secondary">{record.width} × {record.height}</Text> : null}
          <Text type="secondary" style={{ fontSize: 11 }}>SHA-256 {record.content_hash.slice(0, 12)}…</Text>
        </Space>
      ),
    },
    {
      title: '状态与用途',
      key: 'status',
      width: 250,
      render: (_: unknown, record: ProductMaterialAsset) => {
        const status = materialStatusMeta(record.processing_status, record.asset_kind);
        const usages = parseJson(record.downstream_usage_json, []);
        return (
          <Space direction="vertical" size={4}>
            <Space wrap>
              <Tag color={status.color}>{status.label}</Tag>
              {record.contact_sheet_page ? <Tag>Sheet {record.contact_sheet_page} · {record.contact_sheet_label || '-'}</Tag> : null}
            </Space>
            <Space wrap>
              {(Array.isArray(usages) ? usages : []).map((usage: string) => (
                <Tag key={usage} color={usage === 'listing_main' ? 'green' : undefined}>{materialUsageLabels[usage] || usage}</Tag>
              ))}
              {(!Array.isArray(usages) || usages.length === 0) && <Text type="secondary">尚未进入下游</Text>}
            </Space>
            {record.rejection_reason ? <Text type="danger">{record.rejection_reason}</Text> : null}
          </Space>
        );
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      fixed: 'right',
      render: (_: unknown, record: ProductMaterialAsset) => (
        <Space size="small">
          <Button size="small" loading={isFileOpening(record.path)} onClick={() => openPath(record.path)}>打开</Button>
          <Button size="small" icon={<FolderOpenOutlined />} loading={isFileOpening(record.path, true)} onClick={() => openPath(record.path, true)}>文件夹</Button>
        </Space>
      ),
    },
  ];

  const zipColumns = [
    {
      title: '压缩包',
      dataIndex: 'name',
      render: (name, record) => (
        <Button type="link" icon={<FileZipOutlined />} loading={isFileOpening(record.path)} disabled={isFileOpening(record.path)} onClick={() => openPath(record.path)} style={{ padding: 0 }}>
          {name}
        </Button>
      ),
    },
    { title: '大小', dataIndex: 'size', width: 110, render: fileSize },
    { title: '修改时间', dataIndex: 'modified_at', width: 180, render: (v) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
    {
      title: '解压内容',
      dataIndex: 'extracted_files',
      render: (files, record) => record.extracted_exists ? (
        <div>
          <Tag color="success">已解压</Tag>
          {files?.length ? (
            <div style={{ marginTop: 6, color: '#555' }}>
              {files.slice(0, 5).map((file) => <div key={file}>{file}</div>)}
              {files.length > 5 && <Text type="secondary">还有 {files.length - 5} 个文件</Text>}
            </div>
          ) : <Text type="secondary">文件夹为空</Text>}
        </div>
      ) : <Text type="secondary">未解压</Text>,
    },
    {
      title: '操作',
      width: 220,
      render: (_, record) => (
        <Space size="small">
          <Button size="small" icon={<InboxOutlined />} loading={zipExtractingPath === record.path} onClick={() => extractZip(record.path)}>解压</Button>
          <Button size="small" icon={<FolderOpenOutlined />} loading={isFileOpening(record.extracted_dir)} disabled={!record.extracted_exists || isFileOpening(record.extracted_dir)} onClick={() => openPath(record.extracted_dir)}>文件夹</Button>
        </Space>
      ),
    },
  ];

  const generatedFileColumns = [
    { title: '文件', dataIndex: 'label', render: (label, record) => (
      <Space direction="vertical" size={2}>
        <Text strong>{label || record.file_type}</Text>
        <Text type="secondary" copyable style={{ fontSize: 12 }}>{record.path}</Text>
      </Space>
    ) },
    { title: '类型', dataIndex: 'file_type', width: 160, render: (value) => <Tag>{value}</Tag> },
    { title: '更新时间', dataIndex: 'updated_at', width: 180, render: (value) => value ? new Date(value).toLocaleString('zh-CN') : '-' },
    { title: '操作', width: 240, render: (_, record) => (
      <Space size="small">
        <Button size="small" icon={<FileExcelOutlined />} loading={isFileOpening(record.path)} disabled={isFileOpening(record.path)} onClick={() => openPath(record.path)}>打开文件</Button>
        <Button size="small" icon={<FolderOpenOutlined />} loading={isFileOpening(record.path, true)} disabled={isFileOpening(record.path, true)} onClick={() => openPath(record.path, true)}>打开文件夹</Button>
      </Space>
    ) },
  ];

  const fileIndexColumns = [
    { title: '分类', dataIndex: 'kind', width: 110, render: (value) => <Tag>{value}</Tag> },
    { title: '名称', dataIndex: 'label', width: 180, render: (value) => <Text strong>{value}</Text> },
    {
      title: '资源',
      dataIndex: 'path',
      render: (value, record) => {
        const resourceUrl = record.url || record.displayUrl || value;
        if (record.previewable && resourceUrl) {
          return (
            <Space align="start">
              <Image
                src={imgUrl(resourceUrl)}
                width={76}
                height={56}
                alt={record.label}
                style={{ objectFit: 'cover', borderRadius: 4, border: '1px solid #eee' }}
              />
              <Space direction="vertical" size={2} style={{ maxWidth: 520 }}>
                <Text copyable style={{ fontSize: 12 }} ellipsis>
                  {resourceUrl}
                </Text>
                {record.oss_url && <Tag color="success">OSS</Tag>}
              </Space>
            </Space>
          );
        }
        return <Text copyable style={{ maxWidth: '100%' }}>{value || '-'}</Text>;
      },
    },
    { title: '说明', dataIndex: 'meta', width: 180, render: (value) => value || '-' },
    {
      title: '操作',
      width: 220,
      render: (_, record) => {
        const resourceUrl = record.url || record.displayUrl || record.path;
        const localPath = record.localPath || (!isRemoteUrl(record.path) ? record.path : null);
        return (
          <Space size="small">
            {isRemoteUrl(resourceUrl) ? (
              <Button size="small" icon={<ExportOutlined />} onClick={() => window.open(resourceUrl, '_blank', 'noopener,noreferrer')}>
                打开URL
              </Button>
            ) : (
              <Button size="small" icon={<FolderOpenOutlined />} loading={isFileOpening(record.path, record.directory)} disabled={isFileOpening(record.path, record.directory)} onClick={() => openPath(record.path, record.directory)}>打开</Button>
            )}
            {localPath && !record.directory && <Button size="small" loading={isFileOpening(localPath, true)} disabled={isFileOpening(localPath, true)} onClick={() => openPath(localPath, true)}>文件夹</Button>}
          </Space>
        );
      },
    },
  ];

  const stoppedStatuses = ['failed', 'unavailable', 'source_unavailable'];
  const workflowStepStatusValue = workflow?.stage_status === 'failed' ? 'error' : workflow?.stage_status === 'succeeded' ? 'finish' : 'process';
  const stepStatus = hasWorkflow ? workflowStepStatusValue : stoppedStatuses.includes(product.status) ? 'error' : ['completed', 'pending_review'].includes(product.status) ? 'finish' : 'process';
  const isStopped = stoppedStatuses.includes(product.status);
  const isPaused = product.status === 'paused';
  const isReadyToExport = hasWorkflow
    ? ['export_ready', 'exported'].includes(workflow?.work_status || '')
    : product.status === 'completed' && product.current_step >= 6;
  const referenceAsin = product.competitor_asin || '';
  const hasConfirmedSearchImage = Boolean(images?.main_image_path);
  const hasReferenceCompetitor = Boolean(referenceAsin);
  const isCompetitorSearching = product.status === 'competitor_searching';
  const isCompetitorSearchFailed = Boolean(
    product.status === 'failed' && /同款搜索|候选竞品|参考竞品|选择竞品|自动竞品搜索/i.test(product.error_message || '')
  );
  const isLegacyGigaBrowserCollectError = Boolean(
    product.status === 'failed'
    && Number(product.current_step || 0) <= 1
    && /大健商品核心信息采集失败|index\.php\?route=product\/product|Step1 浏览器采集已停用/.test(product.error_message || '')
  );
  const productErrorMessage = isLegacyGigaBrowserCollectError
    ? '旧浏览器采集已停用。请回到商品工作台或任务中心，通过店铺/OpenAPI 同步商品源数据。'
    : product.error_message;
  const failedStep = Number(product.current_step || 0);
  const isImageAnalysisPrerequisiteFailed = Boolean(
    product.status === 'failed'
    && /图片分析节点未完成|不能进入 Listing 文案/.test(product.error_message || '')
  );
  const isImageAnalysisFailed = Boolean(
    isImageAnalysisPrerequisiteFailed
    || (
      product.status === 'failed'
      && failedStep === 5
      && (workflow?.stage || workflow?.node_key) !== 'customer_mindset'
    )
  );
  const isCustomerMindsetFailed = Boolean(
    product.status === 'failed'
    && (
      (workflow?.stage || workflow?.node_key) === 'customer_mindset'
      || /用户心智|customer mindset|customer_mindset/i.test(product.error_message || '')
    )
  );
  const isHardStopped = isStopped && !isCompetitorSearchFailed && !isImageAnalysisFailed && !isCustomerMindsetFailed;
  const showTopProductError = Boolean(
    productErrorMessage
  );
  const hasListingContent = Boolean(
    data?.listing_title
    || data?.listing_bullets
    || data?.listing_search_terms
    || data?.listing_description_zh
  );
  const hasListingImages = Boolean(images?.main_image_path);
  const hasImageAnalysis = Boolean(
    images?.image_analysis
    || images?.image_selling_points
    || imageAnalysisBatches.length
    || product.current_step > 5
    || isReadyToExport
  );
  const hasCustomerMindset = Boolean(
    customerMindset?.schema_version === 'customer_mindset_v1'
    && customerMindsetFixedQuestionCount === 13
    && customerMindsetDynamicQuestionCount >= 2
    && customerMindsetDynamicQuestionCount <= 5
    && customerMindsetStrategy?.core_value_proposition
  );
  const hasAplusOutput = Boolean(
    aplus?.aplus_status === 'done'
    || aplus?.aplus_status === 'regen_done'
    || (Array.isArray(aplusGeneratedImages) && aplusGeneratedImages.length)
  );
  const aplusProgressText = [
    aplusPlanReady ? '规划已完成' : '待规划',
    aplusScriptReady ? '脚本已完成' : '待脚本',
    aplusImageDoneCount ? `出图 ${aplusImageDoneCount}/5` : '待出图',
  ].join('，');
  const canGenerateAplus = isReadyToExport && hasListingContent && hasImageAnalysis;
  const aplusGenerateDisabledReason = (() => {
    if (isAplusRegenerating) return 'A+生成中，请等待后台任务完成';
    if (!isReadyToExport) return '只有待导出或已导出的商品可以生成 A+';
    if (!hasListingContent) return 'Listing文案未完成';
    if (!hasImageAnalysis) return '图片分析未完成';
    return '';
  })();
  const statusSuffix = isPaused ? '，已挂起' : '';
  const nodeErrorAt = (node: string) => {
    if (isCompetitorSearchFailed) return node === 'find-competitors';
    if (isImageAnalysisFailed) return node === 'image-analysis';
    if (isCustomerMindsetFailed) return node === 'customer-mindset';
    if (!isStopped) return false;
    const step = failedStep;
    if (node === 'find-competitors') return step <= 2;
    if (node === 'choose-competitor') return step <= 4;
    if (node === 'image-analysis') return step === 5;
    if (node === 'customer-mindset') return false;
    if (node === 'listing') return step === 6;
    return false;
  };
  const nodeActiveAt = (node: string) => {
    if (isHardStopped || isReadyToExport) return false;
    if (node === 'search-image') return !hasConfirmedSearchImage;
    if (node === 'find-competitors') return isCompetitorSearching || (hasConfirmedSearchImage && !hasReferenceCompetitor && !isCompetitorSearchFailed);
    if (node === 'choose-competitor') return hasConfirmedSearchImage && !hasReferenceCompetitor && !isCompetitorSearching;
    if (node === 'image-analysis') return hasReferenceCompetitor && hasListingImages && !hasImageAnalysis;
    if (node === 'customer-mindset') return hasImageAnalysis && !hasCustomerMindset;
    if (node === 'listing') return hasReferenceCompetitor && hasImageAnalysis && hasCustomerMindset && !hasListingContent;
    if (node === 'export') return isReadyToExport;
    return false;
  };
  const toWorkflowItem = (item: any) => ({
    title: item.title,
    description: item.description,
    status: item.error ? 'error' : item.done ? 'finish' : item.active ? 'process' : 'wait',
  });

  // 商品详情页展示业务节点，不再展示旧的内部技术 Pipeline。
  const legacyPipelineSteps = [
    {
      title: '确认商品图片',
      description: hasConfirmedSearchImage ? `已确认主图和 Listing 图片，已选 ${listingImageCount || 1} 张` : `等待确认主图和 Listing 图片${statusSuffix}`,
      done: hasConfirmedSearchImage || hasReferenceCompetitor || product.current_step >= 5,
      active: nodeActiveAt('search-image'),
    },
    {
      title: '搜索候选竞品',
      description: isCompetitorSearchFailed
        ? (product.error_message || 'Amazon 竞品搜索失败，请回到商品列表或任务中心重试')
        : isCompetitorSearching
          ? (product.error_message || '正在搜索 Amazon 参考竞品')
        : hasReferenceCompetitor
          ? '已完成参考竞品选择'
          : hasConfirmedSearchImage
            ? `等待自动搜索 Amazon 参考竞品${statusSuffix}`
            : `等待先确认商品图片${statusSuffix}`,
      done: hasReferenceCompetitor && !isCompetitorSearchFailed && !isCompetitorSearching,
      active: nodeActiveAt('find-competitors'),
      error: nodeErrorAt('find-competitors'),
    },
    {
      title: '选择竞品',
      description: referenceAsin
        ? `已选参考竞品 ${referenceAsin}`
        : `等待自动竞品链路选择参考竞品${statusSuffix}`,
      done: hasReferenceCompetitor,
      active: nodeActiveAt('choose-competitor'),
      error: nodeErrorAt('choose-competitor') && !hasReferenceCompetitor,
    },
    {
      title: '图片分析',
      description: isImageAnalysisFailed
        ? (product.error_message || '图片分析未完成，请重试当前节点')
        : hasImageAnalysis ? '图片分析和卖点提取已完成' : `等待分析主图、副图和图片卖点${statusSuffix}`,
      done: hasImageAnalysis,
      active: nodeActiveAt('image-analysis'),
      error: nodeErrorAt('image-analysis'),
    },
    {
      title: '用户心智',
      description: isCustomerMindsetFailed
        ? (product.error_message || '用户心智梳理未完成，请在任务中心查看原因')
        : hasCustomerMindset
          ? `已完成 ${customerMindsetQuality.total_question_count || customerMindsetQuestions.length} 个问题的梳理`
          : `等待结合商品事实、关键词、竞品和图片分析梳理用户需求${statusSuffix}`,
      done: hasCustomerMindset,
      active: nodeActiveAt('customer-mindset'),
      error: nodeErrorAt('customer-mindset'),
    },
    {
      title: 'Listing文案',
      description: hasListingContent
        ? '标题、五点、描述已生成'
        : hasCustomerMindset
          ? `等待按用户心智策略生成文案${statusSuffix}`
          : `等待用户心智梳理完成${statusSuffix}`,
      done: hasListingContent || product.current_step >= 6 || isReadyToExport,
      active: nodeActiveAt('listing'),
      error: nodeErrorAt('listing'),
    },
    {
      title: '待导出',
      description: isReadyToExport
        ? '已加入待导出'
        : '等待Listing生成完成',
      done: isReadyToExport,
      active: nodeActiveAt('export'),
    },
  ].map(toWorkflowItem);
  const workflowPipelineSteps = hasWorkflow ? buildWorkflowPipelineSteps(workflow) : [];
  const pipelineSteps = hasWorkflow ? workflowPipelineSteps : legacyPipelineSteps;

  const currentStepIndex = (() => {
    if (hasWorkflow) return workflowStageIndex(workflow);
    const activeIndex = pipelineSteps.findIndex((item) => item.status === 'process' || item.status === 'error');
    if (activeIndex >= 0) return activeIndex;
    const firstWaitingIndex = pipelineSteps.findIndex((item) => item.status === 'wait');
    if (firstWaitingIndex >= 0) return firstWaitingIndex;
    return pipelineSteps.length - 1;
  })();

  const isInterruptedProduct = /运行状态已中断|未在当前服务中运行/.test(product.current_task_status || '');
  const isPipelineRunning = !isInterruptedProduct
    && !PRODUCT_NON_RUNNING_STATUSES.includes(product.status);
  const canRegenerateListing = Boolean(hasReferenceCompetitor && hasImageAnalysis && hasCustomerMindset && !isPipelineRunning && !isPaused && !isHardStopped);
  const canGenerateMissingListing = Boolean(
    canRegenerateListing
    && !hasListingContent
    && !isReadyToExport
  );
  const canSuspendProduct = product.status !== 'paused'
    && !isInterruptedProduct
    && !['completed', 'unavailable', 'source_unavailable'].includes(product.status)
    && !(product.status === 'pending_review' && product.current_step >= 6);
  const hasRestartableDownstreamState = Boolean(
    product.current_step > 0
    || hasReferenceCompetitor
    || hasImageAnalysis
    || hasCustomerMindset
    || hasListingContent
    || hasAplusOutput
    || visibleGeneratedFiles.length
  );
  const canRestartProduct = !isPipelineRunning
    && !isInterruptedProduct
    && !['unavailable', 'source_unavailable'].includes(product.status)
    && hasRestartableDownstreamState;

  // 安全解析JSON
  const renderListingImageConfirmation = () => (
    <Card
      title="商品图片确认"
      size="small"
      style={{ marginBottom: 12 }}
      extra={imageResourceItems.length ? (
        <Space>
          {listingImageDirty && <Tag color="warning">未保存</Tag>}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            disabled={!listingImageDirty || imageOrderSaving}
            onClick={resetListingImageDraft}
          >
            取消
          </Button>
          <Button
            size="small"
            type="primary"
            icon={<CheckOutlined />}
            loading={imageOrderSaving}
            disabled={!listingImageDirty || !selectedListingImages.length}
            onClick={saveListingImagePaths}
          >
            保存
          </Button>
        </Space>
      ) : null}
    >
      <Spin spinning={imageOrderSaving}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <div>
            <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 8 }}>
              <Text strong>已使用图片</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>最多 9 张，第一张为主图，其余为已确认展示图</Text>
            </Space>
            <div
              onDragOver={(event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = 'move';
              }}
              onDrop={dropListingImageToSelected}
              style={{
                minHeight: selectedListingImages.length ? 0 : 132,
                border: selectedListingImages.length ? 'none' : '1px dashed #91caff',
                borderRadius: 8,
                padding: selectedListingImages.length ? 0 : 16,
                background: selectedListingImages.length ? 'transparent' : '#f6fbff',
              }}
            >
              {selectedListingImages.length ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12 }}>
                  {selectedListingImages.map((item, index) => {
                    const isMain = index === 0;
                    const isDropTarget = imageDragPayload?.source && imageDragPayload?.path !== item.path;
                    return (
                      <div
                        key={`aplus-confirm-selected-${item.path}-${index}`}
                        draggable={!imageOrderSaving}
                        onDragStart={(event) => startListingImageDrag(event, { source: 'selected', index, path: item.path })}
                        onDragOver={(event) => {
                          event.preventDefault();
                          event.dataTransfer.dropEffect = 'move';
                        }}
                        onDrop={(event) => replaceListingImageSlot(event, index)}
                        onDragEnd={() => setImageDragPayload(null)}
                        onDoubleClickCapture={(event) => handleListingImageDoubleClick(event, item.path, removeListingImageFromSelected)}
                        onDoubleClick={(event) => handleListingImageDoubleClick(event, item.path, removeListingImageFromSelected)}
                        style={{
                          cursor: imageOrderSaving ? 'default' : 'grab',
                          border: isMain ? '2px solid #1677ff' : '1px solid #d9d9d9',
                          borderRadius: 8,
                          padding: 8,
                          background: imageDragPayload?.source === 'selected' && imageDragPayload?.index === index ? '#f0f7ff' : '#fff',
                          boxShadow: isDropTarget ? '0 0 0 2px rgba(22, 119, 255, 0.12)' : 'none',
                        }}
                      >
                        <Space direction="vertical" size={6} style={{ width: '100%' }}>
                          <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                            <Tag color={isMain ? 'blue' : 'default'}>{isMain ? '主图' : `副图 ${index}`}</Tag>
                            <DragOutlined style={{ color: '#999' }} />
                          </Space>
                          <Image
                            src={imgUrl(item.path)}
                            width="100%"
                            alt={isMain ? '主图' : `副图${index}`}
                            preview={false}
                            onDoubleClick={(event) => handleListingImageDoubleClick(event, item.path, removeListingImageFromSelected)}
                            style={{ aspectRatio: '1 / 1', objectFit: 'cover', background: '#f5f5f5' }}
                          />
                          {item.meta && <Typography.Paragraph type="secondary" ellipsis={{ rows: 1 }} style={{ fontSize: 12, marginBottom: 0 }}>{item.meta}</Typography.Paragraph>}
                        </Space>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <Space direction="vertical" size={4} style={{ width: '100%', alignItems: 'center', justifyContent: 'center', minHeight: 96 }}>
                  <Text type="secondary">把备用/未选素材拖到这里，或双击素材加入已使用图片</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>至少保留一张主图后才能保存</Text>
                </Space>
              )}
            </div>
          </div>
          <div>
            <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 8 }}>
              <Text strong>其他图片 / 备用/未选素材</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>包含商品页候选、素材包解压图片和品牌图</Text>
            </Space>
            <div
              onDragOver={(event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = 'move';
              }}
              onDrop={dropListingImageToUnusedPool}
              style={{
                minHeight: 132,
                border: unusedImageResourceItems.length ? 'none' : '1px dashed #d9d9d9',
                borderRadius: 8,
                padding: unusedImageResourceItems.length ? 0 : 16,
                background: unusedImageResourceItems.length ? 'transparent' : '#fafafa',
              }}
            >
              {unusedImageResourceItems.length ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(132px, 1fr))', gap: 10, maxHeight: 460, overflow: 'auto', paddingRight: 4 }}>
                  {unusedImageResourceItems.map((item, index) => (
                    <div
                      key={`aplus-confirm-pool-${item.path}-${index}`}
                      draggable={!imageOrderSaving}
                      onDragStart={(event) => startListingImageDrag(event, { source: 'pool', path: item.path })}
                      onDragEnd={() => setImageDragPayload(null)}
                      onDoubleClickCapture={(event) => handleListingImageDoubleClick(event, item.path, addListingImageFromPool)}
                      onDoubleClick={(event) => handleListingImageDoubleClick(event, item.path, addListingImageFromPool)}
                      style={{ cursor: imageOrderSaving ? 'default' : 'grab', border: '1px solid #eee', borderRadius: 8, padding: 8, background: '#fff' }}
                    >
                      <Space direction="vertical" size={6} style={{ width: '100%' }}>
                        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                          <Text strong style={{ fontSize: 12 }}>{item.image_id || `#${index + 1}`}</Text>
                          <DragOutlined style={{ color: '#bbb' }} />
                        </Space>
                        <Image
                          src={imgUrl(item.path)}
                          width="100%"
                          alt={item.filename || `图片${index + 1}`}
                          preview={false}
                          onDoubleClick={(event) => handleListingImageDoubleClick(event, item.path, addListingImageFromPool)}
                          style={{ aspectRatio: '1 / 1', objectFit: 'cover', background: '#f5f5f5' }}
                        />
                        <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ fontSize: 12, marginBottom: 0 }}>
                          {item.visible_selling_point || item.image_type || item.filename}
                        </Typography.Paragraph>
                      </Space>
                    </div>
                  ))}
                </div>
              ) : (
                <Space direction="vertical" size={4} style={{ width: '100%', alignItems: 'center', justifyContent: 'center', minHeight: 96 }}>
                    <Text type="secondary">暂无其他图片 / 备用未选素材</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>把上方图片拖到这里，或双击已使用图片即可移出使用区</Text>
                </Space>
              )}
            </div>
          </div>
        </Space>
      </Spin>
    </Card>
  );

  const tabItems = [
    {
      key: 'basic',
      label: '📋 基本信息',
      children: (
        <div>
          {sectionStatus(['source'])}
          <Card title="商品摘要" size="small" style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <div>
                <Text type="secondary">商品标题</Text>
                <Typography.Paragraph
                  style={{ marginBottom: 0, marginTop: 4, fontWeight: 500 }}
                  ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
                >
                  {data?.title || '-'}
                </Typography.Paragraph>
              </div>
              <div>
                <Text type="secondary">Amazon类目</Text>
                <Space style={{ marginTop: 4 }} wrap>
                  <Typography.Paragraph style={{ marginBottom: 0 }} ellipsis={{ rows: 1, expandable: true, symbol: '展开' }}>
                    {categoryPath || '-'}
                  </Typography.Paragraph>
                  <Button size="small" onClick={openCategoryEditor}>编辑类目</Button>
                </Space>
              </div>
              <Descriptions
                bordered
                className="basic-info-descriptions"
                column={{ xs: 1, sm: 1, md: 3 }}
                size="small"
              >
                <Descriptions.Item label="来源商品ID">{product.source_item_id || product.gigab2b_product_id || '-'}</Descriptions.Item>
                <Descriptions.Item label="商品Code">{data?.item_code || '-'}</Descriptions.Item>
                <Descriptions.Item label="品牌">{product.brand || '-'}</Descriptions.Item>
                <Descriptions.Item label="UPC">{product.upc || '-'}</Descriptions.Item>
                <Descriptions.Item label="竞品 ASIN">{product.competitor_asin || '-'}</Descriptions.Item>
                <Descriptions.Item label="真实 ASIN">{product.amazon_asin || '-'}</Descriptions.Item>
                <Descriptions.Item label="颜色">{data?.color || '-'}</Descriptions.Item>
                <Descriptions.Item label="材质">{data?.material || '-'}</Descriptions.Item>
                <Descriptions.Item label="填充物">{data?.filler || '-'}</Descriptions.Item>
                <Descriptions.Item label="产品类型">{data?.product_type || '-'}</Descriptions.Item>
                <Descriptions.Item label="组装尺寸">{data ? `${numberText(data.dimension_length)} × ${numberText(data.dimension_width)} × ${numberText(data.dimension_height)} 英寸` : '-'}</Descriptions.Item>
                <Descriptions.Item label="产品重量">{numberText(data?.weight, ' 磅')}</Descriptions.Item>
                <Descriptions.Item label="供应商">{data?.seller || '-'}</Descriptions.Item>
                <Descriptions.Item label="产地">{data?.origin || '-'}</Descriptions.Item>
                <Descriptions.Item label="Listing图片">{listingImageCount ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="采集时间">{data?.collected_at ? new Date(data.collected_at).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
                <Descriptions.Item label="素材目录">
                  {data?.material_dir ? (
                    <Space>
                      <Button size="small" icon={<FolderOpenOutlined />} loading={isFileOpening(data.material_dir)} disabled={isFileOpening(data.material_dir)} onClick={() => openPath(data.material_dir)}>打开</Button>
                      <Button size="small" icon={<CopyOutlined />} onClick={() => copyText(data.material_dir)}>复制</Button>
                    </Space>
                  ) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="视频素材">
                  {videoFolder?.exists ? (
                    <Space wrap>
                      <Tag color="processing">{videoFolder.file_count} 个视频</Tag>
                      <Button size="small" icon={<FolderOpenOutlined />} loading={isFileOpening(videoFolder.path)} disabled={isFileOpening(videoFolder.path)} onClick={() => openPath(videoFolder.path)}>打开</Button>
                      <Button size="small" icon={<CopyOutlined />} onClick={() => copyText(videoFolder.path)}>复制</Button>
                    </Space>
                  ) : <Text type="secondary">暂无</Text>}
                </Descriptions.Item>
                <Descriptions.Item label="A+图片" span="filled">
                  {aplusFolder?.exists ? (
                    <Space wrap>
                      <Tag color="success">{aplusFolder.file_count} 张</Tag>
                      <Button size="small" icon={<FolderOpenOutlined />} loading={isFileOpening(aplusFolder.path)} disabled={isFileOpening(aplusFolder.path)} onClick={() => openPath(aplusFolder.path)}>打开</Button>
                      <Button size="small" icon={<CopyOutlined />} onClick={() => copyText(aplusFolder.path)}>复制</Button>
                    </Space>
                  ) : <Text type="secondary">未生成</Text>}
                </Descriptions.Item>
              </Descriptions>
              {(product.asin_sync_error || product.amazon_product_status_error) && (
                <Alert
                  type="warning"
                  showIcon
                  message="同步提醒"
                  description={[product.asin_sync_error, product.amazon_product_status_error].filter(Boolean).join('；')}
                />
              )}
            </Space>
          </Card>

          <Card title="销售与定价" size="small" style={{ marginBottom: 16 }}>
            <Descriptions bordered className="basic-info-descriptions" size="small" column={{ xs: 1, md: 2 }}>
              <Descriptions.Item label="ASIN同步状态">
                {product.amazon_asin ? <Tag color="success">已同步</Tag> : product.asin_sync_status === 'not_found' ? <Tag color="warning">未查到</Tag> : product.asin_sync_status === 'failed' ? <Tag color="error">失败</Tag> : product.asin_sync_status === 'pending' || product.asin_sync_status === 'running' ? <Tag color="processing">同步中</Tag> : <Tag>未同步</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="亚马逊状态">
                {product.amazon_product_status ? <Tag color={String(product.amazon_product_status).includes('售') ? 'success' : 'warning'}>{product.amazon_product_status}</Tag> : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="库存">{data?.stock ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="建议售价">{money(data?.suggested_price)}</Descriptions.Item>
              <Descriptions.Item label="利润">{money(data?.profit)}</Descriptions.Item>
              <Descriptions.Item label="净利率">{data?.profit_rate != null ? `${data.profit_rate.toFixed(1)}%` : '-'}</Descriptions.Item>
              <Descriptions.Item label="货值">{money(data?.value_total)}</Descriptions.Item>
              <Descriptions.Item label="含运费成本">{money(data?.estimated_total)}</Descriptions.Item>
              <Descriptions.Item label="总成本">{money(data?.cost_total)}</Descriptions.Item>
              <Descriptions.Item label="一件代发物流">{money(data?.shipping_cost)}</Descriptions.Item>
              <Descriptions.Item label="云送仓物流">
                {data?.shipping_cost_min != null || data?.shipping_cost_max != null ? `${money(data?.shipping_cost_min)} - ${money(data?.shipping_cost_max)}` : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="定价依据">
                {pricingDetail?.selected_rule === 'target_margin' ? '目标净利率' : pricingDetail?.selected_rule ? '最低利润' : '-'}
              </Descriptions.Item>
              {pricingDetail && (
                <>
                  <Descriptions.Item label="可留存收入">{money(pricingDetail.net_revenue)}</Descriptions.Item>
                  <Descriptions.Item label="可留存收入比例">{pricingDetail.retained_revenue_rate != null ? `${pricingDetail.retained_revenue_rate}%` : '-'}</Descriptions.Item>
                  <Descriptions.Item label="Amazon 佣金">{money(pricingDetail.commission_fee)}（{pricingDetail.commission_rate != null ? `${pricingDetail.commission_rate}%` : '-'}）</Descriptions.Item>
                  <Descriptions.Item label="实际退货率">{pricingDetail.return_rate != null ? `${pricingDetail.return_rate}%` : '-'}</Descriptions.Item>
                  <Descriptions.Item label="退货净影响">{money(pricingDetail.return_reserve)}</Descriptions.Item>
                  <Descriptions.Item label="其中退款收入损失">{money(pricingDetail.return_revenue_loss)}</Descriptions.Item>
                  <Descriptions.Item label="其中退货管理费">{money(pricingDetail.return_management_fee)}</Descriptions.Item>
                  <Descriptions.Item label="货值+GIGA物流">{money(pricingDetail.source_cost)}</Descriptions.Item>
                  <Descriptions.Item label="其中 GIGA物流">{money(pricingDetail.source_shipping_cost)}</Descriptions.Item>
                  <Descriptions.Item label="退货保险">{money(pricingDetail.insurance_cost)}（货值的 {pricingDetail.insurance_rate != null ? `${pricingDetail.insurance_rate}%` : '-'}）</Descriptions.Item>
                  <Descriptions.Item label="平均保险赔付">{money(pricingDetail.average_insurance_payout)}（货值的 {pricingDetail.insurance_payout_rate != null ? `${pricingDetail.insurance_payout_rate}%` : '-'}）</Descriptions.Item>
                  <Descriptions.Item label="广告预留">{money(pricingDetail.advertising_cost)}</Descriptions.Item>
                  <Descriptions.Item label="目标净利率">{pricingDetail.target_margin_rate != null ? `${pricingDetail.target_margin_rate}%` : '-'}</Descriptions.Item>
                  <Descriptions.Item label="最低利润">{money(pricingDetail.min_profit)}</Descriptions.Item>
                  <Descriptions.Item label="净利率线价格">{money(pricingDetail.price_for_margin)}</Descriptions.Item>
                  <Descriptions.Item label="最低利润线价格">{money(pricingDetail.price_for_min_profit)}</Descriptions.Item>
                </>
              )}
            </Descriptions>
          </Card>

          <Card title="包装与履约" size="small" style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
                <Descriptions.Item label="产品尺寸">
                  {dimensionLine(data?.dimension_length, data?.dimension_width, data?.dimension_height, '英寸')}
                </Descriptions.Item>
                <Descriptions.Item label="产品重量">{numberText(data?.weight, ' 磅')}</Descriptions.Item>
                <Descriptions.Item label="包裹尺寸合计">
                  {exportPackage?.length != null ? dimensionLine(exportPackage.length, exportPackage.width, exportPackage.height, '英寸') : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="包裹重量合计">
                  {exportPackage?.weight != null ? `${exportPackage.weight} 磅` : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="处理时效">
                  {rawFulfillment?.drop_ship?.handling_time ? `${rawFulfillment.drop_ship.handling_time.min_day}-${rawFulfillment.drop_ship.handling_time.max_day} 天` : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="发货时效">
                  {rawFulfillment?.drop_ship?.estimated_ship_day ? `${rawFulfillment.drop_ship.estimated_ship_day.min_day}-${rawFulfillment.drop_ship.estimated_ship_day.max_day} 天` : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="组合商品">{rawFulfillment?.is_combo ? '是' : '否'}</Descriptions.Item>
                <Descriptions.Item label="Retail Ready">{rawSnapshot?.product?.retail_ready_flag ? '是' : '否'}</Descriptions.Item>
              </Descriptions>
              {Array.isArray(exportPackage?.warnings) && exportPackage.warnings.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="包装提醒"
                  description={exportPackage.warnings.join('；')}
                />
              )}
              <Table
                size="small"
                columns={packageColumns}
                dataSource={Array.isArray(rawPackageSize.combo) && rawPackageSize.combo.length ? rawPackageSize.combo : (Array.isArray(packages) ? packages : [])}
                rowKey={(record) => record.sku || record.code || record.package_id || JSON.stringify(record)}
                pagination={false}
                locale={{ emptyText: '暂无包装明细' }}
              />
            </Space>
          </Card>

          <Card title="变体信息" size="small" style={{ marginBottom: 16 }}>
            {Array.isArray(variants) && variants.length ? (
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                {commonVariantAttributeEntries.length > 0 && (
                  <div>
                    <Text type="secondary">共同属性</Text>
                    <div style={{ marginTop: 6 }}>
                      {renderVariantTags(Object.fromEntries(commonVariantAttributeEntries))}
                    </div>
                  </div>
                )}
                <Table
                  size="small"
                  dataSource={variants}
                  columns={[
                    {
                      title: '图片',
                      dataIndex: 'main_image_url',
                      width: 86,
                      render: (_value, record) => {
                        const url = variantImageUrl(record);
                        return url ? (
                          <Image
                            src={url}
                            width={56}
                            height={56}
                            style={{ objectFit: 'cover', borderRadius: 4, border: '1px solid #f0f0f0' }}
                            preview={{ src: url }}
                          />
                        ) : <Text type="secondary">-</Text>;
                      },
                    },
                    {
                      title: 'SKU',
                      dataIndex: 'sku',
                      width: 150,
                      render: (value) => value ? <Text copyable>{value}</Text> : '-',
                    },
                    {
                      title: '变体属性',
                      dataIndex: 'variation_attributes',
                      render: (value, record) => renderVariantTags(value || {
                        ...(record?.color ? { Color: record.color } : {}),
                      }, 'blue'),
                    },
                    {
                      title: '价格',
                      dataIndex: 'price',
                      width: 110,
                      render: (value) => money(value),
                    },
                    {
                      title: '物流',
                      dataIndex: 'shipping_fee',
                      width: 110,
                      render: (value) => money(value),
                    },
                    {
                      title: '库存',
                      dataIndex: 'stock',
                      width: 90,
                      render: (value) => value ?? '-',
                    },
                  ]}
                  rowKey={(record) => record?.sku || record?.asin || record?.code || JSON.stringify(record)}
                  pagination={false}
                />
              </Space>
            ) : <Text type="secondary">暂无变体</Text>}
          </Card>

          {Array.isArray(features) && features.length > 0 && (
            <Card title="采集特征" size="small" style={{ marginBottom: 16 }}>
              <details>
                <summary style={{ cursor: 'pointer' }}>展开查看原始采集特征</summary>
                <List
                  size="small"
                  style={{ marginTop: 8 }}
                  dataSource={features}
                  renderItem={(item) => <List.Item>{typeof item === 'string' ? item : JSON.stringify(item)}</List.Item>}
                />
              </details>
            </Card>
          )}

        </div>
      ),
    },
    {
      key: 'competitor',
      label: '🎴 竞品',
      children: (
        <div>
          <Card
            title="当前参考竞品"
            size="small"
            style={{ marginBottom: 16 }}
          >
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Descriptions bordered column={{ xs: 1, sm: 1, md: 2 }} size="small">
                <Descriptions.Item label="选中 ASIN">
                  {product.competitor_asin ? (
                    <Space size={8}>
                      <Typography.Link href={`https://www.amazon.com/dp/${product.competitor_asin}`} target="_blank">
                        {product.competitor_asin}
                      </Typography.Link>
                      <Button size="small" icon={<CopyOutlined />} onClick={() => copyText(product.competitor_asin)}>复制</Button>
                    </Space>
                  ) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="来源">自动竞品搜索流程</Descriptions.Item>
              </Descriptions>
            </Space>
          </Card>

          <Card title="竞品搜索状态" size="small">
            {isCompetitorSearching ? (
              <Alert
                type="info"
                showIcon
                message="正在自动搜索 Amazon 参考竞品"
                description={product.error_message || '搜索任务执行状态请以任务中心为准。'}
              />
            ) : isCompetitorSearchFailed ? (
              <Alert
                type="error"
                showIcon
                message="自动竞品搜索失败"
                description={productErrorMessage || '请回到商品列表或任务中心按当前自动流程重试。'}
              />
            ) : hasReferenceCompetitor ? (
              <Alert
                type="success"
                showIcon
                message="参考竞品已确认"
                description="竞品搜索和后续生成将继续由自动流程处理。"
              />
            ) : (
              <Empty description={hasConfirmedSearchImage ? '等待自动竞品搜索任务' : '等待先确认商品图片'} />
            )}
          </Card>
        </div>
      ),
    },
    {
      key: 'mindset',
      label: '用户心智',
      children: hasCustomerMindset ? (
        <div>
          {sectionStatus(['mindset'])}
          <Alert
            type={customerMindsetQuality.requires_review ? 'warning' : 'success'}
            showIcon
            style={{ marginBottom: 12 }}
            message={customerMindsetQuality.requires_review ? '已生成，存在需要人工关注的未知项' : '用户心智梳理已完成'}
            description={(
              <Space wrap>
                <Tag>{customerMindsetQuality.fixed_question_count || 13} 个固定问题</Tag>
                <Tag color="blue">{customerMindsetQuality.dynamic_question_count || Math.max(customerMindsetQuestions.length - 13, 0)} 个动态问题</Tag>
                <Tag color={customerMindsetQuality.requires_review ? 'warning' : 'success'}>
                  共 {customerMindsetQuality.total_question_count || customerMindsetQuestions.length} 个问题
                </Tag>
                <Text type="secondary">
                  {data?.customer_mindset_generated_at
                    ? `生成于 ${new Date(data.customer_mindset_generated_at).toLocaleString('zh-CN')}`
                    : customerMindset.generated_at
                      ? `生成于 ${new Date(customerMindset.generated_at).toLocaleString('zh-CN')}`
                      : null}
                </Text>
              </Space>
            )}
          />

          <Card title="核心策略" size="small" style={{ marginBottom: 12 }}>
            <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
              <Descriptions.Item label="主要购买者">{renderMindsetStrategyValue('primary_buyer', customerMindsetStrategy.primary_buyer)}</Descriptions.Item>
              <Descriptions.Item label="实际使用者">{renderMindsetStrategyValue('actual_user', customerMindsetStrategy.actual_user)}</Descriptions.Item>
              <Descriptions.Item label="购买触发点">{renderMindsetStrategyValue('purchase_trigger', customerMindsetStrategy.purchase_trigger)}</Descriptions.Item>
              <Descriptions.Item label="首要任务">{renderMindsetStrategyValue('primary_job', customerMindsetStrategy.primary_job)}</Descriptions.Item>
              <Descriptions.Item label="核心价值" span="filled">
                {renderMindsetStrategyValue('core_value_proposition', customerMindsetStrategy.core_value_proposition)}
              </Descriptions.Item>
              <Descriptions.Item label="重点场景" span="filled">
                <Space wrap>
                  {(customerMindsetStrategy.top_scenarios || []).map((item: any, index: number) => (
                    <Space key={`${item?.rank || index}-${item?.scenario || item}`} size={4}>
                      <Tag color="blue">{item?.rank ? `${item.rank}. ` : ''}{item?.scenario || String(item)}</Tag>
                      {item?.status && <Tag>{MINDSET_STATUS_META[item.status]?.label || item.status}</Tag>}
                    </Space>
                  ))}
                  {!(customerMindsetStrategy.top_scenarios || []).length && '-'}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="决策标准" span="filled">
                <Space wrap>
                  {(customerMindsetStrategy.decision_criteria || []).map((item: any, index: number) => (
                    <Space key={`${item?.rank || index}-${item?.criterion || item}`} size={4}>
                      <Tag color="purple">{item?.rank ? `${item.rank}. ` : ''}{item?.criterion || String(item)}</Tag>
                      {item?.status && <Tag>{MINDSET_STATUS_META[item.status]?.label || item.status}</Tag>}
                    </Space>
                  ))}
                  {!(customerMindsetStrategy.decision_criteria || []).length && '-'}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="适用边界" span="filled">
                <Space wrap>
                  {(customerMindsetStrategy.fit_boundaries || []).map((item: string) => <Tag key={item}>{item}</Tag>)}
                  {!(customerMindsetStrategy.fit_boundaries || []).length && '-'}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="禁止宣称" span="filled">
                <Space wrap>
                  {(customerMindsetStrategy.content_direction?.claims_to_avoid || []).map((item: string) => (
                    <Tag key={item} color="red">{item}</Tag>
                  ))}
                  {!(customerMindsetStrategy.content_direction?.claims_to_avoid || []).length && '-'}
                </Space>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="Listing 内容分工" size="small" style={{ marginBottom: 12 }}>
            <Typography.Paragraph>
              <Text strong>标题任务：</Text>{customerMindsetStrategy.content_direction?.title_job || '-'}
            </Typography.Paragraph>
            <Space wrap size={[4, 4]} style={{ marginBottom: 12 }}>
              <Text type="secondary">标题证据：</Text>
              {(customerMindsetStrategy.content_direction?.title_required_proof_refs || []).map((ref: string) => (
                <Tag key={ref}>{ref}</Tag>
              ))}
              {!(customerMindsetStrategy.content_direction?.title_required_proof_refs || []).length && <Tag color="warning">待补充</Tag>}
              <Tag color={customerMindsetStrategy.content_direction?.title_claim_proof_usable ? 'success' : 'warning'}>
                {customerMindsetStrategy.content_direction?.title_claim_proof_usable ? '证据可用于标题' : '仅限商品身份信息'}
              </Tag>
            </Space>
            <Table
              size="small"
              rowKey={(record: any) => record.position}
              pagination={false}
              dataSource={customerMindsetStrategy.content_direction?.bullet_jobs || []}
              columns={[
                { title: '五点', dataIndex: 'position', width: 72, render: (value: number) => `第 ${value} 点` },
                { title: '用户问题', dataIndex: 'buyer_question', width: 280, render: (value: string) => value || '-' },
                { title: '表达任务', dataIndex: 'message_job', render: (value: string) => value || '-' },
                {
                  title: '所需证据',
                  dataIndex: 'required_proof_refs',
                  width: 260,
                  render: (refs: string[], record: any) => (
                    <Space wrap size={[4, 4]}>
                      {(refs || []).map((ref) => <Tag key={ref}>{ref}</Tag>)}
                      {!(refs || []).length && <Text type="secondary">待补充</Text>}
                      <Tag color={record?.claim_proof_usable ? 'success' : 'warning'}>
                        {record?.claim_proof_usable ? '可用于文案' : '仅作问题参考'}
                      </Tag>
                    </Space>
                  ),
                },
              ]}
              scroll={{ x: 920 }}
            />
            <Title level={5} style={{ marginTop: 18, marginBottom: 10 }}>后续图片与 A+ 任务</Title>
            <Table
              size="small"
              rowKey={(record: any, index: number) => `${record.surface}-${index}`}
              pagination={false}
              dataSource={[
                ...(customerMindsetStrategy.content_direction?.future_visual_jobs || []).map((item: any) => ({
                  ...item,
                  surface: 'Listing 图片',
                  content_job: item.visual_job,
                })),
                ...(customerMindsetStrategy.content_direction?.aplus_jobs || []).map((item: any) => ({
                  ...item,
                  surface: 'A+',
                  content_job: item.story_job,
                })),
              ]}
              columns={[
                { title: '内容位置', dataIndex: 'surface', width: 120, render: (value: string) => <Tag color="blue">{value}</Tag> },
                { title: '用户问题', dataIndex: 'buyer_question', width: 300, render: (value: string) => value || '-' },
                { title: '沟通任务', dataIndex: 'content_job', render: (value: string) => value || '-' },
                {
                  title: '所需证据',
                  dataIndex: 'required_proof_refs',
                  width: 260,
                  render: (refs: string[], record: any) => (
                    <Space wrap size={[4, 4]}>
                      {(refs || []).map((ref) => <Tag key={ref}>{ref}</Tag>)}
                      {!(refs || []).length && <Text type="secondary">待补充</Text>}
                      <Tag color={record?.claim_proof_usable ? 'success' : record?.visual_anchor_usable ? 'blue' : 'warning'}>
                        {record?.claim_proof_usable
                          ? '可用于文案'
                          : record?.visual_anchor_usable
                            ? '仅作视觉锚点'
                            : '仅作问题参考'}
                      </Tag>
                    </Space>
                  ),
                },
              ]}
              scroll={{ x: 920 }}
              locale={{ emptyText: '暂无后续视觉任务' }}
            />
          </Card>

          <Card title={`问题与回答（${customerMindsetQuestions.length}）`} size="small">
            <Table
              size="small"
              rowKey="id"
              dataSource={customerMindsetQuestions}
              pagination={{ pageSize: 10, showSizeChanger: false }}
              scroll={{ x: 1180 }}
              columns={[
                {
                  title: '类型',
                  dataIndex: 'question_type',
                  width: 100,
                  render: (value: string) => value === 'dynamic'
                    ? <Tag color="blue">动态补充</Tag>
                    : <Tag>固定核心</Tag>,
                },
                {
                  title: '问题',
                  dataIndex: 'question',
                  width: 300,
                  render: (value: string, record: any) => (
                    <Space direction="vertical" size={4}>
                      <Text strong>{value}</Text>
                      {record.why_asked && <Text type="secondary">补充原因：{record.why_asked}</Text>}
                      {record.incremental_decision_gap && (
                        <Text type="secondary">
                          相比 {record.closest_fixed_question_id || '固定问题'} 新增：{record.incremental_decision_gap}
                        </Text>
                      )}
                    </Space>
                  ),
                },
                {
                  title: '结论',
                  dataIndex: 'answer',
                  render: (answer: any) => (
                    <Space direction="vertical" size={6} style={{ width: '100%' }}>
                      <Text>{answer?.conclusion || '-'}</Text>
                      {answer?.supporting_rationale && <Text type="secondary">依据：{answer.supporting_rationale}</Text>}
                      {(answer?.assumptions || []).length > 0 && (
                        <div><Text type="secondary">假设：</Text>{answer.assumptions.join('；')}</div>
                      )}
                      {(answer?.unknowns || []).length > 0 && (
                        <div><Text type="warning">未知：</Text>{answer.unknowns.join('；')}</div>
                      )}
                      <Space wrap size={[4, 4]}>
                        {(answer?.content_uses || []).map((use: string) => (
                          <Tag key={use} color="purple">{MINDSET_CONTENT_USE_LABELS[use] || use}</Tag>
                        ))}
                      </Space>
                    </Space>
                  ),
                },
                {
                  title: '证据',
                  dataIndex: ['answer', 'evidence_refs'],
                  width: 250,
                  render: (refs: string[]) => (
                    <Space wrap size={[4, 4]}>
                      {(refs || []).map((ref) => {
                        const evidence = customerMindsetEvidenceById.get(ref) as any;
                        return (
                          <Tooltip key={ref} title={evidence?.excerpt || evidence?.source || ref}>
                            <Tag>{ref}</Tag>
                          </Tooltip>
                        );
                      })}
                      {!(refs || []).length && <Tag color="warning">无直接证据</Tag>}
                    </Space>
                  ),
                },
                {
                  title: '判断',
                  dataIndex: 'answer',
                  width: 130,
                  render: (answer: any) => {
                    const statusMeta = MINDSET_STATUS_META[answer?.status] || MINDSET_STATUS_META.unknown;
                    const confidenceMeta = MINDSET_CONFIDENCE_META[answer?.confidence] || MINDSET_CONFIDENCE_META.low;
                    return (
                      <Space direction="vertical" size={4}>
                        <Tag color={statusMeta.color}>{statusMeta.label}</Tag>
                        <Tag color={confidenceMeta.color}>{confidenceMeta.label}</Tag>
                        <Tag color={answer?.copy_claim_usable ? 'success' : 'default'}>
                          {answer?.copy_claim_usable ? '可直接用于文案' : '仅作策略参考'}
                        </Tag>
                      </Space>
                    );
                  },
                },
              ]}
            />
          </Card>
        </div>
      ) : (
        <>
          {sectionStatus(['mindset'])}
          <Empty
          description={isCustomerMindsetFailed ? '用户心智梳理失败，可重新提交任务' : '等待图片分析完成后自动梳理'}
        >
          <Space direction="vertical" align="center">
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={pipelineRetryLoading}
              disabled={!hasImageAnalysis || isPipelineRunning}
              onClick={generateCustomerMindset}
            >
              生成用户心智
            </Button>
            {!hasImageAnalysis && <Text type="secondary">请先完成图片分析，才能生成用户心智。</Text>}
            {isPipelineRunning && <Text type="secondary">当前流程正在运行，请等待当前任务结束。</Text>}
          </Space>
          </Empty>
        </>
      ),
    },
    {
      key: 'listing',
      label: '📝 Listing文案',
      children: (
        <div>
          {sectionStatus(['listing'])}
          <Card
            title="标题"
            size="small"
            style={{ marginBottom: 12 }}
            extra={(
              <Space size="small">
                <Popconfirm
                  title="确定重新生成 Listing 文案？"
                  description="会基于当前商品事实、关键词、竞品、图片分析和用户心智策略重新生成标题、五点、描述和 Search Terms；完成后会自动回到待导出。"
                  okText="重新生成"
                  cancelText="取消"
                  onConfirm={regenerateListing}
                  disabled={!canRegenerateListing || listingRegenerateLoading}
                >
                  <Button
                    size="small"
                    icon={<RedoOutlined />}
                    loading={listingRegenerateLoading}
                    disabled={!canRegenerateListing}
                  >
                    重新生成
                  </Button>
                </Popconfirm>
                <Button size="small" onClick={openListingEditor}>编辑 Listing</Button>
              </Space>
            )}
          >
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text>{data?.listing_title || '（未生成）'}</Text>
              {data?.listing_title && <Text type="secondary">{data.listing_title.length}/75 字符</Text>}
              {data?.listing_title_zh && <Text type="secondary">中文：{data.listing_title_zh}</Text>}
            </Space>
          </Card>
          <Card
            title={(
              <Space size="small">
                <span>标题补充（Product Highlight）</span>
                <Tag color={listingProductHighlights.length === 1 ? 'blue' : 'default'}>
                  {listingProductHighlights.length}/1 条
                </Tag>
              </Space>
            )}
            size="small"
            style={{ marginBottom: 12 }}
          >
            {listingProductHighlights.length ? (
              <ol style={{ paddingLeft: 20, marginBottom: 0 }}>
                {listingProductHighlights.map((highlight, index) => (
                  <li key={`${index}-${highlight}`} style={{ marginBottom: 10 }}>
                    <Space direction="vertical" size={2} style={{ width: '100%' }}>
                      <Text>{highlight}</Text>
                      <Text type="secondary">{highlight.length}/120 字符</Text>
                      {listingProductHighlightsZh[index] && (
                        <Text type="secondary">
                          中文：{listingProductHighlightsZh[index]}（{listingProductHighlightsZh[index].length}/120 字符）
                        </Text>
                      )}
                    </Space>
                  </li>
                ))}
              </ol>
            ) : <Text type="secondary">（未填写）</Text>}
          </Card>
          <Card title="五点描述" size="small" style={{ marginBottom: 12 }}>
            {data?.listing_bullets ? (() => {
              try {
                const bullets = JSON.parse(data.listing_bullets) as string[];
                const bulletsZh = parseJson(data.listing_bullets_zh, []);
                return (
                  <ol style={{ paddingLeft: 20, marginBottom: 0 }}>
                    {bullets.map((b, i) => (
                      <li key={i} style={{ marginBottom: 8 }}>
                        <div>{b}</div>
                        {Array.isArray(bulletsZh) && bulletsZh[i] && (
                          <Text type="secondary">中文：{bulletsZh[i]}</Text>
                        )}
                      </li>
                    ))}
                  </ol>
                );
              } catch { return <Text type="secondary">解析失败</Text>; }
            })() : <Text type="secondary">（未生成）</Text>}
          </Card>
          <Card title="商品描述" size="small" style={{ marginBottom: 12 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                {data?.listing_description || '（未生成）'}
              </Typography.Paragraph>
              {data?.listing_description_zh && (
                <Typography.Paragraph type="secondary" style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                  中文：{data.listing_description_zh}
                </Typography.Paragraph>
              )}
            </Space>
          </Card>
          <Card title="Search Terms" size="small" style={{ marginBottom: 12 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text>{data?.listing_search_terms || '（未生成）'}</Text>
              {data?.listing_search_terms_zh && <Text type="secondary">中文：{data.listing_search_terms_zh}</Text>}
            </Space>
          </Card>
          <Card title="关键词策略与定位" size="small" style={{ marginBottom: 12 }}>
            {data?.listing_check ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Descriptions bordered size="small" column={2}>
                  <Descriptions.Item label="主关键词">{data?.listing_primary_keyword || keywordPlan.primary_keyword || '-'}</Descriptions.Item>
                  <Descriptions.Item label="目标买家">{positioning.target_buyer || '-'}</Descriptions.Item>
                  <Descriptions.Item label="点击理由" span="filled">{positioning.main_click_reason || '-'}</Descriptions.Item>
                </Descriptions>
                <div>
                  <Text strong>标题关键词</Text>
                  <div style={{ marginTop: 6 }}>
                    {(keywordPlan.title_keywords || []).map((kw: string) => <Tag key={kw} color="blue">{kw}</Tag>)}
                    {!(keywordPlan.title_keywords || []).length && <Text type="secondary">-</Text>}
                  </div>
                </div>
                <div>
                  <Text strong>五点关键词</Text>
                  <div style={{ marginTop: 6 }}>
                    {(keywordPlan.bullet_keywords || []).map((kw: string) => <Tag key={kw}>{kw}</Tag>)}
                    {!(keywordPlan.bullet_keywords || []).length && <Text type="secondary">-</Text>}
                  </div>
                </div>
                <div>
                  <Text strong>仅 Search Terms</Text>
                  <div style={{ marginTop: 6 }}>
                    {(keywordPlan.search_terms_only || []).map((kw: string) => <Tag key={kw} color="purple">{kw}</Tag>)}
                    {!(keywordPlan.search_terms_only || []).length && <Text type="secondary">-</Text>}
                  </div>
                </div>
                {Array.isArray(positioning.conversion_risks) && positioning.conversion_risks.length > 0 && (
                  <div>
                    <Text strong>转化风险</Text>
                    <div style={{ marginTop: 6 }}>
                      {positioning.conversion_risks.map((risk: string) => <Tag key={risk} color="warning">{risk}</Tag>)}
                    </div>
                  </div>
                )}
                {Array.isArray(removedKeywords) && removedKeywords.length > 0 && (
                  <div>
                    <Text strong>排除关键词</Text>
                    <div style={{ marginTop: 6 }}>
                      {removedKeywords.map((kw: string) => <Tag key={kw} color="red">{kw}</Tag>)}
                    </div>
                  </div>
                )}
                {Array.isArray(listingCheck.issues) && listingCheck.issues.length > 0 && (
                  <div>
                    <Text strong>检查提醒</Text>
                    <div style={{ marginTop: 6 }}>
                      {listingCheck.issues.map((issue: string) => <Tag key={issue} color="warning">{issue}</Tag>)}
                    </div>
                  </div>
                )}
              </Space>
            ) : <Text type="secondary">（未生成）</Text>}
          </Card>
          <Card title="关键词 Top20" size="small">
            {data?.keywords_top ? (() => {
              try {
                const kws = JSON.parse(data.keywords_top) as Array<string | { keyword?: string; volume?: number | string; position?: number | string }>;
                return (
                  <>
                    <Typography.Paragraph
                      copyable={!!keywordCopyLine}
                      style={{
                        marginBottom: 12,
                        padding: 10,
                        border: '1px solid #eee',
                        borderRadius: 6,
                        background: '#fafafa',
                        whiteSpace: 'pre-wrap',
                      }}
                    >
                      {keywordCopyLine || '（暂无可复制关键词）'}
                    </Typography.Paragraph>
                    <Space wrap>
                      {kws.map((kw, i) => {
                        const keyword = typeof kw === 'string' ? kw : kw.keyword;
                        const meta = typeof kw === 'string' ? '' : [kw.volume ? `量 ${kw.volume}` : '', kw.position ? `位 ${kw.position}` : ''].filter(Boolean).join(' / ');
                        return <Tag key={i}>{keyword || '-'}{meta ? ` · ${meta}` : ''}</Tag>;
                      })}
                    </Space>
                  </>
                );
              } catch { return <Text type="secondary">解析失败</Text>; }
            })() : <Text type="secondary">（未获取）</Text>}
          </Card>
        </div>
      ),
    },
    {
      key: 'images',
      label: '🖼️ 图片素材',
      children: (
        <div>
          {sectionStatus(['image_analysis', 'image_selection', 'image_compliance'])}
          {imageSelectionDiagnostics?.main_image_status === 'fallback_substitute' && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="当前第一张已使用图片为替代素材"
              description={(imageSelectionDiagnostics.main_image_warnings || []).join('；') || images?.main_image_summary}
            />
          )}
          <Card title="图库诊断" size="small" style={{ marginBottom: 12 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              {imageHealth?.level && (
                <Alert
                  type={imageHealth.level === 'pass' ? 'success' : imageHealth.level === 'warning' ? 'warning' : 'error'}
                  showIcon
                  message={`图片健康等级：${imageHealth.label || imageHealth.level}`}
                  description={
                    Array.isArray(imageHealth.issues) && imageHealth.issues.length ? (
                      <Space direction="vertical" size={4}>
                        {imageHealth.issues.slice(0, 6).map((item: any, i: number) => (
                          <Text key={`${item.severity}-${i}`}>{item.message}</Text>
                        ))}
                      </Space>
                    ) : '当前图片素材可用'
                  }
                />
              )}
              {imageGalleryRoles.length ? (
                <Table
                  size="small"
                  rowKey={(record) => `${record.slot}-${record.image_id}`}
                  dataSource={imageGalleryRoles}
                  pagination={false}
                  columns={[
                    { title: '位置', dataIndex: 'slot', width: 70, render: (v) => v || '-' },
                    { title: '图片', dataIndex: 'image_id', width: 90, render: (v, r) => v || r.filename || '-' },
                    { title: '任务', dataIndex: 'role_label', width: 150, render: (v, r) => <Tag color={r.is_duplicate_backfill ? 'warning' : 'processing'}>{v || r.role}</Tag> },
                    { title: '买家疑问', dataIndex: 'buyer_question', render: (v) => v || '-' },
                    { title: '说明', dataIndex: 'reason', render: (v, r) => r.duplicate_reason || v || '-' },
                  ]}
                />
              ) : <Text type="secondary">暂无图库诊断</Text>}

              {missingGalleryRoles.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="缺失图片角色"
                  description={
                    <Space wrap>
                      {missingGalleryRoles.map((item: any) => (
                        <Tag key={item.role} color="warning">{item.role_label || item.role}</Tag>
                      ))}
                    </Space>
                  }
                />
              )}

              {imageEvidenceCoverage.length > 0 && (
                <div>
                  <Text strong>图片证据覆盖</Text>
                  <Table
                    size="small"
                    style={{ marginTop: 6 }}
                    rowKey="key"
                    dataSource={imageEvidenceCoverage}
                    pagination={false}
                    columns={[
                      { title: '买家判断', dataIndex: 'label', width: 220 },
                      {
                        title: '覆盖情况', dataIndex: 'status', width: 110,
                        render: (value) => value === 'covered'
                          ? <Tag color="success">已覆盖</Tag>
                          : <Tag color="warning">待补图</Tag>,
                      },
                      { title: '图片', dataIndex: 'image_ids', render: (value) => (value || []).join('、') || '-' },
                    ]}
                  />
                </div>
              )}

              {missingImageEvidence.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="Listing 卖点缺少图片证据"
                  description={
                    <Space direction="vertical" size={4}>
                      {missingImageEvidence.map((item: any, i: number) => (
                        <Text key={`${item.role}-${i}`}>{item.message || item.claim_label}</Text>
                      ))}
                    </Space>
                  }
                />
              )}

              {listingImageAlignmentPending && (
                <Alert
                  type="info"
                  showIcon
                  message="最终 Listing 图片证据将在文案生成后核对"
                  description="当前展示的是图库本身的覆盖情况；标题、Product Highlights、五点和描述尚未生成，不能据此判断文案卖点是否已有对应图片。"
                />
              )}

              {(duplicateSuppressed.length > 0 || duplicateBackfill.length > 0 || supportedImageClaims.length > 0) && (
                <Space direction="vertical" style={{ width: '100%' }} size={6}>
                  {duplicateSuppressed.length > 0 && (
                    <div>
                      <Text strong>已压制重复图</Text>
                      <div style={{ marginTop: 6 }}>
                        {duplicateSuppressed.slice(0, 8).map((item: any) => (
                          <Tag key={`${item.image_id}-${item.reason}`} color="default">{item.image_id} {item.role_label}</Tag>
                        ))}
                      </div>
                    </div>
                  )}
                  {duplicateBackfill.length > 0 && (
                    <div>
                      <Text strong>重复图兜底使用</Text>
                      <div style={{ marginTop: 6 }}>
                        {duplicateBackfill.slice(0, 8).map((item: any) => (
                          <Tag key={`${item.image_id}-${item.reason}`} color="warning">{item.image_id} {item.role_label}</Tag>
                        ))}
                      </div>
                    </div>
                  )}
                  {supportedImageClaims.length > 0 && (
                    <div>
                      <Text strong>已被图片支持的 Listing 卖点</Text>
                      <div style={{ marginTop: 6 }}>
                        {supportedImageClaims.map((item: any, i: number) => (
                          <Tag key={`${item.role}-${i}`} color="success">{item.claim_label}</Tag>
                        ))}
                      </div>
                    </div>
                  )}
                </Space>
              )}
            </Space>
          </Card>
          <Card
            title="商品图片确认"
            size="small"
            extra={imageResourceItems.length ? (
              <Space>
                {listingImageDirty && <Tag color="warning">未保存</Tag>}
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  disabled={!listingImageDirty || imageOrderSaving}
                  onClick={resetListingImageDraft}
                >
                  取消
                </Button>
                <Button
                  size="small"
                  type="primary"
                  icon={<CheckOutlined />}
                  loading={imageOrderSaving}
                  disabled={!listingImageDirty || !selectedListingImages.length}
                  onClick={saveListingImagePaths}
                >
                  保存
                </Button>
              </Space>
            ) : null}
          >
            <Spin spinning={imageOrderSaving}>
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <div>
                  <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 8 }}>
                    <Text strong>已使用图片</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>最多 9 张，第一张为主图，其余为已确认展示图</Text>
                  </Space>
                  <div
                    onDragOver={(event) => {
                      event.preventDefault();
                      event.dataTransfer.dropEffect = 'move';
                    }}
                    onDrop={dropListingImageToSelected}
                    style={{
                      minHeight: selectedListingImages.length ? 0 : 132,
                      border: selectedListingImages.length ? 'none' : '1px dashed #91caff',
                      borderRadius: 8,
                      padding: selectedListingImages.length ? 0 : 16,
                      background: selectedListingImages.length ? 'transparent' : '#f6fbff',
                    }}
                  >
                    {selectedListingImages.length ? (
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12 }}>
                        {selectedListingImages.map((item, i) => {
                          const isMain = i === 0;
                          const isDropTarget = imageDragPayload?.source && imageDragPayload?.path !== item.path;
                          return (
                            <div
                              key={item.path || i}
                              draggable={!imageOrderSaving}
                              onDragStart={(event) => startListingImageDrag(event, { source: 'selected', index: i, path: item.path })}
                              onDragOver={(event) => {
                                event.preventDefault();
                                event.dataTransfer.dropEffect = 'move';
                              }}
                              onDrop={(event) => replaceListingImageSlot(event, i)}
                              onDragEnd={() => setImageDragPayload(null)}
                              onDoubleClickCapture={(event) => handleListingImageDoubleClick(event, item.path, removeListingImageFromSelected)}
                              onDoubleClick={(event) => handleListingImageDoubleClick(event, item.path, removeListingImageFromSelected)}
                              style={{
                                cursor: imageOrderSaving ? 'default' : 'grab',
                                border: isMain ? '2px solid #1677ff' : '1px solid #d9d9d9',
                                borderRadius: 8,
                                padding: 8,
                                background: imageDragPayload?.source === 'selected' && imageDragPayload?.index === i ? '#f0f7ff' : '#fff',
                                boxShadow: isDropTarget ? '0 0 0 2px rgba(22, 119, 255, 0.12)' : 'none',
                              }}
                            >
                              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                                <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                                  <Tag color={isMain ? 'blue' : 'default'}>{isMain ? '主图' : `副图 ${i}`}</Tag>
                                  <DragOutlined style={{ color: '#999' }} />
                                </Space>
                                <Image
                                  src={imgUrl(item.path)}
                                  width="100%"
                                  alt={isMain ? '主图' : `副图${i}`}
                                  preview={false}
                                  onDoubleClick={(event) => handleListingImageDoubleClick(event, item.path, removeListingImageFromSelected)}
                                  style={{ aspectRatio: '1 / 1', objectFit: 'cover', background: '#f5f5f5' }}
                                />
                                {item.meta && (
                                  <Typography.Paragraph
                                    type="secondary"
                                    ellipsis={{ rows: 1 }}
                                    style={{ fontSize: 12, marginBottom: 0 }}
                                  >
                                    {item.meta}
                                  </Typography.Paragraph>
                                )}
                              </Space>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <Space direction="vertical" size={4} style={{ width: '100%', alignItems: 'center', justifyContent: 'center', minHeight: 96 }}>
                        <Text type="secondary">把备用/未选素材拖到这里，或双击素材加入已使用图片</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>至少保留一张主图后才能保存</Text>
                      </Space>
                    )}
                  </div>
                </div>

                <div>
                  <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 8 }}>
                    <Text strong>其他图片 / 备用/未选素材</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>包含商品页候选、素材包解压图片和品牌图</Text>
                  </Space>
                  <div
                    onDragOver={(event) => {
                      event.preventDefault();
                      event.dataTransfer.dropEffect = 'move';
                    }}
                    onDrop={dropListingImageToUnusedPool}
                    style={{
                      minHeight: 132,
                      border: unusedImageResourceItems.length ? 'none' : '1px dashed #d9d9d9',
                      borderRadius: 8,
                      padding: unusedImageResourceItems.length ? 0 : 16,
                      background: unusedImageResourceItems.length ? 'transparent' : '#fafafa',
                    }}
                  >
                    {unusedImageResourceItems.length ? (
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(132px, 1fr))', gap: 10, maxHeight: 460, overflow: 'auto', paddingRight: 4 }}>
                        {unusedImageResourceItems.map((item, i) => (
                          <div
                            key={item.path || i}
                            draggable={!imageOrderSaving}
                            onDragStart={(event) => startListingImageDrag(event, { source: 'pool', path: item.path })}
                            onDragEnd={() => setImageDragPayload(null)}
                            onDoubleClickCapture={(event) => handleListingImageDoubleClick(event, item.path, addListingImageFromPool)}
                            onDoubleClick={(event) => handleListingImageDoubleClick(event, item.path, addListingImageFromPool)}
                            style={{
                              cursor: imageOrderSaving ? 'default' : 'grab',
                              border: '1px solid #eee',
                              borderRadius: 8,
                              padding: 8,
                              background: '#fff',
                            }}
                          >
                            <Space direction="vertical" size={6} style={{ width: '100%' }}>
                              <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                                <Text strong style={{ fontSize: 12 }}>{item.image_id || `#${i + 1}`}</Text>
                                <DragOutlined style={{ color: '#bbb' }} />
                              </Space>
                              <Image
                                src={imgUrl(item.path)}
                                width="100%"
                                alt={item.filename || `图片${i + 1}`}
                                preview={false}
                                onDoubleClick={(event) => handleListingImageDoubleClick(event, item.path, addListingImageFromPool)}
                                style={{ aspectRatio: '1 / 1', objectFit: 'cover', background: '#f5f5f5' }}
                              />
                              <Typography.Paragraph
                                type="secondary"
                                ellipsis={{ rows: 2 }}
                                style={{ fontSize: 12, marginBottom: 0 }}
                              >
                                {item.visible_selling_point || item.image_type || item.filename}
                              </Typography.Paragraph>
                            </Space>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <Space direction="vertical" size={4} style={{ width: '100%', alignItems: 'center', justifyContent: 'center', minHeight: 96 }}>
                        <Text type="secondary">暂无其他图片 / 备用未选素材</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>把上方图片拖到这里，或双击已使用图片即可移出使用区</Text>
                      </Space>
                    )}
                  </div>
                </div>
              </Space>
            </Spin>
          </Card>
          {imageComplianceAssets.length ? (
            <Card title="Amazon 人像图片元数据合规" size="small" style={{ marginTop: 12 }}>
              <Table
                size="small"
                rowKey={(record: any) => record.slot || record.path || record.url}
                dataSource={imageComplianceAssets}
                pagination={false}
                columns={[
                  { title: '位置', dataIndex: 'slot', width: 100 },
                  { title: '人物', dataIndex: 'contains_person', width: 100, render: (value: boolean) => value ? <Tag color="gold">含人物</Tag> : <Tag>无人像</Tag> },
                  { title: '状态', dataIndex: 'compliance_status', render: (value: string) => value === 'oss_round_trip_verified' ? <Tag color="green">已写标并回读验证</Tag> : <Tag>{value || '未处理'}</Tag> },
                  { title: '投放 URL', dataIndex: 'url', ellipsis: true, render: (value: string) => value ? <a href={value} target="_blank" rel="noreferrer">查看</a> : '-' },
                ]}
              />
            </Card>
          ) : null}
          <Card title="图片分析批次" size="small" style={{ marginTop: 12 }}>
            {reviewsByImageBatch.length ? (
              <Space direction="vertical" style={{ width: '100%' }} size={16}>
                {reviewsByImageBatch.map((batch) => (
                  <Card
                    key={batch.sheet_path}
                    size="small"
                    title={`分析批次 ${batch.sheet_page || ''}`}
                    extra={!isVirtualImageBatch(batch) ? <Button size="small" icon={<FolderOpenOutlined />} loading={isFileOpening(batch.sheet_path)} disabled={isFileOpening(batch.sheet_path)} onClick={() => openPath(batch.sheet_path)}>打开</Button> : null}
                  >
                    {!isVirtualImageBatch(batch) && analysisBatchDisplayUrl(batch) ? (
                      <Image src={analysisBatchDisplayUrl(batch)} width={360} alt={`分析图 ${batch.sheet_page || ''}`} style={{ marginBottom: 12 }} />
                    ) : null}
                    <Table
                      size="small"
                      rowKey={(record) => record.image_id || record.filename}
                      dataSource={batch.reviews || []}
                      pagination={false}
                      columns={[
                        { title: '编号', dataIndex: 'image_id', width: 70, render: (v, r) => v || r.index || '-' },
                        { title: '文件', dataIndex: 'filename', width: 180, ellipsis: true },
                        { title: '类型', dataIndex: 'image_type', width: 150, render: (v) => v || '-' },
                        { title: '可见卖点', dataIndex: 'visible_selling_point', render: (v, r) => v || r.selling_points?.join('；') || '-' },
                        { title: '主图分', dataIndex: 'slot01_score', width: 90, render: (v, r) => v ?? r.quality_score ?? '-' },
                        { title: '副图分', dataIndex: 'gallery_score', width: 90, render: (v) => v ?? '-' },
                        { title: '判断', dataIndex: 'decision_reason', render: (v, r) => v || r.reason || '-' },
                      ]}
                      expandable={{
                        expandedRowRender: (record: any) => {
                          const card = imageEvidenceCards.find((item: any) => item?.image_id === record?.image_id) || {};
                          const observations = card.visual_observations || record.multimodal_result || {};
                          const quality = card.quality_assessment || observations.quality_assessment || {};
                          const tagList = (value: any, color = 'default') => Array.isArray(value) && value.length
                            ? <Space wrap>{value.map((item: any) => <Tag key={String(item)} color={color}>{String(item)}</Tag>)}</Space>
                            : <Text type="secondary">-</Text>;
                          return (
                            <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
                              <Descriptions.Item label="视觉摘要" span={2}>{observations.summary || observations.visual_summary || '-'}</Descriptions.Item>
                              <Descriptions.Item label="角度 / 状态">{[observations.product_angle, observations.product_state].filter(Boolean).join('；') || '-'}</Descriptions.Item>
                              <Descriptions.Item label="颜色 / 场景">{[observations.color_reading, observations.scene_type].filter(Boolean).join('；') || '-'}</Descriptions.Item>
                              <Descriptions.Item label="尺寸 / 比例线索">{observations.size_scale_cues || '-'}</Descriptions.Item>
                              <Descriptions.Item label="可见部件">{observations.visible_parts || '-'}</Descriptions.Item>
                              <Descriptions.Item label="材质 / 纹理">{observations.material_texture || '-'}</Descriptions.Item>
                              <Descriptions.Item label="背景 / 可见文字">{[observations.background_props, observations.visible_text_or_graphics || observations.text_graphics].filter(Boolean).join('；') || '-'}</Descriptions.Item>
                              <Descriptions.Item label="图片可支持的表达" span={2}>{tagList(card.claimable_visual_facts)}</Descriptions.Item>
                              <Descriptions.Item label="不确定或不可宣称" span={2}>{tagList(card.not_proven_or_uncertain || observations.non_claimable_or_uncertain || observations.uncertainty, 'warning')}</Descriptions.Item>
                              <Descriptions.Item label="建议文案用途" span={2}>{tagList(card.recommended_copy_uses, 'blue')}</Descriptions.Item>
                              <Descriptions.Item label="清晰度 / 裁切">{[quality.sharpness, quality.crop_and_completeness].filter(Boolean).join('；') || '-'}</Descriptions.Item>
                              <Descriptions.Item label="光线 / Amazon 适配">{[quality.lighting_and_color, quality.amazon_suitability].filter(Boolean).join('；') || '-'}</Descriptions.Item>
                              <Descriptions.Item label="A+ 参考价值" span={2}>{card.aplus_reference_value || observations.aplus_reference_value || '-'}</Descriptions.Item>
                            </Descriptions>
                          );
                        },
                        rowExpandable: (record: any) => Boolean(record?.multimodal_result || imageEvidenceCards.some((item: any) => item?.image_id === record?.image_id)),
                      }}
                    />
                  </Card>
                ))}
              </Space>
            ) : <Text type="secondary">（暂无图片分析批次）</Text>}
          </Card>
        </div>
      ),
    },
    {
      key: 'aplus',
      label: '🎨 A+内容',
      children: (
        <div>
          {sectionStatus(['aplus_plan', 'aplus_script', 'aplus_assets'])}
          <Card
            title="A+生成"
            size="small"
            style={{ marginBottom: 12 }}
            extra={aplusStatus ? <Tag color={aplusStatus.color}>{aplusStatus.text}</Tag> : <Tag>未生成</Tag>}
          >
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Text type="secondary">
                A+已从商品主流程拆出；商品进入待导出后，可以在这里单个生成，也可以到 A+管理批量生成。
              </Text>
              <Space wrap>
                <Button
                  type="primary"
                  icon={<PictureOutlined />}
                  loading={aplusGenerateLoading && !hasAplusOutput}
                  disabled={!canGenerateAplus || isAplusRegenerating || (hasAplusOutput && aplus?.aplus_status === 'done')}
                  onClick={() => generateAplus(false)}
                >
                  生成A+
                </Button>
                <Popconfirm
                  title="确定强制重跑 A+？"
                  description="会清空已有 A+ 规划、脚本和出图结果，并重新走后台生成任务。"
                  okText="强制重跑"
                  cancelText="取消"
                  onConfirm={() => generateAplus(true)}
                  disabled={!canGenerateAplus || isAplusRegenerating || aplusGenerateLoading}
                >
                  <Button
                    icon={<RedoOutlined />}
                    loading={aplusGenerateLoading && hasAplusOutput}
                    disabled={!canGenerateAplus || isAplusRegenerating || aplusGenerateLoading}
                  >
                    强制重跑
                  </Button>
                </Popconfirm>
                {isAplusRegenerating && <Tag color="processing">后台生成中</Tag>}
                {aplusGenerateDisabledReason && <Text type="secondary">{aplusGenerateDisabledReason}</Text>}
              </Space>
            </Space>
          </Card>
          {renderListingImageConfirmation()}
          <Card
            title="A+规划"
            size="small"
            style={{ marginBottom: 12 }}
            extra={<Tag color={aplusPlanReady ? 'success' : 'default'}>{aplusPlanReady ? '已规划' : '未规划'}</Tag>}
          >
            {aplusPlanReady ? (
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                <Typography.Paragraph style={{ marginBottom: 0 }}>
                  {aplus?.aplus_plan_summary || aplusPlanPayload?.plan_summary || '已生成 A+ 规划'}
                </Typography.Paragraph>
                <Table
                  size="small"
                  rowKey={(record: any) => record.position || record.module_position}
                  dataSource={aplusPlanModules}
                  pagination={false}
                  columns={[
                    { title: '模块', width: 80, render: (_: any, record: any, index: number) => record.position || record.module_position || index + 1 },
                    { title: '标题', dataIndex: 'headline', width: 220, render: (value: any, record: any) => value || record.module_type || '-' },
                    { title: '转化目标', dataIndex: 'conversion_goal', render: (value: any, record: any) => value || record.key_message || '-' },
                    { title: '证据来源', dataIndex: 'evidence_source', render: (value: any) => value || '-' },
                  ]}
                />
              </Space>
            ) : (
              <Text type="secondary">（未规划）</Text>
            )}
          </Card>
          <Card
            title="A+脚本"
            size="small"
            style={{ marginBottom: 12 }}
            extra={<Tag color={aplusScriptReady ? 'success' : 'default'}>{aplusScriptReady ? `${aplusScripts.length} 个脚本` : '未生成脚本'}</Tag>}
          >
            {aplusScriptReady ? (
              <Table
                size="small"
                rowKey={(record: any) => record.module_position || record.position}
                dataSource={aplusScripts}
                pagination={false}
                columns={[
                  { title: '模块', width: 80, render: (_: any, record: any, index: number) => record.module_position || record.position || index + 1 },
                  { title: '用途', dataIndex: 'conversion_goal', width: 220, render: (value: any, record: any) => value || record.experience_angle || '-' },
                  { title: '参考图', dataIndex: 'reference_images', width: 160, render: (refs: any[]) => Array.isArray(refs) ? `${refs.length} 张` : '0 张' },
                  {
                    title: 'Prompt',
                    dataIndex: 'prompt',
                    render: (value: any) => (
                      <Typography.Paragraph copyable ellipsis={{ rows: 2 }} style={{ marginBottom: 0 }}>
                        {value || '-'}
                      </Typography.Paragraph>
                    ),
                  },
                ]}
              />
            ) : (
              <Text type="secondary">{aplusPlanReady ? '已有规划，等待生成脚本。' : '请先完成 A+ 规划。'}</Text>
            )}
          </Card>
          <Card
            title="A+出图"
            size="small"
            extra={(
              <Space>
                <Tag color={aplusImageDoneCount >= 5 ? 'success' : aplusImageDoneCount > 0 ? 'warning' : 'default'}>
                  {aplusImageDoneCount ? `${aplusImageDoneCount}/5 已出图` : '未出图'}
                </Tag>
                {aplusStatus && <Tag color={aplusStatus.color}>{aplusStatus.text}</Tag>}
                {canRetryAplusRegeneration && (
                  <Button size="small" icon={<RedoOutlined />} loading={regenRetryLoading} onClick={retryInterruptedAplus}>
                    重试未完成生图
                  </Button>
                )}
              </Space>
            )}
          >
            {aplusModules.length ? (
              <Space direction="vertical" style={{ width: '100%' }} size={16}>
                {aplusModules.map(({ script, generated, references, plan, hasScript }) => {
                  const moduleStatus = moduleRegenerationStatus(generated);
                  const generationTime = moduleGenerationTime(generated, aplus?.generated_at);
                  const conversionGoal = script.conversion_goal || plan.conversion_goal;
                  const buyerObjection = script.buyer_objection || plan.buyer_objection;
                  const evidenceSource = script.evidence_source || plan.evidence_source;
                  const experienceAngle = script.experience_angle || plan.experience_angle;
                  const galleryOverlapAvoidance = script.gallery_overlap_avoidance || plan.gallery_overlap_avoidance;
                  const riskGuardrails = script.risk_guardrails || plan.risk_guardrails || [];
                  const visualDoNotClaim = script.visual_do_not_claim || plan.visual_do_not_claim || [];
                  const regenDiagnosis = script.regeneration_diagnosis || null;
                  const feedbackAnalysis = regenDiagnosis?.user_feedback_analysis || script.user_feedback_analysis || {};
                  return (
                  <Card
                    key={script.module_position}
                    size="small"
                    title={`模块 ${script.module_position} · ${script.width || '-'}×${script.height || '-'}`}
                    extra={(
                      <Space>
                        <Tag>{script.style || 'image'}</Tag>
                        <Button
                          size="small"
                          icon={<ReloadOutlined />}
                          disabled={!hasScript}
                          onClick={() => {
                            setRegenTarget(script);
                            setRegenReason('');
                          }}
                        >
                          重新生成
                        </Button>
                        <Tag color={moduleStatus.color}>
                          {moduleStatus.text}
                        </Tag>
                        {generationTime && (
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            生成时间：{formatModuleGenerationTime(generationTime)}
                          </Text>
                        )}
                      </Space>
                    )}
                  >
                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(820px, 2.1fr) minmax(280px, 0.65fr)', gap: 16, alignItems: 'start' }}>
                      <div>
                        {(conversionGoal || buyerObjection || evidenceSource || experienceAngle || galleryOverlapAvoidance) && (
                          <Card size="small" title="转化策略" style={{ marginBottom: 12 }}>
                            <Descriptions bordered size="small" column={1}>
                              <Descriptions.Item label="转化目标">{conversionGoal || '-'}</Descriptions.Item>
                              <Descriptions.Item label="买家顾虑">{buyerObjection || '-'}</Descriptions.Item>
                              <Descriptions.Item label="证据来源">{evidenceSource || '-'}</Descriptions.Item>
                              <Descriptions.Item label="体验角度">{experienceAngle || '-'}</Descriptions.Item>
                              <Descriptions.Item label="避免重复">{galleryOverlapAvoidance || '-'}</Descriptions.Item>
                            </Descriptions>
                            {(riskGuardrails.length > 0 || visualDoNotClaim.length > 0) && (
                              <div style={{ marginTop: 10 }}>
                                {riskGuardrails.length > 0 && (
                                  <div style={{ marginBottom: 6 }}>
                                    <Text strong>限制规则</Text>
                                    <div style={{ marginTop: 6 }}>
                                      {riskGuardrails.map((item: string, i: number) => <Tag key={`guard-${i}`} color="warning">{item}</Tag>)}
                                    </div>
                                  </div>
                                )}
                                {visualDoNotClaim.length > 0 && (
                                  <div>
                                    <Text strong>不能表达</Text>
                                    <div style={{ marginTop: 6 }}>
                                      {visualDoNotClaim.map((item: string, i: number) => <Tag key={`no-${i}`} color="red">{item}</Tag>)}
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}
                          </Card>
                        )}
                        {regenDiagnosis && (
                          <Alert
                            type="info"
                            showIcon
                            style={{ marginBottom: 12 }}
                            message={`重生成诊断：${regenDiagnosis.issue_type || '反馈分析'}`}
                            description={[
                              feedbackAnalysis.plain_language_intent ? `反馈理解：${feedbackAnalysis.plain_language_intent}` : null,
                              Array.isArray(feedbackAnalysis.acceptance_criteria) && feedbackAnalysis.acceptance_criteria.length
                                ? `处理要点：${feedbackAnalysis.acceptance_criteria.join('；')}`
                                : null,
                              regenDiagnosis.root_cause,
                              regenDiagnosis.reference_action ? `参考图策略：${regenDiagnosis.reference_action}` : null,
                              regenDiagnosis.reference_rationale,
                            ].filter(Boolean).join('；')}
                          />
                        )}
                        <Text strong>参考图</Text>
                        <div style={{ marginTop: 8 }}>
                          <Space wrap>
                            {references.length ? references.map((ref, i) => (
                              <div key={ref.path} style={{ width: 340 }}>
                                <Image src={imgUrl(ref.path)} width={340} alt={`参考图${i + 1}`} />
                                {(ref.use_for || ref.filename) && (
                                  <Typography.Paragraph
                                    type="secondary"
                                    ellipsis={{ rows: 2 }}
                                    style={{ fontSize: 12, marginTop: 6, marginBottom: 0 }}
                                  >
                                    {ref.label ? `${ref.label} · ` : ''}{ref.use_for || ref.filename}
                                  </Typography.Paragraph>
                                )}
                              </div>
                            )) : <Text type="secondary">暂无参考图</Text>}
                          </Space>
                        </div>
                        <div style={{ marginTop: 12 }}>
                          <Space align="center" style={{ marginBottom: 8 }}>
                            <Text strong>生成图</Text>
                            <Button
                              size="small"
                              icon={<ReloadOutlined />}
                              disabled={!hasScript}
                              onClick={() => {
                                setRegenTarget(script);
                                setRegenReason('');
                              }}
                            >
                              重新生成
                            </Button>
                          </Space>
	                        <div>
	                          {generated?.path ? (
	                            <Space direction="vertical" style={{ width: '100%' }}>
	                              <Space>
	                                <Tag color={generated.status === 'done' ? 'success' : 'error'}>{generated.status || 'done'}</Tag>
	                                {generated.skipped && <Tag color="processing">已复用</Tag>}
	                                {generated.size && <Text type="secondary">{fileSize(generated.size)}</Text>}
	                              </Space>
	                              {(generated.regeneration_requested_at || generated.regeneration_completed_at) && (
	                                <Text type="secondary" style={{ fontSize: 12 }}>
	                                  {generated.regeneration_requested_at ? `发起：${new Date(generated.regeneration_requested_at).toLocaleString('zh-CN')}` : ''}
	                                  {generated.regeneration_requested_at && generated.regeneration_completed_at ? ' · ' : ''}
	                                  {generated.regeneration_completed_at ? `完成：${new Date(generated.regeneration_completed_at).toLocaleString('zh-CN')}` : ''}
	                                </Text>
	                              )}
	                              <Image
                                  src={imgUrl(generated.display_url || generated.oss_url || generated.provider_url || generated.path)}
                                  width={780}
                                  alt={`A+模块${script.module_position}`}
                                />
	                            </Space>
	                          ) : generated?.status === 'failed' ? (
	                            <Alert type="error" showIcon message="生成失败" description={generated.error || '未知错误'} />
	                          ) : <Text type="secondary">未生成</Text>}
	                        </div>
                        </div>
                      </div>
                      <div>
                        <Text strong>生成脚本</Text>
                        <Typography.Paragraph
                          copyable
                          style={{
                            whiteSpace: 'pre-wrap',
                            marginTop: 8,
                            maxHeight: 180,
                            overflow: 'auto',
                            padding: 10,
                            border: '1px solid #eee',
                            borderRadius: 6,
                            background: '#fafafa',
                            fontSize: 12,
                            lineHeight: 1.45,
                          }}
                        >
                          {script.prompt || '脚本尚未生成，当前只保存了 A+ 规划。'}
                        </Typography.Paragraph>
                        {script.negative_prompt && (
                          <>
                            <Text strong>排除项</Text>
                            <Typography.Paragraph
                              copyable
                              type="secondary"
                              style={{
                                whiteSpace: 'pre-wrap',
                                marginTop: 8,
                                maxHeight: 110,
                                overflow: 'auto',
                                padding: 10,
                                border: '1px solid #eee',
                                borderRadius: 6,
                                background: '#fafafa',
                                fontSize: 12,
                                lineHeight: 1.45,
                              }}
                            >
                              {script.negative_prompt}
                            </Typography.Paragraph>
                          </>
                        )}
                        {Array.isArray(script.text_overlays) && script.text_overlays.length > 0 && (
                          <div style={{ marginTop: 8 }}>
                            <Text strong>文字层</Text>
                            <Space wrap style={{ marginTop: 8 }}>
                              {script.text_overlays.map((item, i) => <Tag key={i}>{item.text}</Tag>)}
                            </Space>
                          </div>
                        )}
                      </div>
                    </div>
                  </Card>
                  );
                })}
              </Space>
            ) : <Text type="secondary">（未生成）</Text>}
          </Card>
        </div>
      ),
    },
    {
      key: 'files',
      label: '📁 文件信息',
      children: (
        <div>
          {sectionStatus(['export_artifact'])}
          <Card
            title="素材包与附件"
            size="small"
            loading={fullDetailLoading}
            style={{ marginBottom: 16 }}
            extra={(
              <Button size="small" icon={<ReloadOutlined />} loading={fullDetailLoading} onClick={() => loadFullDetail(true)}>
                刷新素材
              </Button>
            )}
          >
            <Space wrap style={{ marginBottom: 12 }}>
              <Tag color="blue">素材 {materialSummary.asset_count || materialAssets.length}</Tag>
              <Tag color="cyan">图片 {materialSummary.image_count || 0}</Tag>
              <Tag color="purple">视频 {materialSummary.video_count || 0}</Tag>
              <Tag color="gold">素材包 {materialSummary.package_count || 0}</Tag>
              <Tag color="green">已分析图片 {materialSummary.analyzed_image_count || 0}</Tag>
            </Space>
            <Table
              size="small"
              columns={materialColumns}
              dataSource={materialAssets}
              rowKey="id"
              pagination={{ pageSize: 20, hideOnSinglePage: true }}
              scroll={{ x: 1320 }}
              locale={{ emptyText: fullDetailProductId === product.id ? '当前商品还没有登记素材' : '正在加载完整素材信息' }}
              expandable={{
                rowExpandable: (record: ProductMaterialAsset) => record.asset_kind === 'zip' && Boolean(materialChildrenByParent.get(record.id)?.length),
                expandedRowRender: (record: ProductMaterialAsset) => {
                  const children = materialChildrenByParent.get(record.id) || [];
                  return (
                    <List
                      size="small"
                      header={<Text strong>压缩包成员（{children.length}）</Text>}
                      dataSource={children}
                      renderItem={(child) => (
                        <List.Item
                          actions={[
                            <Button key="open" type="link" size="small" onClick={() => openPath(child.path)}>打开</Button>,
                            <Button key="folder" type="link" size="small" onClick={() => openPath(child.path, true)}>文件夹</Button>,
                          ]}
                        >
                          <List.Item.Meta
                            title={<Space><Tag>{materialKindLabel(child.asset_kind)}</Tag><Text>{child.relative_path || child.original_filename}</Text></Space>}
                            description={`${fileSize(child.file_size)} · SHA-256 ${child.content_hash.slice(0, 16)}…`}
                          />
                        </List.Item>
                      )}
                    />
                  );
                },
              }}
            />
          </Card>

          <Card
            title="生成文件"
            size="small"
            style={{ marginBottom: 16 }}
          >
            <Table
              size="small"
              columns={generatedFileColumns}
              dataSource={visibleGeneratedFiles}
              rowKey="id"
              pagination={false}
              scroll={{ x: 920 }}
              locale={{ emptyText: '暂无文件' }}
            />
          </Card>

          <Card title="文件夹入口" size="small" style={{ marginBottom: 16 }}>
            <Table
              size="small"
              columns={fileIndexColumns}
              dataSource={folderRows}
              rowKey="key"
              pagination={false}
              scroll={{ x: 920 }}
              locale={{ emptyText: '暂无文件夹信息' }}
            />
          </Card>

          <Card title="图片 / 视频 / A+ 图片索引" size="small" style={{ marginBottom: 16 }}>
            <Table
              size="small"
              columns={fileIndexColumns}
              dataSource={imageFileRows}
              rowKey="key"
              pagination={false}
              scroll={{ x: 920 }}
              locale={{ emptyText: '暂无图片或视频文件' }}
            />
          </Card>

          <Card title="压缩包文件" size="small">
            <Table
              size="small"
              columns={zipColumns}
              dataSource={product.zip_files || []}
              rowKey="path"
              pagination={false}
              scroll={{ x: 980 }}
              locale={{ emptyText: '素材目录内未发现 zip 压缩包' }}
            />
          </Card>
        </div>
      ),
    },
  ];
  const tabOrder = ['basic', 'competitor', 'images', 'mindset', 'listing', 'aplus', 'files'];
  const orderedTabItems = tabOrder
    .map((key) => tabItems.find((item) => item.key === key))
    .filter(Boolean);

  return (
    <>
    <div>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(backTarget)} style={{ marginRight: 12 }}>
          返回
        </Button>
        <Title level={4} style={{ margin: 0, flex: 1 }}>
          商品 #{product.id}
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => fetchDetail(activeTabKey === 'files' || activeTabKey === 'aplus')}>刷新</Button>
          {hasWorkflow && renderWorkflowActionButton(workflow?.primary_action, workflow?.primary_action_label, true)}
          {hasWorkflow && workflowSecondaryActions.map((action: string) => (
            <React.Fragment key={action}>
              {renderWorkflowActionButton(action)}
            </React.Fragment>
          ))}
          {!hasWorkflow && product.status === 'failed' && !isLegacyGigaBrowserCollectError && !isCompetitorSearchFailed && (
            <Button
              icon={<RedoOutlined />}
              loading={pipelineRetryLoading}
              onClick={async () => {
                setPipelineRetryLoading(true);
                await runMutationWithUX(
                  'retryStep|frontend/src/pages/ProductDetail.tsx|ProductDetail',
                  async (metadata) => {
                    await retryStep(product.id, metadata);
                    await fetchDetail();
                  },
                  {
                    errorFallback: '重试失败',
                    onError: (errorMessage) => message.error(errorMessage),
                    clearLoading: () => setPipelineRetryLoading(false),
                  },
                ).catch(() => undefined);
              }}
            >
              重试
            </Button>
          )}
          {!hasWorkflow && product.status === 'paused' && (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={pipelineRetryLoading}
              onClick={async () => {
                setPipelineRetryLoading(true);
                await runMutationWithUX(
                  'resumePipeline|frontend/src/pages/ProductDetail.tsx|ProductDetail|1',
                  async (metadata) => {
                    await resumePipeline(product.id, metadata);
                    await fetchDetail();
                  },
                  {
                    errorFallback: '继续失败',
                    onError: (errorMessage) => message.error(errorMessage),
                    clearLoading: () => setPipelineRetryLoading(false),
                  },
                ).catch(() => undefined);
              }}
            >
              继续
            </Button>
          )}
          {!hasWorkflow && product.status === 'pending_review' && (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={pipelineRetryLoading}
              onClick={async () => {
                setPipelineRetryLoading(true);
                await runMutationWithUX(
                  'resumePipeline|frontend/src/pages/ProductDetail.tsx|ProductDetail|2',
                  async (metadata) => {
                    await resumePipeline(product.id, metadata);
                    await fetchDetail();
                  },
                  {
                    errorFallback: '继续失败',
                    onError: (errorMessage) => message.error(errorMessage),
                    clearLoading: () => setPipelineRetryLoading(false),
                  },
                ).catch(() => undefined);
              }}
            >
              继续
            </Button>
          )}
          {canRetryAplusRegeneration && (
            <Button icon={<RedoOutlined />} loading={regenRetryLoading} onClick={retryInterruptedAplus}>
              重试A+重新生图
            </Button>
          )}
          {!hasWorkflow && canGenerateMissingListing && (
            <Button type="primary" icon={<PlayCircleOutlined />} loading={listingRegenerateLoading} onClick={regenerateListing}>
              生成Listing
            </Button>
          )}
          {!hasWorkflow && isInterruptedProduct && (
            <Button type="primary" icon={<RedoOutlined />} loading={pipelineRetryLoading} onClick={retryInterruptedPipeline}>
              重试当前节点
            </Button>
          )}
          {!hasWorkflow && isPipelineRunning && (
            <Button
              icon={<PauseOutlined />}
              loading={pipelineRetryLoading}
              onClick={async () => {
                setPipelineRetryLoading(true);
                await runMutationWithUX(
                  'pausePipeline|frontend/src/pages/ProductDetail.tsx|ProductDetail|1',
                  async (metadata) => {
                    await pausePipeline(product.id, metadata);
                    await fetchDetail();
                  },
                  {
                    errorFallback: '挂起失败',
                    onError: (errorMessage) => message.error(errorMessage),
                    clearLoading: () => setPipelineRetryLoading(false),
                  },
                ).catch(() => undefined);
              }}
            >
              挂起
            </Button>
          )}
          {!hasWorkflow && canSuspendProduct && !isPipelineRunning && (
            <Popconfirm
              title="挂起这个商品？"
              description="挂起后不会继续执行后续自动流程，之后可以点继续恢复。"
              okText="挂起"
              cancelText="取消"
              onConfirm={async () => {
                setPipelineRetryLoading(true);
                await runMutationWithUX(
                  'pausePipeline|frontend/src/pages/ProductDetail.tsx|ProductDetail|2',
                  async (metadata) => {
                    await pausePipeline(product.id, metadata);
                    await fetchDetail();
                  },
                  {
                    errorFallback: '挂起失败',
                    onError: (errorMessage) => message.error(errorMessage),
                    clearLoading: () => setPipelineRetryLoading(false),
                  },
                ).catch(() => undefined);
              }}
            >
              <Button icon={<PauseOutlined />} loading={pipelineRetryLoading}>挂起</Button>
            </Popconfirm>
          )}
          {!hasWorkflow && canRestartProduct && (
            <Popconfirm
              title="确定重新开始流程？"
              description="会保留已使用图片，清空旧候选竞品、已选竞品、图片分析、用户心智、Listing、A+ 和生成文件；有主图时会重新搜索候选竞品。"
              okText="重新开始"
              cancelText="取消"
              onConfirm={() => doRestart()}
            >
              <Button icon={<RedoOutlined />} loading={restartLoading}>重新开始流程</Button>
            </Popconfirm>
          )}
          <Popconfirm
            title="确定删除此商品？"
            okText="删除"
            cancelText="取消"
            onConfirm={handleDelete}
          >
            <Button danger icon={<DeleteOutlined />} loading={deleting}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      </div>

      {/* Pipeline 进度条 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Steps
          current={!hasWorkflow && isReadyToExport ? pipelineSteps.length : currentStepIndex}
          status={stepStatus}
          items={pipelineSteps}
          size="small"
        />
      </Card>

      {/* 状态信息 */}
      {hasWorkflow && (
        <Alert
          type={workflow?.stage_status === 'failed' || workflow?.work_status === 'failed' ? 'error' : workflow?.stage_status === 'processing' || workflow?.work_status === 'running' || workflow?.work_status === 'competitor_searching' ? 'info' : workflow?.stage_status === 'succeeded' || workflow?.work_status === 'export_ready' || workflow?.work_status === 'exported' ? 'success' : 'warning'}
          showIcon
          style={{ marginBottom: 16 }}
          message={(
            <Space wrap>
              <span>{workflow?.label || workflowWorkStatusMeta?.label || '当前流程状态'}</span>
              {workflowWorkStatusMeta && <Tag color={workflow?.color || workflowWorkStatusMeta.color}>{workflowWorkStatusMeta.label}</Tag>}
            </Space>
          )}
          description={workflow?.action_reason || product.current_task_status || null}
        />
      )}
      {!hasWorkflow && product.status === 'paused' && (
        <Card size="small" style={{ marginBottom: 16, borderColor: '#d9d9d9' }}>
          <Text type="secondary">已挂起：不会继续执行后续自动流程，点击继续后从当前步骤恢复。</Text>
        </Card>
      )}
      {!hasWorkflow && isInterruptedProduct && product.current_task_status && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={product.current_task_status}
        />
      )}
      {!hasWorkflow && isPipelineRunning && product.current_task_status && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={product.current_task_status}
        />
      )}
      {!hasWorkflow && product.status === 'step5_listing' && /竞品.*抓取中|Listing.*抓取中/i.test(product.error_message || '') && (
        <Card size="small" style={{ marginBottom: 16, borderColor: '#1677ff' }}>
          <Text type="secondary">{product.error_message}</Text>
        </Card>
      )}
      {!hasWorkflow && showTopProductError && (
        <Card size="small" style={{ marginBottom: 16, borderColor: '#ff4d4f' }}>
          <Text type="danger">{product.status === 'source_unavailable' ? '原商品下架停止采集：' : '❌ '}{productErrorMessage}</Text>
        </Card>
      )}

      {/* 内容 Tabs */}
      <Tabs
        activeKey={activeTabKey}
        items={orderedTabItems}
        onChange={(key) => {
          userTouchedTabRef.current = true;
          setActiveTabKey(key);
          if (key === 'files') void loadFullDetail();
        }}
      />
    </div>
    <Modal
      title={spreadsheetPreviewTitle || '表格预览'}
      open={Boolean(spreadsheetPreview)}
      footer={null}
      width={1000}
      onCancel={() => setSpreadsheetPreview(null)}
    >
      {spreadsheetPreview && (
        <div>
          <Space style={{ marginBottom: 12 }}>
            <Tag color="blue">工作表：{spreadsheetPreview.sheet_name}</Tag>
            <Tag>{spreadsheetPreview.rows.length} 行预览</Tag>
            {spreadsheetPreview.truncated ? <Tag color="warning">仅展示前 50 行、20 列</Tag> : null}
          </Space>
          <div style={{ overflow: 'auto', maxHeight: 600, border: '1px solid #eee' }}>
            <table style={{ borderCollapse: 'collapse', minWidth: '100%', fontSize: 12 }}>
              <tbody>
                {spreadsheetPreview.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    <td style={{ position: 'sticky', left: 0, background: '#fafafa', border: '1px solid #eee', padding: '6px 8px', color: '#999' }}>{rowIndex + 1}</td>
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex} style={{ border: '1px solid #eee', padding: '6px 8px', whiteSpace: 'nowrap' }}>{String(cell ?? '')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
    <Modal
      title={`重新生成A+模块 ${regenTarget?.module_position || ''}`}
      open={!!regenTarget}
      okText="重新生成"
      cancelText="取消"
      confirmLoading={regenLoading}
      onOk={regenerateAplus}
      onCancel={() => {
        if (!regenLoading) {
          setRegenTarget(null);
          setRegenReason('');
        }
      }}
    >
      <Text type="secondary">写清楚这张图哪里不行。系统会把你的反馈作为必须满足的修改要求，先重新生成 prompt；如果当前参考图支撑不了这个修改目标，再从已分析过的图片里换参考图。</Text>
      <Input.TextArea
        value={regenReason}
        onChange={(event) => setRegenReason(event.target.value)}
        rows={5}
        maxLength={2000}
        showCount
        style={{ marginTop: 12 }}
        placeholder="例如：沙发比例变形了，场景图里人物只露出半身；请保持商品原结构，人物要完整，图片文字不要出现品牌名。"
      />
    </Modal>
    <Modal
      title="编辑 Amazon 类目"
      open={categoryEditOpen}
      okText="保存类目"
      cancelText="取消"
      confirmLoading={categorySaving}
      onOk={saveCategory}
      onCancel={() => {
        if (!categorySaving) setCategoryEditOpen(false);
      }}
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <div>
          <Text type="secondary">从已有 Amazon 类目中选择</Text>
          <Select
            showSearch
            loading={categoryOptionsLoading}
            value={selectedCategoryKey}
            onChange={setSelectedCategoryKey}
            placeholder="请选择已有类目"
            style={{ width: '100%', marginTop: 6 }}
            optionFilterProp="label"
            options={categoryOptions.map((item) => ({
              value: item.key,
              label: item.label,
            }))}
          />
        </div>
        {selectedCategoryKey && (
          <Text type="secondary">
            叶子类目：{categoryOptions.find((item) => item.key === selectedCategoryKey)?.leaf_category || '-'}
          </Text>
        )}
      </Space>
    </Modal>
    <Modal
      title="编辑 Listing 文案"
      open={listingEditOpen}
      okText="保存 Listing"
      cancelText="取消"
      confirmLoading={listingSaving}
      width={820}
      onOk={saveListing}
      onCancel={() => {
        if (!listingSaving) setListingEditOpen(false);
      }}
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <div>
          <Text type="secondary">标题</Text>
          <Input.TextArea
            value={listingTitleInput}
            onChange={(event) => setListingTitleInput(event.target.value)}
            rows={2}
            maxLength={75}
            showCount
          />
        </div>
        <div>
          <Text type="secondary">五点描述（每行一条）</Text>
          <Input.TextArea
            value={listingBulletsInput}
            onChange={(event) => setListingBulletsInput(event.target.value)}
            rows={8}
          />
        </div>
        <div>
          <Text type="secondary">标题补充（仅 1 条，最多 120 字符；标题少于 75 字符时可向买家展示）</Text>
          {listingProductHighlightsInput.map((highlight, index) => (
            <div
              key={`product-highlight-${index}`}
              style={{ borderTop: index ? '1px solid #f0f0f0' : undefined, marginTop: 10, paddingTop: 10 }}
            >
              <Text strong>标题补充</Text>
              <Input.TextArea
                value={highlight}
                onChange={(event) => updateProductHighlight(index, event.target.value)}
                placeholder="英文标题补充"
                rows={2}
                maxLength={120}
                showCount
              />
              <Input.TextArea
                value={listingProductHighlightsZhInput[index] || ''}
                onChange={(event) => updateProductHighlight(index, event.target.value, true)}
                placeholder="中文翻译（可选）"
                rows={2}
                maxLength={120}
                showCount
                style={{ marginTop: 8 }}
              />
            </div>
          ))}
        </div>
        <div>
          <Text type="secondary">商品描述</Text>
          <Input.TextArea
            value={listingDescriptionInput}
            onChange={(event) => setListingDescriptionInput(event.target.value)}
            rows={5}
            maxLength={1900}
            showCount
          />
        </div>
        <div>
          <Text type="secondary">Search Terms</Text>
          <Input.TextArea
            value={listingSearchTermsInput}
            onChange={(event) => setListingSearchTermsInput(event.target.value)}
            rows={2}
          />
        </div>
        <div>
          <Text type="secondary">主关键词</Text>
          <Input
            value={listingPrimaryKeywordInput}
            onChange={(event) => setListingPrimaryKeywordInput(event.target.value)}
          />
        </div>
        <div>
          <Text type="secondary">中文标题</Text>
          <Input.TextArea
            value={listingTitleZhInput}
            onChange={(event) => setListingTitleZhInput(event.target.value)}
            rows={2}
          />
        </div>
        <div>
          <Text type="secondary">中文五点（每行一条）</Text>
          <Input.TextArea
            value={listingBulletsZhInput}
            onChange={(event) => setListingBulletsZhInput(event.target.value)}
            rows={6}
          />
        </div>
        <div>
          <Text type="secondary">中文商品描述</Text>
          <Input.TextArea
            value={listingDescriptionZhInput}
            onChange={(event) => setListingDescriptionZhInput(event.target.value)}
            rows={5}
            maxLength={1900}
            showCount
          />
        </div>
        <div>
          <Text type="secondary">中文 Search Terms</Text>
          <Input.TextArea
            value={listingSearchTermsZhInput}
            onChange={(event) => setListingSearchTermsZhInput(event.target.value)}
            rows={2}
          />
        </div>
      </Space>
    </Modal>
    </>
  );
};

export default ProductDetail;
