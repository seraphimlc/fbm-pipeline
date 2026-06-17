// @ts-nocheck
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, Button, Card, Empty, Image, List, message, Select, Space, Spin, Tag, Typography } from 'antd';
import { ArrowLeftOutlined, CheckOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import {
  captureMissingProductCompetitorCandidates,
  getProductCompetitorReviewDetail,
  listProductCompetitorCandidates,
  listProductCompetitorReviewQueue,
  listProductDataSources,
  retryProductCompetitorCandidateCapture,
  searchProductCompetitorCandidates,
  selectProductCompetitorCandidate,
} from '../api';
import type {
  AmazonStyleSnapCandidateGroup,
  ProductCompetitorReviewDetail,
  ProductCompetitorReviewQueueItem,
  ProductDataSource,
} from '../api';

const { Title, Text } = Typography;
const PRODUCT_DATA_SOURCE_KEY = 'fbm.productList.dataSourceId';
const REVIEW_QUEUE_LIMIT = 30;

const parseJson = (value: string | null | undefined, fallback: any = null) => {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
};

const normalizeComparableImage = (value: string | null | undefined) => String(value || '').trim();

const competitorSourceImageForDetail = (detail: ProductCompetitorReviewDetail | null | undefined) => {
  if (!detail) return '';
  const snapshot = parseJson(detail.data?.gigab2b_raw_snapshot, {});
  return normalizeComparableImage(
    detail.images?.main_image_path
    || snapshot?.selected_stylesnap?.source_image_path
    || snapshot?.stylesnap_search?.source_image_path
  );
};

const competitorGroupMatchesDetail = (
  detail: ProductCompetitorReviewDetail | null | undefined,
  group: AmazonStyleSnapCandidateGroup | null | undefined,
) => {
  if (!detail || !group) return false;
  if (group.product_task_id && group.product_task_id !== detail.id) return false;
  const expectedSource = competitorSourceImageForDetail(detail);
  const groupSource = normalizeComparableImage(group.source_image_path || group.source_image_url);
  return !expectedSource || !groupSource || expectedSource === groupSource;
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const imgUrl = (path: string | null | undefined) => {
  if (!path) return '';
  if (/^https?:\/\//i.test(String(path))) return String(path);
  return `/api/images/${path}`;
};

const isCompetitorSearchFailed = (product: { status?: string; error_message?: string | null }) => (
  product.status === 'failed' && /同款搜索|StyleSnap/i.test(product.error_message || '')
);

const ProductCompetitorReview: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryProductId = useMemo(() => {
    const parsed = Number(searchParams.get('product_id') || '');
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [searchParams]);
  const [dataSources, setDataSources] = useState<ProductDataSource[]>([]);
  const [selectedDataSourceId, setSelectedDataSourceId] = useState<number | undefined>(() => {
    const fromQuery = Number(searchParams.get('data_source_id') || '');
    if (Number.isFinite(fromQuery) && fromQuery > 0) return fromQuery;
    const saved = Number(window.localStorage.getItem(PRODUCT_DATA_SOURCE_KEY) || '');
    return Number.isFinite(saved) && saved > 0 ? saved : undefined;
  });
  const [queue, setQueue] = useState<ProductCompetitorReviewQueueItem[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ProductCompetitorReviewDetail | null>(null);
  const [detailCache, setDetailCache] = useState<Record<number, ProductCompetitorReviewDetail>>({});
  const [candidateCache, setCandidateCache] = useState<Record<number, AmazonStyleSnapCandidateGroup>>({});
  const [candidateGroup, setCandidateGroup] = useState<AmazonStyleSnapCandidateGroup | null>(null);
  const [queueLoading, setQueueLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [selectingId, setSelectingId] = useState<number | null>(null);
  const [retryingCaptureId, setRetryingCaptureId] = useState<number | null>(null);
  const [capturingMissing, setCapturingMissing] = useState(false);
  const [selectedDone, setSelectedDone] = useState<{ productId: number; asin?: string | null } | null>(null);
  const loadSeqRef = useRef(0);

  const currentIndex = queue.findIndex((item) => item.id === currentId);
  const rawSnapshot = useMemo(() => parseJson(detail?.data?.gigab2b_raw_snapshot, {}), [detail?.data?.gigab2b_raw_snapshot]);
  const sourceImage = competitorSourceImageForDetail(detail);
  const candidateGroupMatchesCurrent = competitorGroupMatchesDetail(detail, candidateGroup);
  const candidatesForCurrent = candidateGroupMatchesCurrent && Array.isArray(candidateGroup?.candidates)
    ? candidateGroup.candidates.filter(Boolean)
    : [];
  const hasCandidatesForCurrent = candidatesForCurrent.length > 0;
  const missingBasicInfoCount = candidatesForCurrent.filter((candidate) => (
    !candidate.title
    || !candidate.amazon_image_url
    || candidate.listing_capture_status === 'failed'
  )).length;
  const hasActiveCandidateCapture = candidatesForCurrent.some((candidate) => (
    candidate.listing_capture_status === 'queued'
    || candidate.listing_capture_status === 'running'
  ));
  const queuePositionText = currentId && currentIndex >= 0 ? `，当前第 ${currentIndex + 1} 个` : '';
  const currentProductLabel = detail?.data?.item_code || detail?.source_item_id || (currentId ? `#${currentId}` : '-');

  const loadDataSources = async () => {
    const { data } = await listProductDataSources({ platform: 'giga', sales_channel: 'amazon', enabled: true, page: 1, page_size: 100 });
    setDataSources(data.items);
    setSelectedDataSourceId((current) => current || data.items[0]?.id);
  };

  const loadQueue = async (preferredId?: number | null, options: { preserveCurrentWhenMissing?: boolean } = {}) => {
    if (preferredId) setCurrentId(preferredId);
    setQueueLoading(true);
    try {
      const { data } = await listProductCompetitorReviewQueue({
        data_source_id: selectedDataSourceId,
        limit: REVIEW_QUEUE_LIMIT,
      });
      const items = data.items;
      setQueue(items);
      const preferredExists = preferredId && items.some((item) => item.id === preferredId);
      if (options.preserveCurrentWhenMissing && !preferredExists) return items;
      const nextId = preferredExists ? preferredId : items[0]?.id || null;
      setCurrentId(nextId);
      if (!nextId) {
        setDetail(null);
        setCandidateGroup(null);
      }
      return items;
    } finally {
      setQueueLoading(false);
    }
  };

  const applyDetail = (data: ProductCompetitorReviewDetail) => {
    setDetail(data);
  };

  const loadDetailAndCandidates = async (productId: number) => {
    const seq = loadSeqRef.current + 1;
    loadSeqRef.current = seq;
    const cachedDetail = detailCache[productId];
    if (cachedDetail) {
      applyDetail(cachedDetail);
    } else {
      setDetail(null);
    }
    const cachedCandidates = candidateCache[productId];
    if (cachedCandidates && cachedDetail && competitorGroupMatchesDetail(cachedDetail, cachedCandidates)) {
      setCandidateGroup(cachedCandidates);
    } else {
      setCandidateGroup(null);
    }
    setSelectedDone(null);
    setDetailLoading(true);
    try {
      const { data } = await getProductCompetitorReviewDetail(productId);
      if (loadSeqRef.current !== seq) return;
      setDetailCache((prev) => ({ ...prev, [productId]: data }));
      applyDetail(data);
    } finally {
      if (loadSeqRef.current === seq) setDetailLoading(false);
    }
    setCandidateLoading(true);
    try {
      const { data: group } = await listProductCompetitorCandidates(productId, { enrich_images: true });
      if (loadSeqRef.current !== seq) return;
      setCandidateCache((prev) => ({ ...prev, [productId]: group }));
      setCandidateGroup(competitorGroupMatchesDetail(data, group) ? group : null);
    } catch {
      if (loadSeqRef.current === seq) setCandidateGroup(null);
    } finally {
      if (loadSeqRef.current === seq) setCandidateLoading(false);
    }
  };

  const prefetchNext = async (productId: number | null | undefined) => {
    if (!productId || detailCache[productId]) return;
    try {
      const { data } = await getProductCompetitorReviewDetail(productId);
      setDetailCache((prev) => prev[productId] ? prev : { ...prev, [productId]: data });
    } catch {
      // 预取失败不影响当前操作。
    }
  };

  useEffect(() => { loadDataSources().catch(() => message.error('加载店铺失败')); }, []);
  useEffect(() => {
    if (selectedDataSourceId) {
      window.localStorage.setItem(PRODUCT_DATA_SOURCE_KEY, String(selectedDataSourceId));
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set('data_source_id', String(selectedDataSourceId));
      setSearchParams(nextParams, { replace: true });
    }
    loadQueue(queryProductId).catch(() => message.error('加载竞品选择列表失败'));
  }, [selectedDataSourceId]);
  useEffect(() => { if (currentId) loadDetailAndCandidates(currentId).catch(() => message.error('加载商品候选失败')); }, [currentId]);
  useEffect(() => {
    if (!currentId) return;
    const currentParamId = Number(searchParams.get('product_id') || '');
    if (currentParamId === currentId) return;
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('product_id', String(currentId));
    setSearchParams(nextParams, { replace: true });
  }, [currentId]);
  useEffect(() => {
    if (!currentId || !queue.length) return;
    const index = queue.findIndex((item) => item.id === currentId);
    const nextId = index >= 0 ? queue[index + 1]?.id : queue[0]?.id;
    prefetchNext(nextId);
  }, [currentId, queue, detailCache]);

  const refreshCurrent = async () => {
    if (!currentId) return;
    setCandidateCache((prev) => {
      const next = { ...prev };
      delete next[currentId];
      return next;
    });
    await loadDetailAndCandidates(currentId);
  };

  const waitForCandidates = async (productId: number) => {
    let latestGroup: AmazonStyleSnapCandidateGroup | null = null;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      if (attempt > 0) await sleep(2000);
      const { data: nextDetail } = await getProductCompetitorReviewDetail(productId);
      setDetailCache((prev) => ({ ...prev, [productId]: nextDetail }));
      if (currentId === productId) setDetail(nextDetail);
      const snapshot = parseJson(nextDetail.data?.gigab2b_raw_snapshot, {});
      const searchState = snapshot?.stylesnap_search || {};
      const failed = searchState?.status === 'failed' || isCompetitorSearchFailed(nextDetail);
      if (failed) {
        throw new Error(searchState?.error || nextDetail.error_message || '候选搜索失败');
      }
      try {
        const { data: group } = await listProductCompetitorCandidates(productId, { enrich_images: true });
        setCandidateCache((prev) => ({ ...prev, [productId]: group }));
        if (competitorGroupMatchesDetail(nextDetail, group)) {
          latestGroup = group;
          if (currentId === productId) setCandidateGroup(group);
          if (group.candidates?.length || searchState?.status === 'captured') return group;
        } else if (currentId === productId) {
          setCandidateGroup(null);
        }
      } catch {
        if (searchState?.status === 'captured') return latestGroup;
      }
    }
    return latestGroup;
  };

  const searchCandidates = async (force = false) => {
    if (!detail) return;
    setSearching(true);
    try {
      const productId = detail.id;
      if (force) {
        setCandidateCache((prev) => {
          const next = { ...prev };
          delete next[productId];
          return next;
        });
        setCandidateGroup(null);
      }
      await searchProductCompetitorCandidates(detail.id, force);
      message.loading({ content: '已提交 StyleSnap 搜索，正在等待当前主图候选写入', key: 'competitor-review-search', duration: 0 });
      const group = await waitForCandidates(productId);
      if (group?.candidates?.length) {
        message.success({ content: `已找到 ${group.candidates.length} 个候选竞品`, key: 'competitor-review-search' });
      } else {
        message.info({ content: '搜索已提交，候选写入较慢，请稍后刷新候选状态', key: 'competitor-review-search' });
      }
    } catch (error: any) {
      message.destroy('competitor-review-search');
      message.error(error?.response?.data?.detail || error?.message || '候选搜索失败');
    } finally {
      setSearching(false);
    }
  };

  const selectCandidate = async (candidateId: number) => {
    if (!detail) return;
    if (!candidateGroupMatchesCurrent) {
      message.warning('当前商品候选仍在加载，请稍后再选择');
      return;
    }
    const candidate = candidateGroup?.candidates?.find((item) => item.id === candidateId);
    if (!candidate) {
      message.warning('候选竞品已刷新，请重新选择');
      return;
    }
    const selectionReady = candidate?.title && candidate?.amazon_image_url;
    if (!selectionReady) {
      message.warning('这个候选列表信息还没有标题和主图，请先补抓后再选择');
      return;
    }
    setSelectingId(candidateId);
    try {
      const { data: group } = await selectProductCompetitorCandidate(detail.id, candidateId, false, false);
      setCandidateCache((prev) => ({ ...prev, [detail.id]: group }));
      setCandidateGroup(group);
      setQueue((prev) => prev.map((item) => (
        item.id === detail.id ? { ...item, competitor_asin: candidate?.asin || item.competitor_asin } : item
      )));
      try {
        const { data: updatedDetail } = await getProductCompetitorReviewDetail(detail.id);
        setDetailCache((prev) => ({ ...prev, [detail.id]: updatedDetail }));
        applyDetail(updatedDetail);
      } catch {
        // 选择已成功，详情刷新失败时保留当前页面状态，避免打断用户继续切换。
      }
      setSelectedDone({ productId: detail.id, asin: candidate?.asin });
      await loadQueue(detail.id, { preserveCurrentWhenMissing: true });
      message.success('已选择竞品，当前商品已从待选队列移除');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '选择竞品失败');
    } finally {
      setSelectingId(null);
    }
  };

  const retryCandidateCapture = async (candidateId: number) => {
    if (!detail) return;
    setRetryingCaptureId(candidateId);
    try {
      const { data } = await retryProductCompetitorCandidateCapture(detail.id, candidateId, true);
      setCandidateCache((prev) => ({ ...prev, [detail.id]: data }));
      setCandidateGroup(data);
      message.success('已提交候选 Listing 重新抓取');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '提交重新抓取失败');
    } finally {
      setRetryingCaptureId(null);
    }
  };

  const captureMissingCandidates = async () => {
    if (!detail || !missingBasicInfoCount) return;
    setCapturingMissing(true);
    try {
      const { data } = await captureMissingProductCompetitorCandidates(detail.id, false);
      setCandidateCache((prev) => ({ ...prev, [detail.id]: data }));
      setCandidateGroup(data);
      message.success(`已提交 ${missingBasicInfoCount} 个缺标题/主图候选补抓`);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '提交候选补抓失败');
    } finally {
      setCapturingMissing(false);
    }
  };

  const skipCurrent = () => {
    if (currentIndex >= 0 && queue.length > 1) {
      setCurrentId(queue[(currentIndex + 1) % queue.length].id);
      return;
    }
    if (queue.length > 0) {
      setCurrentId(queue[0].id);
    }
  };

  const continueNext = () => {
    const nextId = queue.find((item) => item.id !== detail?.id)?.id || null;
    setCurrentId(nextId);
    if (!nextId) {
      setDetail(null);
      setCandidateGroup(null);
    }
  };

  return (
    <div>
      <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 16 }} align="start">
        <div>
          <Title level={4} style={{ margin: 0 }}>选竞品</Title>
          <Text type="secondary">逐条查看已确认图片的商品，选择参考竞品后留在当前商品，可手动切换下一条。</Text>
        </div>
        <Space>
          <Select
            style={{ width: 220 }}
            value={selectedDataSourceId}
            options={dataSources.map((source) => ({ value: source.id, label: source.name }))}
            onChange={(value) => setSelectedDataSourceId(value)}
          />
          <Button icon={<ReloadOutlined />} onClick={() => loadQueue(currentId)}>刷新队列</Button>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/products')}>商品工作台</Button>
        </Space>
      </Space>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={queryProductId ? `当前商品：${currentProductLabel}` : `待处理商品 ${queue.length} 个${queuePositionText}`}
        description={queryProductId ? `候选竞品 ${candidatesForCurrent.length} 个${candidateLoading ? '，正在刷新候选' : ''}` : '这里统计的是需要选择竞品的商品数量，不是候选竞品数量。'}
      />
      {selectedDone && detail && selectedDone.productId === detail.id ? (
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 16 }}
          message={`已选择竞品${selectedDone.asin ? ` ${selectedDone.asin}` : ''}`}
          description="当前商品已从待选队列移除。你可以留在这里查看结果，或继续处理下一条。"
          action={<Button type="primary" onClick={continueNext}>继续下一条</Button>}
        />
      ) : null}

      <Spin spinning={(!detail && queueLoading) || detailLoading}>
        {!detail ? (
          <Empty description="当前店铺没有待选择竞品的商品" />
        ) : (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card
              size="small"
              extra={(
                <Space>
                  <Button onClick={skipCurrent}>下一个</Button>
                  <Button icon={<ReloadOutlined />} loading={detailLoading || candidateLoading} onClick={refreshCurrent}>刷新当前</Button>
                </Space>
              )}
            >
              <Space align="start" size={16}>
                {sourceImage ? (
                  <Image src={imgUrl(sourceImage)} width={128} height={128} style={{ objectFit: 'cover', borderRadius: 6 }} />
                ) : null}
                <Space direction="vertical" size={6}>
                  <Text strong>{detail.data?.item_code || detail.source_item_id || `#${detail.id}`}</Text>
                  <Text>{detail.data?.title || detail.title || '-'}</Text>
                  <Space wrap>
                    <Tag>{detail.current_task_status || detail.status}</Tag>
                    {detail.leaf_category ? <Tag color="blue">{detail.leaf_category}</Tag> : null}
                    {isCompetitorSearchFailed(detail) ? <Tag color="error">候选搜索失败</Tag> : null}
                  </Space>
                </Space>
              </Space>
            </Card>

            <Card
              size="small"
              title="候选竞品"
              extra={(
                <Space>
                  {hasCandidatesForCurrent ? (
                    <>
                      <Button
                        icon={<ReloadOutlined />}
                        loading={capturingMissing}
                        disabled={!missingBasicInfoCount || hasActiveCandidateCapture}
                        onClick={captureMissingCandidates}
                      >
                        补抓缺标题/主图
                      </Button>
                      <Button icon={<ReloadOutlined />} loading={candidateLoading} onClick={refreshCurrent}>
                        刷新候选状态
                      </Button>
                      <Button icon={<SearchOutlined />} loading={searching} title="会重新调用 StyleSnap，用当前主图刷新候选来源" onClick={() => searchCandidates(true)}>
                        重新跑搜索
                      </Button>
                    </>
                  ) : (
                    <Button icon={<SearchOutlined />} loading={searching} onClick={() => searchCandidates(false)}>
                      搜索候选
                    </Button>
                  )}
                </Space>
              )}
            >
              <Spin spinning={candidateLoading}>
              <List
                dataSource={candidatesForCurrent}
                locale={{ emptyText: candidateLoading ? '正在加载当前商品候选' : '暂无候选，可先搜索候选' }}
                renderItem={(candidate) => {
                  const selected = candidateGroup?.selected_candidate_id === candidate.id || candidate.is_selected === 1;
                  const hasSelectedCandidate = Boolean(candidateGroup?.selected_candidate_id);
                  const captureStatus = candidate.listing_capture_status;
                  const captureReady = captureStatus === 'captured' && candidate.title && candidate.amazon_image_url;
                  const selectionReady = candidate.title && candidate.amazon_image_url;
                  const captureFailed = captureStatus === 'failed';
                  const captureRunning = captureStatus === 'queued' || captureStatus === 'running';
                  const captureMissingImage = captureStatus === 'captured' && !candidate.amazon_image_url;
                  const captureMissingTitle = captureStatus === 'captured' && !candidate.title;
                  const canRetryCapture = !captureRunning && (!selectionReady || captureFailed || captureMissingImage || captureMissingTitle);
                  return (
                    <List.Item
                      actions={[
                        canRetryCapture ? (
                          <Button
                            key="retry-capture"
                            icon={<ReloadOutlined />}
                            loading={retryingCaptureId === candidate.id}
                            onClick={() => retryCandidateCapture(candidate.id)}
                          >
                            {captureFailed || captureMissingImage || captureMissingTitle ? '重新抓取' : '补抓详情'}
                          </Button>
                        ) : null,
                        <Button
                          key="select"
                          type={selected ? 'default' : 'primary'}
                          icon={<CheckOutlined />}
                          loading={selectingId === candidate.id}
                          disabled={selected || !candidateGroupMatchesCurrent || candidateLoading || !selectionReady || (selectingId !== null && selectingId !== candidate.id)}
                          onClick={() => selectCandidate(candidate.id)}
                        >
                          {selected ? '已选中' : (hasSelectedCandidate ? '改选为此竞品' : '选择')}
                        </Button>,
                      ].filter(Boolean)}
                    >
                      <List.Item.Meta
                        avatar={candidate.amazon_image_url ? (
                          <Image src={candidate.amazon_image_url} loading="lazy" width={96} height={96} style={{ objectFit: 'cover', borderRadius: 6 }} />
                        ) : null}
                        title={(
                          <Space wrap>
                            <Tag color={selected ? 'success' : 'blue'}>#{candidate.rank}</Tag>
                            <Typography.Link href={candidate.url || `https://www.amazon.com/dp/${candidate.asin}`} target="_blank">
                              {candidate.asin}
                            </Typography.Link>
                            <Tag>Item {candidate.item_code || '-'}</Tag>
                            {candidate.title ? <Text strong>{candidate.title}</Text> : null}
                            {candidate.price ? <Tag color="gold">{candidate.price}</Tag> : null}
                            {candidate.rating ? <Tag color="cyan">{candidate.rating}</Tag> : null}
                            {candidate.review_count ? <Tag>{candidate.review_count}</Tag> : null}
                            {candidate.seller ? <Tag color={candidate.seller === 'Amazon' ? 'green' : 'default'}>{candidate.seller}</Tag> : null}
                            {captureReady ? <Tag color="success">已抓详情</Tag> : null}
                            {captureRunning ? <Tag color="processing">抓详情中</Tag> : null}
                            {captureMissingImage ? <Tag color="warning">缺主图</Tag> : null}
                            {captureMissingTitle ? <Tag color="warning">缺标题</Tag> : null}
                            {captureFailed ? <Tag color="error">抓详情失败</Tag> : null}
                            {!captureStatus ? <Tag>未抓详情</Tag> : null}
                          </Space>
                        )}
                        description={(
                          <Space direction="vertical" size={4}>
                            <Text>{[candidate.brand, candidate.color, candidate.size, candidate.style].filter(Boolean).join(' / ') || '-'}</Text>
                            <Text type="secondary">{candidate.leaf_category || candidate.category_rank || '-'}</Text>
                            {candidate.listing_capture_error ? <Text type="danger">{candidate.listing_capture_error}</Text> : null}
                            <Typography.Paragraph style={{ margin: 0 }} ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}>
                              {candidate.listing_summary || candidate.raw_snippet || ''}
                            </Typography.Paragraph>
                          </Space>
                        )}
                      />
                    </List.Item>
                  );
                }}
              />
              </Spin>
            </Card>
          </Space>
        )}
      </Spin>
    </div>
  );
};

export default ProductCompetitorReview;
