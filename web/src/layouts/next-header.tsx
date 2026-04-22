import { useFetchAppConf } from '@/hooks/logic-hooks';
import { useNavigateWithFromState } from '@/hooks/route-hook';
import { theme } from 'antd';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import Toolbar from './components/right-toolbar';

type HeaderProps = {
  collapsed?: boolean;
  onToggleSidebar?: () => void;
};

export function Header({ collapsed = false, onToggleSidebar }: HeaderProps) {
  const {
    token: { colorBgContainer },
  } = theme.useToken();
  const navigate = useNavigateWithFromState();
  const appConf = useFetchAppConf();

  return (
    <header
      className="fixed inset-x-0 top-0 z-50 flex h-[60px] items-center justify-between border-b border-white/10 px-6"
      style={{ background: colorBgContainer }}
    >
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onToggleSidebar}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-text-secondary transition-colors hover:bg-black/5 hover:text-text-primary dark:hover:bg-white/10"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </button>

        <button
          type="button"
          onClick={() => navigate('/')}
          className="flex items-center gap-3"
        >
          <img src="/logo.svg" alt="logo" className="h-9 w-9" />
          <div className="text-left">
            <div className="text-sm font-semibold text-text-primary">
              {appConf.appName || 'Smart AI Agent Factory'}
            </div>
            <div className="text-xs text-text-secondary">Workspace</div>
          </div>
        </button>
      </div>

      <Toolbar />
    </header>
  );
}
