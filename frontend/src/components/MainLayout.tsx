import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu, Typography } from 'antd';
import {
  CloudSyncOutlined,
  SyncOutlined,
  DatabaseOutlined,
  ExportOutlined,
  PictureOutlined,
  CheckSquareOutlined,
  AimOutlined,
  SettingOutlined,
  UnorderedListOutlined,
  ApiOutlined,
  BarsOutlined,
} from '@ant-design/icons';

const { Sider, Content } = Layout;
const { Title } = Typography;

const MainLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const navigate = useNavigate();
  const location = useLocation();

  const menuItems = [
    {
      key: '/products-root',
      icon: <UnorderedListOutlined />,
      label: '商品工作台',
      children: [
        { key: '/products', icon: <UnorderedListOutlined />, label: '商品列表' },
        { key: '/products/image-review', icon: <CheckSquareOutlined />, label: '图片确认' },
        { key: '/products/competitor-review', icon: <AimOutlined />, label: '选竞品' },
      ],
    },
    { key: '/task-runs', icon: <BarsOutlined />, label: '任务中心' },
    { key: '/export-center', icon: <ExportOutlined />, label: '导出中心' },
    { key: '/inventory-sync', icon: <CloudSyncOutlined />, label: '库存同步' },
    { key: '/asin-sync', icon: <SyncOutlined />, label: 'ASIN同步' },
    { key: '/aplus', icon: <PictureOutlined />, label: 'A+管理' },
    { key: '/upc-pool', icon: <DatabaseOutlined />, label: 'UPC池子' },
    { key: '/data-sources', icon: <ApiOutlined />, label: '店铺维护' },
    { key: '/config', icon: <SettingOutlined />, label: '系统配置' },
  ];

  const selectedKey = location.pathname === '/'
    ? '/products'
    : location.pathname.startsWith('/products/image-review')
        ? '/products/image-review'
        : location.pathname.startsWith('/products/competitor-review')
          ? '/products/competitor-review'
          : location.pathname.startsWith('/tiktok/products/')
        ? '/products'
          : location.pathname.startsWith('/products/')
        ? '/products'
        : location.pathname;
  const defaultOpenKeys = selectedKey.startsWith('/products') ? ['/products-root'] : [];

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f7fb' }}>
      <Sider
        width={220}
        theme="light"
        style={{
          borderRight: '1px solid #f0f0f0',
          minHeight: '100vh',
          position: 'sticky',
          top: 0,
          alignSelf: 'flex-start',
        }}
      >
        <div style={{ padding: '18px 20px 14px', borderBottom: '1px solid #f0f0f0' }}>
          <Title level={4} style={{ margin: 0, lineHeight: 1.25 }}>
            FBM铺货
          </Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>自动化工作台</Typography.Text>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          defaultOpenKeys={defaultOpenKeys}
          items={menuItems}
          onClick={({ key }) => {
            if (key !== '/products-root') navigate(key);
          }}
          style={{ border: 'none', paddingTop: 8 }}
        />
      </Sider>
      <Layout style={{ background: '#f5f7fb', minWidth: 0 }}>
        <Content
          style={{
            padding: '24px',
            width: '100%',
            maxWidth: 'calc(100vw - 220px)',
            minWidth: 0,
          }}
        >
          {children}
        </Content>
      </Layout>
    </Layout>
  );
};

export default MainLayout;
