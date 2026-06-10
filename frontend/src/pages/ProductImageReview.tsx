// @ts-nocheck
import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, Button, Card, Empty, Image, message, Select, Space, Spin, Tag, Typography } from 'antd';
import { ArrowLeftOutlined, CheckOutlined, DragOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  getProductImageReviewDetail,
  listProductImageReviewQueue,
  listProductDataSources,
  updateProductListingImages,
} from '../api';
import type { ProductDataSource, ProductImageReviewDetail, ProductImageReviewQueueItem } from '../api';

const { Title, Text } = Typography;
const PRODUCT_DATA_SOURCE_KEY = 'fbm.productList.dataSourceId';
const DEFAULT_LISTING_IMAGE_LIMIT = 9;
const DETAIL_IMAGE_LIMIT = 36;
const PREFETCH_DETAIL_IMAGE_LIMIT = 12;
const EXPANDED_DETAIL_IMAGE_LIMIT = 200;
const INITIAL_UNUSED_IMAGE_LIMIT = 36;

const parseJson = (value: string | null | undefined, fallback: any = null) => {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
};

const imgUrl = (path: string | null | undefined) => {
  if (!path) return '';
  if (/^https?:\/\//i.test(String(path))) return String(path);
  return `/api/images/${path}`;
};

const normalizeImagePath = (item: any) => {
  const path = typeof item === 'string' ? item : item?.path;
  return path ? String(path).trim() : '';
};
const normalizeImageSourceType = (value: string | null | undefined) => String(value || '').trim().toLowerCase();
const uniquePaths = (paths: string[]) => paths.filter((path, index) => path && paths.indexOf(path) === index);
const gigaMainImagePathFromOrder = (galleryOrderPaths: any[]) => (
  Array.isArray(galleryOrderPaths)
    ? normalizeImagePath(galleryOrderPaths.find((item: any) => normalizeImageSourceType(item?.image_type || item?.source) === 'main'))
    : ''
);
const listingImagePathsFromImages = (images: any) => {
  const galleryImagePaths = parseJson(images?.gallery_images, []);
  const galleryOrderPaths = parseJson(images?.gallery_order, []);
  const mainPath = gigaMainImagePathFromOrder(galleryOrderPaths);
  const savedPaths = [
    images?.main_image_path ? String(images.main_image_path).trim() : '',
    ...(Array.isArray(galleryImagePaths) ? galleryImagePaths.map(normalizeImagePath) : []),
  ].filter(Boolean);
  if (savedPaths.length) {
    return uniquePaths([
      mainPath || savedPaths[0],
      ...savedPaths.filter((path) => path !== (mainPath || savedPaths[0])),
    ]).slice(0, DEFAULT_LISTING_IMAGE_LIMIT);
  }
  if (!Array.isArray(galleryOrderPaths)) return [];
  const galleryPaths = uniquePaths(
    galleryOrderPaths
      .filter((item: any) => ['gallery'].includes(normalizeImageSourceType(item?.image_type || item?.source)))
      .map(normalizeImagePath)
      .filter(Boolean)
  ).filter((path) => path !== mainPath);
  return uniquePaths([
    mainPath,
    ...galleryPaths.slice(-(DEFAULT_LISTING_IMAGE_LIMIT - 1)),
  ]).slice(0, DEFAULT_LISTING_IMAGE_LIMIT);
};

const imageSourceLabel = (item: any) => {
  const type = normalizeImageSourceType(item?.image_type || item?.source);
  if (type === 'main') return '详情页主图';
  if (type === 'gallery') return '详情页展示图';
  if (type === 'variant_main') return '其它 SKU 主图';
  if (type === 'variant_gallery') return '其它 SKU 展示图';
  if (type === 'file') return '素材包';
  if (type === 'brand') return '品牌素材';
  return '备用素材';
};

const ProductImageReview: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [dataSources, setDataSources] = useState<ProductDataSource[]>([]);
  const [selectedDataSourceId, setSelectedDataSourceId] = useState<number | undefined>(() => {
    const fromQuery = Number(searchParams.get('data_source_id') || '');
    if (Number.isFinite(fromQuery) && fromQuery > 0) return fromQuery;
    const saved = Number(window.localStorage.getItem(PRODUCT_DATA_SOURCE_KEY) || '');
    return Number.isFinite(saved) && saved > 0 ? saved : undefined;
  });
  const [queue, setQueue] = useState<ProductImageReviewQueueItem[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ProductImageReviewDetail | null>(null);
  const [detailCache, setDetailCache] = useState<Record<number, ProductImageReviewDetail>>({});
  const [draftPaths, setDraftPaths] = useState<string[]>([]);
  const [imageDragPayload, setImageDragPayload] = useState<any | null>(null);
  const [queueLoading, setQueueLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showAllUnusedImages, setShowAllUnusedImages] = useState(false);

  const currentIndex = queue.findIndex((item) => item.id === currentId);
  const galleryOrder = useMemo(() => parseJson(detail?.images?.gallery_order, []), [detail?.images?.gallery_order]);
  const galleryImages = useMemo(() => parseJson(detail?.images?.gallery_images, []), [detail?.images?.gallery_images]);
  const imageMetaByPath = useMemo(() => {
    const meta = new Map<string, string>();
    if (detail?.images?.main_image_path) {
      meta.set(detail.images.main_image_path, detail.images?.main_image_source || 'main image');
    }
    if (Array.isArray(galleryImages)) {
      galleryImages.forEach((item: any) => {
        const path = normalizeImagePath(item);
        if (path) meta.set(path, typeof item === 'string' ? 'gallery image' : (item?.role || item?.label || 'gallery image'));
      });
    }
    return meta;
  }, [detail?.images?.main_image_path, detail?.images?.main_image_source, galleryImages]);
  const selectedListingImages = useMemo(() => (
    draftPaths.map((path, index) => ({
      path,
      label: index === 0 ? '主图' : `副图 ${index}`,
      meta: imageMetaByPath.get(path) || (index === 0 ? 'manual selected' : 'gallery image'),
    })).filter((item) => item.path)
  ), [draftPaths, imageMetaByPath]);
  const imageResourceItems = useMemo(() => {
    const items: any[] = [];
    const seen = new Set<string>();
    const addItem = (item: any, fallback: any = {}) => {
      const path = normalizeImagePath(item);
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
    if (Array.isArray(galleryOrder)) {
      galleryOrder.forEach((item: any, index: number) => {
        const path = normalizeImagePath(item);
        addItem({ ...item, path }, {
          image_id: `#${index + 1}`,
          image_type: item?.image_type || item?.source || (index === 0 ? 'main' : 'gallery'),
          reason: imageSourceLabel(item),
        });
      });
    }
    if (Array.isArray(galleryImages)) {
      galleryImages.forEach((item: any, index: number) => {
        addItem(item, {
          image_id: `#${index + 1}`,
          image_type: index === 0 ? 'main' : 'gallery',
          reason: typeof item === 'string' ? 'gallery image' : imageSourceLabel(item),
        });
      });
    }
    selectedListingImages.forEach((item: any) => addItem(item, { image_type: item.label, reason: item.meta }));
    return items;
  }, [galleryOrder, galleryImages, selectedListingImages]);
  const selectedListingPathSet = useMemo(() => new Set(selectedListingImages.map((item: any) => item.path)), [selectedListingImages]);
  const unusedImageResourceItems = useMemo(
    () => imageResourceItems.filter((item: any) => item?.path && !selectedListingPathSet.has(item.path)),
    [imageResourceItems, selectedListingPathSet],
  );
  const visibleUnusedImageResourceItems = useMemo(
    () => showAllUnusedImages ? unusedImageResourceItems : unusedImageResourceItems.slice(0, INITIAL_UNUSED_IMAGE_LIMIT),
    [showAllUnusedImages, unusedImageResourceItems],
  );
  const galleryOrderTotal = Number(detail?.images?.gallery_order_total || galleryOrder.length || 0);
  const galleryOrderLimit = Number(detail?.images?.gallery_order_limit || galleryOrder.length || 0);
  const hasMoreGalleryOrderImages = galleryOrderTotal > galleryOrder.length && galleryOrderLimit < EXPANDED_DETAIL_IMAGE_LIMIT;

  const loadDataSources = async () => {
    const { data } = await listProductDataSources({ platform: 'giga', enabled: true, page: 1, page_size: 100 });
    setDataSources(data.items);
    setSelectedDataSourceId((current) => current || data.items[0]?.id);
  };

  const loadQueue = async (preferredId?: number | null) => {
    setQueueLoading(true);
    try {
      const { data } = await listProductImageReviewQueue({
        data_source_id: selectedDataSourceId,
        limit: 100,
      });
      const items = data.items;
      setQueue(items);
      const nextId = preferredId && items.some((item) => item.id === preferredId) ? preferredId : items[0]?.id || null;
      setCurrentId(nextId);
      if (!nextId) setDetail(null);
    } finally {
      setQueueLoading(false);
    }
  };

  const applyDetail = (data: ProductImageReviewDetail) => {
    setDetail(data);
    setDraftPaths(listingImagePathsFromImages(data.images));
    setShowAllUnusedImages(false);
  };

  const loadDetail = async (productId: number, imageLimit = DETAIL_IMAGE_LIMIT, options: { silent?: boolean } = {}) => {
    const cached = detailCache[productId];
    if (cached) {
      applyDetail(cached);
      const cachedLimit = Number(cached.images?.gallery_order_limit || 0);
      const cachedTotal = Number(cached.images?.gallery_order_total || 0);
      if (cachedLimit >= imageLimit || (cachedTotal > 0 && cachedLimit >= cachedTotal)) return;
    }
    if (!options.silent) setDetailLoading(true);
    try {
      const { data } = await getProductImageReviewDetail(productId, { image_limit: imageLimit });
      setDetailCache((prev) => ({ ...prev, [productId]: data }));
      if (!options.silent || productId === currentId) applyDetail(data);
    } finally {
      if (!options.silent) setDetailLoading(false);
    }
  };

  const prefetchDetail = async (productId: number | null | undefined) => {
    if (!productId || detailCache[productId]) return;
    try {
      const { data } = await getProductImageReviewDetail(productId, { image_limit: PREFETCH_DETAIL_IMAGE_LIMIT });
      setDetailCache((prev) => prev[productId] ? prev : { ...prev, [productId]: data });
    } catch {
      // 预取失败不影响当前确认。
    }
  };

  useEffect(() => { loadDataSources().catch(() => message.error('加载店铺失败')); }, []);
  useEffect(() => {
    if (selectedDataSourceId) {
      window.localStorage.setItem(PRODUCT_DATA_SOURCE_KEY, String(selectedDataSourceId));
      setSearchParams({ data_source_id: String(selectedDataSourceId) });
    }
    loadQueue(null).catch(() => message.error('加载图片确认列表失败'));
  }, [selectedDataSourceId]);
  useEffect(() => { if (currentId) loadDetail(currentId).catch(() => message.error('加载商品详情失败')); }, [currentId]);
  useEffect(() => {
    if (!currentId || !queue.length || detailLoading) return;
    const index = queue.findIndex((item) => item.id === currentId);
    const nextId = index >= 0 ? queue[index + 1]?.id : queue[0]?.id;
    const timer = window.setTimeout(() => prefetchDetail(nextId), 800);
    return () => window.clearTimeout(timer);
  }, [currentId, queue, detailLoading]);

  const loadMoreGalleryOrderImages = async () => {
    if (!currentId) return;
    await loadDetail(currentId, EXPANDED_DETAIL_IMAGE_LIMIT);
    setShowAllUnusedImages(true);
  };

  const setDraftListingImagePaths = (paths: string[]) => {
    setDraftPaths(uniquePaths(paths).slice(0, DEFAULT_LISTING_IMAGE_LIMIT));
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
      const next = [...draftPaths];
      const [moved] = next.splice(payload.index, 1);
      next.splice(toIndex, 0, moved);
      setDraftListingImagePaths(next);
      setImageDragPayload(null);
      return;
    }
    if (payload.source === 'pool' && payload.path) {
      const withoutDragged = draftPaths.filter((path) => path !== payload.path);
      withoutDragged.splice(Math.min(toIndex, withoutDragged.length), 0, payload.path);
      setDraftListingImagePaths(withoutDragged);
    }
    setImageDragPayload(null);
  };

  const dropListingImageToSelected = (event: React.DragEvent) => {
    event.preventDefault();
    const payload = dragPayloadFromEvent(event);
    if (!payload) return;
    if (payload.source === 'pool' && payload.path) {
      if (!draftPaths.includes(payload.path) && draftPaths.length >= DEFAULT_LISTING_IMAGE_LIMIT) {
        message.warning(`已使用图片最多 ${DEFAULT_LISTING_IMAGE_LIMIT} 张，请先移出一张`);
        setImageDragPayload(null);
        return;
      }
      setDraftListingImagePaths([...draftPaths.filter((path) => path !== payload.path), payload.path]);
    }
    setImageDragPayload(null);
  };

  const dropListingImageToUnusedPool = (event: React.DragEvent) => {
    event.preventDefault();
    const payload = dragPayloadFromEvent(event);
    if (!payload) return;
    if (payload.source === 'selected') {
      setDraftListingImagePaths(draftPaths.filter((path) => path && path !== payload.path));
    }
    setImageDragPayload(null);
  };

  const addListingImageFromPool = (path: string | null | undefined) => {
    if (saving || !path) return;
    if (!draftPaths.includes(path) && draftPaths.length >= DEFAULT_LISTING_IMAGE_LIMIT) {
      message.warning(`已使用图片最多 ${DEFAULT_LISTING_IMAGE_LIMIT} 张，请先移出一张`);
      return;
    }
    setDraftListingImagePaths([...draftPaths.filter((itemPath) => itemPath !== path), path]);
  };

  const removeListingImageFromSelected = (path: string | null | undefined) => {
    if (saving || !path) return;
    setDraftListingImagePaths(draftPaths.filter((itemPath) => itemPath && itemPath !== path));
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

  const saveAndNext = async () => {
    if (!detail || !draftPaths.length) return;
    setSaving(true);
    try {
      await updateProductListingImages(detail.id, {
        main_image_path: draftPaths[0],
        gallery_images: draftPaths.slice(1),
      });
      message.success('商品图片已确认');
      const nextQueue = queue.filter((item) => item.id !== detail.id);
      setQueue(nextQueue);
      const nextId = nextQueue[currentIndex >= 0 ? Math.min(currentIndex, nextQueue.length - 1) : 0]?.id || null;
      setCurrentId(nextId);
      if (!nextId) setDetail(null);
      loadQueue(nextId).catch(() => message.error('刷新图片确认列表失败'));
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '保存图片失败');
    } finally {
      setSaving(false);
    }
  };

  const skipCurrent = () => {
    if (currentIndex >= 0 && queue.length > 1) {
      setCurrentId(queue[(currentIndex + 1) % queue.length].id);
    }
  };

  return (
    <div>
      <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 16 }} align="start">
        <div>
          <Title level={4} style={{ margin: 0 }}>图片确认</Title>
          <Text type="secondary">按当前店铺逐条确认默认商品图片，保存后才推进后续流程。</Text>
        </div>
        <Space>
          <Select
            style={{ width: 220 }}
            value={selectedDataSourceId}
            options={dataSources.map((source) => ({ value: source.id, label: source.name }))}
            onChange={(value) => setSelectedDataSourceId(value)}
          />
          <Button icon={<ReloadOutlined />} onClick={() => loadQueue(currentId)}>刷新</Button>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/products')}>商品工作台</Button>
        </Space>
      </Space>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={`待确认 ${queue.length} 个${currentId ? `，当前第 ${Math.max(currentIndex + 1, 1)} 个` : ''}`}
      />

      <Spin spinning={queueLoading || detailLoading || saving}>
        {!detail ? (
          <Empty description="当前店铺没有待确认图片的商品" />
        ) : (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card size="small">
              <Space direction="vertical" size={4}>
                <Text strong>{detail.data?.item_code || detail.source_item_id || `#${detail.id}`}</Text>
                <Text>{detail.data?.title || detail.title || '-'}</Text>
                <Text type="secondary">{detail.current_task_status || detail.status}</Text>
              </Space>
            </Card>

            <Card
              size="small"
              title="商品图片确认"
              extra={(
                <Space>
                  <Tag color="warning">待保存确认</Tag>
                  <Button onClick={skipCurrent}>跳过</Button>
                  <Button type="primary" icon={<CheckOutlined />} loading={saving} disabled={!draftPaths.length} onClick={saveAndNext}>
                    保存并下一条
                  </Button>
                </Space>
              )}
            >
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
                              key={item.path || index}
                              draggable={!saving}
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
                                cursor: saving ? 'default' : 'grab',
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
                                  loading="lazy"
                                  width="100%"
                                  alt={isMain ? '主图' : `副图${index}`}
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
                    <Text strong>备用/未选素材</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>备用文件和品牌图默认停留在这里</Text>
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
                        {visibleUnusedImageResourceItems.map((item: any, index: number) => (
                          <div
                            key={item.path || index}
                            draggable={!saving}
                            onDragStart={(event) => startListingImageDrag(event, { source: 'pool', path: item.path })}
                            onDragEnd={() => setImageDragPayload(null)}
                            onDoubleClickCapture={(event) => handleListingImageDoubleClick(event, item.path, addListingImageFromPool)}
                            onDoubleClick={(event) => handleListingImageDoubleClick(event, item.path, addListingImageFromPool)}
                            style={{
                              cursor: saving ? 'default' : 'grab',
                              border: '1px solid #eee',
                              borderRadius: 8,
                              padding: 8,
                              background: '#fff',
                            }}
                          >
                            <Space direction="vertical" size={6} style={{ width: '100%' }}>
                              <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                                <Text strong style={{ fontSize: 12 }}>{item.image_id || `#${index + 1}`}</Text>
                                <DragOutlined style={{ color: '#bbb' }} />
                              </Space>
                              <Image
                                src={imgUrl(item.path)}
                                loading="lazy"
                                width="100%"
                                alt={item.filename || `图片${index + 1}`}
                                preview={false}
                                onDoubleClick={(event) => handleListingImageDoubleClick(event, item.path, addListingImageFromPool)}
                                style={{ aspectRatio: '1 / 1', objectFit: 'cover', background: '#f5f5f5' }}
                              />
                              <Typography.Paragraph
                                type="secondary"
                                ellipsis={{ rows: 2 }}
                                style={{ fontSize: 12, marginBottom: 0 }}
                              >
                                {item.visible_selling_point || item.image_type || item.filename || item.reason}
                              </Typography.Paragraph>
                            </Space>
                          </div>
                        ))}
                        {hasMoreGalleryOrderImages ? (
                          <Button loading={detailLoading} onClick={loadMoreGalleryOrderImages}>
                            加载更多备用素材（剩余约 {galleryOrderTotal - galleryOrder.length} 张）
                          </Button>
                        ) : !showAllUnusedImages && unusedImageResourceItems.length > visibleUnusedImageResourceItems.length ? (
                          <Button onClick={() => setShowAllUnusedImages(true)}>
                            显示剩余 {unusedImageResourceItems.length - visibleUnusedImageResourceItems.length} 张备用素材
                          </Button>
                        ) : null}
                      </div>
                    ) : (
                      <Space direction="vertical" size={4} style={{ width: '100%', alignItems: 'center', justifyContent: 'center', minHeight: 96 }}>
                        <Text type="secondary">暂无备用/未选素材</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>把上方图片拖到这里，或双击已使用图片即可移出使用区</Text>
                      </Space>
                    )}
                  </div>
                </div>
              </Space>
            </Card>
          </Space>
        )}
      </Spin>
    </div>
  );
};

export default ProductImageReview;
