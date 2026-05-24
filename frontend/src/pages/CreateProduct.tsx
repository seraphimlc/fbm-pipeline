import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Form, Input, Button, Typography, message, Select } from 'antd';
import { createProduct } from '../api';

const { Title } = Typography;

const CreateProduct: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  const handleSubmit = async (values: { gigab2b_url: string; competitor_asin?: string; brand?: string }) => {
    setLoading(true);
    try {
      const payload = {
        ...values,
        gigab2b_url: values.gigab2b_url.trim(),
        competitor_asin: values.competitor_asin?.trim() || undefined,
      };
      const { data } = await createProduct(payload);
      message.success('任务创建成功');
      navigate(`/products/${data.id}`);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '创建失败');
    } finally {
      setLoading(false);
    }
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
            label="原始数据链接"
            name="gigab2b_url"
            rules={[{ required: true, message: '请输入商品链接' }]}
          >
            <Input placeholder="粘贴供应商商品页链接，例如 GIGAB2B 商品链接" />
          </Form.Item>

          <Form.Item
            label="竞品 ASIN"
            name="competitor_asin"
            extra="可稍后补充；缺少时关键词和类目步骤会需要人工处理。"
          >
            <Input placeholder="B0GMWKDNBC" />
          </Form.Item>

          <Form.Item label="品牌名" name="brand">
            <Select
              options={[
                { label: 'Vindhvisk', value: 'Vindhvisk' },
              ]}
            />
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
