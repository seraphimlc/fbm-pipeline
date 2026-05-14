import React from 'react';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { Layout, Menu, Typography } from 'antd';
import {
  ShoppingOutlined,
  PlusCircleOutlined,
  SettingOutlined,
} from '@ant-design/icons';

const { Header, Content } = Layout;
const { Title } = Typography;

const MainLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const navigate = useNavigate();
  const location = useLocation();

  const menuItems = [
    { key: '/products', icon: <ShoppingOutlined />, label: '商品列表' },
    { key: '/products/new', icon: <PlusCircleOutlined />, label: '创建任务' },
    { key: '/config', icon: <SettingOutlined />, label: '系统配置' },
  ];

  const selectedKey = location.pathname === '/'
    ? '/products'
    : location.pathname.startsWith('/products/new')
      ? '/products/new'
      : location.pathname.startsWith('/products/')
        ? '/products'
        : location.pathname;

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0' }}>
        <Title level={4} style={{ margin: 0, marginRight: 40, whiteSpace: 'nowrap' }}>
          📦 FBM 铺货自动化
        </Title>
        <Menu
          mode="horizontal"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, border: 'none' }}
        />
      </Header>
      <Content style={{ padding: '24px', maxWidth: 1400, margin: '0 auto', width: '100%' }}>
        {children}
      </Content>
    </Layout>
  );
};

export default MainLayout;
