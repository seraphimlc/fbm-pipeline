// @ts-nocheck
import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, Button, Card, Empty, Image, List, message, Select, Space, Spin, Tag, Typography } from 'antd';
import { ArrowLeftOutlined, CheckOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import {
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

const isCompetitorSearchFailed = (product: { status?: string; error_message?: string | null }) => (
  product.status === 'failed' && /同款搜索|StyleSnap/i.test(product.error_message || '')
);

const ProductCompetitorReview: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
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

  const currentIndex = queue.findIndex((item) => item.id === currentId);
  const rawSnapshot = useMemo(() => parseJson(detail?.data?.gigab2b_raw_snapshot, {}), [detail?.data?.gigab2b_raw_snapshot]);
  const sourceImage = detail?.images?.main_image_path || rawSnapshot?.stylesnap_search?.source_image_path || '';

  const loadDataSources = async () => {
    const { data } = await listProductDataSources({ platform: 'giga', enabled: true, page: 1, page_size: 100 });
    setDataSources(data.items);
    setSelectedDataSourceId((current) => current || data.items[0]?.id);
  };

  const loadQueue = async (preferredId?: number | null) => {
    setQueueLoading(true);
    try {
      const { data } = await listProductCompetitorReviewQueue({
        data_source_id: selectedDataSourceId,
        limit: 100,
      });
      const items = data.items;
      setQueue(items);
      const nextId = preferredId && items.some((item) => item.id === preferredId) ? preferredId : items[0]?.id || null;
      setCurrentId(nextId);
      if (!nextId) {
        setDetail(null);
        setCandidateGroup(null);
      }
    } finally {
      setQueueLoading(false);
    }
  };

  const applyDetail = (data: ProductCompetitorReviewDetail) => {
    setDetail(data);
  };

  const loadDetailAndCandidates = async (productId: number) => {
    const cachedDetail = detailCache[productId];
    if (cachedDetail) applyDetail(cachedDetail);
    const cachedCandidates = candidateCache[productId];
    if (cachedCandidates) setCandidateGroup(cachedCandidates);
    setDetailLoading(true);
    try {
      const { data } = await getProductCompetitorReviewDetail(productId);
      setDetailCache((prev) => ({ ...prev, [productId]: data }));
      applyDetail(data);
    } finally {
      setDetailLoading(false);
    }
    setCandidateLoading(true);
    try {
      const { data: group } = await listProductCompetitorCandidates(productId, { enrich_images: false });
      setCandidateCache((prev) => ({ ...prev, [productId]: group }));
      setCandidateGroup(group);
    } catch {
      setCandidateGroup(null);
    } finally {
      setCandidateLoading(false);
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
      setSearchParams({ data_source_id: String(selectedDataSourceId) });
    }
    loadQueue(null).catch(() => message.error('加载竞品选择列表失败'));
  }, [selectedDataSourceId]);
  useEffect(() => { if (currentId) loadDetailAndCandidates(currentId).catch(() => message.error('加载商品候选失败')); }, [currentId]);
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

  const searchCandidates = async (force = false) => {
    if (!detail) return;
    setSearching(true);
    try {
      await searchProductCompetitorCandidates(detail.id, force);
      message.success(force ? '已重新提交候选搜索' : '已提交候选搜索');
      await refreshCurrent();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '候选搜索失败');
    } finally {
      setSearching(false);
    }
  };

  const selectCandidate = async (candidateId: number) => {
    if (!detail) return;
    const candidate = candidateGroup?.candidates?.find((item) => item.id === candidateId);
    const captureReady = candidate?.listing_capture_status === 'captured' && candidate?.title && candidate?.amazon_image_url;
    if (!captureReady) {
      message.warning('这个候选还没有补全标题和主图，先等待补全或点“重新抓取”后再选择');
      return;
    }
    setSelectingId(candidateId);
    try {
      await selectProductCompetitorCandidate(detail.id, candidateId);
      message.success('已选择竞品，系统会抓取竞品详情并继续后续流程');
      const nextQueue = queue.filter((item) => item.id !== detail.id);
      setQueue(nextQueue);
      const nextId = nextQueue[currentIndex >= 0 ? Math.min(currentIndex, nextQueue.length - 1) : 0]?.id || null;
      setCurrentId(nextId);
      if (!nextId) {
        setDetail(null);
        setCandidateGroup(null);
      }
      loadQueue(nextId).catch(() => message.error('刷新竞品选择列表失败'));
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

  const skipCurrent = () => {
    if (currentIndex >= 0 && queue.length > 1) {
      setCurrentId(queue[(currentIndex + 1) % queue.length].id);
    }
  };

  return (
    <div>
      <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 16 }} align="start">
        <div>
          <Title level={4} style={{ margin: 0 }}>选竞品</Title>
          <Text type="secondary">逐条查看已确认图片的商品，选择参考竞品后自动进入下一条。</Text>
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
        message={`待选竞品 ${queue.length} 个${currentId ? `，当前第 ${Math.max(currentIndex + 1, 1)} 个` : ''}`}
      />

      <Spin spinning={queueLoading || detailLoading}>
        {!detail ? (
          <Empty description="当前店铺没有待选择竞品的商品" />
        ) : (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card
              size="small"
              extra={(
                <Space>
                  <Button onClick={skipCurrent}>跳过</Button>
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
                  <Button icon={<SearchOutlined />} loading={searching} onClick={() => searchCandidates(false)}>
                    搜索候选
                  </Button>
                  <Button icon={<ReloadOutlined />} loading={searching} onClick={() => searchCandidates(true)}>
                    重新搜索
                  </Button>
                </Space>
              )}
            >
              <Spin spinning={candidateLoading}>
              <List
                dataSource={candidateGroup?.candidates || []}
                locale={{ emptyText: '暂无候选，先搜索候选' }}
                renderItem={(candidate) => {
                  const selected = candidateGroup?.selected_candidate_id === candidate.id || candidate.is_selected === 1;
                  const captureStatus = candidate.listing_capture_status;
                  const captureReady = captureStatus === 'captured' && candidate.title && candidate.amazon_image_url;
                  const captureFailed = captureStatus === 'failed';
                  const captureRunning = captureStatus === 'queued' || captureStatus === 'running';
                  const captureMissingImage = captureStatus === 'captured' && !candidate.amazon_image_url;
                  return (
                    <List.Item
                      actions={[
                        captureFailed || captureMissingImage ? (
                          <Button
                            key="retry-capture"
                            icon={<ReloadOutlined />}
                            loading={retryingCaptureId === candidate.id}
                            onClick={() => retryCandidateCapture(candidate.id)}
                          >
                            重新抓取
                          </Button>
                        ) : null,
                        <Button
                          key="select"
                          type={selected ? 'default' : 'primary'}
                          icon={<CheckOutlined />}
                          loading={selectingId === candidate.id}
                          disabled={!captureReady}
                          onClick={() => selectCandidate(candidate.id)}
                        >
                          {selected ? '重新选择' : '选择'}
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
                            {candidate.title ? <Text strong>{candidate.title}</Text> : null}
                            {candidate.price ? <Tag color="gold">{candidate.price}</Tag> : null}
                            {candidate.rating ? <Tag color="cyan">{candidate.rating}</Tag> : null}
                            {candidate.review_count ? <Tag>{candidate.review_count}</Tag> : null}
                            {candidate.seller ? <Tag color={candidate.seller === 'Amazon' ? 'green' : 'default'}>{candidate.seller}</Tag> : null}
                            {captureReady ? <Tag color="success">已补全</Tag> : null}
                            {captureRunning ? <Tag color="processing">补全中</Tag> : null}
                            {captureMissingImage ? <Tag color="warning">缺主图</Tag> : null}
                            {captureFailed ? <Tag color="error">补全失败</Tag> : null}
                            {!captureStatus ? <Tag>待补全</Tag> : null}
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
