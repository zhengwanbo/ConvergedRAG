import { ReactComponent as HomeIcon } from '@/assets/svg/home-icon/datasets.svg';
import { ReactComponent as KnowledgeBaseIcon } from '@/assets/svg/knowledge-base.svg';
import { ReactComponent as ChatIcon } from '@/assets/svg/chat-app-cube.svg';
import { ReactComponent as SearchIcon } from '@/assets/svg/navigation-pointer.svg';
import { ReactComponent as AgentIcon } from '@/assets/svg/graph.svg';
import { ReactComponent as FileIcon } from '@/assets/svg/file-management.svg';
import { ReactComponent as SystemIcon } from '@/assets/svg/model-providers.svg';
import { ReactComponent as UserIcon } from '@/assets/svg/profile.svg';
import { useTranslate } from '@/hooks/common-hooks';
import { useNavigateWithFromState } from '@/hooks/route-hook';
import { Layout, Menu, MenuProps } from 'antd';
import { useLocation } from 'umi';
import { useState } from 'react';
import { CpuIcon } from 'lucide-react';

const { Sider } = Layout;

type MenuItem = Required<MenuProps>['items'][number];

interface SidebarProps {
  onCollapseChange?: (collapsed: boolean) => void;
}

const Sidebar: React.FC<SidebarProps> = ({ onCollapseChange }) => {
  const navigate = useNavigateWithFromState();
  const { pathname } = useLocation();
  const { t } = useTranslate('header');
  const [collapsed, setCollapsed] = useState(false);

  const handleCollapse = (value: boolean) => {
    setCollapsed(value);
    onCollapseChange?.(value);
  };

  const getItem = (
    label: React.ReactNode,
    key: React.Key,
    icon?: React.ReactNode,
    children?: MenuItem[],
    type?: 'group',
  ): MenuItem => {
    return {
      key,
      icon,
      children,
      label,
      type,
    } as MenuItem;
  };

  // 主菜单项 - 根据任务要求，只保留首页
  const mainMenuItems: MenuItem[] = [
    getItem(t('knowledgeBase'), '/datasets', <KnowledgeBaseIcon />),
    getItem(t('chat'), '/next-chats', <ChatIcon />),
    getItem(t('search'), '/next-searches', <SearchIcon />),
    getItem(t('flow'), '/agents', <CpuIcon />),
    getItem(t('fileManager'), '/files', <FileIcon />),
  ];

  // 系统管理子菜单项
  const systemManagementItems: MenuItem[] = [
    getItem(t('sidebar.dataSource'), '/user-setting/data-source'),
    getItem(t('sidebar.modelProvider'), '/user-setting/model'),
    getItem(t('sidebar.mcp'), '/user-setting/mcp'),
    getItem(t('sidebar.api'), '/user-setting/api'),
    getItem(t('sidebar.sysinfo'), '/user-setting/system'),
  ];

  // 用户管理子菜单项
  const userManagementItems: MenuItem[] = [
    getItem(t('sidebar.profile'), '/user-setting/profile'),
    getItem(t('sidebar.teamManagement'), '/user-setting/team'),
  ];

  const items: MenuItem[] = [
    ...mainMenuItems,
    getItem(t('sidebar.systemManagement'), '', <SystemIcon />, systemManagementItems),
    getItem(t('sidebar.userManagement'), '', <UserIcon />, userManagementItems),
  ];

  const handleMenuClick: MenuProps['onClick'] = (e) => {
    if (e.key.startsWith('/')) {
      navigate(e.key);
    }
  };

  // 根据当前路径确定选中的菜单项
  const getSelectedKeys = () => {
    const keys: string[] = [];
    
    // 检查主菜单项
    mainMenuItems.forEach(item => {
      if (item && typeof item === 'object' && 'key' in item) {
        const key = item.key as string;
        if (pathname.startsWith(key) && key !== '/') {
          keys.push(key);
        }
      }
    });

    // 检查首页
    if (pathname === '/' || pathname === '/home') {
      keys.push('/');
    }

    // 检查系统管理子菜单
    systemManagementItems.forEach(item => {
      if (item && typeof item === 'object' && 'key' in item) {
        const key = item.key as string;
        if (pathname.startsWith(key)) {
          keys.push('system');
          keys.push(key);
        }
      }
    });

    // 检查用户管理子菜单
    userManagementItems.forEach(item => {
      if (item && typeof item === 'object' && 'key' in item) {
        const key = item.key as string;
        if (pathname.startsWith(key)) {
          keys.push('user');
          keys.push(key);
        }
      }
    });

    return keys;
  };

  return (
    <Sider
      collapsible
      collapsed={collapsed}
      onCollapse={handleCollapse}
      width={240}
      style={{
        overflow: 'auto',
        height: 'calc(100vh - 60px)',
        position: 'fixed',
        left: 0,
        top: 61,
        bottom: 0,
        background: 'var(--bg-base, #161618)',
        borderRight: '1px solid var(--border-default, rgba(255, 255, 255, 0.2))',
        zIndex: 999,
      }}
    >
      <Menu
        mode="inline"
        selectedKeys={getSelectedKeys()}
        defaultOpenKeys={['system', 'user']}
        items={items}
        onClick={handleMenuClick}
        style={{ borderRight: 'none' }}
      />
    </Sider>
  );
};

export default Sidebar;
