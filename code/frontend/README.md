# Aristotle 408 前端

基于 Vue 3、TypeScript 和 Vite 的学习端界面。

## 界面与组件选型

使用 Naive UI：原生 Vue 3 / TypeScript，按需导入按钮、表单、标签、进度、
弹窗和确认框，使用统一绿色主题；Lucide Vue 提供图标。页面样式使用本地系统字体，
无需访问外部字体服务。

页面包含学习概览、知识地图、我的资料、学习记录。3 道栈操作样例题支持
选择、提交、解析和关卡反馈；同题重复提交被当前关卡状态阻止，重复练习会保留历史，
不同题目证据统计按题目 ID 去重。文字讲义支持保存、确认/取消关联和删除。
记录与讲义存储在当前浏览器 localStorage，清除浏览器数据会丢失，不提供账号隔离。

当前是前端演示，样例题不是正式审核题库。认证、PDF 抽取、LLM、正式诊断、
推荐策略、内容审核与服务端持久化尚未实现。知识地图仅展示先修关系示例。
参考网址 https://praxen.dyd.center/ 在开发时只能取得迁移进度过渡页，
未能核实正式页面；当前设计依据项目需求独立完成，待参考站可访问后再对齐。

## 本地开发

```bash
npm install
npm run dev
```

开发服务器默认运行在 `http://localhost:5173`。

## 生产构建

```bash
npm run build
npm run preview
```

`npm run build` 会先执行 Vue TypeScript 类型检查，再生成 `dist/` 构建产物。
