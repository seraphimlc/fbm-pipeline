// @ts-nocheck
import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Descriptions, Tag, Steps, Tabs, Button, Space, Typography, Spin, message, Popconfirm, Image } from 'antd';
import {
  ArrowLeftOutlined, PlayCircleOutlined, RedoOutlined,
  PauseOutlined, ReloadOutlined, DeleteOutlined,
} from '@ant-design/icons';
import { getProduct, startPipeline, retryStep, pausePipeline, deleteProduct, STEP_LABELS, STATUS_COLORS } from '../api';
import type { ProductDetail } from '../api';

const { Title, Text } = Typography;

/** 将本地文件路径转为后端图片代理URL */
const imgUrl = (localPath: string | null | undefined) => {
  if (!localPath) return '';
  return `/api/images/${localPath}`;
};

const ProductDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [loading, setLoading] = useState(true);
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
    const isRunning = !['completed', 'failed', 'paused', 'created'].includes(product.status);
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
    return 7; // completed
  })();

  const stepStatus = product.status === 'failed' ? 'error' : product.status === 'completed' ? 'finish' : 'process';

  // 安全解析JSON
  const tabItems = [
    {
      key: 'basic',
      label: '📋 基本信息',
      children: (
        <Descriptions bordered column={2} size="small">
          <Descriptions.Item label="商品ID">{data?.item_code || '-'}</Descriptions.Item>
          <Descriptions.Item label="标题">{data?.title || '-'}</Descriptions.Item>
          <Descriptions.Item label="颜色">{data?.color || '-'}</Descriptions.Item>
          <Descriptions.Item label="材质">{data?.material || '-'}</Descriptions.Item>
          <Descriptions.Item label="填充物">{data?.filler || '-'}</Descriptions.Item>
          <Descriptions.Item label="产品类型">{data?.product_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="尺寸(长×宽×高)">{data ? `${data.dimension_length}×${data.dimension_width}×${data.dimension_height} 英寸` : '-'}</Descriptions.Item>
          <Descriptions.Item label="重量">{data?.weight ? `${data.weight} 磅` : '-'}</Descriptions.Item>
          <Descriptions.Item label="货值">{data?.value_total != null ? `$${data.value_total}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="含运费成本">{data?.estimated_total != null ? `$${data.estimated_total}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="建议售价">{data?.suggested_price != null ? `$${data.suggested_price}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="利润率">{data?.profit_rate ? `${(data.profit_rate * 100).toFixed(1)}%` : '-'}</Descriptions.Item>
          <Descriptions.Item label="库存">{data?.stock ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="供应商">{data?.seller || '-'}</Descriptions.Item>
          <Descriptions.Item label="图片数量">{data?.image_count ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="素材目录">{data?.material_dir || '-'}</Descriptions.Item>
        </Descriptions>
      ),
    },
    {
      key: 'listing',
      label: '📝 Listing文案',
      children: (
        <div>
          <Card title="标题" size="small" style={{ marginBottom: 12 }}>
            <Text>{data?.listing_title || '（未生成）'}</Text>
          </Card>
          <Card title="五点描述" size="small" style={{ marginBottom: 12 }}>
            {data?.listing_bullets ? (() => {
              try {
                const bullets = JSON.parse(data.listing_bullets) as string[];
                return <ul>{bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>;
              } catch { return <Text type="secondary">解析失败</Text>; }
            })() : <Text type="secondary">（未生成）</Text>}
          </Card>
          <Card title="Search Terms" size="small" style={{ marginBottom: 12 }}>
            <Text>{data?.listing_search_terms || '（未生成）'}</Text>
          </Card>
          <Card title="关键词 Top20" size="small">
            {data?.keywords_top ? (() => {
              try {
                const kws = JSON.parse(data.keywords_top) as string[];
                return <Space wrap>{kws.map((kw, i) => <Tag key={i}>{kw}</Tag>)}</Space>;
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
            {images?.main_image_path ? (
              <Image src={imgUrl(images.main_image_path)} width={200} alt="主图" />
            ) : <Text type="secondary">（未选择）</Text>}
          </Card>
          <Card title="副图" size="small">
            {images?.gallery_images ? (() => {
              try {
                const imgs = JSON.parse(images.gallery_images) as { path: string }[];
                return <Space wrap>{imgs.map((img, i) => <Image key={i} src={imgUrl(typeof img === 'string' ? img : img.path)} width={120} alt={`副图${i+1}`} />)}</Space>;
              } catch { return <Text type="secondary">解析失败</Text>; }
            })() : <Text type="secondary">（未选择）</Text>}
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
            {aplus?.aplus_images ? (() => {
              try {
                const imgs = JSON.parse(aplus.aplus_images) as any[];
                return <Space wrap>{imgs.map((img, i) => <Image key={i} src={imgUrl(img.path)} width={200} alt={`A+图${i+1}`} />)}</Space>;
              } catch { return <Text type="secondary">解析失败</Text>; }
            })() : <Text type="secondary">（未生成）</Text>}
          </Card>
        </div>
      ),
    },
  ];

  return (
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
          {!['completed', 'failed', 'created', 'paused'].includes(product.status) && (
            <Button icon={<PauseOutlined />} onClick={async () => { await pausePipeline(product.id); fetchDetail(); }}>
              暂停
            </Button>
          )}
          <Popconfirm title="确定删除此商品？" onConfirm={async () => { await deleteProduct(product.id); navigate('/products'); }}>
            <Button danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      </div>

      {/* Pipeline 进度条 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Steps
          current={product.status === 'completed' ? pipelineSteps.length : currentStepIndex}
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
  );
};

export default ProductDetail;
