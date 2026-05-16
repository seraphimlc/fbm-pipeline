// @ts-nocheck
import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Alert, Card, Descriptions, Tag, Steps, Tabs, Button, Space, Typography, Spin, message, Popconfirm, Image, Table, List, Modal, Input } from 'antd';
import {
  ArrowLeftOutlined, PlayCircleOutlined, RedoOutlined,
  PauseOutlined, ReloadOutlined, DeleteOutlined,
  FolderOpenOutlined, FileZipOutlined, InboxOutlined, FileExcelOutlined,
  CheckOutlined,
} from '@ant-design/icons';
import { getProduct, startPipeline, restartPipeline, retryStep, resumePipeline, pausePipeline, deleteProduct, openProductFile, extractProductZip, regenerateAplusModule, runPipelineStep, updateProduct, confirmProduct, STEP_LABELS } from '../api';
import type { ProductDetail } from '../api';

const { Title, Text } = Typography;

/** 将本地文件路径转为后端图片代理URL */
const imgUrl = (localPath: string | null | undefined) => {
  if (!localPath) return '';
  return `/api/images/${localPath}`;
};

const parseJson = (value: string | null | undefined, fallback: any = null) => {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
};

const money = (value: number | null | undefined) => value != null ? `$${value}` : '-';
const numberText = (value: number | null | undefined, unit = '') => value != null ? `${value}${unit}` : '-';
const fileSize = (bytes: number | null | undefined) => {
  if (!bytes) return '-';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const ProductDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenTarget, setRegenTarget] = useState<any | null>(null);
  const [regenReason, setRegenReason] = useState('');
  const [regenLoading, setRegenLoading] = useState(false);
  const [restartUpcOpen, setRestartUpcOpen] = useState(false);
  const [restartUpc, setRestartUpc] = useState('');
  const [restartLoading, setRestartLoading] = useState(false);
  const [categoryEditOpen, setCategoryEditOpen] = useState(false);
  const [categoryPathInput, setCategoryPathInput] = useState('');
  const [leafCategoryInput, setLeafCategoryInput] = useState('');
  const [categorySaving, setCategorySaving] = useState(false);
  const [listingEditOpen, setListingEditOpen] = useState(false);
  const [listingTitleInput, setListingTitleInput] = useState('');
  const [listingBulletsInput, setListingBulletsInput] = useState('');
  const [listingSearchTermsInput, setListingSearchTermsInput] = useState('');
  const [listingTitleZhInput, setListingTitleZhInput] = useState('');
  const [listingBulletsZhInput, setListingBulletsZhInput] = useState('');
  const [listingSearchTermsZhInput, setListingSearchTermsZhInput] = useState('');
  const [listingPrimaryKeywordInput, setListingPrimaryKeywordInput] = useState('');
  const [listingSaving, setListingSaving] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDetail = async () => {
    if (!id) return;
    try {
      const { data } = await getProduct(Number(id));
      setProduct(data);
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
    const isRunning = !['completed', 'pending_review', 'failed', 'paused', 'created'].includes(product.status);
    if (isRunning) {
      pollRef.current = setInterval(fetchDetail, 3000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [product?.status]);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  if (!product) return <div>商品不存在</div>;

  const data = product.data;
  const images = product.images;
  const aplus = product.aplus;
  const videoFolder = product.video_folder;
  const aplusFolder = product.aplus_folder;
  const packages = parseJson(data?.packages, []);
  const features = parseJson(data?.features, []);
  const variants = parseJson(data?.variants, []);
  const pricingDetail = parseJson(data?.pricing_detail, null);
  const categories = parseJson(data?.categories, []);
  const categoryPath = Array.isArray(categories) ? categories.join(' > ') : (data?.categories || '');
  const amazonTemplateWarnings = parseJson(data?.amazon_template_warnings, []);
  const amazonTemplateFillSummary = parseJson(data?.amazon_template_fill_summary, null);
  const amazonTemplateRisk = amazonTemplateFillSummary?.risk_level || '';
  const amazonTemplateRiskMap: Record<string, { color: string; label: string }> = {
    pass: { color: 'success', label: '可复核上传' },
    warning: { color: 'warning', label: '需复核' },
    high_risk: { color: 'error', label: '高风险' },
  };
  const amazonTemplateRiskDisplay = amazonTemplateRiskMap[amazonTemplateRisk] || { color: 'default', label: '未检查' };
  const generatedFiles = product.generated_files || [];
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
  const galleryOnlyImages = Array.isArray(galleryImagePaths)
    ? galleryImagePaths.filter((item) => {
      const path = typeof item === 'string' ? item : item?.path;
      return path && path !== images?.main_image_path;
    })
    : [];
  const aplusScriptsPayload = parseJson(aplus?.aplus_scripts, null);
  const aplusScripts = Array.isArray(aplusScriptsPayload?.scripts) ? aplusScriptsPayload.scripts.slice(0, 5) : [];
  const aplusPlanPayload = parseJson(aplus?.aplus_plan, {});
  const aplusPlanModules = Array.isArray(aplusPlanPayload?.modules) ? aplusPlanPayload.modules : [];
  const aplusGeneratedImages = parseJson(aplus?.aplus_images, []);
  const keywordItems = parseJson(data?.keywords_top, []);
  const keywordCopyLine = Array.isArray(keywordItems)
    ? keywordItems
      .map((kw) => typeof kw === 'string' ? kw : kw?.keyword)
      .filter(Boolean)
      .join(' ')
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
  const aplusModules = aplusScripts.map((script) => ({
    script,
    plan: aplusPlanModules.find((item: any) => item?.position === script?.module_position || item?.module_position === script?.module_position) || {},
    references: getModuleReferenceImages(script),
    generated: Array.isArray(aplusGeneratedImages)
      ? aplusGeneratedImages.find((img) => img?.position === script?.module_position)
      : null,
  }));
  const listingCheck = parseJson(data?.listing_check, {});
  const keywordPlan = listingCheck?.keyword_plan || {};
  const positioning = listingCheck?.positioning || {};
  const removedKeywords = parseJson(data?.listing_removed_keywords, []);

  const openPath = async (path?: string, directory = false) => {
    try {
      await openProductFile(product.id, path, directory);
      message.success('已打开');
    } catch {
      message.error('打开失败');
    }
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
      await regenerateAplusModule(product.id, {
        module_position: regenTarget.module_position,
        reason,
      });
      message.success('A+脚本和图片已重新生成');
      setRegenTarget(null);
      setRegenReason('');
      await fetchDetail();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'A+重新生成失败');
    } finally {
      setRegenLoading(false);
    }
  };

  const generateAmazonTemplate = async () => {
    try {
      await runPipelineStep(product.id, 10);
      message.success('导入表格已生成');
      await fetchDetail();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '导入表格生成失败');
    }
  };

  const openCategoryEditor = () => {
    setCategoryPathInput(categoryPath || '');
    setLeafCategoryInput(data?.leaf_category || '');
    setCategoryEditOpen(true);
  };

  const saveCategory = async () => {
    const path = categoryPathInput.trim();
    const leaf = leafCategoryInput.trim();
    if (!path && !leaf) {
      message.warning('请填写 Amazon 类目或叶子类目');
      return;
    }
    setCategorySaving(true);
    try {
      await updateProduct(product.id, {
        categories: path,
        leaf_category: leaf || undefined,
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
    setListingSearchTermsInput(data?.listing_search_terms || '');
    setListingTitleZhInput(data?.listing_title_zh || '');
    setListingBulletsZhInput(parseJson(data?.listing_bullets_zh, []).join('\n'));
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
        listing_search_terms: listingSearchTermsInput.trim(),
        listing_title_zh: listingTitleZhInput.trim(),
        listing_bullets_zh: listingBulletsZhInput,
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

  const doRestart = async (upcOverride?: string) => {
    const nextUpc = (upcOverride ?? product.upc ?? '').trim();
    if (!nextUpc) {
      setRestartUpc(product.upc || '');
      setRestartUpcOpen(true);
      return;
    }
    setRestartLoading(true);
    try {
      if (nextUpc !== (product.upc || '').trim()) {
        await updateProduct(product.id, { upc: nextUpc });
      }
      await restartPipeline(product.id);
      setRestartUpcOpen(false);
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
    { title: '外包装尺寸/重量', dataIndex: 'dimensions', render: (v, record) => v || record.weight || '-' },
    { title: '重量', dataIndex: 'weight', width: 140, render: (v) => v || '-' },
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
    { title: '操作', width: 220, render: (_, record) => (
      <Space size="small">
        <Button size="small" icon={<FileExcelOutlined />} onClick={() => openPath(record.path)}>打开文件</Button>
        <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openPath(record.path, true)}>打开文件夹</Button>
      </Space>
    ) },
  ];

  // Pipeline Steps
  const pipelineSteps = [
    { title: '采集', description: STEP_LABELS[1] },
    { title: '计算', description: STEP_LABELS[2] },
    { title: '关键词+类目', description: `${STEP_LABELS[3]} & ${STEP_LABELS[4]}` },
    { title: 'Listing', description: STEP_LABELS[5] },
    { title: '主图', description: STEP_LABELS[6] },
    { title: 'A+规划', description: STEP_LABELS[7] },
    { title: 'A+脚本', description: STEP_LABELS[8] },
    { title: 'A+出图', description: STEP_LABELS[9] },
    { title: '导入表格', description: STEP_LABELS[10] },
  ];

  // 当前步骤映射到 Steps 组件的 index
  const currentStepIndex = (() => {
    const s = product.current_step;
    if (s <= 1) return 0;
    if (s === 2) return 1;
    if (s <= 4) return 2;
    if (s === 5) return 3;
    if (s === 6) return 4;
    if (s === 7) return 5;
    if (s === 8) return 6;
    if (s === 9) return 7;
    if (s === 10) return 8;
    return 8; // completed
  })();

  const stepStatus = ['failed', 'unavailable'].includes(product.status) ? 'error' : ['completed', 'pending_review'].includes(product.status) ? 'finish' : 'process';
  const isPipelineRunning = !['completed', 'pending_review', 'failed', 'unavailable', 'created', 'paused'].includes(product.status);

  // 安全解析JSON
  const tabItems = [
    {
      key: 'basic',
      label: '📋 基本信息',
      children: (
        <div>
          <Descriptions bordered column={2} size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="来源商品ID">{product.source_item_id || product.gigab2b_product_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="商品Code">{data?.item_code || '-'}</Descriptions.Item>
            <Descriptions.Item label="原始数据链接" span={2}>
              {product.source_url || product.gigab2b_url ? (
                <Typography.Link href={product.source_url || product.gigab2b_url} target="_blank" copyable>
                  {product.source_url || product.gigab2b_url}
                </Typography.Link>
              ) : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="竞品 ASIN">{product.competitor_asin || '-'}</Descriptions.Item>
            <Descriptions.Item label="真实 ASIN">{product.amazon_asin || '-'}</Descriptions.Item>
            <Descriptions.Item label="UPC">{product.upc || '-'}</Descriptions.Item>
            <Descriptions.Item label="ASIN同步状态">
              {product.amazon_asin ? <Tag color="success">已同步</Tag> : product.asin_sync_status === 'not_found' ? <Tag color="warning">未查到</Tag> : product.asin_sync_status === 'failed' ? <Tag color="error">失败</Tag> : product.asin_sync_status === 'pending' || product.asin_sync_status === 'running' ? <Tag color="processing">同步中</Tag> : <Tag>未同步</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="品牌">{product.brand || '-'}</Descriptions.Item>
            {product.asin_sync_error && <Descriptions.Item label="ASIN同步信息" span={2}>{product.asin_sync_error}</Descriptions.Item>}
            <Descriptions.Item label="Amazon类目" span={2}>
              <Space>
                <span>{categoryPath || '-'}</span>
                <Button size="small" onClick={openCategoryEditor}>编辑类目</Button>
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="叶子类目">{data?.leaf_category || '-'}</Descriptions.Item>
            <Descriptions.Item label="标题" span={2}>{data?.title || '-'}</Descriptions.Item>
            <Descriptions.Item label="颜色">{data?.color || '-'}</Descriptions.Item>
            <Descriptions.Item label="材质">{data?.material || '-'}</Descriptions.Item>
            <Descriptions.Item label="填充物">{data?.filler || '-'}</Descriptions.Item>
            <Descriptions.Item label="产品类型">{data?.product_type || '-'}</Descriptions.Item>
            <Descriptions.Item label="组装尺寸">{data ? `${numberText(data.dimension_length)} × ${numberText(data.dimension_width)} × ${numberText(data.dimension_height)} 英寸` : '-'}</Descriptions.Item>
            <Descriptions.Item label="产品重量">{numberText(data?.weight, ' 磅')}</Descriptions.Item>
            <Descriptions.Item label="货值">{money(data?.value_total)}</Descriptions.Item>
            <Descriptions.Item label="含运费成本">{money(data?.estimated_total)}</Descriptions.Item>
            <Descriptions.Item label="一件代发物流费">{money(data?.shipping_cost)}</Descriptions.Item>
            <Descriptions.Item label="云送仓物流费">{data?.shipping_cost_min != null || data?.shipping_cost_max != null ? `${money(data?.shipping_cost_min)} - ${money(data?.shipping_cost_max)}` : '-'}</Descriptions.Item>
            <Descriptions.Item label="建议售价">{money(data?.suggested_price)}</Descriptions.Item>
            <Descriptions.Item label="总成本">{money(data?.cost_total)}</Descriptions.Item>
            <Descriptions.Item label="利润">{money(data?.profit)}</Descriptions.Item>
            <Descriptions.Item label="净利率">{data?.profit_rate != null ? `${data.profit_rate.toFixed(1)}%` : '-'}</Descriptions.Item>
            {pricingDetail && (
              <>
                <Descriptions.Item label="定价依据">
                  {pricingDetail.selected_rule === 'target_margin' ? '目标净利率' : '最低利润'}
                </Descriptions.Item>
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
            <Descriptions.Item label="库存">{data?.stock ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="供应商">{data?.seller || '-'}</Descriptions.Item>
            <Descriptions.Item label="产地">{data?.origin || '-'}</Descriptions.Item>
            <Descriptions.Item label="图片数量">{data?.image_count ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="采集时间">{data?.collected_at ? new Date(data.collected_at).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
            <Descriptions.Item label="素材目录" span={2}>
              <Space>
                <Text copyable>{data?.material_dir || '-'}</Text>
                {data?.material_dir && <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openPath(data.material_dir)}>打开</Button>}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="视频素材" span={2}>
              {videoFolder?.exists ? (
                <Space wrap>
                  <Text copyable>{videoFolder.path}</Text>
                  <Tag color="processing">{videoFolder.file_count} 个视频</Tag>
                  <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openPath(videoFolder.path)}>打开</Button>
                </Space>
              ) : <Text type="secondary">暂无视频素材</Text>}
            </Descriptions.Item>
            <Descriptions.Item label="new a plus" span={2}>
              {aplusFolder?.exists ? (
                <Space wrap>
                  <Text copyable>{aplusFolder.path}</Text>
                  <Tag color="success">{aplusFolder.file_count} 张图片</Tag>
                  <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openPath(aplusFolder.path)}>打开</Button>
                </Space>
              ) : <Text type="secondary">尚未生成 A+ 图片</Text>}
            </Descriptions.Item>
            <Descriptions.Item label="大健描述" span={2}>{data?.description || '-'}</Descriptions.Item>
          </Descriptions>

          <Card title="外包装信息" size="small" style={{ marginBottom: 16 }}>
            <Table
              size="small"
              columns={packageColumns}
              dataSource={Array.isArray(packages) ? packages : []}
              rowKey={(record, index) => `${record.code || 'package'}-${index}`}
              pagination={false}
              locale={{ emptyText: '暂无外包装信息' }}
            />
          </Card>

          <Card title="采集特征" size="small" style={{ marginBottom: 16 }}>
            {Array.isArray(features) && features.length ? (
              <List size="small" dataSource={features} renderItem={(item) => <List.Item>{typeof item === 'string' ? item : JSON.stringify(item)}</List.Item>} />
            ) : <Text type="secondary">暂无特征</Text>}
          </Card>

          <Card title="变体信息" size="small" style={{ marginBottom: 16 }}>
            {Array.isArray(variants) && variants.length ? (
              <Table
                size="small"
                dataSource={variants}
                columns={Object.keys(variants[0] || {}).map((key) => ({ title: key, dataIndex: key, render: (value) => value == null ? '-' : String(value) }))}
                rowKey={(_, index) => `variant-${index}`}
                pagination={false}
              />
            ) : <Text type="secondary">暂无变体</Text>}
          </Card>

          <Card title="压缩包文件" size="small">
            <Table
              size="small"
              columns={zipColumns}
              dataSource={product.zip_files || []}
              rowKey="path"
              pagination={false}
              locale={{ emptyText: '素材目录内未发现 zip 压缩包' }}
            />
          </Card>

          <Card
            title="各种文件"
            size="small"
            style={{ marginTop: 16 }}
            extra={<Button size="small" icon={<FileExcelOutlined />} onClick={generateAmazonTemplate}>生成导入表格</Button>}
          >
            <Table
              size="small"
              columns={generatedFileColumns}
              dataSource={generatedFiles}
              rowKey="id"
              pagination={false}
              locale={{ emptyText: '暂无文件' }}
            />
            {amazonTemplateFillSummary && (
              <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #f0f0f0' }}>
                <Text strong>导入表格检查</Text>
                <Descriptions bordered size="small" column={3}>
                  <Descriptions.Item label="风险等级">
                    <Tag color={amazonTemplateRiskDisplay.color}>{amazonTemplateRiskDisplay.label}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="已填字段">{amazonTemplateFillSummary.filled_count ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="图片URL">{amazonTemplateFillSummary.image_url_count ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="缺关键字段">{amazonTemplateFillSummary.missing_required_count ?? 0}</Descriptions.Item>
                  <Descriptions.Item label="未映射字段">{amazonTemplateFillSummary.unmapped_count ?? 0}</Descriptions.Item>
                  <Descriptions.Item label="提醒数量">{amazonTemplateFillSummary.warnings_count ?? 0}</Descriptions.Item>
                </Descriptions>
                {Array.isArray(amazonTemplateFillSummary.missing_required_fields) && amazonTemplateFillSummary.missing_required_fields.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <Text type="danger">缺少关键字段</Text>
                    <List
                      size="small"
                      dataSource={amazonTemplateFillSummary.missing_required_fields.slice(0, 8)}
                      renderItem={(item: string) => <List.Item><Text copyable>{item}</Text></List.Item>}
                    />
                  </div>
                )}
                {Array.isArray(amazonTemplateFillSummary.unmapped_fields) && amazonTemplateFillSummary.unmapped_fields.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <Text type="secondary">模板未找到字段</Text>
                    <List
                      size="small"
                      dataSource={amazonTemplateFillSummary.unmapped_fields.slice(0, 8)}
                      renderItem={(item: string) => <List.Item><Text copyable>{item}</Text></List.Item>}
                    />
                  </div>
                )}
              </div>
            )}
            {Array.isArray(amazonTemplateWarnings) && amazonTemplateWarnings.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <Text strong>上架前风险提醒</Text>
                <div style={{ marginTop: 8 }}>
                  {amazonTemplateWarnings.map((item, i) => <Tag color="warning" key={i}>{item}</Tag>)}
                </div>
              </div>
            )}
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
                  <Descriptions.Item label="点击理由" span={2}>{positioning.main_click_reason || '-'}</Descriptions.Item>
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
          <Card title="主图" size="small" style={{ marginBottom: 12 }}>
            {imageSelectionDiagnostics?.main_image_status === 'fallback_substitute' && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message="当前主图为替代素材"
                description={(imageSelectionDiagnostics.main_image_warnings || []).join('；') || images?.main_image_summary}
              />
            )}
            {images?.main_image_path ? (
              <Space direction="vertical">
                <Space>
                  <Image src={imgUrl(images.main_image_path)} width={200} alt="主图" />
                  {images?.main_image_source && (
                    <Tag color={images.main_image_source === 'fallback_substitute' ? 'warning' : 'success'}>
                      {images.main_image_source === 'fallback_substitute' ? '替代主图' : images.main_image_source}
                    </Tag>
                  )}
                </Space>
                {images?.main_image_summary && <Text type="secondary">{images.main_image_summary}</Text>}
              </Space>
            ) : <Text type="secondary">（未选择）</Text>}
          </Card>
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
          <Card title="副图" size="small">
            {galleryOnlyImages.length ? (
              <Space wrap>
                {galleryOnlyImages.map((img, i) => {
                  const path = typeof img === 'string' ? img : img.path;
                  return <Image key={path || i} src={imgUrl(path)} width={120} alt={`副图${i + 1}`} />;
                })}
              </Space>
            ) : <Text type="secondary">（未选择）</Text>}
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
          <Card title="A+规划" size="small" style={{ marginBottom: 12 }}>
            <Text>{aplus?.aplus_plan_summary || '（未规划）'}</Text>
          </Card>
          <Card title="A+图片" size="small">
            {aplusModules.length ? (
              <Space direction="vertical" style={{ width: '100%' }} size={16}>
                {aplusModules.map(({ script, generated, references, plan }) => {
                  const conversionGoal = script.conversion_goal || plan.conversion_goal;
                  const buyerObjection = script.buyer_objection || plan.buyer_objection;
                  const evidenceSource = script.evidence_source || plan.evidence_source;
                  const experienceAngle = script.experience_angle || plan.experience_angle;
                  const galleryOverlapAvoidance = script.gallery_overlap_avoidance || plan.gallery_overlap_avoidance;
                  const riskGuardrails = script.risk_guardrails || plan.risk_guardrails || [];
                  const visualDoNotClaim = script.visual_do_not_claim || plan.visual_do_not_claim || [];
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
                          <Text strong>生成图</Text>
	                        <div style={{ marginTop: 8 }}>
	                          {generated?.path ? (
	                            <Space direction="vertical" style={{ width: '100%' }}>
	                              <Space>
	                                <Tag color={generated.status === 'done' ? 'success' : 'error'}>{generated.status || 'done'}</Tag>
	                                {generated.skipped && <Tag color="processing">已复用</Tag>}
	                                {generated.size && <Text type="secondary">{fileSize(generated.size)}</Text>}
	                              </Space>
	                              <Image src={imgUrl(generated.path)} width={780} alt={`A+模块${script.module_position}`} />
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
                          {script.prompt || '无 prompt'}
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
  ];

  return (
    <>
    <div>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/products')} style={{ marginRight: 12 }}>
          返回
        </Button>
        <Title level={4} style={{ margin: 0, flex: 1 }}>
          商品 #{product.id}
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchDetail}>刷新</Button>
          {product.status === 'created' && (
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={async () => { await startPipeline(product.id); fetchDetail(); }}>
              启动Pipeline
            </Button>
          )}
          {product.status === 'failed' && (
            <Button icon={<RedoOutlined />} onClick={async () => { await retryStep(product.id); fetchDetail(); }}>
              重试
            </Button>
          )}
          {product.status === 'paused' && (
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={async () => { await resumePipeline(product.id); fetchDetail(); }}>
              继续
            </Button>
          )}
          {product.status === 'pending_review' && product.current_step < 10 && (
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={async () => { await resumePipeline(product.id); fetchDetail(); }}>
              继续
            </Button>
          )}
          {product.status === 'pending_review' && product.current_step >= 10 && (
            <Popconfirm
              title="确认同步到商品列表？"
              description="确认后，这个商品会进入商品列表，可继续同步 ASIN 和上传 A+。"
              okText="确认入库"
              cancelText="再看看"
              onConfirm={async () => { await confirmProduct(product.id); message.success('已同步到商品列表'); fetchDetail(); }}
            >
              <Button type="primary" icon={<CheckOutlined />}>确认入库</Button>
            </Popconfirm>
          )}
          {isPipelineRunning && (
            <Button icon={<PauseOutlined />} onClick={async () => { await pausePipeline(product.id); fetchDetail(); }}>
              暂停
            </Button>
          )}
          {!isPipelineRunning && (
            <Popconfirm
              title="确定重新开始？"
              description="会删除旧素材文件和已生成结果，并从商品采集重新拉取。"
              okText="重新开始"
              cancelText="取消"
              onConfirm={() => doRestart()}
            >
              <Button icon={<RedoOutlined />}>重新开始</Button>
            </Popconfirm>
          )}
          <Popconfirm title="确定删除此商品？" onConfirm={async () => { await deleteProduct(product.id); navigate('/products'); }}>
            <Button danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      </div>

      {/* Pipeline 进度条 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Steps
          current={['completed', 'pending_review'].includes(product.status) ? pipelineSteps.length : currentStepIndex}
          status={stepStatus}
          items={pipelineSteps}
          size="small"
        />
      </Card>

      {/* 状态信息 */}
      {product.error_message && (
        <Card size="small" style={{ marginBottom: 16, borderColor: '#ff4d4f' }}>
          <Text type="danger">❌ {product.error_message}</Text>
        </Card>
      )}

      {/* 内容 Tabs */}
      <Tabs items={tabItems} />
    </div>
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
      <Text type="secondary">写清楚这张图哪里不行，例如商品变形、人物被裁切、文字不合适、场景不对。系统会重新生成脚本并重画这一张。</Text>
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
      title="填写 UPC 后重新开始"
      open={restartUpcOpen}
      okText="保存并重新开始"
      cancelText="取消"
      confirmLoading={restartLoading}
      onOk={() => doRestart(restartUpc)}
      onCancel={() => {
        if (!restartLoading) setRestartUpcOpen(false);
      }}
    >
      <Text type="secondary">重新开始会重新生成导入表格；请先补上 UPC，后续会写入 Amazon 表格的 Product Id。</Text>
      <Input
        value={restartUpc}
        onChange={(event) => setRestartUpc(event.target.value)}
        style={{ marginTop: 12 }}
        placeholder="请输入 UPC"
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
          <Text type="secondary">类目路径</Text>
          <Input
            value={categoryPathInput}
            onChange={(event) => setCategoryPathInput(event.target.value)}
            placeholder="Home & Kitchen > Furniture > Sofas & Couches"
          />
        </div>
        <div>
          <Text type="secondary">叶子类目</Text>
          <Input
            value={leafCategoryInput}
            onChange={(event) => setLeafCategoryInput(event.target.value)}
            placeholder="Sofas & Couches"
          />
        </div>
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
