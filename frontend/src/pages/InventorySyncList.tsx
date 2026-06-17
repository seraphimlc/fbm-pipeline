import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Empty, Input, Popconfirm, Select, Space, Table, Tag, Typography, message } from 'antd';
import { CloudSyncOutlined, DollarOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import {
  createGigaInventorySyncTaskRuns,
  createGigaPriceSyncTaskRuns,
  listGigaInventory,
  listProductDataSources,
} from '../api';
import type { GigaInventory, ProductDataSource } from '../api';

const { Text, Title } = Typography;

const stockText = (value?: number | null) => value === null || value === undefined ? '-' : value;

const statusTag = (status?: string | null) => {
  if (status === 'in_stock' || status === 'available') return <Tag color="success">有货</Tag>;
  if (status === 'out_of_stock' || status === 'unavailable') return <Tag color="error">无货</Tag>;
  return <Tag>{status || '-'}</Tag>;
};

const formatDateTime = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '-';

const distributionText = (value?: string | null) => {
  if (!value) return '-';
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed) || parsed.length === 0) return '-';
    return `${parsed.length} 个仓`;
  } catch {
    return value;
  }
};

const InventorySyncList: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<GigaInventory[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [priceSyncing, setPriceSyncing] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [dataSources, setDataSources] = useState<ProductDataSource[]>([]);
  const [selectedDataSourceId, setSelectedDataSourceId] = useState<number | undefined>();
  const [skuInput, setSkuInput] = useState('');
  const [skuCode, setSkuCode] = useState('');
  const [availabilityStatus, setAvailabilityStatus] = useState<string | undefined>();
  const [pulledAt, setPulledAt] = useState<string | null>(null);

  const summary = useMemo(() => {
    const inStock = items.filter((item) => (item.stock_qty || 0) > 0).length;
    const outOfStock = items.filter((item) => (item.stock_qty || 0) <= 0).length;
    return { inStock, outOfStock };
  }, [items]);
  const activeDataSource = useMemo(
    () => dataSources.find((source) => source.id === selectedDataSourceId),
    [dataSources, selectedDataSourceId],
  );
  const activeSite = activeDataSource?.site || 'US';
  const hasInventoryFilter = Boolean(skuCode || availabilityStatus);
  const inventoryEmptyText = () => {
    if (!selectedDataSourceId) {
      return (
        <Empty description="还没有选择可用店铺">
          <Button onClick={() => navigate('/data-sources')}>去维护店铺</Button>
        </Empty>
      );
    }
    if (!pulledAt && !hasInventoryFilter) {
      return (
        <Empty description="当前店铺还没有库存同步快照">
          <Space>
            <Button type="primary" icon={<CloudSyncOutlined />} loading={syncing} onClick={handleSync}>同步库存</Button>
            <Button onClick={() => navigate('/task-runs')}>查看任务中心</Button>
          </Space>
        </Empty>
      );
    }
    if (hasInventoryFilter) {
      return (
        <Empty description="当前筛选没有库存记录">
          <Space>
            <Button onClick={() => { setSkuInput(''); setSkuCode(''); setAvailabilityStatus(undefined); setPage(1); }}>清空筛选</Button>
            <Button onClick={() => navigate('/task-runs')}>查看最近同步任务</Button>
          </Space>
        </Empty>
      );
    }
    return (
      <Empty description="当前店铺暂无库存记录">
        <Button onClick={() => navigate('/task-runs')}>查看最近同步任务</Button>
      </Empty>
    );
  };

  const fetchDataSources = async () => {
    try {
      const { data } = await listProductDataSources({ platform: 'giga', enabled: true, page: 1, page_size: 100 });
      setDataSources(data.items);
      setSelectedDataSourceId((current) => (
        current && data.items.some((source) => source.id === current)
          ? current
          : data.items[0]?.id
      ));
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载店铺失败');
    }
  };

  const fetchInventory = async () => {
    if (!selectedDataSourceId) {
      setItems([]);
      setTotal(0);
      setPulledAt(null);
      return;
    }
    setLoading(true);
    try {
      const { data } = await listGigaInventory({
        site: activeSite,
        data_source_id: selectedDataSourceId,
        page,
        page_size: pageSize,
        sku_code: skuCode || undefined,
        availability_status: availabilityStatus,
      });
      setItems(data.items);
      setTotal(data.total);
      setPulledAt(data.pulled_at);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '库存数据加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDataSources(); }, []);
  useEffect(() => {
    if (selectedDataSourceId) fetchInventory();
  }, [page, pageSize, selectedDataSourceId, activeSite, skuCode, availabilityStatus]);

  const handleSync = async () => {
    if (!selectedDataSourceId) {
      message.warning('请先维护并选择店铺');
      return;
    }
    setSyncing(true);
    try {
      const { data } = await createGigaInventorySyncTaskRuns({
        data_source_ids: [selectedDataSourceId],
      });
      message.success(`已创建库存同步任务：${data.runs.map((run) => `#${run.id}`).join('、')}`);
      navigate('/task-runs');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '创建库存同步任务失败');
    } finally {
      setSyncing(false);
    }
  };

  const handlePriceSync = async () => {
    if (!selectedDataSourceId) {
      message.warning('请先维护并选择店铺');
      return;
    }
    setPriceSyncing(true);
    try {
      const { data } = await createGigaPriceSyncTaskRuns({
        data_source_ids: [selectedDataSourceId],
      });
      message.success(`已创建价格同步任务：${data.runs.map((run) => `#${run.id}`).join('、')}`);
      navigate('/task-runs');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '创建价格同步任务失败');
    } finally {
      setPriceSyncing(false);
    }
  };

  const columns = [
    {
      title: 'SKU',
      dataIndex: 'sku_code',
      width: 150,
      fixed: 'left' as const,
      render: (value: string) => <Text strong>{value}</Text>,
    },
    { title: 'Item', dataIndex: 'item_code', width: 150, render: (value: string | null) => value || '-' },
    {
      title: '标题',
      dataIndex: 'product_name',
      width: 320,
      ellipsis: true,
      render: (value: string | null) => value || '-',
    },
    { title: '库存', dataIndex: 'stock_qty', width: 90, render: stockText },
    { title: 'Seller库存', dataIndex: 'seller_available_inventory', width: 110, render: stockText },
    { title: 'Buyer库存', dataIndex: 'total_buyer_available_inventory', width: 110, render: stockText },
    { title: 'Seller分仓', dataIndex: 'seller_inventory_distribution', width: 110, render: distributionText },
    { title: 'Buyer分仓', dataIndex: 'buyer_inventory_distribution', width: 110, render: distributionText },
    { title: '状态', dataIndex: 'availability_status', width: 90, render: statusTag },
    { title: '同步时间', dataIndex: 'pulled_at', width: 170, render: formatDateTime },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 16, alignItems: 'center' }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>库存同步</Title>
          <Text type="secondary">最新同步：{formatDateTime(pulledAt)}，当前页有货 {summary.inStock} / 无货 {summary.outOfStock}</Text>
        </div>
        <Space>
          <Select
            placeholder="选择店铺"
            value={selectedDataSourceId}
            style={{ width: 240 }}
            options={dataSources.map((source) => ({
              value: source.id,
              label: `${source.name} · ${source.site}`,
            }))}
            onChange={(value) => { setSelectedDataSourceId(value); setPage(1); }}
          />
          <Button icon={<ReloadOutlined />} onClick={fetchInventory}>刷新</Button>
          <Popconfirm title="同步最新 GIGA 价格？" okText="开始同步" cancelText="取消" onConfirm={handlePriceSync}>
            <Button icon={<DollarOutlined />} loading={priceSyncing}>同步价格</Button>
          </Popconfirm>
          <Popconfirm title="同步最新 GIGA 库存？" okText="开始同步" cancelText="取消" onConfirm={handleSync}>
            <Button type="primary" icon={<CloudSyncOutlined />} loading={syncing}>同步库存</Button>
          </Popconfirm>
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="库存按 SKU 展示，数据来自最新 GIGA Open API 库存快照；Amazon 库存模板导出也会使用这里的最新库存。"
      />

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <Input
          allowClear
          style={{ width: 260 }}
          prefix={<SearchOutlined />}
          placeholder="搜索 SKU"
          value={skuInput}
          onChange={(event) => setSkuInput(event.target.value)}
          onPressEnter={() => { setSkuCode(skuInput.trim()); setPage(1); }}
        />
        <Button onClick={() => { setSkuCode(skuInput.trim()); setPage(1); }}>搜索</Button>
        <Select
          allowClear
          style={{ width: 140 }}
          placeholder="库存状态"
          value={availabilityStatus}
          options={[
            { value: 'in_stock', label: '有货' },
            { value: 'out_of_stock', label: '无货' },
          ]}
          onChange={(value) => { setAvailabilityStatus(value); setPage(1); }}
        />
      </div>

      <Table
        rowKey="sku_code"
        dataSource={items}
        columns={columns}
        loading={loading}
        scroll={{ x: 1320 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (value) => `共 ${value} 个 SKU`,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          },
        }}
        locale={{ emptyText: inventoryEmptyText() }}
      />
    </div>
  );
};

export default InventorySyncList;
