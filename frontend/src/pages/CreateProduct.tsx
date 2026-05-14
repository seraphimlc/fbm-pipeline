import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Form, Input, Button, Typography, message } from 'antd';
import { createProduct } from '../api';

const { Title } = Typography;

const CreateProduct: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  const handleSubmit = async (values: { gigab2b_url: string; competitor_asin?: string; brand?: string }) => {
    setLoading(true);
    try {
      const { data } = await createProduct(values);
      message.success('任务创建成功');
      navigate(`/products/${data.id}`);
    } catch {
      message.error('创建失败');
    }
    setLoading(false);
  };

  return (
    <div style={{ maxWidth: 600 }}>
      <Title level={4}>创建新任务</Title>
      <Card>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{ brand: 'Vindhvisk' }}
        >
          <Form.Item
            label="大健云仓商品链接"
            name="gigab2b_url"
            rules={[{ required: true, message: '请输入商品链接' }]}
          >
            <Input placeholder="https://www.gigab2b.com/product-detail/xxxxx" />
          </Form.Item>

          <Form.Item
            label="竞品 ASIN"
            name="competitor_asin"
            rules={[{ required: true, message: '请输入竞品ASIN' }]}
          >
            <Input placeholder="B0GMWKDNBC" />
          </Form.Item>

          <Form.Item label="品牌名" name="brand">
            <Input placeholder="Vindhvisk" />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} size="large">
              创建任务
            </Button>
            <Button style={{ marginLeft: 12 }} onClick={() => navigate('/products')}>
              取消
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
};

export default CreateProduct;
