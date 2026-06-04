// @ts-nocheck
import React, { useEffect, useState, useRef } from 'react';
import { useLocation, useParams, useNavigate } from 'react-router-dom';
import { Alert, Card, Descriptions, Tag, Steps, Tabs, Button, Space, Typography, Spin, message, Popconfirm, Image, Table, List, Modal, Input, Select, Empty } from 'antd';
import {
  ArrowLeftOutlined, PlayCircleOutlined, RedoOutlined,
  PauseOutlined, ReloadOutlined, DeleteOutlined,
  FolderOpenOutlined, FileZipOutlined, InboxOutlined, FileExcelOutlined,
  CheckOutlined, DragOutlined, CopyOutlined, ExportOutlined,
} from '@ant-design/icons';
import { getProduct, restartPipeline, retryStep, resumePipeline, pausePipeline, deleteProduct, openProductFile, extractProductZip, regenerateAplusModule, retryAplusRegeneration, updateProduct, updateProductListingImages, confirmProduct, listCategoryOptions, listProductCompetitorCandidates, searchProductCompetitorCandidates, selectProductCompetitorCandidate } from '../api';
import type { AmazonStyleSnapCandidateGroup, CategoryOption, ProductDetail } from '../api';

const { Title, Text } = Typography;
const PRODUCT_LIST_RETURN_KEY = 'fbm.productList.returnPath';

const APLUS_REGEN_ACTIVE_STATUSES = ['regen_queued', 'regen_script_running', 'regen_image_running'];
const APLUS_REGEN_RETRYABLE_STATUSES = ['regen_failed', 'regen_interrupted'];
const APLUS_STATUS_LABELS: Record<string, { color: string; text: string }> = {
  done: { color: 'success', text: 'A+已完成' },
  partial: { color: 'warning', text: 'A+部分完成' },
  regen_queued: { color: 'processing', text: '重新生图排队中' },
  regen_script_running: { color: 'processing', text: '正在重写脚本' },
  regen_image_running: { color: 'processing', text: '正在重新生图' },
  regen_done: { color: 'success', text: '重新生图完成' },
  regen_failed: { color: 'error', text: '重新生图失败' },
  regen_interrupted: { color: 'warning', text: '重新生图被中断' },
};

/** 将本地文件路径转为后端图片代理URL */
const imgUrl = (localPath: string | null | undefined) => {
  if (!localPath) return '';
  if (/^https?:\/\//i.test(String(localPath))) return String(localPath);
  return `/api/images/${localPath}`;
};
const isRemoteUrl = (value: string | null | undefined) => /^https?:\/\//i.test(String(value || ''));

const parseJson = (value: string | null | undefined, fallback: any = null) => {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
};

const normalizeImagePath = (item: any) => {
  const path = typeof item === 'string' ? item : item?.path;
  return path ? String(path).trim() : '';
};

const listingImagePathsFromImages = (images: any) => {
  const galleryImagePaths = parseJson(images?.gallery_images, []);
  const paths = [
    images?.main_image_path ? String(images.main_image_path).trim() : '',
    ...(Array.isArray(galleryImagePaths) ? galleryImagePaths.map(normalizeImagePath) : []),
  ].filter(Boolean);
  return paths.filter((path, index) => paths.indexOf(path) === index);
};

const money = (value: number | null | undefined) => value != null ? `$${value}` : '-';
const numberText = (value: number | null | undefined, unit = '') => value != null ? `${value}${unit}` : '-';
const fileSize = (bytes: number | null | undefined) => {
  if (!bytes) return '-';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};
const valueText = (value: string | null | undefined) => value || '-';
const captureStatusTag = (status: string | null | undefined) => {
  if (!status) return <Tag>未抓详情</Tag>;
  if (status === 'captured') return <Tag color="success">已抓详情</Tag>;
  if (status === 'queued') return <Tag color="processing">等待抓详情</Tag>;
  if (status === 'running') return <Tag color="processing">抓详情中</Tag>;
  if (status === 'failed') return <Tag color="error">详情抓取失败</Tag>;
  return <Tag color="processing">{status}</Tag>;
};

const defaultProductDetailTab = (detail: ProductDetail | null | undefined) => {
  if (!detail) return 'basic';

  const snapshot = parseJson(detail.data?.gigab2b_raw_snapshot, {});
  const searchStatus = snapshot?.stylesnap_search?.status || '';
  const captureStatus = snapshot?.amazon_listing_capture?.status || '';
  const selectedAsin = snapshot?.selected_stylesnap?.asin || detail.competitor_asin;
  const step = Number(detail.current_step || 0);
  const hasMainImage = Boolean(detail.images?.main_image_path || snapshot?.selected_stylesnap?.source_image_path);
  const hasListingCapture = Boolean(
    captureStatus === 'captured'
    || (snapshot?.amazon_listing_capture?.title && captureStatus !== 'failed')
  );
  const hasListingContent = Boolean(
    detail.data?.listing_title
    || detail.data?.listing_bullets
    || detail.data?.listing_description
    || detail.data?.listing_search_terms
  );
  const hasAplusOutput = Boolean(
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
    || searchStatus === 'running'
    || searchStatus === 'failed'
    || (!selectedAsin && hasMainImage)
    || ['queued', 'running', 'failed'].includes(captureStatus)
    || (detail.status === 'failed' && competitorCaptureMessage.test(detail.error_message || ''))
  ) {
    return 'competitor';
  }
  if (
    step === 5
    || detail.status === 'step6_curating'
    || (detail.status === 'failed' && imageAnalysisMessage.test(detail.error_message || ''))
    || (hasListingCapture && !detail.images?.image_analysis && !hasListingContent)
  ) {
    return 'images';
  }
  if (step >= 7 || hasAplusOutput) return 'aplus';
  if (step >= 6 || hasListingContent) return 'listing';
  return 'basic';
};

const ProductDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const backTarget = (location.state as any)?.from || window.localStorage.getItem(PRODUCT_LIST_RETURN_KEY) || '/products';
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenTarget, setRegenTarget] = useState<any | null>(null);
  const [regenReason, setRegenReason] = useState('');
  const [regenLoading, setRegenLoading] = useState(false);
  const [regenRetryLoading, setRegenRetryLoading] = useState(false);
  const [restartLoading, setRestartLoading] = useState(false);
  const [activeTabKey, setActiveTabKey] = useState('basic');
  const [categoryEditOpen, setCategoryEditOpen] = useState(false);
  const [categoryOptions, setCategoryOptions] = useState<CategoryOption[]>([]);
  const [selectedCategoryKey, setSelectedCategoryKey] = useState<string | undefined>();
  const [categoryOptionsLoading, setCategoryOptionsLoading] = useState(false);
  const [categorySaving, setCategorySaving] = useState(false);
  const [competitorModalOpen, setCompetitorModalOpen] = useState(false);
  const [competitorGroup, setCompetitorGroup] = useState<AmazonStyleSnapCandidateGroup | null>(null);
  const [competitorLoading, setCompetitorLoading] = useState(false);
  const [competitorSearchLoading, setCompetitorSearchLoading] = useState(false);
  const [selectingCompetitorId, setSelectingCompetitorId] = useState<number | null>(null);
  const [listingEditOpen, setListingEditOpen] = useState(false);
  const [listingTitleInput, setListingTitleInput] = useState('');
  const [listingBulletsInput, setListingBulletsInput] = useState('');
  const [listingDescriptionInput, setListingDescriptionInput] = useState('');
  const [listingSearchTermsInput, setListingSearchTermsInput] = useState('');
  const [listingTitleZhInput, setListingTitleZhInput] = useState('');
  const [listingBulletsZhInput, setListingBulletsZhInput] = useState('');
  const [listingDescriptionZhInput, setListingDescriptionZhInput] = useState('');
  const [listingSearchTermsZhInput, setListingSearchTermsZhInput] = useState('');
  const [listingPrimaryKeywordInput, setListingPrimaryKeywordInput] = useState('');
  const [listingSaving, setListingSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [imageOrderSaving, setImageOrderSaving] = useState(false);
  const [imageDragPayload, setImageDragPayload] = useState<any | null>(null);
  const [listingImageDraftPaths, setListingImageDraftPaths] = useState<string[]>([]);
  const [listingImageDirty, setListingImageDirty] = useState(false);
  const [listingImageDraftProductId, setListingImageDraftProductId] = useState<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoTabProductIdRef = useRef<number | null>(null);
  const userTouchedTabRef = useRef(false);

  const refreshCompetitorGroupFromProduct = async (detail: ProductDetail) => {
    const snapshot = parseJson(detail.data?.gigab2b_raw_snapshot, {});
    const searchStatus = snapshot?.stylesnap_search?.status;
    const shouldLoadCandidates = Boolean(
      detail.images?.main_image_path
      && (
        searchStatus === 'captured'
        || detail.status === 'competitor_searching'
        || detail.competitor_asin
        || Number(detail.current_step || 0) >= 2
      )
    );
    if (!shouldLoadCandidates) {
      return;
    }
    try {
      const { data: group } = await listProductCompetitorCandidates(detail.id);
      setCompetitorGroup(group);
    } catch {
      setCompetitorGroup(null);
    }
  };

  const fetchDetail = async () => {
    if (!id) return;
    try {
      const { data } = await getProduct(Number(id));
      setProduct(data);
      const nextDefaultTab = defaultProductDetailTab(data);
      const isNewProduct = autoTabProductIdRef.current !== data.id;
      if (isNewProduct) {
        autoTabProductIdRef.current = data.id;
        userTouchedTabRef.current = false;
        setActiveTabKey(nextDefaultTab);
      } else if (!userTouchedTabRef.current) {
        setActiveTabKey(nextDefaultTab);
      }
      await refreshCompetitorGroupFromProduct(data);
    } catch {
      message.error('加载失败');
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchDetail();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [id]);

  // 自动轮询：任务运行中时每3秒刷新
  useEffect(() => {
    if (!product) return;
    const isRunning = !['completed', 'pending_review', 'failed', 'paused', 'created', 'unavailable', 'source_unavailable'].includes(product.status)
      || APLUS_REGEN_ACTIVE_STATUSES.includes(product.aplus?.aplus_status || '');
    if (isRunning) {
      pollRef.current = setInterval(fetchDetail, 3000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [product?.status, product?.aplus?.aplus_status]);

  useEffect(() => {
    if (!product) return;
    if (listingImageDraftProductId !== product.id || !listingImageDirty) {
      setListingImageDraftPaths(listingImagePathsFromImages(product.images));
      setListingImageDirty(false);
      setListingImageDraftProductId(product.id);
    }
  }, [
    product?.id,
    product?.images?.main_image_path,
    product?.images?.gallery_images,
    listingImageDirty,
    listingImageDraftProductId,
  ]);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  if (!product) return <div>商品不存在</div>;

  const data = product.data;
  const images = product.images;
  const aplus = product.aplus;
  const aplusStatus = aplus?.aplus_status ? APLUS_STATUS_LABELS[aplus.aplus_status] : null;
  const isAplusRegenerating = APLUS_REGEN_ACTIVE_STATUSES.includes(aplus?.aplus_status || '');
  const canRetryAplusRegeneration = APLUS_REGEN_RETRYABLE_STATUSES.includes(aplus?.aplus_status || '');

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteProduct(product.id);
      message.success('商品已删除');
      navigate(backTarget);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除失败');
    } finally {
      setDeleting(false);
    }
  };
  const videoFolder = product.video_folder;
  const aplusFolder = product.aplus_folder;
  const packages = parseJson(data?.packages, []);
  const rawSnapshot = parseJson(data?.gigab2b_raw_snapshot, null);
  const selectedStyleSnap = rawSnapshot?.selected_stylesnap || null;
  const amazonListingCapture = rawSnapshot?.amazon_listing_capture || null;
  const amazonCompetitorBullets = Array.isArray(amazonListingCapture?.bullets)
    ? amazonListingCapture.bullets.filter((item: any) => String(item || '').trim())
    : [];
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
  const generatedFiles = product.generated_files || [];
  const visibleGeneratedFiles = generatedFiles.filter((file: any) => file?.file_type !== 'amazon_import_template');
  const dimensionLine = (length?: number | string | null, width?: number | string | null, height?: number | string | null, unit = 'in') => (
    length != null && width != null && height != null ? `${length} × ${width} × ${height} ${unit}` : '-'
  );
  const imageAnalysisPayload = parseJson(images?.image_analysis, null);
  const imageReviews = Array.isArray(imageAnalysisPayload)
    ? imageAnalysisPayload
    : (imageAnalysisPayload?.images || []);
  const imageSelectionDiagnostics = imageAnalysisPayload?.selection_diagnostics || {};
  const imageHealth = imageSelectionDiagnostics?.image_health || {};
  const imageGalleryRoles = imageSelectionDiagnostics?.gallery_roles || [];
  const missingGalleryRoles = imageSelectionDiagnostics?.missing_gallery_roles || [];
  const duplicateSuppressed = imageSelectionDiagnostics?.duplicate_suppressed || [];
  const duplicateBackfill = imageSelectionDiagnostics?.duplicate_backfill || [];
  const listingImageAlignment = imageSelectionDiagnostics?.listing_image_alignment || {};
  const missingImageEvidence = listingImageAlignment?.missing_evidence || [];
  const supportedImageClaims = listingImageAlignment?.supported_claims || [];
  const contactSheets = imageAnalysisPayload?.contact_sheets || (
    images?.contact_sheet_path ? [{ sheet_page: 1, sheet_path: images.contact_sheet_path, image_ids: imageReviews.map((item) => item.image_id || `#${item.index}`) }] : []
  );
  const reviewsBySheet = contactSheets.map((sheet) => ({
    ...sheet,
    reviews: imageReviews.filter((review) => review?.contact_sheet_evidence?.sheet_path === sheet.sheet_path || sheet.image_ids?.includes(review.image_id)),
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
          image_type: index === 0 ? '主图素材' : '副图素材',
          reason: index === 0 ? '大健 listing 首图' : `大健 listing 第 ${index + 1} 张`,
        });
      });
    }
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
    ...contactSheets.map((sheet, index) => sheet?.sheet_path && {
      key: `contact-sheet-${index}-${sheet.sheet_path}`,
      kind: '分析图',
      label: `Contact Sheet ${sheet.sheet_page || index + 1}`,
      path: sheet.sheet_path,
      url: imgUrl(sheet.sheet_path),
      localPath: sheet.sheet_path,
      previewable: true,
      meta: `${sheet.image_ids?.length || 0} 张图`,
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
    try {
      await openProductFile(product.id, path, directory);
      message.success('已打开');
    } catch {
      message.error('打开失败');
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

  const loadCompetitorCandidates = async (silent = false) => {
    setCompetitorLoading(true);
    try {
      const { data: group } = await listProductCompetitorCandidates(product.id);
      setCompetitorGroup(group);
    } catch (error: any) {
      setCompetitorGroup(null);
      if (!silent) message.error(error?.response?.data?.detail || '加载候选竞品失败');
    } finally {
      setCompetitorLoading(false);
    }
  };

  const searchCompetitorCandidates = async (force = false) => {
    setCompetitorSearchLoading(true);
    message.loading({ content: '正在启动 Amazon StyleSnap 同款搜索', key: 'competitor-search', duration: 0 });
    try {
      await searchProductCompetitorCandidates(product.id, force);
      message.success({ content: '已提交同款搜索，Chrome 会在后台用主图搜索 Amazon', key: 'competitor-search' });
      await fetchDetail();
      if (!force) {
        try {
          const { data: group } = await listProductCompetitorCandidates(product.id);
          setCompetitorGroup(group);
        } catch {
          setCompetitorGroup(null);
        }
      }
    } catch (error: any) {
      message.destroy('competitor-search');
      message.error(error?.response?.data?.detail || '启动同款搜索失败');
    } finally {
      setCompetitorSearchLoading(false);
    }
  };

  const chooseCompetitorCandidate = async (candidate: any) => {
    const selectedId = competitorGroup?.selected_candidate_id;
    const isSwitching = selectedId && selectedId !== candidate.id;
    const forceCapture = selectedId === candidate.id || candidate.listing_capture_status === 'failed';
    const hasDownstreamOutput = hasListingContent || hasListingImages || hasImageAnalysis || hasAplusOutput || product.current_step >= 5;
    const doSelect = async () => {
      setSelectingCompetitorId(candidate.id);
      message.loading({ content: '正在提交选择，竞品详情抓取会在后台执行', key: 'competitor-select', duration: 0 });
      try {
        const { data: group } = await selectProductCompetitorCandidate(product.id, candidate.id, forceCapture);
        setCompetitorGroup(group);
        message.success({ content: `${forceCapture ? '已重新提交' : '已选择'}参考竞品 ${candidate.asin}，竞品详情抓取已转后台执行`, key: 'competitor-select' });
        await fetchDetail();
      } catch (error: any) {
        message.destroy('competitor-select');
        message.error(error?.response?.data?.detail || '选择竞品失败');
      } finally {
        setSelectingCompetitorId(null);
      }
    };
    if (isSwitching && hasDownstreamOutput) {
      Modal.confirm({
        title: '确认切换参考竞品？',
        content: '切换后会记录新的 ASIN，并在后台抓取这个竞品的详情页。当前商品后续的 Listing 文案、图片分析、A+ 需要重新生成。',
        okText: '切换并抓详情',
        cancelText: '取消',
        onOk: doSelect,
      });
      return;
    }
    if (forceCapture && hasDownstreamOutput) {
      Modal.confirm({
        title: '确认重新抓取竞品详情？',
        content: '重新抓取后会刷新选中竞品的标题、五点、描述、类目等参考数据；后续生成内容需要重新确认或重跑。',
        okText: '重新抓详情',
        cancelText: '取消',
        onOk: doSelect,
      });
      return;
    }
    await doSelect();
  };

  const retrySelectedCompetitorCapture = async () => {
    const selectedId = competitorGroup?.selected_candidate_id || rawSnapshot?.selected_stylesnap?.candidate_id;
    let group = competitorGroup;
    if (!group) {
      setCompetitorLoading(true);
      try {
        const { data } = await listProductCompetitorCandidates(product.id);
        group = data;
        setCompetitorGroup(data);
      } catch (error: any) {
        message.error(error?.response?.data?.detail || '加载候选竞品失败，无法重新抓取');
        return;
      } finally {
        setCompetitorLoading(false);
      }
    }
    const selected = group?.candidates?.find((candidate: any) => (
      candidate.id === selectedId || candidate.is_selected === 1
    ));
    if (!selected) {
      message.warning('当前未找到已选竞品，请先在候选竞品中选择一个');
      return;
    }
    await chooseCompetitorCandidate({ ...selected, listing_capture_status: 'failed' });
  };

  const extractZip = async (path: string) => {
    try {
      await extractProductZip(product.id, path);
      message.success('已解压');
      fetchDetail();
    } catch {
      message.error('解压失败');
    }
  };

  const regenerateAplus = async () => {
    if (!regenTarget) return;
    const reason = regenReason.trim();
    if (!reason) {
      message.warning('先写一下哪里不行，系统会按这个原因重写脚本');
      return;
    }
    setRegenLoading(true);
    try {
      const { data: result } = await regenerateAplusModule(product.id, {
        module_position: regenTarget.module_position,
        reason,
      });
      message.success(result?.message || '已提交后台重新生成');
      setRegenTarget(null);
      setRegenReason('');
      fetchDetail();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'A+重新生成失败');
    } finally {
      setRegenLoading(false);
    }
  };

  const retryInterruptedAplus = async () => {
    setRegenRetryLoading(true);
    try {
      const { data: result } = await retryAplusRegeneration(product.id);
      message.success(result?.message || '已重新排队 A+ 重新生图任务');
      await fetchDetail();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'A+重新生图重试失败');
    } finally {
      setRegenRetryLoading(false);
    }
  };

  const setDraftListingImagePaths = (paths: string[]) => {
    setListingImageDraftPaths(paths.filter((path, index) => path && paths.indexOf(path) === index));
    setListingImageDirty(true);
  };

  const saveListingImagePaths = async () => {
    const orderedPaths = listingImageDraftPaths.filter(Boolean);
    if (!orderedPaths.length) return;
    setImageOrderSaving(true);
    try {
      await updateProductListingImages(product.id, {
        main_image_path: orderedPaths[0],
        gallery_images: orderedPaths.slice(1),
      });
      message.success('商品图片已确认');
      setListingImageDirty(false);
      await fetchDetail();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '主图/副图保存失败');
    } finally {
      setImageOrderSaving(false);
      setImageDragPayload(null);
    }
  };

  const resetListingImageDraft = () => {
    setListingImageDraftPaths(listingImagePathsFromImages(images));
    setListingImageDirty(false);
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
    setDraftListingImagePaths([...nextPaths.filter((itemPath) => itemPath !== path), path]);
  };

  const removeListingImageFromSelected = (path: string | null | undefined) => {
    if (imageOrderSaving || !path) return;
    const nextPaths = selectedListingImages
      .map((item: any) => item?.path)
      .filter((itemPath) => itemPath && itemPath !== path);
    setDraftListingImagePaths(nextPaths);
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
    try {
      await updateProduct(product.id, {
        categories: selected.categories,
        leaf_category: selected.leaf_category,
      });
      message.success('类目已保存');
      setCategoryEditOpen(false);
      await fetchDetail();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '类目保存失败');
    } finally {
      setCategorySaving(false);
    }
  };

  const openListingEditor = () => {
    setListingTitleInput(data?.listing_title || '');
    setListingBulletsInput(parseJson(data?.listing_bullets, []).join('\n'));
    setListingDescriptionInput(data?.listing_description || '');
    setListingSearchTermsInput(data?.listing_search_terms || '');
    setListingTitleZhInput(data?.listing_title_zh || '');
    setListingBulletsZhInput(parseJson(data?.listing_bullets_zh, []).join('\n'));
    setListingDescriptionZhInput(data?.listing_description_zh || '');
    setListingSearchTermsZhInput(data?.listing_search_terms_zh || '');
    setListingPrimaryKeywordInput((data?.listing_primary_keyword as string) || '');
    setListingEditOpen(true);
  };

  const saveListing = async () => {
    if (!listingTitleInput.trim()) {
      message.warning('请填写标题');
      return;
    }
    setListingSaving(true);
    try {
      await updateProduct(product.id, {
        listing_title: listingTitleInput.trim(),
        listing_bullets: listingBulletsInput,
        listing_description: listingDescriptionInput.trim(),
        listing_search_terms: listingSearchTermsInput.trim(),
        listing_title_zh: listingTitleZhInput.trim(),
        listing_bullets_zh: listingBulletsZhInput,
        listing_description_zh: listingDescriptionZhInput.trim(),
        listing_search_terms_zh: listingSearchTermsZhInput.trim(),
        listing_primary_keyword: listingPrimaryKeywordInput.trim(),
      });
      message.success('Listing 已保存');
      setListingEditOpen(false);
      await fetchDetail();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Listing 保存失败');
    } finally {
      setListingSaving(false);
    }
  };

  const doRestart = async () => {
    setRestartLoading(true);
    try {
      await restartPipeline(product.id);
      await fetchDetail();
      message.success('已重新开始');
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '重新开始失败');
    } finally {
      setRestartLoading(false);
    }
  };

  const packageColumns = [
    { title: '外包装商品', dataIndex: 'code', width: 180, render: (v) => v || '-' },
    { title: '数量', dataIndex: 'qty', width: 90, render: (v) => v || '-' },
    { title: '长', dataIndex: 'length', width: 90, render: (v) => numberText(v) },
    { title: '宽', dataIndex: 'width', width: 90, render: (v) => numberText(v) },
    { title: '高', dataIndex: 'height', width: 90, render: (v) => numberText(v) },
    { title: '重量', dataIndex: 'weight_value', width: 100, render: (v, record) => numberText(v ?? record.weight) },
    { title: '原始文本', dataIndex: 'dimensions', render: (v, record) => v || record.weight || '-' },
  ];

  const zipColumns = [
    {
      title: '压缩包',
      dataIndex: 'name',
      render: (name, record) => (
        <Button type="link" icon={<FileZipOutlined />} onClick={() => openPath(record.path)} style={{ padding: 0 }}>
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
          <Button size="small" icon={<InboxOutlined />} onClick={() => extractZip(record.path)}>解压</Button>
          <Button size="small" icon={<FolderOpenOutlined />} disabled={!record.extracted_exists} onClick={() => openPath(record.extracted_dir)}>文件夹</Button>
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
        <Button size="small" icon={<FileExcelOutlined />} onClick={() => openPath(record.path)}>打开文件</Button>
        <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openPath(record.path, true)}>打开文件夹</Button>
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
              <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openPath(record.path, record.directory)}>打开</Button>
            )}
            {localPath && !record.directory && <Button size="small" onClick={() => openPath(localPath, true)}>文件夹</Button>}
          </Space>
        );
      },
    },
  ];

  const stoppedStatuses = ['failed', 'unavailable', 'source_unavailable'];
  const stepStatus = stoppedStatuses.includes(product.status) ? 'error' : ['completed', 'pending_review'].includes(product.status) ? 'finish' : 'process';
  const isStopped = stoppedStatuses.includes(product.status);
  const isPaused = product.status === 'paused';
  const isReadyToExport = ['completed', 'pending_review'].includes(product.status) && product.current_step >= 9;
  const stylesnapSearch = rawSnapshot?.stylesnap_search || {};
  const stylesnapSearchStatus = stylesnapSearch?.status || '';
  const competitorCandidateCount = competitorGroup?.candidates?.length || Number(stylesnapSearch?.count || 0);
  const referenceAsin = selectedStyleSnap?.asin || product.competitor_asin || '';
  const hasConfirmedSearchImage = Boolean(
    images?.main_image_path
    || selectedStyleSnap?.source_image_path
  );
  const hasReferenceCompetitor = Boolean(referenceAsin);
  const isCompetitorSearching = product.status === 'competitor_searching';
  const isCompetitorSearchFailed = Boolean(
    stylesnapSearchStatus === 'failed'
    || (product.status === 'failed' && /同款搜索|StyleSnap/i.test(product.error_message || ''))
  );
  const hasCompetitorCandidates = Boolean(
    competitorCandidateCount > 0
    && !isCompetitorSearching
    && !isCompetitorSearchFailed
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
  const listingCaptureErrorPattern = /竞品详情|竞品 Listing|Amazon Listing 详情|Amazon Listing 抓取|抓取选中竞品|选中竞品.*抓取|Amazon.*详情抓取/i;
  const isImageAnalysisPrerequisiteFailed = Boolean(
    product.status === 'failed'
    && /图片分析节点未完成|不能进入 Listing 文案/.test(product.error_message || '')
  );
  const isListingCaptureFailed = Boolean(
    amazonListingCapture?.status === 'failed'
    || (
      product.status === 'failed'
      && !isImageAnalysisPrerequisiteFailed
      && listingCaptureErrorPattern.test(product.error_message || '')
    )
  );
  const isImageAnalysisFailed = Boolean(
    isImageAnalysisPrerequisiteFailed
    || (
      product.status === 'failed'
      && failedStep === 5
      && !isListingCaptureFailed
    )
  );
  const isHardStopped = isStopped && !isCompetitorSearchFailed && !isListingCaptureFailed && !isImageAnalysisFailed;
  const isListingCaptureRunning = Boolean(
    product.status === 'step5_listing'
    && /竞品.*抓取中|Listing.*抓取中/i.test(product.error_message || '')
  );
  const showTopProductError = Boolean(
    productErrorMessage
    && !isListingCaptureFailed
    && !isListingCaptureRunning
  );
  const hasListingCapture = Boolean(
    amazonListingCapture?.status === 'captured'
    || (amazonListingCapture?.title && amazonListingCapture?.status !== 'failed')
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
    || contactSheets.length
    || product.current_step > 5
    || isReadyToExport
  );
  const hasAplusOutput = Boolean(
    aplus?.aplus_status === 'done'
    || aplus?.aplus_status === 'regen_done'
    || product.current_step >= 9
    || (Array.isArray(aplusGeneratedImages) && aplusGeneratedImages.length)
  );
  const aplusProgressText = [
    aplusPlanReady ? '规划已完成' : '待规划',
    aplusScriptReady ? '脚本已完成' : '待脚本',
    aplusImageDoneCount ? `出图 ${aplusImageDoneCount}/5` : '待出图',
  ].join('，');
  const statusSuffix = isPaused ? '，已挂起' : '';
  const nodeErrorAt = (node: string) => {
    if (isCompetitorSearchFailed) return node === 'find-competitors';
    if (isListingCaptureFailed) return node === 'capture-competitor-detail';
    if (isImageAnalysisFailed) return node === 'image-analysis';
    if (!isStopped) return false;
    const step = failedStep;
    if (node === 'find-competitors') return step <= 2;
    if (node === 'choose-competitor') return step <= 4;
    if (node === 'capture-competitor-detail') return step <= 4;
    if (node === 'image-analysis') return step === 5;
    if (node === 'listing') return step === 6;
    if (node === 'aplus') return step >= 7;
    return false;
  };
  const nodeActiveAt = (node: string) => {
    if (isHardStopped || isReadyToExport) return false;
    const step = Number(product.current_step || 0);
    if (node === 'search-image') return !hasConfirmedSearchImage;
    if (node === 'find-competitors') return isCompetitorSearching || (hasConfirmedSearchImage && !hasReferenceCompetitor && !hasCompetitorCandidates && !isCompetitorSearchFailed);
    if (node === 'choose-competitor') return hasConfirmedSearchImage && !hasReferenceCompetitor && hasCompetitorCandidates;
    if (node === 'capture-competitor-detail') return isListingCaptureRunning || (hasReferenceCompetitor && !hasListingCapture);
    if (node === 'image-analysis') return !isListingCaptureRunning && hasListingCapture && hasListingImages && !hasImageAnalysis;
    if (node === 'listing') return !isListingCaptureRunning && hasReferenceCompetitor && hasListingCapture && hasImageAnalysis && !hasListingContent;
    if (node === 'aplus') return step >= 7 && step <= 9 && !hasAplusOutput;
    if (node === 'export') return ['completed', 'pending_review'].includes(product.status);
    return false;
  };
  const toWorkflowItem = (item: any) => ({
    title: item.title,
    description: item.description,
    status: item.error ? 'error' : item.done ? 'finish' : item.active ? 'process' : 'wait',
  });

  // 商品详情页展示业务节点，不再展示旧的内部技术 Pipeline。
  const pipelineSteps = [
    {
      title: '确认商品图片',
      description: hasConfirmedSearchImage ? `已确认主图和 Listing 图片，已选 ${listingImageCount || 1} 张` : `等待确认主图和 Listing 图片${statusSuffix}`,
      done: hasConfirmedSearchImage || hasReferenceCompetitor || hasListingCapture || product.current_step >= 5,
      active: nodeActiveAt('search-image'),
    },
    {
      title: '搜索候选竞品',
      description: isCompetitorSearchFailed
        ? (stylesnapSearch?.error || product.error_message || 'Amazon 同款搜索失败，可重新搜索候选')
        : isCompetitorSearching
          ? (product.error_message || '正在用主图搜索 Amazon 同款')
        : hasReferenceCompetitor
          ? '已完成候选搜索，可重新搜索候选'
          : hasCompetitorCandidates
            ? `已找到 ${competitorCandidateCount} 个候选；不合适可重新搜索候选`
            : hasConfirmedSearchImage
              ? `等待用主图搜索 Amazon 同款${statusSuffix}`
              : `等待先确认商品图片${statusSuffix}`,
      done: (hasReferenceCompetitor || hasCompetitorCandidates || hasListingCapture) && !isCompetitorSearchFailed && !isCompetitorSearching,
      active: nodeActiveAt('find-competitors'),
      error: nodeErrorAt('find-competitors'),
    },
    {
      title: '选择竞品',
      description: referenceAsin
        ? `已选参考竞品 ${referenceAsin}`
        : hasCompetitorCandidates
          ? `等待从 ${competitorCandidateCount} 个候选中选择一个竞品${statusSuffix}`
          : `等待先搜索候选竞品${statusSuffix}`,
      done: hasReferenceCompetitor,
      active: nodeActiveAt('choose-competitor'),
      error: nodeErrorAt('choose-competitor') && !hasReferenceCompetitor,
    },
    {
      title: '抓取竞品详情',
      description: isListingCaptureFailed
        ? (amazonListingCapture?.capture_error || product.error_message || '竞品详情抓取失败')
        : isListingCaptureRunning
          ? (product.error_message || '正在抓取选中竞品详情')
          : hasListingCapture
            ? '已抓取选中竞品的标题、五点、描述、类目和图片链接'
            : hasReferenceCompetitor
              ? `等待抓取选中竞品详情${statusSuffix}`
              : hasCompetitorCandidates
                ? `等待先选择竞品${statusSuffix}`
                : `等待先搜索并选择竞品${statusSuffix}`,
      done: hasListingCapture && !isListingCaptureFailed && !isListingCaptureRunning,
      active: nodeActiveAt('capture-competitor-detail'),
      error: nodeErrorAt('capture-competitor-detail'),
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
      title: 'Listing文案',
      description: hasListingContent
        ? '标题、五点、描述已生成'
        : hasListingCapture
          ? `竞品详情已抓取，等待结合图片分析生成文案${statusSuffix}`
          : `等待竞品详情抓取完成${statusSuffix}`,
      done: hasListingContent || product.current_step > 6 || isReadyToExport,
      active: nodeActiveAt('listing'),
      error: nodeErrorAt('listing'),
    },
    {
      title: 'A+规划/脚本/出图',
      description: `${aplusProgressText}${isAplusRegenerating && aplusStatus ? `，${aplusStatus.text}` : statusSuffix}`,
      done: hasAplusOutput || isReadyToExport,
      active: nodeActiveAt('aplus') || isAplusRegenerating,
      error: nodeErrorAt('aplus') || canRetryAplusRegeneration,
    },
    {
      title: '待导出',
      description: isReadyToExport ? '已具备导出条件' : '等待生成结果通过复核',
      done: isReadyToExport,
      active: nodeActiveAt('export'),
    },
  ].map(toWorkflowItem);

  const currentStepIndex = (() => {
    const activeIndex = pipelineSteps.findIndex((item) => item.status === 'process' || item.status === 'error');
    if (activeIndex >= 0) return activeIndex;
    const firstWaitingIndex = pipelineSteps.findIndex((item) => item.status === 'wait');
    if (firstWaitingIndex >= 0) return firstWaitingIndex;
    return pipelineSteps.length - 1;
  })();

  const isPipelineRunning = !['completed', 'pending_review', 'failed', 'unavailable', 'source_unavailable', 'created', 'paused'].includes(product.status);
  const canSuspendProduct = product.status !== 'paused'
    && !['completed', 'unavailable', 'source_unavailable'].includes(product.status)
    && !(product.status === 'pending_review' && product.current_step >= 9);
  const hasRestartableDownstreamState = Boolean(
    product.current_step > 0
    || hasReferenceCompetitor
    || hasCompetitorCandidates
    || hasListingCapture
    || hasImageAnalysis
    || hasListingContent
    || hasAplusOutput
    || visibleGeneratedFiles.length
  );
  const canRestartProduct = !isPipelineRunning
    && !['unavailable', 'source_unavailable'].includes(product.status)
    && hasRestartableDownstreamState;
  const canOperateCompetitor = product.status !== 'completed'
    && !isListingCaptureRunning
    && (!isPipelineRunning || isListingCaptureFailed);
  const canSwitchCompetitor = canOperateCompetitor;
  const competitorCandidateActionDisabled = Boolean(selectingCompetitorId)
    || !canSwitchCompetitor
    || isCompetitorSearching
    || isListingCaptureRunning;
  const competitorCandidateButtonText = (selected: boolean) => {
    if (isListingCaptureRunning && selected) return '抓取中';
    return selected ? '重新抓详情' : '选择并抓详情';
  };
  const shouldForceCompetitorSearch = Boolean(hasCompetitorCandidates || isCompetitorSearchFailed || hasReferenceCompetitor);
  const competitorSearchButtonText = shouldForceCompetitorSearch ? '重新搜索候选' : '搜索候选';

  // 安全解析JSON
  const tabItems = [
    {
      key: 'basic',
      label: '📋 基本信息',
      children: (
        <div>
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
                      <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openPath(data.material_dir)}>打开</Button>
                      <Button size="small" icon={<CopyOutlined />} onClick={() => copyText(data.material_dir)}>复制</Button>
                    </Space>
                  ) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="视频素材">
                  {videoFolder?.exists ? (
                    <Space wrap>
                      <Tag color="processing">{videoFolder.file_count} 个视频</Tag>
                      <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openPath(videoFolder.path)}>打开</Button>
                      <Button size="small" icon={<CopyOutlined />} onClick={() => copyText(videoFolder.path)}>复制</Button>
                    </Space>
                  ) : <Text type="secondary">暂无</Text>}
                </Descriptions.Item>
                <Descriptions.Item label="A+图片" span="filled">
                  {aplusFolder?.exists ? (
                    <Space wrap>
                      <Tag color="success">{aplusFolder.file_count} 张</Tag>
                      <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openPath(aplusFolder.path)}>打开</Button>
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
                  <Descriptions.Item label="净收入">{money(pricingDetail.net_revenue)}</Descriptions.Item>
                  <Descriptions.Item label="变动费用">{money(pricingDetail.variable_fee)}</Descriptions.Item>
                  <Descriptions.Item label="固定成本">{money(pricingDetail.fixed_cost)}</Descriptions.Item>
                  <Descriptions.Item label="退货抵扣">{money(pricingDetail.return_credit)}</Descriptions.Item>
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
              {isListingCaptureFailed && (
                <Alert
                  type="error"
                  showIcon
                  message="竞品详情抓取失败"
                  description={amazonListingCapture?.capture_error || product.error_message || '可以重新抓取当前竞品，或在下方候选中切换其它竞品。'}
                  action={
                    <Button
                      size="small"
                      danger
                      icon={<RedoOutlined />}
                      loading={Boolean(selectingCompetitorId)}
                      disabled={isListingCaptureRunning || isCompetitorSearching || isPipelineRunning}
                      onClick={retrySelectedCompetitorCapture}
                    >
                      重新抓取当前竞品
                    </Button>
                  }
                />
              )}
              <div>
                <Text type="secondary">Amazon标题</Text>
                <Typography.Paragraph
                  style={{ marginBottom: 0, marginTop: 4 }}
                  ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
                >
                  {amazonListingCapture?.title || '-'}
                </Typography.Paragraph>
              </div>
              <Descriptions bordered column={{ xs: 1, sm: 1, md: 2 }} size="small">
                <Descriptions.Item label="选中 ASIN">
                  {selectedStyleSnap?.url || product.competitor_asin ? (
                    <Space size={8}>
                      <Typography.Link href={selectedStyleSnap?.url || `https://www.amazon.com/dp/${product.competitor_asin}`} target="_blank">
                        {selectedStyleSnap?.asin || product.competitor_asin}
                      </Typography.Link>
                      <Button size="small" icon={<CopyOutlined />} onClick={() => copyText(selectedStyleSnap?.asin || product.competitor_asin)}>复制</Button>
                    </Space>
                  ) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="抽卡排名">{selectedStyleSnap?.rank ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="Amazon品牌">{amazonListingCapture?.brand || '-'}</Descriptions.Item>
                <Descriptions.Item label="卖家">{amazonListingCapture?.seller || '-'}</Descriptions.Item>
                <Descriptions.Item label="Amazon价格">{amazonListingCapture?.price || '-'}</Descriptions.Item>
                <Descriptions.Item label="评分/评论">
                  {[amazonListingCapture?.rating, amazonListingCapture?.review_count ? `${amazonListingCapture.review_count} reviews` : null].filter(Boolean).join(' / ') || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="可售状态">{amazonListingCapture?.availability || '-'}</Descriptions.Item>
                <Descriptions.Item label="Amazon主图">
                  {amazonListingCapture?.main_image_url ? (
                    <Image
                      src={amazonListingCapture.main_image_url}
                      width={72}
                      height={72}
                      style={{ objectFit: 'cover', borderRadius: 4, border: '1px solid #f0f0f0' }}
                      preview={{ src: amazonListingCapture.main_image_url }}
                    />
                  ) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="类目排名" span="filled">
                  <Typography.Paragraph style={{ marginBottom: 0 }} ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}>
                    {amazonListingCapture?.category_rank || selectedStyleSnap?.category_rank || '-'}
                  </Typography.Paragraph>
                </Descriptions.Item>
              </Descriptions>
              <div>
                <Text type="secondary">竞品五点</Text>
                {amazonCompetitorBullets.length ? (
                  <List
                    size="small"
                    dataSource={amazonCompetitorBullets.slice(0, 5)}
                    renderItem={(item: string) => (
                      <List.Item style={{ paddingLeft: 0, paddingRight: 0 }}>
                        <Typography.Paragraph style={{ marginBottom: 0 }} copyable>
                          {item}
                        </Typography.Paragraph>
                      </List.Item>
                    )}
                  />
                ) : <Text type="secondary"> 未抓到竞品五点</Text>}
              </div>
            </Space>
          </Card>

          <Card
            title={`候选竞品${competitorCandidateCount ? `（${competitorCandidateCount} 个）` : ''}`}
            size="small"
            extra={
              <Button
                size="small"
                icon={shouldForceCompetitorSearch ? <ReloadOutlined /> : <PlayCircleOutlined />}
                loading={competitorSearchLoading || isCompetitorSearching}
                disabled={!hasConfirmedSearchImage || !canOperateCompetitor || isHardStopped || isReadyToExport}
                onClick={() => searchCompetitorCandidates(shouldForceCompetitorSearch)}
              >
                {competitorSearchButtonText}
              </Button>
            }
          >
            <Spin spinning={competitorLoading}>
              {competitorGroup ? (
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  {isCompetitorSearching && (
                    <Alert
                      type="info"
                      showIcon
                      message="正在追加搜索候选"
                      description="原有候选会保留在页面上；新一轮搜索完成后会追加到列表末尾。"
                    />
                  )}
                  {hasListingContent && (
                    <Alert
                      type="warning"
                      showIcon
                      message="切换竞品后要重走后续流程"
                      description="切换后会记录新的 ASIN、Amazon 类目，并重新抓取竞品详情。当前商品后续的 Listing 文案、图片分析、A+ 需要重新生成。"
                    />
                  )}
                  <div style={{ display: 'grid', gridTemplateColumns: '180px minmax(0, 1fr)', gap: 16 }}>
                    <div>
                      <div
                        style={{
                          height: 180,
                          border: '1px solid #e5e7eb',
                          borderRadius: 8,
                          background: '#f8fafc',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          overflow: 'hidden',
                          marginBottom: 10,
                        }}
                      >
                        {(competitorGroup.source_image_path || competitorGroup.source_image_url) ? (
                          <Image
                            src={competitorGroup.source_image_path ? imgUrl(competitorGroup.source_image_path) : competitorGroup.source_image_url || ''}
                            height={178}
                            style={{ objectFit: 'contain' }}
                            preview={{ src: competitorGroup.source_image_path ? imgUrl(competitorGroup.source_image_path) : competitorGroup.source_image_url || '' }}
                          />
                        ) : (
                          <Text type="secondary">无源图</Text>
                        )}
                      </div>
                      <Space direction="vertical" size={6} style={{ width: '100%' }}>
                        <Text strong>{competitorGroup.product_name || competitorGroup.item_code}</Text>
                        <Text type="secondary">SKU：{competitorGroup.sku_code || '-'}</Text>
                        <Text type="secondary">{competitorGroup.task_ready_reason || '从候选中选择一个 Item 级参考竞品'}</Text>
                      </Space>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(185px, 1fr))', gap: 12 }}>
                      {competitorGroup.candidates.map((candidate: any) => {
                        const selected = competitorGroup.selected_candidate_id === candidate.id || candidate.is_selected === 1;
                        return (
                          <div
                            key={candidate.id}
                            style={{
                              border: selected ? '2px solid #16a34a' : '1px solid #d9e1ec',
                              background: selected ? '#f0fdf4' : '#fff',
                              borderRadius: 8,
                              padding: 10,
                              minHeight: 340,
                              display: 'flex',
                              flexDirection: 'column',
                              gap: 8,
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6, alignItems: 'center' }}>
                              <Space size={4}>
                                <Tag color={selected ? 'success' : 'blue'}>#{candidate.rank}</Tag>
                                <Text strong>{candidate.asin}</Text>
                              </Space>
                              {selected ? <Tag color="success">已选</Tag> : null}
                            </div>
                            <div
                              style={{
                                height: 110,
                                borderRadius: 6,
                                background: '#f5f7fb',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                overflow: 'hidden',
                              }}
                            >
                              {candidate.amazon_image_url ? (
                                <Image
                                  src={candidate.amazon_image_url}
                                  height={110}
                                  style={{ objectFit: 'contain' }}
                                  preview={{ src: candidate.amazon_image_url }}
                                />
                              ) : (
                                <Text type="secondary">{candidate.asin}</Text>
                              )}
                            </div>
                            <Space size={[4, 4]} wrap>
                              <Tag>{valueText(candidate.brand)}</Tag>
                              <Tag color={candidate.seller === 'Amazon' ? 'green' : 'default'}>{valueText(candidate.seller)}</Tag>
                              {candidate.price ? <Tag color="gold">{candidate.price}</Tag> : null}
                            </Space>
                            <div style={{ display: 'grid', gap: 4, fontSize: 12 }}>
                              <Text type="secondary">评分：{valueText(candidate.rating)}</Text>
                              <Text type="secondary">类目：{valueText(candidate.category_rank)}</Text>
                              {(candidate.color || candidate.size || candidate.style) ? (
                                <Text type="secondary">
                                  变体：{[candidate.color, candidate.size, candidate.style].filter(Boolean).join(' / ')}
                                </Text>
                              ) : null}
                              {captureStatusTag(candidate.listing_capture_status)}
                            </div>
                            <Typography.Paragraph
                              type="secondary"
                              ellipsis={{ rows: 3, expandable: false }}
                              style={{ fontSize: 12, margin: 0, minHeight: 54 }}
                            >
                              {candidate.raw_snippet || ''}
                            </Typography.Paragraph>
                            <div style={{ marginTop: 'auto', display: 'flex', gap: 8 }}>
                              <Button
                                type={selected ? 'primary' : 'default'}
                                icon={<CheckOutlined />}
                                loading={selectingCompetitorId === candidate.id}
                                disabled={competitorCandidateActionDisabled}
                                onClick={() => chooseCompetitorCandidate(candidate)}
                                block
                              >
                                {competitorCandidateButtonText(selected)}
                              </Button>
                              <Button
                                icon={<ExportOutlined />}
                                href={candidate.url || `https://www.amazon.com/dp/${candidate.asin}`}
                                target="_blank"
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </Space>
              ) : (
                <Empty description={
                  isCompetitorSearching
                    ? '正在用主图搜索 Amazon 同款'
                    : competitorLoading
                      ? '正在加载候选竞品'
                      : isCompetitorSearchFailed
                        ? (stylesnapSearch?.error || productErrorMessage || '候选竞品搜索失败，请重新搜索')
                      : hasCompetitorCandidates
                        ? '候选已生成，加载候选列表'
                        : '暂无候选竞品'
                }>
                  {hasCompetitorCandidates ? (
                    <Button
                      icon={<ReloadOutlined />}
                      loading={competitorLoading}
                      onClick={() => loadCompetitorCandidates()}
                    >
                      加载候选列表
                    </Button>
                  ) : (
                    <Button
                      type="primary"
                      icon={<PlayCircleOutlined />}
                      loading={competitorSearchLoading || isCompetitorSearching}
                      disabled={!hasConfirmedSearchImage || !canOperateCompetitor || isHardStopped || isReadyToExport}
                      onClick={() => searchCompetitorCandidates(shouldForceCompetitorSearch)}
                    >
                      {competitorSearchButtonText}
                    </Button>
                  )}
                </Empty>
              )}
            </Spin>
          </Card>
        </div>
      ),
    },
    {
      key: 'listing',
      label: '📝 Listing文案',
      children: (
        <div>
          <Card
            title="标题"
            size="small"
            style={{ marginBottom: 12 }}
            extra={<Button size="small" onClick={openListingEditor}>编辑 Listing</Button>}
          >
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text>{data?.listing_title || '（未生成）'}</Text>
              {data?.listing_title_zh && <Text type="secondary">中文：{data.listing_title_zh}</Text>}
            </Space>
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
                    <Text type="secondary" style={{ fontSize: 12 }}>第一张为主图，其余为副图</Text>
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
                              onDoubleClick={() => removeListingImageFromSelected(item.path)}
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
                        <Text type="secondary">把未选图片拖到这里，或双击未选图片作为主图/副图</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>至少保留一张主图后才能保存</Text>
                      </Space>
                    )}
                  </div>
                </div>

                <div>
                  <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 8 }}>
                    <Text strong>未选图片</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>拖回这里或双击已使用图片表示不使用</Text>
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
                            onDoubleClick={() => addListingImageFromPool(item.path)}
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
                        <Text type="secondary">全部图片都已使用</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>把上方图片拖到这里，或双击已使用图片即可移出使用区</Text>
                      </Space>
                    )}
                  </div>
                </div>
              </Space>
            </Spin>
          </Card>
          <Card title="Contact Sheet 与分析" size="small" style={{ marginTop: 12 }}>
            {reviewsBySheet.length ? (
              <Space direction="vertical" style={{ width: '100%' }} size={16}>
                {reviewsBySheet.map((sheet) => (
                  <Card
                    key={sheet.sheet_path}
                    size="small"
                    title={`Contact Sheet ${sheet.sheet_page || ''}`}
                    extra={<Button size="small" icon={<FolderOpenOutlined />} onClick={() => openPath(sheet.sheet_path)}>打开</Button>}
                  >
                    <Image src={imgUrl(sheet.sheet_path)} width={360} alt={`Contact Sheet ${sheet.sheet_page || ''}`} style={{ marginBottom: 12 }} />
                    <Table
                      size="small"
                      rowKey={(record) => record.image_id || record.filename}
                      dataSource={sheet.reviews || []}
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
                    />
                  </Card>
                ))}
              </Space>
            ) : <Text type="secondary">（未生成 Contact Sheet 分析）</Text>}
          </Card>
        </div>
      ),
    },
    {
      key: 'aplus',
      label: '🎨 A+内容',
      children: (
        <div>
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
          <Button icon={<ReloadOutlined />} onClick={fetchDetail}>刷新</Button>
          {product.status === 'failed' && !isLegacyGigaBrowserCollectError && (
            <Button icon={<RedoOutlined />} onClick={async () => { await retryStep(product.id); fetchDetail(); }}>
              重试
            </Button>
          )}
          {product.status === 'paused' && (
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={async () => { await resumePipeline(product.id); fetchDetail(); }}>
              继续
            </Button>
          )}
          {product.status === 'pending_review' && product.current_step < 9 && (
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={async () => { await resumePipeline(product.id); fetchDetail(); }}>
              继续
            </Button>
          )}
          {product.status === 'pending_review' && product.current_step >= 9 && (
            <Popconfirm
              title="确认加入待导出？"
              description={isAplusRegenerating ? 'A+重新生成还在进行中，完成后才能确认。' : '确认后，这个 Item 会进入待导出，后续在导出中心批量生成 Excel。'}
              okText="加入待导出"
              cancelText="再看看"
              disabled={isAplusRegenerating}
              onConfirm={async () => { await confirmProduct(product.id); message.success('已加入待导出'); fetchDetail(); }}
            >
              <Button type="primary" icon={<CheckOutlined />} disabled={isAplusRegenerating}>加入待导出</Button>
            </Popconfirm>
          )}
          {canRetryAplusRegeneration && (
            <Button icon={<RedoOutlined />} loading={regenRetryLoading} onClick={retryInterruptedAplus}>
              重试A+重新生图
            </Button>
          )}
          {isPipelineRunning && (
            <Button icon={<PauseOutlined />} onClick={async () => { await pausePipeline(product.id); fetchDetail(); }}>
              挂起
            </Button>
          )}
          {canSuspendProduct && !isPipelineRunning && (
            <Popconfirm
              title="挂起这个商品？"
              description="挂起后不会继续执行后续自动流程，之后可以点继续恢复。"
              okText="挂起"
              cancelText="取消"
              onConfirm={async () => { await pausePipeline(product.id); fetchDetail(); }}
            >
              <Button icon={<PauseOutlined />}>挂起</Button>
            </Popconfirm>
          )}
          {canRestartProduct && (
            <Popconfirm
              title="确定重新开始流程？"
              description="会保留已使用图片，清空旧候选竞品、已选竞品、Listing、图片分析、A+ 和生成文件；有主图时会重新搜索候选竞品。"
              okText="重新开始"
              cancelText="取消"
              onConfirm={() => doRestart()}
            >
              <Button icon={<RedoOutlined />}>重新开始流程</Button>
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
          current={isReadyToExport ? pipelineSteps.length : currentStepIndex}
          status={stepStatus}
          items={pipelineSteps}
          size="small"
        />
      </Card>

      {/* 状态信息 */}
      {product.status === 'paused' && (
        <Card size="small" style={{ marginBottom: 16, borderColor: '#d9d9d9' }}>
          <Text type="secondary">已挂起：不会继续执行后续自动流程，点击继续后从当前步骤恢复。</Text>
        </Card>
      )}
      {product.status === 'step5_listing' && /竞品.*抓取中|Listing.*抓取中/i.test(product.error_message || '') && (
        <Card size="small" style={{ marginBottom: 16, borderColor: '#1677ff' }}>
          <Text type="secondary">{product.error_message}</Text>
        </Card>
      )}
      {showTopProductError && (
        <Card size="small" style={{ marginBottom: 16, borderColor: '#ff4d4f' }}>
          <Text type="danger">{product.status === 'source_unavailable' ? '原商品下架停止采集：' : '❌ '}{productErrorMessage}</Text>
        </Card>
      )}

      {/* 内容 Tabs */}
      <Tabs
        activeKey={activeTabKey}
        items={tabItems}
        onChange={(key) => {
          userTouchedTabRef.current = true;
          setActiveTabKey(key);
          if (key === 'competitor' && !competitorGroup && !competitorLoading) {
            loadCompetitorCandidates();
          }
        }}
      />
    </div>
    <Modal
      title={`选择参考竞品${data?.item_code ? `：${data.item_code}` : ''}`}
      open={competitorModalOpen}
      onCancel={() => {
        if (!selectingCompetitorId) {
          setCompetitorModalOpen(false);
        }
      }}
      footer={null}
      width={1180}
      destroyOnHidden
    >
      <Spin spinning={competitorLoading}>
        {competitorGroup ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {hasListingContent && (
              <Alert
                type="warning"
                showIcon
                message="更换竞品后需要重新生成 Listing"
                description="当前商品已经有生成文案。选择新竞品会记录 ASIN、类目并抓取竞品详情，但不会自动覆盖已有文案和 A+，需要手动重跑生成。"
              />
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '180px minmax(0, 1fr)', gap: 16 }}>
              <div>
                <div
                  style={{
                    height: 180,
                    border: '1px solid #e5e7eb',
                    borderRadius: 8,
                    background: '#f8fafc',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    overflow: 'hidden',
                    marginBottom: 10,
                  }}
                >
                  {(competitorGroup.source_image_path || competitorGroup.source_image_url) ? (
                    <Image
                      src={competitorGroup.source_image_path ? imgUrl(competitorGroup.source_image_path) : competitorGroup.source_image_url || ''}
                      height={178}
                      style={{ objectFit: 'contain' }}
                      preview={{ src: competitorGroup.source_image_path ? imgUrl(competitorGroup.source_image_path) : competitorGroup.source_image_url || '' }}
                    />
                  ) : (
                    <Text type="secondary">无源图</Text>
                  )}
                </div>
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  <Text strong>{competitorGroup.product_name || competitorGroup.item_code}</Text>
                  <Text type="secondary">SKU：{competitorGroup.sku_code || '-'}</Text>
                  <Text type="secondary">{competitorGroup.task_ready_reason || '从候选中选择一个 Item 级参考竞品'}</Text>
                </Space>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(185px, 1fr))', gap: 12 }}>
                {competitorGroup.candidates.map((candidate: any) => {
                  const selected = competitorGroup.selected_candidate_id === candidate.id || candidate.is_selected === 1;
                  return (
                    <div
                      key={candidate.id}
                      style={{
                        border: selected ? '2px solid #16a34a' : '1px solid #d9e1ec',
                        background: selected ? '#f0fdf4' : '#fff',
                        borderRadius: 8,
                        padding: 10,
                        minHeight: 340,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 8,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6, alignItems: 'center' }}>
                        <Space size={4}>
                          <Tag color={selected ? 'success' : 'blue'}>#{candidate.rank}</Tag>
                          <Text strong>{candidate.asin}</Text>
                        </Space>
                        {selected ? <Tag color="success">已选</Tag> : null}
                      </div>
                      <div
                        style={{
                          height: 110,
                          borderRadius: 6,
                          background: '#f5f7fb',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          overflow: 'hidden',
                        }}
                      >
                        {candidate.amazon_image_url ? (
                          <Image
                            src={candidate.amazon_image_url}
                            height={110}
                            style={{ objectFit: 'contain' }}
                            preview={{ src: candidate.amazon_image_url }}
                          />
                        ) : (
                          <Text type="secondary">{candidate.asin}</Text>
                        )}
                      </div>
                      <Space size={[4, 4]} wrap>
                        <Tag>{valueText(candidate.brand)}</Tag>
                        <Tag color={candidate.seller === 'Amazon' ? 'green' : 'default'}>{valueText(candidate.seller)}</Tag>
                        {candidate.price ? <Tag color="gold">{candidate.price}</Tag> : null}
                      </Space>
                      <div style={{ display: 'grid', gap: 4, fontSize: 12 }}>
                        <Text type="secondary">评分：{valueText(candidate.rating)}</Text>
                        <Text type="secondary">类目：{valueText(candidate.category_rank)}</Text>
                        {(candidate.color || candidate.size || candidate.style) ? (
                          <Text type="secondary">
                            变体：{[candidate.color, candidate.size, candidate.style].filter(Boolean).join(' / ')}
                          </Text>
                        ) : null}
                        {captureStatusTag(candidate.listing_capture_status)}
                      </div>
                      <Typography.Paragraph
                        type="secondary"
                        ellipsis={{ rows: 3, expandable: false }}
                        style={{ fontSize: 12, margin: 0, minHeight: 54 }}
                      >
                        {candidate.raw_snippet || ''}
                      </Typography.Paragraph>
                      <div style={{ marginTop: 'auto', display: 'flex', gap: 8 }}>
                        <Button
                          type={selected ? 'primary' : 'default'}
                          icon={<CheckOutlined />}
                          loading={selectingCompetitorId === candidate.id}
                          disabled={competitorCandidateActionDisabled}
                          onClick={() => chooseCompetitorCandidate(candidate)}
                          block
                        >
                          {competitorCandidateButtonText(selected)}
                        </Button>
                        <Button
                          icon={<ExportOutlined />}
                          href={candidate.url || `https://www.amazon.com/dp/${candidate.asin}`}
                          target="_blank"
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </Space>
        ) : (
          <Empty description={
            competitorLoading
              ? '正在加载候选竞品'
              : isCompetitorSearchFailed
                ? (stylesnapSearch?.error || productErrorMessage || '候选竞品搜索失败，请重新搜索')
                : '暂无候选竞品'
          }>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={competitorSearchLoading || isCompetitorSearching}
              disabled={!hasConfirmedSearchImage || !canOperateCompetitor || isHardStopped || isReadyToExport}
              onClick={() => searchCompetitorCandidates(shouldForceCompetitorSearch)}
            >
              {competitorSearchButtonText}
            </Button>
          </Empty>
        )}
      </Spin>
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
            maxLength={200}
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
