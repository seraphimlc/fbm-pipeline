import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import MainLayout from './components/MainLayout';
import ProductList from './pages/ProductList';
import ProductDetail from './pages/ProductDetail';
import CreateProduct from './pages/CreateProduct';

const App: React.FC = () => (
  <ConfigProvider locale={zhCN}>
    <AntApp>
      <BrowserRouter>
        <MainLayout>
          <Routes>
            <Route path="/" element={<Navigate to="/products" replace />} />
            <Route path="/products" element={<ProductList />} />
            <Route path="/products/new" element={<CreateProduct />} />
            <Route path="/products/:id" element={<ProductDetail />} />
          </Routes>
        </MainLayout>
      </BrowserRouter>
    </AntApp>
  </ConfigProvider>
);

export default App;
