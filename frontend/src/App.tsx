import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import MainLayout from './components/MainLayout';
import ProductList from './pages/ProductList';
import ProductDetail from './pages/ProductDetail';
import TikTokProductDetail from './pages/TikTokProductDetail';
import ProductImageReview from './pages/ProductImageReview';
import CreateProduct from './pages/CreateProduct';
import CatalogList from './pages/CatalogList';
import InventorySyncList from './pages/InventorySyncList';
import AsinSyncList from './pages/AsinSyncList';
import AplusManagement from './pages/AplusManagement';
import ConfigPage from './pages/ConfigPage';
import ProductDataSourceList from './pages/ProductDataSourceList';
import OfflineTaskCenter from './pages/OfflineTaskCenter';
import TaskRunCenter from './pages/TaskRunCenter';
import UpcPoolPage from './pages/UpcPoolPage';

const App: React.FC = () => (
  <ConfigProvider locale={zhCN}>
    <AntApp>
      <BrowserRouter>
        <MainLayout>
          <Routes>
            <Route path="/" element={<Navigate to="/products" replace />} />
            <Route path="/giga-items" element={<Navigate to="/products" replace />} />
            <Route path="/products" element={<ProductList />} />
            <Route path="/products/image-review" element={<ProductImageReview />} />
            <Route path="/products/competitor-review" element={<Navigate to="/products" replace />} />
            <Route path="/offline-tasks" element={<OfflineTaskCenter />} />
            <Route path="/task-runs" element={<TaskRunCenter />} />
            <Route path="/export-center" element={<CatalogList />} />
            <Route path="/inventory-sync" element={<InventorySyncList />} />
            <Route path="/asin-sync" element={<AsinSyncList />} />
            <Route path="/aplus" element={<AplusManagement />} />
            <Route path="/aplus-upload" element={<Navigate to="/aplus" replace />} />
            <Route path="/upc-pool" element={<UpcPoolPage />} />
            <Route path="/data-sources" element={<ProductDataSourceList />} />
            <Route path="/config" element={<ConfigPage />} />
            <Route path="/products/new" element={<CreateProduct />} />
            <Route path="/products/:id" element={<ProductDetail />} />
            <Route path="/tiktok/products/:id" element={<TikTokProductDetail />} />
          </Routes>
        </MainLayout>
      </BrowserRouter>
    </AntApp>
  </ConfigProvider>
);

export default App;
