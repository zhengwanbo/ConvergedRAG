# 修改记录 2026-04-21

## 背景

本文档记录 2026-04-21 针对前端合并、布局改造、管理用户功能接入，以及管理端接口并入主服务的修改内容。

本轮工作的核心目标是：

- 以最新前端代码为基底，保留本地版本的页面布局风格；
- 将用户设置、管理用户等页面统一纳入主布局；
- 把原来依赖独立 `admin` 服务的用户管理能力迁入主服务；
- 调整创建用户表单和管理入口，使管理员可以在主站内完成用户增删改查中的主要操作。

## 修改内容

### 1. 完成前端目录切换与主布局接管

本轮先将原本基于上游最新代码的目录切换为正式 `web`，旧本地前端保留为 `web.bak`，然后围绕新 `web` 继续改造。

主布局层的改动包括：

- 将 `web/src/layouts/next.tsx` 改造成“固定顶部 + 左侧主菜单 + 右侧内容区”的整体框架；
- 重写 `web/src/layouts/next-header.tsx`，保留品牌区和右侧工具区；
- 新增并迭代 `web/src/layouts/components/sidebar/index.tsx` 与样式文件，作为整个主站统一的左侧导航；
- 首页 `web/src/pages/home/index.tsx` 去掉上游 banner，向本地版本的展示风格靠拢。

同时修复了若干构建期样式问题：

- 新增的侧边栏和右上角工具栏样式改为 `.module.less`，兼容 Vite 的 CSS Modules 处理；
- `tailwind.config.js` 改为 ESM 写法，以适配当前 `web/package.json` 中 `"type": "module"` 的工程配置；
- `vite.config.ts` 的开发代理同步调整，保证本地开发与实际请求路径一致。

### 2. 重构左侧导航结构与交互

围绕新的左侧主菜单，完成了以下调整：

- 在主菜单最前面新增“首页”入口，点击行为与顶部 logo 保持一致；
- 保留“知识库、聊天、搜索、智能体、记忆、文件管理”等主功能入口；
- 增加“系统设置”“用户管理”两个分组，并支持展开/收起；
- “系统设置”下挂：
  - 数据源
  - 模型提供商
  - MCP
  - API
- “用户管理”下挂：
  - 概要
  - 团队
  - 管理用户
- 左侧底部新增“登出”按钮，复用现有退出登录逻辑；
- 修复亮色主题下菜单文字和分组标题不可见的问题，使其统一跟随主题变量；
- 为“系统设置”“用户管理”补上图标，并统一字号、图标尺寸和行高。

### 3. 将用户设置页面并回主布局

为满足“点击左侧菜单后仅右侧内容变化，左侧菜单不切换”的要求，调整了用户设置相关路由和页面结构：

- `web/src/routes.tsx` 中将 `/user-setting/*` 整组路由挂回主布局 `@/layouts/next`；
- 修复 React Router 嵌套路由中绝对路径报错，全部改为相对路径；
- `web/src/pages/user-setting/index.tsx` 去掉原有独立的内部侧栏，只保留页面头部和右侧 `Outlet` 区域。

这一步的结果是：

- 点击“数据源、模型提供商、MCP、API、概要、团队、管理用户”后，左侧主菜单保持不动；
- 只在右侧内容区切换对应页面。

### 4. 补齐中英文导航文案与品牌替换

本轮对主界面中新增或硬编码的文案做了收口，主要处理了两类内容：

1. 品牌名称统一：
- `web/src/conf.json`
- `web/src/layouts/next-header.tsx`

主界面品牌由原先的 `RAGFlow` 改为：

- `Smart AI Agent Factory`

2. 左侧菜单与设置页新增文案补齐中英文资源：

- `系统设置 / System settings`
- `用户管理 / User management`
- `概要 / Overview`
- `管理用户 / Manage users`
- `登出 / Log out`

涉及：

- `web/src/locales/zh.ts`
- `web/src/locales/en.ts`

### 5. 新增“管理用户”菜单，并复用现有管理员用户管理能力

为避免重写一套用户管理页面，当前采用“复用原 admin 用户管理页”的方式接入主站：

- 在左侧“用户管理”下新增“管理用户”；
- 新增页面 `web/src/pages/user-setting/manage-users/index.tsx`；
- 仅当当前用户 `is_superuser` 为真时显示“管理用户”菜单；
- 非管理员访问该页面时，显示无权限提示；
- `web/src/pages/admin/users.tsx` 增强为可复用组件，支持在主站中直接作为内容页渲染。

当前主站中的“管理用户”已经支持以下操作：

- 查看用户列表；
- 新增用户；
- 删除用户；
- 修改密码；
- 启用 / 禁用用户；
- 设置 / 取消 superuser；
- 企业版场景下修改角色。

### 6. 将原 `/admin` 用户管理接口并入 `ragflow_server`

为解决“管理用户页面调用 admin 接口时跳去 `/admin` 单独登录”的问题，本轮将原独立 admin 服务中的核心接口迁入主服务。

主要改动如下：

- 在 `api/apps/__init__.py` 中扩展自动注册逻辑，支持页面文件声明自定义 `url_prefix`；
- 新增 `api/apps/admin_app.py`，将原 `admin/server/routes.py` 中的主要接口改写为 Quart 路由并接入主服务；
- 新前缀统一改为：
  - `/admin/v1/*`
- `admin/server/services.py` 做了导入兼容修正，以便被主服务直接复用；
- 前端 `web/src/utils/api.ts` 中，所有原先指向 `/api/v1/admin/*` 的管理接口，统一改为 `/admin/v1/*`；
- `web/src/services/admin-service.ts` 中，401 时不再一律强制跳转 `/admin`，而是根据当前所在页面决定回主登录页还是 admin 登录页。

当前已经并入主服务并可供“管理用户”页面使用的接口包括：

- 登录、登出、认证检查；
- 用户列表、创建用户、删除用户；
- 修改用户密码；
- 启用 / 禁用用户；
- 设置 / 取消管理员；
- 用户详情、用户数据集、用户智能体；
- 服务状态；
- 角色、变量、配置、环境信息；
- sandbox 配置相关接口。

这意味着在主站场景下，不再强依赖单独启动 `admin/server/admin_server.py` 才能使用用户管理。

### 7. 扩展创建用户表单，支持昵称、语言和时区

针对“创建用户时需要像注册页一样填写更多基础信息”的需求，本轮继续补齐了创建链路：

- 后端 `api/apps/admin_app.py` 的创建用户接口新增接收：
  - `nickname`
  - `language`
  - `timezone`
- `admin/server/services.py` 中 `UserMgr.create_user()` 同步支持上述字段；
- `web/src/services/admin-service.ts` 的 `createUser()` 入参扩展为对象形式，携带完整字段；
- `web/src/pages/admin/users.tsx` 中创建用户 mutation 同步传递上述字段；
- `web/src/pages/admin/forms/user-form.tsx` 中创建用户表单新增：
  - 昵称（必填）
  - 语言
  - 时区

默认值策略：

- `nickname` 必填；
- `language` 按浏览器语言自动映射；
- `timezone` 按浏览器时区自动匹配现有 `TimezoneList`；
- 如无法匹配，则回退到默认时区字符串。

表单字段文案和校验信息也补入了中英文资源。

## 涉及文件

- `api/apps/__init__.py`
- `api/apps/admin_app.py`
- `admin/server/services.py`
- `docs/change_record_2026-04-21.md`
- `web/vite.config.ts`
- `web/tailwind.config.js`
- `web/src/conf.json`
- `web/src/layouts/next.tsx`
- `web/src/layouts/next-header.tsx`
- `web/src/layouts/components/sidebar/index.tsx`
- `web/src/layouts/components/sidebar/index.module.less`
- `web/src/layouts/components/right-toolbar/index.tsx`
- `web/src/layouts/components/right-toolbar/index.module.less`
- `web/src/pages/home/index.tsx`
- `web/src/pages/user-setting/index.tsx`
- `web/src/pages/user-setting/manage-users/index.tsx`
- `web/src/pages/admin/users.tsx`
- `web/src/pages/admin/forms/user-form.tsx`
- `web/src/routes.tsx`
- `web/src/services/admin-service.ts`
- `web/src/utils/api.ts`
- `web/src/locales/en.ts`
- `web/src/locales/zh.ts`

## 验证情况

已完成的验证：

- `python -m py_compile api/apps/admin_app.py`
- `python -m py_compile admin/server/services.py`
- 多次执行 `npm run build`

验证结果：

- 前端构建通过；
- 新增的 Quart admin 路由文件通过 Python 语法校验；
- 样式和路由层改动未再引入新的构建错误。

未完成的验证：

- 未执行主服务实际启动后的 `/admin/v1/*` 接口联调；
- 未执行浏览器级完整回归测试；
- 未验证旧独立 `admin_server.py` 停止后，所有管理功能是否都已完整迁移；
- 未对 roles / variables / sandbox 等非“管理用户”主链路接口逐项做功能验证。

## 当前结果

截至目前，今天的改动已经完成以下阶段性结果：

- 新前端目录已切换为最新版本并接管主站布局；
- 左侧主菜单结构、主题、图标、分组交互和多语言文案已完成一轮整理；
- 用户设置页已经并回主布局，点击设置菜单时不会再切换左侧导航；
- “管理用户”已作为主站菜单正式接入；
- 管理用户页已经能在主站中复用原管理员用户管理能力；
- 原独立 admin 用户管理接口已经迁入 `ragflow_server`，前缀调整为 `/admin/v1/*`；
- 创建用户表单已支持昵称、语言和时区，并带浏览器默认值策略。

当前建议下一步重点关注：

- 启动 `api/ragflow_server.py` 后，对 `/admin/v1/users`、创建用户、禁用用户、重置密码等关键接口做一轮真实联调；
- 确认前端“管理用户”页面在不启动独立 `admin_server.py` 的情况下可以完整工作；
- 再决定是否继续迁移 `/admin` 体系下的剩余功能，或进一步隐藏内部管理接口。
