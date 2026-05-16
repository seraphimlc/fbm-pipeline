import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import MainLayout from './components/MainLayout';
import ProductList from './pages/ProductList';
import ProductDetail from './pages/ProductDetail';
import CreateProduct from './pages/CreateProduct';
import CatalogList from './pages/CatalogList';
import AsinSyncList from './pages/AsinSyncList';
import AplusUploadList from './pages/AplusUploadList';
import ConfigPage from './pages/ConfigPage';

const App: React.FC = () => (
  <ConfigProvider locale={zhCN}>
    <AntApp>
      <BrowserRouter>
        <MainLayout>
          <Routes>
            <Route path="/" element={<Navigate to="/products" replace />} />
            <Route path="/products" element={<ProductList />} />
            <Route path="/catalog" element={<CatalogList />} />
            <Route path="/asin-sync" element={<AsinSyncList />} />
            <Route path="/aplus-upload" element={<AplusUploadList />} />
            <Route path="/config" element={<ConfigPage />} />
            <Route path="/products/new" element={<CreateProduct />} />
            <Route path="/products/:id" element={<ProductDetail />} />
          </Routes>
        </MainLayout>
      </BrowserRouter>
    </AntApp>
  </ConfigProvider>
);

export default App;
