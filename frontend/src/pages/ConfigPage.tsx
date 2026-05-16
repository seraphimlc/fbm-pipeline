import React, { useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, Form, Input, InputNumber, Select, Spin, Switch, Tag, Typography, message } from 'antd';
import { SaveOutlined, ReloadOutlined } from '@ant-design/icons';
import { getConfig, updateConfig } from '../api';
import type { SystemConfig, SystemConfigUpdate } from '../api';

const { Title, Text } = Typography;

const yesNo = (value: boolean) => (
  value ? <Tag color="success">已配置</Tag> : <Tag color="warning">未配置</Tag>
);

const ConfigPage: React.FC = () => {
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [form] = Form.useForm<SystemConfigUpdate>();

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const { data } = await getConfig();
      setConfig(data);
      form.setFieldsValue({
        default_brand: data.default_brand,
        product_base_dir: data.product_base_dir,
        pipeline_max_concurrency: data.pipeline_max_concurrency,
        browser_workflow_concurrency: data.browser_workflow_concurrency,
        bulk_start_max_tasks: data.bulk_start_max_tasks,
        aplus_concurrency: data.aplus_concurrency,
        poll_interval: data.poll_interval,
        step3_4_parallel: data.step3_4_parallel,
        step1_extract_retry_attempts: data.step1_extract_retry_attempts,
        step1_extract_retry_delay_seconds: data.step1_extract_retry_delay_seconds,
        step1_download_timeout_seconds: data.step1_download_timeout_seconds,
        step1_material_package_priority: data.step1_material_package_priority,
        step1_price_missing_policy: data.step1_price_missing_policy,
        step1_material_missing_policy: data.step1_material_missing_policy,
        step1_allow_existing_materials: data.step1_allow_existing_materials,
        pricing_net_revenue_rate: data.pricing_net_revenue_rate,
        pricing_target_margin_rate: data.pricing_target_margin_rate,
        pricing_min_profit: data.pricing_min_profit,
        pricing_fixed_cost: data.pricing_fixed_cost,
        pricing_return_credit_rate: data.pricing_return_credit_rate,
        step3_manual_login_on_auth_failure: data.step3_manual_login_on_auth_failure,
        step4_missing_asin_policy: data.step4_missing_asin_policy,
        step4_category_missing_policy: data.step4_category_missing_policy,
        step4_allow_existing_category: data.step4_allow_existing_category,
        step5_llm_temperature: data.step5_llm_temperature,
        step5_llm_max_tokens: data.step5_llm_max_tokens,
        step5_title_max_chars: data.step5_title_max_chars,
        step5_bullet_max_chars: data.step5_bullet_max_chars,
        step5_search_terms_max_bytes: data.step5_search_terms_max_bytes,
        llm_model: data.llm_model,
        vlm_model: data.vlm_model,
        vlm_use_llm_api: data.vlm_use_llm_api,
        gpt_image_model: data.gpt_image_model,
        gpt_image_use_llm_api: data.gpt_image_use_llm_api,
        aplus_image_width: data.aplus_image_width,
	        aplus_image_height: data.aplus_image_height,
	        aplus_image_jpeg_quality: data.aplus_image_jpeg_quality,
	        aplus_image_api_retries: data.aplus_image_api_retries,
	        aplus_image_overwrite_policy: data.aplus_image_overwrite_policy,
      });
    } catch {
      message.error('系统配置加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchConfig(); }, []);

  const saveConfig = async (values: SystemConfigUpdate) => {
    setSaving(true);
    try {
      await updateConfig(values);
      setSaved(true);
      message.success('配置已保存，重启后生效');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  if (!config) return <Alert type="error" message="系统配置不可用" />;

  return (
    <div>
      <Title level={4}>系统配置</Title>
      <Alert
        type={saved ? 'warning' : 'info'}
        showIcon
        style={{ marginBottom: 16 }}
        message={saved ? '配置已保存，等待重启生效' : '修改后重启后端生效'}
        description={(
          <span>
            配置会写入 <Text code>{config.env_file}</Text>。当前运行中的后端仍使用旧配置，重启后端后会读取新值。
          </span>
        )}
      />

      <Form form={form} layout="vertical" onFinish={saveConfig}>
        <Card
          title="运行并发"
          size="small"
          style={{ marginBottom: 16 }}
          extra={<Button type="primary" icon={<SaveOutlined />} htmlType="submit" loading={saving}>保存配置</Button>}
        >
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(180px, 1fr))', gap: 16 }}>
            <Form.Item label="Pipeline 最大并发" name="pipeline_max_concurrency" rules={[{ required: true }]}>
              <InputNumber min={1} max={20} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="浏览器流程并发" name="browser_workflow_concurrency" rules={[{ required: true }]}>
              <InputNumber min={1} max={5} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="批量启动上限" name="bulk_start_max_tasks" rules={[{ required: true }]}>
              <InputNumber min={1} max={1000} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="A+ 出图并发" name="aplus_concurrency" rules={[{ required: true }]}>
              <InputNumber min={1} max={10} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="前端轮询间隔（秒）" name="poll_interval" rules={[{ required: true }]}>
              <InputNumber min={1} max={60} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="Step3/4 并行" name="step3_4_parallel" valuePropName="checked">
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
          </div>
        </Card>

        <Card title="Step 1 采集/素材" size="small" style={{ marginBottom: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(180px, 1fr))', gap: 16 }}>
            <Form.Item label="采集重试次数" name="step1_extract_retry_attempts" rules={[{ required: true }]}>
              <InputNumber min={1} max={20} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="重试等待（秒）" name="step1_extract_retry_delay_seconds" rules={[{ required: true }]}>
              <InputNumber min={0} max={60} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="素材下载超时（秒）" name="step1_download_timeout_seconds" rules={[{ required: true }]}>
              <InputNumber min={30} max={1800} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="素材包优先级" name="step1_material_package_priority" rules={[{ required: true }]}>
              <Input placeholder="To B素材包,Retail Ready素材包,Information" />
            </Form.Item>
            <Form.Item label="价格缺失策略" name="step1_price_missing_policy" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'manual_review', label: '待人工处理' },
                  { value: 'fail', label: '标记失败' },
                  { value: 'continue', label: '继续执行' },
                ]}
              />
            </Form.Item>
            <Form.Item label="素材缺失策略" name="step1_material_missing_policy" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'manual_review', label: '待人工处理' },
                  { value: 'fail', label: '标记失败' },
                  { value: 'continue', label: '继续执行' },
                ]}
              />
            </Form.Item>
            <Form.Item label="允许使用已有本地素材" name="step1_allow_existing_materials" valuePropName="checked">
              <Switch checkedChildren="允许" unCheckedChildren="关闭" />
            </Form.Item>
          </div>
        </Card>

        <Card title="Step 2 定价/利润" size="small" style={{ marginBottom: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(180px, 1fr))', gap: 16 }}>
            <Form.Item label="净收入比例" name="pricing_net_revenue_rate" rules={[{ required: true }]}>
              <InputNumber min={0.01} max={0.99} step={0.005} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="目标净利率" name="pricing_target_margin_rate" rules={[{ required: true }]}>
              <InputNumber min={0} max={0.5} step={0.005} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="最低利润（美元）" name="pricing_min_profit" rules={[{ required: true }]}>
              <InputNumber min={0} max={1000} step={0.5} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="固定成本（美元）" name="pricing_fixed_cost" rules={[{ required: true }]}>
              <InputNumber min={0} max={1000} step={0.5} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="退货抵扣比例" name="pricing_return_credit_rate" rules={[{ required: true }]}>
              <InputNumber min={0} max={0.99} step={0.005} style={{ width: '100%' }} />
            </Form.Item>
          </div>
        </Card>

        <Card title="Step 3 关键词" size="small" style={{ marginBottom: 16 }}>
          <Form.Item label="未登录时打开卖家精灵让人工登录" name="step3_manual_login_on_auth_failure" valuePropName="checked">
            <Switch checkedChildren="开启" unCheckedChildren="关闭" />
          </Form.Item>
        </Card>

        <Card title="Step 4 类目" size="small" style={{ marginBottom: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(180px, 1fr))', gap: 16 }}>
            <Form.Item label="缺竞品 ASIN 策略" name="step4_missing_asin_policy" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'manual_review', label: '待人工处理' },
                  { value: 'fail', label: '标记失败' },
                  { value: 'continue', label: '继续执行' },
                ]}
              />
            </Form.Item>
            <Form.Item label="类目获取失败策略" name="step4_category_missing_policy" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'manual_review', label: '待人工处理' },
                  { value: 'fail', label: '标记失败' },
                  { value: 'continue', label: '继续执行' },
                ]}
              />
            </Form.Item>
            <Form.Item label="允许使用已有类目" name="step4_allow_existing_category" valuePropName="checked">
              <Switch checkedChildren="允许" unCheckedChildren="关闭" />
            </Form.Item>
          </div>
        </Card>

        <Card title="Step 5 Listing" size="small" style={{ marginBottom: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(180px, 1fr))', gap: 16 }}>
            <Form.Item label="LLM 温度" name="step5_llm_temperature" rules={[{ required: true }]}>
              <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="最大输出 Tokens" name="step5_llm_max_tokens" rules={[{ required: true }]}>
              <InputNumber min={500} max={8000} step={100} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="标题字符上限" name="step5_title_max_chars" rules={[{ required: true }]}>
              <InputNumber min={80} max={250} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="五点字符上限" name="step5_bullet_max_chars" rules={[{ required: true }]}>
              <InputNumber min={100} max={1000} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="Search Terms 字节上限" name="step5_search_terms_max_bytes" rules={[{ required: true }]}>
              <InputNumber min={50} max={500} style={{ width: '100%' }} />
            </Form.Item>
          </div>
        </Card>

        <Card title="基础配置" size="small" style={{ marginBottom: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 280px) 1fr', gap: 16 }}>
            <Form.Item label="默认品牌" name="default_brand" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item label="商品目录" name="product_base_dir" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
          </div>
        </Card>

        <Card title="模型与图片参数" size="small" style={{ marginBottom: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(180px, 1fr))', gap: 16 }}>
            <Form.Item label="LLM 模型" name="llm_model" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item label="VLM 模型" name="vlm_model" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item label="VLM 使用 LLM 通道" name="vlm_use_llm_api" valuePropName="checked">
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
            <Form.Item label="图片模型" name="gpt_image_model" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item label="图片使用 LLM 通道" name="gpt_image_use_llm_api" valuePropName="checked">
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
            <Form.Item label="图片宽度" name="aplus_image_width" rules={[{ required: true }]}>
              <InputNumber min={320} max={4096} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="图片高度" name="aplus_image_height" rules={[{ required: true }]}>
              <InputNumber min={320} max={4096} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="JPEG 质量" name="aplus_image_jpeg_quality" rules={[{ required: true }]}>
              <InputNumber min={40} max={100} style={{ width: '100%' }} />
            </Form.Item>
	            <Form.Item label="图片 API 重试次数" name="aplus_image_api_retries" rules={[{ required: true }]}>
	              <InputNumber min={0} max={10} style={{ width: '100%' }} />
	            </Form.Item>
	            <Form.Item label="A+ 出图覆盖策略" name="aplus_image_overwrite_policy" rules={[{ required: true }]}>
	              <Select
	                options={[
	                  { value: 'skip_success', label: '跳过已成功，只补缺失/失败' },
	                  { value: 'overwrite_all', label: '全部重新生成' },
	                ]}
	              />
	            </Form.Item>
	          </div>
	        </Card>
      </Form>

      <Card
        title="当前外部服务状态"
        size="small"
        extra={<Button icon={<ReloadOutlined />} onClick={fetchConfig}>刷新</Button>}
      >
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="LLM API">{yesNo(config.llm_api_configured)}</Descriptions.Item>
          <Descriptions.Item label="VLM API">{yesNo(config.vlm_api_configured)}</Descriptions.Item>
          <Descriptions.Item label="图片 API">{yesNo(config.gpt_image_api_configured)}</Descriptions.Item>
          <Descriptions.Item label="SellerSprite">{yesNo(config.sellersprite_configured)}</Descriptions.Item>
          <Descriptions.Item label="图片通道">{config.gpt_image_api_provider}</Descriptions.Item>
          <Descriptions.Item label="版本">{config.version}</Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
};

export default ConfigPage;
