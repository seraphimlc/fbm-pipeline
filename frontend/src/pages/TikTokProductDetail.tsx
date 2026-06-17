import React, { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Alert, Button, Descriptions, Image, Space, Spin, Table, Tag, Typography, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { getTikTokProduct } from '../api';
import type { TikTokProductDetail, TikTokProductSku } from '../api';

const { Title, Text } = Typography;

const imageProxyUrl = (value: string | null | undefined) => {
  if (!value) return '';
  if (/^https?:\/\//i.test(value)) return value;
  return `/api/images/${value}`;
};

const galleryImageUrl = (value: string | Record<string, unknown>) => {
  if (typeof value === 'string') return value;
  const raw = value.url || value.image_url || value.local_path || value.path;
  return typeof raw === 'string' ? raw : '';
};

const moneyText = (value: number | null | undefined) => (
  value === null || value === undefined ? '-' : `USD ${Number(value).toFixed(2)}`
);

const statusTag = (status: string) => {
  if (status === 'export_ready') return <Tag color="success">待导出</Tag>;
  if (status === 'missing_required_info') return <Tag color="warning">待补资料</Tag>;
  if (status === 'exported') return <Tag color="green">已导出</Tag>;
  if (status === 'failed') return <Tag color="error">失败</Tag>;
  return <Tag>{status || '草稿'}</Tag>;
};

const TikTokProductDetailPage: React.FC = () => {
  const { id } = useParams();
  const [detail, setDetail] = useState<TikTokProductDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const loadDetail = async () => {
    if (!id) return;
    setLoading(true);
    try {
      const { data } = await getTikTokProduct(id);
      setDetail(data);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载 TikTok 商品详情失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadDetail(); }, [id]);

  const gallery = useMemo(() => (
    (detail?.gallery_images || [])
      .map(galleryImageUrl)
      .filter(Boolean)
      .slice(0, 12)
  ), [detail]);

  const skuColumns = [
    {
      title: '图',
      dataIndex: 'main_image_url',
      width: 72,
      render: (value: string | null) => value ? (
        <Image src={imageProxyUrl(value)} width={44} height={44} style={{ objectFit: 'cover', borderRadius: 4 }} />
      ) : '-',
    },
    {
      title: 'SKU',
      dataIndex: 'sku_code',
      width: 150,
      render: (value: string) => <Text strong>{value}</Text>,
    },
    {
      title: '标题',
      dataIndex: 'title',
      ellipsis: true,
      width: 260,
      render: (value: string | null) => value || '-',
    },
    {
      title: '变体',
      dataIndex: 'variation_attributes',
      width: 260,
      render: (value: Record<string, unknown>) => {
        const entries = Object.entries(value || {}).filter(([, v]) => v !== null && v !== undefined && String(v));
        return entries.length ? (
          <Space size={4} wrap>
            {entries.map(([key, item]) => <Tag key={key}>{key}: {String(item)}</Tag>)}
          </Space>
        ) : '-';
      },
    },
    { title: '采购价', dataIndex: 'purchase_price', width: 110, render: moneyText },
    { title: '运费', dataIndex: 'shipping_fee', width: 100, render: moneyText },
    { title: 'TikTok售价', dataIndex: 'tiktok_price', width: 120, render: moneyText },
    {
      title: '分仓库存',
      dataIndex: 'warehouse_inventory',
      width: 300,
      render: (_: unknown, record: TikTokProductSku) => (
        record.warehouse_inventory.length ? (
          <Space size={4} wrap>
            {record.warehouse_inventory.map((item) => (
              <Tag key={`${record.sku_code}-${item.warehouse_code}`}>{item.warehouse_code}: {item.quantity}</Tag>
            ))}
            <Tag color="blue">总 {record.warehouse_inventory_total}</Tag>
          </Space>
        ) : <Text type="danger">缺分仓库存</Text>
      ),
    },
    {
      title: '缺失字段',
      dataIndex: 'missing_fields',
      width: 180,
      render: (value: string[]) => (
        value.length ? <Space size={4} wrap>{value.map((item) => <Tag color="warning" key={item}>{item}</Tag>)}</Space> : <Tag color="success">完整</Tag>
      ),
    },
  ];

  if (loading && !detail) {
    return <Spin />;
  }

  if (!detail) {
    return (
      <Space direction="vertical">
        <Button icon={<ReloadOutlined />} onClick={loadDetail}>刷新</Button>
        <Text type="secondary">暂无数据</Text>
      </Space>
    );
  }

  return (
    <div className="tiktok-product-detail">
      <section className="product-workbench-hero">
        <div className="product-workbench-title">
          <Title level={4} style={{ margin: 0 }}>{detail.item_code || `商品 #${detail.id}`}</Title>
          <Text type="secondary">{detail.title || '-'} · {detail.data_source_name || 'TikTok店铺'}</Text>
        </div>
        <Space wrap>
          {statusTag(detail.status)}
          <Button icon={<ReloadOutlined />} loading={loading} onClick={loadDetail}>刷新</Button>
        </Space>
      </section>

      {detail.missing_fields.length ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`缺失字段：${detail.missing_fields.join('、')}`}
        />
      ) : null}

      <section className="product-detail-band">
        <Descriptions size="small" column={3} bordered>
          <Descriptions.Item label="来源站点">{detail.source_site || '-'}</Descriptions.Item>
          <Descriptions.Item label="来源批次">{detail.source_batch_id || '-'}</Descriptions.Item>
          <Descriptions.Item label="来源状态">{detail.source_status || '-'}</Descriptions.Item>
          <Descriptions.Item label="固定运费">{moneyText(detail.pricing_formula.shipping_fee)}</Descriptions.Item>
          <Descriptions.Item label="价格缓冲">{moneyText(detail.pricing_formula.buffer)}</Descriptions.Item>
          <Descriptions.Item label="倍率">{detail.pricing_formula.multiplier}</Descriptions.Item>
        </Descriptions>
      </section>

      <section className="product-detail-band">
        <Space align="start" size={16} wrap>
          {detail.main_image_url ? (
            <Image src={imageProxyUrl(detail.main_image_url)} width={160} height={160} style={{ objectFit: 'cover', borderRadius: 6 }} />
          ) : null}
          {gallery.map((url) => (
            <Image key={url} src={imageProxyUrl(url)} width={96} height={96} style={{ objectFit: 'cover', borderRadius: 6 }} />
          ))}
        </Space>
      </section>

      <section className="product-detail-band">
        <Table
          rowKey="sku_code"
          dataSource={detail.skus}
          columns={skuColumns}
          pagination={false}
          scroll={{ x: 1400 }}
          size="middle"
        />
      </section>
    </div>
  );
};

export default TikTokProductDetailPage;
