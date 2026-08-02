import { useEffect, useState } from 'react';
import { EditOutlined, ImportOutlined, ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Form, Input, Modal, Space, Table, Tag, Tooltip, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { getLocalEnvConfig, importLocalEnvConfig, updateLocalEnvValue } from '../api';
import type { LocalEnvItem } from '../api';
import { runMutationWithUX } from '../api/mutationRunner';

const { Text } = Typography;

const ENV_LABELS: Record<string, string> = {
  LLM_API_BASE: 'LLM 接口地址',
  LLM_API_KEY: 'LLM API 密钥',
  LLM_MODEL: 'LLM 模型',
  VLM_API_BASE: '视觉模型接口地址',
  VLM_API_KEY: '视觉模型 API 密钥',
  VLM_MODEL: '视觉模型',
  VLM_USE_LLM_API: '视觉模型复用 LLM 通道',
  GPT_IMAGE_API_BASE: '图片生成接口地址',
  GPT_IMAGE_API_KEY: '图片生成 API 密钥',
  GPT_IMAGE_MODEL: '图片生成模型',
  GPT_IMAGE_USE_LLM_API: '图片生成复用 LLM 通道',
  APLUS_IMAGE_API_MODE: 'A+ 图片接口模式',
  APLUS_IMAGE_GENERATION_QUALITY: 'A+ 图片生成质量',
  APLUS_IMAGE_WIDTH: 'A+ 图片宽度',
  APLUS_IMAGE_HEIGHT: 'A+ 图片高度',
  APLUS_IMAGE_ASPECT_RATIO: 'A+ 图片比例',
  APLUS_IMAGE_MAX_BYTES: 'A+ 图片最大文件大小',
  APLUS_IMAGE_JPEG_QUALITY: 'A+ 图片 JPEG 质量',
  APLUS_IMAGE_MIN_JPEG_QUALITY: 'A+ 图片最低 JPEG 质量',
  APLUS_IMAGE_API_RETRIES: '图片接口重试次数',
  APLUS_IMAGE_OVERWRITE_POLICY: 'A+ 图片覆盖策略',
  APLUS_CONCURRENCY: 'A+ 图片生成并发数',
  AUTO_APLUS_AFTER_EXPORT_READY: 'Listing 完成后自动生成 A+',
  SELLERSPRITE_TOKEN: '卖家精灵访问令牌',
  SELLERSPRITE_OPENAPI_SECRET_KEY: '卖家精灵开放平台密钥',
  OSS_ACCESS_KEY_ID: 'OSS 访问密钥 ID',
  OSS_ACCESS_KEY_SECRET: 'OSS 访问密钥 Secret',
  OSS_BUCKET: 'OSS 存储桶',
  OSS_ENDPOINT: 'OSS 服务地址',
  OSS_UPLOAD_PREFIX: 'OSS 上传目录前缀',
  OSS_SIGNED_URL_EXPIRES_SECONDS: 'OSS 签名链接有效期',
  OSS_UPLOAD_TIMEOUT_SECONDS: 'OSS 上传超时秒数',
  DEFAULT_BRAND: '默认品牌',
  PRODUCT_BASE_DIR: '商品素材目录',
  PIPELINE_MAX_CONCURRENCY: '商品流程最大并发数',
  BROWSER_WORKFLOW_CONCURRENCY: '浏览器流程并发数',
  BULK_START_MAX_TASKS: '批量启动任务上限',
  POLL_INTERVAL: '状态轮询间隔秒数',
  STEP3_4_PARALLEL: '步骤 3 与 4 并行执行',
  STEP1_EXTRACT_RETRY_ATTEMPTS: '采集提取重试次数',
  STEP1_EXTRACT_RETRY_DELAY_SECONDS: '采集提取重试间隔秒数',
  STEP1_DOWNLOAD_TIMEOUT_SECONDS: '素材下载超时秒数',
  STEP1_AFTER_READY_WAIT_SECONDS: '采集就绪后等待秒数',
  STEP1_MATERIAL_DOWNLOAD_MODE: '素材包下载方式',
  STEP1_MATERIAL_PACKAGE_PRIORITY: '素材包优先级',
  STEP1_PRICE_MISSING_POLICY: '缺失价格处理方式',
  STEP1_MATERIAL_MISSING_POLICY: '缺失素材处理方式',
  STEP1_ALLOW_EXISTING_MATERIALS: '允许使用已有素材',
  STEP3_MANUAL_LOGIN_ON_AUTH_FAILURE: '认证失败时允许人工登录',
  STEP4_MISSING_ASIN_POLICY: '缺失 ASIN 处理方式',
  STEP4_CATEGORY_MISSING_POLICY: '缺失类目处理方式',
  STEP4_ALLOW_EXISTING_CATEGORY: '允许使用已有类目',
  STEP5_LLM_TEMPERATURE: '文案生成随机度',
  STEP5_LLM_MAX_TOKENS: '文案最大输出长度',
  STEP5_TITLE_MAX_CHARS: '标题最大字符数',
  STEP5_PRODUCT_HIGHLIGHT_MAX_CHARS: '标题补充最大字符数',
  STEP5_BULLET_MAX_CHARS: '五点描述最大字符数',
  STEP5_SEARCH_TERMS_MAX_BYTES: '搜索词最大字节数',
  PRICING_COMMISSION_RATE: 'Amazon 佣金比例',
  PRICING_RETURN_RATE: '实际退货率',
  PRICING_INSURANCE_RATE: '退货保险费率（按货值）',
  PRICING_INSURANCE_PAYOUT_RATE: '保险赔付比例（仅货值）',
  PRICING_RETURN_MANAGEMENT_FEE_RATE: '退货管理费比例（佣金的比例）',
  PRICING_RETURN_MANAGEMENT_FEE_CAP: '退货管理费封顶（美元）',
  PRICING_ADVERTISING_COST: '广告预留（美元/单）',
  PRICING_TARGET_MARGIN_RATE: '目标利润率',
  PRICING_MIN_PROFIT: '最低利润',
  PROJECT_NAME: '项目名称',
  VERSION: '版本号',
  DEBUG: '调试模式',
  DATA_DIR: '数据目录',
  DATABASE_URL: '数据库连接地址',
  BACKEND_PORT: '后端服务端口',
  FRONTEND_PORT: '前端服务端口',
  CHROME_LOCK_TIMEOUT: '浏览器锁超时秒数',
  PRICE_QUANTITY_TEMPLATE_PATH: '价格库存模板路径',
  GIGA_SYNC_PAGE_SIZE: 'GIGA 同步每页数量',
};

const LocalEnvConfigTable = () => {
  const [items, setItems] = useState<LocalEnvItem[]>([]);
  const [envFile, setEnvFile] = useState('backend/.env');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<LocalEnvItem | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importContent, setImportContent] = useState('');
  const [form] = Form.useForm<{ value: string }>();

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await getLocalEnvConfig();
      setItems(data.items);
      setEnvFile(data.env_file);
    } catch {
      message.error('本地配置加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const openEdit = (item: LocalEnvItem) => {
    setEditing(item);
    form.setFieldsValue({ value: item.is_secret ? '' : item.value });
  };

  const saveValue = async () => {
    if (!editing) return;
    const values = await form.validateFields();
    if (editing.is_secret && !values.value) {
      message.error('请重新输入密钥值');
      return;
    }
    setSaving(true);
    await runMutationWithUX(
      'updateLocalEnvValue|frontend/src/components/LocalEnvConfigTable.tsx|saveValue',
      async (metadata) => {
        await updateLocalEnvValue(editing.key, values.value, metadata);
        message.success('本地配置已保存，重启后生效');
        setEditing(null);
        await load();
      },
      {
        errorFallback: '保存本地配置失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setSaving(false),
      },
    ).catch(() => undefined);
  };

  const importConfig = async () => {
    if (!importContent.trim()) {
      message.error('请输入配置文件内容');
      return;
    }
    setSaving(true);
    await runMutationWithUX(
      'importLocalEnvConfig|frontend/src/components/LocalEnvConfigTable.tsx|importConfig',
      async (metadata) => {
        const { data } = await importLocalEnvConfig(importContent, metadata);
        message.success(`已导入 ${data.imported_count} 项配置，重启后生效`);
        setImportOpen(false);
        setImportContent('');
        await load();
      },
      {
        errorFallback: '导入本地配置失败',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setSaving(false),
      },
    ).catch(() => undefined);
  };

  const columns: ColumnsType<LocalEnvItem> = [
    {
      title: '配置项',
      width: 210,
      render: (_, record) => ENV_LABELS[record.key] || record.key,
    },
    { title: '变量名', dataIndex: 'key', width: 320, render: (value) => <Text code>{value}</Text> },
    {
      title: '当前值',
      dataIndex: 'value',
      render: (value, record) => record.is_secret
        ? <Tag color={record.has_value ? 'gold' : 'default'}>{record.has_value ? '已配置（隐藏）' : '未配置'}</Tag>
        : <Text style={{ wordBreak: 'break-all' }}>{value || <Text type="secondary">空</Text>}</Text>,
    },
    { title: '类型', width: 100, render: (_, record) => record.is_secret ? <Tag>敏感</Tag> : <Tag color="blue">普通</Tag> },
    {
      title: '操作',
      width: 88,
      render: (_, record) => (
        <Tooltip title="编辑本地配置">
          <Button type="text" icon={<EditOutlined />} onClick={() => openEdit(record)} aria-label={`编辑 ${record.key}`} />
        </Tooltip>
      ),
    },
  ];

  const sections = [...new Set(items.map((item) => item.section))];

  return (
    <>
      <Alert
        showIcon
        type="info"
        style={{ marginBottom: 16 }}
        message="本地环境变量"
        description={<span>配置写入 <Text code>{envFile}</Text>，敏感值不会返回到页面；保存或导入后需重启服务才会生效。</span>}
      />
      <Space style={{ marginBottom: 16 }} wrap>
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>
        <Button type="primary" icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入配置文件</Button>
      </Space>
      {sections.map((section) => {
        const sectionItems = items.filter((item) => item.section === section);
        return (
          <Card key={section} title={`${section} (${sectionItems.length})`} size="small" style={{ marginBottom: 16 }}>
            <Table
              rowKey="key"
              loading={loading}
              columns={columns}
              dataSource={sectionItems}
              pagination={false}
              size="small"
              scroll={{ x: 760 }}
            />
          </Card>
        );
      })}
      <Modal
        title="编辑本地环境变量"
        open={Boolean(editing)}
        onCancel={() => setEditing(null)}
        onOk={() => void saveValue()}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item label="变量名"><Input value={editing?.key} disabled /></Form.Item>
          <Form.Item name="value" label="值" rules={[{ required: !editing?.is_secret, message: '请输入配置值' }]}>
            {editing?.is_secret ? (
              <Input.Password placeholder="当前值已隐藏，输入新值覆盖" />
            ) : (
              <Input placeholder="输入配置值" />
            )}
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="导入本地配置文件"
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        onOk={() => void importConfig()}
        confirmLoading={saving}
        okText="导入并替换"
        destroyOnClose
        width={760}
      >
        <Alert type="warning" showIcon message="导入会替换整个 backend/.env 文件" style={{ marginBottom: 16 }} />
        <Input.TextArea
          value={importContent}
          onChange={(event) => setImportContent(event.target.value)}
          placeholder={'KEY=value\nANOTHER_KEY=value'}
          autoSize={{ minRows: 14, maxRows: 22 }}
          spellCheck={false}
        />
      </Modal>
    </>
  );
};

export default LocalEnvConfigTable;
