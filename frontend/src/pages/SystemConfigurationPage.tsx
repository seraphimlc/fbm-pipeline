import { Tabs, Typography } from 'antd';
import ConfigPage from './ConfigPage';
import LocalEnvConfigTable from '../components/LocalEnvConfigTable';

const { Title } = Typography;

const SystemConfigurationPage = () => (
  <div>
    <Title level={4}>系统配置</Title>
    <Tabs
      items={[
        { key: 'runtime', label: '运行配置', children: <ConfigPage /> },
        { key: 'local-env', label: '本地环境变量', children: <LocalEnvConfigTable /> },
      ]}
    />
  </div>
);

export default SystemConfigurationPage;
